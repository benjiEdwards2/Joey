"""The hub's background work (W3 split of hub/main.py, H-44): the media.db backup, the Server sample + alert
check, the Media warm-up, Follow and Awards loops, all run by one `_every` helper (H-23), the 07:30 Discord digest
(P2, 2026-10-22: `_server_digest_loop`, hub/server_digest.py), and the app lifespan
that loads the registry (shell.load_areas) and starts / cancels them.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI

from hub import guest, media_awards, media_backup, media_follow, media_plays, media_warmup, shell
from hub import server as server_area
from hub import server_alerts, server_digest, server_history
from hub.store import get_snapshots as _read_snapshots

log = logging.getLogger("hub")

# media.db backups (2026-10-05): first check ~30 s after startup (the NAS is off
# overnight, so this is what gives one a day), then hourly; maybe_backup skips
# while a backup under 20 h old exists. MEDIA_BACKUP=off disables the task.
BACKUP_FIRST_DELAY_S = 30
BACKUP_EVERY_S = 3600


async def _every(label: str, first_s: float, every_s: float, fn) -> None:
    """One background loop (H-23): wait `first_s`, then run `fn` in a worker thread every `every_s`. An error is
    logged by type only and never takes the hub down."""
    await asyncio.sleep(first_s)
    while True:
        try:
            await asyncio.to_thread(fn)
        except Exception as exc:
            log.warning("%s task error: %s", label, type(exc).__name__)
        await asyncio.sleep(every_s)


def _backup_loop():
    return _every("media backup", BACKUP_FIRST_DELAY_S, BACKUP_EVERY_S, lambda: media_backup.maybe_backup())


def _server_tick() -> None:
    """WP-U4: sample the `system` snapshot into media.db (server_history); WP-U2: push NEW Server Attention items
    to Discord (no-op without the webhook). A failed sample never skips the alert check. One snapshot read
    serves both (H-53). JY-031: between the two, the disk forecast is computed once and cached (the hub card, the
    /server render and the check read it); a failed refresh keeps the last cached state."""
    snaps = _read_snapshots()
    try:
        server_history.sample(snaps)
    except Exception as exc:
        log.warning("server history task error: %s", type(exc).__name__)
    try:
        server_history.refresh_forecast()
    except Exception as exc:
        log.warning("server forecast task error: %s", type(exc).__name__)
    server_alerts.check_once(server_area.live_snapshot_ids(shell.registry), snaps)


def _server_alerts_loop():
    return _every("server alerts", server_alerts.FIRST_DELAY_S, server_alerts.EVERY_S, _server_tick)


def _server_digest_loop():
    """P2 (2026-10-22): the overnight digest (hub/server_digest.py) - checked ~90 s after startup, then every 5 min; it
    posts once per hub-local day from DIGEST_AT (07:30). No webhook or DIGEST=off => the tick does nothing."""
    return _every("server digest", server_digest.FIRST_DELAY_S, server_digest.EVERY_S, server_digest.tick)


def _media_warmup_loop():
    """media-speed: warm the film pages behind the Media home shelves ~60 s after startup, then every few
    hours (hub/media_warmup.py). Sequential and paced inside the thread; MEDIA_WARMUP=off disables it. E1: the loop
    ticks every minute — the full pass still runs every EVERY_S, and each new jellyfin snapshot warms the shelf
    titles' Jellyfin item reads (media_warmup.tick)."""
    return _every("media warm-up", media_warmup.FIRST_DELAY_S, media_warmup.TICK_S, lambda: media_warmup.tick())


def _media_follow_loop():
    """Follow (2026-10-07): request NEW films of followed people / series (hub/media_follow.py) ~2 min after
    startup, then every 6 h. Idempotent (the NAS is off overnight); MEDIA_FOLLOW=off disables it."""
    return _every("media follow", media_follow.FIRST_DELAY_S, media_follow.EVERY_S, lambda: media_follow.run_once())


def _media_awards_loop():
    """Awards (2026-10-08): hourly check, a pass when one is due (hub/media_awards.py: every 6 h while a backlog
    exists, then weekly; skipped 22:00-07:00). MEDIA_AWARDS=off disables it; no AWARDS_CONTACT => no calls."""
    return _every("media awards", media_awards.FIRST_DELAY_S, media_awards.TICK_S, lambda: media_awards.tick())


def prewarm() -> dict:
    """E1 (2026-10-13): the first request after a deploy no longer pays the Jinja compiles and the snapshot parses -
    every template is compiled and every envelope parsed once at startup. -> counts; never raises."""
    out = {"templates": 0, "template_errors": 0, "snapshots": 0}
    for name in shell.templates.env.list_templates():
        try:
            shell.templates.env.get_template(name)
            out["templates"] += 1
        except Exception as exc:  # a broken template still fails its own page, as before - never the startup
            out["template_errors"] += 1
            log.warning("template pre-compile failed: %s", type(exc).__name__)
    try:
        out["snapshots"] = len(_read_snapshots())   # hub.store's parse cache - the one every request reads through
    except Exception as exc:
        log.warning("snapshot pre-parse failed: %s", type(exc).__name__)
    return out


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Load the registry at startup (shell.load_areas), failing fast with the aggregated violation list; then
    pre-compile the templates and pre-parse the snapshots (E1) in a worker thread.
    Joey TV WP-B1 (Q24): JOEY_FRONT is validated first (ValueError for an unknown value), and the media front starts
    ZERO loops whatever the env says - joey-hub stays the single background writer against the shared media.db
    (_server_alerts_loop has no env switch, so this guard is in code)."""
    media = guest.startup() == guest.MEDIA_FRONT
    shell.load_areas()
    await asyncio.to_thread(prewarm)
    tasks = [] if media else [
        None if media_backup.disabled() else asyncio.create_task(_backup_loop()),
        media_plays.start_recorder(),  # F7 play recorder; None when off
        asyncio.create_task(_server_alerts_loop()),
        asyncio.create_task(_server_digest_loop()),  # P2 (2026-10-22)
        None if media_warmup.disabled() else asyncio.create_task(_media_warmup_loop()),
        None if media_follow.disabled() else asyncio.create_task(_media_follow_loop()),
        None if media_awards.disabled() else asyncio.create_task(_media_awards_loop()),
    ]
    yield
    for task in reversed(tasks):  # newest first
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
