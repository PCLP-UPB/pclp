"""Extrage conținutul pentru cititor din paginile HTML descărcate (OCW + acs-pclp).

Ieșire: <out>/reader/<unit>.json și <out>/reader/units.json

Un bloc are forma:
  {"i": n, "t": "h|p|li|code|note|table|fig|details", "html": ..., "text": ...,
   "sec": <id secțiune>, "part": "teorie|laborator|problemset|ghid",
   "lvl"?: nivel titlu, "depth"?: adâncime listă, "ordinal"?: număr listă,
   "lang"?: limbaj cod, "kind"?: tip notă, "src"?: imagine}
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path

import yaml
from bs4 import BeautifulSoup, NavigableString, Tag

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "sources" / "raw"
MEDIA = RAW / "media"
OCW = "https://ocw.cs.pub.ro"
ACS = "https://acs-pclp.github.io"

INLINE_OK = {"strong", "b", "em", "i", "code", "a", "sub", "sup", "br", "kbd", "u", "del"}


def slug(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s.lower()).strip("-")
    return s or "x"


def norm_text(s: str) -> str:
    s = s.replace("ş", "ș").replace("Ş", "Ș").replace("ţ", "ț").replace("Ţ", "Ț")
    s = s.replace(" ", " ")
    return s


def ws(s: str) -> str:
    return re.sub(r"\s+", " ", norm_text(s)).strip()


# ---------------------------------------------------------------------------
# legături

LAB_RE = re.compile(r"/courses/programare/laboratoare/(lab\d\d)(?:[?&].*?)?(?:#(.*))?$")
GUIDE_MAP = {
    "coding-style": "coding-style",
    "tutoriale/good_practices": "good-practices",
    "tutoriale/debugging": "debugging",
    "tutoriale/read_docs": "read-docs",
    "tutoriale/code_understanding": "code-understanding",
    "tutoriale/logging": "logging",
    "tutoriale/unittests": "unit-tests",
    "vm-setup": "vm-setup",
}


def rewrite_href(href: str, base: str) -> tuple[str, bool]:
    """Întoarce (href, extern)."""
    href = href.replace("&amp;", "&")
    if href.startswith("mailto:"):
        return "", True
    if href.startswith("#"):
        return "#s-" + href[1:], False
    full = urllib.parse.urljoin(base, href)
    p = urllib.parse.urlparse(full)
    if p.netloc.endswith("ocw.cs.pub.ro"):
        m = LAB_RE.search(p.path + ("#" + p.fragment if p.fragment else ""))
        if m:
            frag = f"#s-{m.group(2)}" if m.group(2) else ""
            return f"/carte/{m.group(1)}/{frag}", False
        for k, v in GUIDE_MAP.items():
            if p.path.rstrip("/").endswith("/programare/" + k):
                return f"/carte/{v}/" + (f"#s-{p.fragment}" if p.fragment else ""), False
    if p.netloc == "acs-pclp.github.io":
        m = re.search(r"/(laboratoare|problemset)/(\d\d)", p.path)
        if m:
            anchor = "#s-lab-exercitii" if m.group(1) == "laboratoare" else "#s-problemset"
            return f"/carte/lab{m.group(2)}/{anchor}", False
    return full, True


# ---------------------------------------------------------------------------
# imagini

def fetch_media(src: str, base: str) -> str | None:
    full = urllib.parse.urljoin(base, src.replace("&amp;", "&"))
    # DokuWiki: fetch.php?media=<url sau id>
    q = urllib.parse.parse_qs(urllib.parse.urlparse(full).query)
    name_hint = q.get("media", [full])[0]
    ext = Path(urllib.parse.urlparse(name_hint).path).suffix.lower()
    if ext not in {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"}:
        ext = ".png"
    h = hashlib.sha1(full.encode()).hexdigest()[:12]
    MEDIA.mkdir(parents=True, exist_ok=True)
    dst = MEDIA / f"{h}{ext}"
    if not dst.exists():
        try:
            req = urllib.request.Request(full, headers={"User-Agent": "pclp-content/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                data = r.read()
            if len(data) < 100:
                return None
            dst.write_bytes(data)
        except Exception as e:  # noqa: BLE001
            print(f"  ! imagine indisponibilă {full}: {e}")
            return None
    return dst.name


# ---------------------------------------------------------------------------
# HTML inline curat

def clean_inline(node: Tag, base: str) -> str:
    out: list[str] = []

    def walk(n):
        if isinstance(n, NavigableString):
            if n.__class__.__name__ in {"Comment", "Doctype"}:
                return
            t = str(n)
            out.append(t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
            return
        if not isinstance(n, Tag):
            return
        name = n.name
        if name in {"script", "style"}:
            return
        if name == "img":
            return
        if name in INLINE_OK:
            if name == "b":
                name = "strong"
            if name == "i":
                name = "em"
            if name == "a":
                href = n.get("href") or ""
                new, ext = rewrite_href(href, base) if href else ("", True)
                if not new:
                    for c in n.children:
                        walk(c)
                    return
                attrs = f' href="{new}"' + (' target="_blank" rel="noopener" class="ext"' if ext else "")
                out.append(f"<a{attrs}>")
                for c in n.children:
                    walk(c)
                out.append("</a>")
                return
            if name == "br":
                out.append("<br>")
                return
            out.append(f"<{name}>")
            for c in n.children:
                walk(c)
            out.append(f"</{name}>")
            return
        for c in n.children:
            walk(c)

    for c in node.children:
        walk(c)
    html = norm_text("".join(out))
    html = re.sub(r"[ \t\r\n]+", " ", html).strip()
    html = re.sub(r"(<br>\s*)+$", "", html)
    return html


# ---------------------------------------------------------------------------
# extracția blocurilor

class Builder:
    def __init__(self, unit: str, base: str, part: str):
        self.unit = unit
        self.base = base
        self.part = part
        self.blocks: list[dict] = []
        self.sections: list[dict] = []
        self.sec_stack: list[tuple[int, str]] = []
        self.used_ids: set[str] = set()

    @property
    def cur_sec(self):
        return self.sec_stack[-1][1] if self.sec_stack else None

    def add(self, **b):
        b.setdefault("sec", self.cur_sec)
        b.setdefault("part", self.part)
        if "html" in b and "text" not in b:
            b["text"] = ws(BeautifulSoup(b["html"], "html.parser").get_text(" "))
        if b["t"] in {"p", "li"} and not b.get("text"):
            return b
        self.blocks.append(b)
        return b

    def heading(self, level: int, title: str, sid: str | None = None):
        sid = sid or slug(title)
        base_id = sid
        k = 2
        while sid in self.used_ids:
            sid = f"{base_id}-{k}"
            k += 1
        self.used_ids.add(sid)
        while self.sec_stack and self.sec_stack[-1][0] >= level:
            self.sec_stack.pop()
        parent = self.cur_sec
        self.sec_stack.append((level, sid))
        self.sections.append({"id": sid, "parent": parent, "title": title, "level": level, "part": self.part})
        self.add(t="h", lvl=level, html=title.replace("<", "&lt;"), text=title, sec=sid, anchor=sid)
        return sid

    # -- elemente bloc
    def block(self, el: Tag, depth: int = 0):
        name = el.name
        cls = " ".join(el.get("class", []))
        if name in {"script", "style"} or "toc" in cls.split() or el.get("id") == "dw__toc":
            return
        if re.fullmatch(r"h[1-6]", name or ""):
            return  # tratate de apelant
        if name == "p":
            imgs = el.find_all("img")
            for img in imgs:
                self.figure(img)
            # un <p> DokuWiki poate conține div-uri (note); le tratăm separat
            inner_divs = el.find_all("div", recursive=False)
            if inner_divs:
                for c in el.children:
                    if isinstance(c, Tag) and c.name == "div":
                        self.block(c, depth)
                    elif isinstance(c, Tag) and c.name == "p":
                        self.block(c, depth)
                rest = BeautifulSoup("<p></p>", "lxml").p
                for c in list(el.children):
                    if isinstance(c, NavigableString) or (isinstance(c, Tag) and c.name not in {"div", "p"}):
                        rest.append(c.__copy__() if isinstance(c, NavigableString) else c)
                html = clean_inline(rest, self.base)
                if html:
                    self.add(t="p", html=html)
                return
            html = clean_inline(el, self.base)
            if html:
                self.add(t="p", html=html)
            return
        if name in {"ul", "ol"}:
            start = int(el.get("start", 1) or 1)
            n = start
            for li in el.find_all("li", recursive=False):
                self.list_item(li, depth, n if name == "ol" else None)
                n += 1
            return
        if name == "pre":
            self.code(el)
            return
        if name == "div" and ("highlighter-rouge" in cls or "highlight" in cls.split()):
            pre = el.find("pre")
            if pre:
                lang = ""
                m = re.search(r"language-(\w+)", cls)
                if m:
                    lang = m.group(1)
                self.code(pre, lang)
            return
        if name == "div" and re.match(r"note", cls):
            kind = cls.split()[0].replace("note", "") or "classic"
            sub = Builder(self.unit, self.base, self.part)
            sub.sec_stack = list(self.sec_stack)
            sub.flow(el)
            if not sub.blocks:
                html = clean_inline(el, self.base)
                if html:
                    sub.add(t="p", html=html)
            inner = []
            for b in sub.blocks:
                if b["t"] == "code":
                    inner.append({"t": "code", "html": b["html"], "lang": b.get("lang", "")})
                elif b["t"] == "fig":
                    inner.append(b)
                else:
                    inner.append({"t": b["t"], "html": b["html"], "depth": b.get("depth", 0), "ordinal": b.get("ordinal")})
            text = " ".join(b.get("text", "") for b in sub.blocks)
            self.add(t="note", kind=kind, inner=inner, html="", text=ws(text))
            return
        if name == "table":
            self.table(el)
            return
        if name == "details":
            summary = el.find("summary")
            title = ws(summary.get_text()) if summary else "Detalii"
            if summary:
                summary.extract()
            sub = Builder(self.unit, self.base, self.part)
            sub.sec_stack = list(self.sec_stack)
            for c in el.children:
                if isinstance(c, Tag):
                    sub.block(c)
            self.add(t="details", title=title, inner=[{k: v for k, v in b.items() if k not in {"sec", "part"}} for b in sub.blocks],
                     html="", text=title + " " + " ".join(b.get("text", "") for b in sub.blocks))
            return
        if name == "img":
            self.figure(el)
            return
        if name in {"div", "section", "article", "main", "span", "blockquote", "center"}:
            if "hiddenHead" in cls:
                t = ws(el.get_text())
                if t:
                    self.add(t="p", html=f"<strong>{t}</strong>")
                return
            if name == "blockquote":
                html = clean_inline(el, self.base)
                if html:
                    self.add(t="p", html=html, quote=True)
                return
            self.walk_children(el, depth)
            return
        if name == "hr":
            return
        if name == "dl":
            for dt in el.find_all(["dt", "dd"], recursive=False):
                html = clean_inline(dt, self.base)
                if html:
                    self.add(t="p", html=("<strong>" + html + "</strong>") if dt.name == "dt" else html)
            return
        # element necunoscut: text inline
        html = clean_inline(el, self.base)
        if html:
            self.add(t="p", html=html)

    def list_item(self, li: Tag, depth: int, ordinal):
        # conținutul inline al elementului + sub-blocuri
        inline = BeautifulSoup("<div></div>", "lxml").div
        subs: list[Tag] = []
        for c in list(li.children):
            if isinstance(c, Tag) and c.name in {"ul", "ol", "pre", "table", "details"}:
                subs.append(c)
            elif isinstance(c, Tag) and c.name == "div" and ("highlighter-rouge" in " ".join(c.get("class", [])) or re.match(r"note", " ".join(c.get("class", [])))):
                subs.append(c)
            elif isinstance(c, Tag) and c.name == "div" and "li" in c.get("class", []):
                # DokuWiki: <div class="li"> text </div>
                for cc in list(c.children):
                    if isinstance(cc, Tag) and cc.name in {"ul", "ol", "pre", "table"}:
                        subs.append(cc)
                    else:
                        inline.append(cc.__copy__() if isinstance(cc, NavigableString) else cc)
            elif isinstance(c, Tag) and c.name == "p":
                if inline.get_text(strip=True):
                    subs.append(c)
                else:
                    for img in c.find_all("img"):
                        self.figure(img)
                    for cc in list(c.children):
                        inline.append(cc.__copy__() if isinstance(cc, NavigableString) else cc)
            elif isinstance(c, Tag) and re.fullmatch(r"h[1-6]", c.name):
                subs.append(c)
            else:
                inline.append(c.__copy__() if isinstance(c, NavigableString) else c)
        html = clean_inline(inline, self.base)
        if html:
            self.add(t="li", html=html, depth=depth, ordinal=ordinal)
        for s in subs:
            if re.fullmatch(r"h[1-6]", s.name):
                self.add(t="p", html=f"<strong>{clean_inline(s, self.base)}</strong>", depth=depth + 1)
            elif s.name == "p":
                h = clean_inline(s, self.base)
                if h:
                    self.add(t="p", html=h, depth=depth + 1)
            elif s.name in {"ul", "ol"}:
                self.block(s, depth + 1)
            else:
                n0 = len(self.blocks)
                self.block(s, depth + 1)
                for b in self.blocks[n0:]:
                    b.setdefault("depth", depth + 1)

    def code(self, pre: Tag, lang: str = ""):
        cls = " ".join(pre.get("class", []))
        if not lang:
            m = re.match(r"code\s+(\w+)", cls)
            lang = m.group(1) if m else ""
        text = norm_text(pre.get_text())
        text = text.rstrip("\n")
        if not text.strip():
            return
        esc = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        lang = {"cpp": "c", "shell": "bash", "sh": "bash", "console": "bash", "plaintext": "", "text": ""}.get(lang, lang)
        self.add(t="code", html=esc, text=text, lang=lang)

    def table(self, el: Tag):
        rows = []
        for tr in el.find_all("tr"):
            cells = []
            for td in tr.find_all(["td", "th"], recursive=False):
                inner = td
                pre = td.find("pre")
                if pre:
                    c = norm_text(pre.get_text()).rstrip().replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                    cells.append({"h": td.name == "th", "html": f"<pre>{c}</pre>"})
                else:
                    cells.append({"h": td.name == "th", "html": clean_inline(inner, self.base)})
            if cells:
                rows.append(cells)
        if rows:
            text = " ".join(ws(BeautifulSoup(c["html"], "html.parser").get_text(" ")) for r in rows for c in r)
            self.add(t="table", rows=rows, html="", text=text)

    def figure(self, img: Tag):
        src = img.get("src") or ""
        if not src or "smileys" in src or src.endswith(".ico"):
            return
        name = fetch_media(src, self.base)
        if not name:
            return
        alt = ws(img.get("alt") or img.get("title") or "")
        self.add(t="fig", src=name, html="", text=alt, cap=alt)

    INLINE_TAGS = INLINE_OK | {"span", "var", "abbr", "small", "mark", "q", "s", "tt", "img"}

    def flow(self, el: Tag, depth: int = 0):
        """Parcurge copiii: nodurile inline consecutive (text, code, strong…) formează un paragraf."""
        buf: list = []

        def flush():
            if not buf:
                return
            holder = BeautifulSoup("<p></p>", "lxml").p
            for n in buf:
                holder.append(n.__copy__() if isinstance(n, NavigableString) else n)
            for img in holder.find_all("img"):
                self.figure(img)
            html = clean_inline(holder, self.base)
            if html:
                self.add(t="p", html=html, depth=depth) if depth else self.add(t="p", html=html)
            buf.clear()

        for c in list(el.children):
            if isinstance(c, NavigableString):
                if c.__class__.__name__ in {"Comment", "Doctype"}:
                    continue
                buf.append(c)
                continue
            if not isinstance(c, Tag):
                continue
            if c.name in self.INLINE_TAGS and not c.find(["div", "p", "pre", "ul", "ol", "table"]):
                buf.append(c)
                continue
            flush()
            m = re.fullmatch(r"h([1-6])", c.name)
            if m:
                self.on_heading(int(m.group(1)), c)
                continue
            self.block(c, depth)
        flush()

    def walk_children(self, el: Tag, depth: int = 0):
        self.flow(el, depth)

    # hook suprascris pentru a decala/omite titluri
    def on_heading(self, level: int, el: Tag):
        self.heading(level, ws(el.get_text()), el.get("id"))


# ---------------------------------------------------------------------------
# surse

def dokuwiki_body(path: Path) -> tuple[Tag, list[str]]:
    soup = BeautifulSoup(path.read_text(encoding="utf-8"), "lxml")
    body = soup.find("div", class_="dokuwiki") or soup.body
    for toc in body.find_all("div", id="dw__toc"):
        toc.decompose()
    for toc in body.find_all("div", class_="toc"):
        toc.decompose()
    # autori: lista de sub „Responsabili”
    authors = []
    for strong in body.find_all("strong"):
        if re.search(r"Respo?n?sabil|Autor", strong.get_text()):
            p = strong.find_parent("p")
            ul = p.find_next_sibling("ul") if p else None
            if ul:
                authors = [ws(li.get_text()) for li in ul.find_all("li")]
                ul.decompose()
            if p:
                p.decompose()
            break
    return body, authors


def jekyll_body(path: Path) -> Tag:
    soup = BeautifulSoup(path.read_text(encoding="utf-8"), "lxml")
    main = soup.find("main") or soup.body
    return main.find("div", class_="wrapper") or main


class TheoryBuilder(Builder):
    """Titlul principal (h1/h2 cu numele laboratorului) se omite; restul se decalează."""

    skip_titles = re.compile(r"^(PCLP\s+)?Laborator\s*\d+|^Laborator\d+|^Coding style PCLP|^Debugging$|^Logging$", re.I)

    def __init__(self, *a, top_level: int = 2, **kw):
        super().__init__(*a, **kw)
        self.top_level = top_level
        self.skipped_first = False

    def on_heading(self, level, el):
        title = ws(el.get_text())
        if not self.skipped_first and level <= self.top_level:
            self.skipped_first = True
            return
        if title.lower() in {"table of contents", "cuprins"}:
            return
        lvl = max(1, level - self.top_level + 1)
        if self.skipped_first and level <= self.top_level:
            lvl = 1
        self.heading(lvl + self.offset, title, el.get("id"))

    offset = 0


def first_heading_level(body: Tag) -> int:
    h = body.find(re.compile(r"^h[1-6]$"))
    return int(h.name[1]) if h else 1


def extract_theory(b: Builder, path: Path, offset: int) -> list[str]:
    body, authors = dokuwiki_body(path)
    tb = TheoryBuilder(b.unit, OCW + "/courses/programare/", b.part, top_level=first_heading_level(body))
    tb.offset = offset
    tb.used_ids = b.used_ids
    tb.sec_stack = list(b.sec_stack)
    tb.walk_children(body)
    merge(b, tb)
    return authors


def merge(b: Builder, other: Builder):
    b.blocks.extend(other.blocks)
    b.sections.extend(other.sections)


def extract_acs(b: Builder, path: Path, kind: str, lab_no: str):
    """Din pagina de laborator acs păstrăm doar secțiunea de exerciții; din problemset, tot."""
    body = jekyll_body(path)
    base = f"{ACS}/{'laboratoare' if kind == 'laborator' else 'problemset'}/{lab_no}"
    sub = Builder(b.unit, base, kind)
    sub.used_ids = b.used_ids
    if kind == "laborator":
        h = None
        for hh in body.find_all("h2"):
            if slug(hh.get_text()).startswith("exerci"):
                h = hh
                break
        if h is None:
            return
        sub.heading(1, "Exerciții de laborator", "lab-exercitii")
        for sib in h.find_next_siblings():
            if sib.name == "h2":
                break
            m = re.fullmatch(r"h([3-6])", sib.name or "")
            if m:
                sub.heading(int(m.group(1)) - 1, ws(sib.get_text()), None)
                continue
            sub.block(sib)
    else:
        sub.heading(1, "Problemset (extra)", "problemset")
        started = False
        for c in body.children:
            if not isinstance(c, Tag):
                continue
            if c.name == "h1":
                started = True
                continue
            if not started:
                continue
            if c.name == "p" and "Probleme extra propuse" in c.get_text():
                continue
            m = re.fullmatch(r"h([2-6])", c.name or "")
            if m:
                sub.heading(int(m.group(1)), ws(c.get_text()), None)
                continue
            sub.block(c)
    merge(b, sub)


def number_blocks(blocks: list[dict]):
    for i, bl in enumerate(blocks):
        bl["i"] = i


def build(out: Path):
    cfg = yaml.safe_load((ROOT / "content" / "curated" / "units.yaml").read_text(encoding="utf-8"))
    rdir = out / "reader"
    rdir.mkdir(parents=True, exist_ok=True)
    units_meta = []
    for lab in cfg["labs"]:
        uid = lab["id"]
        no = uid[3:]
        b = Builder(uid, OCW, "teorie")
        authors: list[str] = []
        b.heading(1, "Suport teoretic", "teorie")
        for i, src in enumerate(lab.get("theory", [])):
            b.sec_stack = [(1, "teorie")]
            authors += extract_theory(b, RAW / src, offset=1)
        b.sec_stack = []
        if lab.get("lab"):
            extract_acs(b, RAW / lab["lab"], "laborator", no)
        if lab.get("problemset"):
            b.sec_stack = []
            extract_acs(b, RAW / lab["problemset"], "problemset", no)
        number_blocks(b.blocks)
        sources = [f"{OCW}/courses/programare/laboratoare/{Path(s).stem.replace('laboratoare_', '').replace('suport_teoretic_', 'suport_teoretic/')}" for s in lab.get("theory", [])]
        if lab.get("lab"):
            sources.append(f"{ACS}/laboratoare/{no}")
        if lab.get("problemset"):
            sources.append(f"{ACS}/problemset/{no}")
        data = {"id": uid, "kind": "lab", "number": int(no), "title": lab["title"], "short": lab.get("short", ""),
                "icon": lab.get("icon", ""), "sources": sources, "authors": sorted(set(authors)),
                "sections": b.sections, "blocks": b.blocks}
        (rdir / f"{uid}.json").write_text(json.dumps(data, ensure_ascii=False, indent=0), encoding="utf-8")
        units_meta.append({k: data[k] for k in ("id", "kind", "number", "title", "short", "icon", "sources", "authors")})
        print(f"{uid}: {len(b.blocks)} blocuri, {len(b.sections)} secțiuni")
    for g in cfg["guides"]:
        uid = g["id"]
        b = Builder(uid, OCW, "ghid")
        body, authors = dokuwiki_body(RAW / g["source"])
        tb = TheoryBuilder(uid, OCW + "/courses/programare/", "ghid", top_level=first_heading_level(body))
        tb.walk_children(body)
        merge(b, tb)
        number_blocks(b.blocks)
        src_url = f"{OCW}/courses/programare/" + Path(g["source"]).stem.replace("tutoriale_", "tutoriale/")
        data = {"id": uid, "kind": "guide", "number": None, "title": g["title"], "short": g["title"], "icon": g.get("icon", ""),
                "sources": [src_url], "authors": authors, "sections": b.sections, "blocks": b.blocks}
        (rdir / f"{uid}.json").write_text(json.dumps(data, ensure_ascii=False, indent=0), encoding="utf-8")
        units_meta.append({k: data[k] for k in ("id", "kind", "number", "title", "short", "icon", "sources", "authors")})
        print(f"{uid}: {len(b.blocks)} blocuri, {len(b.sections)} secțiuni")
    (rdir / "units.json").write_text(json.dumps(units_meta, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "content" / "build"))
    build(Path(ap.parse_args().out))
