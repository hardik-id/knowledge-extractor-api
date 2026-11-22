"""The splitter: pure, no database."""

import pytest

from apps.extraction.extractors.chunks import split


def parts(text: str, limit: int) -> list[str]:
    return [text[a:b] for a, b in split(text, limit)]


def check_cover(text: str, limit: int) -> list[tuple[int, int]]:
    spans = split(text, limit)
    assert "".join(text[a:b] for a, b in spans) == text
    pos = 0
    for a, b in spans:
        assert a == pos and a < b and b - a <= limit
        pos = b
    assert pos == len(text)
    return spans


@pytest.mark.parametrize("limit", [1, 3, 7, 20, 50, 500])
def test_the_parts_cover_the_text_exactly_within_the_limit(limit: int) -> None:
    text = "# A\nsome words here\n\n## B\nmore text, and more\n\nlast line\nx" * 4
    check_cover(text, limit)


def test_a_short_text_is_one_part_and_an_empty_one_has_none() -> None:
    assert split("abc", 3) == [(0, 3)]
    assert split("", 10) == []


def test_a_heading_beats_a_blank_line_and_the_highest_level_wins() -> None:
    text = "intro\n\ntext\n## sub\nmore\n# top\nrest of it\n\nend"
    assert parts(text, len(text) - 4)[0] == "intro\n\ntext\n## sub\nmore\n"
    # no top heading in reach: the level-2 heading
    assert parts(text, 21)[0] == "intro\n\ntext\n"[:0] + text[: text.index("## sub")]


def test_a_blank_line_beats_a_line_end() -> None:
    text = "aaa\nbbb\n\nccc\nddd eee"
    assert parts(text, 15)[0] == "aaa\nbbb\n\n"


def test_a_line_end_beats_a_space() -> None:
    text = "aaa bbb\nccc ddd eee"
    assert parts(text, 12)[0] == "aaa bbb\n"


def test_a_space_when_there_is_no_line_end() -> None:
    assert parts("aaa bbb ccc ddd", 10)[0] == "aaa bbb "


def test_a_hard_cut_when_a_run_has_no_boundary() -> None:
    text = "x" * 25
    assert [b - a for a, b in check_cover(text, 10)] == [10, 10, 5]


def test_a_heading_exactly_at_the_limit_starts_the_next_part() -> None:
    assert parts("abcd\n# H\nxy", 5)[0] == "abcd\n"


def test_a_hash_inside_a_line_is_not_a_heading() -> None:
    assert parts("a # b\nc # d\nef", 8)[0] == "a # b\n"


def test_a_heading_at_the_start_of_the_part_is_not_a_cut() -> None:
    check_cover("# H\n" + "word " * 10, 12)  # no empty part, no endless loop
    assert parts("# H\nabcdefghij", 8)[0] == "# H\n"


def test_a_title_near_the_top_does_not_make_a_tiny_part() -> None:
    body = "".join(f"## Section {n}\n{'words ' * 30}\n" for n in range(8))
    text = "front matter\n# Title\n" + body
    first = parts(text, 600)[0]
    # The level-1 title is in the first half of the part: a later section heading
    # is the cut, and the title stays inside the first part.
    assert "# Title" in first and len(first) > 300
    assert parts(text, 600)[1].startswith("## Section")
    check_cover(text, 600)


def test_a_heading_in_the_first_half_is_still_used_when_there_is_no_other() -> None:
    text = "intro\n# Only\n" + "x" * 100
    assert parts(text, 60)[0] == "intro\n"
