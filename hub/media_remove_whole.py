"""Remove on title pages, phase 2: the WHOLE film or show, files included (JY-265, spec docs/specs/JY-265-remove.md
sections 1b, 2.3, 3 and 6). Called from hub/media_remove.py, behind the same REMOVE_API flag (default off).

This is the first Joey path that deletes media. It never touches the filesystem: Radarr / Sonarr delete through their
own API (`deleteFiles=true`), so the files land in the app's recycle bin (/data/recycle-bin/radarr|sonarr, 7 days),
and Joey refuses when an app has no recycle bin set (Q6 A).

* `live(kind, tmdb, tvdb)` is the live read the Confirm step and the POST both make: the arr entry, its file ids and
  bytes. The POST refuses ("This changed since you looked") when they differ from what the Confirm step showed.
* `run(...)` is the write, in order: Follow removed (a show), the arr queue rows cancelled (removeFromClient, no
  blocklist), the arr DELETE with files (entry gone, Q3 A, no import exclusion), the Seerr requests deleted and its
  media cleared, Jellyfin told (`/Library/Media/Updated`, a show falls back to a recursive refresh). The first failed
  write stops the run; a failure after the arr DELETE is `partial`. Jellyfin is best effort: it catches up on its scan.
Logs carry an HTTP status or an exception type only: never a URL, path or key.
"""
from __future__ import annotations

import logging
import re
import threading
import time

from hub import media_discover as md, media_follow, media_jellyfin as jellyfin, media_requests as mr, shell, upstream
from hub.ids import ARR_SNAPSHOT_ID, JELLYFIN_SNAPSHOT_ID
from hub.store import data_of

log = logging.getLogger("hub.media_remove_whole")
TIMEOUT = mr.TIMEOUT
BIN_TTL = 3600                         # the recycle-bin setting is read at most hourly (spec 3.3)
_bins: dict[str, tuple[float, bool]] = {}
_bins_lock = threading.Lock()


class Unreachable(Exception):
    """An app could not be read; nothing was sent."""


def clear() -> None:
    with _bins_lock:
        _bins.clear()


def app_of(kind: str) -> str:
    return mr.APPS[kind]


def norm(text) -> str:
    """The typed-title check (Q5 A): case-insensitive, punctuation and spaces ignored."""
    return re.sub(r"[\W_]+", "", str(text or "")).casefold()


# ---- the cached facts (never a call) ----

def on_disk(kind: str, tmdb: int, snaps) -> dict | None:
    """The arr snapshot's library_sizes row for this title ({title, year?, size_bytes, tvdb_id?}), or None."""
    sizes = data_of(snaps.get(ARR_SNAPSHOT_ID)).get("library_sizes")
    rows = (sizes or {}).get(app_of(kind)) if isinstance(sizes, dict) else None
    return next((r for r in rows or [] if isinstance(r, dict) and r.get("tmdb_id") == tmdb
                 and isinstance(r.get("size_bytes"), int) and r["size_bytes"] > 0), None)


def _jf_series_id(tmdb: int, tvdb, snaps) -> str | None:
    keys = {f"tmdb:{tmdb}"} | ({f"tvdb:{tvdb}"} if tvdb else set())
    for s in data_of(snaps.get(JELLYFIN_SNAPSHOT_ID)).get("shows") or []:
        if isinstance(s, dict) and s.get("item_key") in keys and s.get("jf_id"):
            return str(s["jf_id"])
    return None


# ---- the live reads ----

def _creds(kind: str):
    return mr._arr_creds(app_of(kind))


def live(kind: str, tmdb: int, tvdb: int | None) -> dict | None:
    """{id, title, year, path, files: [ids], bytes} from the arr app, None when it doesn't have the title.
    Raises Unreachable on no answer / non-2xx; KeyError("unset") when the app isn't configured."""
    creds = _creds(kind)
    if creds is None:
        raise KeyError("unset")
    base, headers = creds
    try:
        entry = mr._find(app_of(kind), base, headers, tmdb, tvdb)
        if entry is None:
            return None
        if kind == "movie":
            mf = entry.get("movieFile") if isinstance(entry.get("movieFile"), dict) else None
            files = [(mf["id"], int(mf.get("size") or 0))] if mf and isinstance(mf.get("id"), int) else []
        else:
            resp = upstream.session("arr").get(f"{base}/api/v3/episodefile", params={"seriesId": int(entry["id"])},
                                               headers=headers, timeout=TIMEOUT)
            if not 200 <= resp.status_code < 300:
                raise RuntimeError(f"HTTP {resp.status_code}")
            body = resp.json()
            files = [(f["id"], int(f.get("size") or 0)) for f in body if isinstance(f, dict)
                     and isinstance(f.get("id"), int)] if isinstance(body, list) else []
    except Exception as exc:
        log.warning("%s live read failed: %s", app_of(kind), type(exc).__name__)
        raise Unreachable from None
    return {"id": int(entry["id"]), "title": str(entry.get("title") or ""), "year": entry.get("year"),
            "path": entry.get("path") if isinstance(entry.get("path"), str) else None,
            "files": sorted(i for i, _ in files), "bytes": sum(n for _, n in files)}


def recycle_bin_set(kind: str) -> bool:
    """Does the app have a recycle bin? (`config/mediamanagement.recycleBin`, kept BIN_TTL). Raises Unreachable."""
    app = app_of(kind)
    with _bins_lock:
        hit = _bins.get(app)
    if hit and time.monotonic() - hit[0] < BIN_TTL:
        return hit[1]
    creds = _creds(kind)
    if creds is None:
        raise Unreachable
    base, headers = creds
    try:
        resp = upstream.session("arr").get(f"{base}/api/v3/config/mediamanagement", headers=headers, timeout=TIMEOUT)
        if not 200 <= resp.status_code < 300:
            raise RuntimeError(f"HTTP {resp.status_code}")
        body = resp.json()
    except Exception as exc:
        log.warning("%s recycle-bin read failed: %s", app, type(exc).__name__)
        raise Unreachable from None
    ok = isinstance(body, dict) and bool(str(body.get("recycleBin") or "").strip())
    with _bins_lock:
        _bins[app] = (time.monotonic(), ok)
    return ok


def watching(kind: str, tmdb: int, path: str | None) -> bool:
    """A live Jellyfin `/Sessions` read: is anyone playing this title now? No Jellyfin set up -> False.
    Raises Unreachable on no answer (the remove is refused: Joey can't tell)."""
    creds = jellyfin.creds()
    if creds is None:
        return False
    try:
        sessions = jellyfin.get(*creds, "/Sessions")
    except Exception as exc:
        log.warning("jellyfin sessions read failed: %s", type(exc).__name__)
        raise Unreachable from None
    folder = (path or "").rstrip("/") + "/" if path else None
    for s in sessions if isinstance(sessions, list) else []:
        item = s.get("NowPlayingItem") if isinstance(s, dict) else None
        if not isinstance(item, dict):
            continue
        ids = item.get("ProviderIds") if isinstance(item.get("ProviderIds"), dict) else {}
        if kind == "movie" and str(ids.get("Tmdb") or "") == str(tmdb):
            return True
        if folder and str(item.get("Path") or "").startswith(folder):
            return True
        if kind == "tv" and str((item.get("SeriesProviderIds") or {}).get("Tmdb") or "") == str(tmdb):
            return True
    return False


# ---- the write ----

def _ok(resp) -> bool:
    return 200 <= resp.status_code < 300


def _step(steps: list, app: str, step: str, outcome: str) -> None:
    steps.append({"app": app, "step": step, "outcome": outcome})


def _call(steps: list, app: str, step: str, fn) -> bool:
    """One write: True on a 2xx. Records the step either way (HTTP status or exception type, never a URL)."""
    try:
        resp = fn()
    except Exception as exc:
        _step(steps, app, step, type(exc).__name__)
        log.warning("%s %s failed: %s", app, step, type(exc).__name__)
        return False
    _step(steps, app, step, "ok" if _ok(resp) else f"HTTP {resp.status_code}")
    return _ok(resp)


def _cancel_queue(kind: str, entry_id: int, steps: list) -> bool:
    base, headers = _creds(kind)
    app = app_of(kind)
    key = "movieId" if kind == "movie" else "seriesId"
    try:
        resp = upstream.session("arr").get(f"{base}/api/v3/queue/details", params={key: entry_id}, headers=headers,
                                           timeout=TIMEOUT)
        rows = resp.json() if _ok(resp) else None
    except Exception as exc:
        _step(steps, app, "read queue", type(exc).__name__)
        return False
    if not isinstance(rows, list):
        _step(steps, app, "read queue", f"HTTP {resp.status_code}")
        return False
    for q in rows:
        if isinstance(q, dict) and isinstance(q.get("id"), int) and q.get(key) == entry_id:
            if not _call(steps, app, f"cancel download {q['id']}", lambda q=q: upstream.session("arr").delete(
                    f"{base}/api/v3/queue/{q['id']}", params={"removeFromClient": "true", "blocklist": "false"},
                    headers=headers, timeout=TIMEOUT)):
                return False
    return True


def _arr_delete(kind: str, entry_id: int, steps: list) -> bool:
    base, headers = _creds(kind)
    path, excl = ("movie", "addImportExclusion") if kind == "movie" else ("series", "addImportListExclusion")
    return _call(steps, app_of(kind), "delete with files", lambda: upstream.session("arr").delete(
        f"{base}/api/v3/{path}/{entry_id}", params={"deleteFiles": "true", excl: "false"}, headers=headers,
        timeout=TIMEOUT))


def _seerr_clear(kind: str, tmdb: int, rows: list[dict], steps: list) -> bool:
    """Delete the title's requests, then Seerr's media (its "Clear data"), so it can be requested again."""
    creds = md._creds()
    if creds is None:
        _step(steps, "seerr", "clear", "not connected")
        return True   # no Seerr: nothing to clear
    for r in rows:
        code, status = mr.delete_request(r["id"])
        _step(steps, "seerr", f"delete request {r['id']}", "ok" if code is None else (f"HTTP {status}" if status else code))
        if code is not None:
            return False
    base, key = creds
    try:
        resp = upstream.session("seerr").get(f"{base}/api/v1/{kind}/{tmdb}", headers={"X-Api-Key": key}, timeout=TIMEOUT)
        body = resp.json() if _ok(resp) else None
    except Exception as exc:
        _step(steps, "seerr", "read media", type(exc).__name__)
        return False
    if body is None:
        _step(steps, "seerr", "read media", f"HTTP {resp.status_code}")
        return False
    media_id = (body.get("mediaInfo") or {}).get("id") if isinstance(body, dict) else None
    if not isinstance(media_id, int):
        _step(steps, "seerr", "clear media", "skipped: not in Seerr")
        return True
    ok = _call(steps, "seerr", "clear media", lambda: upstream.session("seerr").delete(
        f"{base}/api/v1/media/{media_id}", headers={"X-Api-Key": key}, timeout=TIMEOUT))
    return ok or steps[-1]["outcome"] == "HTTP 404"   # 404: already cleared


def _jellyfin(kind: str, tmdb: int, tvdb, path: str | None, snaps, steps: list) -> bool:
    """Tell Jellyfin the folder went. True when it was told; False -> it catches up on its next scan."""
    creds = jellyfin.creds()
    if creds is None or not path:
        _step(steps, "jellyfin", "media updated", "skipped")
        return False
    base, headers = creds
    if _call(steps, "jellyfin", "media updated", lambda: upstream.session("jellyfin").post(
            f"{base}/Library/Media/Updated", json={"Updates": [{"Path": path, "UpdateType": "Deleted"}]},
            headers=headers, timeout=TIMEOUT)):
        return True
    jf = _jf_series_id(tmdb, tvdb, snaps) if kind == "tv" else None
    if jf and re.fullmatch(r"[0-9a-fA-F-]{8,64}", jf):
        return _call(steps, "jellyfin", "refresh series", lambda: upstream.session("jellyfin").post(
            f"{base}/Items/{jf}/Refresh", params={"Recursive": "true"}, headers=headers, timeout=TIMEOUT))
    return False


def run(kind: str, tmdb: int, tvdb: int | None, entry: dict, rows: list[dict]) -> tuple[str, list, bool]:
    """The whole-title remove. -> (outcome done|partial|failed, steps, jellyfin told)."""
    steps: list = []
    if kind == "tv" and media_follow.get("show", tmdb):
        media_follow.unfollow("show", tmdb)   # else Follow's 6-hour re-apply re-monitors the show
        _step(steps, "joey", "unfollow", "ok")
    if not _cancel_queue(kind, entry["id"], steps):
        return "failed", steps, False
    if not _arr_delete(kind, entry["id"], steps):
        return "failed", steps, False
    mr.forget_lookups()
    md._cache.pop(f"film:/api/v1/{kind}/{tmdb}", None)
    if not _seerr_clear(kind, tmdb, rows, steps):
        return "partial", steps, False
    told = _jellyfin(kind, tmdb, tvdb, entry.get("path"), shell.get_snapshots(), steps)
    return "done", steps, told
