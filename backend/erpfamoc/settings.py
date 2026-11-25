"""
Configuración de Django para el ERP Famoc.

Los datos sensibles se leen de variables de entorno. Para desarrollo local
funcionan los valores por defecto; en producción define al menos:
DJANGO_SECRET_KEY, DJANGO_DEBUG=0, DJANGO_ALLOWED_HOSTS, DB_PASSWORD.
"""

import os
from pathlib import Path
from urllib.parse import unquote, urlparse

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent


def _env_bool(nombre, por_defecto=False):
    valor = os.environ.get(nombre, "1" if por_defecto else "0")
    return valor.strip().lower() in ("1", "true", "yes", "on")


_CLAVE_DE_DESARROLLO = "django-insecure-solo-desarrollo-cambiar-en-produccion"
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", _CLAVE_DE_DESARROLLO)

DEBUG = _env_bool("DJANGO_DEBUG", por_defecto=True)

# Con DEBUG apagado (producción) es obligatorio definir una clave propia: con la
# clave de desarrollo cualquiera podría fabricar tokens JWT válidos.
if not DEBUG and SECRET_KEY == _CLAVE_DE_DESARROLLO:
    raise ImproperlyConfigured(
        "Define DJANGO_SECRET_KEY con una clave larga y aleatoria cuando DJANGO_DEBUG=0."
    )

ALLOWED_HOSTS = [
    h.strip()
    for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
    if h.strip()
]

# Render define RENDER_EXTERNAL_HOSTNAME (p. ej. erp-famoc.onrender.com) en cada servicio web.
_HOST_RENDER = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "").strip()
if _HOST_RENDER:
    ALLOWED_HOSTS.append(_HOST_RENDER)


INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "famocapp",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # Sirve los estáticos del admin (/admin/) desde gunicorn, sin nginx extra.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "erpfamoc.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "erpfamoc.wsgi.application"


def _base_desde_url(url):
    """Convierte una DATABASE_URL (postgresql://usuario:clave@host:puerto/nombre) a la config de Django."""
    partes = urlparse(url)
    if partes.scheme not in ("postgres", "postgresql"):
        raise ImproperlyConfigured("DATABASE_URL debe empezar por postgresql://")
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": unquote(partes.path.lstrip("/")),
        "USER": unquote(partes.username or ""),
        "PASSWORD": unquote(partes.password or ""),
        "HOST": partes.hostname or "localhost",
        "PORT": str(partes.port or 5432),
    }


# Base de datos: PostgreSQL por defecto.
# Si existe DATABASE_URL (Render, Railway...) se usa esa.
# Para probar sin PostgreSQL: DB_ENGINE=sqlite
if os.environ.get("DATABASE_URL"):
    DATABASES = {"default": _base_desde_url(os.environ["DATABASE_URL"])}
elif os.environ.get("DB_ENGINE", "postgres") == "sqlite":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ.get("DB_NAME", "ERP_Famoc"),
            "USER": os.environ.get("DB_USER", "postgres"),
            "PASSWORD": os.environ.get("DB_PASSWORD", ""),
            "HOST": os.environ.get("DB_HOST", "localhost"),
            "PORT": os.environ.get("DB_PORT", "5432"),
        }
    }


AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


LANGUAGE_CODE = "es-co"
TIME_ZONE = "America/Bogota"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
# Destino de `collectstatic` (estáticos del admin), servido por WhiteNoise.
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"


# Autenticación y seguridad (RF-03)
#
# La API usa JWT (ver famocapp/jwt_auth.py). La sesión de Django solo la usa el
# panel /admin/, por eso las cookies de sesión/CSRF siguen configuradas.
SESSION_COOKIE_AGE = 60 * 60 * 8  # 8 horas
SESSION_COOKIE_HTTPONLY = True
# Poner DJANGO_HTTPS=1 cuando el sitio se sirva por HTTPS.
SESSION_COOKIE_SECURE = _env_bool("DJANGO_HTTPS", False)
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE

# JWT: access token corto (en memoria del navegador) + refresh token largo
# (cookie httpOnly, SameSite=Strict, solo viaja a /api/).
# `or` (y no el valor por defecto de get): una variable vacía no debe dar una clave vacía.
JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY") or SECRET_KEY
JWT_ACCESS_MINUTES = int(os.environ.get("JWT_ACCESS_MINUTES", "15"))
JWT_REFRESH_HOURS = int(os.environ.get("JWT_REFRESH_HOURS", "8"))
JWT_COOKIE_SECURE = SESSION_COOKIE_SECURE

# Detrás de nginx/un proxy HTTPS, Django debe confiar en X-Forwarded-Proto.
if _env_bool("DJANGO_HTTPS", False):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Orígenes desde los que se aceptan POST del admin (Vite en desarrollo y, en
# producción, el dominio público: p. ej. https://erp.midominio.com).
CSRF_TRUSTED_ORIGINS = [
    o.strip()
    for o in os.environ.get(
        "DJANGO_CSRF_TRUSTED_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    ).split(",")
    if o.strip()
]
if _HOST_RENDER:
    CSRF_TRUSTED_ORIGINS.append(f"https://{_HOST_RENDER}")

# Frontend compilado: si existe la carpeta, WhiteNoise lo sirve en la raíz (/) y así
# una sola URL entrega la página y la API (necesario para la cookie SameSite=Strict).
FRONTEND_DIST = Path(os.environ.get("FRONTEND_DIST", BASE_DIR / "frontend_dist"))
if FRONTEND_DIST.is_dir():
    WHITENOISE_ROOT = FRONTEND_DIST
    WHITENOISE_INDEX_FILE = True
