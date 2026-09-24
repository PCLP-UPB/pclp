from __future__ import annotations

import html as htmlmod
import mimetypes
import re

from django.conf import settings
from django.contrib import messages
from django.http import FileResponse, Http404, HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.utils.safestring import mark_safe
from django.views.decorators.http import require_POST

from . import content as C
from .models import ConceptEdit, RelationEdit
from .render import render_markdownish, rendered_unit


def _author_only(fn):
    def wrap(request, *a, **kw):
        if not settings.PCLP_AUTHOR:
            return HttpResponseForbidden("Editarea este disponibilă doar în modul autor (PCLP_AUTHOR=1).")
        return fn(request, *a, **kw)
    return wrap


def by_level(cs):
    groups = {1: [], 2: [], 3: []}
    for c in cs:
        groups.setdefault(c.get("level") or 2, []).append(c)
    return [(lvl, C.LEVELS.get(lvl, lvl), groups[lvl]) for lvl in sorted(groups) if groups[lvl]]


# ---------------------------------------------------------------------------
# explorare, capitol, cititor

def explore(request):
    tab = request.GET.get("tab", "capitole")
    cs = sorted(C.concepts().values(), key=lambda c: C.fold(c["label"]).lstrip("#%-_"))
    letters: dict[str, list] = {}
    for c in cs:
        first = C.fold(c["label"]).lstrip("#%-_.")[:1].upper() or "#"
        if not first.isalpha():
            first = "#"
        letters.setdefault(first, []).append(c)
    outline = C.outline()
    cmap = C.concepts()

    def tree(parent):
        return [{"c": cmap[x], "kids": tree(x)} for x in outline.get(parent, []) if x in cmap]

    roots_by_unit = {}
    for node in tree(None):
        roots_by_unit.setdefault(node["c"].get("unit") or "-", []).append(node)
    unit_trees = [(u, roots_by_unit.get(u["id"], [])) for u in C.units() if roots_by_unit.get(u["id"])]
    chapters = [{"u": u, "n": len(C.unit_concepts(u["id"])), "base": [c for c in C.unit_concepts(u["id"]) if c["level"] == 1][:8]} for u in C.units()]
    return render(request, "glosar/explore.html", {
        "tab": tab, "letters": sorted(letters.items()), "unit_trees": unit_trees, "chapters": chapters, "n": len(cs),
    })


def chapter(request, uid):
    u = C.unit(uid)
    if not u:
        raise Http404
    cs = C.unit_concepts(uid)
    return render(request, "glosar/chapter.html", {
        "u": u, "sections": [s for s in C.sections(uid) if s["level"] <= 3], "groups": by_level(cs), "concepts": cs,
    })


def reader(request, uid):
    u = C.unit(uid)
    if not u:
        raise Http404
    blocks, sec_terms = rendered_unit(uid)
    secs = C.sections(uid)
    cs = C.concepts()
    sec_terms_data = {s: [{"id": x, "label": cs[x]["label"], "level": cs[x]["level"]} for x in ids if x in cs]
                      for s, ids in sec_terms.items()}
    units = C.units()
    idx = next(k for k, x in enumerate(units) if x["id"] == uid)
    same_kind = [x for x in units if x["kind"] == u["kind"]]
    k2 = next(k for k, x in enumerate(same_kind) if x["id"] == uid)
    probs = C.problems(uid, "curat") if u["kind"] == "lab" else []
    return render(request, "glosar/reader.html", {
        "u": u, "blocks": blocks, "sections": secs, "sec_terms": sec_terms_data,
        "prev": same_kind[k2 - 1] if k2 > 0 else None, "next": same_kind[k2 + 1] if k2 + 1 < len(same_kind) else None,
        "units": units, "problems": probs, "idx": idx, "open_term": request.GET.get("t", ""),
    })


def media(request, name):
    if not re.fullmatch(r"[0-9a-f]{12}\.\w{2,4}", name):
        raise Http404
    path = settings.PCLP_CONTENT / "media" / name
    if not path.exists():
        raise Http404
    resp = FileResponse(open(path, "rb"), content_type=mimetypes.guess_type(name)[0] or "application/octet-stream")
    resp["Cache-Control"] = "max-age=604800"
    return resp


# ---------------------------------------------------------------------------
# termen

def highlight_sentence(sentence: str, cid: str) -> str:
    esc = htmlmod.escape(sentence)
    ms = C.matcher().find(sentence, in_code=True, only={cid})
    if not ms:
        return mark_safe(esc)
    out, pos = [], 0
    for m in ms:
        out.append(htmlmod.escape(sentence[pos:m.start]))
        out.append(f"<mark>{htmlmod.escape(sentence[m.start:m.end])}</mark>")
        pos = m.end
    out.append(htmlmod.escape(sentence[pos:]))
    return mark_safe("".join(out))


def term_context(cid: str) -> dict:
    c = C.concept(cid)
    if not c:
        raise Http404
    defs = C.definitions(cid)
    for key in ("first", "extended"):
        if defs[key]:
            defs[key]["html"] = highlight_sentence(defs[key]["sentence"], cid)
            defs[key]["unit_obj"] = C.unit(defs[key]["unit"])
    for d in defs["other"]:
        d["html"] = highlight_sentence(d["sentence"], cid)
        d["unit_obj"] = C.unit(d["unit"])
    rels = C.relations(cid)
    visible = [r for r in rels if not r["hidden"]]
    related = {}
    for r in visible:
        related[r["other"]["id"]] = r["other"]
    for p in C.prerequisites(cid):
        related[p["id"]] = p
    mentions = [dict(m, u=C.unit(m["unit"])) for m in C.mentions(cid)]
    man = C.man_page(c["man"]) if c.get("man") else None
    if not man and c["kind"] in ("funcție de bibliotecă", "fișier antet"):
        man = C.man_for_name(c["label"])
    parent = C.outline_parent(cid)
    kids = [C.concept(x) for x in C.outline().get(cid, [])]
    probs = C.concept_problems(cid)
    return {
        "c": c, "unit": C.unit(c["unit"]) if c.get("unit") else None, "defs": defs,
        "dedicated": [dict(d, u=C.unit(d["unit"])) for d in C.dedicated_sections(cid)],
        "tree": C.structure_tree(cid), "rels": rels, "related": sorted(related.values(), key=lambda x: (x["level"], x["label"].lower())),
        "mentions": mentions, "man": man, "parent": parent, "kids": [k for k in kids if k],
        "prereqs": C.prerequisites(cid), "problems": [p for p in probs if p["source"] == "curat"][:12],
        "problems_lab": [p for p in probs if p["source"] != "curat"][:12],
        "evidence": [dict(e, u=C.unit(e["unit"])) for e in C.evidence(cid)],
        "level_name": C.LEVELS.get(c["level"], ""), "definition_html": render_markdownish(htmlmod.escape(c.get("definition") or ""), current=cid),
    }


def term(request, cid):
    ctx = term_context(cid)
    ctx["preds"] = C.predicates()
    return render(request, "glosar/term.html", ctx)


def api_panel(request, cid):
    ctx = term_context(cid)
    return render(request, "glosar/_panel.html", ctx)


def api_term(request, cid):
    c = C.concept(cid)
    if not c:
        raise Http404
    return JsonResponse({"id": c["id"], "label": c["label"], "kind": c["kind"], "level": c["level"],
                         "definition": c.get("definition", ""), "origin": c.get("origin")})


# ---------------------------------------------------------------------------
# pagini de manual

def man_index(request):
    pages = C.man_pages()
    groups = {}
    names = {"1": "Comenzi și unelte (secțiunea 1)", "3": "Funcții de bibliotecă C (secțiunea 3)", "0p": "Fișiere antet POSIX (0p)"}
    for p in pages:
        groups.setdefault(p["section"], []).append(p)
    return render(request, "glosar/man_index.html", {"groups": [(names.get(k, k), v) for k, v in sorted(groups.items(), key=lambda x: {"3": 0, "0p": 1, "1": 2}.get(x[0], 3))]})


def man_view(request, mid):
    page = C.man_page(mid)
    if not page:
        raise Http404
    concept = C.concept_by_label(page["name"])
    # legăm identificatorii din pagină spre conceptele cursului (doar în SYNOPSIS/DESCRIPTION, prima apariție)
    from .render import Linker
    linker = Linker(C.matcher(), C.concepts())
    for s in page["sections"]:
        if s["id"] in ("synopsis",):
            continue
        s["html"] = mark_safe(link_man_html(s["html"], linker, s["id"]))
    return render(request, "glosar/man.html", {"p": page, "concept": concept})


def link_man_html(html: str, linker, sec: str) -> str:
    parts = re.split(r"(<pre>.*?</pre>)", html, flags=re.S)
    return "".join(p if p.startswith("<pre>") else _link_code_only(p, linker, sec) for p in parts)


def _link_code_only(html, linker, sec):
    # textul e în engleză: legăm doar identificatorii C (nu și expresiile românești)
    saved = linker.m.index
    linker.m.index = {}
    try:
        return linker.link(html, "man-" + sec)
    finally:
        linker.m.index = saved


# ---------------------------------------------------------------------------
# căutare, graf

def search(request):
    text = request.GET.get("q", "").strip()
    res = C.search(text) if text else {"concepts": [], "blocks": [], "man": []}
    if text and len(res["concepts"]) == 1 and C.fold(res["concepts"][0]["label"]) == C.fold(text) and not request.GET.get("toate"):
        return redirect("term", cid=res["concepts"][0]["id"])
    for b in res["blocks"]:
        b["snip"] = mark_safe(htmlmod.escape(b["snip"]).replace("&lt;mark&gt;", "<mark>").replace("&lt;/mark&gt;", "</mark>"))
    for m in res["man"]:
        m["snip"] = mark_safe(htmlmod.escape(m["snip"]).replace("&lt;mark&gt;", "<mark>").replace("&lt;/mark&gt;", "</mark>"))
    return render(request, "glosar/search.html", {"q": text, "res": res})


def api_suggest(request):
    text = request.GET.get("q", "")
    return JsonResponse({"items": [{"id": c["id"], "label": c["label"], "kind": c["kind"], "level": c["level"],
                                    "def": (c.get("definition") or "")[:140]} for c in C.suggest(text)]})


def graph(request):
    return render(request, "glosar/graph.html", {"units": C.labs()})


def api_graph(request):
    unit_filter = request.GET.get("u")
    level_max = int(request.GET.get("nivel", "2"))
    cs = {k: v for k, v in C.concepts().items() if v["level"] <= level_max and v.get("unit")}
    order = {u["id"]: k for k, u in enumerate(C.units())}
    if unit_filter:
        keep = {k for k, v in cs.items() if v["unit"] == unit_filter}
        # adăugăm prerechizitele directe din alte unități
        for r in C.all_relations():
            if r["pred"] == "requires" and r["subj"] in keep and r["obj"] in cs:
                keep.add(r["obj"])
        cs = {k: v for k, v in cs.items() if k in keep}
    edges = [{"s": r["subj"], "t": r["obj"], "p": r["pred"]} for r in C.all_relations()
             if r["pred"] in ("requires", "is_a", "part_of") and r["subj"] in cs and r["obj"] in cs and r["subj"] != r["obj"]]
    nodes = [{"id": k, "label": v["label"], "level": v["level"], "unit": v["unit"], "u": order.get(v["unit"], 99)} for k, v in cs.items()]
    return JsonResponse({"nodes": nodes, "edges": edges, "units": [{"id": u["id"], "short": u["short"], "i": order[u["id"]]} for u in C.units()]})


def audit(request):
    rows = C.issues()
    groups = {}
    for r in rows:
        groups.setdefault(r["kind"], []).append(r)
    return render(request, "glosar/audit.html", {"groups": sorted(groups.items()), "built": C.meta("built_at")})


# ---------------------------------------------------------------------------
# „Explică” (spec §8.10)

@require_POST
def api_explain(request):
    from invatare import llm
    from invatare.workspace import log_ai

    sel = (request.POST.get("selection") or "").strip()
    if not (2 <= len(sel) <= 80):
        return JsonResponse({"error": "Selectează între 2 și 80 de caractere."}, status=400)
    existing = C.find_concept_for_text(sel)
    if existing:
        return JsonResponse({"id": existing["id"], "existing": True})
    uid = request.POST.get("unit", "")
    try:
        i = int(request.POST.get("block", "-1"))
    except ValueError:
        i = -1
    b = C.block(uid, i) if uid else None
    prev = C.block(uid, i - 1) if b and i > 0 else None
    passage = ((prev["text"] + "\n\n") if prev and prev.get("text") else "") + (b["text"] if b else request.POST.get("context", ""))
    related_labels = [c["label"] for c in C.unit_concepts(uid)] if uid else []
    try:
        data, info = llm.explain_term(sel, passage[:3000], related_labels)
    except llm.LLMError as e:
        return JsonResponse({"error": str(e)}, status=400)
    log_ai("explica", info, prompt=f"Explică „{sel}” în contextul: {passage[:600]}", response=data,
           context={"unit": uid, "block": i})
    if not data.get("is_term"):
        return JsonResponse({"not_term": True, "reason": data.get("reason", ""), "explanation": data.get("explanation", "")})
    label = (data.get("label") or sel).strip()
    cid = C.concept_id(label)
    if C.concept(cid):
        return JsonResponse({"id": cid, "existing": True})
    kind = data.get("kind") if data.get("kind") in C.KIND_ORDER else "noțiune"
    ConceptEdit.objects.create(
        concept_id=cid, is_new=True, label=label, kind=kind, level=int(data.get("level") or 2), unit=uid,
        definition=data.get("definition", ""), extra_aliases=[a for a in data.get("aliases", []) if a][:8],
        origin="claude", author="student", model=info.get("model", ""), passage=passage[:2000], selection=sel,
        explanation=(data.get("explanation", "") + ("\n\nÎn context: " + data["in_context"] if data.get("in_context") else "")),
    )
    for rl in data.get("related", [])[:6]:
        other = C.concept_by_label(rl)
        if other:
            RelationEdit.objects.create(action="add", subj=cid, pred="uses", obj=other["id"])
    C.bump()
    return JsonResponse({"id": cid, "created": True})


# ---------------------------------------------------------------------------
# editare (doar modul autor) — spec §8.11

@require_POST
@_author_only
def term_level(request, cid):
    lvl = int(request.POST.get("level", "2"))
    e, _ = ConceptEdit.objects.get_or_create(concept_id=cid)
    e.level = lvl
    e.save()
    C.bump()
    return redirect("term", cid=cid)


@_author_only
def term_edit(request, cid):
    c = C.concept(cid)
    if not c:
        raise Http404
    if request.method == "POST":
        action = request.POST.get("action", "save")
        e, _ = ConceptEdit.objects.get_or_create(concept_id=cid, defaults={"is_new": False})
        if action == "revert":
            if e.is_new:
                messages.error(request, "Conceptul e nou; nu există o formă din laborator.")
            else:
                e.delete()
                RelationEdit.objects.filter(subj=cid).delete()
                RelationEdit.objects.filter(obj=cid).delete()
                C.bump()
                messages.success(request, "Conceptul a revenit la forma din baza de conținut.")
            return redirect("term", cid=cid)
        if action == "save":
            base = c.get("base", c)
            for f in ("label", "kind", "definition", "unit", "man"):
                v = request.POST.get(f, "").strip()
                setattr(e, f, v if (e.is_new or v != (base.get(f) or "")) else "")
            lvl = int(request.POST.get("level") or c["level"])
            e.level = lvl if (e.is_new or lvl != base.get("level")) else None
            e.extra_aliases = [a.strip() for a in request.POST.get("extra_aliases", "").split(";") if a.strip()]
            e.def_location = request.POST.get("def_location", "")
            e.save()
        elif action == "hide":
            RelationEdit.objects.create(action="hide", subj="", pred="", obj="", relation_id=int(request.POST["relation"]))
        elif action == "unhide":
            RelationEdit.objects.filter(action="hide", relation_id=int(request.POST["relation"])).delete()
        elif action == "delrel":
            RelationEdit.objects.filter(id=int(request.POST["edit"])).delete()
        elif action == "addrel":
            other_label = request.POST.get("other", "").strip()
            other = C.concept_by_label(other_label)
            if not other and request.POST.get("create"):
                oid = C.concept_id(other_label)
                ConceptEdit.objects.create(concept_id=oid, is_new=True, label=other_label, kind="noțiune", level=2,
                                           unit=c.get("unit") or "", origin="editor", author="profesor")
                C.bump()
                other = C.concept(oid)
            if not other:
                messages.error(request, f"Conceptul „{other_label}” nu există (bifează „creează”).")
            else:
                s, o = (cid, other["id"]) if request.POST.get("dir", "out") == "out" else (other["id"], cid)
                RelationEdit.objects.create(action="add", subj=s, pred=request.POST.get("pred", "uses"), obj=o)
        C.bump()
        return redirect("term_edit", cid=cid)
    ctx = term_context(cid)
    ctx.update({"kinds": C.KIND_ORDER, "units": C.units(), "preds": C.predicates().values(),
                "candidates": [ctx["defs"]["first"], ctx["defs"]["extended"], *ctx["defs"]["other"]]})
    return render(request, "glosar/term_edit.html", ctx)


@_author_only
def term_new(request):
    if request.method == "POST":
        label = request.POST.get("label", "").strip()
        if not label:
            messages.error(request, "Denumirea e obligatorie.")
            return redirect("term_new")
        cid = C.concept_id(label)
        if C.concept(cid):
            messages.error(request, "Există deja un concept cu această denumire.")
            return redirect("term", cid=cid)
        ConceptEdit.objects.create(
            concept_id=cid, is_new=True, label=label, kind=request.POST.get("kind", "noțiune"),
            level=int(request.POST.get("level", "2")), unit=request.POST.get("unit", ""),
            definition=request.POST.get("definition", ""), origin="editor", author="profesor",
            extra_aliases=[a.strip() for a in request.POST.get("aliases", "").split(";") if a.strip()],
            def_location=request.POST.get("def_location", ""),
        )
        other = C.concept_by_label(request.POST.get("other", ""))
        if other and request.POST.get("pred"):
            RelationEdit.objects.create(action="add", subj=cid, pred=request.POST["pred"], obj=other["id"])
        C.bump()
        return redirect("term", cid=cid)
    return render(request, "glosar/term_new.html", {"kinds": C.KIND_ORDER, "units": C.units(), "preds": C.predicates().values()})


@require_POST
def term_delete(request, cid):
    """Ștergerea unui concept adăugat (de student prin „Explică” sau de profesor)."""
    e = ConceptEdit.objects.filter(concept_id=cid, is_new=True).first()
    if not e or (e.origin == "editor" and not settings.PCLP_AUTHOR):
        return HttpResponseForbidden("Nu poți șterge acest concept.")
    e.delete()
    RelationEdit.objects.filter(subj=cid).delete()
    RelationEdit.objects.filter(obj=cid).delete()
    C.bump()
    messages.success(request, "Conceptul a fost șters.")
    return redirect("explore")
