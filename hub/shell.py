"""The page shell every router shares (T3 hub core, 2026-10-09): ONE Jinja2Templates instance and the
static asset version. Routers import `templates` from here instead of building their own env, so every
page carries the same globals (H-31: Discover pages once rendered `control-surface.css?v=` empty).

Globals that are functions of hub.main (media_nav, identity, score_for, ...) are set on this env by
hub.main at import. Templates are not re-stat'ed on every render (`auto_reload=False`) unless
HUB_DEV=1 (local template editing).
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from urllib.parse import parse_qs

from fastapi.templating import Jinja2Templates
from starlette.datastructures import MutableHeaders
from starlette.middleware.gzip import GZipMiddleware

from hub.images import fallback_letters

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


templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.auto_reload = dev_mode()
templates.env.globals["static_v"] = _static_version()
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


class CacheHeaders:
    """Pure ASGI (no BaseHTTPMiddleware): sets `cache_control()` on the response start message."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path, query = scope.get("path", ""), scope.get("query_string", b"")

        async def send_with_cache(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(raw=message.setdefault("headers", []))
                value = cache_control(path, query, message["status"], headers.get("content-type", ""))
                if value:
                    headers["Cache-Control"] = value
            await send(message)

        await self.app(scope, receive, send_with_cache)


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
