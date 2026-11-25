"""Cutting a long document into parts for the model extractor (docs/extraction.md).

Pure: no model, no database. The parts cover the text exactly, in order, without
overlap, each at most ``limit`` characters.
"""

import re
from typing import Literal, get_args

from semantic_text_splitter import MarkdownSplitter, TextSplitter

Strategy = Literal["auto", "heading", "paragraph", "fixed"]
STRATEGIES: tuple[str, ...] = get_args(Strategy)

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
    # A heading line starts the next part; the highest level (fewest #) first. One in
    # the second half of the window is preferred, so a title near the top of a
    # document does not make a tiny part.
    headings = [
        m
        for m in _HEADING.finditer(text, start, stop + 1)
        if m.start() > start and m.start() <= stop
    ]
    headings = [m for m in headings if m.start() > start + limit // 2] or headings
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


def split_by(text: str, strategy: Strategy, size: int) -> list[tuple[int, int]]:
    """The ``(start, end)`` character ranges of the parts of ``text`` (``end`` exclusive).

    ``strategy`` is one of ``auto`` (``split``, unchanged), ``heading``
    (``MarkdownSplitter``), ``paragraph`` (``TextSplitter``) or ``fixed`` (windows of
    ``size`` characters cut at the last whitespace of the window when it lies in the
    window's second half, else a hard cut). Whatever the strategy, the ranges are in
    order, not empty, without gaps or overlap, cover the text exactly, and none is
    longer than ``size``. An empty text has no parts; a text of at most ``size``
    characters is one part; a word longer than ``size`` is cut inside the word.
    Raises ``ValueError`` for an unknown strategy or a ``size`` below 1, and
    ``RuntimeError`` if the library returns an offset that does not match its chunk.
    """
    if size < 1:
        raise ValueError("size must be at least 1")
    if strategy == "auto":
        return split(text, size)
    if strategy == "fixed":
        spans = _fixed(text, size)
    elif strategy == "heading":
        spans = _library(text, MarkdownSplitter(size, trim=False))
    elif strategy == "paragraph":
        spans = _library(text, TextSplitter(size, trim=False))
    else:
        raise ValueError(f"unknown chunking strategy: {strategy!r}")
    verify_ranges(text, spans, size)
    return spans


def _library(
    text: str, splitter: MarkdownSplitter | TextSplitter
) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for offset, chunk in splitter.chunk_indices(text):
        # Quotes are located by these positions: never trust them blindly.
        if text[offset : offset + len(chunk)] != chunk:
            raise RuntimeError(
                f"semantic-text-splitter returned a chunk that is not at offset {offset}"
            )
        spans.append((offset, offset + len(chunk)))
    return spans


def _fixed(text: str, size: int) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    start = 0
    while start < len(text):
        stop = start + size
        if stop >= len(text):
            end = len(text)
        else:
            cut = max(text.rfind(" ", start, stop), text.rfind("\n", start, stop))
            cut = max(cut, text.rfind("\t", start, stop), text.rfind("\r", start, stop))
            cut += 1  # the whitespace stays at the end of the part
            end = cut if cut > start + size // 2 else stop
        spans.append((start, end))
        start = end
    return spans


def verify_ranges(text: str, spans: list[tuple[int, int]], size: int) -> None:
    """Raise ``RuntimeError`` unless ``spans`` are a valid split of ``text`` at ``size``.

    In order from 0, no gap, no overlap, none empty, none longer than ``size``, ending
    at ``len(text)``. Also the check of splitting code a model wrote.
    """
    position = 0
    for start, end in spans:
        if start != position or end <= start or end - start > size:
            raise RuntimeError(f"invalid chunk range ({start}, {end}) at {position}")
        position = end
    if position != len(text):
        raise RuntimeError("the chunks do not cover the text")
