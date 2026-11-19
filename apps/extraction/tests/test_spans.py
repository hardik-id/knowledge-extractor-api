import pytest

from apps.core.errors import ApiError
from apps.extraction.spans import anchor, check_span, resolve_span

TEXT = "😀 café note: Accepted"  # the emoji is one code point
QUOTE = "Accepted"
START = TEXT.index(QUOTE)


def span(start: int, end: int, quote: str) -> dict[str, object]:
    return {"start": start, "end": end, "quote": quote}


def test_offsets_count_code_points_after_an_emoji() -> None:
    assert START == len("😀 café note: ")
    assert len(TEXT.encode("utf-16-le")) // 2 > len(TEXT)  # UTF-16 would count more
    ok = check_span(TEXT, span(START, START + len(QUOTE), QUOTE))
    assert TEXT[ok["start"] : ok["end"]] == QUOTE


@pytest.mark.parametrize(
    "bad",
    [
        span(START + 1, START + 1 + len(QUOTE), QUOTE),  # the quote is elsewhere
        span(-1, 3, TEXT[:3]),
        span(START, len(TEXT) + 5, QUOTE),
        span(5, 2, ""),
        span(0, 1, "x"),
        {"start": "0", "end": 1, "quote": "😀"},
        {"start": True, "end": 1, "quote": "😀"},
        {"start": 0, "end": 1},
        "😀",
        None,
    ],
)
def test_invalid_spans(bad: object) -> None:
    with pytest.raises(ApiError) as error:
        check_span(TEXT, bad)
    assert error.value.code == "invalid_span"


def test_anchor_finds_a_quote_and_nothing_else() -> None:
    assert anchor(TEXT, QUOTE) == span(START, START + len(QUOTE), QUOTE)
    assert anchor(TEXT, "invented") is None
    assert anchor(TEXT, "") is None


def test_resolve_keeps_a_fitting_span() -> None:
    fits = span(START, START + len(QUOTE), QUOTE)
    assert resolve_span(TEXT, fits) == (fits, True)


def test_resolve_anchors_a_misplaced_span() -> None:
    assert resolve_span(TEXT, span(0, 8, QUOTE)) == (
        span(START, START + len(QUOTE), QUOTE),
        True,
    )


def test_resolve_keeps_a_quote_that_is_not_in_the_text() -> None:
    made_up = span(3, 11, "invented")
    assert resolve_span(TEXT, made_up) == (made_up, False)
