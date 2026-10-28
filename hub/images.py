"""Poster proxy `GET /img/{ref}` (2026-10-05) — the hub's second live-call exception
(the first is none: everything else reads snapshots). Connectors emit opaque refs
(`jf:<id>`, `jfb:<id>[/<n>]`, `radarr:<id>`, `sonarr:<id>`, `tmdb:<path>`); this fetches the
art with the same env keys the connectors use, caches it on disk and never lets an
upstream problem surface: any failure serves a generated fallback card instead.
Warnings name the ref kind and a status/type only — never a URL or key.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import html
import logging
import os
import re
import tempfile
import time
import weakref
from pathlib import Path

import anyio
import requests  # noqa: F401 - kept: tests fake upstreams at hub.images.requests (E1: via tests/hub/conftest)

from fastapi import APIRouter, Response

from hub import upstream

log = logging.getLogger("hub.images")
router = APIRouter()

SIZES = (120, 240, 400, 600, 1280)
DEFAULT_SIZE = 400
TMDB_WIDTH = {120: "w185", 240: "w342", 400: "w500", 600: "w780", 1280: "w1280"}  # TMDB serves w1280; "original" is multi-MB
# E1 (2026-10-13): a Jellyfin backdrop (jfb:) is sized by the asked h too - it was 1280 wide whatever h said - so the
# phone backdrop (h=600) is a genuinely smaller file
JF_BACKDROP_WIDTH = {120: 320, 240: 480, 400: 640, 600: 800, 1280: 1280}
TIMEOUT = 8
MAX_BYTES = 5 * 1024 * 1024
CHUNK = 64 * 1024
CACHE_TTL = 30 * 24 * 3600
HIT_CACHE = "public, max-age=2592000, immutable"
FALLBACK_CACHE = "public, max-age=3600"
EXT = {"image/jpeg": ".jpg", "image/jpg": ".jpg", "image/png": ".png", "image/webp": ".webp",
       "image/gif": ".gif"}
MIME = {ext: mime for mime, ext in EXT.items() if mime != "image/jpg"}

_UPSTREAM = {"jf": "jellyfin", "jfb": "jellyfin", "radarr": "arr", "sonarr": "arr", "tmdb": "tmdb"}   # E1: keep-alive

# JY-262 (2026-10-28): `jfb:<id>/<n>` is Jellyfin backdrop n (1-9; plain `jfb:<id>` stays backdrop 0) - the title page
# draws the second TMDB backdrop. Only jfb takes an index.
# JY-262 follow-up (2026-10-28): `jfs:<id>/<1|2>` is the title's stored top-ranked TMDB backdrop 1 or 2 (the local
# poster store), served only with its published `&v=`; otherwise it falls back to Jellyfin backdrop 0 or 1.
REF_RE = re.compile(r"^(?:(jf|radarr|sonarr):([A-Za-z0-9-]+)|(jfb):([A-Za-z0-9-]+(?:/[1-9])?)"
                    r"|(tmdb):(/[A-Za-z0-9_-]+\.(?:jpg|png))|(jfs):([A-Za-z0-9-]+/[12]))$")


def _kind_ident(match) -> tuple[str, str]:
    """(kind, ident) of a REF_RE match."""
    return next((match.group(i), match.group(i + 1)) for i in (1, 3, 5, 7) if match.group(i))


# E1 (2026-10-13): a cold-poster burst must never stall pages. /img is async: a cache hit is read in a short worker
# call; a MISS waits (without holding a thread) for one of MISS_SLOTS upstream slots, then fetches + stores in a
# worker of its own limiter, so the shared threadpool pages use is never filled by slow upstreams. A miss that has
# waited MISS_WAIT_S for a slot gets the fallback card (FALLBACK_CACHE) instead of hanging.
MISS_SLOTS = 6
MISS_WAIT_S = 8.0
_limiters: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()   # event loop -> (slot gate, worker limiter)


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
        item, _, index = ident.partition("/")
        return [(f"{url}/Items/{item}/Images/Backdrop/{index or 0}", {"maxWidth": JF_BACKDROP_WIDTH[h], "quality": 85},
                 headers)]
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
            resp = upstream.session(_UPSTREAM[kind]).get(url, params=params or None, headers=headers or None, timeout=TIMEOUT,
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


def _miss_limiters() -> tuple[anyio.CapacityLimiter, anyio.CapacityLimiter]:
    """This event loop's (slot gate, worker limiter); one pair per loop (tests run several loops)."""
    loop = asyncio.get_running_loop()
    pair = _limiters.get(loop)
    if pair is None:
        pair = _limiters[loop] = (anyio.CapacityLimiter(MISS_SLOTS), anyio.CapacityLimiter(MISS_SLOTS))
    return pair


def _fetch_and_store(stem: str, kind: str, ident: str, size: int) -> tuple[bytes, str] | None:
    """A miss, in a worker thread: re-check the cache (a request ahead in the queue may have fetched it), else fetch
    and store. -> (body, ext) or None (upstream failure)."""
    hit = _cached(stem)
    if hit is not None:
        return hit
    got = _fetch(kind, ident, size)
    if got is not None:
        _store(stem, got[1], got[0])
    return got


async def _miss(stem: str, kind: str, ident: str, size: int) -> tuple[bytes, str] | None | bool:
    """-> (body, ext), None (upstream failure) or False (no slot within MISS_WAIT_S)."""
    gate, workers = _miss_limiters()
    slot = False
    with anyio.move_on_after(MISS_WAIT_S):
        await gate.acquire()   # waits on the event loop, holding no thread
        slot = True
    if not slot:
        log.warning("image upstream busy (%s): fallback served", kind)
        return False
    try:
        return await anyio.to_thread.run_sync(_fetch_and_store, stem, kind, ident, size, limiter=workers)
    finally:
        gate.release()


V_RE = re.compile(r"^[0-9a-f]{6,16}$")   # a store version (media_posters_store.version): hex only, never a path


def _stored(kind: str, ident: str, size: int, v: str) -> Path | None:
    """JY-260 phase 2: the stored, pre-sized Joey poster for `jf:<id>?v=<ver>` (films, series, seasons) when `v` is the
    item's published version, else None - and then /img goes on exactly as before. Joey's pages put `v` on the URL
    (Jinja `img_v`), so a new poster is a new URL and the 30-day immutable cache never pins an old one; a URL with no
    `v` (or a bad one) is never served from the store. `v` is only compared with the `current` file, never used in a
    path. A small read and a stat; never raises."""
    if kind not in ("jf", "jfs") or not V_RE.match(v or ""):
        return None
    from hub import media_posters
    try:
        if kind == "jfs":   # a stored backdrop: one 1280-wide file whatever the height asked
            jf_id, _, n = ident.partition("/")
            path = media_posters.served_backdrop(jf_id, int(n))
            return path if path is not None and path.name.startswith(v + ".") else None
        path = media_posters.served(ident, size)
        return path if path is not None and path.name.startswith(v + ".") else None
    except OSError:
        return None


def _read(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except OSError:
        return None


@router.get("/img/{ref:path}")
async def image(ref: str, h: str = "", t: str = "", v: str = ""):
    title = t[:80]
    if ref == "none":
        return _fallback(title)
    match = REF_RE.match(ref)
    if not match:
        return Response("Not found", status_code=404, media_type="text/plain")
    kind, ident = _kind_ident(match)
    size = int(h) if h.isdigit() and int(h) in SIZES else DEFAULT_SIZE

    stored = _stored(kind, ident, size, v)   # JY-260 phase 2: the Joey poster from the local store
    if stored is not None:
        body = await anyio.to_thread.run_sync(_read, stored)
        if body is not None:
            return Response(body, media_type="image/jpeg", headers={"Cache-Control": HIT_CACHE})
    # a `v` that is not (or no longer) published - a page built just before a revert or re-render - gets today's
    # image with the short cache, so that versioned URL never pins the wrong image for 30 days
    cache = FALLBACK_CACHE if v and kind in ("jf", "jfs") else HIT_CACHE
    if kind == "jfs":   # not stored (or a stale v): Jellyfin's own backdrop 0 (for 1) or 1 (for 2), as before
        jf_id, _, n = ident.partition("/")
        kind, ident = "jfb", jf_id + ("/1" if n == "2" else "")
    stem = hashlib.sha256(f"{ref}|{size}".encode("utf-8")).hexdigest()
    hit = await anyio.to_thread.run_sync(_cached, stem) if _cache_path(stem) else None   # a stat, then a short read
    if hit is None:
        if _upstreams(kind, ident, size) is None:   # nothing configured: the card at once, no slot, no thread
            return _fallback(title)
        hit = await _miss(stem, kind, ident, size)
        if not hit:
            return _fallback(title)
    return Response(hit[0], media_type=MIME[hit[1]], headers={"Cache-Control": cache})


def warm(ref: str, h: int = DEFAULT_SIZE) -> str:
    """Pre-fetch one ref into the disk cache exactly as GET /img/{ref}?h= would (media-speed warm-up).
    -> 'cached' (already there), 'fetched', or 'skipped' (bad ref / size, no env, upstream failure)."""
    match = REF_RE.match(ref or "")
    if not match or h not in SIZES or _kind_ident(match)[0] == "jfs":   # jfs: local files, nothing to fetch
        return "skipped"
    stem = hashlib.sha256(f"{ref}|{h}".encode("utf-8")).hexdigest()
    if _cache_path(stem):  # a stat, not a read: the warm-up re-checks hundreds of refs each pass
        return "cached"
    got = _fetch(*_kind_ident(match), h)
    if got is None:
        return "skipped"
    _store(stem, got[1], got[0])
    return "fetched"
