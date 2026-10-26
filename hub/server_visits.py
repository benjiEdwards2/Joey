"""Server → "Since your last visit" (JY-134, P8, 2026-10-26; built as option A for B.'s pick).

One sentence under the Server head for the signed-in viewer ("you" or "her"; no identity = nothing): what changed
since their previous visit, from stored data only — Joey's own update runs (`server_update_runs`, already read by
the page as `last_requested`) that have completed (the cached WUD snapshot no longer lists an update for that
container), and the connectors' runner history (already in memory, JY-226). No live call.

media.db table `server_last_visit(owner, since, last_seen)`: a visit starts when the viewer opens Server more than
GAP after their last view; `since` is then the end of the previous visit and holds for the whole visit, so a reload
keeps the sentence. The rows are read once per media.db path and kept in memory: a render opens no connection.
`touch` (after the page, a response background task; the only writer, the hub being one process) updates the kept
row on every view, so the next visit always starts at the real last view; it commits to media.db only on a new visit
or once a minute, and `flush` (the hub's shutdown) commits the rest. After a restart without that flush the stored
last_seen is at most a minute behind. The sweep scan is kept per viewer, visit and newest history line.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from contextlib import closing
from datetime import datetime, timedelta, timezone

from hub import media_db
from hub import server as _server
from hub.ids import WUD_SNAPSHOT_ID
from hub.store import ago_text, parse_utc

log = logging.getLogger("hub.server_visits")

GAP = timedelta(minutes=30)
TOUCH_EVERY = timedelta(minutes=1)   # within a visit, last_seen is written at most once a minute
OWNERS = ("you", "her")
DDL = "CREATE TABLE IF NOT EXISTS server_last_visit(owner TEXT PRIMARY KEY, since TEXT, last_seen TEXT)"

_memo_lock = threading.Lock()
_memo: dict = {}   # owner -> {"key": (since, the newest history line's ran_at), "feeds": [...]}
_rows_lock = threading.Lock()
_kept: dict | None = None   # {"path": media.db path, "rows": {owner: (since, last_seen)}}
_written: dict = {}         # owner -> the last_seen last committed to media.db


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _row(owner: str):
    """(since, last_seen) as datetimes, or None (no row, no table yet, no media.db, unreadable). The table is read
    once per media.db path (read only: never creates media.db or the table), then served from memory."""
    global _kept
    path = str(media_db.db_path())
    with _rows_lock:
        if _kept is not None and _kept["path"] == path:
            return _kept["rows"].get(owner)
    if not media_db.db_path().is_file():
        return None
    try:
        with closing(sqlite3.connect(f"{media_db.db_path().as_uri()}?mode=ro", uri=True)) as db:
            rows = db.execute("SELECT owner, since, last_seen FROM server_last_visit").fetchall()
    except sqlite3.OperationalError:
        rows = []   # no table yet: nobody has visited since JY-134
    except sqlite3.Error as exc:
        log.warning("last visit unreadable: %s", type(exc).__name__)
        return None
    with _rows_lock:
        _kept = {"path": path, "rows": {o: (parse_utc(s), parse_utc(ls)) for o, s, ls in rows}}
        return _kept["rows"].get(owner)


def since_for(owner: str | None, now: datetime | None = None) -> datetime | None:
    """The render's read: the start point of this viewer's current visit, or None (no identity, first visit)."""
    if owner not in OWNERS:
        return None
    row = _row(owner)
    if row is None or row[1] is None:
        return None
    since, last_seen = row
    return last_seen if (now or _now()) - last_seen > GAP else since


def touch(owner: str | None, now: datetime | None = None) -> None:
    """After the page: record this view in memory; a new visit moves `since` to the previous view. Commits on a new
    visit or once a minute. Never raises."""
    if owner not in OWNERS:
        return
    now = now or _now()
    prev = _row(owner)   # the kept copy: every view updates it, so last_seen is never behind the real last view
    since = prev[0] if prev and prev[1] is not None and now - prev[1] <= GAP else (prev[1] if prev else None)
    with _rows_lock:
        if _kept is not None and _kept["path"] == str(media_db.db_path()):
            _kept["rows"][owner] = (since, now)
        last_write = _written.get(owner)
        due = prev is None or since != prev[0] or last_write is None or not timedelta(0) <= now - last_write < TOUCH_EVERY
    if due:   # a new visit, or a minute since the last write: commit (a reload storm never queues commits)
        _write(owner, since, now)


def _write(owner: str, since: datetime | None, last_seen: datetime) -> None:
    global _kept
    try:
        with closing(media_db.connect()) as db, db:
            db.execute(DDL)
            db.execute("INSERT OR REPLACE INTO server_last_visit(owner, since, last_seen) VALUES(?, ?, ?)",
                       (owner, _iso(since) if since else None, _iso(last_seen)))
        with _rows_lock:
            _written[owner] = last_seen
            if _kept is None or _kept["path"] != str(media_db.db_path()):
                _kept = None   # media.db was just created (or moved): the next read loads the table once
    except (sqlite3.Error, OSError) as exc:
        log.warning("last visit write failed: %s", type(exc).__name__)


def flush() -> None:
    """Write every kept last_seen newer than its last write (the hub's shutdown hook). Never raises."""
    with _rows_lock:
        rows = dict(_kept["rows"]) if _kept is not None and _kept["path"] == str(media_db.db_path()) else {}
        dirty = [(o, s, ls) for o, (s, ls) in rows.items() if ls is not None and _written.get(o) != ls]
    for owner, since, last_seen in dirty:
        _write(owner, since, last_seen)


def _feeds(history, since: datetime, live) -> list[str]:
    """Connectors with a failed sweep after `since` whose latest sweep is OK, as words, oldest failure first."""
    seen: dict[str, dict] = {}
    for at, line in _server._usable_lines(history or []):   # history order: oldest first
        if at <= since:
            continue
        for cid, res in line["results"].items():
            if not isinstance(res, dict):
                continue
            st = seen.setdefault(str(cid), {"fails": 0, "failing": False, "reason": None})
            st["failing"] = res.get("status") == "error"
            if st["failing"]:
                st["fails"] += 1
                st["reason"] = _server._reason(res)
    out = []
    for cid, st in seen.items():
        if st["fails"] and not st["failing"] and not _server.not_configured(cid, st["reason"], live):
            times = "once" if st["fails"] == 1 else f"{st['fails']} times"
            out.append(f"{cid} failed {times}, then recovered")
    return out


def waiting_updates(snaps) -> set[str] | None:
    """Container names the cached WUD snapshot still lists with an update; None when WUD is not readable (then no
    update is called done)."""
    snap = (snaps or {}).get(WUD_SNAPSHOT_ID)
    if snap is None or snap.status != "ok" or not isinstance(snap.data, dict):
        return None
    return {str(c.get("name")) for c in snap.data.get("containers") or []
            if isinstance(c, dict) and c.get("update_available")}


def _updated(requested: dict | None, since: datetime, waiting: set[str] | None) -> str | None:
    """Update now / Update all requests after `since` that have completed: WUD no longer lists an update for that
    container. A request still waiting, or any request while WUD is unreadable, is not "updated"."""
    if waiting is None:
        return None
    runs = sorted((at, name) for name, run in (requested or {}).items()
                  if (at := parse_utc((run or {}).get("requested_at"))) is not None and at > since
                  and name not in waiting)
    names = [name[:1].upper() + name[1:] for _, name in runs]
    if not names:
        return None
    if len(names) == 1:
        return f"{names[0]} was updated"
    if len(names) == 2:
        return f"{names[0]} and {names[1]} were updated"
    return f"{names[0]}, {names[1]} and {len(names) - 2} more were updated"


def sentence(owner: str | None, since: datetime | None, requested: dict | None, history, live=None,
             now: datetime | None = None, waiting: set[str] | None = None) -> str | None:
    """'Since your last visit 2d ago: Sonarr was updated · wud failed 3 times, then recovered.' / '…: nothing
    changed.' None without a visit to compare with. `waiting`: waiting_updates(snaps)."""
    if owner not in OWNERS or since is None:
        return None
    now = now or _now()
    newest = history[-1] if history else None
    key = (_iso(since), newest.get("ran_at") if isinstance(newest, dict) else None)
    with _memo_lock:
        kept = _memo.get(owner)
        if kept is None or kept["key"] != key:
            kept = _memo[owner] = {"key": key, "feeds": _feeds(history, since, live)}
        feeds = list(kept["feeds"])
    parts = [p for p in (_updated(requested, since, waiting), *feeds) if p]
    head = f"Since your last visit {ago_text((now - since).total_seconds() / 60)}: "
    return head + (" · ".join(parts) if parts else "nothing changed") + "."


def clear() -> None:
    """Forget the kept scans and visit rows (tests)."""
    global _kept
    with _memo_lock:
        _memo.clear()
    with _rows_lock:
        _kept = None
        _written.clear()
