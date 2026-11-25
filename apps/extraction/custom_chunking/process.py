"""Run one command of the custom chunking prototype with limits, and always clean up.

Used for the saved splitting code and for the commands of the writing agent. It
replaces the SDK's local exec, which does not kill the child when its caller is
cancelled, keeps all output in memory and lets a command run on in the background.

Each command: its own session and process group, killed as a group when it ends, times
out or the caller is cancelled; ``RLIMIT_CPU`` (so a spinning process dies even if
this server cannot reach it), ``RLIMIT_AS`` and ``RLIMIT_FSIZE``; no stdin; output read
only up to a cap (the rest is drained and dropped); and, where the machine allows it,
no network (``unshare -rn``, probed once).

NO ISOLATION beyond that: the command still runs as the server's user and reads
whatever that user can (docs/security.md).
"""

import asyncio
import functools
import os
import resource
import shutil
import signal
import subprocess
from pathlib import Path

import pydantic
import structlog

log = structlog.get_logger(__name__)

CPU_MARGIN_SECONDS = 2
MEMORY_BYTES = 2 << 30
FILE_BYTES = 64 << 20


class Outcome(pydantic.BaseModel):
    exit_code: int | None
    output: bytes
    truncated: bool
    timed_out: bool


@functools.cache
def network_prefix() -> tuple[str, ...]:
    """``unshare -rn`` when this process may make a network namespace, else nothing.

    Probed once. Without it (a default Docker container, macOS) commands keep the
    server's network, and one warning says so.
    """
    unshare = shutil.which("unshare")
    if unshare:
        try:
            probe = subprocess.run(  # noqa: S603
                [unshare, "-rn", "true"], capture_output=True, timeout=10, check=False
            )
            if probe.returncode == 0:
                return (unshare, "-rn")
        except OSError, subprocess.SubprocessError:
            pass
    log.warning(
        "custom_chunking_network_open",
        detail="custom chunking code runs with network access: no network "
        "namespace is available here",
    )
    return ()


def _limits(cpu_seconds: int) -> None:
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 1))
    for kind, value in (
        (resource.RLIMIT_AS, MEMORY_BYTES),
        (resource.RLIMIT_FSIZE, FILE_BYTES),
    ):
        try:
            resource.setrlimit(kind, (value, value))
        except ValueError, OSError:
            pass


async def run_confined(
    argv: list[str],
    *,
    cwd: Path,
    timeout: float,
    max_output: int,
    env: dict[str, str] | None = None,
) -> Outcome:
    """Run ``argv`` in ``cwd``; never raises for the command's own failure.

    ``timed_out`` is set when the time ran out or the CPU limit killed it.
    """
    cpu = int(timeout) + CPU_MARGIN_SECONDS
    process = await asyncio.create_subprocess_exec(  # noqa: S603
        *network_prefix(),
        *argv,
        cwd=cwd,
        env=env or {},
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        start_new_session=True,
        preexec_fn=lambda: _limits(cpu),  # noqa: PLW1509
    )
    captured = bytearray()
    state = {"truncated": False}

    async def read() -> None:
        stream = process.stdout
        while stream is not None and (chunk := await stream.read(65536)):
            room = max_output - len(captured)
            if room > 0:
                captured.extend(chunk[:room])
            if len(chunk) > room:
                state["truncated"] = True

    timed_out = False
    reader = asyncio.ensure_future(read())
    try:
        try:
            await asyncio.wait_for(process.wait(), timeout)
        except TimeoutError:
            timed_out = True
    finally:
        # The command is over (or out of time, or the caller was cancelled): nothing it
        # started may go on, and what it still holds on the pipe is dropped.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            pass
        try:
            await asyncio.wait_for(asyncio.shield(process.wait()), 5)
            await asyncio.wait_for(reader, 5)
        except TimeoutError, asyncio.CancelledError:
            reader.cancel()
            raise
        finally:
            reader.cancel()
    code = process.returncode
    if code == -signal.SIGXCPU:
        timed_out = True
    return Outcome(
        exit_code=None if timed_out else code,
        output=bytes(captured),
        truncated=state["truncated"],
        timed_out=timed_out,
    )
