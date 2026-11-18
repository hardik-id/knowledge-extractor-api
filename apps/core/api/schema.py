"""OpenAPI wiring: the sign-in scheme and the error responses.

Both are added here, in one place, so no view repeats them. See docs/openapi.md.
"""

from typing import Any

from django.conf import settings
from drf_spectacular.extensions import OpenApiAuthenticationExtension
from drf_spectacular.openapi import AutoSchema
from drf_spectacular.utils import OpenApiResponse
from rest_framework import serializers

ERROR_RESPONSES = {
    "401": "Not signed in, or the token is refused.",
    "403": "Signed in, but not allowed to do this.",
    "404": "Not found, or not visible to the signed-in person.",
    "422": "The request is not valid.",
}


class ErrorSerializer(serializers.Serializer):  # type: ignore[type-arg]
    """The error body every non-2xx answer has. See docs/errors.md."""

    code = serializers.CharField(help_text="Stable, machine-readable error code.")
    message = serializers.CharField(help_text="Human-readable explanation.")
    details = serializers.DictField(
        required=False, help_text="Extra information, such as one list per field."
    )


def entra_authorize_urls() -> tuple[str, str]:
    """The tenant's v2 authorize and token URLs."""
    base = f"https://login.microsoftonline.com/{settings.ENTRA_TENANT_ID}/oauth2/v2.0"
    return f"{base}/authorize", f"{base}/token"


def entra_scope() -> str:
    return f"api://{settings.ENTRA_CLIENT_ID}/{settings.ENTRA_REQUIRED_SCOPE}"


class BearerAuthenticationScheme(OpenApiAuthenticationExtension):  # type: ignore[no-untyped-call]
    """Every view that uses ``BearerAuthentication`` is closed by a bearer token.

    With ``AUTH_MODE=entra`` the same views can also be opened with Microsoft's
    sign-in (OAuth2 authorization code), as an alternative to the pasted token.
    With ``AUTH_MODE=dev`` the bearer scheme is the only one.
    """

    target_class = "apps.identity.authentication.BearerAuthentication"

    @property
    def name(self) -> Any:  # type: ignore[override]
        if settings.AUTH_MODE == "entra":
            return ["bearerAuth", "oauth2"]
        return "bearerAuth"

    def get_security_requirement(self, auto_schema: Any) -> Any:
        if settings.AUTH_MODE == "entra":
            return [{"bearerAuth": []}, {"oauth2": [entra_scope()]}]
        return {"bearerAuth": []}

    def get_security_definition(self, auto_schema: Any) -> Any:
        bearer = {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": "An Entra ID access token (a dev token in local development).",
        }
        if settings.AUTH_MODE != "entra":
            return bearer
        authorize_url, token_url = entra_authorize_urls()
        oauth2 = {
            "type": "oauth2",
            "description": "Sign in with Microsoft (authorization code with PKCE).",
            "flows": {
                "authorizationCode": {
                    "authorizationUrl": authorize_url,
                    "tokenUrl": token_url,
                    "scopes": {entra_scope(): "Act as the signed-in person."},
                }
            },
        }
        return [bearer, oauth2]


class ApiSchema(AutoSchema):
    """Adds the standard error responses to every operation."""

    def _get_response_bodies(self, direction: Any = "response") -> Any:
        responses = super()._get_response_bodies(direction)
        for status, description in ERROR_RESPONSES.items():
            responses.setdefault(
                status,
                self._get_response_for_code(  # type: ignore[no-untyped-call]
                    OpenApiResponse(ErrorSerializer, description=description),
                    status,
                ),
            )
        return responses
