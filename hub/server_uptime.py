"""Server → 7-day uptime per service (JY-133, P7, 2026-10-26; built as option A for B.'s pick).

Derived from the cached `uptime_kuma` snapshot only — no Kuma call. media.db table `server_kuma_samples(ts, states)`
holds one row per new snapshot, keyed by the envelope's `updated_at` (UTC `YYYY-MM-DDTHH:MM:SSZ`, the WP-U4 rule of
hub/server_history.py): `states` is JSON {monitor name: up|down|pending|maintenance}. Names and states only: the
connector already drops URLs, hosts and ports, and nothing else is copied. Each insert prunes rows older than 8 days.

`tick(snaps)` samples and then sums the last 7 days into memory. One writer: it runs only on the hub's 5-minute
Server loop (hub/tasks.py), so the table gets at most one row per 5 minutes (about 1,440 rows over 8 days while the
NAS is on 07:00-22:00). The render reads only `peek()`: no media.db read, no network. The sum reads the table over a
read-only connection. Up % = up / (up + down) samples; pending and maintenance count neither way. The NAS is off
22:00-07:00, so 7 days means the hours it was on. Never raises.
"""

from __future__ import annotations

import json
import logging
import math
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone

from hub import media_db
from hub.ids import UPTIME_KUMA_SNAPSHOT_ID
from hub.store import ago_text, parse_utc

log = logging.getLogger("hub.server_uptime")

RETAIN = timedelta(days=8)
WINDOW = timedelta(days=7)
STATES = ("up", "down", "pending", "maintenance")

DDL = "CREATE TABLE IF NOT EXISTS server_kuma_samples(ts TEXT PRIMARY KEY, states TEXT)"

_summary: dict | None = None   # {monitor name lowercased: {pct, days, last_down}}; None until the first refresh


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def sample(snaps) -> bool:
    """Store the current `uptime_kuma` snapshot (from the caller's snapshot read: this module never reads the store, so
    it stays off the media front's reader list) if it is new. True when a row was inserted."""
    snap = (snaps or {}).get(UPTIME_KUMA_SNAPSHOT_ID)
    if snap is None or snap.status != "ok" or not isinstance(snap.data, dict):
        return False
    states = {str(m["name"]): m["status"] for m in snap.data.get("monitors") or []
              if isinstance(m, dict) and m.get("name") and m.get("status") in STATES}
    at = parse_utc(snap.updated_at)
    if not states or at is None:
        return False
    ts = _iso(at)
    try:
        with closing(media_db.connect()) as db:
            db.execute(DDL)
            last = db.execute("SELECT MAX(ts) FROM server_kuma_samples").fetchone()[0]
            if last is not None and ts <= last:
                return False
            with db:
                db.execute("INSERT OR IGNORE INTO server_kuma_samples(ts, states) VALUES(?, ?)",
                           (ts, json.dumps(states, sort_keys=True)))
                db.execute("DELETE FROM server_kuma_samples WHERE ts < ?", (_iso(at - RETAIN),))
            return True
    except (sqlite3.Error, OSError) as exc:
        log.warning("kuma uptime sample failed: %s", type(exc).__name__)
        return False


def _read_rows(now: datetime) -> list[tuple[datetime, dict]]:
    """The last 7 days of samples, oldest first. No media.db (or unreadable) ⇒ []. Never creates it."""
    if not media_db.db_path().is_file():
        return []
    out = []
    try:
        with closing(sqlite3.connect(f"{media_db.db_path().as_uri()}?mode=ro", uri=True)) as db:
            for ts, states in db.execute("SELECT ts, states FROM server_kuma_samples WHERE ts >= ? ORDER BY ts",
                                         (_iso(now - WINDOW),)):
                at = parse_utc(ts)
                try:
                    st = json.loads(states or "{}")
                except ValueError:
                    continue
                if at is not None and isinstance(st, dict):
                    out.append((at, st))
    except sqlite3.OperationalError:
        return []   # no table yet: nothing sampled since JY-133
    except (sqlite3.Error, OSError) as exc:
        log.warning("kuma uptime unreadable: %s", type(exc).__name__)
        return []
    return out


def summary(rows: list[tuple[datetime, dict]], now: datetime) -> dict:
    """rows (oldest first) -> {monitor name lowercased: {pct, days, last_down}} over the last 7 days. A monitor with
    no up or down sample in the window is left out."""
    rows = [(at, st) for at, st in rows if at >= now - WINDOW]
    if not rows:
        return {}
    days = min(WINDOW.days, (now - rows[0][0]).total_seconds() / 86400)
    counts: dict[str, dict] = {}
    for at, states in rows:
        for name, state in states.items():
            c = counts.setdefault(str(name).strip().lower(), {"up": 0, "down": 0, "last_down": None})
            if state == "up":
                c["up"] += 1
            elif state == "down":
                c["down"] += 1
                c["last_down"] = at
    return {name: {"pct": 100 * c["up"] / (c["up"] + c["down"]), "days": days, "last_down": c["last_down"]}
            for name, c in counts.items() if c["up"] + c["down"]}


def words(u: dict | None, now: datetime | None = None) -> str | None:
    """'100% up · 7 days', '99.4% up · 3 days · down 5h ago', '100% up · today'. Never '100%' after a down sample."""
    if not u:
        return None
    pct = u["pct"]
    if pct >= 100:
        text = "100%"
    else:
        p = min(99.9, math.floor(pct * 10) / 10)
        text = f"{p:g}%"
    d = u["days"]
    span = "today" if d < 1 else f"{min(WINDOW.days, round(d))} day{'' if round(d) == 1 else 's'}"
    out = f"{text} up · {span}"
    if u.get("last_down") is not None:
        out += " · down " + ago_text(((now or _now()) - u["last_down"]).total_seconds() / 60)
    return out


def refresh(now: datetime | None = None) -> dict:
    """Sum the last 7 days into memory (the hub loop)."""
    global _summary
    now = now or _now()
    _summary = summary(_read_rows(now), now)
    return _summary


def tick(snaps) -> None:
    """Sample, then refresh. Never raises."""
    try:
        sample(snaps)
        refresh()
    except Exception as exc:  # noqa: BLE001 - the page and the loop must never fail on uptime
        log.warning("kuma uptime tick failed: %s", type(exc).__name__)


def peek() -> dict:
    """The render's read: the cached sum, or {} before the first refresh. Never touches media.db."""
    return _summary or {}


def clear() -> None:
    """Forget the cached sum (tests)."""
    global _summary
    _summary = None
