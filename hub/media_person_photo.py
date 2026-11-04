"""JY-291 (person hero A, 2026-11-04): the backdrop photo behind a person page's large portrait.

Optional env `TMDB_API_KEY`: when set, one TMDB read `GET https://api.themoviedb.org/3/person/{id}/tagged_images`
(server-side only) picks the highest-voted backdrop-shaped image (aspect >= 1.5) the person is tagged in. Every
answer (an image or none) is remembered TTL (7 days) on disk beside the Seerr meta cache (key `tmdbtag:<id>`); a
failed call FAIL_TTL (10 minutes). No key, no tagged image, or any failure => the backdrop of the person's most
popular credit already loaded from Seerr (no new call). The request URL carries the key, so logs carry the HTTP
status or the exception TYPE only.
"""
from __future__ import annotations

import logging
import os
import time

import requests  # noqa: F401 - tests fake upstreams at the requests module (tests/hub/conftest)

from hub import media_discover as md, upstream

log = logging.getLogger("hub.media_person_photo")

URL = "https://api.themoviedb.org/3/person/{pid}/tagged_images"
TTL = 7 * 24 * 3600
FAIL_TTL = 10 * 60
TIMEOUT = 5
MIN_ASPECT = 1.5


def _key() -> str | None:
    return os.environ.get("TMDB_API_KEY", "").strip() or None


def pick_tagged(body) -> str | None:
    """The best backdrop-shaped tagged image's file path: highest vote average, then vote count, then width."""
    best, score = None, None
    for r in (body.get("results") if isinstance(body, dict) else None) or []:
        if not isinstance(r, dict) or not r.get("file_path"):
            continue
        try:
            if float(r.get("aspect_ratio") or 0) < MIN_ASPECT:
                continue
            s = (float(r.get("vote_average") or 0), int(r.get("vote_count") or 0), int(r.get("width") or 0))
        except (TypeError, ValueError):
            continue
        if score is None or s > score:
            best, score = str(r["file_path"]), s
    return best


def tagged_backdrop(pid: int) -> str | None:
    """The tagged-image ref (`tmdb:/x.jpg`), or None (no key, none tagged, failure)."""
    key = _key()
    if not key:
        return None
    path = f"tmdbtag:{pid}"
    hit = md._meta_disk(path)
    if hit is not None and isinstance(hit[1], dict):
        ttl = FAIL_TTL if hit[1].get("failed") else TTL
        if time.time() - hit[0] < ttl:
            return md._ref(hit[1].get("file"))
    try:
        resp = upstream.session("tmdb").get(URL.format(pid=pid), params={"api_key": key}, timeout=TIMEOUT)
        if resp.status_code == 404:
            body = {}
        elif not 200 <= resp.status_code < 300:
            log.warning("tmdb tagged images failed: HTTP %s", resp.status_code)
            md._meta_store(path, time.time(), {"file": None, "failed": True})
            return None
        else:
            body = resp.json()
    except Exception as exc:  # type only: the exception text holds the URL, which holds the key
        log.warning("tmdb tagged images failed: %s", type(exc).__name__)
        md._meta_store(path, time.time(), {"file": None, "failed": True})
        return None
    file = pick_tagged(body)
    md._meta_store(path, time.time(), {"file": file})
    return md._ref(file)


def credit_backdrop(credits) -> str | None:
    """The backdrop of the person's most popular credit (most votes) in the Seerr combined_credits body."""
    best, votes = None, -1
    for field in ("cast", "crew"):
        for c in ((credits or {}).get(field) if isinstance(credits, dict) else None) or []:
            if not isinstance(c, dict) or not c.get("backdropPath"):
                continue
            try:
                v = int(c.get("voteCount") or 0)
            except (TypeError, ValueError):
                v = 0
            if v > votes:
                best, votes = c.get("backdropPath"), v
    return md._ref(best)
