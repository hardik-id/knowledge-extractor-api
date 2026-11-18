"""The dev issuer, ``mint_dev_token`` and the guards around ``AUTH_MODE=dev``.

Dev tokens go through the real validator, the real authentication class and a
real database. The key lives in a temporary directory.
"""

import os
import shutil
import stat
import subprocess
import sys
import uuid
from collections.abc import Iterator
from io import StringIO
from pathlib import Path
from typing import Any

import jwt
import pytest
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.core.management.base import CommandError
from rest_framework.test import APIClient

from apps.identity import dev_issuer, tokens
from apps.identity.tokens import TokenError, TokenErrorReason, validate_access_token

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def key_file(tmp_path: Path, settings: Any) -> Iterator[Path]:
    path = tmp_path / "keys" / "issuer.pem"
    settings.DEV_AUTH_KEY_PATH = path
    settings.AUTH_MODE = "dev"
    tokens.default_config.cache_clear()
    dev_issuer.default_dev_config.cache_clear()
    yield path
    tokens.default_config.cache_clear()
    dev_issuer.default_dev_config.cache_clear()


def get_me(token: str) -> Any:
    client = APIClient(raise_request_exception=False)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client.get("/api/v1/me")


def mint(*args: str) -> str:
    out = StringIO()
    call_command("mint_dev_token", *args, stdout=out)
    return out.getvalue().strip()


# --- the key ----------------------------------------------------------------


def test_the_key_is_created_on_first_use_for_the_owner_only(key_file: Path) -> None:
    assert not key_file.exists()
    dev_issuer.load_private_key()
    assert stat.S_IMODE(key_file.stat().st_mode) == 0o600
    assert stat.S_IMODE(key_file.parent.stat().st_mode) == 0o700
    assert list(key_file.parent.iterdir()) == [key_file]


def test_the_same_key_is_used_afterwards(key_file: Path) -> None:
    first = dev_issuer.load_private_key().public_key().public_numbers()
    second = dev_issuer.load_private_key().public_key().public_numbers()
    assert first == second


def test_a_key_others_can_read_is_refused(key_file: Path) -> None:
    dev_issuer.load_private_key()
    key_file.chmod(0o644)
    with pytest.raises(ImproperlyConfigured):
        dev_issuer.load_private_key()


def test_the_key_is_never_printed(
    key_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mint()
    seen = capsys.readouterr()
    assert "PRIVATE KEY" not in seen.out + seen.err
    assert "PRIVATE KEY" not in mint()


def test_the_default_key_path_is_ignored_by_git() -> None:
    result = subprocess.run(  # noqa: S603
        [shutil.which("git") or "git", "check-ignore", "-q", ".dev-keys/issuer.pem"],
        cwd=ROOT,
        check=False,
    )
    assert result.returncode == 0


# --- the token --------------------------------------------------------------


@pytest.mark.django_db
def test_a_dev_token_signs_in_with_the_claims_of_an_entra_token(key_file: Path) -> None:
    oid = str(uuid.uuid4())
    token = mint("--name", "Ada Lovelace", "--oid", oid)
    claims = jwt.decode(token, options={"verify_signature": False})
    assert {"oid", "tid", "name", "preferred_username", "scp"} <= set(claims)
    assert claims["iss"] == dev_issuer.DEV_ISSUER
    assert "microsoft" not in claims["iss"] + claims["aud"]

    response = get_me(token)
    assert response.status_code == 200
    assert response.json()["name"] == "Ada Lovelace"
    assert response.json()["preferred_username"] == "adalovelace@dev.invalid"


@pytest.mark.django_db
def test_the_default_person_is_the_same_user_every_time(key_file: Path) -> None:
    first = get_me(mint()).json()["id"]
    assert get_me(mint()).json()["id"] == first


def test_ttl_sets_the_expiry(key_file: Path) -> None:
    claims = jwt.decode(mint("--ttl", "120"), options={"verify_signature": False})
    assert claims["exp"] - claims["iat"] == 120


@pytest.mark.django_db
def test_an_expired_dev_token_is_401(key_file: Path) -> None:
    token = dev_issuer.mint_dev_token(now=1_000_000_000)
    response = get_me(token)
    assert response.status_code == 401
    assert response.json()["code"] == "unauthenticated"
    with pytest.raises(TokenError) as error:
        validate_access_token(token)
    assert error.value.reason is TokenErrorReason.EXPIRED


@pytest.mark.django_db
def test_a_token_signed_by_another_key_is_401(key_file: Path, tmp_path: Path) -> None:
    other = dev_issuer.mint_dev_token(path=tmp_path / "other" / "issuer.pem")
    dev_issuer.load_private_key()  # the key of the running issuer
    assert get_me(other).status_code == 401


@pytest.mark.django_db
def test_a_dev_token_is_refused_with_entra(
    key_file: Path, settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = mint()
    settings.AUTH_MODE = "entra"
    settings.ENTRA_TENANT_ID = str(uuid.uuid4())
    settings.ENTRA_CLIENT_ID = str(uuid.uuid4())
    tokens.default_config.cache_clear()

    class EntraKeys:  # Entra's keys: they do not know the dev key
        def get_key(self, kid: str) -> None:
            return None

    monkeypatch.setattr(tokens, "CachingKeySource", lambda fetch: EntraKeys())
    assert get_me(token).status_code == 401


# --- the command ------------------------------------------------------------


@pytest.mark.parametrize("args", [["--ttl", "0"], ["--ttl", "-5"], ["--oid", "nope"]])
def test_bad_arguments_are_refused(key_file: Path, args: list[str]) -> None:
    with pytest.raises(CommandError):
        mint(*args)
    assert not key_file.exists()


def test_the_command_refuses_to_run_with_entra(key_file: Path, settings: Any) -> None:
    settings.AUTH_MODE = "entra"
    with pytest.raises(CommandError):
        mint()
    assert not key_file.exists()


# --- production -------------------------------------------------------------


def import_production(**env: str) -> subprocess.CompletedProcess[str]:
    clean = {k: v for k, v in os.environ.items() if k not in ("AUTH_MODE",)}
    clean.update(
        DJANGO_SECRET_KEY="x" * 50,
        DJANGO_ALLOWED_HOSTS="example.com",
        DATABASE_URL="postgres://u:p@localhost/db",
        **env,
    )
    return subprocess.run(
        [sys.executable, "-c", "import config.settings.production"],
        cwd=ROOT,
        env=clean,
        capture_output=True,
        text=True,
        check=False,
    )


def test_production_refuses_to_start_with_dev() -> None:
    result = import_production(AUTH_MODE="dev")
    assert result.returncode != 0
    assert "AUTH_MODE=dev is not allowed in production" in result.stderr


@pytest.mark.parametrize("mode", ["entra", ""])
def test_production_starts_with_entra(mode: str) -> None:
    env = {"AUTH_MODE": mode} if mode else {}
    assert import_production(**env).returncode == 0
