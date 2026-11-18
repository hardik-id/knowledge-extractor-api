"""Settings for the test run: deterministic and fast, nothing read from .env."""

from .base import *

SECRET_KEY = 'django-insecure-test-only-key'
DEBUG = False
ALLOWED_HOSTS = ['testserver', 'localhost']
AUTH_MODE = 'dev'
PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
