"""Splitting code used by the custom chunking tests."""

SECTIONS = """\
import re


def split(text, size):
    cuts = [0] + [m.start() for m in re.finditer(r"^## ", text, re.M) if m.start() > 0]
    cuts.append(len(text))
    out = []
    for a, b in zip(cuts, cuts[1:]):
        while b - a > size:
            out.append((a, a + size))
            a += size
        if b > a:
            out.append((a, b))
    return out
"""

WRONG_RANGE = "def split(text, size):\n    return [(0, len(text) + 1)]\n"
RAISES = "def split(text, size):\n    raise ValueError('boom')\n"
FOREVER = "def split(text, size):\n    while True:\n        pass\n"
NOT_RANGES = "def split(text, size):\n    return [[True, len(text)]]\n"
LOUD = (
    "def split(text, size):\n"
    "    print('x' * 20_000_000)\n"
    "    return [(i, min(i + size, len(text))) for i in range(0, len(text), size)]\n"
)
NO_SPLIT = "VALUE = 1\n"

DOCUMENT = (
    "# Decisions\n\nIntro.\n\n"
    + "\n\n".join(f"## Decision {i}\n\nStatus: accepted\n" for i in range(1, 6))
    + "\n"
)
