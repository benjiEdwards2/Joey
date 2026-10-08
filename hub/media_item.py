"""Jellyfin item data for the film page (F9 data helpers; the page itself is hub/media_film.py, F10).
Full film / episode / show information for one Jellyfin item. Read live from Jellyfin (env JELLYFIN_URL +
JELLYFIN_API_KEY) server-side only; the page carries no URL or key except the Play deep link
(the same one the hero uses). Any upstream failure degrades to words, never a 500; logs carry
the exception TYPE only.
"""

from __future__ import annotations

import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from hub import media_db, media_files
from hub.media_discover import _date_words
from hub.media_library import runtime_text

log = logging.getLogger("hub.media_item")

ITEM_RE = re.compile(r"^[A-Za-z0-9-]{1,64}$")
CACHE_TTL = 600
TICKS_PER_MINUTE = 600_000_000
MAX_SEASONS, MAX_EPISODES = 12, 60
FIELDS = ("Overview,Genres,People,ProviderIds,DateCreated,PremiereDate,RunTimeTicks,SeriesId,SeasonId,"
          "ParentIndexNumber,IndexNumber,SeriesName,SeasonName,Studios,OfficialRating,CommunityRating,"
          "UserData,BackdropImageTags,ImageTags,RemoteTrailers,"
          # media-speed (2026-10-07): the file strip's stream facts ride on the same item read
          "MediaStreams,MediaSources,Path,Width,Height,Container")
SEASON_WORKERS = 6
DOWN_TEXT = "Couldn't reach Jellyfin — showing what Joey knows"
KINDS = {"Movie": "movie", "Episode": "episode", "Series": "series", "Season": "season"}

_cache: dict[str, tuple[float, dict]] = {}
_server: list = [0.0, None]  # [fetched_at, server id]


def clear_cache() -> None:
    _cache.clear()
    _server[:] = [0.0, None]


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


def _seasons(base, headers, uid, series_id: str, today: str) -> list[dict]:
    got = media_files._get(base, headers, f"/Shows/{series_id}/Seasons", {"userId": uid})
    picked = [s for s in (got.get("Items") if isinstance(got, dict) else None) or []
              if isinstance(s, dict) and s.get("Id")][:MAX_SEASONS]

    def episodes(s):
        return media_files._get(base, headers, f"/Shows/{series_id}/Episodes", {
            "userId": uid, "seasonId": s["Id"], "Fields": "UserData,PremiereDate,RunTimeTicks"})

    if len(picked) > 1:  # one episode read per season, side by side (media-speed)
        with ThreadPoolExecutor(max_workers=min(SEASON_WORKERS, len(picked))) as pool:
            bodies = list(pool.map(episodes, picked))
    else:
        bodies = [episodes(s) for s in picked]
    out = []
    for s, body in zip(picked, bodies):
        eps = []
        for e in ((body.get("Items") if isinstance(body, dict) else None) or [])[:MAX_EPISODES]:
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
                            **state})
        done = sum(1 for e in eps if e["played"])
        out.append({"id": s["Id"], "number": _int(s.get("IndexNumber")), "name": str(s.get("Name") or "Season")[:100], "episodes": eps,
                    "watched_text": f"{done} of {len(eps)} watched"})
    return out


def _build(jf_id: str) -> dict:
    """The page data for one item, straight from Jellyfin; raises on any upstream failure."""
    base, headers = media_files._creds()
    uid = media_files._user_id(base, headers)
    raw = media_files._get(base, headers, f"/Users/{uid}/Items/{jf_id}", {"Fields": FIELDS})
    kind = KINDS.get(str(raw.get("Type")))
    if kind is None:
        raise ValueError("unsupported item type")
    today = date.today().isoformat()
    series_id = raw.get("SeriesId") if kind in ("episode", "season") else (raw["Id"] if kind == "series" else None)
    tmdb = (raw.get("ProviderIds") or {}).get("Tmdb") if kind in ("movie", "series") else None
    show = None
    with ThreadPoolExecutor(max_workers=3) as pool:
        # media-speed: the independent reads after the item run side by side. An episode / season reads its
        # SHOW through _data (cached), which carries the show's TMDB id and seasons — the film page then
        # finds the show already cached instead of reading it (and its seasons) a second time.
        show_f = pool.submit(_data, series_id) if kind in ("episode", "season") and series_id else None
        seasons_f = pool.submit(_seasons, base, headers, uid, series_id, today) if kind == "series" else None
        files_f = (pool.submit(media_files.file_summary, "tv", int(tmdb)) if kind == "series" and str(tmdb).isdigit()
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
        "left_text": f"{max(0, ticks - pos) // TICKS_PER_MINUTE} min left" if ticks and pos > 0 else None,
        "poster": f"jf:{art}", "backdrop": f"jfb:{art}", "tmdb": str(tmdb) if tmdb else None,
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
                   for p in (raw.get("People") or []) if isinstance(p, dict) and p.get("Name")][:30],
    }
    return {"item": item, "seasons": seasons, "files": files}


def _data(jf_id: str) -> dict | None:
    hit = _cache.get(jf_id)
    if hit and time.time() - hit[0] < CACHE_TTL:
        return hit[1]
    if not media_files._creds():
        return None
    try:
        out = _build(jf_id)
    except Exception as exc:  # type only — requests errors embed the URL
        log.warning("jellyfin item lookup failed: %s", type(exc).__name__)
        return None
    _cache[jf_id] = (time.time(), out)
    return out


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
    kind, out = item["kind"], []
    film_keys = {f"jf:{item['id']}"} | ({f"tmdb:{item['tmdb']}"} if item["tmdb"] else set())
    for r in media_db.list_diary(500, 0, None, owner):
        if kind == "movie":
            hit = r.get("item_key") in film_keys
        elif kind == "episode":
            hit = r.get("item_key") == item["episode_key"]
        elif kind == "season":
            hit = r.get("season_key") == item["season_key"]
        else:
            hit = f"jf:{item['id']}" in (r.get("show_key"), r.get("item_key"))
        if hit and r.get("watched_on"):
            out.append(_date_words(r["watched_on"])[0] or r["watched_on"])
    return out[:8]
