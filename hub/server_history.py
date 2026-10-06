"""Server → host-health history (WP-U4, 2026-10-06): the `system` snapshot, sampled into media.db.

Derived from snapshots only — no new live call. media.db table `server_system_samples(ts, cpu_pct,
ram_pct_used, ram_free_gb, load_1m, volumes)` holds one row per `system` snapshot, keyed by the
envelope's `updated_at` (UTC, `YYYY-MM-DDTHH:MM:SSZ`): a row is inserted only when that stamp is
newer than the last stored one, so the 2-minute feed gives at most one row per snapshot and
repeated `/server` renders never duplicate. `volumes` is JSON `[{path, pct_used, free_gb}]`;
`pct_used` is recomputed from free/total to two decimals when both are present (the envelope's own
integer would hide a slow disk trend). Each insert prunes rows older than 8 days. No sample when the
snapshot is missing, empty or `status != ok`.

Runs on the WP-U2 paths: after each `/server` render (a response background task) and on the
hub's 5-minute Server loop (`_server_alerts_loop` in hub/main.py). Never raises.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone

from hub import media_db

log = logging.getLogger("hub.server_history")

SYSTEM_SNAPSHOT_ID = "system"
RETAIN = timedelta(days=8)

DDL = """CREATE TABLE IF NOT EXISTS server_system_samples(
  ts TEXT PRIMARY KEY, cpu_pct REAL, ram_pct_used INTEGER, ram_free_gb REAL, load_1m REAL,
  volumes TEXT)"""


def ensure(db) -> None:
    db.execute(DDL)
    db.commit()


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(stamp) -> datetime | None:
    try:
        at = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    return at if at.tzinfo else at.replace(tzinfo=timezone.utc)


def _num(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _volumes(data: dict) -> list[dict]:
    out = []
    for v in data.get("volumes") or []:
        if not isinstance(v, dict) or v.get("path") is None:
            continue
        free, total, pct = _num(v.get("free_gb")), _num(v.get("total_gb")), _num(v.get("pct_used"))
        if free is not None and total:
            pct = round((1 - free / total) * 100, 2)
        out.append({"path": str(v["path"]), "pct_used": pct, "free_gb": free})
    return out


def sample(snaps=None) -> bool:
    """Store the current `system` snapshot if it is new. True when a row was inserted."""
    if snaps is None:
        from hub.store import get_snapshots
        snaps = get_snapshots()
    snap = (snaps or {}).get(SYSTEM_SNAPSHOT_ID)
    if snap is None or snap.status != "ok" or not isinstance(snap.data, dict) or not snap.data:
        return False
    at = _parse(snap.updated_at)
    if at is None:
        return False
    ts, d = _iso(at), snap.data
    ram = d.get("ram_pct_used")
    try:
        with closing(media_db.connect()) as db:
            ensure(db)
            last = db.execute("SELECT MAX(ts) FROM server_system_samples").fetchone()[0]
            if last is not None and ts <= last:
                return False
            with db:
                db.execute("INSERT OR IGNORE INTO server_system_samples"
                           "(ts, cpu_pct, ram_pct_used, ram_free_gb, load_1m, volumes) "
                           "VALUES(?,?,?,?,?,?)",
                           (ts, _num(d.get("cpu_pct")), int(ram) if _num(ram) is not None else None,
                            _num(d.get("ram_free_gb")), _num(d.get("load_1m")),
                            json.dumps(_volumes(d))))
                db.execute("DELETE FROM server_system_samples WHERE ts < ?", (_iso(at - RETAIN),))
            return True
    except (sqlite3.Error, OSError) as exc:
        log.warning("server history sample failed: %s", type(exc).__name__)
        return False


def recent(now: datetime | None = None, days: int = 7) -> list[dict]:
    """Samples of the last `days` days, oldest first: {at (datetime), cpu_pct, ram_pct_used,
    ram_free_gb, load_1m, volumes (list)}. No media.db (or unreadable) ⇒ []. Never creates it."""
    if not media_db.db_path().is_file():
        return []
    since = _iso((now or datetime.now(timezone.utc)) - timedelta(days=days))
    try:
        with closing(media_db.connect()) as db:
            ensure(db)
            rows = db.execute("SELECT * FROM server_system_samples WHERE ts >= ? ORDER BY ts",
                              (since,)).fetchall()
    except (sqlite3.Error, OSError) as exc:
        log.warning("server history unreadable: %s", type(exc).__name__)
        return []
    out = []
    for r in rows:
        try:
            vols = json.loads(r["volumes"] or "[]")
        except ValueError:
            vols = []
        out.append({"at": _parse(r["ts"]), "cpu_pct": r["cpu_pct"], "ram_pct_used": r["ram_pct_used"],
                    "ram_free_gb": r["ram_free_gb"], "load_1m": r["load_1m"],
                    "volumes": [v for v in vols if isinstance(v, dict)]})
    return out
