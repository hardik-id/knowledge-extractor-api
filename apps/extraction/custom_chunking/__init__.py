"""Custom chunking, a prototype: splitting code written by a sandbox agent (docs/extraction.md).

``sandbox`` runs a piece of splitting code on a text, ``author`` has an agent write that
code, ``fetch`` reads the reference page a person linked. ``enabled`` says whether the
server allows any of it (``CUSTOM_CHUNKING=local``).
"""

from django.conf import settings


def enabled() -> bool:
    return bool(settings.CUSTOM_CHUNKING == "local")
