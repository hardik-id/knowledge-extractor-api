"""OpenAPI wiring: the sign-in scheme and the error responses.

Both are added here, in one place, so no view repeats them. See docs/openapi.md.
"""

from typing import Any

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


class BearerAuthenticationScheme(OpenApiAuthenticationExtension):  # type: ignore[no-untyped-call]
    """Every view that uses ``BearerAuthentication`` is closed by a bearer token."""

    target_class = "apps.identity.authentication.BearerAuthentication"
    name = "bearerAuth"

    def get_security_definition(self, auto_schema: Any) -> dict[str, str]:
        return {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": "An Entra ID access token (a dev token in local development).",
        }


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
