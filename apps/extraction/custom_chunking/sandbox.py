"""Run splitting code on a text in a local sandbox: deterministic, no model.

Each call makes a fresh session of the Agents SDK's ``UnixLocalSandboxClient`` holding
``splitter.py`` (the code), ``text.txt`` and a small trusted runner. The runner imports
``split``, calls it, and writes the ranges to ``ranges.json``; what the code prints goes
nowhere. The ranges are parsed strictly and checked with the rule of the built-in
strategies (``verify_ranges``).

PROTOTYPE, NO ISOLATION: on Linux the local client confines nothing, so the code runs as
the server's own user. The runner only sets a few resource limits and the call has a
time limit; neither is a security boundary. That is why ``CUSTOM_CHUNKING`` is off by
default and refused in production (docs/security.md).
"""

import json
import sys
from pathlib import Path
from typing import Any

import structlog
from agents.sandbox import Manifest
from agents.sandbox.entries import File
from agents.sandbox.errors import ExecTimeoutError
from agents.sandbox.sandboxes.unix_local import UnixLocalSandboxClient
from django.conf import settings

from apps.extraction.custom_chunking.errors import SplitterFailed, SplitterTimedOut
from apps.extraction.extractors.chunks import verify_ranges

log = structlog.get_logger(__name__)

# Most bytes of ranges.json read back: a range is two numbers, so this allows a part of
# one character everywhere; anything longer is not a valid split.
BYTES_PER_RANGE = 48
MAX_RESULT_BYTES = 32_000_000

# The runner is trusted code. It reads the text without translating line ends, closes
# stdout and stderr (the splitting code can print as much as it likes), limits memory
# and file size, and writes a result only when the code returned.
RUNNER = """\
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.append(HERE)  # after the standard library, which the code cannot shadow

try:
    import resource
    resource.setrlimit(resource.RLIMIT_AS, (2 << 30, 2 << 30))
    resource.setrlimit(resource.RLIMIT_FSIZE, (64 << 20, 64 << 20))
except Exception:
    pass

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

    Raises ``SplitterTimedOut`` when it runs longer than
    ``CUSTOM_CHUNKING_RUN_TIMEOUT_SECONDS``, ``SplitterFailed`` for any other problem
    (it raised, exited non-zero, wrote nothing usable, returned ranges that are not a
    valid split) and ``UnicodeEncodeError`` for a text that cannot be written as UTF-8.
    """
    manifest = Manifest(
        entries={
            "splitter.py": File(content=code.encode("utf-8")),
            "text.txt": File(content=text.encode("utf-8")),
            "run_split.py": File(content=RUNNER.encode()),
        }
    )
    client = UnixLocalSandboxClient(inherit_host_environment=False)
    session = None
    try:
        session = await client.create(manifest=manifest)
        async with session:
            limit = min(len(text) * BYTES_PER_RANGE + 1024, MAX_RESULT_BYTES)
            try:
                # -I: isolated mode, no PYTHON* variables, no user site, and no
                # script directory on sys.path (the runner adds it, last).
                result = await session.exec(
                    sys.executable,
                    "-I",
                    "run_split.py",
                    str(size),
                    timeout=settings.CUSTOM_CHUNKING_RUN_TIMEOUT_SECONDS,
                    shell=False,
                )
            except ExecTimeoutError:
                raise SplitterTimedOut from None
            if result.exit_code != 0:
                raise SplitterFailed(f"the code exited with {result.exit_code}")
            raw = await session.read_bounded(Path("ranges.json"), max_bytes=limit + 1)
            if len(raw) > limit:
                raise SplitterFailed("the ranges are too large")
    except SplitterFailed, SplitterTimedOut, UnicodeEncodeError:
        raise
    except Exception as error:
        raise SplitterFailed(type(error).__name__) from None
    finally:
        if session is not None:
            try:
                await client.delete(session)
            except Exception as error:
                log.warning(
                    "custom_chunking_cleanup_failed", error=type(error).__name__
                )
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
