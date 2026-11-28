from django.conf import settings
from django.db import models

from apps.core.models import BaseModel


class Role(models.TextChoices):
    USER = "user"
    ASSISTANT = "assistant"


class Status(models.TextChoices):
    STREAMING = "streaming"
    DONE = "done"


class Message(BaseModel):
    """One turn of a run's conversation with the assistant.

    A person's message is ``done`` from the start and keeps the ``definition``
    they sent it with. The assistant's reply starts empty and ``streaming``,
    points at the message it answers (``reply_to``) and is filled by the reply
    job. A run has at most one reply streaming at a time.
    """

    run = models.ForeignKey(
        "runs.Run", on_delete=models.CASCADE, related_name="assistant_messages"
    )
    role = models.CharField(max_length=16, choices=Role.choices)
    text = models.TextField(blank=True, default="")
    proposal = models.JSONField(null=True, blank=True)  # {definition, reasons}
    status = models.CharField(max_length=16, choices=Status.choices)
    definition = models.JSONField(null=True, blank=True)  # the draft sent with it
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )  # who wrote a person's message; null on the assistant's and on older ones
    reply_to = models.ForeignKey(
        "self", on_delete=models.CASCADE, null=True, blank=True, related_name="+"
    )

    class Meta:
        ordering = ["created_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["run"],
                condition=models.Q(status="streaming"),
                name="one_reply_at_a_time",
            )
        ]
