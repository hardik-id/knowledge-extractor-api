"""Settings for a developer machine. Every default here is safe to lose."""

import os
import uuid

from .base import *
from .base import env

SECRET_KEY = env.str("DJANGO_SECRET_KEY", default="django-insecure-local-throwaway-key")
DEBUG = env.bool("DJANGO_DEBUG", default=True)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])
AUTH_MODE = env.str("AUTH_MODE", default="dev")

# In dev mode the dev issuer's default person (apps/identity/dev_issuer.py) is a
# platform admin, unless IAM_PLATFORM_ADMIN_OIDS is set (set and empty means nobody).
if AUTH_MODE == "dev" and "IAM_PLATFORM_ADMIN_OIDS" not in os.environ:
    IAM_PLATFORM_ADMIN_OIDS = frozenset(
        {uuid.UUID("de000000-0000-4000-8000-000000000001")}
    )

# A UI dev server may run on any port.
CORS_ALLOWED_ORIGIN_REGEXES = [r"^http://localhost:\d+$"]
