"""Cutting a long document into parts for the model extractor (docs/extraction.md).

Pure: no model, no database. The parts cover the text exactly, in order, without
overlap, each at most ``limit`` characters.
"""

import re

_HEADING = re.compile(r"^(#+)", re.MULTILINE)
_BLANK_LINE = re.compile(r"\n[ \t]*\n")


def split(text: str, limit: int) -> list[tuple[int, int]]:
    """The ``(start, end)`` offsets of the parts of ``text`` (``end`` exclusive)."""
    if limit < 1:
        raise ValueError("limit must be at least 1")
    parts: list[tuple[int, int]] = []
    start = 0
    while len(text) - start > limit:
        end = _cut(text, start, limit)
        parts.append((start, end))
        start = end
    if start < len(text):
        parts.append((start, len(text)))
    return parts


def _cut(text: str, start: int, limit: int) -> int:
    """Where the part that begins at ``start`` ends: the best boundary within ``limit``."""
    stop = start + limit
    # A heading line starts the next part; the highest level (fewest #) first.
    headings = [
        m
        for m in _HEADING.finditer(text, start, stop + 1)
        if m.start() > start and m.start() <= stop
    ]
    if headings:
        level = min(len(m.group(1)) for m in headings)
        return [m.start() for m in headings if len(m.group(1)) == level][-1]
    blank = [m.end() for m in _BLANK_LINE.finditer(text, start, stop)]
    if blank and blank[-1] > start:
        return blank[-1]
    for mark in ("\n", " "):
        cut = text.rfind(mark, start, stop) + 1
        if cut > start:
            return cut
    return stop
