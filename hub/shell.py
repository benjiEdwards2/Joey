"""The page shell every router shares (T3 hub core, 2026-10-09): ONE Jinja2Templates instance and the
static asset version. Routers import `templates` from here instead of building their own env, so every
page carries the same globals (H-31: Discover pages once rendered `control-surface.css?v=` empty).

W3 (2026-10-09, H-44 / H-45 / H-22 / M-18 / M-30): also the module every router imports instead of hub.main —
the registry holder, the per-request snapshot read, the owner view, the feeds status line, the detail-source
lookup, and `render_page` / `not_found_page` (the one base page context and the one 404).

Globals that are functions of the Media helpers (media_nav, score_for, ...) are set on this env by
hub.media_home at import. Templates are not re-stat'ed on every render (`auto_reload=False`) unless
HUB_DEV=1 (local template editing).
"""

from __future__ import annotations

import hashlib
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs

from fastapi import Request
from fastapi.templating import Jinja2Templates
from starlette.datastructures import Headers, MutableHeaders
from starlette.middleware.gzip import GZipMiddleware

from hub.identity import Identity, resolve_identity
from hub.ids import areas_path, home_now
from hub.images import fallback_letters
from hub.registry import Registry, load_registry
from hub.store import get_snapshots as _read_snapshots, tile_state

HUB_DIR = Path(__file__).resolve().parent
STATIC_DIR = HUB_DIR / "static"
TEMPLATES_DIR = HUB_DIR / "templates"


def _static_version(root: Path = STATIC_DIR) -> str:
    """Content hash of the whole static tree (names + bytes), appended as ?v= to every static URL, so a
    deploy that changes ANY asset (CSS, htmx, a logo) is never painted with a browser's cached copy —
    those URLs are served `immutable` (field note 2026-09-11, bit us 2026-10-05)."""
    digest = hashlib.sha1()
    try:
        for path in sorted(p for p in root.rglob("*") if p.is_file()):
            digest.update(path.relative_to(root).as_posix().encode("utf-8") + b"\0")
            digest.update(path.read_bytes())
    except OSError:
        return "0"
    return digest.hexdigest()[:8]


def dev_mode() -> bool:
    return os.environ.get("HUB_DEV", "").strip() == "1"


DEFAULT_WEATHER_PLACE = "Newport VIC"


def weather_place() -> str:
    """Jinja global `weather_place()`: the place the weather labels name (WEATHER_PLACE in .env, next to the
    WEATHER_LAT/LON the connector and the radar read; H-36)."""
    return os.environ.get("WEATHER_PLACE", "").strip() or DEFAULT_WEATHER_PLACE


templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.auto_reload = dev_mode()
templates.env.globals["static_v"] = _static_version()
templates.env.globals["weather_place"] = weather_place
templates.env.globals["img_letters"] = fallback_letters  # /img/...?t= carries letters only, never a whole title


# ---- response headers (T3, 2026-10-09: H-56, N-48, N-49) ----

STATIC_PREFIX = "/static/"
STATIC_IMMUTABLE = "public, max-age=31536000, immutable"   # a ?v= URL changes whenever its bytes do
STATIC_SHORT = "public, max-age=3600"                       # manifests, un-versioned files
PAGE_NO_STORE = "no-store"


def cache_control(path: str, query: bytes, status: int, content_type: str) -> str | None:
    """The Cache-Control a response gets, or None to leave it alone. Static files: `immutable` for a
    content-versioned URL (`?v=`), an hour otherwise (only on 200/304 — an error is never pinned). HTML pages:
    `no-store` — Back/Forward is navigation only (2026-10-08), so neither bfcache, HTTP cache nor a proxy can
    show a page as it was before a Follow / Request / Remove. /img keeps its own headers."""
    if path.startswith(STATIC_PREFIX):
        if status not in (200, 304):
            return None
        return STATIC_IMMUTABLE if parse_qs(query.decode("latin-1")).get("v") else STATIC_SHORT
    if content_type.startswith("text/html"):
        return PAGE_NO_STORE
    return None


# One request line per page/action (H-58, N-28): never for the healthcheck, static files or posters, and the
# signed-in address is never logged — only the owner word. uvicorn's own access log is off (hub/main.py).
QUIET_PREFIXES = ("/healthz", STATIC_PREFIX, "/img/")
request_log = logging.getLogger("hub")


class _HeaderView:
    def __init__(self, scope):
        self.headers = Headers(scope=scope)


def owner_word(scope) -> str:
    """'you' / 'her' / 'none' (not signed in) — what the request log says instead of the email."""
    return resolve_identity(_HeaderView(scope)).owner or "none"


class ShellMiddleware:
    """The one pure ASGI middleware (H-59: the two BaseHTTPMiddleware layers merged): sets `cache_control()` on
    the response start message and writes the request log line."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path, query = scope.get("path", ""), scope.get("query_string", b"")
        status = [500]

        async def send_with_cache(message):
            if message["type"] == "http.response.start":
                status[0] = message["status"]
                headers = MutableHeaders(raw=message.setdefault("headers", []))
                value = cache_control(path, query, message["status"], headers.get("content-type", ""))
                if value:
                    headers["Cache-Control"] = value
            await send(message)

        try:
            await self.app(scope, receive, send_with_cache)
        finally:
            if not path.startswith(QUIET_PREFIXES):
                request_log.info("%s %s owner=%s -> %d", scope.get("method", "-"), path, owner_word(scope), status[0])


# Already-compressed bodies (posters, icons, fonts, radar PNGs) skip gzip: no gain, NAS CPU spent.
NO_GZIP_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".woff2", ".ico")
GZIP_MIN_BYTES = 1024
GZIP_LEVEL = 6


class Compress:
    """GZipMiddleware(minimum_size=1024) for text (pages, CSS, JS, JSON, SVG); /img/ and binary files pass."""

    def __init__(self, app):
        self.plain = app
        self.gzip = GZipMiddleware(app, minimum_size=GZIP_MIN_BYTES, compresslevel=GZIP_LEVEL)

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "") if scope["type"] == "http" else ""
        binary = path.startswith("/img/") or path.lower().endswith(NO_GZIP_SUFFIXES)
        await (self.plain if not path or binary else self.gzip)(scope, receive, send)


# ---- the registry (areas.yaml): loaded once at startup by the lifespan (hub/main.py) ----

log = request_log
registry: Registry | None = None
registry_loaded_at: str | None = None


def load_areas() -> Registry:
    """Load the registry from AREAS_PATH (hub.ids.areas_path), failing fast with the aggregated violation list."""
    global registry, registry_loaded_at
    path = areas_path()
    registry = load_registry(path)  # ValueError here aborts startup by design
    registry_loaded_at = datetime.now(timezone.utc).isoformat()
    log.info("registry loaded from %s: %d areas", path, len(registry.areas))
    return registry


def visible_areas() -> list:
    """The tab bar's areas (parked areas left out)."""
    return registry.visible_areas


def get_snapshots(snapshot_dir=None, request=None):
    """Every envelope (hub.store), with resume items just marked watched / reset left out of the jellyfin
    `up_next` lists until a newer sweep (media_resume, 2026-10-08) — so every shelf, hero and list drops them.
    With `request`: read once per request — the first call keeps it on request.state.snaps, where the page's
    builders and media_frame find it (H-48)."""
    from hub import media_resume  # function-level: media_resume's own imports reach back into this module

    state = getattr(request, "state", None)
    cached = getattr(state, "snaps", None) if state is not None else None
    if cached is not None:
        return cached
    snaps = media_resume.apply_hidden(_read_snapshots(snapshot_dir), "jellyfin")
    if state is not None:
        state.snaps = snaps
    return snaps


# ---- who is looking: identity and the owner view ----

def identity_of(request) -> Identity:
    """Template global `identity(request)`: the signed-in user (name/email/owner), cached per request."""
    state = getattr(request, "state", None)
    cached = getattr(state, "identity", None) if state is not None else None
    if cached is None:
        cached = resolve_identity(request)
        if state is not None:
            state.identity = cached
    return cached


templates.env.globals["identity"] = identity_of

OWNER_VIEWS = ("both", "you", "her")
OWNER_COOKIE = "owner_view"
OWNER_COOKIE_MAX_AGE = 30 * 24 * 3600  # 30 days, per device (WP19)


def resolve_owner_view(request: Request) -> tuple[str, bool]:
    """Signed in (Access header): the view IS the signed-in owner — query and cookie are
    ignored and no cookie is set (2026-10-06). Not signed in (local dev, tests): query param
    wins (and sets the cookie); else cookie; else 'both'.

    Semantics per Q9 (answered 2026-08-25): you = you+shared, her = her+shared.
    Returns (view, came_from_query).
    """
    who = resolve_identity(request)
    if who.owner:
        return who.owner, False
    q = request.query_params.get(OWNER_COOKIE)
    if q in OWNER_VIEWS:
        return q, True
    c = request.cookies.get(OWNER_COOKIE)
    return (c if c in OWNER_VIEWS else "both"), False


def owner_visible(tile, view: str) -> bool:
    return view == "both" or tile.owner.value == "shared" or tile.owner.value == view


def _maybe_set_cookie(response, view: str, from_query: bool):
    if from_query:
        response.set_cookie(OWNER_COOKIE, view, max_age=OWNER_COOKIE_MAX_AGE, samesite="lax")
    return response


# Hub greeting (Apex shell, 2026-10-06) and the film page's "ends at": wall-clock at home, not the container's zone
# (hub/ids.py). A module name of its own so tests can reach / monkeypatch it.
_now_home = home_now


# ---- registry lookups the pages share ----

def build_status(snaps) -> dict:
    """The hub page's "Feeds N/M live" line (H-32): the feeds the VISIBLE areas read (parked areas don't count). A
    feed is live when its tiles read fresh or stale (tile_state — an error envelope without data is not); `stale`
    names the first visible area of every feed whose tile has gone stale."""
    tiles: dict[str, list] = {}   # connector id -> [(area name, tile)] over visible areas
    for a in registry.visible_areas:
        for t in a.tiles:
            if t.snapshot:
                tiles.setdefault(t.snapshot, []).append((a.name, t))
    states = {cid: [tile_state(t, snaps)["state"] for _, t in rows] for cid, rows in tiles.items()}
    return {
        "feeds_total": len(tiles),
        "feeds_ok": sum(1 for st in states.values() if st[0] in ("fresh", "stale")),
        "stale": sorted({tiles[cid][0][0] for cid, st in states.items() if "stale" in st}),
    }


def find_detail_source(snapshot_id, snaps, detail=None) -> dict | None:
    """The page behind a `detail` tile: the first registry tile reading the
    snapshot (the one whose `detail` route matches, when several tiles share a
    snapshot), its area and the area's first LINK tile (the app
    launcher, as find_media resolves it). None when no tile reads the snapshot."""
    for a in registry.areas:
        for t in a.tiles:
            if t.snapshot == snapshot_id and (detail is None or t.detail == detail):
                snap = snaps.get(snapshot_id)
                href = next((x.href for x in a.tiles if x.tier.value == "link"), None)
                return {"tile": t, "st": tile_state(t, snaps),
                        "data": snap.data if snap else {}, "href": href}
    return None


def _deep_link(link, jf_id, server_id) -> str | None:
    """Jellyfin item page for a row; None rather than a fabricated link."""
    if not link or not jf_id:
        return None
    url = f"{link.rstrip('/')}/web/#/details?id={jf_id}"
    return url + (f"&serverId={server_id}" if server_id else "")


# ---- the one page render (H-22, M-18) ----

def render_page(request: Request, template: str, ctx: dict, *, active_id=None, status: int = 200):
    """A full page in the shell: the tab bar's areas and the active tab, then the page's own context."""
    return templates.TemplateResponse(request, template, {
        "areas": registry.visible_areas, "active_id": active_id, **ctx,
    }, status_code=status)


def not_found_page(request: Request, text: str = "No page here"):
    """The one 404 page."""
    return render_page(request, "404.html", {"missing_text": text}, status=404)
