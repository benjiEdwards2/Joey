"""Play recorder + History page (F7, 2026-10-06). The recorder polls Jellyfin `/Sessions`
every PLAY_POLL_SECONDS (default 60) from a background task (the HTTP work runs in a thread,
so the event loop is never blocked) and records each Movie/Episode being played. It is
off when PLAY_RECORDER=off or JELLYFIN_URL/JELLYFIN_API_KEY are missing. Logs carry
exception type names only — never a URL or key.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from hub import identity, media_db, media_jellyfin as jellyfin, media_plays_db as pdb, shell

log = logging.getLogger("hub.media_plays")

DEFAULT_POLL_S = 60
FIRST_DELAY_S = 15
WINDOW_CHIPS = [(7, "7 days"), (30, "30 days"), (90, "90 days"), ("year", "This year"), ("all", "All time")]

router = APIRouter()


def poll_seconds() -> float:
    try:
        return max(1.0, float(os.environ.get("PLAY_POLL_SECONDS", DEFAULT_POLL_S)))
    except ValueError:
        return float(DEFAULT_POLL_S)


_creds = jellyfin.creds   # M-12: one Jellyfin client (hub/media_jellyfin.py)


def disabled() -> bool:
    return os.environ.get("PLAY_RECORDER", "").strip().lower() == "off" or _creds() is None


def _owner(user_id) -> str | None:
    """The play's owner by Jellyfin user ID (Joey TV WP-A2: a friend is jf:<id>, never "you"); None for a session
    without a well-formed UserId. identity.OwnerUnresolved (no /Users read yet) propagates: the poll records nothing."""
    try:
        return identity.owner_for_jellyfin(user_id) if user_id else None
    except ValueError:
        return None


def _key(item: dict) -> str | None:
    tmdb = (item.get("ProviderIds") or {}).get("Tmdb")
    if tmdb:
        return f"tmdb:{tmdb}"
    return f"jf:{item['Id']}" if item.get("Id") else None


def play_from_session(session: dict) -> dict | None:
    item = session.get("NowPlayingItem")
    if not isinstance(item, dict) or item.get("Type") not in ("Movie", "Episode") or not item.get("Id"):
        return None
    owner = _owner(session.get("UserId"))
    if owner is None:
        return None
    user = session.get("UserName")
    ticks = item.get("RunTimeTicks") or 0
    pos = (session.get("PlayState") or {}).get("PositionTicks") or 0
    episode = item["Type"] == "Episode"
    series = item.get("SeriesId")
    art = series if episode and series else item["Id"]
    return {
        "user_name": user, "owner": owner, "jf_id": item["Id"],
        "item_key": f"jf:{series}" if episode and series else _key(item),
        "show_key": f"jf:{series}" if episode and series else None,
        "season_key": f"jf:{item['SeasonId']}" if episode and item.get("SeasonId") else None,
        "episode_key": f"jf:{item['Id']}" if episode else None,
        "title": item.get("Name"), "show_title": item.get("SeriesName") if episode else None,
        "kind": "episode" if episode else "movie",
        "season": item.get("ParentIndexNumber") if episode else None,
        "episode": item.get("IndexNumber") if episode else None,
        "runtime_min": round(ticks / 600_000_000, 1) if ticks else None,
        "position_pct": round(100 * pos / ticks) if ticks else 0,
        "poster": f"jf:{art}",
    }


def poll_once(now: datetime | None = None) -> int:
    """One poll. Returns how many sessions were recorded; never raises."""
    creds = _creds()
    if creds is None:
        return 0
    now = now or datetime.now(timezone.utc)
    base, headers = creds
    try:
        sessions = jellyfin.get(base, headers, "/Sessions")
        count = 0
        for s in sessions if isinstance(sessions, list) else []:
            play = play_from_session(s) if isinstance(s, dict) else None
            if play:
                pdb.record_sighting(play, now)
                count += 1
        return count
    except Exception as exc:
        log.warning("play recorder poll failed: %s", type(exc).__name__)
        return 0


async def recorder_loop():
    await asyncio.sleep(FIRST_DELAY_S)
    while True:
        try:
            await asyncio.to_thread(poll_once)
        except Exception as exc:  # never let the recorder take the hub down
            log.warning("play recorder task error: %s", type(exc).__name__)
        await asyncio.sleep(poll_seconds())


def start_recorder():
    """The asyncio task for the hub lifespan, or None when the recorder is off."""
    return None if disabled() else asyncio.create_task(recorder_loop())


# ---- History page ----

def history_context(window, view: str) -> dict:
    window = window if window in ("year", "all") else (int(window) if str(window) in ("7", "30", "90") else 30)
    owner = media_db.owner_filter(view)
    s = pdb.stats(window, owner)
    day = s["busiest_day"]
    if day:
        d = datetime.fromisoformat(day["date"])
        day = {**day, "text": f"{d.strftime('%A')} {d.day} {d.strftime('%B %Y')}"}
    top = max(s["by_hour"]) or 1
    hours = [{"label": f"{h:02d}", "count": n, "pct": round(100 * n / top)} for h, n in enumerate(s["by_hour"])]
    chips = [{"label": label, "href": f"/media/server/history?w={w}", "on": w == window} for w, label in WINDOW_CHIPS]
    return {"stats": {**s, "busiest_day": day, "hours_text": pdb.hours_text(s["hours"])}, "chips": chips,
            "by_hour": hours, "empty": s["plays"] == 0,
            "since": pdb.first_run_date() or datetime.now(timezone.utc).date().isoformat()}


@router.get("/media/server/history", response_class=HTMLResponse)
def history_page(request: Request, w: str = "30"):
    view, from_query = shell.resolve_owner_view(request)
    ctx = history_context(int(w) if w.isdigit() else w, view)
    resp = shell.render_page(request, "media_server_history.html", {
        "status": shell.build_status(shell.get_snapshots(request=request)), "ratings": {}, **ctx})
    return shell._maybe_set_cookie(resp, view, from_query)
