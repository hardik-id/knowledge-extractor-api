"""Finding and creating the person behind a valid token.

A person is ``oid`` together with ``tid``. The first valid token from a person
creates their user record; later tokens reuse it. ``name`` and
``preferred_username`` are display values and follow the token, but a record
is written only when one of them changed.
"""

import uuid

from django.db import IntegrityError, transaction

from apps.identity.models import User
from apps.identity.tokens import TokenClaims

NAME_MAX_LENGTH = 255


def get_or_create_user(claims: TokenClaims) -> User:
    """Return the user for ``claims``, creating it on first sight.

    Raises ``ValueError`` when ``oid`` or ``tid`` is not a UUID.

    Two first requests at the same moment end with one user: the database
    refuses the second insert (unique ``oid`` and ``tid``) and that request
    reads the user the first one made.
    """
    oid = uuid.UUID(claims.oid)
    tid = uuid.UUID(claims.tid)
    name = _display(claims.name)
    preferred_username = _display(claims.preferred_username)

    user = User.objects.filter(oid=oid, tid=tid).first()
    if user is None:
        try:
            with transaction.atomic():
                return _create(oid, tid, name, preferred_username)
        except IntegrityError:
            user = User.objects.get(oid=oid, tid=tid)
    return _update_display(user, name, preferred_username)


def _create(
    oid: uuid.UUID, tid: uuid.UUID, name: str | None, preferred_username: str | None
) -> User:
    user = User(
        username=f"{tid}:{oid}",
        oid=oid,
        tid=tid,
        name=name or "",
        preferred_username=preferred_username or "",
    )
    user.set_unusable_password()  # signs in with a token, never a password
    user.save()
    return user


def _update_display(
    user: User, name: str | None, preferred_username: str | None
) -> User:
    """Write only what changed. A claim the token does not carry changes nothing."""
    changed: list[str] = []
    if name is not None and name != user.name:
        user.name = name
        changed.append("name")
    if preferred_username is not None and preferred_username != user.preferred_username:
        user.preferred_username = preferred_username
        changed.append("preferred_username")
    if changed:
        user.save(update_fields=changed)
    return user


def _display(value: str | None) -> str | None:
    return value[:NAME_MAX_LENGTH] if value else None
