from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """The project's user.

    A person signed in through Entra ID is identified by ``oid`` together with
    ``tid``. Local admin accounts have neither (both NULL). ``name`` and
    ``preferred_username`` are for display only: they can change and are not
    unique, so they are never used as a key.
    """

    oid = models.UUIDField(null=True, blank=True)
    tid = models.UUIDField(null=True, blank=True)
    name = models.CharField(max_length=255, blank=True)
    preferred_username = models.CharField(max_length=255, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["oid", "tid"],
                condition=models.Q(oid__isnull=False, tid__isnull=False),
                name="identity_user_oid_tid_unique",
            ),
        ]
