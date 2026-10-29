"""Remove a request (2026-10-08): the Requests page's "Remove" button. Two steps, no browser dialog (a
`details.confirm-wrap` panel, as the year-ranking Reset), then ONE same-origin POST:

1. Jellyseerr `DELETE /api/v1/request/{id}` (X-Api-Key; creds as media_discover._creds). A 404 means it is
   already gone — that counts as removed.
2. ONLY when the title has nothing on disk yet, stop the *arr search: Radarr movie by tmdbId / Sonarr series by
   tvdbId (else tmdbId) -> `monitored: false` with a PUT of the app's own resource. Nothing is ever deleted in
   Radarr / Sonarr: no file, no entry. A title with a file on disk (or Jellyseerr saying Available / Partly
   available) is left exactly as it is. (The Requests page's Remove still never deletes; since JY-265 phase 2 only
   the title page's Remove > Whole film / Whole show deletes files, through hub/media_remove_whole.py.)
3. The row leaves the page at once (media_hidden, until the next Jellyseerr sweep) and the page flashes "Removed".

Upstream failures are words; logs and flashes carry an exception TYPE or an HTTP status only (requests errors
embed URLs and keys).
"""
from __future__ import annotations

import logging
import os
import re
import threading
import time

import requests  # noqa: F401 - kept: tests fake upstreams at hub.media_requests.requests (E1: via tests/hub/conftest)
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse

from hub import media_discover as md, media_hidden, media_item, media_text, shell, upstream
from hub.ids import JELLYSEERR_SNAPSHOT_ID
from hub.media_write import flash_keys, same_origin

log = logging.getLogger("hub.media_requests")
router = APIRouter()

PAGE = "/media/requests"
GROUP = "request"
TIMEOUT = 8
# E1 (2026-10-13): the film page's lazy "Search now" fragment looks the title up in Radarr / Sonarr on every view (for
# a show without a TheTVDB id that is the whole series list). Its answers - found or not there - are kept LOOKUP_TTL;
# a failed lookup is not kept, and every Joey write to an *arr app or a Seerr request drops them all (forget_lookups).
# Write paths themselves always read the app live (`_find`), never this cache.
LOOKUP_TTL = 300
_lookups: dict[tuple, tuple[float, dict | None]] = {}
_lookups_lock = threading.Lock()


def forget_lookups() -> None:
    with _lookups_lock:
        _lookups.clear()


def find_kept(app: str, base: str, headers: dict, tmdb: int, tvdb: int | None) -> dict | None:
    """_find through the LOOKUP_TTL cache (the Search now fragment only); raises like _find on a failed read."""
    key = (app, base, tmdb, tvdb)
    with _lookups_lock:
        hit = _lookups.get(key)
    if hit is not None and time.monotonic() - hit[0] < LOOKUP_TTL:
        return hit[1]
    # WP-R1 (2026-10-21): the Search now and Quality fragments load together - concurrent askers share one read
    entry = media_item.once(("arr-find", *key), lambda: _find(app, base, headers, tmdb, tvdb))
    with _lookups_lock:
        if len(_lookups) > 256:
            _lookups.clear()
        _lookups[key] = (time.monotonic(), entry)
    return entry


def kept(app: str, base: str, tmdb: int, tvdb: int | None) -> tuple[bool, dict | None]:
    """find_kept's answer from the cache alone (WP-R1, the Requests page): (True, entry or None) while kept, else
    (False, None) - never a call."""
    with _lookups_lock:
        hit = _lookups.get((app, base, tmdb, tvdb))
    if hit is not None and time.monotonic() - hit[0] < LOOKUP_TTL:
        return True, hit[1]
    return False, None


ON_DISK_WORDS = ("Available", "Partly available")
APPS = {"movie": "radarr", "tv": "sonarr"}
DONE = {"removed": "Removed",
        "stopped": "Removed · {app} stopped searching",
        "ondisk": "Removed · already on disk, {app} left as is",
        "arrfail": "Removed · couldn't stop the {app} search",
        "arrunset": "Removed · {app} not connected, its search carries on"}
ERRORS = {"missing": "That request is no longer listed",
          "unset": "Seerr is not connected",
          "unreachable": "Couldn't reach Seerr",
          "refused": "Seerr refused",
          # WP-RQ1 (2026-10-22): Approve / Decline (hub/media_requests_approve.py)
          "notpending": "That request is no longer pending",
          "busy": "Already sending that one — wait a moment",   # JY-230: a second click while the first is sent
          "noseasons": "Seerr has no seasons left to request — another request or the library holds them"}
COUNT_OF = {"Pending": "pending", "Approved": "approved", "Processing": "approved", "Partly available": "approved",
            "Available": "available", "Declined": "declined"}


# ---- what the pages show ----

def visible_rows(data: dict, updated_at=None) -> list[dict]:
    """The snapshot's request rows minus the ones removed since it was taken."""
    return media_hidden.visible(GROUP, (data or {}).get("requests"), lambda r: r.get("id"), updated_at)


def visible_counts(data: dict, rows: list[dict]) -> dict:
    """Jellyseerr's counts less the rows hidden here (so "1 pending" drops with the row)."""
    counts = dict((data or {}).get("counts") or {})
    shown = {id(r) for r in rows}
    for r in (data or {}).get("requests") or []:
        k = COUNT_OF.get(str(r.get("status_text"))) if isinstance(r, dict) and id(r) not in shown else None
        if k and counts.get(k):
            counts[k] = counts[k] - 1
    return counts


def snapshot_rows(snaps, snapshot_id: str = "jellyseerr") -> list[dict]:
    """Visible request rows straight from the snapshots dict (film page, watchlist)."""
    snap = snaps.get(snapshot_id)
    return visible_rows((snap.data if snap else {}) or {}, snap.updated_at if snap else None)


flash_keys("done", "error", "app", "code")


def flash_text(params) -> tuple[str | None, str | None]:
    """(good line, warning line) from the redirect's query; anything odd -> (None, None)."""
    done, err, app, code = (params.get("done") or ""), (params.get("error") or ""), params.get("app"), params.get("code") or ""
    app = {"radarr": "Radarr", "sonarr": "Sonarr"}.get(app or "", "Radarr / Sonarr")
    if done in DONE:
        return DONE[done].format(app=app), None
    if err in ERRORS:
        word = ERRORS[err]
        if err == "refused" and re.fullmatch(r"\d{3}", code):
            word += f" (HTTP {code})"
        return None, word
    return None, None


# ---- the *arr side ----

def _arr_creds(app: str) -> tuple[str, dict] | None:
    base = os.environ.get(f"{app.upper()}_URL", "").strip()
    key = os.environ.get(f"{app.upper()}_API_KEY", "").strip()
    return (base.rstrip("/"), {"X-Api-Key": key}) if base and key else None


def _find(app: str, base: str, headers: dict, tmdb: int, tvdb: int | None) -> dict | None:
    """The Radarr movie / Sonarr series for this title, or None when the app doesn't have it."""
    if app == "radarr":
        resp = upstream.session("arr").get(f"{base}/api/v3/movie", params={"tmdbId": tmdb}, headers=headers, timeout=TIMEOUT)
        match = lambda m: m.get("tmdbId") == tmdb
    elif tvdb:
        resp = upstream.session("arr").get(f"{base}/api/v3/series", params={"tvdbId": tvdb}, headers=headers, timeout=TIMEOUT)
        match = lambda s: s.get("tvdbId") == tvdb
    else:
        resp = upstream.session("arr").get(f"{base}/api/v3/series", headers=headers, timeout=TIMEOUT)
        match = lambda s: s.get("tmdbId") == tmdb
    if not 200 <= resp.status_code < 300:
        raise RuntimeError(f"HTTP {resp.status_code}")
    body = resp.json()
    rows = body if isinstance(body, list) else [body] if isinstance(body, dict) else []
    return next((r for r in rows if isinstance(r, dict) and r.get("id") and match(r)), None)


def _on_disk(app: str, entry: dict) -> bool:
    stats = entry.get("statistics") or {}
    if app == "radarr":
        return bool(entry.get("hasFile") or entry.get("movieFile") or (stats.get("sizeOnDisk") or 0) > 0
                    or (entry.get("sizeOnDisk") or 0) > 0)
    return bool((stats.get("episodeFileCount") or 0) > 0 or (stats.get("sizeOnDisk") or 0) > 0)


def stop_search(kind: str, tmdb: int, tvdb: int | None = None) -> str:
    """Unmonitor the title in Radarr / Sonarr when nothing is on disk. Returns a DONE code. Never deletes."""
    app = APPS[kind]
    creds = _arr_creds(app)
    if creds is None:
        return "arrunset"
    base, headers = creds
    try:
        entry = _find(app, base, headers, tmdb, tvdb)
        if entry is None:
            return "removed"            # never reached the app: nothing is searching
        if _on_disk(app, entry):
            return "ondisk"
        if not entry.get("monitored"):
            return "stopped"            # already not searching
        path = "movie" if app == "radarr" else "series"
        forget_lookups()
        resp = upstream.session("arr").put(f"{base}/api/v3/{path}/{int(entry['id'])}", json={**entry, "monitored": False},
                            headers=headers, timeout=TIMEOUT)
        if not 200 <= resp.status_code < 300:
            raise RuntimeError(f"HTTP {resp.status_code}")
        return "stopped"
    except Exception as exc:  # type / status only — requests errors embed the URL and key
        log.warning("%s unmonitor failed: %s", app, media_text.why(exc))
        return "arrfail"


# ---- the Jellyseerr side + the route ----

def delete_request(rid: int) -> tuple[str | None, int | None]:
    """DELETE the Jellyseerr request -> (None, None) when gone, else (ERRORS code, HTTP status or None)."""
    creds = md._creds()
    if creds is None:
        return "unset", None
    try:
        resp = upstream.session("seerr").delete(f"{creds[0]}/api/v1/request/{rid}", headers={"X-Api-Key": creds[1]}, timeout=TIMEOUT)
    except Exception as exc:  # type only — requests errors embed the URL
        log.warning("jellyseerr request delete failed: %s", type(exc).__name__)
        return "unreachable", None
    if 200 <= resp.status_code < 300 or resp.status_code == 404:  # 404: already gone
        return None, None
    log.warning("jellyseerr request delete refused: HTTP %s", resp.status_code)
    return "refused", resp.status_code


def _row(rid: int) -> tuple[dict | None, object]:
    snap = shell.get_snapshots().get(JELLYSEERR_SNAPSHOT_ID)
    for r in visible_rows((snap.data if snap else {}) or {}, snap.updated_at if snap else None):
        if r.get("id") == rid:
            return r, snap
    return None, snap


def _to(**params) -> RedirectResponse:
    from urllib.parse import urlencode
    return RedirectResponse(f"{PAGE}?" + urlencode(params), status_code=303)


@router.post("/media/requests/{rid}/remove", dependencies=[Depends(same_origin)])
def remove_request(request: Request, rid: int):
    if rid <= 0:
        raise HTTPException(404, "No such request")
    row, _snap = _row(rid)
    if row is None:
        return _to(error="missing")
    code, status = delete_request(rid)
    if code is not None:
        return _to(error=code, **({"code": status} if status else {}))
    media_hidden.hide(GROUP, rid)
    md._cache.pop(f"film:/api/v1/{row.get('kind')}/{row.get('tmdb_id')}", None)  # the film page re-reads its status
    kind = "tv" if row.get("kind") == "tv" else "movie"
    tmdb = row.get("tmdb_id") if isinstance(row.get("tmdb_id"), int) else 0
    tvdb = row.get("tvdb_id") if isinstance(row.get("tvdb_id"), int) else None
    if row.get("status_text") in ON_DISK_WORDS:
        done = "ondisk"
    elif tmdb <= 0 and not tvdb:
        done = "removed"
    else:
        done = stop_search(kind, tmdb, tvdb)
    return _to(done=done, app=APPS[kind]) if done != "removed" else _to(done="removed")
