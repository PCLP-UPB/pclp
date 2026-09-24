"""Apeluri LLM cu cheia studentului: Claude (SDK-ul oficial anthropic) sau un furnizor
compatibil OpenAI (Gemini, OpenAI, Mistral, Ollama local) — AI-ul preferat al studentului.

Setările (furnizor, cheie, model) stau în PCLP_STATE/ai-settings.json: director ignorat de
git, deci cheia nu ajunge niciodată în arhiva săptămânală. Fiecare apel e logat de apelant
în .pclp/ai/portal.jsonl (prompt + răspuns, fără cheie).
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from django.conf import settings

SETTINGS_FILE = settings.PCLP_STATE / "ai-settings.json"

PROVIDERS = {
    "anthropic": {"name": "Claude (Anthropic)", "base_url": "", "models": ["claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5"],
                  "default_model": "claude-opus-5", "key_hint": "sk-ant-…  (console.anthropic.com)"},
    "gemini": {"name": "Gemini (Google, compatibil OpenAI)", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
               "models": ["gemini-3.6-flash"], "default_model": "gemini-3.6-flash",
               "key_hint": "cheie de la aistudio.google.com (are nivel gratuit)"},
    "openai": {"name": "OpenAI", "base_url": "https://api.openai.com/v1", "models": [], "default_model": "",
               "key_hint": "sk-…  (platform.openai.com)"},
    "mistral": {"name": "Mistral", "base_url": "https://api.mistral.ai/v1", "models": ["mistral-small-latest", "mistral-large-latest"],
                "default_model": "mistral-small-latest", "key_hint": "cheie de la console.mistral.ai"},
    "ollama": {"name": "Ollama (model local, fără cheie)", "base_url": "http://host.docker.internal:11434/v1",
               "models": [], "default_model": "llama3.1", "key_hint": "nu e nevoie de cheie"},
    "custom": {"name": "Alt server compatibil OpenAI", "base_url": "", "models": [], "default_model": "", "key_hint": ""},
}

TUTOR_SYSTEM = """Ești tutorele unui student din anul I la cursul de Programarea Calculatoarelor (limbajul C), \
Politehnica București. Scopul tău este ca studentul să învețe, nu să termine exercițiul.
- Răspunde în română, prietenos și concis.
- Explică noțiunile și mesajele de eroare; pune întrebări care îl ghidează spre soluție.
- Nu scrie soluția completă a problemei curente. Poți da exemple mici pe alte date, pseudocod parțial \
sau un singur rând de cod atunci când e blocat pe sintaxă.
- Trimite-l la documentație (ex. `man 3 printf`), la compilarea cu `-Wall -Wextra`, la gdb și valgrind.
- Dacă studentul insistă explicit pentru soluția completă, o poți da, dar explic-o linie cu linie și \
propune-i apoi o variantă a problemei pe care s-o rezolve singur.
- Când vezi codul studentului, comentează întâi ce face bine, apoi o singură problemă importantă odată."""


class LLMError(Exception):
    pass


def load_settings() -> dict:
    try:
        data = json.loads(SETTINGS_FILE.read_text())
    except (OSError, ValueError):
        data = {}
    data.setdefault("provider", "anthropic")
    data.setdefault("api_key", "")
    data.setdefault("model", PROVIDERS[data["provider"]]["default_model"])
    data.setdefault("base_url", PROVIDERS[data["provider"]]["base_url"])
    return data


def save_settings(data: dict):
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(data, indent=1))
    try:
        os.chmod(SETTINGS_FILE, 0o600)
    except OSError:
        pass


def configured() -> bool:
    s = load_settings()
    return bool(s.get("model")) and (bool(s.get("api_key")) or s["provider"] == "ollama")


def _info(s: dict) -> dict:
    return {"provider": s["provider"], "model": s["model"]}


# ---------------------------------------------------------------------------
# Claude — SDK-ul oficial

def _claude_client(s):
    import anthropic

    return anthropic.Anthropic(api_key=s["api_key"], max_retries=2, timeout=120)


def _claude_create(client, **kw):
    """Cerere cu fallback server-side la refuz (implicit pentru claude-opus-5); dacă parametrul nu e
    acceptat (SDK/cont mai vechi), repetăm cererea simplă."""
    import anthropic

    try:
        return client.beta.messages.create(betas=["server-side-fallback-2026-07-01"], extra_body={"fallbacks": "default"}, **kw)
    except anthropic.BadRequestError as e:
        if "fallback" not in str(e).lower():
            raise
    return client.messages.create(**kw)


def _claude_text(resp) -> str:
    if resp.stop_reason == "refusal":
        raise LLMError("Modelul a refuzat cererea. Reformulează întrebarea.")
    return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()


def _claude_call(s, system, messages, schema=None, max_tokens=16000):
    import anthropic

    kw = {"model": s["model"], "max_tokens": max_tokens, "system": system, "messages": messages}
    if schema:
        kw["output_config"] = {"format": {"type": "json_schema", "schema": schema}}
    try:
        resp = _claude_create(_claude_client(s), **kw)
    except anthropic.AuthenticationError:
        raise LLMError("Cheia API Anthropic nu e validă. Verific-o în Setări AI.")
    except anthropic.PermissionDeniedError:
        raise LLMError("Cheia nu are acces la acest model.")
    except anthropic.NotFoundError:
        raise LLMError(f"Modelul „{s['model']}” nu există sau nu e disponibil pentru cheia ta.")
    except anthropic.RateLimitError:
        raise LLMError("Prea multe cereri (limită de rată). Încearcă din nou peste un minut.")
    except anthropic.APIStatusError as e:
        raise LLMError(f"Eroare API ({e.status_code}): {e.message}")
    except anthropic.APIConnectionError:
        raise LLMError("Nu mă pot conecta la API. Verifică conexiunea la internet.")
    return _claude_text(resp)


# ---------------------------------------------------------------------------
# furnizori compatibili OpenAI (Gemini, OpenAI, Mistral, Ollama)

def _openai_call(s, system, messages, schema=None, max_tokens=4000):
    base = (s.get("base_url") or "").rstrip("/")
    if not base:
        raise LLMError("Lipsește adresa serverului (base URL) în Setări AI.")
    body = {"model": s["model"], "messages": [{"role": "system", "content": system}] + messages, "max_tokens": max_tokens}
    if schema:
        body["response_format"] = {"type": "json_object"}
        body["messages"][0]["content"] += "\n\nRăspunde DOAR cu un obiect JSON valid conform schemei:\n" + json.dumps(schema, ensure_ascii=False)
    req = urllib.request.Request(base + "/chat/completions", data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {s.get('api_key') or 'none'}"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            data = json.loads(r.read())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:300]
        if e.code == 404:
            names = list_models(s)
            if names:
                raise LLMError(f"Modelul „{s['model']}” nu e disponibil pentru cheia ta. Modele disponibile: "
                               + ", ".join(names[:15]) + ". Alege unul în Setări AI.")
        raise LLMError(f"Eroare de la furnizor ({e.code}): {detail}")
    except (urllib.error.URLError, TimeoutError) as e:
        raise LLMError(f"Nu mă pot conecta la {base}: {e}")
    try:
        return (data["choices"][0]["message"]["content"] or "").strip()
    except (KeyError, IndexError, TypeError):
        raise LLMError("Răspuns neașteptat de la furnizor.")


def list_models(s: dict) -> list[str]:
    """Modelele oferite de un server compatibil OpenAI (GET /models), pentru mesaje de eroare utile."""
    base = (s.get("base_url") or "").rstrip("/")
    req = urllib.request.Request(base + "/models", headers={"Authorization": f"Bearer {s.get('api_key') or 'none'}"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read())
    except (urllib.error.URLError, TimeoutError, ValueError):
        return []
    names = [str(m.get("id", "")).removeprefix("models/") for m in data.get("data", []) if isinstance(m, dict)]
    return sorted(n for n in names if n and not any(x in n for x in ("embedding", "tts", "image", "audio", "aqa")))


def call(system: str, messages: list[dict], schema: dict | None = None) -> tuple[str, dict]:
    s = load_settings()
    if not configured():
        raise LLMError("Configurează mai întâi furnizorul AI și cheia în pagina „Setări AI”.")
    fn = _claude_call if s["provider"] == "anthropic" else _openai_call
    return fn(s, system, messages, schema), _info(s)


def call_json(system: str, prompt: str, schema: dict) -> tuple[dict, dict]:
    text, info = call(system, [{"role": "user", "content": prompt}], schema)
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`")
        t = t[t.find("{"):]
    try:
        data = json.loads(t[t.find("{"): t.rfind("}") + 1])
    except ValueError:
        raise LLMError("Modelul nu a întors JSON valid. Încearcă din nou.")
    missing = [k for k in schema.get("required", []) if k not in data]
    if missing:
        raise LLMError(f"Răspuns incomplet (lipsesc: {', '.join(missing)}).")
    return data, info


# ---------------------------------------------------------------------------
# funcționalități

EXPLAIN_SCHEMA = {
    "type": "object",
    "properties": {
        "is_term": {"type": "boolean"},
        "reason": {"type": "string"},
        "label": {"type": "string"},
        "kind": {"type": "string"},
        "level": {"type": "integer"},
        "definition": {"type": "string"},
        "explanation": {"type": "string"},
        "in_context": {"type": "string"},
        "aliases": {"type": "array", "items": {"type": "string"}},
        "related": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["is_term", "reason", "label", "kind", "level", "definition", "explanation", "in_context", "aliases", "related"],
    "additionalProperties": False,
}


def explain_term(selection: str, passage: str, chapter_labels: list[str]) -> tuple[dict, dict]:
    system = ("Ești asistentul unui manual de programare în C pentru anul I. Explici termeni selectați de student "
              "din textul laboratorului, în română, clar și corect. Răspunzi strict în formatul JSON cerut.")
    prompt = f"""Studentul a selectat: „{selection}”

Pasajul din laborator:
<pasaj>
{passage}
</pasaj>

Decide dacă selecția este un termen tehnic de învățat (is_term). Dacă nu e (cuvânt uzual, fragment fără sens), \
explică pe scurt de ce în „reason” și lasă celelalte câmpuri scurte.
Dacă e termen:
- label: forma de bază (singular nearticulat, litere mici, sau identificatorul C exact);
- kind: unul dintre: noțiune, tip de date, operator, instrucțiune, cuvânt cheie, funcție de bibliotecă, fișier antet, directivă preprocesor, unealtă, opțiune de compilare, eroare, bună practică, tehnică, specificator de format;
- level: 1 (bază), 2 (aprofundare) sau 3 (detaliu);
- definition: 1–2 fraze; explanation: o explicație mai pe larg (3–6 fraze) cu un exemplu mic;
- in_context: ce înseamnă termenul exact în pasajul de mai sus;
- aliases: alte forme (sinonime, forma englezească);
- related: până la 5 termeni înrudiți ALEȘI DOAR din lista: {", ".join(chapter_labels[:150])}."""
    return call_json(system, prompt, EXPLAIN_SCHEMA)


QUESTION_SCHEMA = {
    "type": "object",
    "properties": {
        "prompt": {"type": "string"},
        "options": {"type": "array", "items": {"type": "string"}},
        "answer": {"type": "integer"},
        "explanation": {"type": "string"},
    },
    "required": ["prompt", "options", "answer", "explanation"],
    "additionalProperties": False,
}


def generate_question(concept: dict, source_text: str) -> tuple[dict, dict]:
    system = ("Scrii întrebări grilă în română pentru un curs de programare în C, anul I. Întrebările verifică "
              "înțelegerea (nu memorarea), au exact 4 variante, una singură corectă, și o explicație scurtă.")
    prompt = f"""Concept: {concept['label']} (tip: {concept['kind']}, nivel {concept['level']})
Definiție: {concept.get('definition', '')}
Fragment din laborator:
<fragment>
{source_text[:1500]}
</fragment>

Scrie o întrebare grilă. Poate conține un fragment scurt de cod C. „answer” este indexul (0–3) variantei corecte."""
    data, info = call_json(system, prompt, QUESTION_SCHEMA)
    opts = data.get("options") or []
    if len(opts) != 4 or not (0 <= int(data.get("answer", -1)) < 4):
        raise LLMError("Întrebare generată invalid (nu are 4 variante).")
    return data, info


def tutor_reply(history: list[dict], problem: dict | None, code: str | None) -> tuple[str, dict]:
    system = TUTOR_SYSTEM
    if problem:
        system += f"\n\nProblema la care lucrează studentul: „{problem['title']}”\n<enunt>\n{problem['statement_text'][:4000]}\n</enunt>"
    if code:
        system += f"\n\nCodul curent al studentului:\n<cod>\n{code[:8000]}\n</cod>"
    return call(system, history)
