"""Construiește baza de conținut content.sqlite din extracții + fișierele curate.

Intrări:  <out>/reader/*.json, <out>/man/*.json, content/curated/{concepts.tsv|parts/*/concepts.tsv,
          relations.txt, prompts.yaml, course.yaml, problems/**}
Ieșire:   <out>/content.sqlite, <out>/course.json, <out>/problems/<id>/tests/*, <out>/media/*
Baza se scrie într-un fișier temporar și înlocuiește baza veche doar după verificarea integrității.
"""
from __future__ import annotations

import argparse
import csv
import os
import datetime as dt
import json
import re
import shutil
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

import markdown
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from matcher import Matcher, concept_id, fold, slug  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
# versiunea schemei bazei de conținut; trebuie să coincidă cu tools/pclp_content.py:SCHEMA
CONTENT_SCHEMA = 1
CUR = ROOT / "content" / "curated"

KINDS = ["noțiune", "tip de date", "operator", "instrucțiune", "cuvânt cheie", "funcție de bibliotecă",
         "fișier antet", "directivă preprocesor", "unealtă", "opțiune de compilare", "eroare", "bună practică",
         "tehnică", "specificator de format"]

PREDICATES = [
    ("is_a", "este un tip de", "include tipul", 1),
    ("part_of", "face parte din", "conține", 1),
    ("declared_in", "este declarat în", "declară", 1),
    ("requires", "presupune cunoașterea", "este necesar pentru", 0),
    ("uses", "folosește", "este folosit de", 0),
    ("operates_on", "operează asupra", "este operat de", 0),
    ("returns", "returnează", "este returnat de", 0),
    ("pairs_with", "se folosește împreună cu", "se folosește împreună cu", 0),
    ("alternative_to", "este o alternativă la", "are ca alternativă", 0),
    ("causes", "poate cauza", "poate fi cauzat de", 0),
    ("detects", "detectează", "este detectat de", 0),
    ("prevents", "previne", "este prevenit de", 0),
    ("precedes", "se învață înainte de", "se învață după", 0),
    ("has_property", "are proprietatea", "este proprietate a", 0),
]

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE units (id TEXT PRIMARY KEY, kind TEXT, number INTEGER, title TEXT, short TEXT, icon TEXT,
  week INTEGER, sources TEXT, authors TEXT, n_blocks INTEGER, ord INTEGER);
CREATE TABLE sections (unit TEXT REFERENCES units(id), id TEXT, parent TEXT, title TEXT, level INTEGER,
  part TEXT, first_block INTEGER, ord INTEGER, PRIMARY KEY (unit, id));
CREATE TABLE blocks (unit TEXT REFERENCES units(id), i INTEGER, t TEXT, sec TEXT, part TEXT, data TEXT, text TEXT,
  PRIMARY KEY (unit, i));
CREATE VIRTUAL TABLE block_search USING fts5(unit UNINDEXED, i UNINDEXED, sec UNINDEXED, text, tokenize='unicode61 remove_diacritics 2');
CREATE TABLE man_pages (id TEXT PRIMARY KEY, name TEXT, section TEXT, summary TEXT, command TEXT, data TEXT);
CREATE VIRTUAL TABLE man_search USING fts5(id UNINDEXED, name, text, tokenize='unicode61 remove_diacritics 2');
CREATE TABLE concepts (id TEXT PRIMARY KEY, label TEXT NOT NULL, kind TEXT, learning_level INTEGER,
  unit TEXT REFERENCES units(id), definition TEXT, man TEXT, review_status TEXT, level_rationale TEXT, origin TEXT);
CREATE TABLE aliases (concept TEXT REFERENCES concepts(id), alias TEXT, folded TEXT);
CREATE VIRTUAL TABLE concept_search USING fts5(id UNINDEXED, label, aliases, definition, tokenize='unicode61 remove_diacritics 2');
CREATE TABLE predicates (id TEXT PRIMARY KEY, label TEXT, inverse TEXT, hierarchical INTEGER);
CREATE TABLE relations (id INTEGER PRIMARY KEY, subj TEXT REFERENCES concepts(id), pred TEXT REFERENCES predicates(id),
  obj TEXT REFERENCES concepts(id), unit TEXT, sec TEXT, origin TEXT);
CREATE TABLE concept_evidence (concept TEXT REFERENCES concepts(id), unit TEXT, sec TEXT, ok INTEGER);
CREATE TABLE occurrences (concept TEXT, unit TEXT, block INTEGER, start INTEGER, end INTEGER);
CREATE INDEX occ_c ON occurrences(concept);
CREATE INDEX occ_u ON occurrences(unit, block);
CREATE TABLE mentions (concept TEXT, unit TEXT, count INTEGER, PRIMARY KEY (concept, unit));
CREATE TABLE definitions (concept TEXT, rank TEXT, unit TEXT, block INTEGER, sentence TEXT, score INTEGER);
CREATE TABLE dedicated_sections (concept TEXT, unit TEXT, sec TEXT);
CREATE TABLE learning_outline (concept TEXT PRIMARY KEY, parent TEXT, unit TEXT, ord INTEGER);
CREATE TABLE problems (id TEXT PRIMARY KEY, unit TEXT, source TEXT, number INTEGER, title TEXT, slug TEXT,
  difficulty INTEGER, minutes INTEGER, statement_html TEXT, statement_text TEXT, starter TEXT, hints TEXT, pitfalls TEXT,
  first_block INTEGER, last_block INTEGER, n_tests INTEGER, ord INTEGER);
CREATE TABLE problem_concepts (problem TEXT REFERENCES problems(id), concept TEXT REFERENCES concepts(id), origin TEXT);
CREATE TABLE prompts (id INTEGER PRIMARY KEY, unit TEXT, title TEXT, moment TEXT, prompt TEXT, concepts TEXT, ord INTEGER);
CREATE TABLE weeks (week INTEGER PRIMARY KEY, unit TEXT, note TEXT, start_date TEXT);
CREATE TABLE week_guides (week INTEGER, unit TEXT);
CREATE TABLE issues (kind TEXT, ref TEXT, message TEXT);
"""


# ---------------------------------------------------------------------------
# citirea datelor curate

def read_concepts() -> list[dict]:
    files = [CUR / "concepts.tsv"] if (CUR / "concepts.tsv").exists() else sorted((CUR / "parts").glob("*/concepts.tsv"))
    out, seen = [], {}
    for f in files:
        with f.open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh, delimiter="\t"):
                label = (row.get("label") or "").strip()
                if not label:
                    continue
                cid = concept_id(label)
                if cid in seen:
                    # duplicat între părți: păstrăm prima apariție, unim aliasurile și evidențele
                    prev = seen[cid]
                    prev["aliases"] += [a for a in split(row.get("aliases"), ";") if a not in prev["aliases"]]
                    prev["evidence"] += [e for e in split(row.get("evidence"), ",") if e not in prev["evidence"]]
                    continue
                c = {
                    "id": cid, "label": label, "level": int(row.get("level") or 2), "kind": (row.get("kind") or "noțiune").strip(),
                    "unit": (row.get("unit") or "").strip(), "evidence": split(row.get("evidence"), ","),
                    "definition": (row.get("definition") or "").strip(), "aliases": split(row.get("aliases"), ";"),
                    "man": (row.get("man") or "").strip(), "source_file": str(f.relative_to(ROOT)),
                }
                seen[cid] = c
                out.append(c)
    return out


def split(s, sep):
    return [x.strip() for x in (s or "").split(sep) if x.strip()]


def read_relations() -> list[tuple]:
    files = [CUR / "relations.txt"] if (CUR / "relations.txt").exists() else sorted((CUR / "parts").glob("*/relations.txt"))
    rels = []
    for f in files:
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split("|")]
            while len(parts) < 5:
                parts.append("")
            rels.append(tuple(parts[:5]))
    return rels


def read_prompts() -> dict:
    files = [CUR / "prompts.yaml"] if (CUR / "prompts.yaml").exists() else sorted((CUR / "parts").glob("*/prompts.yaml"))
    out: dict[str, list] = defaultdict(list)
    for f in files:
        data = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        for unit, items in data.items():
            out[unit].extend(items or [])
    return out


# ---------------------------------------------------------------------------
# detectarea definițiilor (spec §7, adaptat)

DEF_PREFIX = re.compile(r"(denumit[aăe]?|numit[aăe]?|se nume[sș]te|poart[aă] denumirea|termenul de|prin)\s*$", re.I)
DEF_VERB = re.compile(r"^\s*(\([^)]*\)\s*)?(sau\s+\S+\s+)?(reprezint[aă]|este|sunt|const[aă]|constituie|se define[sș]te|se nume[sș]te|desemneaz[aă]|[–=:-])", re.I)
SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-ZĂÂÎȘȚ„(])")


def sentences(text: str):
    pos = 0
    for part in SENT_SPLIT.split(text):
        start = text.find(part, pos)
        yield start, part
        pos = start + len(part)


def score_definition(sentence: str, s0: int, m_start: int, m_end: int, bold: bool, sec_title_starts: bool) -> tuple[int, bool]:
    before = sentence[: m_start - s0]
    after = sentence[m_end - s0:]
    score = 0
    positional = False
    if re.fullmatch(r"\s*([-•*►●▪–]\s*|\d+[.)]\s*)?(un|o|a|al|ale|cei|cele)?\s*", before, re.I):
        score += 2
        positional = True
    if DEF_PREFIX.search(before):
        score += 3
        positional = True
    if bold:
        score += 2
    if DEF_VERB.match(after) and not re.match(r"^\s*(lui|ei|ului|ilor|elor)\b", after):
        score += 3
        positional = True
    if sec_title_starts:
        score += 3
    if len(sentence) > 80:
        score += 1
    return score, positional


# ---------------------------------------------------------------------------

def build(out: Path, strict: bool = False) -> int:
    rdir = out / "reader"
    units = json.loads((rdir / "units.json").read_text(encoding="utf-8"))
    course = yaml.safe_load((CUR / "course.yaml").read_text(encoding="utf-8"))
    tmp = out / "content.sqlite.tmp"
    if tmp.exists():
        tmp.unlink()
    db = sqlite3.connect(tmp)
    db.executescript(SCHEMA)
    issues: list[tuple[str, str, str]] = []

    # --- săptămâni
    start = dt.date.fromisoformat(str(course["semester_start"]))
    unit_week = {}
    for w in course["weeks"]:
        sd = start + dt.timedelta(weeks=w["week"] - 1)
        db.execute("INSERT INTO weeks VALUES (?,?,?,?)", (w["week"], w.get("lab"), w.get("note", ""), sd.isoformat()))
        if w.get("lab"):
            unit_week.setdefault(w["lab"], w["week"])
    for wk, guides in (course.get("guides") or {}).items():
        for g in guides:
            db.execute("INSERT INTO week_guides VALUES (?,?)", (int(wk), g))

    # --- unități, secțiuni, blocuri
    reader: dict[str, dict] = {}
    for ord_, u in enumerate(units):
        d = json.loads((rdir / f"{u['id']}.json").read_text(encoding="utf-8"))
        reader[u["id"]] = d
        db.execute("INSERT INTO units VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                   (u["id"], u["kind"], u.get("number"), u["title"], u.get("short"), u.get("icon"),
                    unit_week.get(u["id"]), json.dumps(u["sources"]), json.dumps(u.get("authors", []), ensure_ascii=False),
                    len(d["blocks"]), ord_))
        first_block = {}
        for b in d["blocks"]:
            if b["t"] == "h":
                first_block.setdefault(b["sec"], b["i"])
        for k, s in enumerate(d["sections"]):
            db.execute("INSERT INTO sections VALUES (?,?,?,?,?,?,?,?)",
                       (u["id"], s["id"], s["parent"], s["title"], s["level"], s["part"], first_block.get(s["id"]), k))
        for b in d["blocks"]:
            data = {k: v for k, v in b.items() if k not in {"text"}}
            db.execute("INSERT INTO blocks VALUES (?,?,?,?,?,?,?)",
                       (u["id"], b["i"], b["t"], b.get("sec"), b.get("part"), json.dumps(data, ensure_ascii=False), b.get("text", "")))
            if b.get("text"):
                db.execute("INSERT INTO block_search VALUES (?,?,?,?)", (u["id"], b["i"], b.get("sec"), b["text"]))

    # --- pagini de manual
    man_ids = set()
    mdir = out / "man"
    if (mdir / "index.json").exists():
        for m in json.loads((mdir / "index.json").read_text(encoding="utf-8")):
            d = json.loads((mdir / f"{m['id']}.json").read_text(encoding="utf-8"))
            man_ids.add(d["id"])
            db.execute("INSERT INTO man_pages VALUES (?,?,?,?,?,?)",
                       (d["id"], d["name"], d["section"], d["summary"], d["command"], json.dumps(d, ensure_ascii=False)))
            db.execute("INSERT INTO man_search VALUES (?,?,?)", (d["id"], d["name"], " ".join(s["text"] for s in d["sections"])[:20000]))
    else:
        issues.append(("man", "-", "Paginile de manual lipsesc (extract_man nu a rulat în imaginea Linux)."))

    # --- concepte
    for p in PREDICATES:
        db.execute("INSERT INTO predicates VALUES (?,?,?,?)", p)
    concepts = read_concepts()
    by_label = {c["label"]: c for c in concepts}
    by_id = {c["id"]: c for c in concepts}
    unit_ids = {u["id"] for u in units}
    for c in concepts:
        if c["kind"] not in KINDS:
            issues.append(("concept", c["id"], f"tip necunoscut: {c['kind']}"))
        if c["unit"] not in unit_ids:
            issues.append(("concept", c["id"], f"unitate necunoscută: {c['unit']}"))
            c["unit"] = None
        man = c["man"]
        if man:
            mref = re.sub(r"^([\w.+\-]+)\((\w+)\)$", r"\1.\2", man.split(",")[0].strip())
            if mref not in man_ids and man_ids:
                issues.append(("man", c["id"], f"pagina {man} nu e în extragere"))
            c["man_id"] = mref
        db.execute("INSERT INTO concepts VALUES (?,?,?,?,?,?,?,?,?,?)",
                   (c["id"], c["label"], c["kind"], c["level"], c["unit"], c["definition"], c.get("man_id", ""),
                    "curat" if c["evidence"] else "editorial", "", "curat"))
        for a in c["aliases"]:
            db.execute("INSERT INTO aliases VALUES (?,?,?)", (c["id"], a, fold(a)))
        db.execute("INSERT INTO concept_search VALUES (?,?,?,?)", (c["id"], c["label"], " ".join(c["aliases"]), c["definition"]))

    matcher = Matcher.build(concepts)

    # --- apariții (în toate blocurile de laborator și ghid; codul inline contează ca „cod”)
    counts: Counter = Counter()
    occ_by_block: dict[tuple[str, int], list] = defaultdict(list)
    for uid, d in reader.items():
        for b in d["blocks"]:
            if b["t"] in {"fig"}:
                continue
            text = b.get("text", "")
            if not text:
                continue
            in_code = b["t"] == "code"
            for m in matcher.find(text, in_code=in_code):
                db.execute("INSERT INTO occurrences VALUES (?,?,?,?,?)", (m.concept, uid, b["i"], m.start, m.end))
                counts[(m.concept, uid)] += 1
                occ_by_block[(uid, b["i"])].append(m)
    for (cid, uid), n in counts.items():
        db.execute("INSERT INTO mentions VALUES (?,?,?)", (cid, uid, n))

    # --- evidențe
    sec_blocks: dict[tuple[str, str], list[dict]] = defaultdict(list)
    sec_titles: dict[tuple[str, str], str] = {}
    for uid, d in reader.items():
        for s in d["sections"]:
            sec_titles[(uid, s["id"])] = s["title"]
        for b in d["blocks"]:
            if b.get("sec"):
                sec_blocks[(uid, b["sec"])].append(b)
    # descendenții unei secțiuni contează ca aparținând ei
    children: dict[tuple[str, str], list[str]] = defaultdict(list)
    for uid, d in reader.items():
        for s in d["sections"]:
            if s["parent"]:
                children[(uid, s["parent"])].append(s["id"])

    def sec_and_desc(uid, sid):
        stack, out_ = [sid], []
        while stack:
            x = stack.pop()
            out_.append(x)
            stack.extend(children.get((uid, x), []))
        return out_

    for c in concepts:
        for ev in c["evidence"]:
            if "#" not in ev:
                issues.append(("evidence", c["id"], f"evidență fără secțiune: {ev}"))
                continue
            uid, sid = ev.split("#", 1)
            if (uid, sid) not in sec_titles:
                issues.append(("evidence", c["id"], f"secțiune inexistentă: {ev}"))
                continue
            ok = any(m.concept == c["id"] for s2 in sec_and_desc(uid, sid) for b in sec_blocks[(uid, s2)] for m in occ_by_block.get((uid, b["i"]), []))
            if not ok:
                # potrivire mai permisivă: și identificatorii „code_only” în afara codului
                ok = any(matcher.find(b.get("text", ""), in_code=True, only={c["id"]}) for s2 in sec_and_desc(uid, sid) for b in sec_blocks[(uid, s2)])
            db.execute("INSERT INTO concept_evidence VALUES (?,?,?,?)", (c["id"], uid, sid, int(ok)))
            if not ok:
                issues.append(("evidence", c["id"], f"termenul nu apare în {ev}"))

    # --- relații
    for (s, p, o, ev, origin) in read_relations():
        if s not in by_label or o not in by_label:
            issues.append(("relation", f"{s}|{p}|{o}", "capăt necunoscut"))
            continue
        if p not in {x[0] for x in PREDICATES}:
            issues.append(("relation", f"{s}|{p}|{o}", "predicat necunoscut"))
            continue
        uid, sid = (ev.split("#", 1) + [""])[:2] if ev else ("", "")
        db.execute("INSERT INTO relations (subj, pred, obj, unit, sec, origin) VALUES (?,?,?,?,?,?)",
                   (by_label[s]["id"], p, by_label[o]["id"], uid or None, sid or None, origin or "editorial"))

    # cicluri în ierarhie
    hier = defaultdict(set)
    for s, o in db.execute("SELECT subj, obj FROM relations r JOIN predicates p ON p.id=r.pred WHERE p.hierarchical=1"):
        hier[s].add(o)

    def has_cycle(start):
        seen, stack = set(), [start]
        while stack:
            x = stack.pop()
            for y in hier.get(x, ()):
                if y == start:
                    return True
                if y not in seen:
                    seen.add(y)
                    stack.append(y)
        return False

    for cid in list(hier):
        if has_cycle(cid):
            issues.append(("relation", cid, "ciclu în ierarhie"))

    # --- definiții găsite în text + secțiuni dedicate
    unit_order = {u["id"]: k for k, u in enumerate(units)}
    for c in concepts:
        cands = []
        for uid in sorted(reader, key=lambda x: unit_order[x]):
            d = reader[uid]
            for b in d["blocks"]:
                if b["t"] not in {"p", "li", "note"} or b.get("part") in {"problemset", "laborator"}:
                    continue
                ms = [m for m in occ_by_block.get((uid, b["i"]), []) if m.concept == c["id"]]
                if not ms:
                    continue
                text = b["text"]
                html = b.get("html", "")
                title = sec_titles.get((uid, b.get("sec")), "")
                title_starts = fold(title).startswith(fold(c["label"])[: max(4, len(c["label"]) - 2)])
                for s0, sent in sentences(text):
                    for m in ms:
                        if not (s0 <= m.start < s0 + len(sent)):
                            continue
                        bold = bool(re.search(r"<strong>[^<]*" + re.escape(text[m.start:m.end]) + r"[^<]*</strong>", html))
                        sc, pos = score_definition(sent, s0, m.start, m.end, bold, title_starts)
                        if sc >= 5 and pos:
                            cands.append((uid, b["i"], sent, sc, fold(sent).startswith(fold(text[m.start:m.end]))))
                        break
        first = next((x for x in cands if x[3] >= 6), None)
        if first:
            db.execute("INSERT INTO definitions VALUES (?,?,?,?,?,?)", (c["id"], "first", first[0], first[1], first[2], first[3]))
        starting = [x for x in cands if x[4]]
        if starting:
            best = max(starting, key=lambda x: x[3])
            if not first or (best[0], best[1]) != (first[0], first[1]):
                db.execute("INSERT INTO definitions VALUES (?,?,?,?,?,?)", (c["id"], "extended", best[0], best[1], best[2], best[3]))
        for x in cands[:8]:
            if first and (x[0], x[1]) == (first[0], first[1]):
                continue
            db.execute("INSERT INTO definitions VALUES (?,?,?,?,?,?)", (c["id"], "other", x[0], x[1], x[2], x[3]))
        # secțiuni al căror titlu începe cu termenul (cele mai de sus)
        forms = [c["label"]] + c["aliases"]
        for (uid, sid), title in sec_titles.items():
            ft = fold(title)
            if any(ft.startswith(fold(f)) and len(f) >= 3 for f in forms):
                db.execute("INSERT INTO dedicated_sections VALUES (?,?,?)", (c["id"], uid, sid))

    # --- arborele de învățare (un singur părinte, derivat din relațiile ierarhice)
    parent_of = {}
    for s, o in db.execute("SELECT subj, obj FROM relations r JOIN predicates p ON p.id=r.pred WHERE p.hierarchical=1 ORDER BY r.id"):
        if s not in parent_of and s != o:
            # părintele trebuie să fie introdus cel târziu în aceeași unitate
            su, ou = by_id[s]["unit"], by_id[o]["unit"]
            if su and ou and unit_order.get(ou, 0) <= unit_order.get(su, 0):
                parent_of[s] = o
    # fără cicluri
    for s in list(parent_of):
        seen = {s}
        x = parent_of.get(s)
        while x:
            if x in seen:
                parent_of.pop(s, None)
                break
            seen.add(x)
            x = parent_of.get(x)
    for k, c in enumerate(sorted(concepts, key=lambda c: (unit_order.get(c["unit"], 99), c["level"], c["label"].lower()))):
        db.execute("INSERT INTO learning_outline VALUES (?,?,?,?)", (c["id"], parent_of.get(c["id"]), c["unit"], k))

    # --- probleme: exercițiile din laborator/problemset (segmentate) + problemele curate
    n_problems = build_problems(db, reader, units, matcher, by_label, out, issues)

    # --- prompturi
    prompts = read_prompts()
    for uid, items in prompts.items():
        for k, p in enumerate(items):
            cons = [by_label[x]["id"] for x in (p.get("concepts") or []) if x in by_label]
            db.execute("INSERT INTO prompts (unit, title, moment, prompt, concepts, ord) VALUES (?,?,?,?,?,?)",
                       (uid, p.get("title", ""), p.get("when", ""), (p.get("prompt") or "").strip(), json.dumps(cons), k))

    # --- metadate + probleme de calitate
    built_at = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    version = os.environ.get("PCLP_CONTENT_VERSION") or dt.datetime.now(dt.timezone.utc).strftime("%Y.%m.%d-%H%M")
    db.execute("INSERT INTO meta VALUES ('built_at', ?)", (built_at,))
    db.execute("INSERT INTO meta VALUES ('version', ?)", (version,))
    db.execute("INSERT INTO meta VALUES ('schema', ?)", (str(CONTENT_SCHEMA),))
    db.execute("INSERT INTO meta VALUES ('course', ?)", (json.dumps(course, ensure_ascii=False, default=str),))
    # aliasuri scurte cu multe apariții
    for c in concepts:
        for a in c["aliases"]:
            if len(a) <= 3:
                n = sum(1 for (cid, _), _n in counts.items() if cid == c["id"])
                if n > 40:
                    issues.append(("alias", c["id"], f"alias scurt „{a}” cu multe apariții — posibile potriviri false"))
    for kind, ref, msg in issues:
        db.execute("INSERT INTO issues VALUES (?,?,?)", (kind, ref, msg))
    db.commit()

    # integritate
    bad = db.execute("PRAGMA integrity_check").fetchone()[0]
    fk = db.execute("PRAGMA foreign_key_check").fetchall()
    db.close()
    if bad != "ok" or fk:
        print("! integritate:", bad, fk[:5])
        return 1
    final = out / "content.sqlite"
    tmp.replace(final)
    (out / "course.json").write_text(json.dumps(course, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    (out / "bundle.json").write_text(json.dumps({
        "schema": CONTENT_SCHEMA, "version": version, "built_at": built_at,
        "commit": (os.environ.get("GITHUB_SHA") or "")[:7], "units": len(units), "concepts": len(concepts),
        "problems": n_problems,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    # imaginile
    media_src = ROOT / "sources" / "raw" / "media"
    if media_src.exists():
        shutil.copytree(media_src, out / "media", dirs_exist_ok=True)
    print(f"content.sqlite: {len(units)} unități, {len(concepts)} concepte, {n_problems} probleme, {len(issues)} observații")
    by_kind = Counter(k for k, _, _ in issues)
    if by_kind:
        print("  observații:", dict(by_kind))
    return 0 if not (strict and issues) else 2


def md(text: str) -> str:
    return markdown.markdown(text or "", extensions=["fenced_code", "tables", "sane_lists"])


def build_problems(db, reader, units, matcher, by_label, out: Path, issues) -> int:
    n = 0
    pdir = out / "problems"
    if pdir.exists():
        shutil.rmtree(pdir)
    pdir.mkdir(parents=True)
    ord_ = 0
    # 1) problemele curate (10 pe laborator)
    for yml in sorted((CUR / "problems").glob("*/*/problem.yaml")):
        try:
            p = yaml.safe_load(yml.read_text(encoding="utf-8"))
        except yaml.YAMLError as e:
            issues.append(("problem", str(yml), f"YAML invalid: {e}"))
            continue
        pid = p["id"]
        tests_src = yml.parent / "tests"
        n_tests = len(list(tests_src.glob("*.in"))) if tests_src.exists() else 0
        if tests_src.exists():
            shutil.copytree(tests_src, pdir / pid / "tests")
        (pdir / pid / "problem.json").write_text(json.dumps({"id": pid, "title": p.get("title"), "lab": p.get("lab")}, ensure_ascii=False), encoding="utf-8")
        stmt = p.get("statement", "")
        db.execute("INSERT INTO problems VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (pid, p["lab"], "curat", p.get("number"), p.get("title"), slug(pid), p.get("difficulty"),
                    p.get("estimated_minutes"), md(stmt), stmt, p.get("starter") or "",
                    json.dumps(p.get("hints") or [], ensure_ascii=False), json.dumps(p.get("pitfalls") or [], ensure_ascii=False),
                    None, None, n_tests, ord_))
        ord_ += 1
        tagged = set()
        for lab in p.get("concepts") or []:
            lab = "NULL" if lab is None else str(lab)  # YAML citește NULL nescris între ghilimele ca null
            cid = by_label[lab]["id"] if lab in by_label else None
            if not cid:
                # etichetă apropiată: potrivitorul recunoaște forma (flexionată, alias) pe aproape tot textul
                ms = matcher.find(lab, in_code=True)
                best = max(ms, key=lambda m: m.end - m.start, default=None)
                if best and (best.end - best.start) >= 0.7 * len(lab):
                    cid = best.concept
            if cid:
                if cid not in tagged:
                    tagged.add(cid)
                    db.execute("INSERT INTO problem_concepts VALUES (?,?,?)", (pid, cid, "curat"))
            else:
                issues.append(("problem", pid, f"concept necunoscut: {lab}"))
        for m in matcher.find(stmt, in_code=False):
            if m.concept not in tagged:
                tagged.add(m.concept)
                db.execute("INSERT INTO problem_concepts VALUES (?,?,?)", (pid, m.concept, "auto"))
        n += 1
    # 2) exercițiile existente din laborator și problemset
    for u in units:
        if u["kind"] != "lab":
            continue
        d = reader[u["id"]]
        for part, source in (("laborator", "laborator"), ("problemset", "problemset")):
            blocks = [b for b in d["blocks"] if b.get("part") == part]
            groups: list[list[dict]] = []
            for b in blocks:
                if b["t"] == "h" and b["lvl"] == 1:
                    continue
                starts = (b["t"] == "li" and b.get("depth", 0) == 0 and b.get("ordinal")) or b["t"] == "h"
                if starts or not groups:
                    groups.append([b])
                else:
                    groups[-1].append(b)
            num = 0
            for g in groups:
                text = " ".join(x.get("text", "") for x in g)
                if len(text) < 25:
                    continue
                num += 1
                head = g[0].get("text", "")
                m = re.match(r"\[\s*([^\]]+?)\s*\]", head)
                tag = m.group(1) if m and "BONUS" not in m.group(1).upper() else None
                title = tag or re.split(r"(?<=[.?!:])\s", head)[0]
                title = re.sub(r"^\[\s*BONUS\s*\]\s*", "", title)
                if len(title) > 80:
                    title = title[:77].rsplit(" ", 1)[0] + "…"
                pid = f"{u['id']}-{'ex' if source == 'laborator' else 'ps'}{num:02d}"
                db.execute("INSERT INTO problems VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                           (pid, u["id"], source, num, title, slug(pid + "-" + (tag or " ".join(head.split()[:4]))), None, None,
                            "", text, "", "[]", "[]", g[0]["i"], g[-1]["i"], 0, ord_))
                ord_ += 1
                seen = set()
                for mm in matcher.find(text, in_code=True):
                    if mm.concept not in seen:
                        seen.add(mm.concept)
                        db.execute("INSERT INTO problem_concepts VALUES (?,?,?)", (pid, mm.concept, "auto"))
                n += 1
    return n


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "content" / "build"))
    ap.add_argument("--strict", action="store_true")
    a = ap.parse_args()
    sys.exit(build(Path(a.out), a.strict))
