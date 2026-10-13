"""Poster proxy `GET /img/{ref}` (2026-10-05) — the hub's second live-call exception
(the first is none: everything else reads snapshots). Connectors emit opaque refs
(`jf:<id>`, `jfb:<id>`, `radarr:<id>`, `sonarr:<id>`, `tmdb:<path>`); this fetches the
art with the same env keys the connectors use, caches it on disk and never lets an
upstream problem surface: any failure serves a generated fallback card instead.
Warnings name the ref kind and a status/type only — never a URL or key.
"""

from __future__ import annotations

import contextlib
import hashlib
import html
import logging
import os
import re
import tempfile
import time
from pathlib import Path

import requests
from fastapi import APIRouter, Response

log = logging.getLogger("hub.images")
router = APIRouter()

SIZES = (120, 240, 400, 600, 1280)
DEFAULT_SIZE = 400
TMDB_WIDTH = {120: "w185", 240: "w342", 400: "w500", 600: "w780", 1280: "w1280"}  # TMDB serves w1280; "original" is multi-MB
TIMEOUT = 8
MAX_BYTES = 5 * 1024 * 1024
CHUNK = 64 * 1024
CACHE_TTL = 30 * 24 * 3600
HIT_CACHE = "public, max-age=2592000, immutable"
FALLBACK_CACHE = "public, max-age=3600"
EXT = {"image/jpeg": ".jpg", "image/jpg": ".jpg", "image/png": ".png", "image/webp": ".webp",
       "image/gif": ".gif"}
MIME = {ext: mime for mime, ext in EXT.items() if mime != "image/jpg"}

REF_RE = re.compile(r"^(?:(jf|jfb|radarr|sonarr):([A-Za-z0-9-]+)|(tmdb):(/[A-Za-z0-9_-]+\.(?:jpg|png)))$")


def cache_dir() -> Path:
    return Path(os.environ.get("IMG_CACHE_DIR", "/data/cache/img"))


def fallback_letters(title) -> str:
    """The fallback card's text: the title's first two letters/digits, upper-cased ("" when none). Templates pass
    this, not the whole title, as `t=` (Jinja global `img_letters`), so one placeholder URL — cached for an hour —
    serves every title sharing those letters instead of one URL per title (N-33)."""
    return "".join(c for c in str(title or "") if c.isalnum())[:2].upper()


def fallback_svg(title: str = "") -> bytes:
    """Area-neutral dark 2:3 card with the title's first two letters; no external request."""
    letters = fallback_letters(title) or "·"
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 300" role="img">'
        '<rect width="200" height="300" fill="#18181b"/>'
        '<text x="100" y="168" text-anchor="middle" font-family="system-ui, sans-serif" font-size="64" '
        f'font-weight="600" fill="#52525b">{html.escape(letters)}</text></svg>'
    ).encode("utf-8")


def _fallback(title: str) -> Response:
    return Response(fallback_svg(title), media_type="image/svg+xml",
                    headers={"Cache-Control": FALLBACK_CACHE})


def _env(*names: str) -> list[str] | None:
    values = [os.environ.get(n, "").strip() for n in names]
    return values if all(values) else None


def _upstreams(kind: str, ident: str, h: int) -> list[tuple[str, dict, dict]] | None:
    """(url, params, headers) candidates in order, or None when the env isn't set."""
    if kind in ("jf", "jfb"):
        env = _env("JELLYFIN_URL", "JELLYFIN_API_KEY")
        if not env:
            return None
        url, key = env[0].rstrip("/"), env[1]
        headers = {"Authorization": f"MediaBrowser Token={key}"}
        if kind == "jf":
            return [(f"{url}/Items/{ident}/Images/Primary", {"maxHeight": h, "quality": 90}, headers)]
        return [(f"{url}/Items/{ident}/Images/Backdrop/0", {"maxWidth": 1280, "quality": 85}, headers)]
    if kind in ("radarr", "sonarr"):
        env = _env(f"{kind.upper()}_URL", f"{kind.upper()}_API_KEY")
        if not env:
            return None
        base = f"{env[0].rstrip('/')}/api/v3/mediacover/{ident}"
        return [(f"{base}/{name}", {"apikey": env[1]}, {}) for name in ("poster-500.jpg", "poster.jpg")]
    return [(f"https://image.tmdb.org/t/p/{TMDB_WIDTH[h]}{ident}", {}, {})]  # tmdb: no key


def _reason(exc: Exception) -> str:
    return type(exc).__name__  # requests exception text embeds the URL — never use it


def _read_capped(resp) -> bytes | None:
    """The body, streamed with a running cap: None as soon as it passes MAX_BYTES (a declared
    Content-Length over the cap is refused unread), so a huge upstream image is never held in RAM."""
    try:
        if int(resp.headers.get("content-length") or 0) > MAX_BYTES:
            return None
    except (TypeError, ValueError):
        pass
    chunks = getattr(resp, "iter_content", None)
    body = bytearray()
    for chunk in (chunks(CHUNK) if chunks else (resp.content,)):
        body += chunk or b""
        if len(body) > MAX_BYTES:
            return None
    return bytes(body)


def _fetch(kind: str, ident: str, h: int) -> tuple[bytes, str] | None:
    candidates = _upstreams(kind, ident, h)
    if candidates is None:
        return None
    reason = "no answer"
    for url, params, headers in candidates:
        try:
            resp = requests.get(url, params=params or None, headers=headers or None, timeout=TIMEOUT,
                                stream=True)
        except Exception as exc:
            reason = _reason(exc)
            break  # an unreachable app won't answer the second candidate either
        try:
            ctype = str(resp.headers.get("content-type", "")).split(";")[0].strip().lower()
            if resp.status_code != 200:
                reason = f"HTTP {resp.status_code}"
                continue  # radarr/sonarr: poster-500.jpg missing -> try poster.jpg
            if ctype not in EXT:
                reason = "not an image"
                break
            body = _read_capped(resp)
            if body is None:
                reason = "image too large"
                break
            return body, EXT[ctype]
        except Exception as exc:  # a connection dropped mid-body
            reason = _reason(exc)
            break
        finally:
            close = getattr(resp, "close", None)
            if close:
                close()
    log.warning("image upstream failed (%s: %s)", kind, reason)
    return None


def _cache_path(stem: str) -> Path | None:
    """The cached file for a stem still inside CACHE_TTL (any image extension), else None. A stat, not a read."""
    folder = cache_dir()
    for ext in MIME:
        path = folder / (stem + ext)
        try:
            if time.time() - path.stat().st_mtime < CACHE_TTL:
                return path
        except OSError:
            continue
    return None


def _cached(stem: str) -> tuple[bytes, str] | None:
    path = _cache_path(stem)
    try:
        return (path.read_bytes(), path.suffix) if path else None
    except OSError:
        return None


def _store(stem: str, ext: str, body: bytes) -> None:
    folder = cache_dir()
    tmp = None
    try:
        folder.mkdir(parents=True, exist_ok=True)
        # a temp name unique per call (H-62): request threads and the warm-up share one pid, and two
        # fetches of one ref must never write the same temp file and publish a half-written image
        fd, tmp = tempfile.mkstemp(dir=folder, prefix=stem[:16] + ".", suffix=".tmp")
        with os.fdopen(fd, "wb") as fh:
            fh.write(body)
        os.replace(tmp, folder / (stem + ext))  # atomic — a reader never sees a half-written image
    except OSError as exc:
        log.warning("image cache write failed (%s)", _reason(exc))
        if tmp:
            with contextlib.suppress(OSError):
                os.unlink(tmp)


@router.get("/img/{ref:path}")
def image(ref: str, h: str = "", t: str = ""):
    title = t[:80]
    if ref == "none":
        return _fallback(title)
    match = REF_RE.match(ref)
    if not match:
        return Response("Not found", status_code=404, media_type="text/plain")
    kind = match.group(1) or match.group(3)
    ident = match.group(2) or match.group(4)
    size = int(h) if h.isdigit() and int(h) in SIZES else DEFAULT_SIZE

    stem = hashlib.sha256(f"{ref}|{size}".encode("utf-8")).hexdigest()
    hit = _cached(stem)
    if hit is None:
        got = _fetch(kind, ident, size)
        if got is None:
            return _fallback(title)
        _store(stem, got[1], got[0])
        hit = got
    return Response(hit[0], media_type=MIME[hit[1]], headers={"Cache-Control": HIT_CACHE})


def warm(ref: str, h: int = DEFAULT_SIZE) -> str:
    """Pre-fetch one ref into the disk cache exactly as GET /img/{ref}?h= would (media-speed warm-up).
    -> 'cached' (already there), 'fetched', or 'skipped' (bad ref / size, no env, upstream failure)."""
    match = REF_RE.match(ref or "")
    if not match or h not in SIZES:
        return "skipped"
    stem = hashlib.sha256(f"{ref}|{h}".encode("utf-8")).hexdigest()
    if _cache_path(stem):  # a stat, not a read: the warm-up re-checks hundreds of refs each pass
        return "cached"
    got = _fetch(match.group(1) or match.group(3), match.group(2) or match.group(4), h)
    if got is None:
        return "skipped"
    _store(stem, got[1], got[0])
    return "fetched"
