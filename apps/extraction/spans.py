"""Spans: ``{start, end, quote}`` into a document's text.

Offsets count Unicode code points and ``end`` is exclusive: plain ``str`` indexing.
A ``Span`` is stored as the same JSON it always was (``as_json``); ``from_json``
reads it back. Anything that arrives from outside (a request) goes through
``check_span``.
"""

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any, Self

from apps.core.errors import ApiError


@dataclass(frozen=True)
class Span:
    start: int
    end: int
    quote: str

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> Self:
        """A stored span. Not checked: use ``check_span`` for data from outside."""
        return cls(data["start"], data["end"], data["quote"])

    def as_json(self) -> dict[str, Any]:
        return asdict(self)


def _invalid(message: str) -> ApiError:
    return ApiError("invalid_span", message)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _problem(text: str, span: Span) -> str | None:
    """Why the span does not fit ``text``, or None when it does."""
    if not 0 <= span.start <= span.end <= len(text):
        return "The span's offsets are out of range."
    if text[span.start : span.end] != span.quote:
        return "The span's quote is not the text at its offsets."
    return None


def check_span(text: str, data: Any) -> Span:
    """The span in ``data``, if ``text[start:end] == quote`` and the offsets are in range.

    Otherwise 422 ``invalid_span``.
    """
    if not isinstance(data, dict):
        raise _invalid("A span is { start, end, quote }.")
    start: Any = data.get("start")
    end: Any = data.get("end")
    quote: Any = data.get("quote")
    if not (_is_int(start) and _is_int(end) and isinstance(quote, str)):
        raise _invalid("A span is { start, end, quote }.")
    span = Span(start, end, quote)
    problem = _problem(text, span)
    if problem:
        raise _invalid(problem)
    return span


def anchor(text: str, quote: str) -> Span | None:
    """The first exact occurrence of ``quote`` in ``text`` as a span, or None."""
    if not quote:
        return None
    start = text.find(quote)
    if start < 0:
        return None
    return Span(start, start + len(quote), quote)


def resolve_span(text: str, span: Span) -> tuple[Span, bool]:
    """A span from the model, made to fit: ``(span, anchored)``.

    A span that fits is kept. One whose offsets do not fit is searched for by its
    quote. A quote that is not in the text is kept as returned with ``anchored``
    false, never dropped.
    """
    if _problem(text, span) is None:
        return span, True
    found = anchor(text, span.quote)
    if found is not None:
        return found, True
    return span, False
