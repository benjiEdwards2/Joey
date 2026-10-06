"""The film page (F10, 2026-10-06): ONE Cinema-layout page for every title, whether it is on the server or
not. Merges Jellyfin item data (hub/media_item.py) with Jellyseerr title data (hub/media_discover.py) into
one `film` dict, rendered by media_film.html. Both URL families resolve here:
/media/title/{kind}/{tmdb_id} and /media/item/{jf_id}.

Live reads (Jellyfin and Jellyseerr, server-side only) are cached 10 min per path and every upstream failure
degrades to a missing section, never a 500. Logs carry exception TYPES only; the page carries no URL or key
except the Play deep link and the "Open in Jellyseerr" link (as the old title page did).
"""

from __future__ import annotations

import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from hub import media_db, media_discover as md, media_files, media_item, media_plays_db
from hub.media_library import runtime_text
from hub.media_watchlist import keys_for, on_server_keys

log = logging.getLogger("hub.media_film")
router = APIRouter()

BADGES_DIR = Path(__file__).resolve().parent / "static" / "badges"
CAST_MAX, SHELF_MAX = 8, 10
REGION = "AU"
JUSTWATCH = "https://www.justwatch.com/au/search?q="
RELEASE_TYPES = {3: "Cinema", 4: "Digital", 5: "Disc"}
ARR_LABELS = {"Cinemas": "Cinema", "Digital": "Digital", "Disc": "Disc"}
PROVIDER_GROUPS = (("Stream", "flatrate"), ("Rent", "rent"), ("Buy", "buy"))


# ---- cached Jellyseerr reads (shares media_discover's cache, so its clear_cache() clears these too) ----

def _cget(path: str):
    key = f"film:{path}"
    hit = md._cache.get(key)
    if hit and time.time() - hit[0] < md.CACHE_TTL:
        return hit[1]
    body = md._get(path)
    if body is None:
        return None  # a failed fetch is not cached
    md._cache[key] = (time.time(), body)
    return body


def _results(body, kind: str) -> list[dict]:
    return md._rows(body["results"], kind)[:SHELF_MAX] if isinstance(body, dict) and isinstance(body.get("results"), list) else []


def _score(value) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0 else None


def parse_ratings(body) -> dict:
    """IMDb / Rotten Tomatoes words from either Jellyseerr ratings shape (combined {rt, imdb} or flat RT)."""
    out: dict = {}
    if not isinstance(body, dict):
        return out
    rt = body.get("rt") if isinstance(body.get("rt"), dict) else body if "criticsScore" in body else None
    imdb = body.get("imdb") if isinstance(body.get("imdb"), dict) else None
    if rt and _score(rt.get("criticsScore")):
        out["rt"] = f"{int(_score(rt['criticsScore']))} %"
    if imdb and _score(imdb.get("criticsScore")):
        out["imdb"] = f"{_score(imdb['criticsScore']):.1f}"
    return out


def _ratings(kind: str, tmdb: int) -> dict:
    return parse_ratings(_cget(f"/api/v1/{kind}/{tmdb}/ratingscombined")) or parse_ratings(_cget(f"/api/v1/{kind}/{tmdb}/ratings"))


# ---- small pure helpers ----

def _short(words: str | None) -> str | None:
    """'12 Oct 2026' -> '12 Oct' when it is this year."""
    if not words:
        return None
    from datetime import date
    year = f" {date.today().year}"
    return words[: -len(year)] if words.endswith(year) else words


def _next_episode(seasons: list[dict]) -> dict | None:
    for i, s in enumerate(seasons):
        for e in s["episodes"]:
            if e["in_progress"] or (not e["played"] and e["aired"]):
                n = s.get("number") if s.get("number") is not None else i + 1
                return {"jf_id": e["jf_id"], "season": n, "number": e["number"], "label": f"S{n} E{e['number']}"}
    return None


def _override(badge_id) -> str | None:
    for ext in ("svg", "png"):
        if badge_id and (BADGES_DIR / f"{badge_id}.{ext}").is_file():
            return f"/static/badges/{badge_id}.{ext}"
    return None


def pills_for(files: dict | None) -> list[dict]:
    """Quality pills for the file strip: media_files words, tone + optional override image per pill."""
    out = []
    for b in ((files or {}).get("video") or []) + ((files or {}).get("audio") or []):
        p = media_files.badge_pill(b["word"], b["icon"])
        out.append({**p, "img": _override(p["id"])})
    if files and files.get("kind") == "tv" and files.get("episodes_on_disk"):
        n = files["episodes_on_disk"]
        out.insert(0, {"id": None, "label": f"{n} episode{'s' if n != 1 else ''} on disk", "tone": "plain",
                       "glyph": False, "icon": "disk", "img": None})
    if files and files.get("size_text"):
        out.append({"id": None, "label": files["size_text"], "tone": "plain", "glyph": False, "icon": "disk", "img": None})
    return out


def status_line(f: dict) -> str:
    """The words-first line: what we know about this title, in one sentence of ' · ' pieces."""
    if f["jf_failed"]:
        return media_item.DOWN_TEXT
    if not f["on_server"]:
        parts = ["Not on your server"]
        if f.get("requested_when"):
            parts.append(f"Requested {f['requested_when']}")
        if f.get("status_word") in ("Processing", "Partly available") or (f.get("status_word") == "Requested" and not f.get("requested_when")):
            parts.append(f["status_word"])
        if f.get("downloading_pct") is not None:
            parts.append(f"downloading {f['downloading_pct']} %")
        return " · ".join(parts)
    parts = ["On your server"]
    if f["kind"] == "tv":
        s = f.get("series")
        if s:
            parts.append(f"{s['episodes']} episode{'s' if s['episodes'] != 1 else ''}")
            parts.append(f"{s['to_watch']} to watch" if s["to_watch"] else "all watched")
            if f.get("next_ep"):
                parts.append(f"{f['next_ep']['label']} next")
    else:
        res = next((b["word"] for b in (f.get("files") or {}).get("video", []) if b["icon"] == "res"), None)
        hdr = next((b["word"] for b in (f.get("files") or {}).get("video", []) if b["icon"] == "hdr"), None)
        parts += [p for p in (res, hdr) if p]
        if f.get("played") or f.get("watch_count"):
            parts.append(f"watched {f['last_watched']}" if f.get("last_watched") else "watched")
        else:
            parts.append("in progress" if f.get("in_progress") else "not watched yet")
    if f.get("downloading_pct") is not None:
        parts.append(f"downloading {f['downloading_pct']} %")
    if f.get("score"):
        parts.append(f"you rated {f['score']}")
    return " · ".join(parts)


# ---- the merge ----

def _jf_from_snapshot(jelly: dict, kind: str, tmdb: int) -> dict | None:
    for r in jelly.get("movies" if kind == "movie" else "shows") or []:
        if isinstance(r, dict) and r.get("item_key") == f"tmdb:{tmdb}" and media_item.ITEM_RE.match(str(r.get("jf_id") or "")):
            return r
    return None


def _requested(snaps, hub, tmdb) -> dict | None:
    snap = snaps.get(hub.JELLYSEERR_SNAPSHOT_ID)
    for r in ((snap.data if snap else {}) or {}).get("requests") or []:
        if isinstance(r, dict) and str(r.get("tmdb_id")) == str(tmdb):
            return r
    return None


def _releases(raw: dict, arr: dict, tmdb) -> list[dict]:
    """Cinema / Digital / Disc dates: Jellyseerr `releases` (AU, else US), topped up from the arr calendar."""
    found: dict[str, str] = {}
    results = [r for r in ((raw.get("releases") or {}).get("results") or []) if isinstance(r, dict)]
    region = next((r for code in (REGION, "US") for r in results if r.get("iso_3166_1") == code), None)
    for rd in (region or {}).get("release_dates") or []:
        label = RELEASE_TYPES.get(rd.get("type")) if isinstance(rd, dict) else None
        day = str(rd.get("release_date") or "")[:10] if label else ""
        if label and day and (label not in found or day < found[label]):
            found[label] = day
    for r in arr.get("this_week") or []:
        label = ARR_LABELS.get(r.get("label")) if isinstance(r, dict) and r.get("item_key") == f"tmdb:{tmdb}" else None
        if label and label not in found and r.get("date"):
            found[label] = str(r["date"])[:10]
    return [{"label": label, "date": md._date_words(found[label])[0]} for label in ("Cinema", "Digital", "Disc")
            if label in found and md._date_words(found[label])[0]]


def _trailer(jf_url, raw: dict) -> str | None:
    if jf_url:
        return jf_url
    for v in raw.get("relatedVideos") or []:
        url = str(v.get("url") or "") if isinstance(v, dict) else ""
        if v.get("site") == "YouTube" and v.get("type") == "Trailer" and url.startswith("https://"):
            return url
    return None


def _cast(raw: dict, people: list[dict]) -> list[dict]:
    out = []
    for c in ((raw.get("credits") or {}).get("cast") or []):
        if isinstance(c, dict) and c.get("name") and len(out) < CAST_MAX:
            out.append({"name": str(c["name"])[:80], "role": str(c.get("character") or "")[:80],
                        "ref": md._ref(c.get("profilePath"))})
    if out:
        return out
    return [{"name": p["name"], "role": p["role"], "ref": p["ref"]} for p in people if p["type"] == "Actor"][:CAST_MAX]


def _makers(raw: dict, people: list[dict], kind: str) -> list[str]:
    if kind == "tv":
        names = [c.get("name") for c in raw.get("createdBy") or [] if isinstance(c, dict)]
    else:
        names = [c.get("name") for c in ((raw.get("credits") or {}).get("crew") or [])
                 if isinstance(c, dict) and c.get("job") == "Director"]
    names = [str(n)[:80] for n in names if n] or [p["name"] for p in people if p["type"] == "Director"]
    return list(dict.fromkeys(names))[:4]


def _providers(raw: dict, title: str) -> list[dict]:
    entry = next((p for p in raw.get("watchProviders") or [] if isinstance(p, dict) and p.get("iso_3166_1") == REGION), None)
    out = []
    for label, field in PROVIDER_GROUPS:
        names = [str(p.get("name")) for p in (entry or {}).get(field) or [] if isinstance(p, dict) and p.get("name")]
        if names:
            out.append({"label": label, "names": names[:8], "href": JUSTWATCH + quote(title, safe="")})
    return out


def _languages(files: dict | None) -> str | None:
    bits = []
    if (files or {}).get("languages"):
        bits.append("Audio " + ", ".join(files["languages"][:4]))
    if (files or {}).get("subtitles"):
        bits.append("Subtitles " + ", ".join(files["subtitles"][:6]))
    return " · ".join(bits) or None


def _shelves(raw: dict, kind: str, lib_keys: set, similar, recs) -> list[dict]:
    paths = [("Collection", None), ("Similar", similar), ("Recommended", recs)]
    col = raw.get("collection") if isinstance(raw.get("collection"), dict) else None
    if col and isinstance(col.get("id"), int):
        body = _cget(f"/api/v1/collection/{col['id']}")
        parts = body.get("parts") if isinstance(body, dict) else None
        paths[0] = (str(col.get("name") or "Collection")[:80], parts if isinstance(parts, list) else None)
    out = []
    for title, src in paths:
        if isinstance(src, list):
            rows = md._rows(src, "movie")[:SHELF_MAX]
        elif isinstance(src, dict):
            rows = _results(src, kind)
        else:
            rows = []
        rows = [{**r, "on_server": f"tmdb:{r['tmdb_id']}" in lib_keys or r["status_word"] in md.ON_DISK} for r in rows]
        if rows:
            out.append({"title": title, "rows": rows})
    return out


def build_film(kind: str | None = None, tmdb_id: int | None = None, jf_id: str | None = None, *,
               view: str, request: Request, hub, req_state: str = "idle", req_msg: str | None = None) -> dict:
    snaps = hub.get_snapshots()
    jsrc = hub.find_detail_source(hub.JELLYFIN_SNAPSHOT_ID, snaps)
    jelly = (jsrc or {}).get("data") or {}
    owner = media_db.owner_of(view)
    arr_snap = snaps.get(hub.ARR_SNAPSHOT_ID)
    arr = (arr_snap.data if arr_snap else {}) or {}
    f: dict = {"note": None, "jf_failed": False, "req_state": req_state, "req_msg": req_msg}

    # --- 1. Jellyfin side: base (film / series), plus the episode when the page is for one ---
    base, ep, row = None, None, None
    if jf_id:
        got = media_item._data(jf_id)
        if got is None:
            f["jf_failed"] = True
        else:
            it = got["item"]
            ep = it if it["kind"] == "episode" else None
            show = media_item._data(it["show_id"]) if it["kind"] in ("episode", "season") and it.get("show_id") else None
            base = show or got
    elif tmdb_id and kind:
        row = _jf_from_snapshot(jelly, kind, tmdb_id)
        if row:
            base = media_item._data(row["jf_id"])
            f["jf_failed"] = base is None
    item = base["item"] if base else None
    seasons = (base or {}).get("seasons") or []
    if item:
        kind = "movie" if item["kind"] == "movie" else "tv"
        if not (tmdb_id and kind) and str(item.get("tmdb") or "").isdigit():
            tmdb_id = int(item["tmdb"])
    f["kind"] = kind
    jf_item_id = item["id"] if item else (row["jf_id"] if row else None)

    # --- 2. Jellyseerr side: one title body + ratings + shelves, in parallel ---
    raw, t, ratings, similar, recs = {}, None, {}, None, None
    connected = md._creds() is not None
    if tmdb_id and kind and connected:
        with ThreadPoolExecutor(max_workers=4) as pool:
            futs = [pool.submit(fn, *args) for fn, args in (
                (_cget, (f"/api/v1/{kind}/{tmdb_id}",)), (_ratings, (kind, tmdb_id)),
                (_cget, (f"/api/v1/{kind}/{tmdb_id}/similar",)), (_cget, (f"/api/v1/{kind}/{tmdb_id}/recommendations",)))]
            body, ratings, similar, recs = (x.result() for x in futs)
        if isinstance(body, dict):
            raw, t = body, md.title_from(body, kind, tmdb_id)
    f["t"], f["connected"] = t, connected
    if tmdb_id and not item and not t:
        f["note"] = "Title unavailable" if connected else "Not connected"

    # --- 3. what is on the server ---
    files = (base or {}).get("files")
    if files is None and t and t["status_word"] in md.ON_DISK and not item:
        files = media_files.file_summary(kind, tmdb_id)
    on_server = bool(item or row or jf_id and not f["jf_failed"] or (t and t["status_word"] in md.ON_DISK))
    f.update(on_server=on_server, files=files, pills=pills_for(files), status_word=(t or {}).get("status_word"))
    title = (item["title"] if item else (t or {}).get("title") or (row or {}).get("title")
             or ("Jellyfin item" if jf_id else "Title unavailable"))
    year = (item["year"] if item else (t or {}).get("year") or (row or {}).get("year"))
    f.update(title=title, year=year, tagline=(t or {}).get("tagline") or "",
             overview=(item or {}).get("overview") or (t or {}).get("overview") or "",
             genres=(item or {}).get("genres") or (t or {}).get("genres") or [],
             official=(item or {}).get("official_rating"),
             backdrop=(item["backdrop"] if item else (row or {}).get("backdrop") if row else None) or (t or {}).get("backdrop"),
             poster=(item["poster"] if item else (row or {}).get("poster")) or (t or {}).get("poster"),
             jellyseerr_href=(t or {}).get("jellyseerr_href"), tmdb=tmdb_id)

    # --- 4. watch state, Play, series summary ---
    played, in_progress, left = (item["played"], item["in_progress"], item["left_text"]) if item and kind == "movie" else (False, False, None)
    f.update(played=played, in_progress=in_progress)
    snap_server = jelly.get("server_id")
    creds = media_files._creds()
    server = media_item._server_id(*creds, snap_server) if creds and (jf_item_id or jf_id) else snap_server
    href_of = lambda i: hub._deep_link((jsrc or {}).get("href"), i, server)
    f["play"] = None
    f["series"], f["next_ep"] = None, None
    if kind == "tv" and seasons:
        eps = [e for s in seasons for e in s["episodes"]]
        nxt = _next_episode(seasons)
        f["series"] = {"episodes": len(eps), "to_watch": sum(1 for e in eps if not e["played"] and e["aired"])}
        f["next_ep"] = nxt
        title_key = f"{title} · "
        for r in arr.get("this_week") or []:
            if isinstance(r, dict) and r.get("kind") == "episode" and str(r.get("title") or "").startswith(title_key):
                code = re.search(r"S\d+E\d+", r["title"])
                f["next_air"] = {"code": code.group(0) if code else "", "date": md._date_words(r.get("date"))[0]}
                break
        if jf_item_id:
            f["play"] = ({"href": href_of(nxt["jf_id"]), "label": f"Next to watch: {nxt['label']} ▶"} if nxt
                         else {"href": href_of(jf_item_id), "label": "Play ▶"})
    elif jf_item_id or f["jf_failed"]:
        pid = jf_item_id or jf_id
        label = (f"Resume ▶ · {left}" if left else "Resume ▶") if in_progress else "Play again ▶" if played else "Play ▶"
        f["play"] = {"href": href_of(pid), "label": label}
    f["seasons"] = seasons
    if ep:
        f["episode"] = {"code": ep["code"], "title": ep["title"], "air_date": ep["air_date"],
                        "overview": ep["overview"], "runtime": ep["runtime"],
                        "play": {"href": href_of(ep["id"]),
                                 "label": ("Resume ▶" + (f" · {ep['left_text']}" if ep["left_text"] else "")) if ep["in_progress"]
                                 else "Play again ▶" if ep["played"] else "Play ▶"},
                        "show_href": f"/media/item/{item['id']}" if item and item["kind"] == "series" else None}
        f["episode_season"] = ep["season_no"]
    else:
        f["episode"] = None

    # --- 5. your rating, diary, watches ---
    key_item = ep or item
    if key_item:
        rating = media_item._rating_for(key_item, media_db.rating_level(owner))
    elif tmdb_id and t:
        rating = {"item_key": f"tmdb:{tmdb_id}", "kind": kind, "level": "show", "title": title,
                  "year": year, "poster": t.get("poster")}
    else:
        rating = None
    ratings_map = hub._ratings(view, [{"item_key": rating["item_key"]}] if rating else [])
    f["rating"] = rating
    f["score"] = ratings_map.get(rating["item_key"]) if rating else None
    diary_item = key_item or {"kind": "movie" if kind == "movie" else "series", "id": "", "tmdb": tmdb_id,
                              "episode_key": None, "season_key": None}
    dates = media_item._diary_dates(diary_item, owner) if (rating or item) else []
    count = max(len(dates), media_plays_db.watch_count(jf_item_id, owner) if jf_item_id and kind == "movie" else 0)
    last = _short(dates[0]) if dates else (_short(md._date_words(item.get("last_played"))[0]) if item and item.get("last_played") else None)
    f.update(diary=dates, watch_count=count, last_watched=last)

    # --- 6. request / downloading ---
    req = _requested(snaps, hub, tmdb_id) if tmdb_id else None
    f["requested_when"] = req.get("when") if req else None
    f["requested_by"] = req.get("requested_by") if req else None
    badge = md._dl_badge(title) if title and not f["jf_failed"] else None
    m = re.search(r"(\d+)\s*%", badge or "")
    f["downloading_pct"] = int(m.group(1)) if m else None

    # --- 7. numbers, facts, people, shelves ---
    runtime_min = (item or {}).get("runtime_min") or (t or {}).get("runtime") if kind == "movie" else None
    if ep:
        runtime_min = ep.get("runtime_min")
    mins = (int("".join(c for c in left if c.isdigit()) or 0) if in_progress and left else None) or runtime_min
    ends = None
    if mins and (kind == "movie" or ep):
        ends = (hub._now_home() + timedelta(minutes=mins)).strftime("%H:%M")
    community = (f"{item['community_rating']} / 10" if item and item.get("community_rating") else (t or {}).get("vote"))
    f["numbers"] = {"community": community, "imdb": ratings.get("imdb"), "rt": ratings.get("rt"),
                    "runtime": runtime_text(runtime_min) if runtime_min else None, "ends": ends}
    added = md._date_words(item.get("added"))[0] if item and item.get("added") else None
    f["facts"] = {"runtime": runtime_text(runtime_min) if runtime_min else None,
                  "languages": _languages(files), "added": added,
                  "releases": _releases(raw, arr, tmdb_id) if kind == "movie" else [],
                  "seasons": (f"{t['n_seasons']} season{'s' if t['n_seasons'] != 1 else ''}"
                              + (f" · {t['n_episodes']} episodes" if t.get("n_episodes") else "")) if kind == "tv" and t and t.get("n_seasons") else None}
    people = (item or {}).get("people") or []
    f["cast"], f["makers"] = _cast(raw, people), _makers(raw, people, kind or "movie")
    f["makers_label"] = "Creators" if kind == "tv" else "Director"
    f["providers"] = _providers(raw, title)
    f["trailer"] = _trailer((item or {}).get("trailer"), raw)
    lib_keys = on_server_keys(jelly, "movie") | on_server_keys(jelly, "tv")
    f["shelves"] = _shelves(raw, kind, lib_keys, similar, recs) if raw and kind and tmdb_id else []
    f["wl_on"] = bool(keys_for(request, [f"tmdb:{tmdb_id}"])) if tmdb_id else False
    f["show_request"] = bool(t and t["code"] != 5 and not (kind == "movie" and on_server))
    f["status_line"] = status_line(f)
    if kind and (jf_id or on_server):  # an off-server title keeps the Discover section it was found in
        request.state.media_section = "movies" if kind == "movie" else "tv"
    return f


# ---- routes ----

def _render(request: Request, hub, src, film: dict, view, from_query):
    resp = hub.templates.TemplateResponse(request, "media_film.html", {
        "areas": hub.registry.areas, "active_id": None, "owner_view": view,
        "status": hub.build_status(hub.get_snapshots()), "src": src, "film": film})
    return hub._maybe_set_cookie(resp, view, from_query)


@router.get("/media/title/{kind}/{tmdb_id}", response_class=HTMLResponse)
def title_page(request: Request, kind: str, tmdb_id: int, step: str = "", requested: str = "", error: str = ""):
    from hub import main as hub  # late: hub.main includes this router

    kind = md._kind(kind)
    view, from_query = hub.resolve_owner_view(request)
    src = hub.find_detail_source(hub.JELLYSEERR_SNAPSHOT_ID, hub.get_snapshots(), detail=md.DISCOVER_DETAIL)
    if src is None:
        return hub.templates.TemplateResponse(request, "404.html", {
            "areas": hub.registry.areas, "active_id": None, "owner_view": view,
            "missing_text": "No page here"}, status_code=404)
    state, msg = (("done", None) if requested == "1" else ("error", md.ERRORS[error]) if error in md.ERRORS
                  else ("confirm" if step == "confirm" else "idle", None))
    film = build_film(kind, tmdb_id, view=view, request=request, hub=hub, req_state=state, req_msg=msg)
    return _render(request, hub, src, film, view, from_query)


@router.get("/media/item/{jf_id}", response_class=HTMLResponse)
def item_page(request: Request, jf_id: str):
    from hub import main as hub

    if not media_item.ITEM_RE.match(jf_id):
        raise HTTPException(404, "No such item")
    view, from_query = hub.resolve_owner_view(request)
    src = hub.find_detail_source(hub.JELLYFIN_SNAPSHOT_ID, hub.get_snapshots())
    if src is None:
        raise HTTPException(404, "No such item")
    film = build_film(jf_id=jf_id, view=view, request=request, hub=hub)
    return _render(request, hub, src, film, view, from_query)
