"""Overnight digest to Discord (P2, 2026-10-22): ONE plain message a day, built from the snapshots the hub
already holds — "Joey digest · Thu 23 Oct · Arrived: 3 episodes, 1 film · 1 update pending · Disk 71 % ·
All 11 services up · 2 torrents stalled".

`build(snaps, now)` is pure: a part whose snapshot is missing is left out, no parts at all ⇒ None (no message).
`tick(now=None)` runs on the hub loop (hub/tasks.py, every 5 min): it sends once per hub-local day, from
DIGEST_AT (default 07:30) on — the NAS sleeps 22:00–07:00 and the hub starts ~07:00, so a hub that starts at
09:00 still sends that day. The send goes through `server_alerts.post` (never raises, the webhook URL never
logged) to the same webhook as the Server alerts; no webhook ⇒ nothing at all (no call, no table writes).
`media.db` table `server_digest_sent(day, at, text)` holds a row only for a SUCCESSFUL post; a failed post retries
on the next tick, at most MAX_FAILS times per day (in-process count, like server_alerts). `DIGEST=off` stops it.
`last_sent(now)` is the Server page's one line ("Digest · sent 07:31" / "Digest · not sent today").
JY-254 (2026-10-26): boot grace. joey-hub starts with the NAS, so its start time (`STARTED`) is the boot. Until the
boot health settles - a `media_status` sample taken since the start with every app up, or BOOT_GRACE since the start,
whichever comes first - the tick holds, so a digest is never built from pre-boot or still-starting "Down" samples.
After the grace the text is whatever the snapshots say: a service still down shows "Down".
"""

from __future__ import annotations

import logging
import os
import re
import sqlite3
import threading
from contextlib import closing
from datetime import datetime, timedelta, timezone

from hub import media_db, media_store, server, server_alerts
from hub.ids import ARR_SNAPSHOT_ID, MEDIA_STATUS_SNAPSHOT_ID, QBIT_SNAPSHOT_ID, WUD_SNAPSHOT_ID
from hub.store import parse_utc

log = logging.getLogger("hub.server_digest")

ENV_AT = "DIGEST_AT"
ENV_ON = "DIGEST"
DEFAULT_AT = "07:30"
FIRST_DELAY_S = 90
EVERY_S = 300
MAX_FAILS = 3        # failed posts per day before the digest gives up until tomorrow
MAX_CHARS = 300
WINDOW = timedelta(hours=24)
BOOT_GRACE = timedelta(minutes=15)   # JY-254: the longest the digest waits for the boot health to settle
STARTED = datetime.now(timezone.utc)   # JY-254: the hub start = the NAS boot (joey-hub starts with it)

DDL = "CREATE TABLE IF NOT EXISTS server_digest_sent(day TEXT PRIMARY KEY, at TEXT, text TEXT)"

_lock = threading.Lock()      # the loop must never double-post
_fails: dict[str, int] = {}   # local day -> failed posts so far (in-process; a restart gives a fresh try)


def disabled() -> bool:
    return os.environ.get(ENV_ON, "on").strip().lower() == "off"


def send_after() -> tuple[int, int]:
    """DIGEST_AT as (hour, minute); an unreadable value falls back to the default."""
    for raw in (os.environ.get(ENV_AT, ""), DEFAULT_AT):
        m = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", raw)
        if m and int(m[1]) < 24 and int(m[2]) < 60:
            return int(m[1]), int(m[2])
    return 7, 30


def _plural(n: int, one: str) -> str:
    return f"{n} {one}{'' if n == 1 else 's'}"


def _arrived(snaps, now: datetime) -> str | None:
    rows = server._data(snaps, ARR_SNAPSHOT_ID).get("arrived")
    if not isinstance(rows, list):
        return None
    films = episodes = 0
    for r in rows:
        at = parse_utc(r.get("at")) if isinstance(r, dict) else None
        if at is None or not (now - WINDOW <= at <= now):
            continue
        if r.get("kind") == "movie":
            films += 1
        elif r.get("kind") == "season":   # "Show · S02 · 3 episodes" (connectors/feeds/arr.py groups a season's imports)
            m = re.search(r"(\d+) episodes?$", str(r.get("title") or ""))
            episodes += int(m[1]) if m else 1
        elif r.get("kind") == "episode":
            episodes += 1
    words = ([_plural(episodes, "episode")] if episodes else []) + ([_plural(films, "film")] if films else [])
    return "Arrived: " + ", ".join(words) if words else "Nothing new arrived"


def _updates(snaps, now: datetime) -> str | None:
    rows = server._data(snaps, WUD_SNAPSHOT_ID).get("containers")
    if not isinstance(rows, list):
        return None
    from hub import server_updates   # function-level: keeps this module's import light (hub.tasks imports it at startup)
    pending = [c for c in rows if isinstance(c, dict) and c.get("update_available")]
    n = len(server.split_updates(pending, server_updates.get_ignores(), None, now)[0])
    return f"{_plural(n, 'update')} pending" if n else "No updates pending"


def _disk(snaps) -> str | None:
    pcts = [int(p) for v in server._volumes(snaps) if (p := server._num(v.get("pct_used"))) is not None]
    return f"Disk {max(pcts)} %" if pcts else None


def _services(snaps) -> str | None:
    apps = server._apps(snaps)
    if not apps:
        return None
    down = [str(a.get("name", a.get("id", "?"))) for a in apps if not a.get("up")]
    return "Down: " + ", ".join(down) if down else f"All {len(apps)} services up"


def _torrents(snaps) -> str | None:
    rows = server._data(snaps, QBIT_SNAPSHOT_ID).get("active")
    if not isinstance(rows, list):
        return None
    states = [str(r.get("state_text")) for r in rows if isinstance(r, dict)]
    stalled, active = states.count("Stalled"), states.count("Downloading")
    if stalled:
        return f"{_plural(stalled, 'torrent')} stalled"
    return f"{active} downloading" if active else "Nothing downloading"


def build(snaps, now: datetime) -> str | None:
    """The digest text, or None when no snapshot gives any part. `now`: aware, hub-local (its date is the heading)."""
    parts = [p for p in (_arrived(snaps, now), _updates(snaps, now), _disk(snaps), _services(snaps), _torrents(snaps)) if p]
    if not parts:
        return None
    return " · ".join([f"Joey digest · {now:%a} {now.day} {now:%b}", *parts])[:MAX_CHARS]


def settled(snaps, now: datetime, booted: datetime) -> bool:
    """JY-254: True once BOOT_GRACE has passed since `booted`, or a media_status sample taken at or after `booted`
    shows every app up. Before that the services part could only repeat pre-boot or still-starting "Down"s."""
    if now - booted >= BOOT_GRACE:
        return True
    snap = snaps.get(MEDIA_STATUS_SNAPSHOT_ID)
    sampled = parse_utc(snap.updated_at) if snap is not None else None
    apps = server._apps(snaps)
    return sampled is not None and sampled >= booted and bool(apps) and all(a.get("up") for a in apps)


def _local(now: datetime | None) -> datetime:
    """Hub-local time: the container's TZ (Australia/Melbourne). A caller-supplied aware `now` is taken as already local."""
    return now if now is not None else datetime.now().astimezone()


def tick(now: datetime | None = None, booted: datetime | None = None) -> bool:
    """Send today's digest when due. True only when a message was posted this call. Never raises.
    `booted` (JY-254): the boot to grace from; default STARTED."""
    url = server_alerts.webhook()
    if not url or disabled():
        return False
    now = _local(now)
    if (now.hour, now.minute) < send_after():
        return False
    day = now.date().isoformat()
    with _lock:
        if _fails.get(day, 0) >= MAX_FAILS:
            return False
        try:
            from hub.store import get_snapshots
            with closing(media_db.connect()) as db:
                db.execute(DDL)
                if db.execute("SELECT 1 FROM server_digest_sent WHERE day = ?", (day,)).fetchone():
                    return False
                snaps = get_snapshots()
                if not settled(snaps, now, booted or STARTED):
                    return False   # JY-254: boot health not settled yet; the next tick looks again
                text = build(snaps, now)
                if text is None:
                    return False
                if not server_alerts.post(url, text):
                    _fails[day] = _fails.get(day, 0) + 1
                    if _fails[day] >= MAX_FAILS:
                        log.warning("digest push: giving up for today after %d failures", MAX_FAILS)
                    return False
                with db:
                    db.execute("INSERT OR REPLACE INTO server_digest_sent(day, at, text) VALUES(?,?,?)",
                               (day, now.isoformat(), text))
                return True
        except (sqlite3.Error, OSError) as exc:
            log.warning("server digest failed: %s", type(exc).__name__)
            return False


def last_sent(now: datetime | None = None) -> str | None:
    """The Server page's digest line, or None (no line) without a webhook or with DIGEST=off.
    "Digest · sent 07:31" when today's row exists, else "Digest · not sent today". Read-only."""
    if not server_alerts.webhook() or disabled():
        return None
    now = _local(now)
    sent = None
    db = media_store.reader()
    if db is not None:
        try:
            with closing(db):
                row = db.execute("SELECT at FROM server_digest_sent WHERE day = ?", (now.date().isoformat(),)).fetchone()
            sent = parse_utc(row["at"]) if row else None
        except sqlite3.Error:
            sent = None   # no table yet: nothing sent
    return f"Digest · sent {sent.astimezone(now.tzinfo):%H:%M}" if sent else "Digest · not sent today"
