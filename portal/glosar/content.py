"""Acces la baza de conținut (read-only) + stratul de editări.

Toate citirile de concepte trec prin `concepts()`, care aplică ConceptEdit/RelationEdit.
Cache-urile derivate (potrivitor, capitole randate) se invalidează la fiecare editare
prin `bump()`.
"""
from __future__ import annotations

import datetime as dt
import json
import sqlite3
import sys
import threading
from functools import lru_cache

from django.conf import settings

if str(settings.PCLP_PIPELINE) not in sys.path:
    sys.path.insert(0, str(settings.PCLP_PIPELINE))
from matcher import Matcher, concept_id, fold, slug  # noqa: E402,F401

_local = threading.local()
_version = {"n": 0}

KIND_ORDER = ["noțiune", "tip de date", "operator", "instrucțiune", "cuvânt cheie", "funcție de bibliotecă",
              "fișier antet", "directivă preprocesor", "specificator de format", "tehnică", "eroare", "bună practică",
              "unealtă", "opțiune de compilare"]
LEVELS = {1: "bază", 2: "aprofundare", 3: "detaliu"}


def db() -> sqlite3.Connection:
    con = getattr(_local, "con", None)
    if con is None:
        path = settings.PCLP_CONTENT / "content.sqlite"
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
        con.row_factory = sqlite3.Row
        _local.con = con
    return con


def q(sql, *args):
    return db().execute(sql, args).fetchall()


def q1(sql, *args):
    return db().execute(sql, args).fetchone()


def bump():
    """Invalidează cache-urile derivate după o editare."""
    _version["n"] += 1
    _concepts_cached.cache_clear()
    _matcher_cached.cache_clear()
    _rendered_unit.cache_clear()


def version() -> int:
    return _version["n"]


# ---------------------------------------------------------------------------
# unități

@lru_cache(maxsize=1)
def units() -> list[dict]:
    out = []
    for r in q("SELECT * FROM units ORDER BY ord"):
        d = dict(r)
        d["sources"] = json.loads(d["sources"] or "[]")
        d["authors"] = json.loads(d["authors"] or "[]")
        out.append(d)
    return out


def unit(uid: str) -> dict | None:
    return next((u for u in units() if u["id"] == uid), None)


def labs() -> list[dict]:
    return [u for u in units() if u["kind"] == "lab"]


def guides() -> list[dict]:
    return [u for u in units() if u["kind"] == "guide"]


@lru_cache(maxsize=64)
def sections(uid: str) -> list[dict]:
    return [dict(r) for r in q("SELECT * FROM sections WHERE unit=? ORDER BY ord", uid)]


@lru_cache(maxsize=32)
def blocks(uid: str) -> list[dict]:
    out = []
    for r in q("SELECT i, data, text FROM blocks WHERE unit=? ORDER BY i", uid):
        b = json.loads(r["data"])
        b["text"] = r["text"]
        out.append(b)
    return out


def block(uid: str, i: int) -> dict | None:
    bl = blocks(uid)
    return bl[i] if 0 <= i < len(bl) else None


def section_title(uid: str, sid: str) -> str:
    return next((s["title"] for s in sections(uid) if s["id"] == sid), sid or "")


def section_of_block(uid: str, i: int) -> str | None:
    b = block(uid, i)
    return b.get("sec") if b else None


# ---------------------------------------------------------------------------
# calendar

@lru_cache(maxsize=1)
def weeks() -> list[dict]:
    return [dict(r) for r in q("SELECT * FROM weeks ORDER BY week")]


def week_of_unit(uid: str) -> int | None:
    u = unit(uid)
    return u["week"] if u else None


def current_week(today: dt.date | None = None) -> int:
    today = today or dt.date.today()
    ws = weeks()
    if not ws:
        return 1
    current = 1
    for w in ws:
        if dt.date.fromisoformat(w["start_date"]) <= today:
            current = w["week"]
    return current


def week(n: int) -> dict | None:
    return next((w for w in weeks() if w["week"] == n), None)


def week_guides(n: int) -> list[dict]:
    ids = [r["unit"] for r in q("SELECT unit FROM week_guides WHERE week=?", n)]
    return [u for u in (unit(x) for x in ids) if u]


# ---------------------------------------------------------------------------
# concepte (cu stratul de editări)

def concepts() -> dict[str, dict]:
    return _concepts_cached(_version["n"])


@lru_cache(maxsize=2)
def _concepts_cached(_v: int) -> dict[str, dict]:
    from .models import ConceptEdit

    out: dict[str, dict] = {}
    aliases: dict[str, list[str]] = {}
    for r in q("SELECT concept, alias FROM aliases"):
        aliases.setdefault(r["concept"], []).append(r["alias"])
    for r in q("SELECT * FROM concepts"):
        c = dict(r)
        c["aliases"] = aliases.get(c["id"], [])
        c["level"] = c.pop("learning_level")
        c["edited"] = False
        c["origin"] = "curat"
        out[c["id"]] = c
    for e in ConceptEdit.objects.all():
        if e.is_new or e.concept_id not in out:
            out[e.concept_id] = {
                "id": e.concept_id, "label": e.label, "kind": e.kind or "noțiune", "level": e.level or 2,
                "unit": e.unit or None, "definition": e.definition, "man": e.man, "aliases": list(e.extra_aliases or []),
                "edited": True, "origin": e.origin, "new": True, "edit": e,
            }
            continue
        c = out[e.concept_id]
        c["base"] = {k: c[k] for k in ("label", "kind", "level", "definition", "unit")}
        for f in ("label", "kind", "definition", "unit", "man"):
            v = getattr(e, f)
            if v:
                c[f] = v
        if e.level:
            c["level"] = e.level
        c["aliases"] = c["aliases"] + [a for a in (e.extra_aliases or []) if a not in c["aliases"]]
        c["edited"] = True
        c["edit"] = e
    return out


def concept(cid: str) -> dict | None:
    return concepts().get(cid)


def concept_by_label(label: str) -> dict | None:
    return concepts().get(concept_id(label))


def matcher() -> Matcher:
    return _matcher_cached(_version["n"])


@lru_cache(maxsize=2)
def _matcher_cached(_v: int) -> Matcher:
    return Matcher.build(list(concepts().values()))


def find_concept_for_text(text: str) -> dict | None:
    """Selecția e deja un concept (formă de bază, sinonim sau formă flexionată)?"""
    text = text.strip()
    ft = fold(text)
    for c in concepts().values():
        if fold(c["label"]) == ft or any(fold(a) == ft for a in c["aliases"]):
            return c
    ms = matcher().find(text, in_code=True)
    if len(ms) == 1 and ms[0].end - ms[0].start >= len(text) - 3:
        return concept(ms[0].concept)
    return None


def predicates() -> dict[str, dict]:
    return {r["id"]: dict(r) for r in q("SELECT * FROM predicates")}


def relations(cid: str) -> list[dict]:
    """Relațiile conceptului în ambele sensuri, cu editările aplicate."""
    from .models import RelationEdit

    preds = predicates()
    hidden = set(RelationEdit.objects.filter(action="hide").values_list("relation_id", flat=True))
    cs = concepts()
    out = []
    for r in q("SELECT * FROM relations WHERE subj=? OR obj=?", cid, cid):
        r = dict(r)
        if r["subj"] not in cs or r["obj"] not in cs:
            continue
        r["hidden"] = r["id"] in hidden
        r["added"] = False
        out.append(r)
    for e in RelationEdit.objects.filter(action="add").filter(subj=cid) | RelationEdit.objects.filter(action="add", obj=cid):
        if e.subj in cs and e.obj in cs:
            out.append({"id": None, "edit_id": e.id, "subj": e.subj, "pred": e.pred, "obj": e.obj, "unit": None,
                        "sec": None, "origin": "editorial", "hidden": False, "added": True})
    for r in out:
        p = preds.get(r["pred"], {"label": r["pred"], "inverse": r["pred"], "hierarchical": 0})
        if r["subj"] == cid:
            r["dir"], r["other"], r["verb"] = "out", cs[r["obj"]], p["label"]
        else:
            r["dir"], r["other"], r["verb"] = "in", cs[r["subj"]], p["inverse"]
        r["hierarchical"] = p["hierarchical"]
    return out


def all_relations() -> list[dict]:
    from .models import RelationEdit

    hidden = set(RelationEdit.objects.filter(action="hide").values_list("relation_id", flat=True))
    rels = [dict(r) for r in q("SELECT * FROM relations") if r["id"] not in hidden]
    rels += [{"id": None, "subj": e.subj, "pred": e.pred, "obj": e.obj, "origin": "editorial", "unit": None, "sec": None}
             for e in RelationEdit.objects.filter(action="add")]
    cs = concepts()
    return [r for r in rels if r["subj"] in cs and r["obj"] in cs]


def prerequisites(cid: str) -> list[dict]:
    cs = concepts()
    return [cs[r["obj"]] for r in all_relations() if r["subj"] == cid and r["pred"] == "requires"]


def structure_tree(cid: str, depth: int = 3) -> list[dict]:
    """Arbore din relațiile ierarhice spre termen (componente, tipuri)."""
    preds = predicates()
    rels = [r for r in all_relations() if preds.get(r["pred"], {}).get("hierarchical")]
    cs = concepts()

    def kids(x, d, seen):
        if d == 0:
            return []
        out = []
        for r in rels:
            if r["obj"] == x and r["subj"] not in seen:
                seen.add(r["subj"])
                out.append({"c": cs[r["subj"]], "verb": preds[r["pred"]]["inverse"], "kids": kids(r["subj"], d - 1, seen)})
        return out

    return kids(cid, depth, {cid})


def mentions(cid: str) -> list[dict]:
    return [dict(r) for r in q("SELECT unit, count FROM mentions WHERE concept=? ORDER BY count DESC", cid)]


def occurrences(cid: str, uid: str | None = None) -> list[dict]:
    if uid:
        return [dict(r) for r in q("SELECT * FROM occurrences WHERE concept=? AND unit=? ORDER BY block", cid, uid)]
    return [dict(r) for r in q("SELECT * FROM occurrences WHERE concept=? ORDER BY unit, block", cid)]


def definitions(cid: str) -> dict:
    out = {"first": None, "extended": None, "other": []}
    for r in q("SELECT * FROM definitions WHERE concept=?", cid):
        d = dict(r)
        d["section"] = section_of_block(d["unit"], d["block"])
        d["section_title"] = section_title(d["unit"], d["section"]) if d["section"] else ""
        if d["rank"] == "other":
            out["other"].append(d)
        else:
            out[d["rank"]] = d
    c = concept(cid)
    e = c.get("edit") if c else None
    if e and e.def_location and ":" in e.def_location:
        uid, i = e.def_location.split(":")
        b = block(uid, int(i))
        if b:
            out["first"] = {"unit": uid, "block": int(i), "sentence": b["text"][:400], "section": b.get("sec"),
                            "section_title": section_title(uid, b.get("sec")), "rank": "first", "score": 99}
    return out


def dedicated_sections(cid: str) -> list[dict]:
    rows = [dict(r) for r in q("SELECT * FROM dedicated_sections WHERE concept=?", cid)]
    for r in rows:
        r["title"] = section_title(r["unit"], r["sec"])
    return rows


def evidence(cid: str) -> list[dict]:
    rows = [dict(r) for r in q("SELECT * FROM concept_evidence WHERE concept=?", cid)]
    for r in rows:
        r["title"] = section_title(r["unit"], r["sec"])
    return rows


def outline() -> dict[str | None, list[str]]:
    kids: dict[str | None, list[str]] = {}
    cs = concepts()
    seen = set()
    for r in q("SELECT concept, parent, unit FROM learning_outline ORDER BY ord"):
        if r["concept"] in cs:
            kids.setdefault(r["parent"] if r["parent"] in cs else None, []).append(r["concept"])
            seen.add(r["concept"])
    for cid in cs:
        if cid not in seen:
            kids.setdefault(None, []).append(cid)
    return kids


def outline_parent(cid: str) -> dict | None:
    r = q1("SELECT parent FROM learning_outline WHERE concept=?", cid)
    return concept(r["parent"]) if r and r["parent"] else None


def unit_concepts(uid: str) -> list[dict]:
    cs = [c for c in concepts().values() if c.get("unit") == uid]
    return sorted(cs, key=lambda c: (c["level"], c["label"].lower()))


def section_concepts(uid: str, sid: str) -> list[dict]:
    ids = {r["concept"] for r in q("SELECT DISTINCT o.concept FROM occurrences o JOIN blocks b ON b.unit=o.unit AND b.i=o.block WHERE o.unit=? AND b.sec=?", uid, sid)}
    cs = concepts()
    return sorted([cs[i] for i in ids if i in cs], key=lambda c: (c["level"], c["label"].lower()))


def term_of_the_day() -> dict | None:
    cs = sorted((c for c in concepts().values() if c["level"] == 1 and c.get("definition")), key=lambda c: c["id"])
    if not cs:
        return None
    return cs[dt.date.today().toordinal() % len(cs)]


# ---------------------------------------------------------------------------
# probleme, prompturi, pagini de manual

def problems(uid: str | None = None, source: str | None = None) -> list[dict]:
    sql, args = "SELECT * FROM problems WHERE 1=1", []
    if uid:
        sql += " AND unit=?"
        args.append(uid)
    if source:
        sql += " AND source=?"
        args.append(source)
    out = []
    for r in q(sql + " ORDER BY ord", *args):
        d = dict(r)
        d["hints"] = json.loads(d["hints"] or "[]")
        d["pitfalls"] = json.loads(d["pitfalls"] or "[]")
        out.append(d)
    return out


def problem(pid: str) -> dict | None:
    r = q1("SELECT * FROM problems WHERE id=?", pid)
    if not r:
        return None
    d = dict(r)
    d["hints"] = json.loads(d["hints"] or "[]")
    d["pitfalls"] = json.loads(d["pitfalls"] or "[]")
    return d


def problem_concepts(pid: str) -> list[dict]:
    cs = concepts()
    out, seen = [], set()
    for r in q("SELECT concept, origin FROM problem_concepts WHERE problem=?", pid):
        if r["concept"] in cs and r["concept"] not in seen:
            seen.add(r["concept"])
            out.append(cs[r["concept"]])
    return sorted(out, key=lambda c: (c["level"], c["label"].lower()))


def concept_problems(cid: str) -> list[dict]:
    ids = [r["problem"] for r in q("SELECT DISTINCT problem FROM problem_concepts WHERE concept=?", cid)]
    return [p for p in (problem(i) for i in ids) if p]


def prompts(uid: str | None = None) -> list[dict]:
    rows = q("SELECT * FROM prompts WHERE unit=? ORDER BY ord", uid) if uid else q("SELECT * FROM prompts ORDER BY unit, ord")
    out = []
    cs = concepts()
    for r in rows:
        d = dict(r)
        d["concepts"] = [cs[x] for x in json.loads(d["concepts"] or "[]") if x in cs]
        out.append(d)
    return out


def man_pages() -> list[dict]:
    return [dict(r) for r in q("SELECT id, name, section, summary, command FROM man_pages ORDER BY section, name")]


def man_page(mid: str) -> dict | None:
    r = q1("SELECT data FROM man_pages WHERE id=?", mid)
    return json.loads(r["data"]) if r else None


def man_for_name(name: str) -> dict | None:
    r = q1("SELECT id FROM man_pages WHERE name=? ORDER BY section LIMIT 1", name)
    return man_page(r["id"]) if r else None


def issues() -> list[dict]:
    return [dict(r) for r in q("SELECT * FROM issues")]


def meta(key: str):
    r = q1("SELECT value FROM meta WHERE key=?", key)
    return r["value"] if r else None


# ---------------------------------------------------------------------------
# căutare

def fts_query(text: str) -> str:
    words = [w for w in fold(text).replace('"', " ").split() if w]
    return " ".join(f'"{w}"*' for w in words)


def suggest(text: str, limit: int = 8) -> list[dict]:
    ft = fold(text.strip())
    if not ft:
        return []
    cs = concepts().values()
    pref = [c for c in cs if fold(c["label"]).startswith(ft) or any(fold(a).startswith(ft) for a in c["aliases"])]
    pref.sort(key=lambda c: (c["level"], len(c["label"])))
    out = pref[:limit]
    if len(out) < limit:
        seen = {c["id"] for c in out}
        try:
            for r in q("SELECT id FROM concept_search WHERE concept_search MATCH ? LIMIT 20", fts_query(text)):
                c = concept(r["id"])
                if c and c["id"] not in seen:
                    out.append(c)
                    seen.add(c["id"])
                    if len(out) >= limit:
                        break
        except sqlite3.OperationalError:
            pass
        for c in cs:  # concepte noi (din editări), neindexate în FTS
            if len(out) >= limit:
                break
            if c["id"] not in seen and ft in fold(c["label"] + " " + c.get("definition", "")):
                out.append(c)
                seen.add(c["id"])
    return out


def search(text: str) -> dict:
    res = {"concepts": suggest(text, 30), "blocks": [], "man": []}
    fq = fts_query(text)
    if not fq:
        return res
    try:
        for r in q("SELECT unit, i, sec, snippet(block_search, 3, '<mark>', '</mark>', '…', 24) AS snip "
                   "FROM block_search WHERE block_search MATCH ? ORDER BY rank LIMIT 60", fq):
            d = dict(r)
            u = unit(d["unit"])
            d["unit_title"] = u["title"] if u else d["unit"]
            d["section_title"] = section_title(d["unit"], d["sec"])
            res["blocks"].append(d)
        for r in q("SELECT id, name, snippet(man_search, 2, '<mark>', '</mark>', '…', 16) AS snip FROM man_search "
                   "WHERE man_search MATCH ? ORDER BY rank LIMIT 15", fq):
            res["man"].append(dict(r))
    except sqlite3.OperationalError:
        pass
    return res


# importat târziu ca să evităm ciclul render → content
from .render import _rendered_unit  # noqa: E402,F401
