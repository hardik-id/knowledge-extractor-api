"""``run_splitter`` runs real subprocesses through the SDK's local sandbox."""

import asyncio
from typing import Any

import pytest

from apps.extraction.custom_chunking.errors import SplitterFailed, SplitterTimedOut
from apps.extraction.custom_chunking.sandbox import run_splitter
from apps.extraction.tests import custom_code as code


def run(source: str, text: str = code.DOCUMENT, size: int = 1000) -> Any:
    return asyncio.run(run_splitter(source, text, size))


def test_a_good_splitter_returns_the_ranges() -> None:
    spans = run(code.SECTIONS)
    assert spans[0] == (0, code.DOCUMENT.index("## Decision 1"))
    assert [code.DOCUMENT[s:e][:11] for s, e in spans[1:]] == [
        f"## Decision {i}"[:11] for i in range(1, 6)
    ]
    assert spans[-1][1] == len(code.DOCUMENT)


def test_a_part_longer_than_the_size_is_cut_by_the_code() -> None:
    spans = run(code.SECTIONS, size=20)
    assert all(e - s <= 20 for s, e in spans)


def test_an_empty_text_has_no_parts() -> None:
    assert run(code.SECTIONS, text="") == []


def test_line_ends_are_not_translated() -> None:
    text = "## a\r\nline\r\n## b\r\nline\r\n"
    assert run(code.SECTIONS, text=text) == [(0, 12), (12, len(text))]


@pytest.mark.parametrize(
    "source",
    [code.WRONG_RANGE, code.RAISES, code.NOT_RANGES, code.NO_SPLIT, ""],
)
def test_a_splitter_that_does_not_work_fails(source: str) -> None:
    with pytest.raises(SplitterFailed):
        run(source)


def test_a_range_that_is_not_a_valid_split_fails() -> None:
    gap = "def split(text, size):\n    return [(0, 5), (6, len(text))]\n"
    with pytest.raises(SplitterFailed):
        run(gap, size=10_000)


def test_a_splitter_that_never_returns_times_out(settings: Any) -> None:
    settings.CUSTOM_CHUNKING_RUN_TIMEOUT_SECONDS = 1
    with pytest.raises(SplitterTimedOut):
        run(code.FOREVER)


def test_a_splitter_that_prints_a_lot_is_harmless() -> None:
    spans = run(code.LOUD, size=500)
    assert spans[-1][1] == len(code.DOCUMENT)


def test_too_many_ranges_fail() -> None:
    many = "def split(text, size):\n    return [(0, 1)] * (len(text) + 1)\n"
    with pytest.raises(SplitterFailed):
        run(many)


def test_a_text_that_cannot_be_written_raises_unicode_error() -> None:
    with pytest.raises(UnicodeEncodeError):
        run(code.SECTIONS, text="a\ud800b")


def test_production_refuses_local_custom_chunking() -> None:
    from apps.identity.tests.test_dev_sign_in import import_production

    result = import_production(CUSTOM_CHUNKING="local")
    assert result.returncode != 0
    assert "prototype without isolation" in result.stderr
    assert import_production(CUSTOM_CHUNKING="off").returncode == 0


def test_an_unknown_setting_value_is_refused() -> None:
    from apps.identity.tests.test_dev_sign_in import import_production

    assert import_production(CUSTOM_CHUNKING="remote").returncode != 0
