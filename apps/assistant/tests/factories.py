import factory

from apps.assistant.models import Message, Role, Status
from apps.runs.tests.factories import RunFactory


class MessageFactory(factory.django.DjangoModelFactory):
    """A person's message, done. Pass ``role``, ``status`` and ``reply_to`` for a reply."""

    class Meta:
        model = Message

    run = factory.SubFactory(RunFactory)
    role = Role.USER
    text = "Extract every architecture decision record"
    status = Status.DONE
