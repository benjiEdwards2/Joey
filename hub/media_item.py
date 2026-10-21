"""Jellyfin item data for the film page (F9 data helpers; the page itself is hub/media_film.py, F10).
Full film / episode / show information for one Jellyfin item. Read live from Jellyfin (env JELLYFIN_URL +
JELLYFIN_API_KEY) server-side only; the page carries no URL or key except the Play deep link
(the same one the hero uses). Any upstream failure degrades to words, never a 500; logs carry
the exception TYPE only.
"""

from __future__ import annotations

import contextvars
import logging
import re
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import date

from hub import media_db, media_files
from hub.media_cache import LRU
from hub.media_discover import _date_words
from hub.media_library import runtime_text

log = logging.getLogger("hub.media_item")

ITEM_RE = re.compile(r"^[A-Za-z0-9-]{1,64}$")
# E1 (2026-10-13): stale-while-revalidate. An item read is served from the cache up to CACHE_TTL old; once it is
# older than FRESH_S it is still served at once and re-read in the background (one refresh per item at a time).
# Joey's own watch-state writes drop the cache (`invalidate`), so a mark is never shown stale.
CACHE_TTL = 6 * 3600
FRESH_S = 600
TICKS_PER_MINUTE = 600_000_000
MAX_SEASONS, MAX_EPISODES = 12, 60
FIELDS = ("Overview,Genres,People,ProviderIds,DateCreated,PremiereDate,RunTimeTicks,SeriesId,SeasonId,"
          "ParentIndexNumber,IndexNumber,SeriesName,SeasonName,Studios,OfficialRating,CommunityRating,"
          "UserData,BackdropImageTags,ImageTags,RemoteTrailers,"
          # media-speed (2026-10-07): the file strip's stream facts ride on the same item read
          "MediaStreams,MediaSources,Path,Width,Height,Container")
CREW_TYPES = ("Director", "Writer")
DOWN_TEXT = "Couldn't reach Jellyfin — showing what Joey knows"
KINDS = {"Movie": "movie", "Episode": "episode", "Series": "series", "Season": "season"}

_cache: LRU = LRU()   # _ck(jf_id) -> (fetched_at, item + seasons); bounded (M-42)
_server: list = [0.0, None]  # [fetched_at, server id]
_flights: dict = {}           # key -> Future of the one read in flight (F2 fast pages, 2026-10-12)
_flight_lock = threading.Lock()
_gen = [0]                    # bumped by every invalidation: a read that started before one is not cached (E1)
_refreshing: set = set()      # item ids with a background refresh queued or running
_refresh_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="item-refresh")   # bounded: one at a time


def once(key, fn):
    """fn() run ONCE for concurrent callers with the same key (F2, 2026-10-12): the first caller runs it, the others wait
    for its answer. A link prefetch and the tap right after it, or a page and its deferred parts, share one upstream
    read instead of racing two. Nothing is kept once it is done — the callers' own caches hold the answer."""
    with _flight_lock:
        fut = _flights.get(key)
        lead = fut is None
        if lead:
            fut = _flights[key] = Future()
    if not lead:
        return fut.result()
    try:
        out = fn()
        fut.set_result(out)
        return out
    except BaseException as exc:
        fut.set_exception(exc)
        raise
    finally:
        with _flight_lock:
            _flights.pop(key, None)


def _ck(jf_id: str):
    """The cache key of an item read: its id; on the media front (viewer, id) - the read carries that viewer's watch
    state (UserData), so one friend's entry is never served to another, and none exists outside a signed-in request
    (Joey TV WP-B2, P3)."""
    from hub import guest, media_jellyfin
    return (media_jellyfin.viewer(), jf_id) if guest.is_media() else jf_id


def _in_context(pool, fn, *args):
    """pool.submit that carries this request's context (the media front's bound viewer) into the worker thread."""
    return pool.submit(contextvars.copy_context().run, fn, *args)


def clear_cache() -> None:
    invalidate()
    _server[:] = [0.0, None]


def invalidate() -> None:
    """Every cached item dropped (Joey changed watch state): the next page reads Jellyfin again, and a read already
    in flight is not cached."""
    with _flight_lock:
        _gen[0] += 1
        _cache.clear()


def drain_refresh(timeout: float = 10.0) -> None:
    """Wait for the background refreshes queued so far (tests: one test's refresh never lands in the next one)."""
    try:
        _refresh_pool.submit(lambda: None).result(timeout=timeout)
    except Exception:
        pass


def _int(v) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def _server_id(base, headers, from_snapshot) -> str | None:
    if from_snapshot:
        return from_snapshot
    if _server[1] and time.time() - _server[0] < media_files.UID_TTL:
        return _server[1]
    try:
        sid = (media_files._get(base, headers, "/System/Info/Public") or {}).get("Id")
    except Exception as exc:
        log.warning("jellyfin server id lookup failed: %s", type(exc).__name__)
        return None
    if sid and ITEM_RE.match(str(sid)):
        _server[:] = [time.time(), str(sid)]
        return _server[1]
    return None


def _trailer(raw: dict) -> str | None:
    for t in raw.get("RemoteTrailers") or []:
        url = str(t.get("Url") or "") if isinstance(t, dict) else ""
        if url.startswith(("https://", "http://")):
            return url
    return None


def _state(row: dict, today: str) -> dict:
    ud = row.get("UserData") or {}
    played = bool(ud.get("Played"))
    aired = str(row.get("PremiereDate") or "")[:10] <= today
    return {"played": played, "in_progress": not played and (ud.get("PlaybackPositionTicks") or 0) > 0,
            "aired": aired or played}


def _season_groups(items) -> list[tuple[dict, list[dict]]]:
    """The show's episodes (ONE /Shows/{id}/Episodes read, E1) grouped by their season: [(season, episodes)] in
    season-number order (Specials, number 0, first; unnumbered last), at most MAX_SEASONS. Each episode names its
    season (SeasonId, SeasonName, ParentIndexNumber), so the separate /Seasons read and the read per season went."""
    groups: dict[str, tuple[dict, list[dict]]] = {}
    for e in items or []:
        if not isinstance(e, dict) or not e.get("Id") or not e.get("SeasonId"):
            continue
        sid = str(e["SeasonId"])
        if sid not in groups:
            groups[sid] = ({"Id": sid, "Name": e.get("SeasonName"), "IndexNumber": _int(e.get("ParentIndexNumber"))}, [])
        groups[sid][1].append(e)
    ordered = sorted(groups.values(), key=lambda g: (g[0]["IndexNumber"] is None, g[0]["IndexNumber"] or 0))
    return ordered[:MAX_SEASONS]


def _seasons(base, headers, uid, series_id: str, today: str) -> list[dict]:
    body = media_files._get(base, headers, f"/Shows/{series_id}/Episodes", {
        "userId": uid, "Fields": "UserData,PremiereDate,RunTimeTicks,People"})
    out = []
    for s, items in _season_groups(body.get("Items") if isinstance(body, dict) else None):
        eps = []
        for e in items[:MAX_EPISODES]:
            if isinstance(e, dict) and e.get("Id"):
                num = _int(e.get("IndexNumber"))
                ticks = e.get("RunTimeTicks") or 0
                pos = (e.get("UserData") or {}).get("PlaybackPositionTicks") or 0
                state = _state(e, today)
                # Episode list (2026-10-08): air date, runtime and minutes left ride on the same read; the 16:9
                # still is the episode's own Primary image through the /img proxy (`jf:<id>`).
                eps.append({"number": num if num is not None else len(eps) + 1,
                            "name": str(e.get("Name") or "Episode")[:200], "jf_id": e["Id"],
                            "air_date": _date_words(e.get("PremiereDate"))[0] if e.get("PremiereDate") else None,
                            "runtime": runtime_text(ticks / TICKS_PER_MINUTE) if ticks else None,
                            "left_min": max(0, ticks - pos) // TICKS_PER_MINUTE if state["in_progress"] and ticks else None,
                            "still": f"jf:{e['Id']}" if ITEM_RE.match(str(e["Id"])) else None,
                            # TV directors (2026-10-10): the show page's Director / Writer rows add these up
                            "crew": [{"name": str(c["Name"])[:80], "type": c["Type"],
                                      # the show page's "Directed by" cards use the Jellyfin headshot when there is one
                                      "ref": (f"jf:{c['Id']}" if c.get("Id") and c.get("PrimaryImageTag")
                                              and ITEM_RE.match(str(c["Id"])) else None)}
                                     for c in e.get("People") or []
                                     if isinstance(c, dict) and c.get("Name") and c.get("Type") in CREW_TYPES],
                            # TV episode flow (WP-E3, 2026-10-16): everyone the episode lists, any Type - an episode
                            # page counts a guest's "k eps this season" from these (same read, no extra call)
                            "people_names": [str(c["Name"])[:80] for c in (e.get("People") or [])[:100]
                                             if isinstance(c, dict) and c.get("Name")],
                            **state})
        done = sum(1 for e in eps if e["played"])
        out.append({"id": s["Id"], "number": _int(s.get("IndexNumber")), "name": str(s.get("Name") or "Season")[:100], "episodes": eps,
                    "watched_text": f"{done} of {len(eps)} watched"})
    return out


def _build(jf_id: str) -> dict:
    """The page data for one item, straight from Jellyfin; raises on any upstream failure."""
    base, headers = media_files._creds()
    uid = media_files._user_id(base, headers)
    if not uid:   # the media front outside a signed-in request (P3): no read as anyone else
        raise LookupError("no Jellyfin user")
    raw = media_files._get(base, headers, f"/Users/{uid}/Items/{jf_id}", {"Fields": FIELDS})
    kind = KINDS.get(str(raw.get("Type")))
    if kind is None:
        raise ValueError("unsupported item type")
    today = date.today().isoformat()
    series_id = raw.get("SeriesId") if kind in ("episode", "season") else (raw["Id"] if kind == "series" else None)
    tmdb = (raw.get("ProviderIds") or {}).get("Tmdb") if kind in ("movie", "series") else None
    imdb = (raw.get("ProviderIds") or {}).get("Imdb") if kind in ("movie", "series") else None  # media-ux4: OMDb lookup
    show = None
    with ThreadPoolExecutor(max_workers=3) as pool:
        # media-speed: the independent reads after the item run side by side. An episode / season reads its
        # SHOW through _data (cached), which carries the show's TMDB id and seasons — the film page then
        # finds the show already cached instead of reading it (and its seasons) a second time.
        show_f = _in_context(pool, _data, series_id) if kind in ("episode", "season") and series_id else None
        seasons_f = _in_context(pool, _seasons, base, headers, uid, series_id, today) if kind == "series" else None
        files_f = (_in_context(pool, media_files.file_summary, "tv", int(tmdb), raw["Id"])   # M-45: the series id is known
                   if kind == "series" and str(tmdb).isdigit()
                   else None)
        if show_f is not None:
            show = show_f.result()
            if show is None:
                log.warning("jellyfin series lookup failed")
            tmdb = (show or {}).get("item", {}).get("tmdb")
        seasons = (seasons_f.result() if seasons_f is not None
                   else (show["seasons"] if show is not None else _seasons(base, headers, uid, series_id, today))
                   if series_id else [])
        files = (files_f.result() if files_f is not None
                 else media_files.file_summary_from_item(jf_id, raw) if kind in ("movie", "episode") else None)
    ud = raw.get("UserData") or {}
    ticks = raw.get("RunTimeTicks") or 0
    pos = ud.get("PlaybackPositionTicks") or 0
    played = bool(ud.get("Played"))
    year = raw.get("ProductionYear") or (str(raw.get("PremiereDate") or "")[:4] or None)
    cr, art = raw.get("CommunityRating"), series_id or raw["Id"]
    season_no = _int(raw.get("ParentIndexNumber")) if kind == "episode" else _int(raw.get("IndexNumber"))
    ep_no = _int(raw.get("IndexNumber")) if kind == "episode" else None
    air = _date_words(raw.get("PremiereDate"))[0] if kind == "episode" else None
    item = {
        "kind": kind, "id": raw["Id"], "title": str(raw.get("Name") or "Jellyfin item")[:200],
        "year": year, "overview": str(raw.get("Overview") or "")[:1500],
        "genres": [str(g) for g in (raw.get("Genres") or [])][:5],
        "runtime": runtime_text(ticks / TICKS_PER_MINUTE) if ticks else "",
        "community_rating": f"{cr:.1f}" if isinstance(cr, (int, float)) and cr > 0 else None,
        "official_rating": str(raw.get("OfficialRating") or "") or None,
        "air_date": air, "runtime_min": ticks // TICKS_PER_MINUTE if ticks else None,
        "added": raw.get("DateCreated"), "last_played": ud.get("LastPlayedDate"), "trailer": _trailer(raw),
        "played": played, "in_progress": not played and pos > 0,
        "left_text": f"{max(0, ticks - pos) // TICKS_PER_MINUTE}m left" if ticks and pos > 0 else None,
        "poster": f"jf:{art}", "backdrop": f"jfb:{art}", "tmdb": str(tmdb) if tmdb else None,
        "imdb": str(imdb) if imdb else None,
        # F2 (2026-10-12): the show's TheTVDB id from Jellyfin, so the download badge and Search now need no Jellyseerr read
        "tvdb": (str((raw.get("ProviderIds") or {}).get("Tvdb") or "") or None) if kind == "series" else None,
        # media-ux3: the "part of" banner draws a backdrop only when Jellyfin has one (else a plain panel)
        "has_backdrop": bool(raw.get("BackdropImageTags")),
        "show_title": str(raw.get("SeriesName") or "") or None, "show_id": series_id if kind != "series" else None,
        "season_no": season_no, "episode_no": ep_no,
        "code": f"S{season_no:02d}E{ep_no:02d}" if kind == "episode" and season_no is not None and ep_no is not None else None,
        "show_key": f"jf:{series_id}" if series_id else None,
        "season_key": (f"jf:{raw['SeasonId']}" if raw.get("SeasonId") else
                       f"jf:{raw['Id']}" if kind == "season" else None),
        "episode_key": f"jf:{raw['Id']}" if kind == "episode" else None,
        "people": [{"name": str(p["Name"])[:80], "role": str(p.get("Role") or "")[:80], "type": p.get("Type"),
                    "ref": f"jf:{p['Id']}" if p.get("Id") and p.get("PrimaryImageTag") and ITEM_RE.match(str(p["Id"])) else None}
                   for p in (raw.get("People") or []) if isinstance(p, dict) and p.get("Name")],
    }
    # cap at 30, but never cut a Director / Writer (an episode lists its guest stars first, 2026-10-10)
    item["people"] = item["people"][:30] + [p for p in item["people"][30:] if p["type"] in CREW_TYPES]
    return {"item": item, "seasons": seasons, "files": files}


def _data(jf_id: str, stale_ok: bool = True) -> dict | None:
    """The item's page data. Fresh (under FRESH_S): from the cache. Older but under CACHE_TTL: from the cache at once
    and re-read in the background (`stale_ok`; False = read now, as a write path that needs today's state does).
    Otherwise one blocking read, shared by concurrent callers."""
    hit = _cache.get(_ck(jf_id))
    if hit:
        age = time.time() - hit[0]
        if age < FRESH_S:
            return hit[1]
        if stale_ok and age < CACHE_TTL and media_files._creds():
            _refresh_later(jf_id)
            return hit[1]
    if not media_files._creds():
        return None
    return once(("item", _ck(jf_id)), lambda: _read(jf_id))


def _read(jf_id: str, force: bool = False) -> dict | None:
    key = _ck(jf_id)
    hit = _cache.get(key)   # a caller that queued behind a read that has just finished
    if not force and hit and time.time() - hit[0] < FRESH_S:
        return hit[1]
    gen = _gen[0]
    try:
        out = _build(jf_id)
    except Exception as exc:  # type only — requests errors embed the URL
        log.warning("jellyfin item lookup failed: %s", type(exc).__name__)
        return None   # a background refresh that fails keeps the entry it was refreshing
    with _flight_lock:
        if gen == _gen[0]:   # not across an invalidation: the read may predate Joey's own write
            _cache[key] = (time.time(), out)
    return out


def _refresh_later(jf_id: str) -> None:
    """Queue one background re-read of a stale item (the bounded refresh pool; a second ask while queued is a no-op)."""
    key = _ck(jf_id)
    with _flight_lock:
        if key in _refreshing:
            return
        _refreshing.add(key)

    def run():
        try:
            once(("item", key), lambda: _read(jf_id, force=True))
        finally:
            with _flight_lock:
                _refreshing.discard(key)
    ctx = contextvars.copy_context()   # the media front's bound viewer rides along (one zero-arg callable, as before)
    _refresh_pool.submit(lambda: ctx.run(run))


def warm(jf_id: str) -> str:
    """The warm-up's item read (E1): 'cached' when the item is fresh, else read now -> 'fetched' or 'failed'."""
    hit = _cache.get(_ck(jf_id))
    if hit and time.time() - hit[0] < FRESH_S:
        return "cached"
    if not media_files._creds():
        return "failed"
    return "fetched" if once(("item", _ck(jf_id)), lambda: _read(jf_id, force=True)) is not None else "failed"


def peek(jf_id: str | None) -> dict | None:
    """The cached page data for an item, however old, WITHOUT a Jellyfin read — the film page's deferred parts
    (F2, 2026-10-12) use what the page itself just read and never read Jellyfin again."""
    hit = _cache.get(_ck(jf_id)) if jf_id else None
    return hit[1] if hit else None


def _rating_for(item: dict, level: str) -> dict:
    """The one rating this page offers: movie/series -> show key; season -> season key;
    episode -> the owner's level key (falling back to the show)."""
    kind = item["kind"]
    if kind == "episode":
        has = bool(item.get(level + "_key"))
        key, lv = (item[level + "_key"], level) if has else (item.get("show_key") or item["episode_key"], "show")
        if lv == "episode" and item["show_title"] and item["code"]:
            title = f"{item['show_title']} · {item['code']} · {item['title']}"
        elif lv == "season" and item["show_title"] and item["season_no"] is not None:
            title = f"{item['show_title']} · Season {item['season_no']}"
        else:
            title = item["show_title"] or item["title"]
    elif kind == "season":
        key, lv, title = item["season_key"], "season", f"{item['show_title'] or ''} · {item['title']}".strip(" ·")
    elif kind == "series":
        key, lv, title = f"jf:{item['id']}", "show", item["title"]
    else:
        key, lv, title = (f"tmdb:{item['tmdb']}" if item["tmdb"] else f"jf:{item['id']}"), "show", item["title"]
    return {"item_key": key, "kind": "movie" if kind == "movie" else "tv", "level": lv, "title": title,
            "year": item["year"], "poster": item["poster"]}


def _diary_dates(item: dict, owner: str) -> list[str]:
    """The title's newest 8 diary dates as words — one dedicated SELECT (M-36), not a scan of the latest 500 rows."""
    kind = item["kind"]
    if kind == "movie":
        q = {"item_keys": [f"jf:{item['id']}"] + ([f"tmdb:{item['tmdb']}"] if item["tmdb"] else [])}
    elif kind == "episode":
        q = {"item_keys": [item["episode_key"]]}
    elif kind == "season":
        q = {"season_key": item["season_key"]}
    else:
        q = {"item_keys": [f"jf:{item['id']}"], "show_key": f"jf:{item['id']}"}
    return [_date_words(d)[0] or d for d in media_db.diary_dates(owner, **q)]
