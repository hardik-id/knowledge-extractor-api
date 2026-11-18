"""Fixtures that sign tokens with a local key.

The real validator and the real authentication class run. Only the source of
the signing keys is local, as Entra ID's is on the network.
"""

import time
import uuid
from collections.abc import Callable
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, RSAPublicKey

from apps.identity import tokens
from apps.identity.tokens import TokenConfig, entra_config

TENANT = "11111111-1111-1111-1111-111111111111"
CLIENT_ID = "33333333-3333-3333-3333-333333333333"
SCOPE = "access_as_user"
KID = "test-key"


class LocalKeys:
    """A key source that knows one public key, or none can be fetched."""

    def __init__(self, key: RSAPrivateKey) -> None:
        self.public_key = key.public_key()
        self.broken = False

    def get_key(self, kid: str) -> RSAPublicKey | None:
        if self.broken:
            raise OSError("connection refused")
        return self.public_key if kid == KID else None


@pytest.fixture(scope="session")
def signing_key() -> RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def key_source(signing_key: RSAPrivateKey) -> LocalKeys:
    return LocalKeys(signing_key)


@pytest.fixture
def token_config(monkeypatch: pytest.MonkeyPatch, key_source: LocalKeys) -> TokenConfig:
    config = entra_config(
        tenant_id=TENANT,
        client_id=CLIENT_ID,
        required_scope=SCOPE,
        key_source=key_source,
    )
    monkeypatch.setattr(tokens, "default_config", lambda: config)
    return config


MakeToken = Callable[..., str]


@pytest.fixture
def make_token(signing_key: RSAPrivateKey) -> MakeToken:
    """``make_token(name="Ada")`` signs a valid token; a keyword overrides a
    claim, and ``None`` removes it."""

    def make(**overrides: Any) -> str:
        now = int(time.time())
        payload: dict[str, Any] = {
            "iss": f"https://login.microsoftonline.com/{TENANT}/v2.0",
            "aud": CLIENT_ID,
            "tid": TENANT,
            "oid": str(uuid.uuid4()),
            "name": "Ada Lovelace",
            "preferred_username": "ada@example.com",
            "scp": SCOPE,
            "iat": now,
            "nbf": now,
            "exp": now + 3600,
        }
        payload.update(overrides)
        payload = {key: value for key, value in payload.items() if value is not None}
        return jwt.encode(payload, signing_key, algorithm="RS256", headers={"kid": KID})

    return make
