"""Remove on title pages (JY-265, spec docs/specs/JY-265-remove.md). Phase 1: Remove REQUEST. Phase 2 (2026-10-29):
remove the WHOLE film or show, files included, through Radarr / Sonarr (hub/media_remove_whole.py; their recycle bin
keeps the files 7 days). Seasons and episodes are phase 3, the TV phase 4.

B., 2026-10-28: "JY-265: Q1A · Q2A · Q3A · Q4A · Q5A · Q6A · Q7A · Q8A · Q9A · Q10A".

* `REMOVE_API=on` turns it on (default off). Off, every route below is the ordinary 404 page and the title page's
  More fold has no Remove line.
* Owner "you" on the private front only (Q1 A). Anyone else - Georgina's view, and friends on the media front (where
  hub.guest classifies the routes PRIVATE and the GuestGate 404s them first) - gets the same ordinary 404 page.
* GET /media/remove/{kind}/{tmdb_id} is the Pick step (only "Request only" exists in phase 1);
  `?step=confirm&scope=request` is the Confirm step, which lists exactly what will happen. Both read the cached
  jellyseerr snapshot only: no network call on render.
* POST /media/remove/{kind}/{tmdb_id} removes the request(s) shown on the Confirm step. Same-origin (as every Joey
  write), one remove at a time, at most RATE_MAX per rolling hour. It re-reads each request live in Seerr first
  (`GET /api/v1/request/{id}`; 404 = already gone): the posted request ids must still be the ones the cache lists for
  this title, and each live request must be this title, else nothing is sent ("This changed since you looked").
  Then exactly what the Requests page's Remove does (hub/media_requests.py, reused, Q4 A): Seerr
  `DELETE /api/v1/request/{id}`, and only when nothing is on disk, Radarr / Sonarr `monitored: false` (the entry is
  kept). Phase 1 deletes no file and no arr entry, and cancels no download.
* Every POST that reaches Seerr writes one `media_removals` row (who, what, when, each step's result; titles and
  codes only, never a path, URL or key) and posts one Discord line to the Server webhook (Q9 A; none set -> nothing).
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from collections import deque
from contextlib import closing
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlencode

import requests
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool

from hub import guest, media_discover as md, media_hidden, media_requests as mr, media_store, server_alerts, shell, upstream
from hub import media_remove_whole as whole
from hub.ids import JELLYSEERR_SNAPSHOT_ID, home_tz
from hub.media_requests_approve import season_words, who
from hub.media_write import MAX_BODY, flash_keys, owner_for, same_origin

log = logging.getLogger("hub.media_remove")
router = APIRouter()
flash_keys("done", "error", "app", "at")

FLAG = "REMOVE_API"
PAGE = "/media/remove"
KINDS = ("movie", "tv")
SCOPES = ("request", "whole")         # phases 1-2; seasons / episodes come in phase 3
RATE_MAX = 10                         # removes per rolling hour
WHOLE_MAX = 3                         # whole-title removes per rolling hour (spec 3.6)
DISK_GROUP = "remove-disk"            # media_hidden: a removed title's library_sizes row until the next arr sweep
RATE_WINDOW_S = 3600
SEERR_ON_DISK = (4, 5)                # Seerr MediaStatus: 4 partly available, 5 available

DDL = """CREATE TABLE IF NOT EXISTS media_removals(
  id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, owner TEXT NOT NULL, front TEXT NOT NULL,
  kind TEXT NOT NULL, tmdb_id INTEGER, tvdb_id INTEGER, title TEXT, scope TEXT NOT NULL, picked TEXT,
  files INTEGER NOT NULL DEFAULT 0, bytes INTEGER NOT NULL DEFAULT 0, request_ids TEXT, steps TEXT, outcome TEXT NOT NULL)"""

DONE = {"removed": "Request removed",
        "stopped": "Request removed · {app} stopped searching. Its entry stays.",
        "ondisk": "Request removed · already on disk, {app} left as it is. The files stay.",
        "arrfail": "Request removed · couldn't stop the {app} search",
        "arrunset": "Request removed · {app} not connected, its search carries on",
        "partial": "Some requests were removed, one was not. Check the Requests page."}
ERRORS = {"changed": "This changed since you looked. Check again.",
          "busy": "Another remove is running. Try again in a moment.",
          "unset": "Seerr is not connected. Nothing was removed.",
          "unreachable": "Seerr can't be reached. Nothing was removed.",
          "refused": "Seerr refused. Nothing was removed.",
          "scope": "Pick what to remove first.",
          "typed": "The title you typed doesn't match. Nothing was removed.",
          "nobin": "{app} has no recycle bin set, so this can't be undone. Set one in {app} › Settings › Media Management first.",
          "arrdown": "{app} can't be reached. Nothing was removed.",
          "watching": "Someone is watching it now. Try again when it stops.",
          "jfdown": "Jellyfin can't be reached, so Joey can't check nobody is watching. Nothing was removed.",
          "deletefail": "{app} refused the delete. Nothing was removed.",
          "wholepartial": "{app} deleted the files, but Seerr couldn't be cleared. Check the Requests page.",
          "wholeslow": "{app} was slow to answer, but the title is gone: its files are in {app}'s recycle bin.",
          "wholeunsure": "{app} didn't answer and couldn't be checked. Look in {app}: the files may be in its recycle bin."}
DONE_WHOLE = {"whole": "Removed · {app} moved the files to its recycle bin (kept 7 days)",
              "wholelate": "Removed · {app} moved the files to its recycle bin (kept 7 days). Jellyfin will catch up on its next scan"}

_lock = threading.Lock()              # one remove at a time
_times: deque[float] = deque()        # monotonic times of the removes in the last hour
_whole_times: deque[float] = deque()  # ... of the whole-title removes
_times_lock = threading.Lock()


def clear() -> None:
    """Tests: forget the rate-limit clock."""
    with _times_lock:
        _times.clear()
        _whole_times.clear()
    whole.clear()


def enabled() -> bool:
    return (os.environ.get(FLAG) or "").strip().lower() == "on"


def can_remove(request: Request) -> bool:
    """Flag on, private front, owner "you" (Q1 A). Everyone else never sees Remove."""
    return enabled() and not guest.is_media() and owner_for(request) == "you"


# ---- the cached rows (never a call) ----

def rows_for(kind: str, tmdb: int, snaps=None) -> list[dict]:
    """The visible Seerr request rows for this title, from the jellyseerr snapshot."""
    snaps = snaps if snaps is not None else shell.get_snapshots()
    return [r for r in mr.snapshot_rows(snaps, JELLYSEERR_SNAPSHOT_ID)
            if isinstance(r, dict) and isinstance(r.get("id"), int) and r.get("tmdb_id") == tmdb
            and ("tv" if r.get("kind") == "tv" else "movie") == kind]


def disk_for(kind: str, tmdb: int, snaps=None) -> dict | None:
    """The cached on-disk row (arr snapshot library_sizes), unless removed since that snapshot. Never a call."""
    snaps = snaps if snaps is not None else shell.get_snapshots()
    row = whole.on_disk(kind, tmdb, snaps)
    snap = snaps.get("arr")
    if row and media_hidden.is_hidden(DISK_GROUP, f"{kind}:{tmdb}", snap.updated_at if snap else None):
        return None
    return row


def more_href(request: Request, kind, tmdb, snaps) -> str | None:
    """The title page's More line: the Remove page when the owner may remove and a request exists or the title is
    on disk in Radarr / Sonarr (both from caches). Never a call."""
    if kind not in KINDS or not isinstance(tmdb, int) or tmdb <= 0 or not can_remove(request):
        return None
    return f"{PAGE}/{kind}/{tmdb}" if rows_for(kind, tmdb, snaps) or disk_for(kind, tmdb, snaps) else None


def _app(kind: str) -> str:
    return "Sonarr" if kind == "tv" else "Radarr"


def plan(kind: str, rows: list[dict]) -> list[str]:
    """What the Confirm step says will happen, in words."""
    app = _app(kind)
    lines = []
    for r in rows:
        whose = who(r)
        whose = "your" if whose == "you" else "Georgina's" if whose == "her" else f"{whose}'s"
        seasons = season_words(r.get("seasons")) if kind == "tv" else None
        lines.append(f"Seerr deletes {whose} request{f' ({seasons})' if seasons else ''} · {r.get('status_text') or 'Requested'}.")
    if any(r.get("status_text") in mr.ON_DISK_WORDS for r in rows):
        lines.append(f"It is already on disk: {app} is left as it is and the files stay.")
    else:
        lines.append(f"{app} stops searching for it (unmonitored). Its entry stays, so it can be requested again.")
    lines.append("Nothing on disk is deleted.")
    lines.append("Your ratings, diary and poster stay.")
    return lines


def size_words(n: int) -> str:
    gb = n / 1024 ** 3
    return f"{gb:,.1f} GB" if gb >= 1 else f"{n / 1024 ** 2:,.0f} MB"


def plan_whole(kind: str, entry: dict, rows: list[dict]) -> list[str]:
    """What the whole-title Confirm says will happen, from the live read."""
    app, n = _app(kind), len(entry["files"])
    lines = [f"{app} deletes {n} file{'' if n == 1 else 's'} · {size_words(entry['bytes'])}, and its entry for the title.",
             f"Files go to {app}'s recycle bin and are kept for 7 days, so the space frees up when it empties."]
    if rows:
        lines.append(f"Seerr deletes the request{'s' if len(rows) > 1 else ''} and clears the title, so it can be requested again.")
    if kind == "tv":
        lines.append("If you follow the show, the follow goes too, so it isn't added back.")
    lines.append("A download still running for it is cancelled.")
    lines.append("Your ratings, diary and poster stay.")
    return lines


def _title(rows: list[dict]) -> str:
    r = rows[0] if rows else {}
    year = r.get("year")
    return str(r.get("title") or "This title")[:200] + (f" ({year})" if isinstance(year, int) else "")


def flash(params) -> tuple[str | None, str | None]:
    done, err = params.get("done") or "", params.get("error") or ""
    app = {"radarr": "Radarr", "sonarr": "Sonarr"}.get(params.get("app") or "", "Radarr / Sonarr")
    if done in DONE:
        return DONE[done].format(app=app), None
    if done in DONE_WHOLE:
        return DONE_WHOLE[done].format(app=app), None
    if err == "rate":
        at = params.get("at") or ""
        return None, "Too many removes in the last hour." + (f" Try again at {at}." if len(at) == 5 and at[2] == ":" and at.replace(":", "").isdigit() else "")
    return (None, ERRORS[err].format(app=app)) if err in ERRORS else (None, None)


# ---- the page ----

@router.get(PAGE + "/{kind}/{tmdb_id}", response_class=HTMLResponse)
def remove_page(request: Request, kind: str, tmdb_id: int, step: str = "", scope: str = ""):
    if kind not in KINDS or tmdb_id <= 0 or not can_remove(request):
        return shell.not_found_page(request)
    snaps = shell.get_snapshots(request=request)
    rows = rows_for(kind, tmdb_id, snaps)
    disk = disk_for(kind, tmdb_id, snaps)
    good, warn = flash(request.query_params)
    back = f"/media/title/{kind}/{tmdb_id}"
    confirm = step == "confirm" and ((scope == "request" and bool(rows)) or (scope == "whole" and bool(disk)))
    entry, plan_lines = None, []
    if confirm and scope == "whole":   # the explicit step: a live read of the arr entry and its files (spec 2.3)
        entry, code = _live_whole(kind, tmdb_id, disk)
        if entry is None:
            confirm = False
            warn = ERRORS[code].format(app=_app(kind)) if code in ERRORS else warn
        else:
            plan_lines = plan_whole(kind, entry, rows)
    elif confirm:
        plan_lines = plan(kind, rows)
    title = _title(rows) if rows else (_disk_title(disk) if disk else None)
    ctx = {"kind": kind, "tmdb": tmdb_id, "rows": rows, "disk": disk, "title": title, "back": back,
           "disk_size": size_words(disk["size_bytes"]) if disk else None, "scope": scope if confirm else "",
           "entry": entry, "fids": ",".join(str(i) for i in entry["files"]) if entry else "",
           "action": f"{PAGE}/{kind}/{tmdb_id}", "confirm": confirm, "app": _app(kind),
           "plan": plan_lines, "rids": ",".join(str(r["id"]) for r in rows),
           "asked": [{"who": who(r), "seasons": season_words(r.get("seasons")) if kind == "tv" else None,
                      "status": r.get("status_text") or "Requested"} for r in rows],
           "flash": good, "flash_warn": warn}
    request.state.media_section = "movies" if kind == "movie" else "tv"
    return shell.render_page(request, "media_remove.html", ctx)


def _disk_title(disk: dict) -> str:
    year = disk.get("year")
    return str(disk.get("title") or "This title")[:200] + (f" ({year})" if isinstance(year, int) else "")


def _live_whole(kind: str, tmdb: int, disk: dict | None) -> tuple[dict | None, str | None]:
    """(live entry, None) or (None, ERRORS code). The recycle bin must be set, the entry must hold files."""
    tvdb = (disk or {}).get("tvdb_id") if kind == "tv" else None
    try:
        if not whole.recycle_bin_set(kind):
            return None, "nobin"
        entry = whole.live(kind, tmdb, tvdb if isinstance(tvdb, int) else None)
    except (whole.Unreachable, KeyError):
        return None, "arrdown"
    if entry is None or not entry["files"]:
        return None, "changed"
    return entry, None


# ---- the write ----

def _seerr_read(rid: int) -> tuple[str, dict | None]:
    """("ok", body) | ("gone", None) | (ERRORS code, None) for one live request read."""
    creds = md._creds()
    if creds is None:
        return "unset", None
    try:
        resp = upstream.session("seerr").get(f"{creds[0]}/api/v1/request/{rid}", headers={"X-Api-Key": creds[1]},
                                             timeout=mr.TIMEOUT)
    except Exception as exc:   # type only: requests errors embed the URL
        log.warning("seerr request read failed: %s", type(exc).__name__)
        return "unreachable", None
    if resp.status_code == 404:
        return "gone", None
    if not 200 <= resp.status_code < 300:
        log.warning("seerr request read refused: HTTP %s", resp.status_code)
        return "refused", None
    try:
        body = resp.json()
    except ValueError:
        return "refused", None
    return ("ok", body) if isinstance(body, dict) else ("refused", None)


def _same_title(body: dict, kind: str, tmdb: int) -> bool:
    media = body.get("media") if isinstance(body.get("media"), dict) else {}
    return media.get("tmdbId") == tmdb and (body.get("type") or media.get("mediaType")) == kind


def _rate_ok(now: float) -> tuple[bool, float | None]:
    with _times_lock:
        while _times and now - _times[0] >= RATE_WINDOW_S:
            _times.popleft()
        if len(_times) >= RATE_MAX:
            return False, _times[0] + RATE_WINDOW_S
        _times.append(now)
        return True, None


def _clock_at(mono_at: float) -> str:
    at = datetime.now(timezone.utc) + timedelta(seconds=max(0.0, mono_at - time.monotonic()))
    tz = home_tz()
    return (at.astimezone(tz) if tz else at).strftime("%H:%M")


def record(row: dict) -> None:
    """One media_removals row. A failed write is logged by type and never stops the remove."""
    try:
        with closing(media_store.connect()) as db:
            db.execute("INSERT INTO media_removals(at, owner, front, kind, tmdb_id, tvdb_id, title, scope, picked, files, "
                       "bytes, request_ids, steps, outcome) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (datetime.now(timezone.utc).isoformat(timespec="seconds"), row["owner"], row["front"], row["kind"],
                        row["tmdb_id"], row.get("tvdb_id"), row["title"], row["scope"], json.dumps(row.get("picked") or []),
                        int(row.get("files") or 0), int(row.get("bytes") or 0), json.dumps(row["request_ids"]),
                        json.dumps(row["steps"]), row["outcome"]))
            db.commit()
    except (sqlite3.Error, OSError) as exc:
        log.warning("remove audit not saved: %s", type(exc).__name__)


def recent(limit: int = 30) -> list[dict]:
    db = media_store.reader()
    if db is None:
        return []
    try:
        with closing(db):
            return [dict(r) for r in db.execute("SELECT * FROM media_removals ORDER BY id DESC LIMIT ?", (limit,))]
    except sqlite3.Error:
        return []


def discord_line(title: str, kind: str, done: str, outcome: str) -> str:
    app = _app(kind)
    tail = {"stopped": f"{app} stopped searching", "ondisk": f"already on disk, {app} left as it is",
            "arrfail": f"couldn't stop the {app} search", "arrunset": f"{app} not connected",
            "removed": None}.get(done)
    head = "Joey Media: removed the request for " if outcome == "done" else "Joey Media: remove partly failed for "
    safe = title.replace("@", "@​")   # a title can never ping: @everyone, @here, <@id>, <@&role> are broken up
    return head + safe + (f" · {tail}" if tail else "") + " · nothing on disk deleted"


def _notify(text: str) -> None:
    """One Discord message that may mention nobody (`allowed_mentions: {parse: []}`, the belt to the escaping's
    braces). Never raises; logs an HTTP status or an exception type only (the webhook URL is a secret)."""
    url = server_alerts.webhook()
    if not url:
        return
    try:
        resp = requests.post(url, json={"content": text[:1900], "allowed_mentions": {"parse": []}},
                             timeout=server_alerts.TIMEOUT)
    except Exception as exc:
        log.warning("discord push failed: %s", type(exc).__name__)
        return
    if not 200 <= resp.status_code < 300:
        log.warning("discord push refused: HTTP %s", resp.status_code)


def _to(kind: str, tmdb: int, **params) -> RedirectResponse:
    return RedirectResponse(f"{PAGE}/{kind}/{tmdb}?" + urlencode(params), status_code=303)


@router.post(PAGE + "/{kind}/{tmdb_id}", dependencies=[Depends(same_origin)])
async def remove_post(request: Request, kind: str, tmdb_id: int):
    if kind not in KINDS or tmdb_id <= 0 or not can_remove(request):
        return shell.not_found_page(request)
    body = await request.body()
    form = parse_qs(body[:MAX_BODY].decode("utf-8", "replace"), keep_blank_values=True)
    return await run_in_threadpool(_remove, kind, tmdb_id, form)


def _remove(kind: str, tmdb: int, form: dict[str, list[str]]):
    scope = (form.get("scope") or [""])[-1]
    if scope not in SCOPES:
        return _to(kind, tmdb, error="scope")
    if scope == "whole":
        return _remove_whole(kind, tmdb, form)
    raw = (form.get("rids") or [""])[-1]
    posted = sorted({int(x) for x in raw.split(",") if x.isascii() and x.isdigit() and 0 < len(x) <= 9})
    if not _lock.acquire(blocking=False):
        return _to(kind, tmdb, error="busy")
    try:
        rows = rows_for(kind, tmdb)
        if not posted or posted != sorted(r["id"] for r in rows):
            return _to(kind, tmdb, error="changed", step="confirm", scope="request")
        ok, until = _rate_ok(time.monotonic())
        if not ok:
            return _to(kind, tmdb, error="rate", at=_clock_at(until))
        return _remove_rows(kind, tmdb, rows)
    finally:
        _lock.release()


def _remove_rows(kind: str, tmdb: int, rows: list[dict]):
    live: dict[int, dict | None] = {}
    for r in rows:   # the fresh re-read: every request first, so a refusal sends nothing
        code, body = _seerr_read(r["id"])
        if code in ("unset", "unreachable", "refused"):
            return _to(kind, tmdb, error=code)
        if code == "ok" and not _same_title(body, kind, tmdb):
            return _to(kind, tmdb, error="changed", step="confirm", scope="request")
        live[r["id"]] = body
    title = _title(rows)
    tvdb = next((r["tvdb_id"] for r in rows if isinstance(r.get("tvdb_id"), int)), None)
    steps, removed = [], []
    for r in rows:
        if live[r["id"]] is None:
            steps.append({"app": "seerr", "step": f"request {r['id']}", "outcome": "already gone"})
            removed.append(r)
            continue
        code, status = mr.delete_request(r["id"])
        steps.append({"app": "seerr", "step": f"delete request {r['id']}",
                      "outcome": "ok" if code is None else (f"HTTP {status}" if status else code)})
        if code is None:
            removed.append(r)
    for r in removed:
        media_hidden.hide(mr.GROUP, r["id"])
    if removed:
        md._cache.pop(f"film:/api/v1/{kind}/{tmdb}", None)   # the title page re-reads its status
        mr.forget_lookups()
    done = None
    if removed:
        on_disk = any(r.get("status_text") in mr.ON_DISK_WORDS for r in rows) or any(
            isinstance(b, dict) and isinstance(b.get("media"), dict) and b["media"].get("status") in SEERR_ON_DISK
            for b in live.values())
        done = "ondisk" if on_disk else mr.stop_search(kind, tmdb, tvdb)
        app = "radarr" if kind == "movie" else "sonarr"
        steps.append({"app": app, "step": "unmonitor", "outcome": {"stopped": "ok", "ondisk": "skipped: on disk",
                      "removed": "skipped: not in the app", "arrfail": "failed", "arrunset": "not connected"}[done]})
    outcome = "done" if len(removed) == len(rows) else "partial" if removed else "failed"
    record({"owner": "you", "front": guest.front(), "kind": kind, "tmdb_id": tmdb, "tvdb_id": tvdb, "title": title,
            "scope": "request", "request_ids": [r["id"] for r in rows], "steps": steps, "outcome": outcome})
    if outcome == "failed":
        last = steps[-1]["outcome"]
        return _to(kind, tmdb, error="unreachable" if last == "unreachable" else "refused")
    _notify(discord_line(title, kind, done, outcome))
    if outcome == "partial":
        return _to(kind, tmdb, done="partial")
    return _to(kind, tmdb, done=done, **({"app": "radarr" if kind == "movie" else "sonarr"} if done != "removed" else {}))


# ---- phase 2: the whole film or show ----

def _rate_whole(now: float) -> tuple[bool, float | None]:
    """Both limits at once: at most RATE_MAX removes and WHOLE_MAX whole-title removes per rolling hour."""
    with _times_lock:
        for q in (_times, _whole_times):
            while q and now - q[0] >= RATE_WINDOW_S:
                q.popleft()
        for q, cap in ((_times, RATE_MAX), (_whole_times, WHOLE_MAX)):
            if len(q) >= cap:
                return False, q[0] + RATE_WINDOW_S
        _times.append(now)
        _whole_times.append(now)
        return True, None


def _ints(raw: str) -> list[int]:
    return sorted({int(x) for x in raw.split(",") if x.isascii() and x.isdigit() and 0 < len(x) <= 12})


def _remove_whole(kind: str, tmdb: int, form: dict[str, list[str]]):
    app = "radarr" if kind == "movie" else "sonarr"
    again = {"step": "confirm", "scope": "whole", "app": app}

    def one(k):
        return (form.get(k) or [""])[-1]

    disk = disk_for(kind, tmdb)
    if disk is None:
        return _to(kind, tmdb, error="changed")
    typed = whole.norm(one("typed"))
    if not typed or typed not in (whole.norm(disk.get("title")), whole.norm(_disk_title(disk))):
        return _to(kind, tmdb, error="typed", **again)   # Q5 A: the strong confirm; nothing read or sent
    if not _lock.acquire(blocking=False):
        return _to(kind, tmdb, error="busy")
    try:
        entry, code = _live_whole(kind, tmdb, disk)
        if entry is None:
            return _to(kind, tmdb, error=code, **({} if code == "changed" else {"app": app}))
        if (one("arr_id") != str(entry["id"]) or _ints(one("fids")) != entry["files"]
                or one("bytes") != str(entry["bytes"])):
            return _to(kind, tmdb, error="changed", **again)
        try:
            if whole.watching(kind, tmdb, entry.get("path")):
                return _to(kind, tmdb, error="watching")
        except whole.Unreachable:
            return _to(kind, tmdb, error="jfdown")
        ok, until = _rate_whole(time.monotonic())
        if not ok:
            return _to(kind, tmdb, error="rate", at=_clock_at(until))
        rows = rows_for(kind, tmdb)
        tvdb = disk.get("tvdb_id") if isinstance(disk.get("tvdb_id"), int) else None
        result, steps, told = whole.run(kind, tmdb, tvdb, entry, rows)
        outcome = {"slow": "partial", "unsure": "partial"}.get(result, result)
        if result not in ("failed", "unsure"):
            media_hidden.hide(DISK_GROUP, f"{kind}:{tmdb}")
            for r in rows:
                media_hidden.hide(mr.GROUP, r["id"])
        title = _disk_title(disk)
        record({"owner": "you", "front": guest.front(), "kind": kind, "tmdb_id": tmdb, "tvdb_id": tvdb, "title": title,
                "scope": "whole", "picked": ["whole"], "files": len(entry["files"]), "bytes": entry["bytes"],
                "request_ids": [r["id"] for r in rows], "steps": steps, "outcome": outcome})
        if outcome == "failed":
            return _to(kind, tmdb, error="deletefail", app=app)
        safe = title.replace("@", "@\u200b")   # a title can never ping (as discord_line)
        _notify(f"Joey Media: removed {safe} ({size_words(entry['bytes'])}) · " + {
            "done": "recycle bin 7 days", "slow": "recycle bin 7 days (slow answer)",
            "unsure": "no answer from the app, check it"}.get(result, "Seerr not cleared"))
        if result in ("slow", "unsure", "partial"):
            return _to(kind, tmdb, error="whole" + result, app=app)
        return _to(kind, tmdb, done="whole" if told else "wholelate", app=app)
    finally:
        _lock.release()
