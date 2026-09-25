"""Împachetează conținutul construit pentru actualizarea automată din containerele studenților.

    python content/pipeline/package.py --build content/build --out dist [--changes "text"]

Scrie dist/content.tar.gz (content.sqlite, bundle.json, course.json, media/, problems/) și
dist/content.json (manifestul citit de container: versiune, dată, schemă, SHA-256).
"""
import argparse
import hashlib
import json
import tarfile
from pathlib import Path

INCLUDE = ("content.sqlite", "bundle.json", "course.json", "media", "problems")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", default="content/build")
    ap.add_argument("--out", default="dist")
    ap.add_argument("--changes", action="append", default=[], help="rând pentru lista de modificări (repetabil)")
    a = ap.parse_args()
    build, out = Path(a.build), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    bundle = json.loads((build / "bundle.json").read_text(encoding="utf-8"))
    tgz = out / "content.tar.gz"

    def clean(ti: tarfile.TarInfo):
        ti.uid = ti.gid = 0
        ti.uname = ti.gname = ""
        ti.mtime = 0
        return ti

    with tarfile.open(tgz, "w:gz") as tar:
        for name in INCLUDE:
            p = build / name
            if p.exists():
                tar.add(p, arcname=name, filter=clean)
    digest = hashlib.sha256(tgz.read_bytes()).hexdigest()
    manifest = {**bundle, "asset": tgz.name, "sha256": digest, "size": tgz.stat().st_size,
                "changes": [c for c in a.changes if c.strip()]}
    (out / "content.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{tgz} ({tgz.stat().st_size // 1024} KiB)  versiunea {bundle['version']}  sha256 {digest[:16]}…")


if __name__ == "__main__":
    main()
