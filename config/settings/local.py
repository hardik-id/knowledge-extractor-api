"""Settings for a developer machine. Every default here is safe to lose."""

from .base import *
from .base import env

SECRET_KEY = env.str("DJANGO_SECRET_KEY", default="django-insecure-local-throwaway-key")
DEBUG = env.bool("DJANGO_DEBUG", default=True)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])
AUTH_MODE = env.str("AUTH_MODE", default="dev")

# A UI dev server may run on any port.
CORS_ALLOWED_ORIGIN_REGEXES = [r"^http://localhost:\d+$"]
