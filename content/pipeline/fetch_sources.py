"""Descarcă (din nou) sursele laboratoarelor în sources/raw/.

    python3 content/pipeline/fetch_sources.py

- OCW (DokuWiki): exportul „plain XHTML” al fiecărei pagini (exportul raw e dezactivat pe server);
- acs-pclp.github.io: paginile de laborator și problemset-urile (HTML generat de Jekyll).
Imaginile se descarcă la extracție (extract_reader.py), în sources/raw/media/.
"""
import urllib.request
from pathlib import Path

RAW = Path(__file__).resolve().parents[2] / "sources" / "raw"
OCW_PAGES = [
    "coding-style", "vm-setup", "laboratoare/suport_teoretic/introducere-unelte-de-programare-configurare",
    *[f"laboratoare/lab{i:02d}" for i in range(1, 13)], "laboratoare/lab12-bitset-example",
    "tutoriale/code_understanding", "tutoriale/debugging", "tutoriale/good_practices", "tutoriale/logging",
    "tutoriale/read_docs", "tutoriale/unittests",
]


def get(url: str, dst: Path):
    req = urllib.request.Request(url, headers={"User-Agent": "pclp-content/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read()
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(data)
    print(f"{len(data):8d}  {dst.relative_to(RAW)}")


def main():
    for p in OCW_PAGES:
        get(f"https://ocw.cs.pub.ro/courses/_export/xhtml/programare/{p}", RAW / "ocw" / (p.replace("/", "_") + ".html"))
    for i in range(1, 13):
        get(f"https://acs-pclp.github.io/laboratoare/{i:02d}.html", RAW / "labs" / f"{i:02d}.html")
        if i > 1:
            get(f"https://acs-pclp.github.io/problemset/{i:02d}.html", RAW / "problemset" / f"{i:02d}.html")


if __name__ == "__main__":
    main()
