"""Cloudflare Access JWT verification (Joey TV WP-A6a, 2026-10-19; Q25b pulled forward into Phase A; parent H-64).

Cloudflare Access is the hub's only gate, and `hub/identity.py` believes `Cf-Access-Authenticated-User-Email` as sent.
Since N-09 and the host-mode SWAG (Q44 a), more than cloudflared can reach `hub:8000`, so a forged header from any
neighbour would read B.'s private Joey. `AccessGate` checks Cloudflare's signed `Cf-Access-Jwt-Assertion` first:

* `ACCESS_JWT_VERIFY` (read per request): unset / `0` = off, today's behaviour and the default (nothing is fetched or
  logged); `audit` = verify every request and log the verdict, never refuse; `1` = enforce.
* `ACCESS_AUD`: comma-separated Application Audience tags allowed (the joeyhome.net Access app). Required when the flag
  is not off: `check_config()` raises at import of hub.main, so a bad deploy fails at `wait_for_hub` and rolls back.
* `ACCESS_TEAM` (default `joeyhomeed`): issuer `https://<team>.cloudflareaccess.com`, keys from `/cdn-cgi/access/certs`.

Checks: `alg` exactly RS256 (never `none` / HS256), a known `kid`, the signature, `iss`, `aud` meets `ACCESS_AUD`,
`exp` / `nbf` / `iat` present and in window (60 s leeway), and the `email` claim equal to the header (any case), so
identity comes from the signed claim. Refusals: 401 plain text; 503 `no_keys` when the certs cannot be read and no key
is cached. Exempt: `/healthz` and loopback peers (smoke.py, `docker exec` reads, local dev) - nothing else.
Reason codes: missing, alg, kid, sig, iss, aud, exp (also nbf / iat), email, no_keys. Logs carry the reason, the path,
8 characters of the kid and the owner word - never the email or the token (rule 20).
Not closed: replay of a captured token within its lifetime, and a compromised hub container.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from types import SimpleNamespace

import jwt
import requests
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import Headers

from hub.identity import IDENTITY_HEADER, resolve_identity

JWT_HEADER = "Cf-Access-Jwt-Assertion"
DEFAULT_TEAM = "joeyhomeed"
LEEWAY_S = 60
FETCH_TIMEOUT_S = 5
UNKNOWN_KID_REFETCH_S = 60
REFRESH_EVERY_S = 24 * 3600
EXEMPT_PATHS = frozenset({"/healthz"})
LOOPBACK = frozenset({"127.0.0.1", "::1"})
MODES = {"": "off", "0": "off", "audit": "audit", "1": "enforce"}

log = logging.getLogger("hub.access_jwt")
_clock = time.monotonic


@dataclass(frozen=True)
class Verdict:
    ok: bool
    email: str | None = None
    reason: str | None = None
    kid: str | None = None


def _flag() -> str:
    return (os.environ.get("ACCESS_JWT_VERIFY") or "").strip().lower()


def mode() -> str:
    """'off' | 'audit' | 'enforce'. An unrecognised value enforces (fail closed); check_config refuses it at startup."""
    return MODES.get(_flag(), "enforce")


def allowed_auds() -> list[str]:
    return [a.strip() for a in (os.environ.get("ACCESS_AUD") or "").split(",") if a.strip()]


def issuer() -> str:
    return f"https://{(os.environ.get('ACCESS_TEAM') or '').strip() or DEFAULT_TEAM}.cloudflareaccess.com"


def check_config() -> None:
    """Startup validation (hub.main): a misconfigured flag crash-loops visibly instead of silently opening or closing."""
    if _flag() not in MODES:
        raise ValueError("ACCESS_JWT_VERIFY must be unset, 0, audit or 1")
    if mode() != "off" and not allowed_auds():
        raise ValueError("ACCESS_AUD must be set when ACCESS_JWT_VERIFY is audit or 1")


# ---- the signing keys (JWKS), cached by kid ----

def _fetch_jwks(url: str) -> dict:
    resp = requests.get(url, timeout=FETCH_TIMEOUT_S)
    resp.raise_for_status()
    return resp.json()


_lock = threading.Lock()
_keys: dict = {}            # kid -> public key
_loaded_at: float | None = None
_tried_at: float | None = None
_unknown_at: float | None = None


def reset() -> None:
    global _keys, _loaded_at, _tried_at, _unknown_at
    with _lock:
        _keys, _loaded_at, _tried_at, _unknown_at = {}, None, None, None


def _load(now: float) -> None:
    """Fetch the team's certs; a failure keeps whatever is cached (Cloudflare serves the previous key alongside)."""
    global _keys, _loaded_at, _tried_at
    _tried_at = now
    try:
        found = {k.key_id: k.key for k in jwt.PyJWKSet.from_dict(_fetch_jwks(issuer() + "/cdn-cgi/access/certs")).keys
                 if k.key_id and k.algorithm_name == "RS256"}
    except Exception as exc:  # noqa: BLE001 - any failure: keep the cache, the verdict says no_keys / kid
        log.warning("access_jwt: keys fetch failed (%s)", type(exc).__name__)
        return
    if found:
        _keys, _loaded_at = found, now
        log.info("access_jwt: keys loaded n=%d", len(found))


def _key_for(kid: str):
    """(key, None) or (None, 'kid' | 'no_keys'). First use loads; a stale cache (24 h) reloads; an unknown kid
    re-fetches at most once per 60 s."""
    global _unknown_at
    with _lock:
        now = _clock()
        fetched = False
        if not _keys and (_tried_at is None or now - _tried_at >= UNKNOWN_KID_REFETCH_S):
            _load(now)
            fetched = True
        elif _keys and now - _loaded_at >= REFRESH_EVERY_S and now - _tried_at >= UNKNOWN_KID_REFETCH_S:
            _load(now)
            fetched = True
        if kid not in _keys and _keys and not fetched and (
                _unknown_at is None or now - _unknown_at >= UNKNOWN_KID_REFETCH_S):
            _unknown_at = now
            _load(now)
        if kid in _keys:
            return _keys[kid], None
        return None, ("kid" if _keys else "no_keys")


# ---- the verdict ----

_TIME_CLAIMS = {"exp", "nbf", "iat"}


def _reason(exc: jwt.InvalidTokenError) -> str:
    if isinstance(exc, jwt.MissingRequiredClaimError):
        return "exp" if exc.claim in _TIME_CLAIMS else exc.claim if exc.claim in ("iss", "aud", "email") else "sig"
    for kind, reason in ((jwt.ExpiredSignatureError, "exp"), (jwt.ImmatureSignatureError, "exp"),
                         (jwt.InvalidIssuedAtError, "exp"), (jwt.InvalidAudienceError, "aud"),
                         (jwt.InvalidIssuerError, "iss"), (jwt.InvalidAlgorithmError, "alg")):
        if isinstance(exc, kind):
            return reason
    return "sig"   # bad signature or a malformed token


def verify(headers) -> Verdict:
    token = (headers.get(JWT_HEADER) or "").strip()
    if not token:
        return Verdict(False, reason="missing")
    try:
        head = jwt.get_unverified_header(token)
    except jwt.InvalidTokenError:
        return Verdict(False, reason="sig")
    if head.get("alg") != "RS256":
        return Verdict(False, reason="alg")
    kid = head.get("kid")
    if not isinstance(kid, str) or not kid:
        return Verdict(False, reason="kid")
    key, missing = _key_for(kid)
    if key is None:
        return Verdict(False, reason=missing, kid=kid)
    auds = allowed_auds()
    if not auds:
        return Verdict(False, reason="aud", kid=kid)
    try:
        claims = jwt.decode(token, key, algorithms=["RS256"], audience=auds, issuer=issuer(), leeway=LEEWAY_S,
                            options={"require": ["exp", "iat", "nbf", "iss", "aud", "email"]})
    except jwt.InvalidTokenError as exc:
        return Verdict(False, reason=_reason(exc), kid=kid)
    email, sent = claims.get("email"), (headers.get(IDENTITY_HEADER) or "").strip()
    if not isinstance(email, str) or not sent or email.strip().lower() != sent.lower():
        return Verdict(False, reason="email", kid=kid)
    return Verdict(True, email=email, kid=kid)


# ---- the ASGI gate (registered FIRST in hub.main = innermost, so ShellMiddleware logs its 401) ----

async def _refuse(send, status: int, text: str) -> None:
    body = text.encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"text/plain; charset=utf-8"), (b"content-length", str(len(body)).encode()),
                            (b"cache-control", b"no-store")]})
    await send({"type": "http.response.body", "body": body})


class AccessGate:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or (current := mode()) == "off":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        peer = (scope.get("client") or (None,))[0]
        if path in EXEMPT_PATHS or peer in LOOPBACK:
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        verdict = await run_in_threadpool(verify, headers)
        prefix = "audit " if current == "audit" else ""
        if verdict.ok:
            owner = resolve_identity(SimpleNamespace(headers=headers)).owner or "none"
            log.debug("access_jwt: %sok kid=%s owner=%s", prefix, (verdict.kid or "")[:8], owner)
        else:
            log.warning("access_jwt: %sFAIL reason=%s path=%s", prefix, verdict.reason, path)
            if current == "enforce":
                if verdict.reason == "no_keys":
                    await _refuse(send, 503, "Service unavailable: Access keys could not be read.\n")
                else:
                    await _refuse(send, 401, "Unauthorized.\n")
                return
        await self.app(scope, receive, send)
