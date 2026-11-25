"""Run splitting code on a text: deterministic, no model.

Each call makes a fresh temporary workspace holding ``splitter.py`` (the code),
``text.txt`` and a small trusted runner, and runs the runner with ``process.run_confined``
(own process group killed at the end or on cancel, CPU, memory and file limits, the
time limit, no network where ``unshare`` works). The runner imports ``split``, calls it
and writes the ranges to ``ranges.json``; what the code prints goes nowhere. The ranges
are parsed strictly and checked with the rule of the built-in strategies
(``verify_ranges``).

PROTOTYPE, NO ISOLATION: the code runs as the server's own user and can read whatever
that user can. The limits are not a security boundary. That is why ``CUSTOM_CHUNKING`` is
off by default, needs ``AUTH_MODE=dev`` and is refused in production (docs/security.md).
"""

import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from django.conf import settings

from apps.extraction.custom_chunking.errors import SplitterFailed, SplitterTimedOut
from apps.extraction.custom_chunking.process import run_confined
from apps.extraction.extractors.chunks import verify_ranges

# Most bytes of ranges.json read back: a range is two numbers, so this allows a part of
# one character everywhere; anything longer is not a valid split.
BYTES_PER_RANGE = 48
MAX_RESULT_BYTES = 32_000_000

# The runner is trusted code. It reads the text without translating line ends, closes
# stdout and stderr (the splitting code can print as much as it likes), and writes a
# result only when the code returned.
RUNNER = """\
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.append(HERE)  # after the standard library, which the code cannot shadow

size = int(sys.argv[1])
with open(os.path.join(HERE, "text.txt"), encoding="utf-8", newline="") as f:
    text = f.read()
quiet = os.open(os.devnull, os.O_RDWR)
os.dup2(quiet, 1)
os.dup2(quiet, 2)
sys.stdout = sys.stderr = open(os.devnull, "w")

from splitter import split

spans = split(text, size)
if not isinstance(spans, (list, tuple)) or len(spans) > len(text):
    sys.exit(3)
with open(os.path.join(HERE, "ranges.json"), "w") as f:
    json.dump([list(s) for s in spans], f)
"""


async def run_splitter(code: str, text: str, size: int) -> list[tuple[int, int]]:
    """The ``(start, end)`` parts that ``code``'s ``split(text, size)`` returns.

    An empty text has no parts and starts nothing. Raises ``SplitterTimedOut`` when it
    runs longer than ``CUSTOM_CHUNKING_RUN_TIMEOUT_SECONDS``, ``SplitterFailed`` for any
    other problem (it raised, exited non-zero, wrote nothing usable, returned ranges
    that are not a valid split) and ``UnicodeEncodeError`` for a text or code that
    cannot be written as UTF-8.
    """
    if not text:
        return []
    source = code.encode("utf-8")
    body = text.encode("utf-8")
    workspace = Path(tempfile.mkdtemp(prefix="custom-chunking-"))
    try:
        (workspace / "splitter.py").write_bytes(source)
        (workspace / "text.txt").write_bytes(body)
        (workspace / "run_split.py").write_text(RUNNER, encoding="utf-8")
        outcome = await run_confined(
            [sys.executable, "-I", "run_split.py", str(size)],
            cwd=workspace,
            timeout=settings.CUSTOM_CHUNKING_RUN_TIMEOUT_SECONDS,
            max_output=0,
        )
        if outcome.timed_out:
            raise SplitterTimedOut
        if outcome.exit_code != 0:
            raise SplitterFailed(f"the code exited with {outcome.exit_code}")
        limit = min(len(text) * BYTES_PER_RANGE + 1024, MAX_RESULT_BYTES)
        result = workspace / "ranges.json"
        try:
            if result.stat().st_size > limit:
                raise SplitterFailed("the ranges are too large")
            raw = result.read_bytes()
        except OSError:
            raise SplitterFailed("the code returned no ranges") from None
    finally:
        shutil.rmtree(workspace, ignore_errors=True)
    spans = _parse(raw)
    try:
        verify_ranges(text, spans, size)
    except RuntimeError as error:
        raise SplitterFailed(str(error)) from None
    return spans


def _parse(raw: bytes) -> list[tuple[int, int]]:
    """``[[start, end], ...]`` of whole numbers, nothing else."""
    try:
        data: Any = json.loads(raw)
    except ValueError:
        raise SplitterFailed("the ranges are not JSON") from None
    spans: list[tuple[int, int]] = []
    if not isinstance(data, list):
        raise SplitterFailed("the ranges are not a list")
    for item in data:
        if (
            not isinstance(item, list)
            or len(item) != 2
            or any(type(n) is not int for n in item)
        ):
            raise SplitterFailed("a range is not a pair of whole numbers")
        spans.append((item[0], item[1]))
    return spans
