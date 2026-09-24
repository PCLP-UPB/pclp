"""Legătura portalului cu spațiul de lucru al studentului (~/work).

Portalul scrie în zona înregistrată DOAR:
  - folderele problemelor (cod) — ~/work/sapt-NN/<problemă>/
  - prompturile AI: .pclp/ai/portal.jsonl (apelurile făcute din portal) și .pclp/ai/external/*.md
Starea portalului (indicii văzute, întrebări, setări) stă în .pclp/state/, ignorat de git.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from django.conf import settings

from glosar import content as C
from glosar.content import slug

TEMPLATES_VSCODE = Path("/opt/pclp/templates/vscode")


def now_iso() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def ai_dir() -> Path:
    d = settings.PCLP_WORK / ".pclp" / "ai"
    d.mkdir(parents=True, exist_ok=True)
    return d


def log_ai(kind: str, info: dict, prompt: str, response, context: dict | None = None):
    rec = {"ts": now_iso(), "tool": "portal", "kind": kind, "provider": info.get("provider"), "model": info.get("model"),
           "prompt": prompt, "response": response, "context": context or {}}
    with (ai_dir() / "portal.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def save_external(tool: str, prompt: str, answer: str, notes: str, link: str, problem: str, week: int | None) -> Path:
    d = ai_dir() / "external"
    d.mkdir(parents=True, exist_ok=True)
    ts = dt.datetime.now().astimezone()
    name = f"{ts:%Y%m%d-%H%M%S}-{slug(tool)[:20]}.md"
    front = {"ts": ts.isoformat(timespec="seconds"), "tool": tool, "problem": problem or "", "week": week or "", "link": link or ""}
    body = ["---"] + [f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in front.items()] + ["---", "", "## Prompt", "", prompt.strip(), ""]
    if answer.strip():
        body += ["## Răspuns (rezumat sau copiat)", "", answer.strip(), ""]
    if notes.strip():
        body += ["## Ce am învățat / ce am făcut cu răspunsul", "", notes.strip(), ""]
    path = d / name
    path.write_text("\n".join(body), encoding="utf-8")
    return path


def external_prompts(limit: int = 50) -> list[dict]:
    d = ai_dir() / "external"
    out = []
    for p in sorted(d.glob("*.md"), reverse=True)[:limit]:
        txt = p.read_text(encoding="utf-8", errors="replace")
        meta = dict(re.findall(r"^(\w+): (.*)$", txt.split("---")[1], re.M)) if txt.startswith("---") else {}
        m = re.search(r"## Prompt\n\n(.*?)(\n## |\Z)", txt, re.S)
        out.append({"file": p.name, "tool": json.loads(meta.get("tool", '""')), "ts": json.loads(meta.get("ts", '""')),
                    "problem": json.loads(meta.get("problem", '""')), "prompt": (m.group(1).strip() if m else "")[:400]})
    return out


def portal_prompts(limit: int = 50) -> list[dict]:
    f = ai_dir() / "portal.jsonl"
    if not f.exists():
        return []
    rows = []
    for line in f.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]:
        try:
            rows.append(json.loads(line))
        except ValueError:
            pass
    return list(reversed(rows))


# ---------------------------------------------------------------------------
# foldere de probleme

def problem_week(p: dict) -> int:
    return C.week_of_unit(p["unit"]) or int(re.sub(r"\D", "", p["unit"]) or 0)


def problem_dir(p: dict) -> Path:
    return settings.PCLP_WORK / f"sapt-{problem_week(p):02d}" / p["slug"]


def problem_dir_in_container(p: dict) -> str:
    return f"{settings.PCLP_CODE_WORK}/sapt-{problem_week(p):02d}/{p['slug']}"


def code_url(p: dict) -> str:
    return f"{settings.PCLP_CODE_URL}/?folder={problem_dir_in_container(p)}"


STARTER_TEMPLATE = """/*
 * {title}
 * {pid} — săptămâna {week}
 *
 * Enunțul complet e în README.md și în portal: http://localhost:8000/problema/{pid}/
 * Compilare:  gcc -Wall -Wextra -std=c11 -g main.c -o main -lm
 * Testare:    pclp test
 */
#include <stdio.h>

int main(void)
{{
\t/* TODO */
\treturn 0;
}}
"""


def ensure_problem_dir(p: dict) -> Path:
    d = problem_dir(p)
    d.mkdir(parents=True, exist_ok=True)
    main = d / "main.c"
    if not main.exists() and not any(d.glob("*.c")):
        if p.get("starter"):
            header = f"/*\n * {p['title']}\n * {p['id']}\n * Compilare: gcc -Wall -Wextra -std=c11 -g main.c -o main -lm   |   Testare: pclp test\n */\n"
            main.write_text(header + p["starter"].rstrip() + "\n", encoding="utf-8")
        else:
            main.write_text(STARTER_TEMPLATE.format(title=p["title"], pid=p["id"], week=problem_week(p)), encoding="utf-8")
    readme = d / "README.md"
    if not readme.exists():
        text = p["statement_text"] or ""
        readme.write_text(f"# {p['title']}\n\n`{p['id']}`\n\n{text}\n", encoding="utf-8")
    vs = d / ".vscode"
    if TEMPLATES_VSCODE.exists() and not vs.exists():
        shutil.copytree(TEMPLATES_VSCODE, vs)
    return d


def read_code(p: dict, max_chars: int = 12000) -> str:
    d = problem_dir(p)
    if not d.exists():
        return ""
    parts = []
    for f in sorted(d.glob("*.[ch]")):
        parts.append(f"// ===== {f.name} =====\n" + f.read_text(encoding="utf-8", errors="replace"))
    return "\n\n".join(parts)[:max_chars]


# ---------------------------------------------------------------------------
# teste

def run_tests(p: dict) -> dict:
    d = problem_dir(p)
    if not d.exists():
        return {"error": "Folderul problemei nu există încă. Apasă „Începe problema”."}
    if shutil.which("pclp"):
        try:
            r = subprocess.run(["pclp", "test", p["id"], "--json"], cwd=d, capture_output=True, text=True, timeout=120)
            return json.loads(r.stdout)
        except (subprocess.TimeoutExpired, ValueError) as e:
            return {"error": f"Rularea testelor a eșuat: {e}"}
    return _run_tests_fallback(p, d)


def _run_tests_fallback(p: dict, d: Path) -> dict:
    """Rulare minimală în afara containerului (dezvoltare)."""
    tests = settings.PCLP_CONTENT / "problems" / p["id"] / "tests"
    res = {"problem": p["id"], "compiled": False, "compile_output": "", "tests": [], "passed": 0, "total": 0}
    with tempfile.TemporaryDirectory() as tmp:
        exe = Path(tmp) / "main"
        cc = subprocess.run(["gcc", "-Wall", "-Wextra", "-std=c11", "-g", "-o", str(exe), *map(str, sorted(d.glob("*.c"))), "-lm"],
                            capture_output=True, text=True)
        res["compile_output"] = cc.stderr[-4000:]
        if cc.returncode != 0:
            return res
        res["compiled"] = True
        for tin in sorted(tests.glob("*.in")):
            name = tin.stem
            run_dir = Path(tmp) / f"run-{name}"
            run_dir.mkdir()
            files = tests / f"{name}.files"
            if files.exists():
                shutil.copytree(files, run_dir, dirs_exist_ok=True)
            args_f = tests / f"{name}.args"
            args = args_f.read_text().splitlines() if args_f.exists() else []
            exp = (tests / f"{name}.out").read_text(errors="replace") if (tests / f"{name}.out").exists() else ""
            try:
                r = subprocess.run([str(exe), *args], stdin=tin.open("rb"), cwd=run_dir, capture_output=True, timeout=2)
                got, timeout = r.stdout.decode(errors="replace"), False
            except subprocess.TimeoutExpired:
                got, timeout = "", True
            norm = lambda s: "\n".join(line.rstrip() for line in s.rstrip().splitlines())  # noqa: E731
            ok = not timeout and norm(got) == norm(exp)
            res["tests"].append({"name": name, "ok": ok, "timeout": timeout, "expected": exp[:2000], "got": got[:2000],
                                 "stdin": tin.read_text(errors="replace")[:1000]})
        res["total"] = len(res["tests"])
        res["passed"] = sum(t["ok"] for t in res["tests"])
    return res


# ---------------------------------------------------------------------------
# identitatea studentului (pentru arhivă)

def student() -> dict:
    try:
        return json.loads((settings.PCLP_WORK / ".pclp" / "student.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def set_student(name: str, email: str, group: str) -> str | None:
    """Scrie identitatea prin `pclp init` (actualizează și autorul git); întoarce eroarea, dacă există."""
    if shutil.which("pclp"):
        r = subprocess.run(["pclp", "init", "--auto", "--name", name, "--email", email, "--group", group],
                           cwd=settings.PCLP_WORK, capture_output=True, text=True, timeout=60)
        return None if r.returncode == 0 else (r.stderr or r.stdout)[-500:]
    d = settings.PCLP_WORK / ".pclp"
    d.mkdir(parents=True, exist_ok=True)
    data = student()
    data.update({"name": name, "email": email, "group": group})
    (d / "student.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return None
