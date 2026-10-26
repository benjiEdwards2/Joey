"""Server → Discord push of NEW Attention items (WP-U2, 2026-10-06).

Every Attention item (hub/server.py `attention_items`) carries a stable key (`down:prowlarr`,
`disk:/volume1`, `kuma:Prowlarr`, `sweep:wud`, `backup`, and JY-031's `forecast:/volume1`). `media.db` table
`server_attention_seen(key, first_seen, last_seen, notified_at)` remembers which keys are
current: a key with no `notified_at` gets ONE plain Discord message "Joey Server: <text>"
(at most 5 per cycle, 10 s timeout), and a key that leaves Attention loses its row so a
recurrence notifies again. A key whose push failed MAX_FAILS (3) times is not retried while it stays
current (`fails`, 2026-10-09: a permanently refused webhook no longer retries every 5 minutes forever).

WP-U3 (2026-10-07): not-configured connectors (hub/server.py `not_configured`: latest error a
MissingCredential, or no visible area reads the snapshot) never enter Attention, so they are
never posted — and a seen-row left from before is deleted as "item gone", so a later genuine
failure of that connector notifies again.

Runs on two paths: after each `/server` render (a response background task) and on the
hub's own loop (`lifespan` in hub/main.py, the media_backup pattern: first check ~60 s
after startup, then every 5 min). `SERVER_DISCORD_WEBHOOK` unset ⇒ nothing at all (no
call, no table writes). Failures log the exception type / HTTP status only — the webhook
URL is the credential and never appears in a log or on a page.

JY-254 (2026-10-26): boot grace (hub/boot.py). Until the boot health settles - a `media_status` sample taken since the hub
start with every app up, or BOOT_GRACE since the start - `check_once` holds the `down:` items: they are not pushed and
their seen-rows are kept (no new row, no delete), so a pre-boot or still-starting "Down" never alerts and an outage
already pushed before a restart is not pushed again. After the grace a still-down service alerts as before.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
from contextlib import closing
from datetime import datetime, timezone

import requests

from hub import media_db

log = logging.getLogger("hub.server_alerts")

ENV = "SERVER_DISCORD_WEBHOOK"
TIMEOUT = 10
MAX_PER_CYCLE = 5
MAX_FAILS = 3   # H-67: a key whose push failed this often is not retried until it leaves Attention and returns
FIRST_DELAY_S = 60
EVERY_S = 300
PREFIX = "Joey Server: "
FORECAST_PREFIX = "forecast:"   # JY-031: the disk forecast's keys (hub/server.py forecast_item)

DOWN_PREFIX = "down:"   # JY-254: the media_status service items (hub/server.py attention_items)

DDL = """CREATE TABLE IF NOT EXISTS server_attention_seen(
  key TEXT PRIMARY KEY, first_seen TEXT, last_seen TEXT, notified_at TEXT, fails INTEGER NOT NULL DEFAULT 0)"""


def _ensure(db) -> None:
    db.execute(DDL)
    if "fails" not in {r[1] for r in db.execute("PRAGMA table_info(server_attention_seen)")}:
        db.execute("ALTER TABLE server_attention_seen ADD COLUMN fails INTEGER NOT NULL DEFAULT 0")  # pre-2026-10-09

_lock = threading.Lock()  # the render path and the loop must never double-post


def webhook() -> str | None:
    return os.environ.get(ENV, "").strip() or None


def post(url: str, text: str) -> bool:
    """One Discord webhook message. Never raises; logs status/type only."""
    try:
        resp = requests.post(url, json={"content": text[:1900]}, timeout=TIMEOUT)
    except Exception as exc:  # type only — requests errors embed the URL
        log.warning("discord push failed: %s", type(exc).__name__)
        return False
    if 200 <= resp.status_code < 300:
        return True
    log.warning("discord push refused: HTTP %s", resp.status_code)
    return False


def sync(items: list[dict], now: datetime | None = None, keep: tuple[str, ...] = ()) -> int:
    """Reconcile `items` ([{key, text}]) with server_attention_seen and push new ones.
    Returns the number of messages sent. No webhook ⇒ 0, untouched. Never raises. `keep` (JY-031): key prefixes
    whose rows stay even when absent (a forecast that could not be worked out this time is unknown, not gone)."""
    url = webhook()
    if not url:
        return 0
    stamp = (now or datetime.now(timezone.utc)).isoformat()
    current = {}
    for i in items:
        current.setdefault(str(i["key"]), str(i["text"]))
    sent = tried = 0
    with _lock:
        try:
            with closing(media_db.connect()) as db:
                _ensure(db)
                rows = {r["key"]: (r["notified_at"], r["fails"]) for r in
                        db.execute("SELECT key, notified_at, fails FROM server_attention_seen")}
                with db:
                    for key in set(rows) - set(current):
                        if keep and key.startswith(keep):
                            continue
                        db.execute("DELETE FROM server_attention_seen WHERE key = ?", (key,))
                    for key in current:
                        db.execute("INSERT INTO server_attention_seen(key, first_seen, last_seen) "
                                   "VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET "
                                   "last_seen = excluded.last_seen", (key, stamp, stamp))
                for key, text in current.items():
                    notified, fails = rows.get(key, (None, 0))
                    if notified or fails >= MAX_FAILS or tried >= MAX_PER_CYCLE:
                        continue  # already pushed, given up on, or capped (the rest go next cycle)
                    tried += 1
                    if post(url, PREFIX + text):
                        sent += 1
                        with db:
                            db.execute("UPDATE server_attention_seen SET notified_at = ? "
                                       "WHERE key = ?", (stamp, key))
                    else:
                        with db:
                            db.execute("UPDATE server_attention_seen SET fails = fails + 1 WHERE key = ?", (key,))
                        if fails + 1 >= MAX_FAILS:
                            log.warning("discord push: giving up on one item after %d failures", MAX_FAILS)
        except (sqlite3.Error, OSError) as exc:
            log.warning("server attention sync failed: %s", type(exc).__name__)
    return sent


def seen_keys(prefix: str) -> set[str]:
    """Keys in server_attention_seen that start with `prefix` (JY-031: an open disk forecast episode outlives a hub
    restart). No media.db or no table => empty. Never creates the file, never raises."""
    if not media_db.db_path().is_file():
        return set()
    try:
        with closing(media_db.connect()) as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'server_attention_seen'"
                              ).fetchone():
                return set()
            return {r[0] for r in db.execute("SELECT key FROM server_attention_seen WHERE substr(key, 1, ?) = ?",
                                             (len(prefix), prefix))}
    except (sqlite3.Error, OSError) as exc:
        log.warning("server attention seen-rows unreadable: %s", type(exc).__name__)
        return set()


def _live_from_config() -> set[str] | None:
    """`live_snapshot_ids` of the registry on disk (AREAS_PATH or config/areas.yaml); None
    when it cannot load (rule (b) then stays off, rule (a) still applies)."""
    from hub import server
    from hub.ids import areas_path
    from hub.registry import load_registry

    try:
        return server.live_snapshot_ids(load_registry(areas_path()))
    except Exception as exc:
        log.warning("server alerts: registry unavailable: %s", type(exc).__name__)
        return None


def check_once(live: set[str] | None = None, snaps=None, now: datetime | None = None,
               booted: datetime | None = None) -> int:
    """Build Attention from the current snapshots (as /server does) and sync it. `live` is
    `server.live_snapshot_ids(registry)` (hub/main.py passes the loaded one); not-configured
    connectors (WP-U3) are left out, so their seen-rows are purged like any item gone. `snaps`: the
    caller's own read (the hub loop shares one with server_history.sample), else read here. The disk forecast is
    the hub loop's cached item (JY-031, server_history.forecast), as on the hub card and the /server render.
    JY-254: `now` / `booted` (default the clock / hub/boot.py STARTED) set the boot grace that holds the `down:` items."""
    if not webhook():
        return 0
    from hub import boot, media_backup, server, server_history
    from hub.store import get_runner, get_runner_history, get_snapshots

    if live is None:
        live = _live_from_config()
    forecast, keep = forecast_or_keep(server_history.forecast)
    snaps = get_snapshots() if snaps is None else snaps
    items = server.attention_items(snaps, media_backup.current_status(),
                                   get_runner(),
                                   server.sweep_stats(get_runner_history()), live, forecast)
    if not boot.settled(snaps, now, booted):   # JY-254: hold the boot's "Down"s, keep their seen-rows
        items = [i for i in items if not str(i["key"]).startswith(DOWN_PREFIX)]
        keep = (*keep, DOWN_PREFIX)
    return sync(items, keep=keep) if keep else sync(items)


def forecast_or_keep(read, *args) -> tuple[dict | None, tuple[str, ...]]:
    """(the cached forecast item, ()) from `read(*args)`; when it raises (a failed first compute), (None, the forecast
    prefix) with one log line naming the error type only, so the other alerts still go and the forecast's seen-row
    stays (JY-031 fix round)."""
    try:
        return read(*args), ()
    except Exception as exc:
        log.warning("disk forecast skipped this time: %s", type(exc).__name__)
        return None, (FORECAST_PREFIX,)
