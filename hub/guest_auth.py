"""Guest identity on the media front (Joey TV WP-B2, 2026-10-21): the ONE Jellyfin auth client of `joey-media`.

A guest signs in with Jellyfin itself - Quick Connect first, username + password as the fallback (DECISIONS B #18) -
and the Jellyfin access token it gets back IS the session: it lives in the `__Host-jm_session` cookie (HttpOnly,
Secure, SameSite=Lax, 90 days absolute from sign-in - Q26) and Jellyfin stays the session store, so revoking a friend
in Jellyfin (disable / delete the user, sign the device out) ends their Joey Media session too (DECISIONS B #17).

* Every Jellyfin call sends the 12.2 header `Authorization: MediaBrowser Client="Joey Media", Device="Joey Media TV" |
  "Joey Media web", DeviceId="<__Host-jm_dev>", Version="<VERSION>"[, Token="…"]` (12.2 answers 400 to
  X-Emby-Authorization and 401 to a bare X-Emby-Token - W3 probe, 2026-10-21).
* Re-validation: `GET /Users/Me` with the token, the verdict kept VERDICT_TTL (Q27 = 60 s) per sha256(token), one call
  at a time per token (a page's burst of poster requests shares it). 4xx = invalid (the cookie is cleared). Valid but
  `Policy.IsDisabled`, `Policy.IsAdministrator`, or `Policy.EnableRemoteAccess` not true = invalid as well (P1,
  2026-10-19: joey-media reaches Jellyfin from the 172.18/16 bridge, which Jellyfin counts as LAN, so it never applies
  the remote-access flag to these sign-ins - the hub enforces it, and the admin can never hold a guest session).
  5xx / timeout / no answer = UNREACHABLE: never cached, the cookie kept, a 503 page - except that a verdict which WAS
  valid is served up to STALE_GRACE past its TTL while Jellyfin does not answer (the NAS under swap pressure can take
  more than 10 s - W3), never a verdict Jellyfin refused.
* The owner is hub.identity.owner_for_jellyfin(user id) - the one mapping: the alias user (JELLYFIN_USER_ALIASES) is
  `you`, everyone else `jf:<32 hex>`. The household lookup failing is UNREACHABLE, never a guessed owner.
* Password failures: FAIL_LIMIT (5) per username in FAIL_WINDOW_S (15 min), then refused WITHOUT calling Jellyfin
  (Q28 / D-P15), so the guest path can never trip Jellyfin's own lockout (10, which DISABLES the user). In-process,
  keyed by sha256(lower(username)).
* Logs carry `jf:<id>` or a username-hash prefix, never a username, password, token or Quick Connect secret
  (DECISIONS G; §2 rule 20).
* Cookies: `JOEY_COOKIE_SECURE` (default 1). 0 = plain names without `__Host-` and no Secure flag, for http previews
  only; tests/deploy/test_joey_media_service.py forbids it in compose.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import secrets
import threading
import time
from collections import OrderedDict
from concurrent.futures import Future
from http.cookies import SimpleCookie

from starlette.datastructures import Headers

from hub import guest, identity, upstream
from hub.identity import Identity

log = logging.getLogger("hub.guest_auth")

CLIENT = "Joey Media"
DEVICE_TV = "Joey Media TV"
DEVICE_WEB = "Joey Media web"
VERSION = "1.0.0"
FALLBACK_DEVICE = "joey-media"   # a request without a __Host-jm_dev cookie (never on the sign-in path, which sets it)

VERDICT_TTL = 60              # Q27
STALE_GRACE = 300             # a valid verdict served this long past its TTL while Jellyfin does not answer
VALIDATE_TIMEOUT = 10         # /Users/Me on a page's path (W3: the NAS can be slow under swap pressure)
SIGNIN_TIMEOUT = 30           # sign-in calls: a friend waits for these, a page never does
FAIL_LIMIT = 5                # Q28 / D-P15
FAIL_WINDOW_S = 15 * 60
WRONG_DELAY_S = 1             # a wrong password answers no faster than this
VERDICT_MAX = 512

SESSION, QC, DEV = "jm_session", "jm_qc", "jm_dev"
SESSION_MAX_AGE = 7_776_000   # 90 days, absolute (Q26): set once at sign-in, never extended
QC_MAX_AGE = 600
DEV_MAX_AGE = 34_560_000      # 400 days, the browser maximum

TOKEN_RE = re.compile(r"^[A-Za-z0-9]{16,128}$")
DEV_RE = re.compile(r"^[0-9a-f]{32}$")
SECRET_RE = re.compile(r"^[A-Za-z0-9]{16,256}$")

clock = time.monotonic        # tests inject a clock
sleep = time.sleep            # tests record the wrong-password delay instead of waiting


class Unreachable(Exception):
    """Jellyfin did not give a usable answer (timeout, 5xx, garbage) - never a verdict about the token."""


# ---- cookies ----

def secure_cookies() -> bool:
    return (os.environ.get("JOEY_COOKIE_SECURE") or "1").strip() != "0"


def cookie_name(base: str) -> str:
    return f"__Host-{base}" if secure_cookies() else base


def set_cookie_header(base: str, value: str, max_age: int) -> str:
    """One Set-Cookie value with the exact attributes: HttpOnly, SameSite=Lax, Path=/ (+ Secure unless the http
    preview turned it off). A cleared cookie is `<name>=; Max-Age=0; …`."""
    attrs = f"; Max-Age={max_age}; Path=/; HttpOnly" + ("; Secure" if secure_cookies() else "") + "; SameSite=Lax"
    return f"{cookie_name(base)}={value}{attrs}"


def clear_cookie_header(base: str) -> str:
    return set_cookie_header(base, "", 0)


def cookies_of(headers: Headers) -> dict:
    jar = SimpleCookie()
    try:
        jar.load(headers.get("cookie") or "")
    except Exception:   # a malformed Cookie header: no cookies
        return {}
    return {k: m.value for k, m in jar.items()}


def device_of(cookies: dict) -> str:
    value = cookies.get(cookie_name(DEV)) or ""
    return value if DEV_RE.match(value) else FALLBACK_DEVICE


def new_device_id() -> str:
    return secrets.token_hex(16)


def is_tv(headers: Headers) -> bool:
    return guest.TV_UA_TOKEN in (headers.get("user-agent") or "")


# ---- the Jellyfin client ----

def jellyfin_base() -> str | None:
    base = (os.environ.get("JELLYFIN_URL") or "").strip().rstrip("/")
    return base or None


def auth_header(device_id: str, tv: bool = False, token: str | None = None) -> dict:
    parts = [f'Client="{CLIENT}"', f'Device="{DEVICE_TV if tv else DEVICE_WEB}"',
             f'DeviceId="{device_id if DEV_RE.match(device_id or "") else FALLBACK_DEVICE}"', f'Version="{VERSION}"']
    if token:
        parts.append(f'Token="{token}"')
    return {"Authorization": "MediaBrowser " + ", ".join(parts)}


def _call(method: str, path: str, headers: dict, timeout: float, body: dict | None = None, params: dict | None = None):
    """-> (status, json or None). Unreachable on no answer or a 5xx; the exception TYPE only is ever logged (requests
    errors embed the URL)."""
    base = jellyfin_base()
    if base is None:
        raise Unreachable("Jellyfin not configured")
    session = upstream.session("jellyfin")
    try:
        if method == "GET":
            resp = session.get(f"{base}{path}", params=params, headers=headers, timeout=timeout)
        else:
            resp = session.post(f"{base}{path}", params=params, json=body, headers=headers, timeout=timeout)
    except Exception as exc:
        raise Unreachable(type(exc).__name__) from None
    if resp.status_code >= 500:
        raise Unreachable(f"HTTP {resp.status_code}")
    try:
        data = resp.json()
    except Exception:
        data = None
    return resp.status_code, data


def refusal(user) -> str | None:
    """Why a VALID Jellyfin user may not hold a guest session, or None. Fails closed on a missing policy (P1)."""
    policy = user.get("Policy") if isinstance(user, dict) else None
    if not isinstance(policy, dict):
        return "policy"
    if policy.get("IsDisabled") is not False:
        return "disabled"
    if policy.get("IsAdministrator") is not False:
        return "admin"
    if policy.get("EnableRemoteAccess") is not True:
        return "remote-off"
    return None


def _log_id(user) -> str:
    try:
        return "jf:" + identity._norm_id((user or {}).get("Id"))
    except (ValueError, AttributeError):
        return "jf:?"


def identity_for(user: dict, token: str) -> Identity | None:
    """The guest Identity for a valid, allowed Jellyfin user; None when the id is malformed; Unreachable while the
    household's ids cannot be read (identity.OwnerUnresolved - never a guessed owner)."""
    try:
        uid = identity._norm_id(user.get("Id"))
    except ValueError:
        return None
    try:
        owner = identity.owner_for_jellyfin(uid)
    except identity.OwnerUnresolved as exc:
        raise Unreachable(f"owner lookup: {exc}") from None
    name = str(user.get("Name") or "").strip()[:80] or "Friend"
    return Identity(owner=owner, name=name, jf_user_id=uid, jf_token=token)


# ---- the verdict cache ----

_lock = threading.Lock()
_verdicts: OrderedDict = OrderedDict()   # sha256(token) -> (checked_at, Identity); valid verdicts only
_flights: dict = {}                     # sha256(token) -> Future of the one /Users/Me call in flight
_fails: dict = {}                       # sha256(lower(username)) -> [failure times]


def clear() -> None:
    with _lock:
        _verdicts.clear()
        _flights.clear()
        _fails.clear()


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _keep(key: str, ident: Identity) -> None:
    with _lock:
        _verdicts[key] = (clock(), ident)
        _verdicts.move_to_end(key)
        while len(_verdicts) > VERDICT_MAX:
            _verdicts.popitem(last=False)


def forget(token: str | None) -> None:
    """Evict a token's verdict (sign-out, or Jellyfin refused it)."""
    if token:
        with _lock:
            _verdicts.pop(_hash(token), None)


def _check(token: str, device_id: str, tv: bool) -> Identity | None:
    status, user = _call("GET", "/Users/Me", auth_header(device_id, tv, token), VALIDATE_TIMEOUT)
    if not 200 <= status < 300:
        return None   # 4xx: the token is dead (revoked, user deleted)
    if not isinstance(user, dict):
        raise Unreachable("unexpected /Users/Me answer")
    reason = refusal(user)
    if reason:
        log.warning("guest: refused %s %s", reason, _log_id(user))
        return None
    ident = identity_for(user, token)
    if ident is not None:
        _keep(_hash(token), ident)
    return ident


def _once(key: str, fn):
    with _lock:
        fut = _flights.get(key)
        lead = fut is None
        if lead:
            fut = _flights[key] = Future()
    if not lead:
        return fut.result()
    try:
        out = fn()
        fut.set_result(out)
        return out
    except BaseException as exc:
        fut.set_exception(exc)
        raise
    finally:
        with _lock:
            _flights.pop(key, None)


def validate(token: str, device_id: str, tv: bool = False) -> Identity | None:
    """The token's Identity, or None when Jellyfin says it is not a guest session (dead token, disabled, admin, remote
    access off). Raises Unreachable when Jellyfin cannot say (nothing cached; a recent valid verdict is served for
    STALE_GRACE instead)."""
    key = _hash(token)
    with _lock:
        hit = _verdicts.get(key)
    now = clock()
    if hit and now - hit[0] < VERDICT_TTL:
        return hit[1]
    try:
        ident = _once(key, lambda: _check(token, device_id, tv))
    except Unreachable as exc:
        if hit and now - hit[0] < VERDICT_TTL + STALE_GRACE:
            log.warning("guest: jellyfin unreachable (%s), keeping a recent verdict for %s", exc, hit[1].owner)
            return hit[1]
        raise
    if ident is None:
        forget(token)
    return ident


# ---- GuestGate's identity hook ----

OK, NONE, INVALID, UNREACHABLE = "ok", "none", "invalid", "unreachable"


def resolve_scope(scope) -> tuple[str, Identity | None]:
    """(OK, identity) / (NONE, None) no session cookie / (INVALID, None) Jellyfin refused it or it is malformed - the
    cookie is to be cleared / (UNREACHABLE, None) Jellyfin cannot say - the cookie is kept. Runs in a worker thread
    (GuestGate: anyio.to_thread); it may block up to VALIDATE_TIMEOUT."""
    headers = Headers(scope=scope)
    cookies = cookies_of(headers)
    token = cookies.get(cookie_name(SESSION))
    if not token:
        return NONE, None
    if not TOKEN_RE.match(token):
        return INVALID, None
    try:
        ident = validate(token, device_of(cookies), is_tv(headers))
    except Unreachable as exc:
        log.warning("guest: jellyfin unreachable (%s)", exc)
        return UNREACHABLE, None
    return (OK, ident) if ident is not None else (INVALID, None)


def user_creds(request) -> tuple[str, dict, str] | None:
    """(base, headers, user id) to act as the signed-in user with THEIR token (P3) - None without a full identity."""
    ident = guest.identity_in_scope(getattr(request, "scope", None))
    base = jellyfin_base()
    if not (ident and ident.jf_user_id and ident.jf_token and base):
        return None
    headers = request.headers
    return base, auth_header(device_of(cookies_of(headers)), is_tv(headers), ident.jf_token), ident.jf_user_id


# ---- sign-in ----

def user_key(username: str) -> str:
    return _hash((username or "").strip().lower())


def blocked(username: str) -> bool:
    """True once FAIL_LIMIT failures for this username fall inside FAIL_WINDOW_S: refuse without calling Jellyfin."""
    key, now = user_key(username), clock()
    with _lock:
        recent = [t for t in _fails.get(key, []) if now - t < FAIL_WINDOW_S]
        if recent:
            _fails[key] = recent
        else:
            _fails.pop(key, None)
        return len(recent) >= FAIL_LIMIT


def note_failure(username: str) -> None:
    key = user_key(username)
    with _lock:
        _fails.setdefault(key, []).append(clock())
    log.info("guest: password sign-in failed u:%s", key[:8])


def clear_failures(username: str) -> None:
    with _lock:
        _fails.pop(user_key(username), None)


def logout(token: str, device_id: str, tv: bool = False) -> bool:
    """POST /Sessions/Logout with the token (Jellyfin forgets the session and its device); best effort."""
    try:
        status, _ = _call("POST", "/Sessions/Logout", auth_header(device_id, tv, token), VALIDATE_TIMEOUT)
    except Unreachable as exc:
        log.warning("guest: sign-out not confirmed by jellyfin (%s)", exc)
        return False
    return 200 <= status < 300


def session_from(body, device_id: str, tv: bool) -> tuple[str, Identity] | None:
    """An AuthenticateByName / AuthenticateWithQuickConnect answer -> (token, identity), or None when the user may not
    hold a guest session (P1) - that fresh token is logged out at once, so no orphan session is left in Jellyfin."""
    token = body.get("AccessToken") if isinstance(body, dict) else None
    user = body.get("User") if isinstance(body, dict) else None
    if not (isinstance(token, str) and TOKEN_RE.match(token) and isinstance(user, dict)):
        raise Unreachable("unexpected sign-in answer")
    reason = refusal(user)
    ident = None if reason else identity_for(user, token)
    if ident is None:
        log.warning("guest: refused %s %s", reason or "id", _log_id(user))
        logout(token, device_id, tv)
        return None
    _keep(_hash(token), ident)
    log.info("guest: signed in %s", ident.owner if ident.owner == "you" else f"jf:{ident.jf_user_id}")
    return token, ident


def password_signin(username: str, password: str, device_id: str, tv: bool = False):
    """-> (token, identity) / "wrong" (bad credentials, refused user, or the username is resting) - the same words for
    all three / raises Unreachable (not counted)."""
    if blocked(username):
        log.info("guest: password sign-in refused before jellyfin u:%s", user_key(username)[:8])
        return "wrong"
    status, body = _call("POST", "/Users/AuthenticateByName", auth_header(device_id, tv), SIGNIN_TIMEOUT,
                         body={"Username": username, "Pw": password})
    if not 200 <= status < 300:
        note_failure(username)
        return "wrong"
    out = session_from(body, device_id, tv)
    if out is None:
        note_failure(username)   # P1: an admin's right password counts like a wrong one
        return "wrong"
    clear_failures(username)
    return out


def qc_initiate(device_id: str, tv: bool = False) -> tuple[str, str]:
    """-> (secret, code). Unreachable when Quick Connect is off or Jellyfin does not answer."""
    status, body = _call("POST", "/QuickConnect/Initiate", auth_header(device_id, tv), SIGNIN_TIMEOUT)
    body = body if isinstance(body, dict) else {}
    secret, code = body.get("Secret"), body.get("Code")
    if not (200 <= status < 300 and isinstance(secret, str) and SECRET_RE.match(secret) and code):
        raise Unreachable(f"Quick Connect initiate HTTP {status}")
    return secret, str(code)


def qc_state(secret: str, device_id: str, tv: bool = False) -> bool | None:
    """True once approved on the phone, False while waiting, None when Jellyfin no longer knows the code (expired)."""
    status, body = _call("GET", "/QuickConnect/Connect", auth_header(device_id, tv), VALIDATE_TIMEOUT,
                         params={"secret": secret})
    if not 200 <= status < 300 or not isinstance(body, dict):
        return None
    return bool(body.get("Authenticated"))


def qc_signin(secret: str, device_id: str, tv: bool = False):
    """-> (token, identity) / None (refused user, or Jellyfin would not exchange the secret)."""
    status, body = _call("POST", "/Users/AuthenticateWithQuickConnect", auth_header(device_id, tv), SIGNIN_TIMEOUT,
                         body={"Secret": secret})
    if not 200 <= status < 300:
        return None
    return session_from(body, device_id, tv)
