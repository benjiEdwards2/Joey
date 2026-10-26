"""Server → "Since your last visit" (JY-134, P8, 2026-10-26; built as option A for B.'s pick).

One sentence under the Server head for the signed-in viewer ("you" or "her"; no identity = nothing): what changed
since their previous visit, from stored data only — Joey's own update runs (`server_update_runs`, already read by
the page as `last_requested`) and the connectors' runner history (already in memory, JY-226). No live call.

media.db table `server_last_visit(owner, since, last_seen)`: a visit starts when the viewer opens Server more than
GAP after their last view; `since` is then the end of the previous visit and holds for the whole visit, so a reload
keeps the sentence. The row is written after the page (`touch`, a response background task); the render only reads
it (`since_for`, one primary-key SELECT). The sweep scan is kept per viewer, visit and history list.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from contextlib import closing
from datetime import datetime, timedelta, timezone

from hub import media_db
from hub import server as _server
from hub.store import ago_text, parse_utc

log = logging.getLogger("hub.server_visits")

GAP = timedelta(minutes=30)
OWNERS = ("you", "her")
DDL = "CREATE TABLE IF NOT EXISTS server_last_visit(owner TEXT PRIMARY KEY, since TEXT, last_seen TEXT)"

_memo_lock = threading.Lock()
_memo: dict = {}   # owner -> {"key": (since, id(history), len(history)), "feeds": [...]}


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _row(owner: str):
    """(since, last_seen) as datetimes, or None (no row, no table yet, no media.db, unreadable). Read only: never
    creates media.db or the table."""
    if not media_db.db_path().is_file():
        return None
    try:
        with closing(sqlite3.connect(f"{media_db.db_path().as_uri()}?mode=ro", uri=True)) as db:
            row = db.execute("SELECT since, last_seen FROM server_last_visit WHERE owner = ?", (owner,)).fetchone()
    except sqlite3.OperationalError:
        return None   # no table yet: nobody has visited since JY-134
    except sqlite3.Error as exc:
        log.warning("last visit unreadable: %s", type(exc).__name__)
        return None
    return (parse_utc(row[0]), parse_utc(row[1])) if row else None


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
    """After the page: record this view. A new visit moves `since` to the previous view. Never raises."""
    if owner not in OWNERS:
        return
    now = now or _now()
    try:
        with closing(media_db.connect()) as db, db:
            db.execute(DDL)
            row = db.execute("SELECT since, last_seen FROM server_last_visit WHERE owner = ?", (owner,)).fetchone()
            last = parse_utc(row[1]) if row else None
            since = row[0] if row and last is not None and now - last <= GAP else (row[1] if row else None)
            db.execute("INSERT OR REPLACE INTO server_last_visit(owner, since, last_seen) VALUES(?, ?, ?)",
                       (owner, since, _iso(now)))
    except (sqlite3.Error, OSError) as exc:
        log.warning("last visit write failed: %s", type(exc).__name__)


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


def _updated(requested: dict | None, since: datetime) -> str | None:
    runs = sorted((at, name) for name, run in (requested or {}).items()
                  if (at := parse_utc((run or {}).get("requested_at"))) is not None and at > since)
    names = [name for _, name in runs]
    if not names:
        return None
    if len(names) == 1:
        return f"{names[0]} was updated"
    if len(names) == 2:
        return f"{names[0]} and {names[1]} were updated"
    return f"{names[0]}, {names[1]} and {len(names) - 2} more were updated"


def sentence(owner: str | None, since: datetime | None, requested: dict | None, history, live=None,
             now: datetime | None = None) -> str | None:
    """'Since your last visit 2d ago: sonarr was updated · wud failed 3 times, then recovered.' / '…: nothing
    changed.' None without a visit to compare with."""
    if owner not in OWNERS or since is None:
        return None
    now = now or _now()
    key = (_iso(since), id(history), len(history or []))
    with _memo_lock:
        kept = _memo.get(owner)
        if kept is None or kept["key"] != key:
            kept = _memo[owner] = {"key": key, "feeds": _feeds(history, since, live)}
        feeds = list(kept["feeds"])
    parts = [p for p in (_updated(requested, since), *feeds) if p]
    head = f"Since your last visit {ago_text((now - since).total_seconds() / 60)}: "
    return head + (" · ".join(parts) if parts else "nothing changed") + "."


def clear() -> None:
    """Forget the kept scans (tests)."""
    with _memo_lock:
        _memo.clear()
