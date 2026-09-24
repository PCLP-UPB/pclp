"""Randarea blocurilor din cititor, cu legarea termenilor și evidențierea codului C."""
from __future__ import annotations

import html as htmlmod
import re
from functools import lru_cache

from django.utils.safestring import mark_safe

TAG_RE = re.compile(r"(<[^>]+>)")

C_KEYWORDS = set("""auto break case char const continue default do double else enum extern float for goto if inline int long
register restrict return short signed sizeof static struct switch typedef union unsigned void volatile while
bool true false NULL size_t FILE uint8_t uint16_t uint32_t uint64_t int8_t int16_t int32_t int64_t""".split())
C_TOKEN = re.compile(
    r"(?P<com>//[^\n]*|/\*.*?\*/)|(?P<str>\"(?:\\.|[^\"\\\n])*\"|'(?:\\.|[^'\\\n])*')|(?P<pre>^\s*#\s*\w+)|"
    r"(?P<num>\b0[xX][0-9a-fA-F]+\b|\b\d+(?:\.\d+)?[uUlLfF]*\b)|(?P<id>\b[A-Za-z_]\w*\b)",
    re.S | re.M,
)
SH_TOKEN = re.compile(r"(?P<com>#[^\n]*)|(?P<str>\"(?:\\.|[^\"\\])*\"|'[^']*')|(?P<prompt>^\$ )", re.M)


def highlight(code: str, lang: str) -> str:
    """Evidențiere minimă (fără dependențe externe) pentru C și shell."""
    if lang in ("c", "cpp", ""):
        rx = C_TOKEN
    elif lang in ("bash", "sh", "shell"):
        rx = SH_TOKEN
    else:
        return htmlmod.escape(code)
    out, pos = [], 0
    for m in rx.finditer(code):
        out.append(htmlmod.escape(code[pos:m.start()]))
        kind = m.lastgroup
        tok = m.group(0)
        if kind == "id":
            if tok in C_KEYWORDS:
                out.append(f'<span class="k">{htmlmod.escape(tok)}</span>')
            else:
                out.append(htmlmod.escape(tok))
        else:
            cls = {"com": "c", "str": "s", "pre": "p", "num": "n", "prompt": "p"}[kind]
            out.append(f'<span class="{cls}">{htmlmod.escape(tok)}</span>')
        pos = m.end()
    out.append(htmlmod.escape(code[pos:]))
    return "".join(out)


class Linker:
    """Leagă termenii în HTML-ul inline. Prima apariție din fiecare secțiune primește clasa `t1`."""

    def __init__(self, matcher, concepts):
        self.m = matcher
        self.cs = concepts
        self.seen_in_sec: dict[str, set[str]] = {}
        self.found_in_sec: dict[str, set[str]] = {}

    def link(self, html: str, sec: str | None, current: str | None = None) -> str:
        seen = self.seen_in_sec.setdefault(sec or "", set())
        found = self.found_in_sec.setdefault(sec or "", set())
        out = []
        in_code = 0
        in_a = 0
        for part in TAG_RE.split(html):
            if not part:
                continue
            if part.startswith("<"):
                t = part.lower()
                if t.startswith("<code"):
                    in_code += 1
                elif t.startswith("</code"):
                    in_code = max(0, in_code - 1)
                elif t.startswith("<a ") or t == "<a>":
                    in_a += 1
                elif t.startswith("</a"):
                    in_a = max(0, in_a - 1)
                out.append(part)
                continue
            if in_a:
                out.append(part)
                continue
            text = htmlmod.unescape(part)
            ms = self.m.find(text, in_code=bool(in_code))
            if not ms:
                out.append(part)
                continue
            pos = 0
            for mm in ms:
                c = self.cs.get(mm.concept)
                if not c:
                    continue
                out.append(htmlmod.escape(text[pos:mm.start], quote=False))
                cls = "t1" if mm.concept not in seen else "tn"
                seen.add(mm.concept)
                found.add(mm.concept)
                lvl = c.get("level", 2)
                extra = " cur" if current == mm.concept else ""
                extra += " added" if c.get("origin") == "claude" else ""
                out.append(f'<a class="term {cls} l{lvl}{extra}" data-t="{c["id"]}" href="/termen/{c["id"]}/">'
                           f'{htmlmod.escape(text[mm.start:mm.end], quote=False)}</a>')
                pos = mm.end
            out.append(htmlmod.escape(text[pos:], quote=False))
        return "".join(out)


def render_block(b: dict, linker: Linker | None, uid: str) -> str:
    t = b["t"]
    sec = b.get("sec")
    lk = (lambda h: linker.link(h, sec)) if linker else (lambda h: h)
    anchor = f'id="b{b["i"]}"' if "i" in b else ""
    depth = b.get("depth", 0) or 0
    style = f' style="--d:{depth}"' if depth else ""
    if t == "h":
        lvl = min(6, (b.get("lvl") or 1) + 1)
        return f'<h{lvl} id="s-{b["anchor"]}" class="rh" data-sec="{b["anchor"]}">{b["html"]}<a class="hl" href="#s-{b["anchor"]}">#</a></h{lvl}>'
    if t == "p":
        cls = "rp quote" if b.get("quote") else "rp"
        return f'<p {anchor} class="{cls}"{style}>{lk(b["html"])}</p>'
    if t == "li":
        mark = f'<span class="ord">{b["ordinal"]}.</span>' if b.get("ordinal") else '<span class="bul">•</span>'
        return f'<div {anchor} class="rli"{style}>{mark}<div>{lk(b["html"])}</div></div>'
    if t == "code":
        lang = b.get("lang", "")
        return (f'<div {anchor} class="rcode"{style}><button class="copy" type="button" title="Copiază">⧉</button>'
                f'<pre class="lang-{lang}"><code>{highlight(htmlmod.unescape(b["html"]), lang)}</code></pre></div>')
    if t == "note":
        kind = b.get("kind", "classic")
        inner = "".join(render_block({**x, "sec": sec}, linker, uid) for x in b.get("inner", []))
        label = {"important": "Important", "warning": "Atenție", "tip": "Sfat", "info": "Info"}.get(kind, "Notă")
        return f'<aside {anchor} class="note note-{kind}"{style}><div class="note-h">{label}</div>{inner}</aside>'
    if t == "details":
        inner = "".join(render_block({**x, "sec": sec}, linker, uid) for x in b.get("inner", []))
        return f'<details {anchor} class="rdet"{style}><summary>{htmlmod.escape(b.get("title", "Detalii"))}</summary>{inner}</details>'
    if t == "table":
        rows = []
        for r in b.get("rows", []):
            cells = "".join(f'<{"th" if c["h"] else "td"}>{lk(c["html"]) if "<pre>" not in c["html"] else c["html"]}</{"th" if c["h"] else "td"}>' for c in r)
            rows.append(f"<tr>{cells}</tr>")
        return f'<div {anchor} class="rtable"{style}><table>{"".join(rows)}</table></div>'
    if t == "fig":
        cap = htmlmod.escape(b.get("cap") or "")
        return (f'<figure {anchor} class="rfig"><a href="/media/{b["src"]}" class="zoom"><img loading="lazy" src="/media/{b["src"]}" alt="{cap}"></a>'
                + (f"<figcaption>{cap}</figcaption>" if cap else "") + "</figure>")
    return ""


@lru_cache(maxsize=40)
def _rendered_unit(uid: str, version: int):
    from . import content as C

    linker = Linker(C.matcher(), C.concepts())
    out = []
    for b in C.blocks(uid):
        out.append({"i": b.get("i"), "t": b["t"], "sec": b.get("sec"), "part": b.get("part"), "html": render_block(b, linker, uid)})
    return out, {k: sorted(v) for k, v in linker.found_in_sec.items()}


def rendered_unit(uid: str):
    from . import content as C

    blocks, sec_terms = _rendered_unit(uid, C.version())
    return [dict(b, html=mark_safe(b["html"])) for b in blocks], sec_terms


def render_markdownish(html: str, current: str | None = None) -> str:
    """Leagă termenii într-un fragment HTML (enunțuri de probleme, definiții)."""
    from . import content as C

    linker = Linker(C.matcher(), C.concepts())
    out = []
    for part in re.split(r"(<pre>.*?</pre>)", html, flags=re.S):
        if part.startswith("<pre>"):
            m = re.match(r"<pre>(?:<code(?: class=\"language-(\w+)\")?>)?(.*?)(?:</code>)?</pre>", part, re.S)
            if m:
                lang = m.group(1) or "c"
                code = htmlmod.unescape(m.group(2))
                out.append(f'<div class="rcode"><button class="copy" type="button" title="Copiază">⧉</button><pre><code>{highlight(code, lang)}</code></pre></div>')
            else:
                out.append(part)
        else:
            out.append(linker.link(part, "x", current))
    return mark_safe("".join(out))
