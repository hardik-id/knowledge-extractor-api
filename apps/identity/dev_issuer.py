"""The local token issuer for ``AUTH_MODE=dev``.

Tokens from here go through the same ``validate_access_token`` as Entra ID's;
only the configuration differs (``dev_config``): another issuer, audience and
tenant, and signing keys that come from a private key on this machine.

The RSA key pair is created on first use and kept in a file outside git (see
``DEV_AUTH_KEY_PATH``), readable by its owner only. It is never printed or
logged. Production settings refuse ``AUTH_MODE=dev``, so none of this runs there.
"""

import os
import tempfile
import time
import uuid
from functools import cache
from pathlib import Path

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, RSAPublicKey
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from apps.identity.tokens import ALGORITHM, TokenConfig

# Plainly not Microsoft's: none of these can be mistaken for an Entra value.
DEV_ISSUER = "urn:knowledge-extractor:dev-issuer"
DEV_AUDIENCE = "knowledge-extractor-api-dev"
DEV_TENANT_ID = "de000000-0000-4000-8000-000000000000"
DEV_KEY_ID = "dev-issuer-1"

# The default person, so repeated tokens are the same user.
DEFAULT_OID = "de000000-0000-4000-8000-000000000001"
DEFAULT_NAME = "Dev User"
DEFAULT_TTL_SECONDS = 3600

KEY_FILE_MODE = 0o600
KEY_DIR_MODE = 0o700


def key_path() -> Path:
    return Path(settings.DEV_AUTH_KEY_PATH)


def load_private_key(path: Path | None = None) -> RSAPrivateKey:
    """Read the dev private key, creating the key pair on first use."""
    path = path or key_path()
    if not path.exists():
        _create_key_file(path)
    if path.stat().st_mode & 0o077:
        raise ImproperlyConfigured(
            f"{path} must be readable by its owner only; run: chmod 600 {path}"
        )
    key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    if not isinstance(key, RSAPrivateKey):
        raise ImproperlyConfigured(f"{path} does not hold an RSA private key")
    return key


def _create_key_file(path: Path) -> None:
    path.parent.mkdir(mode=KEY_DIR_MODE, parents=True, exist_ok=True)
    pem = rsa.generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    # Written whole to a private temporary file, then linked into place: the
    # key never exists with wider permissions, a reader never sees half of it,
    # and of two processes starting at once, one wins and the other reads that.
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".key-")
    try:
        with os.fdopen(descriptor, "wb") as file:
            file.write(pem)
        os.chmod(temporary, KEY_FILE_MODE)
        try:
            os.link(temporary, path)
        except FileExistsError:
            pass
    finally:
        os.unlink(temporary)


class DevKeySource:
    """The key source of the dev issuer: it knows one public key."""

    def __init__(self, public_key: RSAPublicKey) -> None:
        self._public_key = public_key

    def get_key(self, kid: str) -> RSAPublicKey | None:
        return self._public_key if kid == DEV_KEY_ID else None


def dev_config(path: Path | None = None) -> TokenConfig:
    return TokenConfig(
        issuer=DEV_ISSUER,
        tenant_id=DEV_TENANT_ID,
        audience=DEV_AUDIENCE,
        required_scope=settings.ENTRA_REQUIRED_SCOPE,
        key_source=DevKeySource(load_private_key(path).public_key()),
    )


@cache
def default_dev_config() -> TokenConfig:
    return dev_config()


def mint_dev_token(
    *,
    name: str = DEFAULT_NAME,
    oid: str = DEFAULT_OID,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    now: int | None = None,
    path: Path | None = None,
) -> str:
    """Sign an access token with the claims an Entra ID v2 token has."""
    uuid.UUID(oid)  # raises ValueError for anything the API would refuse
    issued_at = int(time.time()) if now is None else now
    payload = {
        "iss": DEV_ISSUER,
        "aud": DEV_AUDIENCE,
        "tid": DEV_TENANT_ID,
        "oid": oid,
        "sub": oid,
        "name": name,
        "preferred_username": _username(name),
        "scp": settings.ENTRA_REQUIRED_SCOPE,
        "iat": issued_at,
        "nbf": issued_at,
        "exp": issued_at + ttl_seconds,
    }
    return jwt.encode(
        payload,
        load_private_key(path),
        algorithm=ALGORITHM,
        headers={"kid": DEV_KEY_ID},
    )


def _username(name: str) -> str:
    local = "".join(c for c in name.lower() if c.isalnum()) or "dev"
    return f"{local}@dev.invalid"
