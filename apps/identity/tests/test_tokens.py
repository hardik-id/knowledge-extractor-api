"""Token validation tests: locally generated RSA keys, a fake key source, no
network and no database."""

import base64
import hashlib
import hmac
import json
import logging
import time
import urllib.request
from collections.abc import Callable, Iterator
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, RSAPublicKey

from apps.identity import tokens
from apps.identity.tokens import (
    CachingKeySource,
    OpenIdKeyFetcher,
    TokenClaims,
    TokenConfig,
    TokenError,
    TokenErrorReason,
    validate_access_token,
)

TENANT = "11111111-1111-1111-1111-111111111111"
OTHER_TENANT = "22222222-2222-2222-2222-222222222222"
CLIENT_ID = "33333333-3333-3333-3333-333333333333"
ISSUER = f"https://login.microsoftonline.com/{TENANT}/v2.0"
SCOPE = "access_as_user"
KID = "key-1"


def make_key() -> RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="module")
def private_key() -> RSAPrivateKey:
    return make_key()


@pytest.fixture(scope="module")
def other_private_key() -> RSAPrivateKey:
    return make_key()


class FakeKeySource:
    def __init__(self, keys: dict[str, RSAPublicKey]) -> None:
        self.keys = keys

    def get_key(self, kid: str) -> RSAPublicKey | None:
        return self.keys.get(kid)


class BrokenKeySource:
    def get_key(self, kid: str) -> RSAPublicKey | None:
        raise OSError("connection refused")


@pytest.fixture
def config(private_key: RSAPrivateKey) -> TokenConfig:
    return TokenConfig(
        issuer=ISSUER,
        tenant_id=TENANT,
        audience=CLIENT_ID,
        required_scope=SCOPE,
        key_source=FakeKeySource({KID: private_key.public_key()}),
    )


def claims(**overrides: Any) -> dict[str, Any]:
    now = int(time.time())
    payload: dict[str, Any] = {
        "iss": ISSUER,
        "aud": CLIENT_ID,
        "tid": TENANT,
        "oid": "oid-1",
        "name": "Ada Lovelace",
        "preferred_username": "ada@example.com",
        "scp": f"{SCOPE} other",
        "iat": now,
        "nbf": now,
        "exp": now + 3600,
    }
    payload.update(overrides)
    return {key: value for key, value in payload.items() if value is not None}


def sign(payload: dict[str, Any], key: RSAPrivateKey, kid: str | None = KID) -> str:
    headers = {"kid": kid} if kid else {}
    return jwt.encode(payload, key, algorithm="RS256", headers=headers)


def refused(token: str, config: TokenConfig) -> TokenErrorReason:
    with pytest.raises(TokenError) as raised:
        validate_access_token(token, config)
    return raised.value.reason


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def test_correct_token_returns_its_claims(
    private_key: RSAPrivateKey, config: TokenConfig
) -> None:
    result = validate_access_token(sign(claims(), private_key), config)

    assert result == TokenClaims(
        oid="oid-1",
        tid=TENANT,
        name="Ada Lovelace",
        preferred_username="ada@example.com",
        scopes=frozenset({SCOPE, "other"}),
    )


def test_name_and_username_are_optional(
    private_key: RSAPrivateKey, config: TokenConfig
) -> None:
    token = sign(claims(name=None, preferred_username=None), private_key)

    result = validate_access_token(token, config)

    assert result.name is None
    assert result.preferred_username is None


def test_audience_list_containing_the_client_is_accepted(
    private_key: RSAPrivateKey, config: TokenConfig
) -> None:
    token = sign(claims(aud=["someone-else", CLIENT_ID]), private_key)

    assert validate_access_token(token, config).oid == "oid-1"


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"exp": int(time.time()) - 3600}, TokenErrorReason.EXPIRED),
        ({"nbf": int(time.time()) + 3600}, TokenErrorReason.EXPIRED),
        (
            {"iss": "https://login.microsoftonline.com/x/v2.0"},
            TokenErrorReason.WRONG_ISSUER,
        ),
        ({"tid": OTHER_TENANT}, TokenErrorReason.WRONG_ISSUER),
        ({"tid": None}, TokenErrorReason.WRONG_ISSUER),
        ({"aud": "another-client"}, TokenErrorReason.WRONG_AUDIENCE),
        ({"scp": None}, TokenErrorReason.MISSING_SCOPE),
        ({"scp": "other access_as_user_not"}, TokenErrorReason.MISSING_SCOPE),
        ({"scp": ["access_as_user"]}, TokenErrorReason.MISSING_SCOPE),
        ({"oid": None}, TokenErrorReason.MALFORMED),
        ({"exp": None}, TokenErrorReason.MALFORMED),
        ({"nbf": None}, TokenErrorReason.MALFORMED),
    ],
)
def test_refuses_bad_claims(
    overrides: dict[str, Any],
    reason: TokenErrorReason,
    private_key: RSAPrivateKey,
    config: TokenConfig,
) -> None:
    assert refused(sign(claims(**overrides), private_key), config) == reason


def test_leeway_tolerates_small_clock_differences(
    private_key: RSAPrivateKey, config: TokenConfig
) -> None:
    now = int(time.time())
    token = sign(claims(exp=now - 10, nbf=now + 10), private_key)

    assert validate_access_token(token, config).oid == "oid-1"


def test_version_1_token_is_refused(
    private_key: RSAPrivateKey, config: TokenConfig
) -> None:
    token = sign(
        claims(iss=f"https://sts.windows.net/{TENANT}/", aud=f"api://{CLIENT_ID}"),
        private_key,
    )

    assert refused(token, config) == TokenErrorReason.WRONG_ISSUER


def test_token_signed_by_another_key_is_refused(
    other_private_key: RSAPrivateKey, config: TokenConfig
) -> None:
    token = sign(claims(), other_private_key)

    assert refused(token, config) == TokenErrorReason.BAD_SIGNATURE


def test_tampered_payload_is_refused(
    private_key: RSAPrivateKey, config: TokenConfig
) -> None:
    header, _, signature = sign(claims(), private_key).split(".")
    forged = b64(json.dumps(claims(oid="someone-else")).encode())

    assert refused(f"{header}.{forged}.{signature}", config) == (
        TokenErrorReason.BAD_SIGNATURE
    )


def test_alg_none_is_refused(config: TokenConfig) -> None:
    token = jwt.encode(
        claims(),
        None,  # type: ignore[arg-type]
        algorithm="none",
        headers={"kid": KID},
    )

    assert refused(token, config) == TokenErrorReason.BAD_SIGNATURE


def test_hs256_with_the_public_key_as_secret_is_refused(
    private_key: RSAPrivateKey, config: TokenConfig
) -> None:
    public_pem = private_key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    header = b64(json.dumps({"alg": "HS256", "typ": "JWT", "kid": KID}).encode())
    body = b64(json.dumps(claims()).encode())
    mac = hmac.new(public_pem, f"{header}.{body}".encode(), hashlib.sha256).digest()

    assert refused(f"{header}.{body}.{b64(mac)}", config) == (
        TokenErrorReason.BAD_SIGNATURE
    )


@pytest.mark.parametrize("token", ["", "not-a-token", "a.b.c", "x" * 20_000])
def test_malformed_tokens_are_refused(token: str, config: TokenConfig) -> None:
    assert refused(token, config) == TokenErrorReason.MALFORMED


def test_token_without_kid_is_malformed(
    private_key: RSAPrivateKey, config: TokenConfig
) -> None:
    assert refused(sign(claims(), private_key, kid=None), config) == (
        TokenErrorReason.MALFORMED
    )


def test_unknown_key_id_is_refused(
    private_key: RSAPrivateKey, config: TokenConfig
) -> None:
    assert refused(sign(claims(), private_key, kid="unknown"), config) == (
        TokenErrorReason.BAD_SIGNATURE
    )


def test_key_source_failure_means_keys_unavailable(
    private_key: RSAPrivateKey, config: TokenConfig
) -> None:
    broken = TokenConfig(
        issuer=config.issuer,
        tenant_id=config.tenant_id,
        audience=config.audience,
        required_scope=config.required_scope,
        key_source=BrokenKeySource(),
    )

    assert refused(sign(claims(), private_key), broken) == (
        TokenErrorReason.KEYS_UNAVAILABLE
    )


def test_error_message_is_the_reason_only(
    private_key: RSAPrivateKey, config: TokenConfig
) -> None:
    token = sign(claims(aud="another-client"), private_key)

    with pytest.raises(TokenError) as raised:
        validate_access_token(token, config)

    assert str(raised.value) == "wrong_audience"
    assert token not in repr(raised.value)


def test_nothing_secret_is_logged(
    private_key: RSAPrivateKey,
    config: TokenConfig,
    caplog: pytest.LogCaptureFixture,
) -> None:
    good = sign(claims(), private_key)
    bad = sign(claims(aud="another-client"), private_key)
    broken = TokenConfig(
        issuer=config.issuer,
        tenant_id=config.tenant_id,
        audience=config.audience,
        required_scope=config.required_scope,
        key_source=BrokenKeySource(),
    )
    public_pem = private_key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )

    with caplog.at_level(logging.DEBUG):
        validate_access_token(good, config)
        refused(bad, config)
        refused(good, broken)
        refused("garbage.token.text", config)

    logged = caplog.text
    assert "wrong_audience" in logged
    assert "OSError" in logged
    for secret in (good, bad, "garbage.token.text", "connection refused"):
        assert secret not in logged
    assert good.split(".")[1] not in logged
    assert public_pem.decode().splitlines()[1] not in logged


# --- key caching -----------------------------------------------------------


class CountingFetch:
    def __init__(self, keys: dict[str, RSAPublicKey]) -> None:
        self.keys = keys
        self.calls = 0
        self.fail = False

    def __call__(self) -> dict[str, RSAPublicKey]:
        self.calls += 1
        if self.fail:
            raise OSError("down")
        return dict(self.keys)


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def caching_config(source: CachingKeySource, config: TokenConfig) -> TokenConfig:
    return TokenConfig(
        issuer=config.issuer,
        tenant_id=config.tenant_id,
        audience=config.audience,
        required_scope=config.required_scope,
        key_source=source,
    )


def test_keys_are_fetched_once_and_cached(
    private_key: RSAPrivateKey, config: TokenConfig
) -> None:
    fetch = CountingFetch({KID: private_key.public_key()})
    cfg = caching_config(CachingKeySource(fetch), config)

    for _ in range(5):
        validate_access_token(sign(claims(), private_key), cfg)

    assert fetch.calls == 1


def test_unknown_key_id_refreshes_once_then_a_burst_fetches_no_more(
    private_key: RSAPrivateKey, config: TokenConfig
) -> None:
    fetch = CountingFetch({KID: private_key.public_key()})
    clock = Clock()
    cfg = caching_config(CachingKeySource(fetch, clock=clock), config)
    validate_access_token(sign(claims(), private_key), cfg)
    assert fetch.calls == 1

    clock.now += 61  # past the refresh interval
    bad = sign(claims(), private_key, kid="unknown")
    assert refused(bad, cfg) == TokenErrorReason.BAD_SIGNATURE
    assert fetch.calls == 2

    for _ in range(50):
        assert refused(bad, cfg) == TokenErrorReason.BAD_SIGNATURE
    assert fetch.calls == 2


def test_unknown_key_id_on_a_cold_cache_fetches_once(
    private_key: RSAPrivateKey, config: TokenConfig
) -> None:
    fetch = CountingFetch({KID: private_key.public_key()})
    cfg = caching_config(CachingKeySource(fetch), config)
    bad = sign(claims(), private_key, kid="unknown")

    for _ in range(10):
        assert refused(bad, cfg) == TokenErrorReason.BAD_SIGNATURE

    assert fetch.calls == 1


def test_rotated_key_is_found_after_the_interval(
    private_key: RSAPrivateKey, other_private_key: RSAPrivateKey, config: TokenConfig
) -> None:
    fetch = CountingFetch({KID: private_key.public_key()})
    clock = Clock()
    cfg = caching_config(CachingKeySource(fetch, clock=clock), config)
    validate_access_token(sign(claims(), private_key), cfg)

    fetch.keys = {
        KID: private_key.public_key(),
        "key-2": other_private_key.public_key(),
    }
    new = sign(claims(), other_private_key, kid="key-2")
    assert refused(new, cfg) == TokenErrorReason.BAD_SIGNATURE  # too soon
    clock.now += 61

    assert validate_access_token(new, cfg).oid == "oid-1"


def test_failed_fetch_is_keys_unavailable_and_is_rate_limited(
    private_key: RSAPrivateKey, config: TokenConfig
) -> None:
    fetch = CountingFetch({KID: private_key.public_key()})
    fetch.fail = True
    clock = Clock()
    cfg = caching_config(CachingKeySource(fetch, clock=clock), config)
    token = sign(claims(), private_key)

    for _ in range(10):
        assert refused(token, cfg) == TokenErrorReason.KEYS_UNAVAILABLE
    assert fetch.calls == 1

    fetch.fail = False
    clock.now += 61
    assert validate_access_token(token, cfg).oid == "oid-1"
    assert fetch.calls == 2


def test_keys_are_fetched_again_when_too_old(
    private_key: RSAPrivateKey, config: TokenConfig
) -> None:
    fetch = CountingFetch({KID: private_key.public_key()})
    clock = Clock()
    cfg = caching_config(CachingKeySource(fetch, clock=clock), config)
    token = sign(claims(), private_key)
    validate_access_token(token, cfg)

    clock.now += tokens.MAX_KEY_AGE_SECONDS + 1
    validate_access_token(token, cfg)

    assert fetch.calls == 2


def test_failed_refresh_of_old_keys_is_not_served_from_the_cache(
    private_key: RSAPrivateKey, config: TokenConfig
) -> None:
    fetch = CountingFetch({KID: private_key.public_key()})
    clock = Clock()
    cfg = caching_config(CachingKeySource(fetch, clock=clock), config)
    token = sign(claims(), private_key)
    validate_access_token(token, cfg)

    fetch.fail = True
    clock.now += tokens.MAX_KEY_AGE_SECONDS + 1

    assert refused(token, cfg) == TokenErrorReason.KEYS_UNAVAILABLE


# --- fetching from the tenant ----------------------------------------------


def jwks_for(key: RSAPublicKey, kid: str) -> dict[str, Any]:
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key))
    return {"keys": [{**jwk, "kid": kid, "use": "sig", "alg": "RS256"}]}


def test_fetcher_reads_keys_from_the_jwks_uri_of_the_openid_configuration(
    private_key: RSAPrivateKey, monkeypatch: pytest.MonkeyPatch
) -> None:
    requested: list[tuple[str, float]] = []

    def get_json(url: str, timeout: float) -> Any:
        requested.append((url, timeout))
        return {"jwks_uri": "https://keys.example.test/jwks"}

    def fetch_data(self: jwt.PyJWKClient) -> Any:
        requested.append((self.uri, self.timeout))
        return jwks_for(private_key.public_key(), KID)

    monkeypatch.setattr(tokens, "_get_json", get_json)
    monkeypatch.setattr(jwt.PyJWKClient, "fetch_data", fetch_data)
    fetcher = OpenIdKeyFetcher(ISSUER, timeout=2.0)

    keys = fetcher()
    fetcher()

    assert list(keys) == [KID]
    assert keys[KID].public_numbers() == private_key.public_key().public_numbers()
    assert requested == [
        (f"{ISSUER}/.well-known/openid-configuration", 2.0),
        ("https://keys.example.test/jwks", 2.0),
        ("https://keys.example.test/jwks", 2.0),
    ]


def test_fetcher_failure_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    def get_json(url: str, timeout: float) -> Any:
        raise TimeoutError("timed out")

    monkeypatch.setattr(tokens, "_get_json", get_json)

    with pytest.raises(TimeoutError):
        OpenIdKeyFetcher(ISSUER)()


def test_http_fetch_reads_json_with_a_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[tuple[str, float]] = []

    class Response:
        def __init__(self, body: bytes) -> None:
            self.body = body

        def __enter__(self) -> Response:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self, limit: int) -> bytes:
            return self.body[:limit]

    def urlopen(url: str, timeout: float) -> Response:
        seen.append((url, timeout))
        return Response(b'{"jwks_uri": "https://keys.example.test/jwks"}')

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)

    assert tokens._get_json("https://example.test/c", 3.0) == {
        "jwks_uri": "https://keys.example.test/jwks"
    }
    assert seen == [("https://example.test/c", 3.0)]


def test_http_fetch_refuses_a_huge_response(monkeypatch: pytest.MonkeyPatch) -> None:
    class Huge:
        def __enter__(self) -> Huge:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self, limit: int) -> bytes:
            return b"x" * limit

    monkeypatch.setattr(urllib.request, "urlopen", lambda url, timeout: Huge())

    with pytest.raises(ValueError, match="large"):
        tokens._get_json("https://example.test/c", 3.0)


def test_http_fetch_refuses_plain_http() -> None:
    with pytest.raises(ValueError, match="https"):
        tokens._get_json("http://example.test/", 1.0)


# --- configuration from settings -------------------------------------------


@pytest.fixture
def fresh_default_config(settings: Any) -> Iterator[Callable[[], TokenConfig]]:
    settings.AUTH_MODE = "entra"  # the test settings use dev
    tokens.default_config.cache_clear()
    yield tokens.default_config
    tokens.default_config.cache_clear()


def test_default_config_is_built_from_settings_once(
    settings: Any, fresh_default_config: Callable[[], TokenConfig]
) -> None:
    settings.ENTRA_TENANT_ID = TENANT
    settings.ENTRA_CLIENT_ID = CLIENT_ID
    settings.ENTRA_REQUIRED_SCOPE = SCOPE

    built = fresh_default_config()

    assert built.issuer == ISSUER
    assert built.tenant_id == TENANT
    assert built.audience == CLIENT_ID
    assert built.required_scope == SCOPE
    assert fresh_default_config() is built


def test_default_config_needs_tenant_and_client(
    settings: Any, fresh_default_config: Callable[[], TokenConfig]
) -> None:
    from django.core.exceptions import ImproperlyConfigured

    settings.ENTRA_TENANT_ID = ""
    settings.ENTRA_CLIENT_ID = CLIENT_ID

    with pytest.raises(ImproperlyConfigured):
        fresh_default_config()


def test_validate_without_a_config_uses_the_default(
    private_key: RSAPrivateKey,
    config: TokenConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tokens, "default_config", lambda: config)

    assert validate_access_token(sign(claims(), private_key)).oid == "oid-1"
