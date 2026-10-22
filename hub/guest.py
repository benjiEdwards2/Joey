"""The guest front (Joey TV WP-B1, 2026-10-21): one image, two processes. `joey-hub` runs with JOEY_FRONT unset
(= `private`, today's Joey behind Cloudflare Access); `joey-media` runs the same `life-hub` image with
JOEY_FRONT=media behind the tunnel hostname media.joeyhome.net (no Access policy, its own sign-in from WP-B2).

This module is the single source of truth for what the media front serves:

* `front()` reads JOEY_FRONT on every call: unset/blank = `private`, `media`, anything else = ValueError (the
  lifespan calls it first, so a typo stops the container at startup instead of serving the wrong front).
* GUEST / PRIVATE / RESERVED are tables of (method, path template), the templates spelled exactly as the routes are
  declared. HEAD counts as GET. `allows()` is deny-by-default: a request is allowed only when a GUEST template matches,
  no PRIVATE or RESERVED template matches, or it is the guest home. RESERVED entries are denied until their WP moves
  them to GUEST (D-P7); none is left: WP-B4 (2026-10-21) moved GET + POST /media/title/{kind}/{tmdb_id}/request to
  GUEST (a friend's request is sent as their own Seerr user and waits for approval, hub/media_guest_requests.py; the
  admin request paths - Requests, Remove, Follow, Search now, Quality - stay PRIVATE, Q19). WP-B2 moved the sign-in routes
  (exactly GET /signin, POST /signin/qc/start, GET /signin/qc/poll, POST /signin/password, POST /signout) to GUEST and
  PUBLIC; nothing else under /signin is served. WP-B8 (2026-10-21) moved GET /app and GET /app/{rest:path} (the TV
  app download + version.json, hub/tv_app.py) to GUEST and PUBLIC (Q37); hub/tv_app.py 404s anything but its files.
* The guest home is `/a/<id of the registry's first layout: shelves area>`, resolved at runtime (no area name here).
* Every route of hub.main.app must sit in exactly one table: tests/hub/test_guest_routes.py fails the suite on an
  unclassified route, naming it. A new route is PRIVATE until someone decides otherwise.
* Section / tab visibility on the media front is derived from `allows()` (`href_allowed`), never a second list.
* `GuestGate` (ASGI) enforces it: registered FIRST in hub.main, so it is the innermost middleware and the request
  log line (hub.shell.ShellMiddleware) sees its 404 / 303 and the identity it stored.

Media front: `/` -> 303 guest home; not allowed -> the ordinary Joey 404 page, rendered for a fixed neutral path so
every denied or unknown path gets byte-identical HTML (no hint, DECISIONS C); PUBLIC paths pass with no identity and
no Jellyfin call; otherwise the session cookie is resolved (hub.guest_auth, in a worker thread): valid -> the identity
is stored at scope['state']['identity'] and its Jellyfin user bound for the request (media_jellyfin.bind_viewer, P3);
no session -> 303 /signin?next=...; a session Jellyfin refused -> 303 /signin with the cookie cleared; Jellyfin
unreachable -> a 503 page with no data, the cookie kept. An htmx request gets `HX-Redirect: /signin` (200) instead of
a 303 the XHR would follow silently. The media front ignores
Cf-Access-Authenticated-User-Email entirely (hub.identity), and hub.access_jwt.AccessGate passes it through by design:
joey-media never carries ACCESS_* (Q23) and its visitors never pass Cloudflare Access.
Private front: pass-through, except the Host guard (Q25a): a request whose Host is MEDIA_PUBLIC_HOST (default IN CODE
media.joeyhome.net) gets the 404 page, so a Zero Trust ingress typo can never publish private Joey ungated.

Frozen interfaces (§4 rule 9; WP-B2 / WP-B7 build on them):
* `hub.identity.Identity(owner, name, email=None, jf_user_id=None, jf_token=None)`.
* `TV_UA_TOKEN = "JoeyTV/"`: the TV shell's user agent carries ` JoeyTV/<semver> (<versionCode>)` (D-P8); the server
  matches the substring.
* The owner-key format is NOT defined here: `OWNER_KEY_RE` is imported from hub.identity (WP-A2).

Identity: the session cookie (hub.guest_auth, WP-B2). `identity_provider` (a callable scope -> Identity | None) stays
as the test seam and wins when set. The dev seam GUEST_DEV_OWNER (Q31) is honoured only when HUB_DEV=1 AND the front
is media; tests/deploy/test_joey_media_service.py forbids it in compose. Owners are frozen as OWNER_KEY_RE keys:
hub.media_db.owner_of raises on a malformed `jf:` owner, so a dev owner must be `jf:<32 lowercase hex>`.
"""
from __future__ import annotations

import dataclasses
import logging
import os
from functools import lru_cache
from typing import Callable
from urllib.parse import quote

from starlette.datastructures import Headers
from starlette.requests import Request
from starlette.routing import compile_path

from hub.identity import OWNER_KEY_RE, Identity  # noqa: F401 - OWNER_KEY_RE re-exported, never redefined (WP-A2)

log = logging.getLogger("hub.guest")

PRIVATE_FRONT = "private"
MEDIA_FRONT = "media"
FRONTS = (PRIVATE_FRONT, MEDIA_FRONT)
TV_UA_TOKEN = "JoeyTV/"
DEFAULT_MEDIA_PUBLIC_HOST = "media.joeyhome.net"
NOT_FOUND_PATH = "/not-found"   # the path every media-front 404 is rendered for (byte-identical pages)
DEV_NAME = "Dev friend"


def front() -> str:
    """'private' (JOEY_FRONT unset or blank) or 'media'. Any other value raises ValueError."""
    value = (os.environ.get("JOEY_FRONT") or "").strip().lower() or PRIVATE_FRONT
    if value not in FRONTS:
        raise ValueError("JOEY_FRONT must be unset, private or media")
    return value


def is_media() -> bool:
    return front() == MEDIA_FRONT


def media_public_host() -> str:
    return (os.environ.get("MEDIA_PUBLIC_HOST") or "").strip().lower() or DEFAULT_MEDIA_PUBLIC_HOST


# ---- the tables: (method, path template), templates exactly as the routes declare them ----

def _each(methods: str, *paths: str) -> tuple:
    return tuple((m, p) for p in paths for m in methods.split())


SIGNIN: tuple = (("GET", "/signin"), ("POST", "/signin/qc/start"), ("GET", "/signin/qc/poll"),
                 ("POST", "/signin/password"), ("POST", "/signout"))   # WP-B2: hub/guest_signin.py
TV_APP: tuple = (("GET", "/app"), ("GET", "/app/{rest:path}"))   # WP-B8: hub/tv_app.py, public per Q37

_MOVIES_TV = tuple(f"/media/{s}{tail}" for s in ("movies", "tv")
                   for tail in ("", "/watchlist", "/tonight", "/to-rate", "/awards",
                                "/awards/part/categories", "/awards/part/rows"))

GUEST: tuple = (
    *_each("GET", *_MOVIES_TV),
    *_each("GET", "/media/diary", "/media/history"),   # Diary + To rate (Q18); the play log stays PRIVATE
    *_each("GET", "/media/discover", "/media/discover/search", "/media/discover/service/{provider_id}"),
    *_each("GET", "/media/title/{kind}/{tmdb_id}", "/media/title/{kind}/{tmdb_id}/part/{name}",
           "/media/title/tv/{tmdb_id}/season/{n}"),
    *_each("GET", "/media/item/{jf_id}", "/media/item/{jf_id}/part/{name}", "/media/person/{person_id}"),
    *_each("GET", "/media/search", "/img/{ref:path}", "/healthz", "/static/{path:path}"),
    ("POST", "/media/rate"), ("DELETE", "/media/rate/{item_key}"), ("POST", "/media/rate/{item_key}/delete"),
    *_each("POST", "/media/rate/skip", "/media/rate/skip-show", "/media/rate/unskip"),   # the To rate inbox's own buttons
    ("POST", "/media/log"), ("POST", "/media/settings/rating_level"),
    *SIGNIN,
    *TV_APP,
    *_each("POST", "/media/watchlist/add", "/media/watchlist/remove"),
    *_each("POST", *(f"/media/resume/{{jf_id}}/{a}" for a in ("watched", "unwatched", "reset", "hide"))),
    # WP-B4: Request, as the friend's own Seerr user (X-Api-User) and always pending (hub/media_guest_requests.py)
    *_each("GET POST", "/media/title/{kind}/{tmdb_id}/request"),
)

PRIVATE: tuple = (
    *_each("GET", "/", "/server", "/a/{area_id}", "/whoami", "/weather"),   # the guest home is a runtime exception
    *_each("GET", "/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"),
    *_each("GET", "/server/updates/all/run", "/server/updates/{name}/run", "/server/stack/run"),
    *_each("POST", "/server/updates/all/run", "/server/updates/{name}/run", "/server/updates/{name}/ignore",
           "/server/updates/{name}/unignore", "/server/stack/run"),
    *_each("GET", "/media/apps", "/media/playing", "/media/downloads", "/media/library", "/media/requests",
           "/media/server/history", "/media/following"),
    ("POST", "/media/requests/{rid}/remove"),
    *_each("POST", "/media/follow/{kind}/{tmdb_id}", "/media/follow/{kind}/{tmdb_id}/unfollow"),
    *_each("GET POST", "/media/arr/sweep", "/media/title/{kind}/{tmdb_id}/quality",
           "/media/upgrades/why/{app}/{arr_id}"),
    ("GET", "/media/title/{kind}/{tmdb_id}/arr"),
    *_each("POST", "/media/title/{kind}/{tmdb_id}/search", "/media/title/{kind}/{tmdb_id}/upgrade",
           "/media/upgrades/why/{app}/{arr_id}/grab"),
    *_each("GET", "/media/diary/year", "/media/diary/year/{year}"),   # Wrapped reads the household's history (Q18)
    ("POST", "/media/settings/diary_scope"),   # "Show: Everyone" is hidden for friends (DECISIONS C)
)

RESERVED: tuple = ()   # empty since WP-B4 moved the request route to GUEST; kept for the next route a WP builds dark

# Served without an identity on the media front (everything else that is allowed needs one).
PUBLIC: tuple = (("GET", "/healthz"), ("GET", "/static/{path:path}"), *SIGNIN, *TV_APP)


@lru_cache(maxsize=None)
def _regex(template: str):
    return compile_path(template)[0]


def _matches(table: tuple, method: str, path: str) -> bool:
    return any(m == method and _regex(t).match(path) for m, t in table)


def _verb(method: str) -> str:
    method = (method or "").upper()
    return "GET" if method == "HEAD" else method


def home_path(registry=None) -> str | None:
    """`/a/<id>` of the registry's first `layout: shelves` area, or None without one."""
    from hub import media_nav, shell
    area = media_nav.shelves_area(registry if registry is not None else shell.registry)
    return f"/a/{area.id}" if area else None


def allows(method: str, path: str, registry=None) -> bool:
    """True when the media front serves this request: the guest home, or a GUEST match with no PRIVATE / RESERVED one."""
    verb = _verb(method)
    if verb == "GET" and path == home_path(registry):
        return True
    if _matches(RESERVED, verb, path) or _matches(PRIVATE, verb, path):
        return False
    return _matches(GUEST, verb, path)


def is_public(method: str, path: str) -> bool:
    return _matches(PUBLIC, _verb(method), path)


def href_allowed(href: str, registry=None) -> bool:
    """A nav link's visibility on the media front: its GET is allowed (sections / tabs derive from allows())."""
    return allows("GET", (href or "").partition("?")[0], registry)


# ---- media-mode snapshot scrub (Q22 (c), Q20): ONE point, hub.shell.get_snapshots ----

SNAPSHOT_KEYS: dict = {
    "jellyfin": frozenset({"latest", "library", "movies", "shows", "library_fetched_at", "server_id", "summary"}),
    "jellyseerr": frozenset({"requests"}),
    "arr": frozenset({"arrived", "this_week", "updated", "radarr", "sonarr"}),
}
NESTED_KEYS: dict = {("arr", "radarr"): frozenset({"movies", "missing", "wanted"}),
                     ("arr", "sonarr"): frozenset({"series", "wanted"})}
ROW_DROP: dict = {   # per-row fields removed from list rows: B.'s played state (Q20), the requester's name
    ("jellyfin", "latest"): ("played", "last_played_at", "unplayed"),
    ("jellyfin", "movies"): ("played", "last_played_at", "unplayed"),
    ("jellyfin", "shows"): ("played", "last_played_at", "unplayed"),
    ("jellyseerr", "requests"): ("requested_by",),
}


def _rows(value, drop: tuple):
    if not isinstance(value, list):
        return value
    return [{k: v for k, v in r.items() if k not in drop} if isinstance(r, dict) else r for r in value]


def scrub_data(cid: str, data) -> dict:
    """One envelope's data reduced to the media-mode allow-list (a new dict; the cached envelope is never touched)."""
    keep = SNAPSHOT_KEYS.get(cid)
    if not keep or not isinstance(data, dict):
        return {}
    out = {}
    for key in sorted(keep & set(data)):
        value = data[key]
        nested = NESTED_KEYS.get((cid, key))
        if nested is not None:
            value = {k: v for k, v in value.items() if k in nested} if isinstance(value, dict) else {}
        out[key] = _rows(value, ROW_DROP.get((cid, key), ()))
    return out


def scrub_snapshots(snaps: dict) -> dict:
    """Only jellyfin / jellyseerr / arr survive, each reduced to its key allow-list."""
    return {cid: dataclasses.replace(snap, data=scrub_data(cid, snap.data))
            for cid, snap in snaps.items() if cid in SNAPSHOT_KEYS}


# ---- identity on the media front ----

identity_provider: Callable | None = None   # scope -> Identity | None; WP-B2 sets the session read here


def dev_identity() -> Identity | None:
    """GUEST_DEV_OWNER (Q31) as an identity - only with HUB_DEV=1 on the media front, else None."""
    owner = (os.environ.get("GUEST_DEV_OWNER") or "").strip()
    if not owner or os.environ.get("HUB_DEV", "").strip() != "1" or not is_media():
        return None
    return Identity(owner=owner, name=DEV_NAME)


async def _resolve(scope) -> tuple[str, Identity | None]:
    """(verdict, identity): the test seam, else the dev seam, else the session cookie (hub.guest_auth.resolve_scope,
    which may wait on Jellyfin - run in a worker thread so the event loop never blocks)."""
    if identity_provider is not None:
        ident = identity_provider(scope)
        return ("ok", ident) if ident is not None else ("none", None)
    dev = dev_identity()
    if dev is not None:
        return "ok", dev
    import anyio
    from hub import guest_auth
    return await anyio.to_thread.run_sync(guest_auth.resolve_scope, scope)


def identity_in_scope(scope) -> Identity | None:
    """The identity GuestGate stored for this request (None when it stored none)."""
    state = (scope or {}).get("state") if isinstance(scope, dict) else None
    ident = state.get("identity") if isinstance(state, dict) else None
    return ident if isinstance(ident, Identity) else None


def startup() -> str:
    """Lifespan check (hub.tasks): validates JOEY_FRONT (ValueError) and logs the dev-seam warning once."""
    current = front()
    if current == MEDIA_FRONT and dev_identity() is not None:
        log.warning("guest: GUEST_DEV_OWNER is set (HUB_DEV=1) - every media-front request is signed in as it")
    return current


# ---- the gate ----

async def _redirect(send, location: str, set_cookie: str | None = None, htmx: bool = False) -> None:
    """303 to `location`, or for htmx a 200 carrying `HX-Redirect` (an XHR follows a 303 silently)."""
    headers = [(b"hx-redirect", location.encode("latin-1"))] if htmx else [(b"location", location.encode("latin-1"))]
    headers += [(b"content-length", b"0"), (b"cache-control", b"no-store")]
    if set_cookie:
        headers.append((b"set-cookie", set_cookie.encode("latin-1")))
    await send({"type": "http.response.start", "status": 200 if htmx else 303, "headers": headers})
    await send({"type": "http.response.body", "body": b""})


UNAVAILABLE_HTML = ('<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
                    '<meta name="viewport" content="width=device-width, initial-scale=1"><title>Joey Media</title>'
                    '</head><body style="background:#09090b;color:#e4e4e7;font-family:system-ui,sans-serif;'
                    'padding:2rem"><h1>Joey Media</h1><p>Can\u2019t reach the media server right now. Try again in a '
                    'minute.</p></body></html>').encode("utf-8")


async def unavailable(send) -> None:
    """The 503 while Jellyfin cannot confirm the session: no data, no nav, the cookie untouched."""
    await send({"type": "http.response.start", "status": 503,
                "headers": [(b"content-type", b"text/html; charset=utf-8"), (b"cache-control", b"no-store"),
                            (b"retry-after", b"30"), (b"content-length", str(len(UNAVAILABLE_HTML)).encode())]})
    await send({"type": "http.response.body", "body": UNAVAILABLE_HTML})


async def not_found(scope, receive, send) -> None:
    """The Joey 404 page (hub.shell.not_found_page), rendered for NOT_FOUND_PATH whatever was asked for."""
    from hub import shell
    neutral = {**scope, "path": NOT_FOUND_PATH, "raw_path": NOT_FOUND_PATH.encode(), "query_string": b""}
    response = shell.not_found_page(Request(neutral, receive))
    await response(neutral, receive, send)


def _host_is_media(scope) -> bool:
    host = (Headers(scope=scope).get("host") or "").strip().lower()
    if host.startswith("["):
        return False   # an IPv6 literal is never the public hostname
    return host.partition(":")[0] == media_public_host()


class GuestGate:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        if not is_media():
            if _host_is_media(scope):   # Q25a: private Joey never answers on the public guest hostname
                await not_found(scope, receive, send)
                return
            await self.app(scope, receive, send)
            return
        from hub import media_front   # Joey TV WP-B3: `?tv=1` / `?tv=0` persists TV mode in a cookie (Q34)
        send = media_front.wrap_tv_send(scope, send)
        method, path = scope.get("method", "GET"), scope.get("path", "")
        if path == "/" and _verb(method) == "GET":
            home = home_path()
            if home:
                await _redirect(send, home)
                return
        if not allows(method, path):
            await not_found(scope, receive, send)
            return
        if is_public(method, path):
            await self.app(scope, receive, send)
            return
        verdict, ident = await _resolve(scope)
        if verdict == "ok":
            from hub import media_jellyfin
            scope.setdefault("state", {})["identity"] = ident
            bound = media_jellyfin.bind_viewer(ident.jf_user_id)   # P3: the only Jellyfin identity of this request
            try:
                await self.app(scope, receive, send)
            finally:
                media_jellyfin.reset_viewer(bound)
            return
        if verdict == "unreachable":
            await unavailable(send)
            return
        htmx = Headers(scope=scope).get("hx-request") == "true"
        if verdict == "invalid":
            from hub import guest_auth
            await _redirect(send, "/signin", guest_auth.clear_cookie_header(guest_auth.SESSION), htmx)
            return
        query = scope.get("query_string", b"").decode("latin-1")
        await _redirect(send, "/signin" if htmx else
                        "/signin?next=" + quote(path + ("?" + query if query else ""), safe=""), htmx=htmx)
