"""The guest Overview (Joey TV WP-B3 step 2, 2026-10-21): the media front's Media home is exactly three shelves -
Continue watching, Recently added, Recently watched (DECISIONS C; the WP-M mockup, call 4: no hero).

* Continue watching and Recently watched are live reads of the SIGNED-IN user's own Jellyfin state, made with THEIR
  token (hub.guest_auth.user_creds - P3, 2026-10-19: for a `you` session that is the alias user, so the admin's
  lounge-room state never appears): `GET /UserItems/Resume?userId=…` and
  `GET /Items?userId=…&SortBy=DatePlayed&SortOrder=Descending&IsPlayed=true&Recursive=true`. Each is cached TTL (60 s)
  per user, read with a TIMEOUT (3 s), and its shelf is OMITTED when the read fails (the page still renders); logs carry
  the exception type only (requests errors embed the URL).
* Recently added comes from the scrubbed snapshot's `latest` (hub.guest: no played state, Q20).
* Nothing else: no hero / Playing now, Downloading, Arrived, Requests, Most played, follow shelf, backup warning or
  household Up next. Library ticks: none (Q20).
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone

from hub import guest_auth, media_home, media_item, media_text, upstream
from hub.ids import JELLYFIN_SNAPSHOT_ID

log = logging.getLogger("hub.media_guest_home")

TIMEOUT = 3          # s, each shelf read (a page waits for it)
TTL = 60             # s, per user and shelf
SHELF_MAX = media_home.SHELF_MAX
TICKS_PER_MIN = 600_000_000
FIELDS = "ProviderIds,SeriesId,SeasonId,ParentIndexNumber,IndexNumber,SeriesName,RunTimeTicks,UserData"
RESUME, WATCHED = "resume", "watched"
CACHE_MAX = 64

clock = time.monotonic   # tests inject a clock
_cache: dict = {}        # (user id, shelf) -> (read_at, rows)
_lock = threading.Lock()


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def _params(shelf: str, uid: str) -> tuple[str, dict]:
    common = {"userId": uid, "Limit": SHELF_MAX, "Fields": FIELDS, "EnableUserData": "true"}
    if shelf == RESUME:
        return "/UserItems/Resume", {**common, "MediaTypes": "Video"}
    return "/Items", {**common, "SortBy": "DatePlayed", "SortOrder": "Descending", "IsPlayed": "true",
                      "Recursive": "true", "IncludeItemTypes": "Movie,Episode"}


def _keys(item: dict, episode: bool) -> dict:
    """The rating keys a row carries, as the recorder writes them (hub.media_plays.play_from_session)."""
    if episode and item.get("SeriesId"):
        series = f"jf:{item['SeriesId']}"
        return {"item_key": series, "show_key": series, "episode_key": f"jf:{item['Id']}",
                "season_key": f"jf:{item['SeasonId']}" if item.get("SeasonId") else None}
    tmdb = (item.get("ProviderIds") or {}).get("Tmdb")
    return {"item_key": f"tmdb:{tmdb}" if tmdb else f"jf:{item['Id']}"}


def _row(item, shelf: str, now: datetime) -> dict | None:
    if not isinstance(item, dict) or item.get("Type") not in ("Movie", "Episode"):
        return None
    jf_id = str(item.get("Id") or "")
    if not media_item.ITEM_RE.match(jf_id):
        return None
    episode = item["Type"] == "Episode"
    ud = item.get("UserData") if isinstance(item.get("UserData"), dict) else {}
    code = None
    if episode and isinstance(item.get("ParentIndexNumber"), int) and isinstance(item.get("IndexNumber"), int):
        code = f"S{item['ParentIndexNumber']} E{item['IndexNumber']}"
    if shelf == RESUME:
        runtime, pos = item.get("RunTimeTicks") or 0, ud.get("PlaybackPositionTicks") or 0
        left = (runtime - pos) / TICKS_PER_MIN if runtime and pos else 0
        sub = " · ".join(x for x in (code, f"{media_text.duration(left)} left" if left >= 1 else None) if x)
        pct = round(100 * pos / runtime) if runtime and pos else None
    else:
        sub = " · ".join(x for x in (code, media_home._ago_text(ud.get("LastPlayedDate"), now)) if x)
        pct = None
    series = item.get("SeriesId") if episode else None
    title = (item.get("SeriesName") if episode else None) or item.get("Name") or ""
    return {"title": title, "sub": sub, "poster": f"jf:{series or jf_id}", "href": media_home.item_href(jf_id),
            "pct": pct, **_keys(item, episode)}


def read_shelf(request, shelf: str) -> list[dict] | None:
    """The signed-in user's rows for one live shelf (RESUME / WATCHED), or None when it cannot be read (no full
    identity, Jellyfin down / refusing / answering garbage). Cached TTL per user; failures are not cached."""
    creds = guest_auth.user_creds(request)
    if creds is None:
        return None
    base, headers, uid = creds
    key = (uid, shelf)
    with _lock:
        hit = _cache.get(key)
    if hit and clock() - hit[0] < TTL:
        return [dict(r) for r in hit[1]]   # copies: the page decorates its rows
    path, params = _params(shelf, uid)
    try:
        resp = upstream.session("jellyfin").get(f"{base}{path}", params=params, headers=headers, timeout=TIMEOUT)
        if not 200 <= resp.status_code < 300:
            raise RuntimeError(f"HTTP {resp.status_code}")
        items = (resp.json() or {}).get("Items")
        if not isinstance(items, list):
            raise ValueError("unexpected answer")
    except Exception as exc:   # type only - requests errors embed the URL
        log.warning("guest shelf %s skipped: %s", shelf, type(exc).__name__)
        return None
    now = datetime.now(timezone.utc)
    rows = [r for r in (_row(i, shelf, now) for i in items) if r][:SHELF_MAX]
    with _lock:
        if len(_cache) >= CACHE_MAX:
            _cache.clear()
        _cache[key] = (clock(), rows)
    return [dict(r) for r in rows]


def _added(jelly: dict) -> list[dict]:
    now = datetime.now(timezone.utc)
    latest = sorted(jelly.get("latest") or [], key=lambda r: str(r.get("added_at") or ""), reverse=True)
    out, seen = [], set()
    for r in latest:
        key = r.get("item_key") or r.get("title")
        if key in seen:
            continue
        seen.add(key)
        out.append({"title": r.get("title"), "sub": media_home._ago_text(r.get("added_at"), now),
                    "poster": r.get("poster"), "pct": None,
                    "href": media_home.row_href(r.get("jf_id"), r.get("item_key"),
                                                "movie" if r.get("type") == "Movie" else None),
                    **{k: r.get(k) for k in media_home.LEVEL_KEYS}})
    return out[:SHELF_MAX]


def build(request, snaps, view: str) -> dict:
    """The guest Overview's `sh` for area_shelves.html: three shelves at most, no hero, no freshness line."""
    snap = snaps.get(JELLYFIN_SNAPSHOT_ID)
    jelly = media_home.view_jelly(snap.data if snap else {}, view)   # the media front: scrubbed, no household rows
    resume, watched, added = read_shelf(request, RESUME), read_shelf(request, WATCHED), _added(jelly)
    shelves = []
    if resume is not None:
        shelves.append({"id": "continue", "title": "Continue watching", "see_all_href": None, "items": resume,
                        "quiet_text": "Nothing to continue"})
    shelves.append({"id": "added", "title": "Recently added", "see_all_href": None, "items": added,
                    "quiet_text": "Nothing added recently"})
    if watched is not None:
        shelves.append({"id": "watched", "title": "Recently watched", "see_all_href": media_home.DIARY_DETAIL,
                        "items": watched, "quiet_text": "Nothing watched yet"})
    ratings = media_home._ratings(view, *(s["items"] for s in shelves))   # ONE query; the viewer's own ratings
    for s in shelves:
        for it in s["items"]:
            it["score"] = media_home.score_for(it, ratings)
            for k in media_home.LEVEL_KEYS:
                it.pop(k, None)
    return {"hero": None, "kind_word": None, "shelves": shelves, "waiting": {}, "open_href": None, "freshness": None}
