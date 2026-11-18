"""The error contract: every code the API can answer with, and the exception to raise.

Add a code by adding one line to ``ERRORS``. See docs/errors.md.
"""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ErrorCode:
    status: int
    message: str


ERRORS: dict[str, ErrorCode] = {
    "bad_request": ErrorCode(400, "The request could not be read."),
    "unauthenticated": ErrorCode(401, "Authentication is required."),
    "forbidden": ErrorCode(403, "You do not have permission to do this."),
    "not_found": ErrorCode(404, "Not found."),
    "method_not_allowed": ErrorCode(405, "Method not allowed."),
    "conflict": ErrorCode(409, "The request conflicts with the current state."),
    "validation_error": ErrorCode(422, "The request is not valid."),
    "server_error": ErrorCode(500, "Something went wrong."),
}


class ApiError(Exception):
    """An error the API answers as ``{ "code", "message" }`` with optional ``details``.

    ``code`` must be registered in ``ERRORS``; an unknown code raises ``ValueError``
    at once, so a typo never reaches a client.
    """

    def __init__(
        self,
        code: str,
        message: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        if code not in ERRORS:
            raise ValueError(f"Unregistered error code: {code!r}")
        registered = ERRORS[code]
        self.code = code
        self.status = registered.status
        self.message = message or registered.message
        self.details = details
        super().__init__(self.message)

    def body(self) -> dict[str, Any]:
        body: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details:
            body["details"] = self.details
        return body
