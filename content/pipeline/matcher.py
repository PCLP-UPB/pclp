"""Potrivitorul de termeni: găsește aparițiile conceptelor într-un text.

Folosit de pipeline (numărarea mențiunilor, evidențe, detectarea definițiilor) și de
aplicație (legarea termenilor în cititor). Reguli (spec §6, adaptate pentru C):

- identificatori C (`malloc`, `size_t`, `NULL`) și simboluri (`#define`, `->`, `%d`,
  `stdio.h`, `-Wall`): potrivire EXACTĂ, cu majuscule, cu limite de „cuvânt” C;
  cuvintele cheie scurte și identificatorii care sunt și cuvinte uzuale (`if`, `static`,
  `free`) se leagă doar în interiorul codului inline (`code_only`);
- acronime (majuscule, ≤ 8 caractere): exact, cu majuscule;
- expresii românești: fără diacritice, litere mici, rădăcină + terminații flexionare,
  pe fiecare cuvânt; între cuvinte: spațiu, rând nou sau cratimă;
- cea mai lungă formă câștigă, potrivirile nu se suprapun.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

ENDINGS = sorted({
    "", "a", "e", "i", "ul", "ului", "ei", "ii", "ile", "ilor", "le", "lor", "ele", "elor", "elui",
    "ia", "ie", "iei", "iile", "iilor", "uri", "urile", "urilor", "l", "lui", "ri", "rile", "rilor",
    "u", "ua", "ul", "ea", "ele", "s", "es",
}, key=len, reverse=True)
# terminații care se pot elimina din forma de bază ca să obținem rădăcina
STRIP = sorted({"a", "e", "i", "u", "ie", "ul", "ea", "ă"}, key=len, reverse=True)

C_KEYWORDS = {
    "auto", "break", "case", "char", "const", "continue", "default", "do", "double", "else", "enum",
    "extern", "float", "for", "goto", "if", "inline", "int", "long", "register", "restrict", "return",
    "short", "signed", "sizeof", "static", "struct", "switch", "typedef", "union", "unsigned", "void",
    "volatile", "while", "main", "free", "exit", "abs", "pow", "time", "read", "write", "open", "close",
    "rand", "log", "floor", "ceil", "round", "puts", "gets", "index", "stat", "make", "test", "assert",
}
IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# „să indice”, „să aloce”: după „să” urmează un verb, nu un termen
VERB_CTX = re.compile(r"\bsa\s+$")
WORDCH = r"[0-9A-Za-z_À-ɏ]"


def fold_char(c: str) -> str:
    d = unicodedata.normalize("NFD", c)
    return d[0].lower() if d else c.lower()


def fold(s: str) -> str:
    """Litere mici, fără diacritice, păstrând lungimea (poziții 1:1)."""
    return "".join(fold_char(c) for c in s)


def slug(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s.lower()).strip("-")
    return s or "x"


def concept_id(label: str) -> str:
    return "c-" + slug(label)


def form_kind(form: str) -> str:
    if IDENT_RE.match(form):
        if form.isupper() and len(form) <= 8:
            return "acronym"
        if "_" in form or form.islower() and form.isascii() and len(form) > 1 and not any(ch in "ăâîșț" for ch in form):
            # identificator C (sau cuvânt englez scris ca în cod) — decide apelantul dacă e ident
            return "ident"
        return "word"
    if re.search(r"[#%<>\-\.\[\]\*&|^~!=+/(){}]", form) and " " not in form.strip():
        return "symbol"
    return "phrase"


def word_pattern(w: str) -> str:
    w = fold(w)
    if len(w) <= 3 or not w.isalpha():
        return re.escape(w)
    root = w
    for e in STRIP:
        if w.endswith(e) and len(w) - len(e) >= 4:
            root = w[: -len(e)]
            break
    alts = "|".join(re.escape(e) for e in ENDINGS if e)
    # rădăcina + (terminație)? — iar forma completă rămâne acceptată
    return f"(?:{re.escape(w)}|{re.escape(root)}(?:{alts})?)"


@dataclass
class Form:
    concept: str
    text: str
    kind: str           # ident | acronym | symbol | phrase
    code_only: bool
    regex: re.Pattern
    key: str             # cheia de indexare (primele caractere)
    length: int


@dataclass
class Match:
    start: int
    end: int
    concept: str
    form: str


@dataclass
class Matcher:
    forms: list[Form] = field(default_factory=list)
    index: dict[str, list[Form]] = field(default_factory=dict)
    exact_index: dict[str, list[Form]] = field(default_factory=dict)

    @classmethod
    def build(cls, concepts: list[dict]) -> "Matcher":
        """concepts: [{id, label, aliases: [..], kind}]"""
        m = cls()
        seen: set[tuple[str, str]] = set()
        for c in concepts:
            forms = [c["label"]] + [a for a in c.get("aliases", []) if a]
            for f in forms:
                f = f.strip()
                if not f:
                    continue
                if len(f) < 2 and not f.isalnum():
                    continue  # simbolurile de un caracter ar lega zgomotos
                key = (c["id"], f)
                if key in seen:
                    continue
                seen.add(key)
                m.add_form(c["id"], f, c.get("kind", ""))
        return m

    def add_form(self, cid: str, f: str, ckind: str):
        k = form_kind(f)
        code_only = False
        if k == "ident":
            # cuvinte englezești uzuale scrise ca identificatori (ex. „heap”, „stack”) sunt tratate ca expresii
            is_code_kind = ckind in {"funcție de bibliotecă", "cuvânt cheie", "tip de date", "fișier antet",
                                     "directivă preprocesor", "specificator de format", "opțiune de compilare", "unealtă", "instrucțiune", "operator"}
            if not is_code_kind and "_" not in f:
                k = "phrase"
            else:
                code_only = f in C_KEYWORDS or len(f) <= 3
        if k == "word":
            k = "phrase"
        if k in {"ident", "acronym"}:
            rx = re.compile(r"(?<![0-9A-Za-z_])" + re.escape(f) + r"(?![0-9A-Za-z_])")
            form = Form(cid, f, k, code_only, rx, f[:2], len(f))
            self.exact_index.setdefault(f[:2], []).append(form)
        elif k == "symbol":
            left = r"(?<![0-9A-Za-z_])" if re.match(r"[\w]", f) else r"(?<![#%\w])" if f[0] in "#%" else ""
            right = r"(?![0-9A-Za-z_])" if re.search(r"\w$", f) else ""
            rx = re.compile(left + re.escape(f) + right)
            form = Form(cid, f, k, False, rx, f[:2], len(f))
            self.exact_index.setdefault(f[:2], []).append(form)
        else:
            words = re.split(r"[\s\-]+", f.strip())
            pat = r"[\s\-]+".join(word_pattern(w) for w in words)
            rx = re.compile(r"(?<![0-9a-z_])" + pat + r"(?![0-9a-z_])")
            first = fold(words[0])
            form = Form(cid, f, "phrase", False, rx, first[:3], len(f))
            self.index.setdefault(first[:3], []).append(form)
        self.forms.append(form)

    def find(self, text: str, in_code: bool = False, only: set[str] | None = None) -> list[Match]:
        """Toate potrivirile, nesuprapuse, cea mai lungă câștigă."""
        cands: list[Match] = []
        low = fold(text)
        # expresii: în textul normalizat, pornind de la începutul fiecărui cuvânt
        for wm in re.finditer(r"[0-9a-z_]+", low):
            key = wm.group(0)[:3]
            for f in self.index.get(key, ()):
                if only is not None and f.concept not in only:
                    continue
                mm = f.regex.match(low, wm.start())
                if mm and not VERB_CTX.search(low, max(0, wm.start() - 4), wm.start()):
                    cands.append(Match(mm.start(), mm.end(), f.concept, f.text))
        # identificatori, acronime, simboluri: exact, pe textul original
        for key, forms in self.exact_index.items():
            if key not in text:
                continue
            for f in forms:
                if f.code_only and not in_code:
                    continue
                if only is not None and f.concept not in only:
                    continue
                for mm in f.regex.finditer(text):
                    cands.append(Match(mm.start(), mm.end(), f.concept, f.text))
        cands.sort(key=lambda x: (-(x.end - x.start), x.start))
        taken: list[tuple[int, int]] = []
        out: list[Match] = []
        for c in cands:
            if any(not (c.end <= a or c.start >= b) for a, b in taken):
                continue
            taken.append((c.start, c.end))
            out.append(c)
        out.sort(key=lambda x: x.start)
        return out
