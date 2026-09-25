#!/usr/bin/env python3
"""Verifică toate soluțiile de referință pe testele problemelor (doar pentru profesor).

    python3 tools/check_solutions.py [--solutions ../pclp-solutions] [lab05 ...]

Soluțiile stau în repo-ul privat PCLP-UPB/pclp-solutions, clonat implicit alături de acest repo
(../pclp-solutions) sau indicat cu --solutions / variabila PCLP_SOLUTIONS.
Compilează fiecare <soluții>/<lab>/<id>/solution.c cu -Wall -Wextra -std=c11 și îl rulează
pe content/curated/problems/<lab>/<id>/tests exact ca `pclp test` (director temporar,
NN.files copiate, argumente din NN.args, stdin din NN.in; se compară doar stdout).
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROBLEMS = ROOT / "content" / "curated" / "problems"
SOLUTIONS = Path(os.environ.get("PCLP_SOLUTIONS", ROOT.parent / "pclp-solutions"))


def norm(s: str) -> str:
    return "\n".join(line.rstrip() for line in s.rstrip().splitlines())


def check(pdir: Path) -> tuple[int, int, str]:
    sol = SOLUTIONS / pdir.parent.name / pdir.name / "solution.c"
    if not sol.exists():
        return 0, 0, "lipsește solution.c"
    with tempfile.TemporaryDirectory() as tmp:
        exe = Path(tmp) / "sol"
        cc = subprocess.run(["gcc", "-Wall", "-Wextra", "-std=c11", "-O0", "-o", str(exe), str(sol), "-lm"],
                            capture_output=True, text=True)
        if cc.returncode != 0:
            return 0, 0, "nu compilează:\n" + cc.stderr[-800:]
        warn = "warning-uri: " + cc.stderr.strip().splitlines()[0] if cc.stderr.strip() else ""
        ok = total = 0
        fails = []
        for tin in sorted((pdir / "tests").glob("*.in")):
            name = tin.stem
            total += 1
            run = Path(tmp) / f"r{name}"
            run.mkdir()
            files = tin.with_name(f"{name}.files")
            if files.exists():
                shutil.copytree(files, run, dirs_exist_ok=True)
            args_f = tin.with_name(f"{name}.args")
            args = args_f.read_text().splitlines() if args_f.exists() else []
            try:
                r = subprocess.run([str(exe), *args], stdin=tin.open("rb"), cwd=run, capture_output=True, timeout=5)
                got = r.stdout.decode(errors="replace")
            except subprocess.TimeoutExpired:
                got = "<timeout>"
            out_f = tin.with_name(f"{name}.out")
            if not out_f.exists():
                fails.append(f"{name}(lipsește .out)")
                continue
            exp = out_f.read_text(errors="replace")
            if norm(got) == norm(exp):
                ok += 1
            else:
                fails.append(name)
        msg = warn + (f" eșuate: {', '.join(fails)}" if fails else "")
        return ok, total, msg


def main():
    global SOLUTIONS
    ap = argparse.ArgumentParser(description="Verifică soluțiile de referință pe testele problemelor.")
    ap.add_argument("labs", nargs="*", help="ex. lab05 lab06 (implicit toate)")
    ap.add_argument("--solutions", help="directorul cu soluții (implicit ../pclp-solutions)")
    a = ap.parse_args()
    if a.solutions:
        SOLUTIONS = Path(a.solutions)
    if not SOLUTIONS.is_dir():
        sys.exit(f"Nu găsesc soluțiile în {SOLUTIONS}. Clonează PCLP-UPB/pclp-solutions alături sau folosește --solutions.")
    labs = a.labs or sorted(p.name for p in PROBLEMS.iterdir() if p.is_dir())
    bad = 0
    count = 0
    for lab in labs:
        for pdir in sorted((PROBLEMS / lab).iterdir()):
            if not (pdir / "problem.yaml").exists():
                continue
            count += 1
            ok, total, msg = check(pdir)
            status = "OK " if total and ok == total and not msg else "ERR"
            if status == "ERR":
                bad += 1
            print(f"{status} {pdir.name:45s} {ok}/{total} {msg}")
    print(f"\n{count - bad}/{count} probleme în regulă")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
