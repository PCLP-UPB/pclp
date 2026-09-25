"""Conținutul cursului (laboratoare, concepte, probleme, teste) — versiunea activă și actualizarea ei.

Conținutul vine în două feluri:
  - inclus în imagine, la build: $PCLP_CONTENT (implicit /opt/pclp/content/build);
  - pachete publicate separat (GitHub Releases), descărcate automat în
    $PCLP_STATE/content/<versiune>/ — director ignorat de git, deci nu intră în arhive.

Versiunea activă = cea mai nouă dintre cele două care e validă și are o schemă compatibilă.
Folosit și de portal, și de `pclp` (test, week, update), ca să vadă aceleași teste.
Doar biblioteca standard.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import sqlite3
import tarfile
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# schema bazei de conținut pe care o înțelege acest cod (portal + pclp); build_database scrie aceeași valoare
SCHEMA = 1
DEFAULT_URL = "https://github.com/PCLP-UPB/pclp/releases/latest/download/content.json"
REQUIRED = ("content.sqlite", "bundle.json", "course.json")


def base_dir() -> Path:
    return Path(os.environ.get("PCLP_CONTENT", "/opt/pclp/content/build"))


def state_dir() -> Path:
    home = Path(os.environ.get("HOME", "/home/student"))
    work = Path(os.environ.get("PCLP_WORK", home / "work"))
    return Path(os.environ.get("PCLP_STATE", work / ".pclp" / "state"))


def store() -> Path:
    return state_dir() / "content"


def manifest_url() -> str:
    return os.environ.get("PCLP_CONTENT_URL", "")


def read_bundle(d: Path) -> dict:
    try:
        return json.loads((d / "bundle.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def valid(d: Path) -> bool:
    if not all((d / f).exists() for f in REQUIRED):
        return False
    b = read_bundle(d)
    return b.get("schema") == SCHEMA and bool(b.get("built_at"))


def active_dir() -> Path:
    """Directorul de conținut folosit acum: pachetul descărcat, dacă e mai nou decât cel din imagine."""
    base = base_dir()
    best, best_at = base, read_bundle(base).get("built_at", "")
    try:
        name = (store() / "current").read_text().strip()
    except OSError:
        name = ""
    if name:
        d = store() / name
        if valid(d) and read_bundle(d).get("built_at", "") > best_at:
            best = d
    return best


def active_info() -> dict:
    d = active_dir()
    b = read_bundle(d)
    return {"dir": str(d), "version": b.get("version", "?"), "built_at": b.get("built_at", ""),
            "source": "imagine" if d == base_dir() else "actualizare"}


# ---------------------------------------------------------------------------
# actualizare

def _get(url: str, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "pclp-content-update/1"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _fresh(url: str) -> str:
    """Adresa `releases/latest/...` a GitHub e ținută în cache de rețea câteva minute; un parametru
    unic forțează răspunsul curent."""
    return url + ("&" if "?" in url else "?") + f"t={int(datetime.now(timezone.utc).timestamp())}"


def check(url: str | None = None) -> dict:
    """Ce versiune e publicată și dacă e mai nouă decât cea activă (fără descărcare)."""
    url = url or manifest_url()
    if not url:
        return {"status": "dezactivat"}
    man = json.loads(_get(_fresh(url)))
    cur = read_bundle(active_dir())
    newer = man.get("built_at", "") > cur.get("built_at", "")
    if newer and man.get("schema") != SCHEMA:
        return {"status": "imagine-veche", "manifest": man, "current": cur}
    return {"status": "nou" if newer else "la-zi", "manifest": man, "current": cur}


def _safe_extract(tar: tarfile.TarFile, dest: Path):
    for m in tar.getmembers():
        p = Path(m.name)
        if p.is_absolute() or ".." in p.parts or not (m.isfile() or m.isdir()):
            raise ValueError(f"membru nepermis în pachet: {m.name}")
    try:
        tar.extractall(dest, filter="data")
    except TypeError:  # Python < 3.12
        tar.extractall(dest)


def update(url: str | None = None, keep: int = 2) -> dict:
    """Descarcă, verifică și activează versiunea nouă. Sigur de rulat din mai multe procese."""
    url = url or manifest_url()
    if not url:
        return {"status": "dezactivat"}
    st = store()
    st.mkdir(parents=True, exist_ok=True)
    with open(st / ".lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        info = check(url)
        if info["status"] != "nou":
            return info
        man = info["manifest"]
        version = str(man["version"])
        # adresa exactă a versiunii (din manifest); altfel, relativ la manifest
        asset_url = man.get("asset_url") or _fresh(url.split("?")[0].rsplit("/", 1)[0] + "/" + (man.get("asset") or "content.tar.gz"))
        data = _get(asset_url, timeout=300)
        if hashlib.sha256(data).hexdigest() != man.get("sha256"):
            return {"status": "eroare", "error": "amprenta SHA-256 a pachetului nu corespunde"}
        target = st / version
        tmp = Path(tempfile.mkdtemp(prefix=".new-", dir=st))
        try:
            with tarfile.open(fileobj=__import__("io").BytesIO(data), mode="r:gz") as tar:
                _safe_extract(tar, tmp)
            if not valid(tmp):
                raise ValueError("pachet incomplet sau cu schemă incompatibilă")
            con = sqlite3.connect(f"file:{tmp / 'content.sqlite'}?mode=ro", uri=True)
            ok = con.execute("PRAGMA integrity_check").fetchone()[0]
            con.close()
            if ok != "ok":
                raise ValueError("baza de conținut e coruptă")
            if target.exists():
                shutil.rmtree(target)
            tmp.rename(target)
        except Exception as e:  # noqa: BLE001
            shutil.rmtree(tmp, ignore_errors=True)
            return {"status": "eroare", "error": str(e)}
        (st / "current.tmp").write_text(version)
        (st / "current.tmp").replace(st / "current")
        (st / "notice.json").write_text(json.dumps({"version": version, "built_at": man.get("built_at"),
                                                    "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                                    "changes": man.get("changes", [])}, ensure_ascii=False))
        # păstrăm ultimele `keep` versiuni, ca rezervă
        versions = sorted((d for d in st.iterdir() if d.is_dir() and not d.name.startswith(".")),
                          key=lambda d: read_bundle(d).get("built_at", ""), reverse=True)
        for old in versions[keep:]:
            shutil.rmtree(old, ignore_errors=True)
        return {"status": "actualizat", "version": version, "manifest": man}
