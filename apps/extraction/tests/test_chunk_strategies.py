"""The chunking strategies as properties over awkward documents: pure, no database."""

from typing import get_args

import pytest

from apps.extraction.extractors import chunks
from apps.extraction.extractors.chunks import Strategy, split_by

_PARA = "Alpha beta gamma delta. " * 12
DOCUMENTS = {
    "empty": "",
    "short": "just a few words",
    "non_ascii": "Zażółć gęślą jaźń. Привет, мир! 你好,世界。 Ünïcödé café. " * 60,
    "emoji": "Launch 🚀 day 👩‍👩‍👧 went well 😀.\n\nNext 🎉 steps 🧪 follow. " * 60,
    "crlf": "# Title\r\n\r\nFirst paragraph.\r\nSecond line.\r\n\r\n## Part\r\n\r\nText.\r\n"
    * 60,
    "trailing_spaces": "Line with trailing spaces   \n\n  \nAnother   \n\n" * 80,
    "repeated": (_PARA + "\n\n") * 40,
    "code_fence": "# Real\n\ntext\n\n```bash\n# not a heading\n# neither\necho hi\n```\n\n"
    * 50,
    "front_matter": "---\ntitle: Doc\ntags: [a, b]\n---\n\n# H1\n\n" + _PARA * 60,
    "headings": "".join(
        f"# Section {i}\n\n{_PARA}\n\n## Sub {i}\n\n{_PARA}\n\n" for i in range(30)
    ),
    "long_word": "before " + "x" * 9000 + " after",
    "only_long_word": "y" * 20000,
    "only_whitespace": " \n\n \r\n \t " * 500,
}
SIZES = [1000, 4000, 8000]
STRATEGIES = list(get_args(Strategy))


@pytest.mark.parametrize("size", SIZES)
@pytest.mark.parametrize("strategy", STRATEGIES)
@pytest.mark.parametrize("name", DOCUMENTS)
def test_the_parts_cover_the_text_within_the_size(
    name: str, strategy: Strategy, size: int
) -> None:
    text = DOCUMENTS[name]
    spans = split_by(text, strategy, size)
    assert "".join(text[a:b] for a, b in spans) == text
    position = 0
    for start, end in spans:
        assert start == position and start < end and end - start <= size
        position = end
    assert position == len(text)
    assert spans == split_by(text, strategy, size)  # deterministic
    if len(text) <= size:
        assert len(spans) == (1 if text else 0)


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_the_smallest_size_still_covers_the_text(strategy: Strategy) -> None:
    text = DOCUMENTS["emoji"][:200]
    spans = split_by(text, strategy, 1)
    assert [text[a:b] for a, b in spans] == list(text)


def test_auto_is_the_existing_splitter() -> None:
    for text in DOCUMENTS.values():
        assert split_by(text, "auto", 1000) == chunks.split(text, 1000)


def test_fixed_cuts_at_the_last_whitespace_of_the_second_half_else_hard() -> None:
    assert split_by("aaaa bbbb cccc", "fixed", 10) == [(0, 10), (10, 14)]
    assert split_by("aaaa bbb cccccc", "fixed", 10) == [(0, 9), (9, 15)]
    assert split_by("ab cdefghijklmn", "fixed", 10) == [
        (0, 10),
        (10, 15),
    ]  # space in 1st half
    assert split_by("x" * 25, "fixed", 10) == [(0, 10), (10, 20), (20, 25)]


def test_a_word_longer_than_the_size_is_cut_inside_the_word() -> None:
    for strategy in STRATEGIES:
        spans = split_by("z" * 2500, strategy, 1000)
        assert all(b - a <= 1000 for a, b in spans) and spans[-1][1] == 2500


def test_heading_and_paragraph_prefer_their_boundaries() -> None:
    text = "# One\n\n" + "a " * 300 + "\n\n# Two\n\n" + "b " * 300
    for strategy in ("heading", "paragraph"):
        spans = split_by(text, strategy, 1000)
        assert len(spans) >= 2
        assert text[spans[1][0] :].lstrip().startswith(("#", "b", "a"))
    heading = split_by(text, "heading", 1000)
    assert any(text[a:].startswith("# Two") for a, _ in heading)


@pytest.mark.parametrize("size", [0, -5])
@pytest.mark.parametrize("strategy", STRATEGIES)
def test_a_size_below_one_is_refused(strategy: Strategy, size: int) -> None:
    with pytest.raises(ValueError):
        split_by("text", strategy, size)


def test_an_unknown_strategy_is_refused() -> None:
    with pytest.raises(ValueError, match="unknown chunking strategy"):
        split_by("text", "semantic", 1000)  # type: ignore[arg-type]


@pytest.mark.parametrize("strategy", ["heading", "paragraph"])
def test_an_offset_that_does_not_match_fails_loudly(
    strategy: Strategy, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Lying:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def chunk_indices(self, text: str) -> list[tuple[int, str]]:
            return [(1, text)]

    monkeypatch.setattr(chunks, "MarkdownSplitter", Lying)
    monkeypatch.setattr(chunks, "TextSplitter", Lying)
    with pytest.raises(RuntimeError, match="not at offset"):
        split_by("some text here", strategy, 1000)
