"""
WSGI config for config project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/6.1/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application

from apps.core.telemetry import setup_telemetry

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")

# Before the application loads, so the Django middleware is instrumented. Each
# worker process imports this module itself, and so sets up its own SDK.
setup_telemetry()

application = get_wsgi_application()
