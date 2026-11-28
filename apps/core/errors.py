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
    "document_not_found": ErrorCode(404, "Document not found."),
    "run_not_found": ErrorCode(404, "Run not found."),
    "workspace_not_found": ErrorCode(404, "Workspace not found."),
    "tenant_not_found": ErrorCode(404, "Tenant not found."),
    "file_not_found": ErrorCode(404, "File not found."),
    "extraction_not_found": ErrorCode(404, "This file has no extraction yet."),
    "record_not_found": ErrorCode(404, "Record not found."),
    "value_not_found": ErrorCode(404, "Value not found."),
    "revision_conflict": ErrorCode(409, "The records changed since they were loaded."),
    "unknown_field": ErrorCode(
        422, "This record type or field is not in the extraction definition."
    ),
    "invalid_span": ErrorCode(422, "The span does not match the text."),
    "not_deletable": ErrorCode(
        422, "A suggestion cannot be deleted. Reject it instead."
    ),
    "too_many_values": ErrorCode(422, "This field takes a single value."),
    "upstream_not_ready": ErrorCode(422, "The file has no text to extract from yet."),
    "no_files": ErrorCode(422, "A run needs at least one file."),
    "mixed_sources": ErrorCode(
        422, "A run cannot mix storage documents with files from other sources."
    ),
    "unsupported_source": ErrorCode(422, "This source is not supported yet."),
    "definition_conflict": ErrorCode(
        409, "Someone saved a newer version of this definition."
    ),
    "invalid_definition": ErrorCode(422, "The extraction definition is not valid."),
    "definition_version_not_found": ErrorCode(
        404, "This version of the definition was not found."
    ),
    "custom_chunking_off": ErrorCode(
        409, "Custom chunking is turned off on this server."
    ),
    "model_not_configured": ErrorCode(409, "No language model is configured."),
    "model_unreachable": ErrorCode(502, "The language model could not be reached."),
    "custom_chunking_failed": ErrorCode(
        422,
        "The assistant could not write splitting code that works on these "
        "documents. Try describing it differently.",
    ),
    "custom_chunking_timeout": ErrorCode(
        504, "Writing the splitting code took too long. Try again."
    ),
    "unknown_template": ErrorCode(422, "This template does not exist."),
    "template_not_found": ErrorCode(404, "Template not found."),
    "assistant_busy": ErrorCode(409, "The assistant is still answering."),
    "empty_message": ErrorCode(422, "Write a message first."),
    "run_belongs_to_workspace": ErrorCode(
        409, "This run belongs to a workspace. Delete the workspace instead."
    ),
    "execution_in_progress": ErrorCode(409, "This stage is already running."),
    "unknown_file": ErrorCode(422, "One of the files is not part of this run."),
    "conflict": ErrorCode(409, "The request conflicts with the current state."),
    "validation_error": ErrorCode(422, "The request is not valid."),
    "server_error": ErrorCode(500, "Something went wrong."),
    "not_ready": ErrorCode(503, "The service is not ready."),
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
