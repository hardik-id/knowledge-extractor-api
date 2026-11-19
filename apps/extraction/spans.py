"""Spans: ``{start, end, quote}`` into a document's text.

Offsets count Unicode code points and ``end`` is exclusive: plain ``str`` indexing.
"""

from typing import Any

from apps.core.errors import ApiError

Span = dict[str, Any]


def _invalid(message: str) -> ApiError:
    return ApiError("invalid_span", message)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def check_span(text: str, span: Any) -> Span:
    """The span, if ``text[start:end] == quote`` and the offsets are in range.

    Otherwise 422 ``invalid_span``.
    """
    if not isinstance(span, dict):
        raise _invalid("A span is { start, end, quote }.")
    start: Any = span.get("start")
    end: Any = span.get("end")
    quote: Any = span.get("quote")
    if not (_is_int(start) and _is_int(end) and isinstance(quote, str)):
        raise _invalid("A span is { start, end, quote }.")
    if not 0 <= start <= end <= len(text):
        raise _invalid("The span's offsets are out of range.")
    if text[start:end] != quote:
        raise _invalid("The span's quote is not the text at its offsets.")
    return {"start": start, "end": end, "quote": quote}


def anchor(text: str, quote: str) -> Span | None:
    """The first exact occurrence of ``quote`` in ``text`` as a span, or None."""
    if not quote:
        return None
    start = text.find(quote)
    if start < 0:
        return None
    return {"start": start, "end": start + len(quote), "quote": quote}


def resolve_span(text: str, span: Any) -> tuple[Span, bool]:
    """A span from the model, made to fit: ``(span, anchored)``.

    A span that fits is kept. One whose offsets do not fit is searched for by its
    quote. A quote that is not in the text is kept as returned with ``anchored``
    false, never dropped.
    """
    try:
        return check_span(text, span), True
    except ApiError:
        quote = span.get("quote") if isinstance(span, dict) else None
        if not isinstance(quote, str):
            raise
        found = anchor(text, quote)
        if found is not None:
            return found, True
        start, end = span.get("start"), span.get("end")
        return (
            {
                "start": start if _is_int(start) else 0,
                "end": end if _is_int(end) else 0,
                "quote": quote,
            },
            False,
        )
