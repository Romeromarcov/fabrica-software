"""Settings mínimos del proyecto fixture (solo para ejercitar los gates de runtime).

Lee DATABASE_URL del entorno y configura el engine de Postgres parseando manualmente
la URL (soporta `postgres://user:pass@host:port/db` y `postgresql://...`). Si no hay
DATABASE_URL, cae a SQLite en memoria (útil para un sanity-check local sin Postgres).

NO contiene secretos en VCS: SECRET_KEY se lee del entorno con un default de desarrollo
claramente marcado (este proyecto nunca corre en producción).
"""
import os
from pathlib import Path
from urllib.parse import unquote, urlparse

BASE_DIR = Path(__file__).resolve().parent

# Default de desarrollo CLARAMENTE marcado — NO es un secreto real (solo fixture de CI).
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-only-insecure-fixture-key-not-a-secret")

DEBUG = True
ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "core",
]

MIDDLEWARE = [
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "urls"

TEMPLATES = []

WSGI_APPLICATION = "wsgi.application"


def _database_from_url(url: str) -> dict:
    """Parsea `postgres://user:pass@host:port/db` → config de Django ENGINE postgres."""
    parsed = urlparse(url)
    scheme = parsed.scheme.split("+", 1)[0]
    if scheme in ("postgres", "postgresql"):
        return {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": unquote((parsed.path or "/").lstrip("/")),
            "USER": unquote(parsed.username or ""),
            "PASSWORD": unquote(parsed.password or ""),
            "HOST": parsed.hostname or "localhost",
            "PORT": str(parsed.port or "5432"),
        }
    # Fallback defensivo: cualquier otro esquema → SQLite (no debería ocurrir en CI).
    return {"ENGINE": "django.db.backends.sqlite3", "NAME": str(BASE_DIR / "db.sqlite3")}


_DATABASE_URL = os.getenv("DATABASE_URL", "")
if _DATABASE_URL:
    DATABASES = {"default": _database_from_url(_DATABASE_URL)}
else:
    # Sin DATABASE_URL: SQLite en memoria (sanity-check local sin Postgres).
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True
