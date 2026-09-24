"""Reconstruiește tot conținutul: cititor → pagini de manual → baza de date.

    python content/pipeline/build.py --out content/build [--skip-man] [--strict]

În imaginea Docker rulează la build (are mandoc și man-pages). Pe alt sistem, paginile
de manual deja extrase în <out>/man sunt refolosite.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def run(script: str, *args: str) -> int:
    print(f"== {script}")
    return subprocess.call([sys.executable, str(HERE / script), *args])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HERE.parents[1] / "content" / "build"))
    ap.add_argument("--skip-man", action="store_true")
    ap.add_argument("--strict", action="store_true")
    a = ap.parse_args()
    if run("extract_reader.py", "--out", a.out):
        sys.exit(1)
    if not a.skip_man:
        run("extract_man.py", "--out", a.out)
    args = ["--out", a.out] + (["--strict"] if a.strict else [])
    sys.exit(run("build_database.py", *args))


if __name__ == "__main__":
    main()
