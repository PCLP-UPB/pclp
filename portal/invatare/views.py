from __future__ import annotations

import datetime as dt
import random

from django.contrib import messages
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from glosar import content as C
from glosar.render import render_markdownish

from . import llm, quiz as Q, workspace as W
from .models import ProblemState, QuizAnswer, QuizSet, TutorMessage


def states() -> dict[str, ProblemState]:
    return {s.problem: s for s in ProblemState.objects.all()}


def decorate(problems: list[dict], st: dict | None = None) -> list[dict]:
    st = st if st is not None else states()
    for p in problems:
        s = st.get(p["id"])
        p["status"] = s.status if s else "nou"
        p["dir_exists"] = W.problem_dir(p).exists() if p["source"] == "curat" else False
        p["last_tests"] = s.last_tests if s else {}
    return problems


def problem_prompts(p: dict, concepts: list[dict]) -> list[dict]:
    """Prompturi recomandate pentru o problemă: ajută la învățare, nu cer soluția."""
    cl = ", ".join(c["label"] for c in concepts[:6]) or "noțiunile din laborator"
    stmt = (p.get("statement_text") or "").strip()
    head = f"Lucrez la problema „{p['title']}” (curs PCLP, limbajul C, anul I). Enunțul:\n\n{stmt}\n\n"
    return [
        {"title": "Verifică dacă ai înțeles enunțul", "when": "înainte să scrii cod",
         "prompt": head + "Nu-mi da soluția și nici cod. Pune-mi 3–4 întrebări care să verifice dacă am înțeles "
                          "cerința, formatul datelor și cazurile limită. Așteaptă răspunsurile mele înainte să continui."},
        {"title": "Discută planul tău, nu codul", "when": "după ce ai o idee de rezolvare",
         "prompt": head + "Planul meu de rezolvare este:\n«descrie aici pașii, în cuvinte»\n\n"
                          f"Spune-mi dacă planul e corect și ce cazuri ar putea să-l strice. Nu scrie cod. Noțiuni relevante: {cl}."},
        {"title": "Înțelege o eroare de compilare sau de execuție", "when": "când compilatorul, valgrind sau testele se plâng",
         "prompt": "Primesc următorul mesaj:\n«lipește aici eroarea / warning-ul / ieșirea valgrind»\n\n"
                   "pentru codul:\n«lipește aici DOAR funcția relevantă»\n\n"
                   "Explică-mi ce înseamnă mesajul și unde să mă uit, dar nu-mi rescrie codul. Ce comandă gdb m-ar ajuta să verific?"},
        {"title": "Găsește teste care îți pot strica programul", "when": "după ce trec testele din enunț",
         "prompt": head + "Propune-mi 5 intrări de test (fără rezultatele așteptate) care verifică margini și cazuri "
                          "speciale. Pentru fiecare, spune-mi doar CE verifică, ca să calculez singur rezultatul."},
        {"title": "Review de cod după coding style-ul cursului", "when": "după ce programul funcționează",
         "prompt": "Fă-mi un code review pentru codul de mai jos, după coding style-ul cursului PCLP (indentare "
                   "consecventă, acolade K&R, nume sugestive, funcții scurte, fără numere magice, verificarea "
                   "alocărilor și a fișierelor). Enumeră maxim 5 observații, ordonate după importanță, fără să rescrii codul.\n\n«lipește aici codul tău»"},
        {"title": "Explică-mi o noțiune cu un exemplu diferit", "when": "când nu înțelegi o noțiune din problemă",
         "prompt": f"Explică-mi noțiunea «alege: {cl}» din limbajul C, cu o analogie și un exemplu mic de cod "
                   f"care NU rezolvă problema „{p['title']}”. La final pune-mi o întrebare ca să verific că am înțeles."},
    ]


# ---------------------------------------------------------------------------

def home(request):
    if request.method == "POST":
        name, email = request.POST.get("name", "").strip(), request.POST.get("email", "").strip()
        group = request.POST.get("group", "").strip()
        if not name or "@" not in email:
            messages.error(request, "Completează numele și adresa de e-mail folosită pe Moodle.")
        else:
            err = W.set_student(name, email, group)
            if err:
                messages.error(request, f"Nu am putut salva datele: {err}")
            else:
                messages.success(request, "Mulțumim! Datele tale apar în arhivele săptămânale.")
        return redirect("home")
    n = C.current_week()
    ctx = _week_ctx(n, home=True)
    ctx["student"] = W.student()
    return render(request, "invatare/home.html", ctx)


def week_redirect(request):
    return redirect("week", n=C.current_week())


def week(request, n):
    if not C.week(n):
        raise Http404
    return render(request, "invatare/week.html", _week_ctx(n))


def _week_ctx(n: int, home: bool = False) -> dict:
    w = C.week(n) or {"week": n, "unit": None, "note": "", "start_date": None}
    u = C.unit(w["unit"]) if w.get("unit") else None
    st = states()
    probs = decorate(C.problems(u["id"], "curat"), st) if u else []
    lab_ex = decorate(C.problems(u["id"], "laborator"), st) if u else []
    extra = decorate(C.problems(u["id"], "problemset"), st) if u else []
    concepts = C.unit_concepts(u["id"]) if u else []
    start = dt.date.fromisoformat(w["start_date"]) if w.get("start_date") else None
    solved = sum(1 for p in probs if p["status"] == "rezolvat")
    return {
        "w": w, "u": u, "problems": probs, "lab_ex": lab_ex, "extra": extra, "n": n,
        "groups": [(lvl, C.LEVELS[lvl], [c for c in concepts if c["level"] == lvl]) for lvl in (1, 2, 3)],
        "guides": C.week_guides(n), "prompts": C.prompts(u["id"]) if u else [],
        "start": start, "end": start + dt.timedelta(days=6) if start else None,
        "weeks": C.weeks(), "solved": solved, "is_home": home,
        "term_day": C.term_of_the_day() if home else None,
        "stats": {"concepts": len(C.concepts()), "problems": len(C.problems(source="curat")), "man": len(C.man_pages())} if home else None,
        "ai_ok": llm.configured(),
    }


def problems(request):
    st = states()
    rows = []
    for u in C.labs():
        rows.append({"u": u, "week": u["week"], "problems": decorate(C.problems(u["id"], "curat"), st)})
    return render(request, "invatare/problems.html", {"rows": rows})


def problem(request, pid):
    p = C.problem(pid)
    if not p:
        raise Http404
    s = ProblemState.objects.filter(problem=pid).first()
    concepts = C.problem_concepts(pid)
    u = C.unit(p["unit"])
    ctx = {"p": p, "u": u, "state": s, "concepts": concepts, "week": W.problem_week(p)}
    if p["source"] == "curat":
        ctx.update({
            "statement": render_markdownish(p["statement_html"]),
            "hints_shown": p["hints"][: (s.hints_shown if s else 0)], "hints_left": len(p["hints"]) - (s.hints_shown if s else 0),
            "dir": W.problem_dir_in_container(p), "dir_exists": W.problem_dir(p).exists(), "code_url": W.code_url(p),
            "prompts": problem_prompts(p, concepts), "tutor": TutorMessage.objects.filter(problem=pid).order_by("created"),
            "ai_ok": llm.configured(), "siblings": C.problems(p["unit"], "curat"),
        })
    else:
        from glosar.render import rendered_unit
        blocks, _ = rendered_unit(p["unit"])
        ctx["blocks"] = [b for b in blocks if p["first_block"] <= b["i"] <= p["last_block"]]
        ctx["prompts"] = problem_prompts(p, concepts)
        ctx["siblings"] = C.problems(p["unit"], p["source"])
    return render(request, "invatare/problem.html", ctx)


@require_POST
def problem_start(request, pid):
    p = C.problem(pid)
    if not p or p["source"] != "curat":
        raise Http404
    W.ensure_problem_dir(p)
    s, _ = ProblemState.objects.get_or_create(problem=pid)
    if s.status == "nou":
        s.status = "lucru"
        s.save()
    if request.POST.get("open"):
        return redirect(W.code_url(p))
    messages.success(request, f"Am creat folderul {W.problem_dir_in_container(p)}. Deschide-l în VS Code.")
    return redirect("problem", pid=pid)


@require_POST
def problem_tests(request, pid):
    p = C.problem(pid)
    if not p:
        raise Http404
    res = W.run_tests(p)
    s, _ = ProblemState.objects.get_or_create(problem=pid)
    if "total" in res:
        s.last_tests = {"passed": res.get("passed", 0), "total": res.get("total", 0), "compiled": res.get("compiled"),
                        "at": W.now_iso()}
        if res.get("total") and res.get("passed") == res.get("total"):
            s.status = "rezolvat"
        elif s.status == "nou":
            s.status = "lucru"
        s.save()
    return JsonResponse(res)


@require_POST
def problem_hint(request, pid):
    p = C.problem(pid)
    if not p:
        raise Http404
    s, _ = ProblemState.objects.get_or_create(problem=pid)
    if s.hints_shown < len(p["hints"]):
        s.hints_shown += 1
        if s.status == "nou":
            s.status = "lucru"
        s.save()
    return redirect(f"/problema/{pid}/#indicii")


@require_POST
def problem_status(request, pid):
    s, _ = ProblemState.objects.get_or_create(problem=pid)
    v = request.POST.get("status")
    if v in dict(ProblemState.STATUS):
        s.status = v
        s.save()
    return redirect("problem", pid=pid)


@require_POST
def problem_tutor(request, pid):
    p = C.problem(pid)
    if not p:
        raise Http404
    if request.POST.get("reset"):
        TutorMessage.objects.filter(problem=pid).delete()
        return redirect(f"/problema/{pid}/#tutore")
    text = (request.POST.get("message") or "").strip()
    if not text:
        return redirect(f"/problema/{pid}/#tutore")
    TutorMessage.objects.create(problem=pid, role="user", content=text)
    hist = [{"role": m.role, "content": m.content} for m in TutorMessage.objects.filter(problem=pid).order_by("created")][-20:]
    code = W.read_code(p) if request.POST.get("with_code") else None
    try:
        reply, info = llm.tutor_reply(hist, p, code)
    except llm.LLMError as e:
        TutorMessage.objects.filter(problem=pid).order_by("-created").first().delete()
        messages.error(request, str(e))
        return redirect(f"/problema/{pid}/#tutore")
    TutorMessage.objects.create(problem=pid, role="assistant", content=reply)
    W.log_ai("tutore", info, prompt=text, response=reply, context={"problem": pid, "with_code": bool(code)})
    return redirect(f"/problema/{pid}/#tutore")


# ---------------------------------------------------------------------------

def prompts(request):
    labs = [(u, C.prompts(u["id"])) for u in C.units()]
    return render(request, "invatare/prompts.html", {
        "labs": [x for x in labs if x[1]], "external": W.external_prompts(), "portal": W.portal_prompts(30),
        "week": C.current_week(), "problems": C.problems(source="curat"),
    })


@require_POST
def prompt_external(request):
    prompt = (request.POST.get("prompt") or "").strip()
    if len(prompt) < 5:
        messages.error(request, "Scrie promptul pe care l-ai folosit.")
        return redirect("/prompturi/#extern")
    path = W.save_external(request.POST.get("tool", "altul"), prompt, request.POST.get("answer", ""),
                           request.POST.get("notes", ""), request.POST.get("link", ""), request.POST.get("problem", ""),
                           C.current_week())
    messages.success(request, f"Promptul a fost salvat în .pclp/ai/external/{path.name} și va intra în arhiva săptămânii.")
    nxt = request.POST.get("next")
    return redirect(nxt if nxt and nxt.startswith("/") else "/prompturi/#extern")


def quiz_config(request):
    if request.method == "POST":
        units = request.POST.getlist("units") or [C.week(C.current_week())["unit"] or "lab01"]
        max_level = int(request.POST.get("level", "2"))
        n = max(3, min(30, int(request.POST.get("n", "10"))))
        types = request.POST.getlist("types") or list(Q.TYPES)
        source = request.POST.get("source", "offline")
        errors = []
        if source == "llm":
            qs, errors = Q.llm_questions(units, max_level, n, fresh=bool(request.POST.get("fresh")))
            if len(qs) < n:
                qs += Q.offline_questions(units, max_level, n - len(qs), types)
        else:
            qs = Q.offline_questions(units, max_level, n, types)
        for e in errors[:2]:
            messages.warning(request, e)
        if not qs:
            messages.error(request, "Nu am putut genera întrebări pentru selecția aleasă.")
            return redirect("quiz")
        qz = QuizSet.objects.create(config={"units": units, "level": max_level, "n": n, "types": types, "source": source}, questions=qs)
        return redirect("quiz_play", qid=qz.id)
    cw = C.week(C.current_week())
    return render(request, "invatare/quiz_config.html", {
        "units": C.units(), "types": Q.TYPES, "default_unit": cw["unit"] if cw else "lab01",
        "history": QuizSet.objects.order_by("-created")[:10], "ai_ok": llm.configured(),
    })


def quiz_play(request, qid):
    qz = QuizSet.objects.filter(id=qid).first()
    if not qz:
        raise Http404
    answers = {a.index: a for a in qz.answers.all()}
    if request.method == "POST":
        i = int(request.POST["index"])
        chosen = int(request.POST["choice"])
        if i not in answers and 0 <= i < len(qz.questions):
            qd = qz.questions[i]
            a = QuizAnswer.objects.create(quiz=qz, index=i, concept=qd.get("concept", ""), unit=qd.get("unit") or "",
                                          chosen=chosen, correct=chosen == qd["answer"])
            answers[i] = a
            qz.score = sum(1 for x in answers.values() if x.correct)
            qz.finished = len(answers) == len(qz.questions)
            qz.save()
        return redirect(f"/intrebari/{qid}/#q{i}")
    cs = C.concepts()
    items = []
    for i, qd in enumerate(qz.questions):
        a = answers.get(i)
        items.append({"i": i, "q": qd, "a": a, "c": cs.get(qd.get("concept"))})
    return render(request, "invatare/quiz_play.html", {"qz": qz, "items": items, "answered": len(answers)})


def progress(request):
    cs = C.concepts()
    per_unit = {}
    wrong: dict[str, int] = {}
    for a in QuizAnswer.objects.all():
        d = per_unit.setdefault(a.unit or "-", [0, 0])
        d[1] += 1
        d[0] += int(a.correct)
        if not a.correct:
            wrong[a.concept] = wrong.get(a.concept, 0) + 1
        else:
            wrong[a.concept] = max(0, wrong.get(a.concept, 0) - 1)
    st = states()
    labs = []
    for u in C.labs():
        ps = C.problems(u["id"], "curat")
        done = sum(1 for p in ps if st.get(p["id"]) and st[p["id"]].status == "rezolvat")
        work = sum(1 for p in ps if st.get(p["id"]) and st[p["id"]].status == "lucru")
        q = per_unit.get(u["id"])
        labs.append({"u": u, "done": done, "work": work, "total": len(ps),
                     "quiz": (round(100 * q[0] / q[1]), q[1]) if q else None})
    review = [cs[k] for k, v in sorted(wrong.items(), key=lambda x: -x[1]) if v > 0 and k in cs][:30]
    return render(request, "invatare/progress.html", {
        "labs": labs, "review": review, "history": QuizSet.objects.order_by("-created")[:20],
        "n_ai_portal": len(W.portal_prompts(10000)), "n_ai_ext": len(W.external_prompts(10000)),
    })


def ai_settings(request):
    s = llm.load_settings()
    if request.method == "POST":
        prov = request.POST.get("provider", "anthropic")
        if prov not in llm.PROVIDERS:
            prov = "anthropic"
        new = {"provider": prov, "model": request.POST.get("model", "").strip() or llm.PROVIDERS[prov]["default_model"],
               "base_url": request.POST.get("base_url", "").strip() or llm.PROVIDERS[prov]["base_url"]}
        key = request.POST.get("api_key", "").strip()
        new["api_key"] = key if key else (s.get("api_key", "") if prov == s.get("provider") else "")
        if request.POST.get("clear_key"):
            new["api_key"] = ""
        llm.save_settings(new)
        if request.POST.get("test"):
            try:
                text, info = llm.call("Răspunde foarte scurt, în română.", [{"role": "user", "content": "Spune „salut” și numele modelului tău."}])
                messages.success(request, f"Conexiune reușită ({info['model']}): {text[:120]}")
            except llm.LLMError as e:
                messages.error(request, str(e))
        else:
            messages.success(request, "Setările au fost salvate (local, în .pclp/state — nu intră în arhivă).")
        return redirect("settings")
    masked = ("•" * 8 + s["api_key"][-4:]) if s.get("api_key") else ""
    return render(request, "invatare/settings.html", {"s": s, "masked": masked, "providers": llm.PROVIDERS})


def about(request):
    return render(request, "invatare/about.html", {"built": C.meta("built_at"), "sources": C.units()})


def random_problem(request):  # pragma: no cover - rezervat
    ps = C.problems(source="curat")
    return redirect("problem", pid=random.choice(ps)["id"])
