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

from hub import media_db, media_discover as md, media_files, media_follow, media_item, media_omdb, media_plays_db, media_rank
from hub.media_library import runtime_text
from hub.media_watchlist import keys_for, on_server_keys

log = logging.getLogger("hub.media_film")
router = APIRouter()

BADGES_DIR = Path(__file__).resolve().parent / "static" / "badges"
LOGO_IDS = ("imdb", "rt", "mc", "tmdb", "lbxd", "you")   # media-ux4: hub/static/logos/<id>.svg monograms
CAST_MAX, SHELF_MAX = 8, 10
CAST_H = 400   # /img size of a portrait cast card (180 x 270 px; TMDB w500 covers 2x). The warm-up warms the same.
CREW_ROLES = (("Director", ("Director",)), ("Writer", ("Screenplay", "Writer", "Story", "Novel")),
              ("Cinematography", ("Director of Photography", "Cinematographer", "Cinematography")),
              ("Composer", ("Original Music Composer", "Music")), ("Editor", ("Editor",)))
CREW_NAMES = 4
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
    body, code = md._fetch(path)
    if body is None and code != 404:
        return None  # a failed fetch is not cached; a 404 is an answer (nothing there) and is (media-speed)
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
        out["rt"] = f"{int(_score(rt['criticsScore']))}%"   # media-ux4: one score format ("90%")
    if imdb and _score(imdb.get("criticsScore")):
        out["imdb"] = f"{_score(imdb['criticsScore']):.1f}"
    return out


def _ratings(kind: str, tmdb: int) -> dict:
    """IMDb / RT words. Ratings carry no user state, so they ride the long, restart-proof meta cache, and a
    404 ("no ratings for this title") is remembered rather than re-asked on every open (media-speed).
    Jellyseerr has `ratingscombined` for films only — a TV title goes straight to `ratings`."""
    if kind == "tv":
        return parse_ratings(md.meta_get(f"/api/v1/tv/{tmdb}/ratings"))
    return (parse_ratings(md.meta_get(f"/api/v1/{kind}/{tmdb}/ratingscombined"))
            or parse_ratings(md.meta_get(f"/api/v1/{kind}/{tmdb}/ratings")))


def _collection_id(body) -> int | None:
    col = body.get("collection") if isinstance(body, dict) and isinstance(body.get("collection"), dict) else None
    return col["id"] if col and isinstance(col.get("id"), int) else None


def seerr_bundle(kind: str, tmdb: int) -> tuple:
    """(title body, ratings, similar, recommendations) for one title, read side by side; the collection read
    starts the moment the title body names one (it lands in _cget's cache for _shelves)."""
    with ThreadPoolExecutor(max_workers=5) as pool:
        body_f = pool.submit(_cget, f"/api/v1/{kind}/{tmdb}")
        rest = [pool.submit(_ratings, kind, tmdb), pool.submit(_cget, f"/api/v1/{kind}/{tmdb}/similar"),
                pool.submit(_cget, f"/api/v1/{kind}/{tmdb}/recommendations")]
        body = body_f.result()
        col = _collection_id(body)
        col_f = pool.submit(_cget, f"/api/v1/collection/{col}") if col is not None else None
        ratings, similar, recs = (x.result() for x in rest)
        if col_f is not None:
            col_f.result()
    return body, ratings, similar, recs


def tmdb_hint(jelly: dict, jf_id: str) -> tuple[str, int] | None:
    """(kind, tmdb) for a Jellyfin id from the library snapshot alone — a film or show row directly, an
    episode through the show key its up-next / history / latest row carries. Lets the Jellyseerr reads start
    before the Jellyfin item read has answered. None when the snapshot can't tell."""
    def tmdb_of(r):
        key = str(r.get("item_key") or "")
        return int(key[5:]) if key.startswith("tmdb:") and key[5:].isdigit() else None

    profiles = [jelly] + [jelly["her"]] if isinstance(jelly.get("her"), dict) else [jelly]
    by_jf: dict[str, tuple[str, int]] = {}
    for prof in profiles:
        for field, kind in (("movies", "movie"), ("shows", "tv")):
            for r in prof.get(field) or []:
                if isinstance(r, dict) and r.get("jf_id") and tmdb_of(r):
                    by_jf.setdefault(str(r["jf_id"]), (kind, tmdb_of(r)))
    if jf_id in by_jf:
        return by_jf[jf_id]
    for prof in profiles:
        rows = (prof.get("up_next") or []) + (prof.get("now_playing") or []) + (prof.get("latest") or []) \
            + ((prof.get("history") or {}).get("recent") or [])
        for r in rows:
            if isinstance(r, dict) and str(r.get("jf_id") or "") == jf_id:
                show = str(r.get("show_key") or "")
                if show.startswith("jf:") and show[3:] in by_jf:
                    return by_jf[show[3:]]
    return None


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


def episode_state(e: dict) -> dict:
    """One episode's state as a word + a colour class (the word is never left out): Watched · In progress 23m
    left · Not aired · Not watched."""
    if e.get("played"):
        return {"word": "Watched", "cls": "st-good", "key": "watched"}
    if e.get("in_progress"):
        left = e.get("left_min")
        return {"word": f"In progress · {left}m left" if left else "In progress", "cls": "st-progress", "key": "progress"}
    if not e.get("aired"):
        return {"word": "Not aired", "cls": "st-off", "key": "unaired"}
    return {"word": "Not watched", "cls": "st-todo", "key": "todo"}


def episode_list(seasons: list[dict], href_of, page_season=None, next_ep: dict | None = None) -> list[dict]:
    """The Seasons section's data (2026-10-08): per season `open` (the page's episode's season, else the next
    episode's, else the last one) and per episode its state word and Play / Resume deep link. Copies — the
    seasons come from media_item's shared cache and are never changed in place."""
    out = []
    for i, s in enumerate(seasons or []):
        n = s.get("number") if s.get("number") is not None else i + 1
        eps = []
        for e in s.get("episodes") or []:
            play = None
            href = href_of(e["jf_id"]) if href_of and e.get("aired") else None
            if href:
                label = ("Resume ▶" + (f" · {e['left_min']}m left" if e.get("left_min") else "")) if e.get("in_progress")                     else "Play again ▶" if e.get("played") else "Play ▶"
                play = {"href": href, "label": label}
            eps.append({**e, "state": episode_state(e), "play": play})
        aired = [e for e in eps if e.get("aired")]
        # media-ux3: the season header offers "Mark season unwatched" once every aired episode is watched
        out.append({**s, "n": n, "episodes": eps, "open": False,
                    "all_watched": bool(aired) and all(e.get("played") for e in aired)})
    want = page_season if page_season is not None else (next_ep or {}).get("season")
    pick = next((s for s in out if s["n"] == want), None) if want is not None else None
    if pick is None and out:
        pick = out[-1]
    if pick is not None:
        pick["open"] = True
    return out


def listed_episode(ep: dict, seasons: list[dict]) -> dict:
    """The page's episode with its watch state taken from the show's season list (media-ux4, 2026-10-08) — the list the
    "part of" banner counts and the episode rows show. The episode's own item read is a separate cache entry, read at
    another time, so on a fully watched show the hero could say "Mark watched" beside "10 of 10 watched". Matched by
    Jellyfin id, else by season + episode number (a duplicate item of the same episode: the listed one's id is used,
    so the hero acts on the episode the banner counts). Not listed: unchanged."""
    hit = None
    for s in seasons or []:
        hit = next((e for e in s.get("episodes") or [] if e.get("jf_id") == ep.get("id")), None)
        if hit:
            break
    if hit is None and ep.get("season_no") is not None and ep.get("episode_no") is not None:
        for i, s in enumerate(seasons or []):
            n = s.get("number") if s.get("number") is not None else i + 1
            if n == ep["season_no"]:
                hit = next((e for e in s.get("episodes") or [] if e.get("number") == ep["episode_no"]), None)
                break
    if hit is None:
        return ep
    prog, left = bool(hit.get("in_progress")), hit.get("left_min")
    jf = hit["jf_id"] if media_item.ITEM_RE.match(str(hit.get("jf_id") or "")) else ep["id"]
    return {**ep, "id": jf, "played": bool(hit.get("played")), "in_progress": prog,
            "left_text": (f"{left} min left" if left else ep.get("left_text")) if prog else None}


def logos() -> dict:
    """{id: url} for the score / site pills (media-ux4, 2026-10-08): `hub/static/badges/logo-<id>.svg|png` when dropped
    in (the badge override folder), else the shipped monogram `/static/logos/<id>.svg`."""
    return {i: _override(f"logo-{i}") or f"/static/logos/{i}.svg" for i in LOGO_IDS}


def score_text(value) -> str | None:
    """A 0-10 score in the pills' one format: 8.0 -> "8.0", "7.4 / 10" -> "7.4"; None when absent."""
    m = re.match(r"\s*(\d+(?:\.\d+)?)", str(value)) if value is not None else None
    return f"{float(m.group(1)):.1f}" if m and float(m.group(1)) > 0 else None


def imdb_id(raw: dict, item: dict | None) -> str | None:
    """The title's IMDb id: Jellyseerr's `externalIds.imdbId` (films and shows), its film-only `imdbId`, else Jellyfin's
    ProviderIds.Imdb (media_item `imdb`)."""
    ext = raw.get("externalIds") if isinstance(raw.get("externalIds"), dict) else {}
    for v in (ext.get("imdbId"), raw.get("imdbId"), (item or {}).get("imdb")):
        if isinstance(v, str) and media_omdb.IMDB_RE.match(v.strip()):
            return v.strip()
    return None


def mc_band(score) -> str | None:
    """Metacritic's colour band: good >= 61, mid 40-60, bad < 40 (the number is always shown too)."""
    if not isinstance(score, int) or isinstance(score, bool):
        return None
    return "good" if score >= 61 else "mid" if score >= 40 else "bad"


def _override(badge_id) -> str | None:
    for ext in ("svg", "png"):
        if badge_id and (BADGES_DIR / f"{badge_id}.{ext}").is_file():
            return f"/static/badges/{badge_id}.{ext}"
    return None


# Format badges (film-quality, 2026-10-07): MediaHub-style TEXT badges — a bold main word over a small uppercase
# sub-label (1080p / FULL HD, H.265 / HEVC, 5.1 / SURROUND). No brand artwork; an image dropped in
# hub/static/badges/<id>.svg|png still replaces a badge (the words stay as its alt text).
BADGE_WORDS = {"4K": ("4K", "ULTRA HD"), "1080p": ("1080p", "FULL HD"), "720p": ("720p", "HD"), "SD": ("SD", ""),
               "HEVC": ("H.265", "HEVC"), "H.264": ("H.264", "AVC"), "Dolby Vision": ("Vision", "DOLBY"),
               "HDR10": ("HDR10", ""), "HDR10+": ("HDR10+", ""), "HLG": ("HLG", "HDR"),
               "Dolby Digital Plus": ("DD+", "DOLBY"), "Dolby Digital": ("DD", "DOLBY"), "TrueHD": ("TrueHD", "DOLBY"),
               "Atmos": ("Atmos", "DOLBY"), "DTS-HD": ("DTS-HD", ""), "5.1": ("5.1", "SURROUND"),
               "7.1": ("7.1", "SURROUND"), "Stereo": ("2.0", "STEREO"), "Mono": ("1.0", "MONO")}


def _slug(word: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", word.lower()).strip("-")


def badge(word: str) -> dict:
    """One badge word -> {main, sub, label, id, img}. `id` keeps the F10 override names (dolby-atmos, hdr10, ...)."""
    main, sub = BADGE_WORDS.get(word, (word, ""))
    bid = media_files.badge_pill(word)["id"] or _slug(word)
    label = media_files.badge_pill(word)["label"]
    return {"main": main, "sub": sub, "label": label, "id": bid, "img": _override(bid)}


def badges_for(files: dict | None) -> list[dict]:
    """The File panel's badge row: resolution, HDR, video codec, audio format, channels, Atmos, then the source
    from the file name (Blu-ray, WEB-DL, Remux ...). The container lives in the Release row instead."""
    files = files or {}
    words = [b["word"] for b in files.get("video") or [] if b["icon"] in ("res", "hdr", "codec")]
    words += [b["word"] for b in files.get("audio") or []]
    out = [badge(w) for w in words]
    if files.get("source"):
        out.append({**badge(files["source"]), "source": True})
    return out


def crew_for(raw: dict, kind: str) -> list[dict]:
    """[{role, people: [{name, id}]}] — Director, Writer (screenplay / writer / story / novel, de-duplicated),
    Cinematography, Composer, Editor from TMDB credits.crew; a show leads with Created by. Empty roles drop out."""
    crew = [c for c in ((raw.get("credits") or {}).get("crew") or []) if isinstance(c, dict) and c.get("name")]
    roles = []
    if kind == "tv":
        roles.append(("Created by", [c for c in raw.get("createdBy") or [] if isinstance(c, dict) and c.get("name")]))
    for role, jobs in CREW_ROLES:
        roles.append((role, [c for c in crew if c.get("job") in jobs]))
    out = []
    for role, found in roles:
        people: dict[str, dict] = {}
        for c in found:
            name = str(c["name"])[:80]
            people.setdefault(name, {"name": name, "id": _pid(c.get("id"))})
        if people:
            out.append({"role": role, "people": list(people.values())[:CREW_NAMES]})
    return out


def file_panel(files: dict | None, kind: str | None, added: str | None) -> dict | None:
    """What the FILE section draws: badges, the stat grid, key / value rows and the file name. A film shows its
    one file; a show degrades to its total size, episode count and languages (no single file name)."""
    if not files:
        return None
    one = files.get("file") or {}
    size_text = files.get("size_text")
    grid, rows = [], []
    if size_text:
        grid.append({"label": "Size", "value": size_text, "key": "size"})
    if kind == "tv":
        n = files.get("episodes_on_disk") or files.get("files") or 0
        if n:
            grid.append({"label": "On disk", "value": f"{n} episode{'s' if n != 1 else ''}"})
    if one.get("bitrate_text"):
        grid.append({"label": "Bitrate", "value": one["bitrate_text"], "key": "bitrate"})
    if one.get("picture"):
        grid.append({"label": "Picture", "value": one["picture"]["ratio"], "sub": one["picture"]["sub"]})
    if added:
        grid.append({"label": "Added", "value": added})
    if one:
        rows += [("Audio", one.get("audio_text")), ("Subtitles", one.get("subs_text")), ("Release", one.get("release"))]
    else:
        langs, subs = files.get("languages") or [], files.get("subtitles") or []
        rows += [("Audio", ", ".join(langs[:4]) or None),
                 ("Subtitles", (subs[0] + (f" + {len(subs) - 1} more" if len(subs) > 1 else "")) if subs else None)]
    rows = [{"label": k, "value": v} for k, v in rows if v]
    if kind == "movie" and one:
        ranks = media_rank.rank(one.get("jf_id"), files.get("size"), one.get("bitrate"))
        for g in grid:
            if g.get("key") in ranks and ranks[g["key"]]:
                g["sub"] = ranks[g["key"]]
    return {"badges": badges_for(files), "grid": grid, "rows": rows, "filename": one.get("filename")}


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
    from hub.media_requests import snapshot_rows  # a removed request stops showing at once (2026-10-08)
    for r in snapshot_rows(snaps, hub.JELLYSEERR_SNAPSHOT_ID):
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
                        "ref": md._ref(c.get("profilePath")), "id": _pid(c.get("id"))})
    if out:
        return out
    return [{"name": p["name"], "role": p["role"], "ref": p["ref"], "id": None} for p in people if p["type"] == "Actor"][:CAST_MAX]


def _pid(value) -> int | None:
    """A TMDB person id for the /media/person link, else None (plain text / search fallback)."""
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _makers(raw: dict, people: list[dict], kind: str) -> list[dict]:
    if kind == "tv":
        found = [c for c in raw.get("createdBy") or [] if isinstance(c, dict)]
    else:
        found = [c for c in ((raw.get("credits") or {}).get("crew") or [])
                 if isinstance(c, dict) and c.get("job") == "Director"]
    out: dict[str, dict] = {}
    for c in found:
        if c.get("name"):
            out.setdefault(str(c["name"])[:80], {"name": str(c["name"])[:80], "id": _pid(c.get("id"))})
    if not out:
        out = {p["name"]: {"name": p["name"], "id": None} for p in people if p["type"] == "Director"}
    return list(out.values())[:4]


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


def _on_server(rows: list[dict], lib_keys: set) -> list[dict]:
    return [{**r, "on_server": f"tmdb:{r['tmdb_id']}" in lib_keys or r["status_word"] in md.ON_DISK} for r in rows]


def _shelves(raw: dict, kind: str, lib_keys: set, similar, recs) -> list[dict]:
    """Similar / Recommended (the collection moved to its own banner under Overview, media-ux3)."""
    out = []
    for title, src in (("Similar", similar), ("Recommended", recs)):
        rows = _on_server(_results(src, kind), lib_keys) if isinstance(src, dict) else []
        if rows:
            out.append({"title": title, "rows": rows, "collection_id": None})
    return out


def collection_banner(raw: dict, kind: str, lib_keys: set, tmdb_id) -> dict | None:
    """The film series banner under Overview (media-ux3, 2026-10-08): the collection's name, its parts in release order
    with On server words and the page's own film flagged, "3 films · 2 on server", and a backdrop — the collection's,
    else the first part's that has one, else None (a plain panel)."""
    col = raw.get("collection") if isinstance(raw.get("collection"), dict) else None
    col_id = col["id"] if col and isinstance(col.get("id"), int) and not isinstance(col.get("id"), bool) else None
    if kind != "movie" or col_id is None:
        return None
    body = _cget(f"/api/v1/collection/{col_id}")
    body = body if isinstance(body, dict) else {}
    parts = body.get("parts") if isinstance(body.get("parts"), list) else []
    rows = sorted(_on_server(md._rows(parts, "movie"), lib_keys), key=lambda r: (r["year"] is None, r["year"] or 0))
    if not rows:
        return None
    rows = [{**r, "current": str(r["tmdb_id"]) == str(tmdb_id)} for r in rows]
    n, on = len(rows), sum(1 for r in rows if r["on_server"])
    backdrop = md._ref(body.get("backdropPath")) or next((r["backdrop"] for r in rows if r.get("backdrop")), None)
    return {"title": str(body.get("name") or col.get("name") or "Collection")[:80], "collection_id": col_id,
            "rows": rows, "poster": md._ref(body.get("posterPath")), "backdrop": backdrop,
            "line": [f"{n} film{'s' if n != 1 else ''}", f"{on} on server"]}


def part_of(page: dict | None, item: dict | None, seasons: list[dict]) -> dict | None:
    """The "part of" banner on an episode or season page (media-ux3): the show's backdrop (when Jellyfin has one) and
    poster, "Show · Season 6 · Episode 4 · 3 of 6 watched", and links to the show page — "This season" opens and
    scrolls to that season (`?season=N#season-N`), "All seasons" lands on the Seasons section."""
    if not page or not item or item.get("kind") != "series" or page.get("kind") not in ("episode", "season"):
        return None
    n = page.get("season_no")
    season = next((s for s in seasons if s.get("n") == n), None) if n is not None else None
    line = [f"Season {n}" if n is not None else None,
            f"Episode {page['episode_no']}" if page["kind"] == "episode" and page.get("episode_no") is not None else None,
            (season or {}).get("watched_text")]
    show = f"/media/item/{item['id']}"
    return {"title": item["title"], "line": [x for x in line if x], "poster": item["poster"],
            "backdrop": item["backdrop"] if item.get("has_backdrop") else None,
            "season_href": f"{show}?season={n}#season-{n}" if page["kind"] == "episode" and n is not None else None,
            "all_href": f"{show}#seasons"}


def build_film(kind: str | None = None, tmdb_id: int | None = None, jf_id: str | None = None, *,
               view: str, request: Request, hub, req_state: str = "idle", req_msg: str | None = None,
               snaps=None, open_season: int | None = None) -> dict:
    snaps = hub.get_snapshots() if snaps is None else snaps  # media-speed: the route's one read, passed in
    jsrc = hub.find_detail_source(hub.JELLYFIN_SNAPSHOT_ID, snaps)
    jelly = (jsrc or {}).get("data") or {}
    owner = media_db.owner_of(view)
    arr_snap = snaps.get(hub.ARR_SNAPSHOT_ID)
    arr = (arr_snap.data if arr_snap else {}) or {}
    f: dict = {"note": None, "jf_failed": False, "req_state": req_state, "req_msg": req_msg}

    # media-speed (2026-10-07): the Jellyseerr reads start as soon as the title's TMDB id is known — from the
    # URL, else from the library snapshot — so they overlap the Jellyfin reads instead of following them.
    connected = md._creds() is not None
    early: dict[tuple, object] = {}
    side = ThreadPoolExecutor(max_workers=2)

    def start(k, t):
        if connected and k and t and (k, t) not in early:
            early[(k, t)] = side.submit(seerr_bundle, k, t)

    try:
        if tmdb_id and kind:
            start(kind, tmdb_id)
        elif jf_id:
            start(*(tmdb_hint(jelly, jf_id) or (None, None)))

        # --- 1. Jellyfin side: base (film / series), plus the episode when the page is for one ---
        base, ep, row, page_item = None, None, None, None
        if jf_id:
            got = media_item._data(jf_id)
            if got is None:
                f["jf_failed"] = True
            else:
                it = page_item = got["item"]
                ep = it if it["kind"] == "episode" else None
                if it["kind"] in ("episode", "season") and str(it.get("tmdb") or "").isdigit():
                    start("tv", int(it["tmdb"]))
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

        # --- 2. Jellyseerr side: one title body + ratings + shelves, in parallel ---
        raw, t, ratings, similar, recs = {}, None, {}, None, None
        if tmdb_id and kind and connected:
            fut = early.get((kind, tmdb_id))
            body, ratings, similar, recs = fut.result() if fut is not None else seerr_bundle(kind, tmdb_id)
            if isinstance(body, dict):
                raw, t = body, md.title_from(body, kind, tmdb_id)
    finally:
        side.shutdown(wait=False)  # a mispredicted early read just finishes into the cache
    f["kind"] = kind
    jf_item_id = item["id"] if item else (row["jf_id"] if row else None)
    f["t"], f["connected"] = t, connected
    if tmdb_id and not item and not t:
        f["note"] = "Title unavailable" if connected else "Not connected"

    # --- 3. what is on the server ---
    files = (base or {}).get("files")
    if files is None and t and t["status_word"] in md.ON_DISK and not item:
        files = media_files.file_summary(kind, tmdb_id)
    on_server = bool(item or row or jf_id and not f["jf_failed"] or (t and t["status_word"] in md.ON_DISK))
    f.update(on_server=on_server, files=files, status_word=(t or {}).get("status_word"))
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
    # media-ux3: `?season=N` (the banner's "This season") opens that season; else the page's episode / season
    page_season = (open_season if open_season is not None
                   else page_item["season_no"] if page_item and page_item["kind"] in ("episode", "season") else None)
    f["seasons"] = episode_list(seasons, href_of if (jf_item_id or jf_id) else None, page_season, f["next_ep"])
    f["part_of"] = part_of(page_item, item, f["seasons"])
    if ep:
        ep = listed_episode(ep, seasons)  # media-ux4: one watch state per page (hero = banner = rows)
        f["episode"] = {"code": ep["code"], "title": ep["title"], "air_date": ep["air_date"],
                        "overview": ep["overview"], "runtime": ep["runtime"],
                        "play": {"href": href_of(ep["id"]),
                                 "label": ("Resume ▶" + (f" · {ep['left_text']}" if ep["left_text"] else "")) if ep["in_progress"]
                                 else "Play again ▶" if ep["played"] else "Play ▶"},
                        "show_href": f"/media/item/{item['id']}" if item and item["kind"] == "series" else None}
        f["episode_season"] = ep["season_no"]
    else:
        f["episode"] = None
    # Move on (2026-10-08): Mark watched / Reset progress beside "Resume ▶". The page's watch state is read as
    # JELLYFIN_USER, so the buttons show in B.'s views only (Georgina moves on from her Continue watching shelf).
    resume_id = (ep["id"] if ep and ep["in_progress"] else
                 (jf_item_id or jf_id) if kind == "movie" and in_progress and not ep else None)
    f["resume_acts"] = ({"jf_id": resume_id, "owner": owner, "reset": True}
                        if resume_id and owner == "you" and media_item.ITEM_RE.match(str(resume_id)) else None)
    # Watched / unwatched (media-ux3): the season headers, each episode row and the film / episode page toggle. Same
    # B.'s-views-only rule as above (the page reads watch state as JELLYFIN_USER). A page already offering the
    # Move-on pair (in progress) gets no second "Mark watched".
    f["watch_owner"] = owner if owner == "you" and item and not f["jf_failed"] else None
    f["show_id"] = item["id"] if item and item["kind"] == "series" else None
    toggle_id = ep["id"] if ep else (jf_item_id if kind == "movie" and item else None)
    f["watch_toggle"] = ({"jf_id": toggle_id, "played": bool(ep["played"] if ep else played),
                          "season": ep["season_no"] if ep else None}
                         if f["watch_owner"] and toggle_id and not f["resume_acts"]
                         and media_item.ITEM_RE.match(str(toggle_id)) else None)

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
    badge = md._dl_badge(title, snaps) if title and not f["jf_failed"] else None
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
    # media-ux4: every score is a pill in one format — IMDb 8.0 · RT 90% · Metacritic 74 · TMDB 8.1 · Yours 8
    community = score_text(item["community_rating"] if item and item.get("community_rating") else (t or {}).get("vote"))
    mc = media_omdb.metascore(imdb_id(raw, item)) if kind in ("movie", "tv") else None   # Metacritic via OMDb (item 2)
    f["numbers"] = {"tmdb": community, "imdb": ratings.get("imdb"), "rt": ratings.get("rt"), "mc": mc, "mc_band": mc_band(mc),
                    "runtime": runtime_text(runtime_min) if runtime_min else None, "ends": ends}
    f["logos"] = logos()
    added = md._date_words(item.get("added"))[0] if item and item.get("added") else None
    f["file"] = file_panel(files, kind, added)
    f["facts"] = {"runtime": runtime_text(runtime_min) if runtime_min else None,
                  "languages": _languages(files), "added": added,
                  "releases": _releases(raw, arr, tmdb_id) if kind == "movie" else [],
                  "seasons": (f"{t['n_seasons']} season{'s' if t['n_seasons'] != 1 else ''}"
                              + (f" · {t['n_episodes']} episodes" if t.get("n_episodes") else "")) if kind == "tv" and t and t.get("n_seasons") else None}
    people = (item or {}).get("people") or []
    f["cast"], f["makers"] = _cast(raw, people), _makers(raw, people, kind or "movie")
    f["crew"], f["cast_h"] = crew_for(raw, kind or "movie"), CAST_H
    f["makers_label"] = "Creators" if kind == "tv" else "Director"
    f["providers"] = _providers(raw, title)
    f["trailer"] = _trailer((item or {}).get("trailer"), raw)
    lib_keys = on_server_keys(jelly, "movie") | on_server_keys(jelly, "tv")
    f["shelves"] = _shelves(raw, kind, lib_keys, similar, recs) if raw and kind and tmdb_id else []
    f["collection"] = collection_banner(raw, kind, lib_keys, tmdb_id) if raw and kind and tmdb_id else None
    f["wl_on"] = bool(keys_for(request, [f"tmdb:{tmdb_id}"])) if tmdb_id else False
    f["follow_flash"] = media_follow.flash_text(request)
    if f["collection"]:
        try:  # Follow (2026-10-07): the series' Follow button state; the page never fails on it
            f["collection"]["following"] = media_follow.get("collection", f["collection"]["collection_id"]) is not None
        except Exception as exc:
            log.warning("follow lookup failed: %s", type(exc).__name__)
            f["collection"]["following"] = False
    f["show_request"] = bool(t and t["code"] != 5 and not (kind == "movie" and on_server))
    f["status_line"] = status_line(f)
    if kind and (jf_id or on_server):  # an off-server title keeps the Discover section it was found in
        request.state.media_section = "movies" if kind == "movie" else "tv"
    return f


# ---- routes ----

def _render(request: Request, hub, src, film: dict, view, from_query, snaps=None):
    resp = hub.templates.TemplateResponse(request, "media_film.html", {
        "areas": hub.registry.visible_areas, "active_id": None, "owner_view": view,
        "status": hub.build_status(hub.get_snapshots() if snaps is None else snaps), "src": src, "film": film})
    return hub._maybe_set_cookie(resp, view, from_query)


@router.get("/media/title/{kind}/{tmdb_id}", response_class=HTMLResponse)
def title_page(request: Request, kind: str, tmdb_id: int, step: str = "", requested: str = "", error: str = ""):
    from hub import main as hub  # late: hub.main includes this router

    kind = md._kind(kind)
    view, from_query = hub.resolve_owner_view(request)
    snaps = request.state.snaps = hub.get_snapshots()  # media-speed: one snapshot read per request, shared
    src = hub.find_detail_source(hub.JELLYSEERR_SNAPSHOT_ID, snaps, detail=md.DISCOVER_DETAIL)
    if src is None:
        return hub.templates.TemplateResponse(request, "404.html", {
            "areas": hub.registry.visible_areas, "active_id": None, "owner_view": view,
            "missing_text": "No page here"}, status_code=404)
    state, msg = (("done", None) if requested == "1" else ("error", md.ERRORS[error]) if error in md.ERRORS
                  else ("confirm" if step == "confirm" else "idle", None))
    film = build_film(kind, tmdb_id, view=view, request=request, hub=hub, req_state=state, req_msg=msg, snaps=snaps)
    return _render(request, hub, src, film, view, from_query, snaps)


@router.get("/media/item/{jf_id}", response_class=HTMLResponse)
def item_page(request: Request, jf_id: str, season: str = ""):
    from hub import main as hub

    if not media_item.ITEM_RE.match(jf_id):
        raise HTTPException(404, "No such item")
    view, from_query = hub.resolve_owner_view(request)
    snaps = request.state.snaps = hub.get_snapshots()  # media-speed: one snapshot read per request, shared
    src = hub.find_detail_source(hub.JELLYFIN_SNAPSHOT_ID, snaps)
    if src is None:
        raise HTTPException(404, "No such item")
    open_season = int(season) if season.isdigit() and len(season) <= 3 else None  # media-ux3: "This season"
    film = build_film(jf_id=jf_id, view=view, request=request, hub=hub, snaps=snaps, open_season=open_season)
    return _render(request, hub, src, film, view, from_query, snaps)
