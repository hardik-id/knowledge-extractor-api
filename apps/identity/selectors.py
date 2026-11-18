"""Reads for the identity app."""

from apps.identity.models import User


def get_me(user: User) -> User:
    """The signed-in person, as stored."""
    return User.objects.get(pk=user.pk)
