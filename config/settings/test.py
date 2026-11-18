"""Settings for the test run: deterministic and fast, nothing read from .env."""

import hashlib

from .base import *

SECRET_KEY = "django-insecure-test-only-key"
DEBUG = False
ALLOWED_HOSTS = ["testserver", "localhost"]
AUTH_MODE = "dev"
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# The test database name is unique per checkout, so parallel git worktrees never
# share or drop each other's test database. The suffix comes from the project path.
_checkout = hashlib.sha256(str(BASE_DIR).encode()).hexdigest()[:8]
DATABASES["default"]["TEST"] = {
    "NAME": f"test_{DATABASES['default']['NAME']}_{_checkout}"[:63],
}
