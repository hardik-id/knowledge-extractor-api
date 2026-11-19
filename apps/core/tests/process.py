"""The environment of a process a test starts: its own, never the runner's."""

import os

KEPT = ("PATH", "HOME", "SYSTEMROOT", "LANG", "LC_ALL")


def process_env(**extra: str) -> dict[str, str]:
    """A small environment plus `extra`, with no .env file (ENV_FILE is empty)."""
    env = {name: os.environ[name] for name in KEPT if name in os.environ}
    return {**env, "ENV_FILE": "", **extra}
