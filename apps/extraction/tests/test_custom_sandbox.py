"""``run_splitter`` runs real subprocesses through the SDK's local sandbox."""

import asyncio
import sys
from pathlib import Path
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
    both = import_production(CUSTOM_CHUNKING="local", AUTH_MODE="dev")
    assert both.returncode != 0


def test_local_custom_chunking_needs_the_dev_sign_in() -> None:
    from apps.identity.tests.test_dev_sign_in import import_production

    refused = import_production(CUSTOM_CHUNKING="local", AUTH_MODE="entra")
    assert "needs AUTH_MODE=dev" in refused.stderr
    assert "single developer machine" in refused.stderr


def test_an_unknown_setting_value_is_refused() -> None:
    from apps.identity.tests.test_dev_sign_in import import_production

    assert import_production(CUSTOM_CHUNKING="remote").returncode != 0


def _processes_running(marker: str) -> list[int]:
    found = []
    for entry in Path("/proc").iterdir():
        if entry.name.isdigit():
            try:
                argv = (entry / "cmdline").read_bytes().split(b"\0")
            except OSError:
                continue
            if any(marker.encode() in part for part in argv):
                found.append(int(entry.name))
    return found


@pytest.mark.skipif(not Path("/proc").exists(), reason="needs /proc")
def test_a_cancelled_run_leaves_no_process_behind() -> None:
    async def scenario() -> None:
        task = asyncio.ensure_future(run_splitter(code.FOREVER, code.DOCUMENT, 1000))
        for _ in range(100):  # until the runner is up
            await asyncio.sleep(0.05)
            if _processes_running("run_split.py"):
                break
        assert _processes_running("run_split.py")
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert _processes_running("run_split.py") == []


def test_a_generate_deadline_kills_the_runaway_too() -> None:
    async def scenario() -> None:
        with pytest.raises(TimeoutError):
            async with asyncio.timeout(1):
                await run_splitter(code.FOREVER, code.DOCUMENT, 1000)

    asyncio.run(scenario())
    assert _processes_running("run_split.py") == []


def test_the_cpu_limit_stops_a_process_the_server_cannot_reach(
    settings: Any,
) -> None:
    from apps.extraction.custom_chunking.process import run_confined

    async def scenario() -> Any:
        return await run_confined(
            [sys.executable, "-c", "while True: pass"],
            cwd=Path("/tmp"),  # noqa: S108
            timeout=0.1,
            max_output=10,
        )

    # wall time first: the group is killed at once; the CPU limit is the backstop
    outcome = asyncio.run(scenario())
    assert outcome.timed_out


NETWORK = """
import socket

def split(text, size):
    try:
        socket.create_connection(("93.184.216.34", 80), timeout=3).close()
    except OSError:
        return [(i, min(i + size, len(text))) for i in range(0, len(text), size)]
    raise AssertionError("connected")
"""


def test_the_splitter_has_no_network_where_unshare_works() -> None:
    from apps.extraction.custom_chunking.process import network_prefix

    if not network_prefix():
        pytest.skip("no network namespace on this machine")
    spans = run(NETWORK, size=500)  # valid ranges: it could not connect
    assert spans[-1][1] == len(code.DOCUMENT)


def test_without_a_network_namespace_commands_still_run_with_one_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import subprocess

    from apps.extraction.custom_chunking import process

    process.network_prefix.cache_clear()
    monkeypatch.setattr(
        "apps.extraction.custom_chunking.process.subprocess.run",
        lambda *a, **k: subprocess.CompletedProcess(a, 1),
    )
    warnings: list[str] = []
    monkeypatch.setattr(
        process.log, "warning", lambda event, **kw: warnings.append(event)
    )
    try:
        assert process.network_prefix() == ()
        assert process.network_prefix() == ()  # cached: one warning
        assert warnings == ["custom_chunking_network_open"]
        assert run(code.SECTIONS)  # it still works
    finally:
        process.network_prefix.cache_clear()
