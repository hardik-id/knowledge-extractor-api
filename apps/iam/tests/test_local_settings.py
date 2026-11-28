"""On a developer machine in dev mode, the dev issuer's person is a platform admin by default."""

import subprocess
import sys
from pathlib import Path

from apps.core.tests.process import process_env
from apps.identity.dev_issuer import DEFAULT_OID

ROOT = Path(__file__).resolve().parents[3]
PROBE = (
    "import django; django.setup(); from django.conf import settings as s; "
    "print(','.join(sorted(str(o) for o in s.IAM_PLATFORM_ADMIN_OIDS)) or 'nobody')"
)
OTHER = "11111111-1111-4111-8111-111111111111"


def listed(directory: Path, dotenv: str, module: str = "config.settings.local") -> str:
    """Who IAM_PLATFORM_ADMIN_OIDS lists under `module` with this .env, in a fresh process."""
    (directory / ".env").write_text(dotenv)
    env = process_env(
        DJANGO_SETTINGS_MODULE=module,
        ENV_FILE=str(directory / ".env"),
        DJANGO_SECRET_KEY="x" * 50,
        DJANGO_ALLOWED_HOSTS="example.com",
        DATABASE_URL="postgres://u:p@localhost/db",
    )
    result = subprocess.run(  # noqa: S603 - our own interpreter
        [sys.executable, "-c", PROBE],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip().splitlines()[-1]


def test_dev_mode_lists_the_dev_person_when_the_setting_is_not_set(
    tmp_path: Path,
) -> None:
    assert listed(tmp_path, "AUTH_MODE=dev\n") == DEFAULT_OID
    assert listed(tmp_path, "") == DEFAULT_OID  # dev is the local default


def test_a_set_value_wins_and_empty_means_nobody(tmp_path: Path) -> None:
    assert listed(tmp_path, f"IAM_PLATFORM_ADMIN_OIDS={OTHER}\n") == OTHER
    assert listed(tmp_path, "IAM_PLATFORM_ADMIN_OIDS=\n") == "nobody"


def test_entra_mode_and_production_list_nobody_by_default(tmp_path: Path) -> None:
    assert listed(tmp_path, "AUTH_MODE=entra\n") == "nobody"
    assert listed(tmp_path, "", "config.settings.production") == "nobody"
