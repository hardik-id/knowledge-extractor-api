"""What can go wrong with splitting code. None of them carries the code or the text."""


class SplitterFailed(Exception):
    """The code did not run, raised, printed nothing usable or returned bad ranges."""


class SplitterTimedOut(Exception):
    """The code ran longer than ``CUSTOM_CHUNKING_RUN_TIMEOUT_SECONDS``."""
