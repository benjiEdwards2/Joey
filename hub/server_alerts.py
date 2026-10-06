"""Server → Discord push of NEW Attention items (WP-U2, 2026-10-06).

Every Attention item (hub/server.py `attention_items`) carries a stable key (`down:prowlarr`,
`disk:/volume1`, `kuma:Prowlarr`, `sweep:wud`, `backup`). `media.db` table
`server_attention_seen(key, first_seen, last_seen, notified_at)` remembers which keys are
current: a key with no `notified_at` gets ONE plain Discord message "Joey Server: <text>"
(at most 5 per cycle, 10 s timeout), and a key that leaves Attention loses its row so a
recurrence notifies again.

Runs on two paths: after each `/server` render (a response background task) and on the
hub's own loop (`lifespan` in hub/main.py, the media_backup pattern: first check ~60 s
after startup, then every 5 min). `SERVER_DISCORD_WEBHOOK` unset ⇒ nothing at all (no
call, no table writes). Failures log the exception type / HTTP status only — the webhook
URL is the credential and never appears in a log or on a page.
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
FIRST_DELAY_S = 60
EVERY_S = 300
PREFIX = "Joey Server: "

DDL = """CREATE TABLE IF NOT EXISTS server_attention_seen(
  key TEXT PRIMARY KEY, first_seen TEXT, last_seen TEXT, notified_at TEXT)"""

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


def sync(items: list[dict], now: datetime | None = None) -> int:
    """Reconcile `items` ([{key, text}]) with server_attention_seen and push new ones.
    Returns the number of messages sent. No webhook ⇒ 0, untouched. Never raises."""
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
                db.execute(DDL)
                rows = {r["key"]: r["notified_at"] for r in
                        db.execute("SELECT key, notified_at FROM server_attention_seen")}
                with db:
                    for key in set(rows) - set(current):
                        db.execute("DELETE FROM server_attention_seen WHERE key = ?", (key,))
                    for key in current:
                        db.execute("INSERT INTO server_attention_seen(key, first_seen, last_seen) "
                                   "VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET "
                                   "last_seen = excluded.last_seen", (key, stamp, stamp))
                for key, text in current.items():
                    if rows.get(key) or tried >= MAX_PER_CYCLE:
                        continue  # already pushed, or capped (the rest go next cycle)
                    tried += 1
                    if post(url, PREFIX + text):
                        sent += 1
                        with db:
                            db.execute("UPDATE server_attention_seen SET notified_at = ? "
                                       "WHERE key = ?", (stamp, key))
        except (sqlite3.Error, OSError) as exc:
            log.warning("server attention sync failed: %s", type(exc).__name__)
    return sent


def check_once() -> int:
    """Build Attention from the current snapshots (as /server does) and sync it."""
    if not webhook():
        return 0
    from hub import media_backup, server
    from hub.store import get_runner, get_runner_history, get_snapshots

    items = server.attention_items(get_snapshots(), media_backup.current_status(), get_runner(),
                                   server.sweep_stats(get_runner_history()))
    return sync(items)
