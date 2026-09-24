"""Generatorul de întrebări (spec §8.7): offline din datele curate, sau cu LLM (cache)."""
from __future__ import annotations

import hashlib
import random

from glosar import content as C

TYPES = {
    "def2term": "definiție → termen",
    "term2def": "termen → definiție",
    "relation": "completează relația",
    "truefalse": "adevărat / fals",
}


def _pool(units: list[str], max_level: int) -> list[dict]:
    return [c for c in C.concepts().values()
            if c.get("unit") in units and c["level"] <= max_level and c.get("definition") and c.get("origin") != "claude"]


def _distractors(c: dict, pool: list[dict], n: int, rnd: random.Random, key="label") -> list[str]:
    same = [x for x in pool if x["id"] != c["id"] and x["kind"] == c["kind"] and x.get(key)]
    other = [x for x in pool if x["id"] != c["id"] and x["kind"] != c["kind"] and x.get(key)]
    rnd.shuffle(same)
    rnd.shuffle(other)
    out = []
    for x in same + other:
        v = x[key]
        if v not in out and v != c[key]:
            out.append(v)
        if len(out) == n:
            break
    return out


def _mc(prompt, correct, wrong, rnd, explanation, c):
    opts = [correct] + wrong[:3]
    rnd.shuffle(opts)
    return {"type": "mc", "prompt": prompt, "options": opts, "answer": opts.index(correct), "explanation": explanation,
            "concept": c["id"], "unit": c.get("unit")}


def mask_label(text: str, c: dict) -> str:
    ms = C.matcher().find(text, in_code=True, only={c["id"]})
    for m in reversed(ms):
        text = text[:m.start] + "_____" + text[m.end:]
    return text


def offline_questions(units: list[str], max_level: int, n: int, types: list[str], seed: int | None = None) -> list[dict]:
    rnd = random.Random(seed)
    pool = _pool(units, max_level)
    full_pool = _pool([u["id"] for u in C.units()], 3)
    if not pool:
        return []
    rels = [r for r in C.all_relations() if r["pred"] != "precedes"]
    cs = C.concepts()
    preds = C.predicates()
    out: list[dict] = []
    tries = 0
    while len(out) < n and tries < n * 20:
        tries += 1
        t = rnd.choice(types)
        c = rnd.choice(pool)
        if any(q["concept"] == c["id"] and q["kind"] == t for q in out):
            continue
        if t == "def2term":
            wrong = _distractors(c, full_pool, 3, rnd)
            if len(wrong) < 3:
                continue
            q = _mc(f"Ce termen corespunde definiției?\n\n„{mask_label(c['definition'], c)}”", c["label"], wrong, rnd,
                    f"{c['label']}: {c['definition']}", c)
        elif t == "term2def":
            wrong = _distractors(c, full_pool, 3, rnd, key="definition")
            if len(wrong) < 3:
                continue
            q = _mc(f"Care este definiția corectă pentru „{c['label']}”?", c["definition"], wrong, rnd,
                    f"{c['label']}: {c['definition']}", c)
        elif t in ("relation", "truefalse"):
            mine = [r for r in rels if r["subj"] == c["id"] and r["obj"] in cs]
            if not mine:
                continue
            r = rnd.choice(mine)
            obj = cs[r["obj"]]
            verb = preds[r["pred"]]["label"]
            if t == "relation":
                wrong = [x["label"] for x in full_pool if x["id"] != obj["id"] and x["kind"] == obj["kind"]
                         and not any(rr["subj"] == c["id"] and rr["pred"] == r["pred"] and rr["obj"] == x["id"] for rr in rels)]
                rnd.shuffle(wrong)
                if len(wrong) < 3:
                    continue
                q = _mc(f"{c['label']} — {verb} …?", obj["label"], wrong, rnd, f"{c['label']} {verb} {obj['label']}.", c)
            else:
                truth = rnd.random() < 0.5
                shown = obj
                if not truth:
                    alts = [x for x in full_pool if x["kind"] == obj["kind"] and x["id"] != obj["id"]
                            and not any(rr["subj"] == c["id"] and rr["pred"] == r["pred"] and rr["obj"] == x["id"] for rr in rels)]
                    if not alts:
                        continue
                    shown = rnd.choice(alts)
                q = {"type": "tf", "prompt": f"Adevărat sau fals?\n\n{c['label']} {verb} {shown['label']}.",
                     "options": ["Adevărat", "Fals"], "answer": 0 if truth else 1,
                     "explanation": f"{c['label']} {verb} {obj['label']}.", "concept": c["id"], "unit": c.get("unit")}
        else:
            continue
        q["kind"] = t
        q["source"] = "offline"
        out.append(q)
    return out


def llm_questions(units: list[str], max_level: int, n: int, fresh: bool = False) -> tuple[list[dict], list[str]]:
    from . import llm
    from .models import LLMCache
    from .workspace import log_ai

    rnd = random.Random()
    pool = _pool(units, max_level)
    rnd.shuffle(pool)
    out, errors = [], []
    for c in pool[: n * 2]:
        if len(out) >= n:
            break
        key = hashlib.sha256(f"q1|{c['id']}|{c.get('definition')}".encode()).hexdigest()
        cached = None if fresh else LLMCache.objects.filter(key=key).first()
        if cached:
            data = cached.data
        else:
            occ = C.occurrences(c["id"])
            src = ""
            if occ:
                b = C.block(occ[0]["unit"], occ[0]["block"])
                src = b["text"] if b else ""
            try:
                data, info = llm.generate_question(c, src)
            except llm.LLMError as e:
                errors.append(str(e))
                if "Configurează" in str(e) or "cheia" in str(e).lower():
                    break
                continue
            log_ai("intrebari", info, prompt=f"Întrebare grilă despre „{c['label']}”", response=data, context={"concept": c["id"]})
            LLMCache.objects.update_or_create(key=key, defaults={"data": data})
        out.append({"type": "mc", "kind": "llm", "source": "llm", "prompt": data["prompt"], "options": data["options"],
                    "answer": int(data["answer"]), "explanation": data.get("explanation", ""), "concept": c["id"], "unit": c.get("unit")})
    return out, errors
