"""Bearer authentication: ``Authorization: Bearer <Entra ID access token>``.

The token is checked by ``validate_access_token`` (``tokens.py``), the person
comes from ``services.get_or_create_user``. See docs/auth.md.
"""

import structlog
from rest_framework import exceptions
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.request import Request

from apps.core.errors import ApiError
from apps.identity.models import User
from apps.identity.services import get_or_create_user
from apps.identity.tokens import (
    TokenClaims,
    TokenError,
    TokenErrorReason,
    validate_access_token,
)

log = structlog.get_logger(__name__)

SCHEME = b"bearer"


class BearerAuthentication(BaseAuthentication):
    """Returns ``(user, claims)``.

    - No ``Authorization`` header, or another scheme: no answer here, and the
      permission check then answers 401.
    - A token that is refused: 401 ``unauthenticated`` with
      ``WWW-Authenticate: Bearer``.
    - Keys that cannot be fetched: 503, because nothing is known about the token.
    - A deactivated user: 403 ``forbidden``.
    """

    def authenticate(self, request: Request) -> tuple[User, TokenClaims] | None:
        parts = get_authorization_header(request).split()
        if not parts or parts[0].lower() != SCHEME:
            return None
        if len(parts) != 2:
            raise exceptions.AuthenticationFailed()
        try:
            token = parts[1].decode("ascii")
        except UnicodeDecodeError:
            raise exceptions.AuthenticationFailed() from None

        try:
            claims = validate_access_token(token)
        except TokenError as error:
            if error.reason is TokenErrorReason.KEYS_UNAVAILABLE:
                raise ApiError(
                    "not_ready", "Sign-in is not available right now."
                ) from None
            raise exceptions.AuthenticationFailed() from None

        try:
            user = get_or_create_user(claims)
        except ValueError:  # oid or tid is not a UUID
            raise exceptions.AuthenticationFailed() from None
        if not user.is_active:
            raise ApiError("forbidden")

        structlog.contextvars.bind_contextvars(user_id=user.pk)
        return user, claims

    def authenticate_header(self, request: Request) -> str:
        return "Bearer"
