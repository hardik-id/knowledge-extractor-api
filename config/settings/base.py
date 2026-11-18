"""Settings shared by every environment.

Everything that differs between machines is read from the environment (see
.env.example for the full contract). The environment modules (local, test,
production) import this module and override only what must differ.

Sections are labelled so that later changes touch one section each.
"""

from pathlib import Path

import environ

from apps.core.logging import build_logging_config, configure_structlog

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
# .env is for local use only and is ignored by git; a missing file is fine.
if (BASE_DIR / ".env").is_file():
    environ.Env.read_env(BASE_DIR / ".env")

# ---------------------------------------------------------------------------
# Core
# SECRET_KEY, DEBUG and ALLOWED_HOSTS are set by the environment modules.
# ---------------------------------------------------------------------------

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
APPEND_SLASH = False  # the UI calls /api/v1/runs, without a trailing slash

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
# collectstatic target; WhiteNoise serves it (see docs/docker.md)
STATIC_ROOT = BASE_DIR / "staticfiles"

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

# ---------------------------------------------------------------------------
# Apps
# ---------------------------------------------------------------------------

AUTH_USER_MODEL = "identity.User"

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "django_structlog",
    "apps.core",
    "apps.identity",
]

# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

MIDDLEWARE = [
    "apps.core.middleware.RequestIdMiddleware",
    "apps.core.middleware.RequestLogMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

# ---------------------------------------------------------------------------
# Database
# PostgreSQL from compose.yaml by default (see .env.example).
# ---------------------------------------------------------------------------

DATABASES = {
    "default": env.db(
        "DATABASE_URL",
        default=f"postgres://ke:ke@localhost:{env.int('DB_PORT', default=5432)}/ke",
    ),
}
DATABASES["default"]["CONN_HEALTH_CHECKS"] = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

# ---------------------------------------------------------------------------
# REST framework: JSON only, no browsable API.
# ---------------------------------------------------------------------------

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "EXCEPTION_HANDLER": "apps.core.api.exception_handler.exception_handler",
}

API_DOCS_ENABLED = env.bool("API_DOCS_ENABLED", default=True)

# ---------------------------------------------------------------------------
# Sign-in
# AUTH_MODE is 'entra' or 'dev'. The code default is the safe one; local.py
# switches to 'dev'.
# ---------------------------------------------------------------------------

AUTH_MODE = env.str("AUTH_MODE", default="entra")
if AUTH_MODE not in ("entra", "dev"):
    raise environ.ImproperlyConfigured(
        f"AUTH_MODE must be 'entra' or 'dev', got {AUTH_MODE!r}"
    )
ENTRA_TENANT_ID = env.str("ENTRA_TENANT_ID", default="")
ENTRA_CLIENT_ID = env.str("ENTRA_CLIENT_ID", default="")
ENTRA_REQUIRED_SCOPE = env.str("ENTRA_REQUIRED_SCOPE", default="access_as_user")

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOG_LEVEL = env.str("LOG_LEVEL", default="INFO")
LOG_FORMAT = env.str("LOG_FORMAT", default="console")  # 'json' or 'console'

# RequestIdMiddleware has already replaced an unfit X-Request-ID, so trust what is left.
DJANGO_STRUCTLOG_TRUST_UPSTREAM_REQUEST_ID = True
configure_structlog()
LOGGING = build_logging_config(LOG_LEVEL, LOG_FORMAT)

# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------

CORS_ALLOWED_ORIGINS = env.list(
    "CORS_ALLOWED_ORIGINS", default=["http://localhost:3000"]
)
