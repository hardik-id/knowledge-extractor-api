"""Production settings: nothing is guessed, missing configuration stops startup."""

from django.core.exceptions import ImproperlyConfigured

from .base import *
from .base import AUTH_MODE, env

# env.str without a default raises ImproperlyConfigured naming the variable.
SECRET_KEY = env.str("DJANGO_SECRET_KEY")
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS")
DEBUG = False

if AUTH_MODE == "dev":
    raise ImproperlyConfigured(
        "AUTH_MODE=dev is not allowed in production; set AUTH_MODE=entra."
    )

# HTTPS. TLS ends at the proxy, which must send X-Forwarded-Proto.
SECURE_SSL_REDIRECT = env.bool("DJANGO_SECURE_SSL_REDIRECT", default=True)
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True

# Preload submits the domain to browser lists and cannot be undone quickly;
# that is an owner decision, not a default.
SILENCED_SYSTEM_CHECKS = ["security.W021"]
