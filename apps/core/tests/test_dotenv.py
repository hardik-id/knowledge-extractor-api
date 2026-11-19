"""Only a local run reads .env; the test and production settings never do."""

import subprocess
import sys
from pathlib import Path

from apps.core.tests.process import process_env

ROOT = Path(__file__).resolve().parents[3]
DOTENV = "OTEL_SDK_DISABLED=false\nAUTH_MODE=dev\nLOG_FORMAT=json\nLOG_LEVEL=ERROR\n"
PROBE = (
    "from django.conf import settings as s; "
    "print(s.OTEL_SDK_DISABLED, s.AUTH_MODE, s.LOG_FORMAT)"
)


def settings_in(module: str, directory: Path) -> str:
    """What `module` holds when `directory` has a .env, read in a fresh process."""
    (directory / ".env").write_text(DOTENV)
    env = process_env(
        DJANGO_SETTINGS_MODULE=module,
        ENV_FILE=str(directory / ".env"),
        DJANGO_SECRET_KEY="x" * 50,
        DJANGO_ALLOWED_HOSTS="example.com",
        DATABASE_URL="postgres://u:p@localhost/db",
    )
    result = subprocess.run(  # noqa: S603 - our own interpreter
        [sys.executable, "-c", f"import django; django.setup(); {PROBE}"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip().splitlines()[-1]


def test_the_test_settings_ignore_a_dotenv(tmp_path: Path) -> None:
    assert settings_in("config.settings.test", tmp_path) == "True dev console"


def test_the_production_settings_ignore_a_dotenv(tmp_path: Path) -> None:
    # AUTH_MODE=dev in the file would make production refuse to start
    assert settings_in("config.settings.production", tmp_path) == "True entra console"


def test_the_local_settings_read_a_dotenv(tmp_path: Path) -> None:
    assert settings_in("config.settings.local", tmp_path) == "False dev json"
