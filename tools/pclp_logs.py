"""pclp_logs — parsere comune (stdlib) pentru jurnalele PCLP și sesiunile uneltelor AI.

Folosit de `pclp` (în container) și `pclp-verify` (pe laptopul profesorului).

Formate:
  terminal.log  — TSV: ISO8601 \t cwd \t exit \t comanda
  tools.log     — blocuri: "=== ISO | cwd | comanda | exit N ===" urmat de ieșirea capturată
  ai/<tool>/... — copii ale fișierelor de sesiune ale uneltelor AI (formatele originale)
  ai/portal.jsonl, ai/external/*.md — scrise de portal
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Tabel unelte AI: unde își țin sesiunile și ce fișiere se copiază (DOAR transcrieri).
# `env` = variabilă care mută directorul de bază; `env_suffix` se adaugă la valoarea ei.
# Verificat (sept. 2026) pe sursele oficiale:
#   Continue  core/util/paths.ts            ~/.continue/sessions/<id>.json (+ sessions.json index)
#   Gemini    core/config/storage.ts        ~/.gemini/tmp/<proj>/chats/session-*.json(l), logs.json
#   Claude    ~/.claude/projects/<cwd-cu-liniuțe>/<uuid>.jsonl
#   Codex     ~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl
# ---------------------------------------------------------------------------
AI_SOURCES = [
    {"tool": "continue", "base": "~/.continue", "env": "CONTINUE_GLOBAL_DIR", "env_suffix": "",
     "include": ["sessions/*.json"]},
    {"tool": "gemini", "base": "~/.gemini", "env": "GEMINI_CLI_HOME", "env_suffix": ".gemini",
     "include": ["tmp/*/chats/*.json", "tmp/*/chats/*.jsonl", "tmp/*/chats/*/*.jsonl",
                 "tmp/*/logs.json"]},
    {"tool": "claude", "base": "~/.claude", "env": "CLAUDE_CONFIG_DIR", "env_suffix": "",
     "include": ["projects/*/*.jsonl", "projects/*/*/subagents/*.jsonl"]},
    {"tool": "codex", "base": "~/.codex", "env": "CODEX_HOME", "env_suffix": "",
     "include": ["sessions/*/*/*/*.jsonl", "archived_sessions/*.jsonl",
                 "archived_sessions/*/*/*/*.jsonl"]},
]

# Nume de fișiere care NU se copiază niciodată (configurări, chei, tokenuri).
SECRET_NAME_RE = re.compile(
    r"(auth|cred|oauth|token|secret|password|passwd|\.env$|^\.env|settings|config|"
    r"google_accounts|installation_id|\.key$|\.pem$|keychain|\.sqlite)", re.I)

# Șiruri care arată a chei API — se înlocuiesc în copii (ex. dacă studentul a lipit o cheie).
SECRET_VALUE_RES = [
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}"),
    re.compile(r"sk-(?:proj-|svcacct-)?[A-Za-z0-9_\-]{32,}"),
    re.compile(r"AIza[0-9A-Za-z_\-]{35}"),
    re.compile(r"ya29\.[0-9A-Za-z_\-]{20,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{24,}"),
]


def redact(text: str) -> str:
    for r in SECRET_VALUE_RES:
        if r.groups:
            text = r.sub(lambda m: m.group(1) + "[REDACTAT]", text)
        else:
            text = r.sub("[REDACTAT]", text)
    return text


# ---------------------------------------------------------------------------
# Timp
# ---------------------------------------------------------------------------
def parse_ts(v) -> datetime | None:
    """Acceptă ISO 8601 (cu/fără Z), epoch s sau ms. Întoarce datetime cu fus orar."""
    if v is None or v == "":
        return None
    try:
        if isinstance(v, (int, float)):
            x = float(v)
            if x > 1e12:
                x /= 1000.0
            return datetime.fromtimestamp(x, tz=timezone.utc)
        s = str(v).strip()
        if re.fullmatch(r"\d{10,13}(\.\d+)?", s):
            return parse_ts(float(s))
        s = s.replace("Z", "+00:00")
        if re.search(r"[+-]\d{4}$", s):
            s = s[:-2] + ":" + s[-2:]
        d = datetime.fromisoformat(s)
        if d.tzinfo is None:
            d = d.astimezone()
        return d
    except (ValueError, OverflowError, OSError):
        return None


# ---------------------------------------------------------------------------
# terminal.log / tools.log
# ---------------------------------------------------------------------------
def parse_terminal_log(text: str) -> list[dict]:
    out = []
    for i, line in enumerate(text.splitlines()):
        if not line.strip():
            continue
        parts = line.split("\t", 3)
        if len(parts) < 4:
            out.append({"ts": None, "cwd": "", "exit": None, "cmd": line, "malformed": True, "line": i + 1})
            continue
        ts, cwd, ec, cmd = parts
        try:
            eci = int(ec)
        except ValueError:
            eci = None
        out.append({"ts": parse_ts(ts), "cwd": cwd, "exit": eci, "cmd": cmd, "line": i + 1})
    return out


def parse_tests_log(text: str) -> list[dict]:
    """tests.log — TSV: ISO \t problemă \t trecute/total \t compile_ok|compile_fail [\t normal|valgrind]"""
    out = []
    for line in text.splitlines():
        p = line.split("\t")
        if len(p) < 4:
            continue
        m = re.fullmatch(r"(\d+)/(\d+)", p[2].strip())
        out.append({"ts": parse_ts(p[0]), "problem": p[1], "passed": int(m.group(1)) if m else 0,
                    "total": int(m.group(2)) if m else 0, "compiled": p[3].strip() == "compile_ok",
                    "mode": p[4].strip() if len(p) > 4 else "normal"})
    return out


TOOLS_HDR = re.compile(r"^=== (\S+) \| (.*?) \| (.*) \| exit (-?\d+) ===$")
COMPILERS = {"gcc", "cc", "clang", "make"}


def parse_tools_log(text: str) -> list[dict]:
    blocks: list[dict] = []
    cur = None
    for line in text.splitlines():
        m = TOOLS_HDR.match(line)
        if m:
            cur = {"ts": parse_ts(m.group(1)), "cwd": m.group(2), "cmd": m.group(3),
                   "exit": int(m.group(4)), "output": []}
            cur["tool"] = cur["cmd"].split(" ", 1)[0].rsplit("/", 1)[-1]
            blocks.append(cur)
        elif cur is not None:
            cur["output"].append(line)
    for b in blocks:
        b["output"] = "\n".join(b["output"])
        out = b["output"]
        b["is_compile"] = b["tool"] in COMPILERS
        b["has_error"] = b["exit"] != 0 or bool(re.search(r"\berror\b|eroare", out))
        b["has_warning"] = bool(re.search(r"\bwarning\b", out))
        if b["tool"] == "valgrind":
            m = re.search(r"ERROR SUMMARY: (\d+) errors", out)
            leak = re.search(r"definitely lost: ([\d,]+) bytes", out)
            b["valgrind_errors"] = int(m.group(1)) if m else None
            b["valgrind_leak"] = int(leak.group(1).replace(",", "")) if leak else 0
            b["has_error"] = b["exit"] != 0 or bool(b["valgrind_errors"]) or bool(b["valgrind_leak"])
    return blocks


# ---------------------------------------------------------------------------
# Sesiuni AI -> listă de mesaje {ts, role: user|assistant, text, session}
# ---------------------------------------------------------------------------
def _text_of(content) -> str:
    """Extrage textul dintr-un câmp content: șir sau listă de părți {type,text}."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        for k in ("text", "content", "message"):
            if isinstance(content.get(k), (str, list)):
                return _text_of(content[k])
        return ""
    if isinstance(content, list):
        parts = []
        for p in content:
            if isinstance(p, str):
                parts.append(p)
            elif isinstance(p, dict):
                t = p.get("type")
                if t in ("tool_result", "tool_use", "thinking", "redacted_thinking", "image", "imageUrl",
                         "functionCall", "functionResponse"):
                    continue
                if isinstance(p.get("text"), str):
                    parts.append(p["text"])
        return "\n".join(x for x in parts if x)
    return str(content)


def _jsonl(text: str):
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except ValueError:
            continue


def parse_continue(text: str, name: str) -> list[dict]:
    try:
        d = json.loads(text)
    except ValueError:
        return []
    if name.endswith("sessions.json") or isinstance(d, list):
        return []  # index — folosit doar pentru date/titluri
    msgs = []
    sid = d.get("sessionId") or name
    title = d.get("title") or ""
    for h in d.get("history") or []:
        m = (h or {}).get("message") or {}
        role = m.get("role")
        if role not in ("user", "assistant"):
            continue
        txt = _text_of(m.get("content"))
        if not txt.strip():
            continue
        msgs.append({"ts": parse_ts(h.get("timestamp") or m.get("timestamp")), "role": role,
                     "text": txt, "session": sid, "title": title})
    return msgs


def continue_index(text: str) -> dict:
    """sessions.json -> {sessionId: (dateCreated, title)}"""
    try:
        d = json.loads(text)
    except ValueError:
        return {}
    out = {}
    for s in d if isinstance(d, list) else []:
        if isinstance(s, dict) and s.get("sessionId"):
            out[s["sessionId"]] = (parse_ts(s.get("dateCreated")), s.get("title") or "")
    return out


def parse_gemini(text: str, name: str) -> list[dict]:
    msgs = []
    recs = []
    try:
        d = json.loads(text)
        recs = d if isinstance(d, list) else [d]
    except ValueError:
        recs = list(_jsonl(text))
    sid = name
    for r in recs:
        if not isinstance(r, dict):
            continue
        if "messages" in r and isinstance(r["messages"], list):
            sid = r.get("sessionId") or sid
            for m in r["messages"]:
                _gemini_msg(m, sid, msgs)
        elif "$set" in r or "$rewindTo" in r:
            continue
        elif name.endswith("logs.json"):
            # logs.json: [{sessionId, messageId, type:"user", message, timestamp}]
            if r.get("type") == "user" and r.get("message"):
                msgs.append({"ts": parse_ts(r.get("timestamp")), "role": "user", "text": str(r["message"]),
                             "session": r.get("sessionId") or name, "source": "logs"})
        else:
            if r.get("sessionId") and "type" not in r:
                sid = r["sessionId"]
                continue
            _gemini_msg(r, sid, msgs)
    return msgs


def _gemini_msg(m, sid, out):
    if not isinstance(m, dict):
        return
    t = m.get("type") or m.get("role")
    role = {"user": "user", "gemini": "assistant", "model": "assistant"}.get(t)
    if not role:
        return
    content = m.get("content")
    if content is None and "parts" in m:
        content = m["parts"]
    txt = _text_of(content)
    if txt.strip():
        out.append({"ts": parse_ts(m.get("timestamp")), "role": role, "text": txt, "session": sid})


_CLAUDE_SKIP_USER = re.compile(r"^\s*<(command-name|command-message|local-command-stdout|system-reminder|"
                               r"user-prompt-submit-hook)|^\s*Caveat: The messages below")


def parse_claude(text: str, name: str) -> list[dict]:
    msgs = []
    for r in _jsonl(text):
        if not isinstance(r, dict):
            continue
        t = r.get("type")
        if t not in ("user", "assistant") or r.get("isMeta"):
            continue
        m = r.get("message") or {}
        c = m.get("content")
        if t == "user":
            if isinstance(c, list) and any(isinstance(p, dict) and p.get("type") == "tool_result" for p in c):
                continue
            txt = _text_of(c)
            if not txt.strip() or _CLAUDE_SKIP_USER.search(txt):
                # comenzi slash: păstrăm numele comenzii ca prompt scurt
                mm = re.search(r"<command-name>(.*?)</command-name>", txt or "")
                if mm:
                    txt = mm.group(1)
                else:
                    continue
            role = "user"
        else:
            txt = _text_of(c)
            if not txt.strip():
                continue
            role = "assistant"
        msgs.append({"ts": parse_ts(r.get("timestamp")), "role": role, "text": txt,
                     "session": r.get("sessionId") or name, "sidechain": bool(r.get("isSidechain"))})
    # asistentul emite mai multe înregistrări per răspuns -> le unim pe cele consecutive
    merged: list[dict] = []
    for m in msgs:
        if merged and m["role"] == "assistant" and merged[-1]["role"] == "assistant":
            merged[-1]["text"] += "\n\n" + m["text"]
        else:
            merged.append(m)
    return merged


_CODEX_CTX = re.compile(r"^\s*(<environment_context>|<user_instructions>|<INSTRUCTIONS>|# AGENTS\.md|"
                        r"<permissions|<collaboration_mode|<turn_aborted>)")


def parse_codex(text: str, name: str) -> list[dict]:
    items, events = [], []
    sid = name
    for r in _jsonl(text):
        if not isinstance(r, dict):
            continue
        p = r.get("payload") or {}
        ts = parse_ts(r.get("timestamp"))
        if r.get("type") == "session_meta":
            sid = p.get("id") or sid
        elif r.get("type") == "response_item" and p.get("type") == "message":
            role = p.get("role")
            if role not in ("user", "assistant"):
                continue
            txt = _text_of(p.get("content"))
            if not txt.strip() or (role == "user" and _CODEX_CTX.search(txt)):
                continue
            items.append({"ts": ts, "role": role, "text": txt, "session": sid})
        elif r.get("type") == "event_msg":
            if p.get("type") == "user_message" and p.get("message"):
                events.append({"ts": ts, "role": "user", "text": str(p["message"]), "session": sid})
            elif p.get("type") == "agent_message" and p.get("message"):
                events.append({"ts": ts, "role": "assistant", "text": str(p["message"]), "session": sid})
        elif "record_type" not in r and r.get("role") in ("user", "assistant"):  # format foarte vechi
            txt = _text_of(r.get("content"))
            if txt.strip():
                items.append({"ts": ts, "role": r["role"], "text": txt, "session": sid})
    return items if any(m["role"] == "user" for m in items) else events


def parse_portal(text: str, name: str) -> list[dict]:
    """portal.jsonl — format scris de portal; citire tolerantă (chei posibile multiple)."""
    msgs = []
    for r in _jsonl(text):
        if not isinstance(r, dict):
            continue
        ts = parse_ts(r.get("ts") or r.get("timestamp") or r.get("time") or r.get("created_at"))
        ctx = r.get("problem") or r.get("problem_slug") or r.get("context") or ""
        sess = r.get("session") or r.get("conversation") or r.get("thread") or ctx or "portal"
        role = r.get("role")
        if role in ("user", "assistant") and (r.get("content") or r.get("text")):
            msgs.append({"ts": ts, "role": role, "text": _text_of(r.get("content") or r.get("text")),
                         "session": sess, "context": ctx})
            continue
        q = r.get("prompt") or r.get("question") or r.get("user") or r.get("message")
        a = r.get("response") or r.get("answer") or r.get("reply") or r.get("assistant")
        if q:
            msgs.append({"ts": ts, "role": "user", "text": _text_of(q), "session": sess, "context": ctx})
        if a:
            msgs.append({"ts": ts, "role": "assistant", "text": _text_of(a), "session": sess, "context": ctx})
        if not q and not a:
            msgs.append({"ts": ts, "role": "user", "text": json.dumps(r, ensure_ascii=False), "session": sess,
                         "context": ctx, "raw": True})
    return msgs


def parse_external(text: str, name: str) -> list[dict]:
    """ai/external/*.md — prompt extern auto-raportat. Front-matter opțional (--- ... ---)."""
    meta = {}
    body = text
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.S)
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip().lower()] = v.strip().strip('"\'')
        body = m.group(2)
    ts = parse_ts(meta.get("timestamp") or meta.get("date") or meta.get("ts") or meta.get("created_at"))
    if ts is None:
        mm = re.search(r"(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2})?)", name + " " + text[:300])
        if mm:
            ts = parse_ts(mm.group(1).replace(" ", "T"))
    return [{"ts": ts, "role": "user", "text": body.strip(), "session": name, "meta": meta,
             "tool_name": meta.get("tool") or meta.get("unealta") or ""}]


def tool_of_path(rel: str) -> str:
    """ai/<tool>/... sau .pclp/ai/<tool>/... -> tool"""
    p = rel.split("/")
    if "ai" in p:
        p = p[p.index("ai") + 1:]
    if not p:
        return "?"
    if p[0] == "portal.jsonl":
        return "portal"
    return p[0]


PARSERS = {"continue": parse_continue, "gemini": parse_gemini, "claude": parse_claude,
           "codex": parse_codex, "portal": parse_portal, "external": parse_external}


def parse_ai_file(rel: str, text: str) -> list[dict]:
    tool = tool_of_path(rel)
    fn = PARSERS.get(tool)
    if fn is None:
        return []
    try:
        msgs = fn(text, rel)
    except Exception:  # noqa: BLE001 — format necunoscut: nu cădem
        return []
    for m in msgs:
        m["tool"] = tool
        m["file"] = rel
    return msgs


def count_user_prompts(msgs: list[dict]) -> int:
    return sum(1 for m in msgs if m["role"] == "user")
