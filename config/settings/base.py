"""Settings shared by every environment.

Everything that differs between machines is read from the environment (see
.env.example for the full contract). The environment modules (local, test,
production) import this module and override only what must differ.

Sections are labelled so that later changes touch one section each.
"""

from pathlib import Path

import environ
from corsheaders.defaults import default_headers
from django.utils.csp import CSP

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
    "drf_spectacular",
    "drf_spectacular_sidecar",
    "corsheaders",
    "django_structlog",
    "django_tasks_db",
    "apps.core",
    "apps.identity",
    "apps.documents",
    "apps.runs",
    "apps.realtime",
    "apps.extraction",
]

# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

MIDDLEWARE = [
    "apps.core.middleware.RequestIdMiddleware",
    "apps.core.telemetry.TelemetryMiddleware",
    "apps.core.middleware.RequestLogMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django.middleware.csp.ContentSecurityPolicyMiddleware",
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
# Background jobs: Django Tasks with a database queue (docs/jobs.md).
# The worker is `manage.py db_worker` (make worker); test.py runs jobs inline.
# ---------------------------------------------------------------------------

TASKS = {
    "default": {"BACKEND": "django_tasks_db.DatabaseBackend"},
}

# ---------------------------------------------------------------------------
# REST framework: JSON only, no browsable API.
# ---------------------------------------------------------------------------

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "EXCEPTION_HANDLER": "apps.core.api.exception_handler.exception_handler",
    "DEFAULT_PAGINATION_CLASS": "apps.core.pagination.DefaultPagination",
    # Sign-in: a bearer token is the only way in (no session or basic
    # authentication on the API) and every view is closed unless it opts out.
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "apps.identity.authentication.BearerAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_SCHEMA_CLASS": "apps.core.api.schema.ApiSchema",
}

# ---------------------------------------------------------------------------
# OpenAPI: schema at /api/schema, Swagger UI at /api/docs (docs/openapi.md).
# SPECTACULAR_SETTINGS reads nothing from the environment, so docs/openapi.yaml
# is the same on every machine.
# ---------------------------------------------------------------------------

API_DOCS_ENABLED = env.bool("API_DOCS_ENABLED", default=True)

SPECTACULAR_SETTINGS = {
    "TITLE": "Knowledge Extractor API",
    "VERSION": "v1",
    "SERVERS": [{"url": "/api/v1"}],
    "SCHEMA_PATH_PREFIX": "/api/v1",
    "SCHEMA_PATH_PREFIX_TRIM": True,
    "SERVE_INCLUDE_SCHEMA": False,
    # The schema and Swagger UI are open; "Try it out" sends its own token.
    "SERVE_AUTHENTICATION": [],
    # Swagger UI's files come from drf-spectacular-sidecar, not a CDN.
    "SWAGGER_UI_DIST": "SIDECAR",
    "SWAGGER_UI_FAVICON_HREF": "SIDECAR",
    "SWAGGER_UI_SETTINGS": {"persistAuthorization": True},
    "COMPONENT_SPLIT_REQUEST": True,
}

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

# Swagger UI's "Authorize" signs in with Microsoft: the browser client is the
# app registration itself, with PKCE and no secret (docs/auth.md). In dev mode
# the bearer scheme is the only one, so Swagger UI gets no OAuth2 settings.
if AUTH_MODE == "entra":
    SPECTACULAR_SETTINGS["SWAGGER_UI_OAUTH2_CONFIG"] = {
        "clientId": ENTRA_CLIENT_ID,
        "usePkceWithAuthorizationCodeFlow": True,
        "scopes": f"api://{ENTRA_CLIENT_ID}/{ENTRA_REQUIRED_SCOPE}",
    }
# Private key of the dev token issuer (AUTH_MODE=dev); created on first use.
DEV_AUTH_KEY_PATH = Path(
    env.str("DEV_AUTH_KEY_PATH", default=str(BASE_DIR / ".dev-keys" / "issuer.pem"))
)

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
# Studio
# Declared here so later PBIs read them from one place; nothing uses them yet.
# ---------------------------------------------------------------------------

# Live updates: channel layer and the lifetime of a socket ticket.
# REDIS_PORT is the host port of the compose Redis; REDIS_URL wins when set.
REDIS_PORT = env.int("REDIS_PORT", default=6379)
REDIS_URL = env.str("REDIS_URL", default=f"redis://localhost:{REDIS_PORT}/0")
WS_TICKET_TTL_SECONDS = env.int("WS_TICKET_TTL_SECONDS", default=30)
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {"hosts": [REDIS_URL]},
    },
}
# The echo socket at /ws/test/ that proves the wiring; off outside the tests.
REALTIME_TEST_ROUTE = env.bool("REALTIME_TEST_ROUTE", default=False)

# Documents: where the list and the content come from.
DOCUMENT_CATALOG = env.str("DOCUMENT_CATALOG", default="samples")  # samples | http
DOCUMENT_CATALOG_URL = env.str("DOCUMENT_CATALOG_URL", default="")
DOCUMENT_STORAGE = env.str("DOCUMENT_STORAGE", default="samples")  # samples | azure
AZURE_STORAGE_ACCOUNT_URL = env.str("AZURE_STORAGE_ACCOUNT_URL", default="")

# Assistant and extractor.
ASSISTANT_AGENT = env.str("ASSISTANT_AGENT", default="scripted")  # scripted | openai
EXTRACTOR = env.str("EXTRACTOR", default="scripted")
LLM_PROVIDER = env.str("LLM_PROVIDER", default="openai")  # openai | azure
LLM_MODEL = env.str("LLM_MODEL", default="")
OPENAI_API_KEY = env.str("OPENAI_API_KEY", default="")  # secret
AZURE_OPENAI_ENDPOINT = env.str("AZURE_OPENAI_ENDPOINT", default="")  # no key

# Telemetry (OpenTelemetry, exported over OTLP/HTTP).
OTEL_SDK_DISABLED = env.bool("OTEL_SDK_DISABLED", default=True)
OTEL_SERVICE_NAME = env.str("OTEL_SERVICE_NAME", default="knowledge-extractor-api")
OTEL_EXPORTER_OTLP_ENDPOINT = env.str(
    "OTEL_EXPORTER_OTLP_ENDPOINT", default="http://localhost:4318"
)
OTEL_RESOURCE_ATTRIBUTES = env.str(
    "OTEL_RESOURCE_ATTRIBUTES", default="deployment.environment=local"
)
# Logs go over OTLP only with "otlp" (the logs signal is not stable in Python yet).
OTEL_LOGS_EXPORTER = env.str("OTEL_LOGS_EXPORTER", default="none")  # none | otlp

# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------

# CORS: only the UI's origins, never '*', no cookies. See docs/security.md.
CORS_ALLOWED_ORIGINS = env.list(
    "CORS_ALLOWED_ORIGINS", default=["http://localhost:3000"]
)
if "*" in CORS_ALLOWED_ORIGINS:
    raise environ.ImproperlyConfigured("CORS_ALLOWED_ORIGINS must not contain '*'.")
CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOW_CREDENTIALS = False
# traceparent, tracestate and baggage let the browser agent continue a trace;
# Server-Timing carries the trace id back to it (docs/observability.md).
CORS_ALLOW_HEADERS = [
    *default_headers,
    "x-request-id",
    "traceparent",
    "tracestate",
    "baggage",
]
CORS_EXPOSE_HEADERS = ["ETag", "X-Request-ID", "Server-Timing"]

# Security headers on every response (HSTS is set in production.py).
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

# Content-Security-Policy for the pages this service renders itself (admin,
# later Swagger UI). Enforced, not report-only.
SECURE_CSP = {
    "default-src": [CSP.SELF],
    "img-src": [CSP.SELF, "data:"],
    "object-src": [CSP.NONE],
    "base-uri": [CSP.SELF],
    "form-action": [CSP.SELF],
    "frame-ancestors": [CSP.NONE],
}
