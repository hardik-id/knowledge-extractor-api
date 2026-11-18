"""Entra ID access token validation.

``validate_access_token(token)`` decides whether an access token is valid and
says who it belongs to. It returns ``TokenClaims`` or raises ``TokenError``
with one reason. It knows nothing about the web framework.

Where the signing keys come from, who issued the token and which audience and
scope it needs all arrive in one ``TokenConfig``. Django settings are read in
``default_config`` only, so another issuer (a local one for development) needs
a different ``TokenConfig`` and no change to the validation.

Nothing here logs a token or a key: a rejection logs its reason only.
"""

import json
import logging
import threading
import time
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from functools import cache
from typing import Any, Protocol

import jwt
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey

logger = logging.getLogger(__name__)

ALGORITHM = "RS256"
MAX_TOKEN_LENGTH = 16_384
LEEWAY_SECONDS = 60
HTTP_TIMEOUT_SECONDS = 5.0
MAX_RESPONSE_BYTES = 1_000_000
# At most one key fetch per interval, however many tokens name an unknown key.
MIN_REFRESH_INTERVAL_SECONDS = 60.0
# Keys are fetched again after this long, so a retired key stops being trusted.
MAX_KEY_AGE_SECONDS = 24 * 60 * 60


class TokenErrorReason(StrEnum):
    MALFORMED = "malformed"
    BAD_SIGNATURE = "bad_signature"
    EXPIRED = "expired"  # also a token that is not valid yet (nbf)
    WRONG_ISSUER = "wrong_issuer"  # also another tenant's tid
    WRONG_AUDIENCE = "wrong_audience"
    MISSING_SCOPE = "missing_scope"
    KEYS_UNAVAILABLE = "keys_unavailable"


class TokenError(Exception):
    """The token is refused, or cannot be checked. ``reason`` says why."""

    def __init__(self, reason: TokenErrorReason) -> None:
        super().__init__(reason.value)
        self.reason = reason


@dataclass(frozen=True)
class TokenClaims:
    oid: str
    tid: str
    name: str | None
    preferred_username: str | None
    scopes: frozenset[str]


class KeySource(Protocol):
    """Finds the public key for a key id.

    Returns ``None`` when the source does not know the key. Any exception
    means the keys cannot be fetched.
    """

    def get_key(self, kid: str) -> RSAPublicKey | None: ...


@dataclass(frozen=True)
class TokenConfig:
    issuer: str
    tenant_id: str  # the `tid` claim a token must carry
    audience: str
    required_scope: str
    key_source: KeySource
    leeway_seconds: int = LEEWAY_SECONDS


class CachingKeySource:
    """Caches the keys ``fetch`` returns (a mapping of key id to key).

    The first lookup fetches. A key id that is not in the cache fetches again,
    but at most once per ``min_refresh_interval``, failed fetches included, so
    a stream of bad tokens cannot force a fetch per request. A fetch that
    fails raises: the answer is then "cannot check".
    """

    def __init__(
        self,
        fetch: Callable[[], Mapping[str, RSAPublicKey]],
        *,
        min_refresh_interval: float = MIN_REFRESH_INTERVAL_SECONDS,
        max_age: float = MAX_KEY_AGE_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._fetch = fetch
        self._min_refresh_interval = min_refresh_interval
        self._max_age = max_age
        self._clock = clock
        self._lock = threading.Lock()
        self._keys: Mapping[str, RSAPublicKey] = {}
        self._loaded_at: float | None = None
        self._last_attempt: float | None = None

    def get_key(self, kid: str) -> RSAPublicKey | None:
        with self._lock:
            now = self._clock()
            expired = self._loaded_at is None or now - self._loaded_at >= self._max_age
            refreshed = False
            if expired and self._may_fetch(now):
                self._refresh(now)
                refreshed = True
            elif expired:
                raise RuntimeError("signing keys are not available")
            key = self._keys.get(kid)
            if key is None and not refreshed and self._may_fetch(now):
                self._refresh(now)
                key = self._keys.get(kid)
            return key

    def _may_fetch(self, now: float) -> bool:
        return (
            self._last_attempt is None
            or now - self._last_attempt >= self._min_refresh_interval
        )

    def _refresh(self, now: float) -> None:
        self._last_attempt = now
        self._keys = dict(self._fetch())
        self._loaded_at = now


def _get_json(url: str, timeout: float) -> Any:
    if not url.startswith("https://"):
        raise ValueError("only https is allowed")
    with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310
        body = response.read(MAX_RESPONSE_BYTES + 1)
    if len(body) > MAX_RESPONSE_BYTES:
        raise ValueError("response is too large")
    return json.loads(body)


class OpenIdKeyFetcher:
    """Fetches a tenant's signing keys from the ``jwks_uri`` of its OpenID
    configuration, with network timeouts. Pass it to ``CachingKeySource``.
    """

    def __init__(self, issuer: str, timeout: float = HTTP_TIMEOUT_SECONDS) -> None:
        self._configuration_url = f"{issuer}/.well-known/openid-configuration"
        self._timeout = timeout
        self._client: jwt.PyJWKClient | None = None

    def __call__(self) -> dict[str, RSAPublicKey]:
        if self._client is None:
            configuration = _get_json(self._configuration_url, self._timeout)
            self._client = jwt.PyJWKClient(
                configuration["jwks_uri"],
                cache_jwk_set=False,  # CachingKeySource owns the caching
                timeout=self._timeout,
            )
        keys = self._client.get_signing_keys(refresh=True)
        return {
            key.key_id: key.key
            for key in keys
            if key.key_id is not None and isinstance(key.key, RSAPublicKey)
        }


def entra_config(
    *, tenant_id: str, client_id: str, required_scope: str, key_source: KeySource
) -> TokenConfig:
    return TokenConfig(
        issuer=entra_issuer(tenant_id),
        tenant_id=tenant_id,
        audience=client_id,
        required_scope=required_scope,
        key_source=key_source,
    )


def entra_issuer(tenant_id: str) -> str:
    return f"https://login.microsoftonline.com/{urllib.parse.quote(tenant_id, safe='')}/v2.0"


@cache
def default_config() -> TokenConfig:
    """The configuration from Django settings, built once so the key cache
    lives as long as the process. This is the only place settings are read.
    """
    from django.conf import settings
    from django.core.exceptions import ImproperlyConfigured

    if not settings.ENTRA_TENANT_ID or not settings.ENTRA_CLIENT_ID:
        raise ImproperlyConfigured(
            "ENTRA_TENANT_ID and ENTRA_CLIENT_ID are required to validate tokens"
        )
    issuer = entra_issuer(settings.ENTRA_TENANT_ID)
    return entra_config(
        tenant_id=settings.ENTRA_TENANT_ID,
        client_id=settings.ENTRA_CLIENT_ID,
        required_scope=settings.ENTRA_REQUIRED_SCOPE,
        key_source=CachingKeySource(OpenIdKeyFetcher(issuer)),
    )


def validate_access_token(token: str, config: TokenConfig | None = None) -> TokenClaims:
    """Return the claims of a valid access token, or raise ``TokenError``."""
    if config is None:
        config = default_config()
    try:
        return _validate(token, config)
    except TokenError as error:
        logger.info("access token refused: %s", error.reason.value)
        raise


def _validate(token: str, config: TokenConfig) -> TokenClaims:
    if not isinstance(token, str) or not token or len(token) > MAX_TOKEN_LENGTH:
        raise TokenError(TokenErrorReason.MALFORMED)

    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError:
        raise TokenError(TokenErrorReason.MALFORMED) from None
    # RS256 only: refuses `none` and the HMAC algorithms before any key is used.
    if header.get("alg") != ALGORITHM:
        raise TokenError(TokenErrorReason.BAD_SIGNATURE)
    kid = header.get("kid")
    if not isinstance(kid, str) or not kid:
        raise TokenError(TokenErrorReason.MALFORMED)

    try:
        key = config.key_source.get_key(kid)
    except Exception as error:
        # Say what failed, never what it carried.
        logger.warning("signing keys could not be fetched: %s", type(error).__name__)
        raise TokenError(TokenErrorReason.KEYS_UNAVAILABLE) from None
    if key is None:
        raise TokenError(TokenErrorReason.BAD_SIGNATURE)

    try:
        payload = jwt.decode(
            token,
            key,
            algorithms=[ALGORITHM],
            leeway=config.leeway_seconds,
            options={
                "require": ["exp", "nbf", "iss", "aud"],
                "verify_aud": False,  # checked below, after the issuer
                "verify_iss": False,
            },
        )
    except jwt.ExpiredSignatureError, jwt.ImmatureSignatureError:
        raise TokenError(TokenErrorReason.EXPIRED) from None
    except (
        jwt.InvalidSignatureError,
        jwt.InvalidAlgorithmError,
        jwt.InvalidKeyError,
    ):
        raise TokenError(TokenErrorReason.BAD_SIGNATURE) from None
    except jwt.PyJWTError:
        raise TokenError(TokenErrorReason.MALFORMED) from None

    if payload["iss"] != config.issuer or payload.get("tid") != config.tenant_id:
        raise TokenError(TokenErrorReason.WRONG_ISSUER)
    audience = payload["aud"]
    audiences = audience if isinstance(audience, list) else [audience]
    if config.audience not in audiences:
        raise TokenError(TokenErrorReason.WRONG_AUDIENCE)

    scp = payload.get("scp")
    scopes = frozenset(scp.split()) if isinstance(scp, str) else frozenset()
    if config.required_scope not in scopes:
        raise TokenError(TokenErrorReason.MISSING_SCOPE)

    oid = payload.get("oid")
    if not isinstance(oid, str) or not oid:
        raise TokenError(TokenErrorReason.MALFORMED)

    return TokenClaims(
        oid=oid,
        tid=config.tenant_id,
        name=_optional_text(payload.get("name")),
        preferred_username=_optional_text(payload.get("preferred_username")),
        scopes=scopes,
    )


def _optional_text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
