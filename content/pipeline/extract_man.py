"""Extrage paginile de manual (Linux man-pages) relevante pentru curs, ca unități de cititor.

Rulează în imaginea Docker (are nevoie de `man` și `mandoc`). Candidații vin din:
  - coloana `man` din concepts.tsv (ex. `malloc(3)`, `gcc(1)`, `stdio.h(0p)`);
  - identificatorii apelați în codul din laboratoare (`nume(`) care au pagină în secțiunea 3.

Ieșire: <out>/man/<nume>.<secțiune>.json și <out>/man/index.json
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import re
import shutil
import subprocess
from pathlib import Path

from bs4 import BeautifulSoup, NavigableString, Tag

ROOT = Path(__file__).resolve().parents[2]
MAN_ROOT = Path("/usr/share/man")

# Paginile de bază incluse mereu (pe lângă cele găsite automat).
BASE = [
    "printf(3)", "scanf(3)", "puts(3)", "putchar(3)", "getchar(3)", "fgets(3)", "gets(3)",
    "malloc(3)", "calloc(3)", "realloc(3)", "free(3)",
    "strlen(3)", "strcpy(3)", "strncpy(3)", "strcat(3)", "strcmp(3)", "strncmp(3)", "strchr(3)", "strstr(3)",
    "strtok(3)", "strdup(3)", "memcpy(3)", "memmove(3)", "memset(3)", "memcmp(3)",
    "atoi(3)", "strtol(3)", "abs(3)", "rand(3)", "qsort(3)", "bsearch(3)", "exit(3)",
    "isalpha(3)", "toupper(3)",
    "sqrt(3)", "pow(3)", "floor(3)", "ceil(3)", "fabs(3)",
    "fopen(3)", "fclose(3)", "fread(3)", "fwrite(3)", "fseek(3)", "ftell(3)", "feof(3)", "fflush(3)", "fprintf(3)", "fscanf(3)",
    "stdarg(3)", "assert(3)", "errno(3)", "perror(3)",
    "gcc(1)", "gdb(1)", "valgrind(1)", "make(1)",
    "stdio.h(0p)", "stdlib.h(0p)", "string.h(0p)", "math.h(0p)", "ctype.h(0p)", "stdarg.h(0p)", "limits.h(0p)", "stdint.h(0p)",
]

KEEP_SECTIONS = {
    "NAME", "SYNOPSIS", "DESCRIPTION", "RETURN VALUE", "ERRORS", "NOTES", "BUGS", "EXAMPLES", "EXAMPLE",
    "SEE ALSO", "CAVEATS", "APPLICATION USAGE", "OPTIONS", "HISTORY", "STANDARDS", "VERSIONS",
}
TITLES_RO = {
    "NAME": "NAME — nume", "SYNOPSIS": "SYNOPSIS — sinopsis", "DESCRIPTION": "DESCRIPTION — descriere",
    "RETURN VALUE": "RETURN VALUE — valoarea returnată", "ERRORS": "ERRORS — erori", "NOTES": "NOTES — observații",
    "BUGS": "BUGS — probleme cunoscute", "EXAMPLES": "EXAMPLES — exemple", "EXAMPLE": "EXAMPLE — exemplu",
    "SEE ALSO": "SEE ALSO — vezi și", "CAVEATS": "CAVEATS — atenție", "OPTIONS": "OPTIONS — opțiuni",
    "APPLICATION USAGE": "APPLICATION USAGE — utilizare", "STANDARDS": "STANDARDS — standarde",
    "HISTORY": "HISTORY — istoric", "VERSIONS": "VERSIONS — versiuni",
}
# pagini foarte lungi: păstrăm doar primele secțiuni utile
MAX_SECTION_CHARS = 60000


def parse_ref(ref: str):
    m = re.fullmatch(r"\s*([\w.+\-]+)\((\w+)\)\s*", ref)
    return (m.group(1), m.group(2)) if m else None


def man_path(name: str, sec: str) -> Path | None:
    """Caută direct în /usr/share/man (în imaginile Ubuntu minimizate `man` e un stub)."""
    for cand in (MAN_ROOT / f"man{sec}" / f"{name}.{sec}.gz", MAN_ROOT / f"man{sec}" / f"{name}.{sec}",
                 MAN_ROOT / f"man{sec[0]}" / f"{name}.{sec}.gz",
                 # manpages-posix-dev pe Debian/Ubuntu: stdio.h.7posix, printf.3posix
                 MAN_ROOT / "man7" / f"{name}.7posix.gz", MAN_ROOT / f"man{sec[0]}" / f"{name}.{sec[0]}posix.gz"):
        if cand.exists():
            return cand
    return None


def read_source(path: Path) -> str:
    data = gzip.open(path, "rt", errors="replace").read() if path.suffix == ".gz" else path.read_text(errors="replace")
    m = re.match(r"\.so\s+(\S+)", data.strip())
    if m:  # pagină-alias: .so man3/malloc.3
        target = MAN_ROOT / m.group(1)
        for cand in (target, Path(str(target) + ".gz")):
            if cand.exists():
                return read_source(cand)
    return data


def render(path: Path) -> str:
    src = read_source(path)
    out = subprocess.run(["mandoc", "-T", "html", "-O", "fragment"], input=src, capture_output=True, text=True, timeout=60)
    return out.stdout


def man_link(name: str, sec: str) -> str:
    return f"/man/{name}.{sec}/"


def clean(node: Tag, known: set[str]) -> str:
    """HTML mandoc → HTML simplu (b, i, code, pre, a, ul/ol/li, dl/dt/dd, p, br, table)."""
    allowed = {"b", "i", "em", "strong", "code", "pre", "a", "ul", "ol", "li", "dl", "dt", "dd", "p", "br", "table", "tr", "td", "th", "tbody", "var", "sup", "sub"}

    def walk(n) -> str:
        if isinstance(n, NavigableString):
            return str(n).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        if not isinstance(n, Tag):
            return ""
        inner = "".join(walk(c) for c in n.children)
        name = n.name
        cls = " ".join(n.get("class", []))
        if name == "a":
            href = n.get("href", "")
            m = re.match(r"^(?:\.\./)?(?:man\d\w*/)?([\w.+\-]+)\.(\d\w*)\.html$", href) or re.match(r"^([\w.+\-]+)\((\w+)\)$", n.get_text())
            if "Xr" in cls:
                mm = re.match(r"([\w.+\-]+)\((\w+)\)", n.get_text())
                if mm and f"{mm.group(1)}.{mm.group(2)}" in known:
                    return f'<a href="{man_link(mm.group(1), mm.group(2))}">{inner}</a>'
                return f"<b>{inner}</b>"
            if href.startswith("#"):
                return inner
            if href.startswith("http"):
                return f'<a href="{href}" target="_blank" rel="noopener" class="ext">{inner}</a>'
            return inner
        if name in {"div", "span", "section", "h2", "h1"}:
            if "Bd-indent" in cls or "Bd" in cls.split():
                return inner
            if "Pp" in cls:
                return f"<p>{inner}</p>"
            return inner
        if name in allowed:
            if name == "var":
                name = "i"
            return f"<{name}>{inner}</{name}>"
        return inner

    html = walk(node)
    html = re.sub(r"\n{3,}", "\n\n", html)
    return html.strip()


def extract(name: str, sec: str, known: set[str]) -> dict | None:
    path = man_path(name, sec)
    if not path:
        return None
    html = render(path)
    if not html.strip():
        return None
    soup = BeautifulSoup(html, "lxml")
    sections = []
    summary = ""
    for s in soup.find_all("section", class_="Sh"):
        h = s.find("h1")
        title = re.sub(r"[\s_\xa0]+", " ", (h.get("id") or h.get_text(" ", strip=True)) if h else "").strip().upper()
        if h:
            h.extract()
        if title not in KEEP_SECTIONS:
            continue
        body = clean(s, known)
        if title == "SYNOPSIS":
            # detaliile glibc („Feature Test Macro Requirements”) nu sunt utile la anul I
            cut = body.find("Feature Test Macro")
            if cut > 0:
                body = body[:body.rfind("<", 0, cut)].rstrip()
                body = re.sub(r"(<p>\s*</p>\s*)+$", "", body)
        body = re.sub(r"<pre>(.*?)</pre>", lambda m: "<pre>" + re.sub(r"\n{2,}", "\n", re.sub(r"<br\s*/?>\s*(</br>)?", "\n", m.group(1))).strip("\n") + "</pre>", body, flags=re.S)
        body = re.sub(r"<p>\s*</p>", "", body)
        if len(body) > MAX_SECTION_CHARS:
            body = body[:MAX_SECTION_CHARS] + "\n<p><em>[… secțiune scurtată; vezi pagina completă cu comanda man]</em></p>"
        text = BeautifulSoup(body, "lxml").get_text(" ")
        if title == "NAME":
            summary = re.sub(r"\s+", " ", text).strip()
        sid = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
        sections.append({"id": sid, "title": TITLES_RO.get(title, title), "html": body, "text": re.sub(r"\s+", " ", text).strip()})
    if not sections:
        return None
    return {"id": f"{name}.{sec}", "name": name, "section": sec, "summary": summary,
            "command": f"man {sec} {name}", "sections": sections}


def candidates(content_build: Path) -> list[tuple[str, str]]:
    refs: list[str] = list(BASE)
    for tsv in list((ROOT / "content" / "curated").glob("concepts.tsv")) + list((ROOT / "content" / "curated" / "parts").glob("*/concepts.tsv")):
        with tsv.open(encoding="utf-8") as f:
            for row in csv.DictReader(f, delimiter="\t"):
                for r in (row.get("man") or "").split(","):
                    if r.strip():
                        refs.append(r.strip())
    # funcții apelate în codul laboratoarelor
    for p in (content_build / "reader").glob("*.json"):
        if p.name == "units.json":
            continue
        d = json.loads(p.read_text(encoding="utf-8"))
        for b in d["blocks"]:
            if b["t"] == "code" and b.get("lang") in ("c", "", None):
                for m in re.finditer(r"\b([a-z_][a-z0-9_]{1,20})\s*\(", b["text"]):
                    refs.append(f"{m.group(1)}(3)")
    seen, out = set(), []
    for r in refs:
        pr = parse_ref(r)
        if pr and pr not in seen:
            seen.add(pr)
            out.append(pr)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "content" / "build"))
    args = ap.parse_args()
    out = Path(args.out)
    if not shutil.which("mandoc") or not MAN_ROOT.exists():
        print("! mandoc/man lipsesc: sar peste paginile de manual")
        return
    mdir = out / "man"
    mdir.mkdir(parents=True, exist_ok=True)
    cands = candidates(out)
    # mai întâi aflăm ce pagini există, ca să putem lega „SEE ALSO” doar spre pagini incluse
    existing = [(n, s) for n, s in cands if man_path(n, s)]
    known = {f"{n}.{s}" for n, s in existing}
    index = []
    for n, s in existing:
        d = extract(n, s, known)
        if not d:
            continue
        (mdir / f"{d['id']}.json").write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        index.append({"id": d["id"], "name": n, "section": s, "summary": d["summary"]})
    index.sort(key=lambda x: (x["section"], x["name"]))
    (mdir / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"man: {len(index)} pagini (din {len(cands)} candidați)")


if __name__ == "__main__":
    main()
