"""The guest surface's small server-side helpers (Joey TV WP-B3, 2026-10-21). hub.guest owns WHAT the media front
serves (the route tables, allows(), the gate); this module owns how its pages read: the Jinja globals `guest(request)`,
`guest_allows(path)`, `brand()`, `guest_home()` and `tv_mode(request)`, the `brand_title` filter (Q32), the TV-mode
cookie GuestGate sets, and the one-time "Set up Jellyfin" card's cookie (Q39). hub.shell registers the globals on the
one Jinja env. Every function answers for the private front too (always "not guest"), so templates call them freely.

TV mode (Q34, DECISIONS D, D-P8): true only on the media front, when the user agent carries hub.guest.TV_UA_TOKEN
(the shell's ` JoeyTV/<semver> (<versionCode>)`) or the `tv=1` cookie is set. `?tv=1` sets the cookie (1 year,
SameSite=Lax) and `?tv=0` clears it - for desktop testing; the query also decides the page it arrives on. The shell's
user agent always wins (the TV never leaves TV mode).

The TV shell player (JY-057, 2026-10-27): `tv_player(request)` says Play on this page opens the shell's own player
(PLAYER_API on, the media front, the shell's user agent at TV_PLAYER_MIN_CODE or later, a household member signed in);
the title / episode pages then add TV_PLAYER_MARK to their Jellyfin deep links (`tv_play_href`), which the shell's
UrlPolicy reads. Anyone else keeps today's link."""
from __future__ import annotations

import re
from urllib.parse import parse_qs

from hub import guest

BRAND_PRIVATE = "Joey"
BRAND_MEDIA = "Joey Media"
TV_COOKIE = "tv"
TV_COOKIE_MAX_AGE = 31_536_000          # 1 year
SETUP_COOKIE = "jm_setup"               # the Set up Jellyfin card was dismissed (Q39)
SETUP_COOKIE_MAX_AGE = 31_536_000
SETUP_DONE = "done"                     # `?setup=done` on the guest home dismisses the card


def is_guest(request=None) -> bool:
    """Jinja `guest(request)`: True on the media front (every visitor there is a guest surface viewer, B. included)."""
    return guest.is_media()


def guest_allows(path: str, method: str = "GET") -> bool:
    """Jinja `guest_allows(path)`: whether a link / form to `path` may be drawn - always on the private front, on the
    media front exactly when hub.guest.allows() serves it (query and fragment ignored)."""
    if not guest.is_media():
        return True
    clean = str(path or "").partition("#")[0].partition("?")[0]
    return guest.allows(method, clean)


def brand() -> str:
    return BRAND_MEDIA if guest.is_media() else BRAND_PRIVATE


def brand_title(text) -> str:
    """The `brand_title` filter on base.html's <title> (Q32): on the media front a trailing " · Joey" (or a bare
    "Joey") becomes " · Joey Media", so the ~30 page titles need no edit. The private front is untouched."""
    text = str(text or "").strip()
    if not guest.is_media():
        return text
    if text in ("", BRAND_PRIVATE):
        return BRAND_MEDIA
    if text.endswith(" · " + BRAND_MEDIA):
        return text
    if text.endswith(" · " + BRAND_PRIVATE):
        return text[: -len(BRAND_PRIVATE)] + BRAND_MEDIA
    return f"{text} · {BRAND_MEDIA}"


def guest_home() -> str:
    """The guest home `/a/<shelves id>` (the same value as /healthz `home`), '/' without one."""
    return guest.home_path() or "/"


# ---- TV mode ----

def _secure() -> str:
    from hub import guest_auth
    return "; Secure" if guest_auth.secure_cookies() else ""


def tv_choice(query_string: bytes | str | None) -> str | None:
    """'1' / '0' from a `?tv=` query, else None."""
    raw = query_string.decode("latin-1") if isinstance(query_string, bytes) else str(query_string or "")
    value = (parse_qs(raw).get("tv") or [None])[-1]
    return value if value in ("0", "1") else None


def tv_cookie_header(choice: str) -> str:
    if choice == "1":
        return f"{TV_COOKIE}=1; Max-Age={TV_COOKIE_MAX_AGE}; Path=/{_secure()}; SameSite=Lax"
    return f"{TV_COOKIE}=; Max-Age=0; Path=/{_secure()}; SameSite=Lax"


def wrap_tv_send(scope, send):
    """GuestGate's hook: on the media front a `?tv=0|1` request's response carries the Set-Cookie that persists the
    choice (whatever the response is - a page, the 404 page, the 303 to sign-in). Other requests: `send` unchanged."""
    choice = tv_choice(scope.get("query_string", b""))
    if choice is None:
        return send
    cookie = tv_cookie_header(choice).encode("latin-1")

    async def send_with_cookie(message):
        if message["type"] == "http.response.start":
            message.setdefault("headers", []).append((b"set-cookie", cookie))
        await send(message)

    return send_with_cookie


def tv_mode(request) -> bool:
    """Jinja `tv_mode(request)`: the 10-foot styling is on for this request (media front only)."""
    if request is None or not guest.is_media():
        return False
    if guest.TV_UA_TOKEN in (request.headers.get("user-agent") or ""):
        return True
    choice = tv_choice(request.scope.get("query_string", b""))
    if choice is not None:
        return choice == "1"
    return request.cookies.get(TV_COOKIE) == "1"


# ---- the Set up Jellyfin card (Q39) ----

def setup_card(request, public_url: str | None) -> dict | None:
    """The card's context on the guest Overview - the server address (JELLYFIN_PUBLIC_URL, port verbatim) and the
    dismiss link - or None: not the media front, no public URL, already dismissed (cookie) or being dismissed now."""
    if not guest.is_media() or not public_url:
        return None
    if request.cookies.get(SETUP_COOKIE) == "1" or request.query_params.get("setup") == SETUP_DONE:
        return None
    return {"server": public_url, "done_href": f"{guest_home()}?setup={SETUP_DONE}"}


def setup_dismissed_now(request) -> bool:
    return guest.is_media() and request.query_params.get("setup") == SETUP_DONE


def setup_cookie_header() -> str:
    return f"{SETUP_COOKIE}=1; Max-Age={SETUP_COOKIE_MAX_AGE}; Path=/{_secure()}; SameSite=Lax"


# ---- the TV shell player (JY-057) ----

TV_PLAYER_MIN_CODE = 2026102701   # Joey TV 1.0.3: the first shell with its own player
TV_PLAYER_MARK = "player=joey"    # the fragment parameter the shell's UrlPolicy turns into its player
_TV_APP = re.compile(r"JoeyTV/\d+\.\d+\.\d+ \((\d{10})\)")


def tv_app_code(request) -> int | None:
    """The Joey TV shell's versionCode from its user agent (` JoeyTV/<semver> (<versionCode>)`), else None."""
    m = _TV_APP.search((request.headers.get("user-agent") or "") if request is not None else "")
    return int(m.group(1)) if m else None


def _viewer_owner(request) -> str | None:
    from hub.identity import resolve_identity
    return resolve_identity(request).owner


def tv_player(request) -> bool:
    """Play on this page opens the shell's own player: the flag is on, the media front, the shell's user agent (never the
    `tv=1` cookie) at TV_PLAYER_MIN_CODE or later, and `you` or `her` is signed in. Else today's Jellyfin hand-off."""
    from hub import player_api
    if request is None or not guest.is_media() or not player_api.enabled():
        return False
    code = tv_app_code(request)
    if code is None or code < TV_PLAYER_MIN_CODE:
        return False
    return _viewer_owner(request) in player_api.HOUSEHOLD


def tv_play_href(href: str | None) -> str | None:
    """A Jellyfin deep link (`.../web/#/details?id=...`) with the player mark as one more fragment parameter."""
    return f"{href}&{TV_PLAYER_MARK}" if href else href
