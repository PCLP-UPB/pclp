"""Setările portalului PCLP (rulează local, în container, pentru un singur student)."""
import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
REPO = BASE_DIR.parent

# Unde se află conținutul generat, spațiul de lucru al studentului și starea portalului.
PCLP_CONTENT = Path(os.environ.get("PCLP_CONTENT", REPO / "content" / "build"))
PCLP_PIPELINE = Path(os.environ.get("PCLP_PIPELINE", REPO / "content" / "pipeline"))
PCLP_WORK = Path(os.environ.get("PCLP_WORK", REPO / "work" / "dev"))
PCLP_STATE = Path(os.environ.get("PCLP_STATE", PCLP_WORK / ".pclp" / "state"))
# Adresa VS Code (code-server) văzută din browserul studentului, și calea spațiului de lucru în container.
PCLP_CODE_URL = os.environ.get("PCLP_CODE_URL", "http://localhost:8080")
PCLP_CODE_WORK = os.environ.get("PCLP_CODE_WORK", "/home/student/work")
# Modul autor (profesor): editarea conceptelor și relațiilor. Studenții nu îl au activ.
PCLP_AUTHOR = os.environ.get("PCLP_AUTHOR", "0") == "1"
PCLP_VERSION = os.environ.get("PCLP_VERSION", "dev")

PCLP_STATE.mkdir(parents=True, exist_ok=True)
# Actualizarea automată a conținutului (laboratoare, probleme, teste): manifestul publicat de
# workflow-ul „content”. Gol = dezactivat (implicit în dezvoltare; imaginea îl setează).
PCLP_CONTENT_URL = os.environ.get("PCLP_CONTENT_URL", "")
PCLP_UPDATE_HOURS = float(os.environ.get("PCLP_UPDATE_HOURS", "6"))
# modulul comun cu `pclp` (tools/pclp_content.py) citește aceleași căi din mediu
for _k, _v in (("PCLP_CONTENT", PCLP_CONTENT), ("PCLP_WORK", PCLP_WORK), ("PCLP_STATE", PCLP_STATE),
               ("PCLP_CONTENT_URL", PCLP_CONTENT_URL)):
    os.environ.setdefault(_k, str(_v))
PCLP_TOOLS = Path(os.environ.get("PCLP_TOOLS", REPO / "tools"))
_key_file = PCLP_STATE / "django-secret.txt"
if not _key_file.exists():
    _key_file.write_text(secrets.token_urlsafe(50))
SECRET_KEY = _key_file.read_text().strip()

DEBUG = os.environ.get("PCLP_DEBUG", "0") == "1"
ALLOWED_HOSTS = ["*"]  # portalul e publicat doar pe 127.0.0.1 (vezi compose.yaml)
CSRF_TRUSTED_ORIGINS = ["http://localhost:8000", "http://127.0.0.1:8000"]

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "glosar",
    "invatare.apps.InvatareConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "glosar.middleware.ContentVersionMiddleware",
]

ROOT_URLCONF = "pclp_site.urls"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates"],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.messages.context_processors.messages",
        "glosar.context.pclp",
    ]},
}]
WSGI_APPLICATION = "pclp_site.wsgi.application"

DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": PCLP_STATE / "app.sqlite"}}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
SESSION_ENGINE = "django.contrib.sessions.backends.signed_cookies"
MESSAGE_STORAGE = "django.contrib.messages.storage.cookie.CookieStorage"

LANGUAGE_CODE = "ro"
TIME_ZONE = "Europe/Bucharest"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = PCLP_STATE / "static"
STATIC_VERSION = "11"

LOGGING = {"version": 1, "handlers": {"console": {"class": "logging.StreamHandler"}},
           "root": {"handlers": ["console"], "level": "WARNING"}}
