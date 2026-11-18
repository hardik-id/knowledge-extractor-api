# Sign-in

Every endpoint under `/api/v1` needs a valid Entra ID access token, unless its code says otherwise. The first valid token from a person creates their user record. What the UI sends and why is in [auth-api.md](https://github.com/hardik-id/knowledge-extractor/blob/main/docs/auth-api.md) (sections 2 to 4); this page is what the API does with it.

## How a request is signed in

1. The UI sends `Authorization: Bearer <access token>`.
2. `BearerAuthentication` (`apps/identity/authentication.py`) hands the token to `validate_access_token` (`apps/identity/tokens.py`), which checks signature, expiry, issuer and tenant, audience and scope.
3. `get_or_create_user` (`apps/identity/services.py`) finds the user by `oid` together with `tid`. It creates the user on first sight. It writes `name` and `preferred_username` only when the token carries a different value; an unchanged token costs one `SELECT`. A claim the token lacks changes nothing. Names are cut to 255 characters.
4. The view runs with `request.user` set and `request.auth` holding the token's claims (`TokenClaims`).

Two first requests at the same moment end with one user: the unique constraint on `oid` and `tid` refuses the second insert, and that request reads the user the first one made.

A user made this way has no usable password. Local admin accounts (no `oid`, no `tid`) keep the admin's own session login at `/admin/`; the API does not accept session cookies.

## Answers

| Case | Status | Body |
| --- | --- | --- |
| No `Authorization` header, another scheme, `Bearer` with no token or with extra parts | 401 | `unauthenticated` |
| Token malformed, expired, for another issuer, tenant or audience, without the scope, or with an `oid` or `tid` that is not a UUID | 401 | `unauthenticated` |
| Signing keys cannot be fetched from Microsoft | 503 | `not_ready` ("Sign-in is not available right now.") |
| Valid token, user has `is_active` false | 403 | `forbidden` |

Every 401 carries `WWW-Authenticate: Bearer`. The 401 body does not say why the token was refused; the reason is logged (`access token refused: <reason>`), never the token. A 503 has no `WWW-Authenticate`: nothing is known about the token, so the UI should retry rather than sign the person out.

## Defaults

In `REST_FRAMEWORK` (`config/settings/base.py`, section "REST framework"):

- `DEFAULT_AUTHENTICATION_CLASSES` is `BearerAuthentication` only. Session and basic authentication are off for the API.
- `DEFAULT_PERMISSION_CLASSES` is `IsAuthenticated`. A view that declares nothing is closed.

A view opts out in its own code, so the exception is visible where it is made:

```python
@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def health(request): ...
```

`/api/v1/health`, `/api/v1/ready` and the unknown-URL 404 under `/api/` are open.

## Logging

After a token is accepted the person's id is bound to the log context as `user_id`, so every log line of the request carries it, including `request_finished`. See [logging.md](logging.md).

## Variables

| Variable | Meaning |
| --- | --- |
| `ENTRA_TENANT_ID` | The directory (tenant) id. Tokens must come from it: `iss` is `https://login.microsoftonline.com/<tenant-id>/v2.0` and `tid` equals it |
| `ENTRA_CLIENT_ID` | The app registration's client id. Tokens must have it as `aud` |
| `ENTRA_REQUIRED_SCOPE` | The scope `scp` must contain. Default `access_as_user` |
| `AUTH_MODE` | `entra` or `dev`. `dev` is refused in production |

None of them is a secret. Without `ENTRA_TENANT_ID` and `ENTRA_CLIENT_ID` the validator refuses to start work and a signed-in request answers 500. The signing keys are fetched from the tenant's OpenID configuration and cached (see `tokens.py`).

## The app registration

One registration serves the UI and the API; steps are in [auth-api.md](https://github.com/hardik-id/knowledge-extractor/blob/main/docs/auth-api.md), section 1. What this API depends on:

- Single tenant, so `iss` and `tid` are the one tenant in `ENTRA_TENANT_ID`.
- Application ID URI `api://<client-id>`, and a scope `access_as_user`.
- `requestedAccessTokenVersion` is `2` in the manifest. Version 1 tokens have another issuer and audience, and every one of them is refused here.
- The access token carries `oid`, `tid` and `scp`; `name` and `preferred_username` are optional.
- No client secret, no implicit grant. The API holds no secret to talk to Entra ID.

## Tests

`apps/identity/tests/test_authentication.py`. Tokens are signed with a locally generated RSA key and go through the real validator, the real authentication class and a real PostgreSQL database. Only the source of the signing keys is local (`apps/identity/tests/conftest.py`).
