from django.conf import settings
from django.db import models

from apps.core.models import BaseModel


class WsTicket(BaseModel):
    """A one-time pass for a WebSocket, tied to the person who asked for it.

    Only the hash of the ticket is stored, so a copy of the table signs nobody
    in. ``used_at`` is set when the ticket is redeemed; see ``services.py``.
    """

    token_hash = models.CharField(max_length=64, unique=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+"
    )
    expires_at = models.DateTimeField(db_index=True)
    used_at = models.DateTimeField(null=True, blank=True)
