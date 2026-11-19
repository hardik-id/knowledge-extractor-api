# Security: CORS and response headers

All of it is configured in `config/settings/base.py` (section "Security") and `production.py`.

## CORS

- Origins come from `CORS_ALLOWED_ORIGINS` (comma separated, default `http://localhost:3000`). A `*` stops startup. `CORS_ALLOW_ALL_ORIGINS` is off.
- Allowed request headers: Django-CORS defaults plus `X-Request-ID`, `traceparent`, `tracestate` and `baggage` (so `Authorization` and `Content-Type` are included).
- Exposed response headers: `ETag`, `X-Request-ID` and `Server-Timing` (the trace id, see [observability.md](observability.md)).
- No credentials: `Access-Control-Allow-Credentials` is never sent, because the UI sends a bearer token and no cookies.
- The middleware sits right after the request id and log middleware, before everything else, so preflights and errors carry the headers too.

django-cors-headers 4.9.0 declares support up to Django 6.0; it has no release that names 6.1. It runs unchanged on 6.1 and the tests cover it. Revisit when a release names 6.1.

## Security headers

| Header | Value | Where |
| --- | --- | --- |
| `X-Content-Type-Options` | `nosniff` | `SECURE_CONTENT_TYPE_NOSNIFF` |
| `Referrer-Policy` | `same-origin` | `SECURE_REFERRER_POLICY` |
| `X-Frame-Options` | `DENY` | `X_FRAME_OPTIONS` |
| `Strict-Transport-Security` | one year, include subdomains | production only |
| `Content-Security-Policy` | see below | `SECURE_CSP` |

## Content-Security-Policy

Django's built-in `ContentSecurityPolicyMiddleware` and `SECURE_CSP` send an enforced policy: everything from `'self'`, images also from `data:`, no plugins, `frame-ancestors 'none'`. The admin renders under it. When Swagger UI is added (#20), allow it per view with `CSP.NONCE` or a view-level override, not by loosening the global policy.
