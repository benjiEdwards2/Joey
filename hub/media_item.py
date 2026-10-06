"""In-Joey item page (F9, 2026-10-06): full film / episode / show information for one Jellyfin
item, with a Play button that goes to Jellyfin. Read live from Jellyfin (env JELLYFIN_URL +
JELLYFIN_API_KEY) server-side only; the page carries no URL or key except the Play deep link
(the same one the hero uses). Any upstream failure degrades to words, never a 500; logs carry
the exception TYPE only.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import date

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from hub import media_db, media_files
from hub.media_discover import _date_words
from hub.media_library import runtime_text

log = logging.getLogger("hub.media_item")
router = APIRouter()

ITEM_RE = re.compile(r"^[A-Za-z0-9-]{1,64}$")
CACHE_TTL = 600
TICKS_PER_MINUTE = 600_000_000
MAX_SEASONS, MAX_EPISODES = 12, 60
FIELDS = ("Overview,Genres,People,ProviderIds,DateCreated,PremiereDate,RunTimeTicks,SeriesId,SeasonId,"
          "ParentIndexNumber,IndexNumber,SeriesName,SeasonName,Studios,OfficialRating,CommunityRating,"
          "UserData,BackdropImageTags,ImageTags")
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


def _state(row: dict, today: str) -> dict:
    ud = row.get("UserData") or {}
    played = bool(ud.get("Played"))
    aired = str(row.get("PremiereDate") or "")[:10] <= today
    return {"played": played, "in_progress": not played and (ud.get("PlaybackPositionTicks") or 0) > 0,
            "aired": aired or played}


def _seasons(base, headers, uid, series_id: str, today: str) -> list[dict]:
    got = media_files._get(base, headers, f"/Shows/{series_id}/Seasons", {"userId": uid})
    out = []
    for s in (got.get("Items") if isinstance(got, dict) else None) or []:
        if not isinstance(s, dict) or not s.get("Id") or len(out) >= MAX_SEASONS:
            continue
        body = media_files._get(base, headers, f"/Shows/{series_id}/Episodes", {
            "userId": uid, "seasonId": s["Id"], "Fields": "UserData,PremiereDate,RunTimeTicks"})
        eps = []
        for e in ((body.get("Items") if isinstance(body, dict) else None) or [])[:MAX_EPISODES]:
            if isinstance(e, dict) and e.get("Id"):
                num = _int(e.get("IndexNumber"))
                eps.append({"number": num if num is not None else len(eps) + 1,
                            "name": str(e.get("Name") or "Episode")[:200], "jf_id": e["Id"],
                            **_state(e, today)})
        done = sum(1 for e in eps if e["played"])
        out.append({"id": s["Id"], "name": str(s.get("Name") or "Season")[:100], "episodes": eps,
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
    if kind in ("episode", "season") and series_id:
        try:  # the episode/season payload carries no show provider ids: look the series up once
            tmdb = (media_files._get(base, headers, f"/Users/{uid}/Items/{series_id}",
                                     {"Fields": "ProviderIds"}).get("ProviderIds") or {}).get("Tmdb")
        except Exception as exc:
            log.warning("jellyfin series lookup failed: %s", type(exc).__name__)
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
        "air_date": air, "played": played, "in_progress": not played and pos > 0,
        "left_text": f"{max(0, ticks - pos) // TICKS_PER_MINUTE} min left" if ticks and pos > 0 else None,
        "poster": f"jf:{art}", "backdrop": f"jfb:{art}", "tmdb": str(tmdb) if tmdb else None,
        "show_title": str(raw.get("SeriesName") or "") or None, "show_id": series_id if kind != "series" else None,
        "season_no": season_no, "episode_no": ep_no,
        "code": f"S{season_no:02d}E{ep_no:02d}" if kind == "episode" and season_no is not None and ep_no is not None else None,
        "show_key": f"jf:{series_id}" if series_id else None,
        "season_key": (f"jf:{raw['SeasonId']}" if raw.get("SeasonId") else
                       f"jf:{raw['Id']}" if kind == "season" else None),
        "episode_key": f"jf:{raw['Id']}" if kind == "episode" else None,
        "cast": [f"{p['Name']} · {p['Role']}" if p.get("Role") else str(p["Name"])
                 for p in (raw.get("People") or []) if isinstance(p, dict) and p.get("Name")
                 and p.get("Type") == "Actor"][:8],
    }
    seasons = _seasons(base, headers, uid, series_id, today) if series_id else []
    files = (media_files.file_summary("tv", int(tmdb)) if kind == "series" and str(tmdb).isdigit()
             else media_files.file_summary_for_item(jf_id) if kind in ("movie", "episode") else None)
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


@router.get("/media/item/{jf_id}", response_class=HTMLResponse)
def item_page(request: Request, jf_id: str):
    from hub import main as hub  # late: hub.main includes this router

    if not ITEM_RE.match(jf_id):
        raise HTTPException(404, "No such item")
    view, from_query = hub.resolve_owner_view(request)
    snaps = hub.get_snapshots()
    src = hub.find_detail_source(hub.JELLYFIN_SNAPSHOT_ID, snaps)
    if src is None:
        raise HTTPException(404, "No such item")
    data = _data(jf_id)
    item = data["item"] if data else {"kind": "unknown", "id": jf_id, "title": "Jellyfin item", "year": None,
                                      "genres": [], "cast": [], "poster": None, "backdrop": None, "tmdb": None}
    if data:
        request.state.media_section = "movies" if item["kind"] == "movie" else "tv"
    owner = media_db.owner_of(view)
    rating = _rating_for(item, media_db.rating_level(owner)) if data else None
    ratings = hub._ratings(view, [{"item_key": rating["item_key"]}] if rating else [])
    snap_server = (src["data"] or {}).get("server_id")
    creds = media_files._creds()
    server = _server_id(*creds, snap_server) if creds else snap_server
    resp = hub.templates.TemplateResponse(request, "media_item.html", {
        "areas": hub.registry.areas, "active_id": None, "owner_view": view,
        "status": hub.build_status(snaps), "src": src, "item": item,
        "seasons": data["seasons"] if data else [], "files": data["files"] if data else None,
        "note": None if data else DOWN_TEXT, "rating": rating,
        "score": ratings.get(rating["item_key"]) if rating else None,
        "diary": _diary_dates(item, owner) if data else [],
        "play_href": hub._deep_link(src["href"], jf_id, server),
        "seerr_href": (f"/media/title/{'movie' if item['kind'] == 'movie' else 'tv'}/{item['tmdb']}"
                       if item["tmdb"] and str(item["tmdb"]).isdigit() else None)})
    return hub._maybe_set_cookie(resp, view, from_query)
