"""What every tool uses: wrapping untrusted text, clipping, the wording of an error."""

NAME_CHARS = 200  # of a document name


def as_data(text: str) -> str:
    """Document text cannot close the element it is wrapped in."""
    return text.replace("</document>", "</ document>")


def clip(text: str, limit: int) -> str:
    return text[:limit]


def error(message: str) -> str:
    """A failure, as the model reads it: text that starts with ``Error:``."""
    return f"Error: {message}"
