"""The film page (F10, 2026-10-06): ONE Cinema-layout page for every title, whether it is on the server or
not. Merges Jellyfin item data (hub/media_item.py) with Jellyseerr title data (hub/media_discover.py) into
one `film` dict, rendered by media_film.html. Both URL families resolve here:
/media/title/{kind}/{tmdb_id} and /media/item/{jf_id}.

Live reads (Jellyfin and Jellyseerr, server-side only) are cached 10 min per path and every upstream failure
degrades to a missing section, never a 500. F2 fast pages (2026-10-12): the page renders from Jellyfin + whatever
Jellyseerr / OMDb answers are already cached; the sections still waiting on an upstream read are placeholders that
ONE htmx request fills (`.../part/all`, out-of-band swaps) while the read runs in the background. Logs carry exception TYPES only; the page carries no URL or key
except the Play deep link and the "Open in Seerr" link (as the old title page did).
"""

from __future__ import annotations

import logging
import re
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import timedelta
from functools import lru_cache
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from starlette.background import BackgroundTask

from hub import media_arr_search, media_awards_badges, media_db, media_discover as md, media_downloads, media_files, media_follow, media_item, media_omdb, media_plays_db, media_rank
from hub import media_episode_ratings, media_season_state as mss
from hub import guest, media_home, media_quality, media_text, media_upgrades, shell
from hub import media_watch   # JY-054: Play opens Joey's own player when PLAYER_API is on
from hub.ids import ARR_SNAPSHOT_ID, JELLYFIN_SNAPSHOT_ID, JELLYSEERR_SNAPSHOT_ID
from hub.media_library import empty_series, runtime_text
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
MAKERS_MAX = 4      # media-ux4: "Directed by" / "Created by" cards in the hero
MAKER_H = 240       # /img size of a maker headshot (a 52 px circle; 2:3 portrait cropped to the face)
REGION = "AU"
JUSTWATCH = "https://www.justwatch.com/au/search?q="
RELEASE_TYPES = {3: "Cinema", 4: "Digital", 5: "Disc"}
ARR_LABELS = {"Cinemas": "Cinema", "Digital": "Digital", "Disc": "Disc"}
PROVIDER_GROUPS = (("Stream", "flatrate"), ("Rent", "rent"), ("Buy", "buy"))


# ---- cached Jellyseerr reads (shares media_discover's cache, so its clear_cache() clears these too) ----

def _cget(path: str):
    hit = md._cache.get(f"film:{path}")
    if hit and time.time() - hit[0] < md.CACHE_TTL:
        return hit[1]
    return media_item.once(("seerr", path), lambda: _cread(path))   # F2: concurrent askers share one read


def _cread(path: str):
    key = f"film:{path}"
    hit = md._cache.get(key)
    if hit and time.time() - hit[0] < md.CACHE_TTL:
        return hit[1]
    body, code = md._fetch(path)
    if body is None and code != 404:
        return None  # a failed fetch is not cached; a 404 is an answer (nothing there) and is (media-speed)
    md._cache[key] = (time.time(), body)
    return body


def _cpeek(path: str):
    """_cget's answer from the cache only - MISSING when it would need a call (F2)."""
    hit = md._cache.get(f"film:{path}")
    return hit[1] if hit and time.time() - hit[0] < md.CACHE_TTL else MISSING


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


# ---- deferred parts (F2 fast item pages, 2026-10-12) ----
# The page renders at once from Jellyfin + the caches. A section whose upstream answer is not cached yet is a placeholder
# (`film.pending`); its read runs in the background (one job per title, `warm_extras`) and the page's ONE htmx request
# (`/part/all`) waits for it and swaps every placeholder out of band. A cached title renders whole, as before.

MISSING = md.MISSING
PARTS = ("makers", "actions", "scores", "collection", "crew", "dates", "cast", "providers", "shelves")
RAW_PARTS = ("makers", "actions", "crew", "dates", "cast", "providers")   # drawn from the Jellyseerr title body
EXTRAS_WAIT = 30          # s a part request waits for the background read (each upstream call has its own timeout)
_extras_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="film-extras")   # bounded: a NAS (M-46)
# E1 (2026-10-13): link prefetches (X-Joey-Prefetch) read in their own 1-worker lane, so a real tap's read never queues
# behind speculation. At most one prefetch waits in that lane (a later one is skipped), and a tap on a title whose
# prefetch is still waiting takes it over in the page lane.
_prefetch_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="film-prefetch")
_prefetch_waiting = [0]   # prefetch jobs submitted and not yet started
_extras: dict[tuple, Future] = {}
_extras_lock = threading.RLock()   # re-entrant: cancelling a queued prefetch runs its _forget callback under the lock


def _ratings_peek(kind: str, tmdb: int):
    if kind == "tv":
        body = md.meta_peek(f"/api/v1/tv/{tmdb}/ratings")
        return MISSING if body is MISSING else parse_ratings(body)
    combined = md.meta_peek(f"/api/v1/{kind}/{tmdb}/ratingscombined")
    if combined is MISSING:
        return MISSING
    if parse_ratings(combined):
        return parse_ratings(combined)
    flat = md.meta_peek(f"/api/v1/{kind}/{tmdb}/ratings")
    return MISSING if flat is MISSING else parse_ratings(flat)


def _mc_peek(imdb):
    """The Metascore from the OMDb cache only: None when there is nothing to look up, MISSING when it needs a call."""
    if not media_omdb._key() or not media_omdb.IMDB_RE.match(str(imdb or "").strip()):
        return None
    found, score = media_omdb._cached(str(imdb).strip())
    return score if found else MISSING


def peek_extras(kind: str, tmdb: int, imdb_hint=None, raw=MISSING) -> dict:
    """Everything the upstream sections need, from the caches alone - no call. MISSING marks what is not cached.
    `raw` overrides the title body (a page that has just read it)."""
    if md._creds() is None:
        out = {"raw": None, "ratings": {}, "similar": None, "recs": None, "collection": None}
    else:
        out = {"raw": _cpeek(f"/api/v1/{kind}/{tmdb}") if raw is MISSING else raw,
               "ratings": _ratings_peek(kind, tmdb), "similar": _cpeek(f"/api/v1/{kind}/{tmdb}/similar"),
               "recs": _cpeek(f"/api/v1/{kind}/{tmdb}/recommendations")}
        col = _collection_id(out["raw"]) if out["raw"] is not MISSING else None
        out["collection"] = (MISSING if out["raw"] is MISSING else
                             _cpeek(f"/api/v1/collection/{col}") if col is not None else None)
    body = out["raw"] if isinstance(out["raw"], dict) else {}
    out["mc"] = (MISSING if out["raw"] is MISSING and not imdb_hint
                 else _mc_peek(imdb_id(body, {"imdb": imdb_hint})))
    return out


def _complete(ex: dict) -> bool:
    return all(v is not MISSING for v in ex.values())


def _load_extras(kind: str, tmdb: int, imdb_hint) -> dict:
    """The background read: the Jellyseerr bundle (title body, ratings, shelves, collection), then OMDb."""
    if md._creds() is not None:
        body, ratings, similar, recs = seerr_bundle(kind, tmdb)
        col = _collection_id(body)
        collection = _cget(f"/api/v1/collection/{col}") if col is not None else None
    else:
        body, ratings, similar, recs, collection = None, {}, None, None, None
    mc = media_omdb.metascore(imdb_id(body if isinstance(body, dict) else {}, {"imdb": imdb_hint}))
    return {"raw": body, "ratings": ratings, "similar": similar, "recs": recs, "collection": collection, "mc": mc}


def _forget(key, fut) -> None:
    with _extras_lock:
        if _extras.get(key) is fut:
            _extras.pop(key, None)


def _prefetch_job(kind: str, tmdb: int, imdb_hint) -> dict:
    with _extras_lock:
        _prefetch_waiting[0] -= 1
    return _load_extras(kind, tmdb, imdb_hint)


def warm_extras(kind: str, tmdb: int, imdb_hint=None, *, prefetch: bool = False) -> Future | None:
    """Start (or join) the title's background read - one job per title at a time; a done job is dropped, the
    caches hold its answers. `prefetch` (E1): the prefetch lane - None when a prefetch is already waiting there."""
    key = (kind, tmdb)
    with _extras_lock:
        fut = _extras.get(key)
        if fut is not None and not prefetch and getattr(fut, "joey_prefetch", False) and fut.cancel():
            _prefetch_waiting[0] -= 1   # its prefetch had not started: the tap's read runs in the page lane now
            fut = None
        fresh = fut is None
        if fresh and prefetch:
            if _prefetch_waiting[0] >= 1:
                return None
            _prefetch_waiting[0] += 1
            fut = _extras[key] = _prefetch_pool.submit(_prefetch_job, kind, tmdb, imdb_hint)
            fut.joey_prefetch = True
        elif fresh:
            fut = _extras[key] = _extras_pool.submit(_load_extras, kind, tmdb, imdb_hint)
    if fresh:
        fut.add_done_callback(lambda f, k=key: _forget(k, f))   # outside the lock: a done future calls back at once
    return fut


def drain_extras(timeout: float = EXTRAS_WAIT) -> None:
    """Wait for every background read in flight (tests: one test's read never lands in the next one's fakes)."""
    with _extras_lock:
        futs = list(_extras.values())
    for fut in futs:
        try:
            fut.result(timeout=timeout)
        except Exception:
            pass


def settle(ex: dict) -> dict:
    """MISSING -> each part's 'nothing there' value, so a section can be drawn from what is known."""
    blank = {"raw": None, "ratings": {}, "similar": None, "recs": None, "collection": None, "mc": None}
    return {k: blank[k] if v is MISSING else v for k, v in ex.items()}


def extras_for(kind: str, tmdb: int, imdb_hint=None, *, wait: bool, prefetch: bool = False) -> dict:
    """The title's upstream extras: from the caches when complete; else the background read is started and either
    awaited (`wait`: a part request, a script) or not (the page renders what `peek_extras` found)."""
    ex = peek_extras(kind, tmdb, imdb_hint)
    if _complete(ex):
        return ex
    fut = warm_extras(kind, tmdb, imdb_hint, prefetch=prefetch and not wait)
    if not wait:
        return ex
    try:
        got = fut.result(timeout=EXTRAS_WAIT)
    except Exception as exc:  # type only
        log.warning("film extras read failed: %s", type(exc).__name__)
        return settle(ex)
    if got.get("mc") is None and imdb_hint:   # a job started before the Jellyfin item named its IMDb id
        got = {**got, "mc": media_omdb.metascore(imdb_id(got["raw"] if isinstance(got.get("raw"), dict) else {},
                                                          {"imdb": imdb_hint}))}
    return got


def pending_parts(ex: dict | None, kind: str | None) -> set:
    """The parts a page draws as placeholders: each one whose upstream answer is not cached."""
    if not ex:
        return set()
    out = set(RAW_PARTS) if ex["raw"] is MISSING else set()
    if ex["ratings"] is MISSING or ex["mc"] is MISSING:
        out.add("scores")
    if kind == "movie" and ex["collection"] is MISSING:
        out.add("collection")
    # the shelves are drawn only with the title body too (_sections): similar / recommendations answered before the body
    # must not draw them empty for good (JY-006, 2026-10-23: a CI race lost the Similar shelf)
    if ex["similar"] is MISSING or ex["recs"] is MISSING or ex["raw"] is MISSING:
        out.add("shelves")
    return out


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
            "left_text": (f"{left}m left" if left else ep.get("left_text")) if prog else None}


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
    """An image dropped in hub/static/badges for this badge / logo id, else None. Cached (M-09): the folder only
    changes on deploy, and a film page asks for ~14 ids."""
    return _override_in(BADGES_DIR, badge_id)


@lru_cache(maxsize=256)
def _override_in(folder: Path, badge_id) -> str | None:
    for ext in ("svg", "png"):
        if badge_id and (folder / f"{badge_id}.{ext}").is_file():
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


def crew_for(raw: dict, kind: str, people: list[dict] | None = None, jf_crew: bool = False) -> list[dict]:
    """[{role, people: [{name, id}]}] — Director, Writer (screenplay / writer / story / novel, de-duplicated),
    Cinematography, Composer, Editor from TMDB credits.crew; a show leads with Created by. Empty roles drop out.
    A show's TMDB crew is show-level (directors are credited per episode), so for TV the Director and Writer rows
    come from Jellyfin's `people` (the episode's on an episode page) first, TMDB crew after (2026-10-10). `jf_crew`: a
    film's too - its placeholder while the TMDB crew is a pending part (F2)."""
    crew = [c for c in ((raw.get("credits") or {}).get("crew") or []) if isinstance(c, dict) and c.get("name")]
    jf = {"Director": "Director", "Writer": "Writer"} if kind == "tv" or jf_crew else {}
    roles = []
    if kind == "tv":
        roles.append(("Created by", [c for c in raw.get("createdBy") or [] if isinstance(c, dict) and c.get("name")]))
    for role, jobs in CREW_ROLES:
        found = [{"name": p["name"]} for p in people or [] if role in jf and p.get("type") == jf[role] and p.get("name")]
        roles.append((role, found or [c for c in crew if c.get("job") in jobs]))
    out = []
    for role, found in roles:
        people: dict[str, dict] = {}
        for c in found:
            name = str(c["name"])[:80]
            people.setdefault(name, {"name": name, "id": _pid(c.get("id"))})
        if people:
            out.append({"role": role, "people": list(people.values())[:CREW_NAMES]})
    return out


def show_crew(item: dict | None, seasons: list[dict]) -> list[dict]:
    """A show page's Director / Writer people: the series' own Jellyfin People when it has any, else everyone who
    directed or wrote an episode on the server, most episodes first (2026-10-10 — Jellyfin credits them per episode)."""
    own = [p for p in (item or {}).get("people") or [] if p.get("type") in ("Director", "Writer")]
    if own:
        return own
    counts: dict[tuple, int] = {}
    for s in seasons or []:
        for e in s.get("episodes") or []:
            for c in e.get("crew") or []:
                counts[(c["name"], c["type"])] = counts.get((c["name"], c["type"]), 0) + 1
    return [{"name": n, "type": t} for (n, t), _ in sorted(counts.items(), key=lambda kv: -kv[1])]


def show_directors(item: dict | None, seasons: list[dict]) -> list[dict]:
    """The show page's "Directed by" headshot cards (2026-10-11), the TV twin of a film's: the series' own Director
    People first when Jellyfin lists any, then whoever directed the most episodes on the server, up to MAKERS_MAX.
    Cards carry the Jellyfin headshot (`jf:<person id>`) when one exists; there is no TMDB person id, so the card
    links to a Discover search like a film's maker card does without one."""
    counts: dict[str, int] = {}
    refs: dict[str, str | None] = {}
    for p in (item or {}).get("people") or []:
        if p.get("type") == "Director" and p.get("name"):
            counts[p["name"]] = counts.get(p["name"], 0) + 10_000    # the series' own credit outranks any count
            refs[p["name"]] = refs.get(p["name"]) or p.get("ref")
    for s in seasons or []:
        for e in s.get("episodes") or []:
            for c in e.get("crew") or []:
                if c.get("type") == "Director" and c.get("name"):
                    counts[c["name"]] = counts.get(c["name"], 0) + 1
                    refs[c["name"]] = refs.get(c["name"]) or c.get("ref")
    ranked = sorted(counts.items(), key=lambda kv: -kv[1])          # stable: ties keep first-seen order
    return [{"name": n, "id": None, "ref": refs.get(n)} for n, _ in ranked][:MAKERS_MAX]


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
    """The words-first line: what we know about this title, in one sentence of ' · ' pieces. A show (WP-T1,
    2026-10-19) also says what Sonarr still expects ("3 of 8 episodes · all watched · 5 to come · next airs 2 Nov"),
    and one with no episode on the server reads "Requested · waiting for the first episode · airs 5 Dec"."""
    if f["jf_failed"]:
        return media_item.DOWN_TEXT
    son = f.get("sonarr")
    if not f["on_server"] and f["kind"] == "tv" and (f.get("empty_show") or mss.waiting(son)):
        word = (son or {}).get("word") or ""
        parts = [f"Requested {f['requested_when']}" if f.get("requested_when") else "Requested",
                 mss.waiting_words(son) if not word or word.startswith("Waiting") else word]
        if f.get("downloading_pct") is not None:
            parts.append(media_downloads.badge_text({"pct": f["downloading_pct"]}))
        return " · ".join(parts)
    if not f["on_server"]:
        parts = ["Not on server"]
        if f.get("requested_when"):
            parts.append(f"Requested {f['requested_when']}")
        if f.get("status_word") in ("Processing", "Partly available") or (f.get("status_word") == "Requested" and not f.get("requested_when")):
            parts.append(f["status_word"])
        if f.get("downloading_pct") is not None:
            parts.append(media_downloads.badge_text({"pct": f["downloading_pct"]}))
        return " · ".join(parts)
    parts = ["On server"]
    if f["kind"] == "tv":
        s = f.get("series")
        if s:
            parts.append(mss.episodes_words(son, f"{s['episodes']} episode{'s' if s['episodes'] != 1 else ''}"))
            parts.append(s.get("progress") or (f"{s['to_watch']} left" if s["to_watch"] else "all watched"))
            if f.get("next_ep"):
                parts.append(f"{f['next_ep']['label']} next")
        if son and son.get("word") and not mss.waiting(son):   # WP-T1: never "all watched" last while more is due
            parts.append(son["word"])
    else:
        res = next((b["word"] for b in (f.get("files") or {}).get("video", []) if b["icon"] == "res"), None)
        hdr = next((b["word"] for b in (f.get("files") or {}).get("video", []) if b["icon"] == "hdr"), None)
        parts += [p for p in (res, hdr) if p]
        if f.get("played") or f.get("watch_count"):
            parts.append(f"watched {f['last_watched']}" if f.get("last_watched") else "watched")
        else:
            parts.append("in progress" if f.get("in_progress") else "not watched yet")
    if f.get("downloading_pct") is not None:
        parts.append(media_downloads.badge_text({"pct": f["downloading_pct"]}))   # 'Downloading · 43%' (M-27)
    if f.get("score"):
        parts.append(f"you rated {f['score']}")
    return " · ".join(parts)


# ---- the merge ----

def _jf_from_snapshot(jelly: dict, kind: str, tmdb: int) -> dict | None:
    for r in jelly.get("movies" if kind == "movie" else "shows") or []:
        if isinstance(r, dict) and r.get("item_key") == f"tmdb:{tmdb}" and media_item.ITEM_RE.match(str(r.get("jf_id") or "")) \
                and not empty_series(r):   # WP-T1: a show with no episode is not a library entry
            return r
    return None


def _upgrade(snaps, jelly: dict, kind, tmdb, tvdb, title) -> str | None:
    """F4b: "Below cutoff · …" (WP-U1) for the hero, from the arr snapshot's cutoff-unmet lists - no call. A show matches
    its TheTVDB id, else its title when the library holds that title once."""
    if kind not in ("movie", "tv"):
        return None
    name = media_upgrades.norm_title(title)
    once = kind == "tv" and sum(1 for r in jelly.get("shows") or [] if isinstance(r, dict)
                                and media_upgrades.norm_title(r.get("title")) == name) <= 1
    row = media_upgrades.find(media_upgrades.index(snaps), kind, f"tmdb:{tmdb}" if tmdb else None, tvdb,
                              title if once else None)
    return row["note"] if row else None


def _requested(snaps, tmdb) -> dict | None:
    from hub.media_requests import snapshot_rows  # a removed request stops showing at once (2026-10-08)
    for r in snapshot_rows(snaps, JELLYSEERR_SNAPSHOT_ID):
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


YT_KEY_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
YT_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtube-nocookie.com", "www.youtube-nocookie.com"}


def youtube_key(url) -> str | None:
    """The 11-character YouTube video id in a watch / youtu.be / embed / shorts URL, else None."""
    try:
        parts = urlsplit(str(url or ""))
    except ValueError:
        return None
    host, path = (parts.hostname or "").lower(), parts.path
    if host == "youtu.be":
        key = path.strip("/").split("/")[0]
    elif host in YT_HOSTS:
        key = (parse_qs(parts.query).get("v") or [""])[0] if path == "/watch" else \
            path.split("/")[2] if path.startswith(("/embed/", "/shorts/")) and path.count("/") >= 2 else ""
    else:
        return None
    return key if YT_KEY_RE.match(key or "") else None


def _trailer(jf_url, raw: dict) -> tuple[str | None, str | None]:
    """(link, YouTube key) for the Trailer button. Candidates: Jellyfin's RemoteTrailers URL, then Jellyseerr's TMDB
    `relatedVideos` (YouTube trailers; their `key` field, else the key in the URL). The first one with a YouTube key wins
    — the in-page player (media-ux4) needs it, and the link (the no-JS fallback) is that same video; none has a key: the
    first link, played on YouTube itself."""
    cands = [(jf_url, youtube_key(jf_url))] if jf_url else []
    for v in raw.get("relatedVideos") or []:
        url = str(v.get("url") or "") if isinstance(v, dict) else ""
        if v.get("site") == "YouTube" and v.get("type") == "Trailer" and url.startswith("https://"):
            key = str(v.get("key") or "")
            cands.append((url, key if YT_KEY_RE.match(key) else youtube_key(url)))
    keyed = next((c for c in cands if c[1]), None)
    return keyed or (cands[0] if cands else (None, None))


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
    for c in found:   # media-ux4: the headshot (TMDB profile through /img) rides along for the "Directed by" cards
        if c.get("name"):
            out.setdefault(str(c["name"])[:80], {"name": str(c["name"])[:80], "id": _pid(c.get("id")),
                                                 "ref": md._ref(c.get("profilePath"))})
    if not out:
        out = {p["name"]: {"name": p["name"], "id": None, "ref": p.get("ref")} for p in people if p["type"] == "Director"}
    return list(out.values())[:MAKERS_MAX]


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


def _shelves(kind: str, lib_keys: set, similar, recs) -> list[dict]:
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
            (season or {}).get("watched_text"), (season or {}).get("state_word")]   # WP-T1: "5 to come · next airs 2 Nov"
    show = f"/media/item/{item['id']}"
    return {"title": item["title"], "line": [x for x in line if x], "poster": item["poster"],
            "backdrop": item["backdrop"] if item.get("has_backdrop") else None,
            "season_href": f"{show}?season={n}#season-{n}" if page["kind"] == "episode" and n is not None else None,
            "all_href": f"{show}#seasons"}


# ---- TV episode flow: nav, guests, crew_ep (WP-E3, 2026-10-16; EPISODES_CONTRACT section 2) ----
# Season and episode pages only (on-server Jellyfin items). Everything comes from the page's own item read and the
# show's cached season list (media_item._seasons, which carries each episode's People) - no extra Jellyfin call.
# Jellyfin's People entries carry no ProviderIds (Name, Id, Role, Type, PrimaryImageTag only), so a guest's or a
# crew member's `href` (/media/person/{tmdb}) is None: there is no TMDB person id without a per-person read.

CREW_EP = (("Director", "Directed by"), ("Writer", "Written by"))


def _item_href(jf_id) -> str | None:
    return f"/media/item/{jf_id}" if jf_id and media_item.ITEM_RE.match(str(jf_id)) else None


def _page_season(page: dict, seasons: list[dict]) -> dict | None:
    """The episode_list season a season / episode page belongs to: by the season's id, or the season listing the
    episode's id, else by season number."""
    if page["kind"] == "season":
        hit = next((s for s in seasons if s.get("id") == page["id"]), None)
    else:
        hit = next((s for s in seasons if any(e.get("jf_id") == page["id"] for e in s.get("episodes") or [])), None)
    if hit is None and page.get("season_no") is not None:
        hit = next((s for s in seasons if s.get("n") == page["season_no"]), None)
    return hit


def episode_nav(page: dict, show: dict | None, seasons: list[dict]) -> dict:
    """`nav`: the show link, the S1 / S2 switch (`on` = the page's season); on an episode also its season (n, link,
    episodes listed), Previous / Next within the season in list order and "E6 of 10". Episode-only keys are None on
    a season page."""
    season = _page_season(page, seasons)
    nav = {"show": {"title": (show or {}).get("title") or page.get("show_title") or "Show",
                    "href": _item_href(page.get("show_id"))},
           "seasons": [{"n": s["n"], "href": _item_href(s.get("id")), "on": s is season} for s in seasons],
           "season": None, "prev": None, "next": None, "position": None}
    if page["kind"] != "episode" or season is None:
        return nav
    eps = season.get("episodes") or []
    i = next((k for k, e in enumerate(eps) if e.get("jf_id") == page["id"]), None)
    if i is None and page.get("episode_no") is not None:
        i = next((k for k, e in enumerate(eps) if e.get("number") == page["episode_no"]), None)
    nav["season"] = {"n": season["n"], "href": _item_href(season.get("id")), "total": len(eps)}

    def card(e):
        return {"number": e["number"], "name": e["name"], "href": _item_href(e.get("jf_id"))}
    if i is not None:
        nav["prev"] = card(eps[i - 1]) if i > 0 else None
        nav["next"] = card(eps[i + 1]) if i + 1 < len(eps) else None
    number = eps[i]["number"] if i is not None else page.get("episode_no")
    nav["position"] = f"E{number} of {len(eps)}" if number is not None else None
    return nav


def episode_guests(ep: dict, cast: list[dict] | None, show_people: list[dict] | None, season: dict | None) -> list[dict]:
    """`guests`: the episode's GuestStar People not in the show's main cast (the page's `cast`, plus the series'
    Actor People), each with how many of the season's episodes list them (any Type; at least this one)."""
    main = {c.get("name") for c in cast or []} | {p.get("name") for p in show_people or [] if p.get("type") == "Actor"}
    listed = [set(e.get("people_names") or ()) for e in (season or {}).get("episodes") or []]
    out: dict[str, dict] = {}
    for p in ep.get("people") or []:
        name = p.get("name")
        if p.get("type") == "GuestStar" and name and name not in main and name not in out:
            out[name] = {"name": name, "role": p.get("role") or None, "poster": p.get("ref"), "href": None,
                         "eps_this_season": max(1, sum(1 for names in listed if name in names))}
    return list(out.values())


def episode_crew(ep: dict) -> list[dict]:
    """`crew_ep`: the episode's own Director / Writer People as "Directed by" / "Written by" rows, de-duplicated."""
    out = []
    for typ, role in CREW_EP:
        names = list(dict.fromkeys(p["name"] for p in ep.get("people") or [] if p.get("type") == typ and p.get("name")))
        if names:
            out.append({"role": role, "people": [{"name": n, "href": None} for n in names]})
    return out


def offserver_seasons(listing: list[dict]) -> list[dict]:
    """The season shapes `build_ratings` takes for a show Jellyfin does not have: Jellyseerr's season list (`t["seasons"]`),
    Specials left out, no episodes and so no watch state. The per-season rows come from the stored / cached ratings."""
    return [{"n": s["number"], "number": s["number"], "episodes": []} for s in listing
            if isinstance(s.get("number"), int) and s["number"] >= 1][:media_episode_ratings.SEASONS_MAX]


def episode_flow(page: dict | None, ep: dict | None, item: dict | None, seasons: list[dict], cast) -> dict:
    """{nav} for a season page, {nav, guests, crew_ep} for an episode page; {} otherwise (a film, a show page, an
    off-server title) - the keys are then absent from the page's dict. `ep` is the page's episode as listed_episode
    gave it, `item` the base item (the show when its read answered)."""
    if not page or page.get("kind") not in ("season", "episode"):
        return {}
    show = item if item and item.get("kind") == "series" else None
    here = ep if page["kind"] == "episode" and ep else page
    out = {"nav": episode_nav(here, show, seasons)}
    if page["kind"] == "episode":
        out["guests"] = episode_guests(here, cast, (show or {}).get("people"), _page_season(here, seasons))
        out["crew_ep"] = episode_crew(here)
    return out

def _tv_chip(e: dict, nxt_id, this_id) -> str | None:
    """The word on a TV episode still (JY-192): this page's episode, then watched / next / in progress / not aired."""
    if this_id and e.get("jf_id") == this_id:
        return "This one"
    if e.get("played"):
        return "Watched"
    if nxt_id and e.get("jf_id") == nxt_id:
        return "Next"
    if e.get("in_progress"):
        return "In progress"
    return None if e.get("aired") else "Not aired"


def tv_shelves(seasons: list[dict], page_season=None, this_id=None, next_ep: dict | None = None) -> dict:
    """JY-192 (U6, 2026-10-25): the TV title page's Seasons and Episodes shelves, from the page's season list
    (`episode_list` output: on the media front it was read as the signed-in viewer, so every word here is theirs) -
    no read of its own. `page_season` = the season / episode page's season number (else the open season: the next
    episode's, else the last); `this_id` = an episode page's own episode. Specials (number 0) keep Jellyfin's name."""
    with_eps = [s for s in seasons or [] if s.get("episodes")]
    cur = next((s for s in with_eps if s["n"] == page_season), None) if page_season is not None else None
    cur = cur or next((s for s in with_eps if s.get("open")), None) or (with_eps[-1] if with_eps else None)
    cards = []
    for s in with_eps:
        aired = [e for e in s["episodes"] if e.get("aired")]
        done = sum(1 for e in aired if e.get("played"))
        cards.append({"n": s["n"], "title": s.get("name") or f"Season {s['n']}", "href": _item_href(s.get("id")),
                      "poster": f"jf:{s['id']}" if _item_href(s.get("id")) else None,
                      "sub": s.get("watched_text"), "pct": round(100 * done / len(aired)) if aired else None,
                      "here": page_season is not None and s is cur})
    eps = None
    if cur is not None:
        nxt_id = (next_ep or {}).get("jf_id")
        rows = []
        for e in cur["episodes"]:
            run, left = e.get("runtime_min"), e.get("left_min")
            pct = (max(1, min(99, round(100 * (run - left) / run))) if e.get("in_progress") and run and left is not None
                   else None)
            play = e.get("play") or {}
            rows.append({"title": f"E{e['number']} · {e['name']}", "still": e.get("still"),
                         "href": play.get("href") or _item_href(e.get("jf_id")),
                         "jf_id": e["jf_id"] if play.get("href") else None,
                         "sub": " · ".join(x for x in (e.get("runtime"), f"{left}m left" if pct is not None and left else None) if x),
                         "chip": _tv_chip(e, nxt_id, this_id), "pct": pct})
        eps = {"label": cur.get("name") or f"Season {cur['n']}", "rows": rows}
    return {"seasons": cards, "eps": eps}


def _jellyfin_side(kind, tmdb_id, jf_id, jelly: dict, read, on_tmdb=None) -> dict:
    """The Jellyfin side: base (film / series), plus the episode when the page is for one. `read` is media_item._data
    (the page) or media_item.peek (a part request: never a second Jellyfin read, F2)."""
    out = {"base": None, "ep": None, "row": None, "page_item": None, "jf_failed": False}
    if jf_id:
        got = read(jf_id)
        if got is None:
            out["jf_failed"] = True
        else:
            it = out["page_item"] = got["item"]
            out["ep"] = it if it["kind"] == "episode" else None
            if on_tmdb and it["kind"] in ("episode", "season") and str(it.get("tmdb") or "").isdigit():
                on_tmdb("tv", int(it["tmdb"]))
            show = read(it["show_id"]) if it["kind"] in ("episode", "season") and it.get("show_id") else None
            out["base"] = show or got
    elif tmdb_id and kind:
        out["row"] = _jf_from_snapshot(jelly, kind, tmdb_id)
        if out["row"]:
            out["base"] = read(out["row"]["jf_id"])
            out["jf_failed"] = out["base"] is None
    return out


def _sections(f: dict, names, c: dict, ex: dict) -> None:
    """The sections drawn from upstream answers (`ex`, settled) into `f`, one builder each (F2). The page calls it with
    what is cached, and with blank answers for a pending part (its Jellyfin-only fallback, the placeholder's content);
    a part request calls it with what the background read found. `c` is the page's context: kind, tmdb, t, title,
    people, crew_people, on_server, lib_keys, arr, jf_trailer, pending, late."""
    raw = ex["raw"] if isinstance(ex["raw"], dict) else {}
    kind, t, tmdb_id = c["kind"], c["t"], c["tmdb"]
    if "makers" in names:   # a show's "Created by" is TMDB's alone: its placeholder stays empty, not Jellyfin directors
        f["makers"] = [] if kind == "tv" and "makers" in c["pending"] else _makers(raw, c["people"], kind or "movie")
        f["makers_label"] = "Created by" if kind == "tv" else "Directed by"   # media-ux4: headshot cards in the hero
    if "actions" in names:
        f["show_request"] = bool(t and t["code"] != 5 and not (kind == "movie" and c["on_server"]))
        if c.get("late") and not c["jf_trailer"]:   # a part request: the TMDB trailer the page could not draw yet
            url, key = _trailer(None, raw)
            f["late_trailer"] = {"href": url, "key": key} if url else None
    if "scores" in names:   # media-ux4: every score is a pill in one format - IMDb 8.0 · RT 90% · Metacritic 74
        ratings = ex["ratings"] or {}
        mc = ex["mc"] if kind in ("movie", "tv") else None   # Metacritic via OMDb (item 2)
        f["numbers"].update(imdb=ratings.get("imdb"), rt=ratings.get("rt"), mc=mc, mc_band=mc_band(mc))
    if "collection" in names:
        f["collection"] = collection_banner(raw, kind, c["lib_keys"], tmdb_id) if raw and kind and tmdb_id else None
        if f["collection"]:
            try:  # Follow (2026-10-07): the series' Follow button state; the page never fails on it
                f["collection"]["following"] = media_follow.get("collection", f["collection"]["collection_id"]) is not None
            except Exception as exc:
                log.warning("follow lookup failed: %s", type(exc).__name__)
                f["collection"]["following"] = False
    if "crew" in names:
        f["crew"] = crew_for(raw, kind or "movie", c["crew_people"], jf_crew="crew" in c["pending"])
    if "dates" in names:
        f["facts"]["releases"] = _releases(raw, c["arr"], tmdb_id) if kind == "movie" else []
        f["facts"]["seasons"] = ((f"{t['n_seasons']} season{'s' if t['n_seasons'] != 1 else ''}"
                                  + (f" · {t['n_episodes']} episodes" if t.get("n_episodes") else ""))
                                 if kind == "tv" and t and t.get("n_seasons") else None)
    if "cast" in names:
        f["cast"] = _cast(raw, c["people"])
    if "providers" in names:
        f["providers"] = _providers(raw, c["title"])
    if "shelves" in names:
        f["shelves"] = _shelves(kind, c["lib_keys"], ex["similar"], ex["recs"]) if raw and kind and tmdb_id else []
    if "shelves" in names or "collection" in names:
        media_awards_badges.attach([r for sh in f.get("shelves") or [] for r in sh["rows"]]   # awards-ui item 3: one lookup
                                   + ((f.get("collection") or {}).get("rows") or []), kind)


BLANK = {"raw": None, "ratings": {}, "similar": None, "recs": None, "collection": None, "mc": None}


def build_film(kind: str | None = None, tmdb_id: int | None = None, jf_id: str | None = None, *,
               view: str, request: Request, req_state: str = "idle", req_msg: str | None = None,
               snaps=None, open_season: int | None = None, defer: bool = False) -> dict:
    """The page's `film` dict. `defer` (the routes, F2): never wait on Jellyseerr / OMDb - a section whose answer is
    not cached is left in `film.pending` for the page's part request. Without it (scripts, tests) every section is
    drawn, waiting for the reads as the page always did."""
    snaps = shell.get_snapshots() if snaps is None else snaps  # media-speed: the route's one read, passed in
    jsrc = shell.find_detail_source(JELLYFIN_SNAPSHOT_ID, snaps)
    jelly = (jsrc or {}).get("data") or {}
    owner = media_db.owner_of(view)
    arr_snap = snaps.get(ARR_SNAPSHOT_ID)
    arr = (arr_snap.data if arr_snap else {}) or {}
    f: dict = {"note": None, "jf_failed": False, "req_state": req_state, "req_msg": req_msg}
    connected = md._creds() is not None
    warmed: set = set()
    pf = is_prefetch(request)   # E1: a link prefetch's reads take the prefetch lane

    def warm(k, t):
        # media-speed (2026-10-07) / F2: the upstream reads start as soon as the title's TMDB id is known - from the
        # URL, else from the library snapshot - in the background, overlapping the Jellyfin reads.
        if k and t and (k, t) not in warmed:
            warmed.add((k, t))
            if not _complete(peek_extras(k, t)):
                warm_extras(k, t, prefetch=pf)

    if tmdb_id and kind:
        warm(kind, tmdb_id)
    elif jf_id:
        warm(*(tmdb_hint(jelly, jf_id) or (None, None)))

    # --- 1. Jellyfin side: base (film / series), plus the episode when the page is for one ---
    side = _jellyfin_side(kind, tmdb_id, jf_id, jelly, media_item._data, warm)
    base, ep, row, page_item = side["base"], side["ep"], side["row"], side["page_item"]
    f["jf_failed"] = side["jf_failed"]
    item = base["item"] if base else None
    seasons = (base or {}).get("seasons") or []
    if item:
        kind = "movie" if item["kind"] == "movie" else "tv"
        if not (tmdb_id and kind) and str(item.get("tmdb") or "").isdigit():
            tmdb_id = int(item["tmdb"])

    # --- 2. Jellyseerr side: what is cached (F2); an off-server title waits for its one title body ---
    ex, pending = dict(BLANK), set()
    if tmdb_id and kind:
        ex = extras_for(kind, tmdb_id, (item or {}).get("imdb"), wait=not defer, prefetch=pf)
        if defer and ex["raw"] is MISSING and connected and (not item or req_state != "idle"):
            # the title body IS the page when Jellyfin has nothing (title, poster, overview, Request), and a request
            # step (confirm / done / error) draws the request block now - the one read such a page waits for
            ex = peek_extras(kind, tmdb_id, (item or {}).get("imdb"), raw=_cget(f"/api/v1/{kind}/{tmdb_id}"))
        pending = pending_parts(ex, kind) if defer else set()
        ex = settle(ex)
    body = ex["raw"]
    raw, t = ({}, None) if not isinstance(body, dict) else (body, md.title_from(body, kind, tmdb_id))
    f["kind"], f["pending"] = kind, pending
    jf_item_id = item["id"] if item else (row["jf_id"] if row else None)
    f["t"], f["connected"] = t, connected
    if tmdb_id and not item and not t:
        f["note"] = "Title unavailable" if connected else "Not connected"

    # --- 3. what is on the server ---
    files = (base or {}).get("files")
    if files is None and t and t["status_word"] in md.ON_DISK and not item:
        files = media_files.file_summary(kind, tmdb_id, snaps=snaps)
    on_server = bool(item or row or jf_id and not f["jf_failed"] or (t and t["status_word"] in md.ON_DISK))
    # WP-T1 (2026-10-19): a show is on the server only with an episode file. A series Jellyfin lists with no episode
    # (Sonarr made its folder before any file arrived) and a show Sonarr holds no file of (whatever Seerr says) is not.
    ext = raw.get("externalIds") if isinstance(raw.get("externalIds"), dict) else {}
    tvdb = ext.get("tvdbId") or (item or {}).get("tvdb")   # F2: Jellyfin's TheTVDB id while the body is pending
    sonarr = mss.season_states(tvdb, tmdb_id) if kind == "tv" else None
    empty_show = bool(kind == "tv" and item and item["kind"] == "series" and not any(s.get("episodes") for s in seasons))
    if empty_show or (kind == "tv" and not item and mss.waiting(sonarr)):
        on_server = False
    f.update(on_server=on_server, files=files, status_word=(t or {}).get("status_word"), sonarr=sonarr,
             empty_show=empty_show)
    title = (item["title"] if item else (t or {}).get("title") or (row or {}).get("title")
             or ("Jellyfin item" if jf_id else "Title unavailable"))
    year = (item["year"] if item else (t or {}).get("year") or (row or {}).get("year"))
    seerr = md._creds()
    f.update(title=title, year=year, tagline=(t or {}).get("tagline") or "",
             overview=(item or {}).get("overview") or (t or {}).get("overview") or "",
             genres=(item or {}).get("genres") or (t or {}).get("genres") or [],
             official=(item or {}).get("official_rating"),
             backdrop=(item["backdrop"] if item else (row or {}).get("backdrop") if row else None) or (t or {}).get("backdrop"),
             poster=(item["poster"] if item else (row or {}).get("poster")) or (t or {}).get("poster"),
             # F2: the link needs no read (the same URL title_from builds), so it is there while the body is pending
             jellyseerr_href=(t or {}).get("jellyseerr_href") or (f"{seerr[0]}/{kind}/{tmdb_id}"
                                                                  if seerr and "actions" in pending else None),
             tmdb=tmdb_id)

    # --- 4. watch state, Play, series summary ---
    played, in_progress, left = (item["played"], item["in_progress"], item["left_text"]) if item and kind == "movie" else (False, False, None)
    f.update(played=played, in_progress=in_progress)
    snap_server = jelly.get("server_id")
    creds = media_files._creds()
    server = media_item._server_id(*creds, snap_server) if creds and (jf_item_id or jf_id) else snap_server
    href_of = lambda i: shell._deep_link((jsrc or {}).get("href"), i, server)
    if media_watch.available(request):   # JY-054: flag on, private front, you / her - else today's Jellyfin hand-off
        href_of = media_watch.href
    f["play"] = None
    play_ids: dict = {}   # Joey TV WP-B3: the item id behind each Play href (data-jf-id)
    f["series"], f["next_ep"] = None, None
    if kind == "tv" and seasons:
        eps = [e for s in seasons for e in s["episodes"]]
        nxt = _next_episode(seasons)
        f["series"] = {"episodes": len(eps), "to_watch": sum(1 for e in eps if not e["played"] and e["aired"])}
        # E6 (2026-10-13; E5's M2 words on the show hero): "6 left · ~4h 30m" — the hours from the average runtime of
        # this show's episodes in the read above (JY-104), else the recorded plays' (media_plays_db.show_runtimes),
        # else "6 left"; never on an episode page
        if not ep and jf_item_id and f["series"]["to_watch"]:
            rt = (media_item.episode_runtime(seasons)
                  or media_plays_db.show_runtimes([f"jf:{jf_item_id}"]).get(f"jf:{jf_item_id}"))
            f["series"]["progress"] = media_text.progress_words(f["series"]["to_watch"], len(eps), rt)
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
            play_ids["play"] = nxt["jf_id"] if nxt else jf_item_id
    elif (jf_item_id or f["jf_failed"]) and not empty_show:   # WP-T1: nothing to play in an empty show
        pid = jf_item_id or jf_id
        label = (f"Resume ▶ · {left}" if left else "Resume ▶") if in_progress else "Play again ▶" if played else "Play ▶"
        f["play"] = {"href": href_of(pid), "label": label}
        play_ids["play"] = pid
    # media-ux3: `?season=N` (the banner's "This season") opens that season; else the page's episode / season
    page_season = (open_season if open_season is not None
                   else page_item["season_no"] if page_item and page_item["kind"] in ("episode", "season") else None)
    f["seasons"] = episode_list(seasons, href_of if (jf_item_id or jf_id) else None, page_season, f["next_ep"])
    for s in f["seasons"]:   # WP-T1: "Season 4 · 3 of 6 watched · 5 to come · next airs 2 Nov"
        s["state_word"] = ((sonarr or {}).get("by_n", {}).get(s["n"]) or {}).get("word")
    # JY-113: seasons only Sonarr has (announced / monitored, nothing on the server) end the same Seasons list
    f["seasons_sonarr"] = mss.sonarr_only_seasons(sonarr, [s["n"] for s in f["seasons"]])
    # WP-T1: Sonarr's reads for these words run after the response (never before the render); the next view has them
    f["state_later"] = mss.later([(tvdb, tmdb_id)], detail=True) if kind == "tv" else None
    f["part_of"] = part_of(page_item, item, f["seasons"])
    if ep:
        ep = listed_episode(ep, seasons)  # media-ux4: one watch state per page (hero = banner = rows)
        f["episode"] = {"code": ep["code"], "title": ep["title"], "air_date": ep["air_date"],
                        "overview": ep["overview"], "runtime": ep["runtime"],
                        "play": {"href": href_of(ep["id"]),
                                 "label": ("Resume ▶" + (f" · {ep['left_text']}" if ep["left_text"] else "")) if ep["in_progress"]
                                 else "Play again ▶" if ep["played"] else "Play ▶"},
                        "show_href": f"/media/item/{item['id']}" if item and item["kind"] == "series" else None}
        # JY-192: the TV episode hero leads with the episode's own still (the /img proxy, never a call here)
        f["episode"]["still"] = f"jf:{ep['id']}" if media_item.ITEM_RE.match(str(ep["id"])) else None
        f["episode_season"] = ep["season_no"]
        play_ids["episode"] = ep["id"]
    else:
        f["episode"] = None
    # TV episode flow (WP-E1, 2026-10-16): per-episode ratings from media.db / the caches only; the reads they still
    # need run as the response's BackgroundTask (`ratings_later`, attached by the routes after the render). A show
    # Jellyfin does not have (an off-server /media/title/tv/... page) is rated from Jellyseerr's own season list (JY-119,
    # 2026-10-24): same stored rows and cache peeks, the same BackgroundTask fill, no watch state.
    f["ratings"], f["ratings_later"] = None, None
    if kind == "tv" and item and item["kind"] == "series" and seasons:
        try:
            f["ratings"], f["ratings_later"] = media_episode_ratings.build_ratings(
                item, f["seasons"], (page_item or item)["kind"], page_season, lambda i: f"/media/item/{i}",
                page_episode=ep["episode_no"] if ep else None)
        except Exception as exc:  # the page never fails on the ratings block
            log.warning("episode ratings skipped: %s", type(exc).__name__)
    elif kind == "tv" and tmdb_id and not f["seasons"] and t and t.get("seasons"):
        try:
            f["ratings"], f["ratings_later"] = media_episode_ratings.build_ratings(
                {"imdb": imdb_id(raw, item), "tmdb": tmdb_id}, offserver_seasons(t["seasons"]), "series")
        except Exception as exc:  # the page never fails on the ratings block
            log.warning("episode ratings skipped: %s", type(exc).__name__)
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
    ratings_map = media_home._ratings(view, [{"item_key": rating["item_key"]}] if rating else [])
    f["rating"] = rating
    f["score"] = ratings_map.get(rating["item_key"]) if rating else None
    diary_item = key_item or {"kind": "movie" if kind == "movie" else "series", "id": "", "tmdb": tmdb_id,
                              "episode_key": None, "season_key": None}
    dates = media_item._diary_dates(diary_item, owner) if (rating or item) else []
    count = max(len(dates), media_plays_db.watch_count(jf_item_id, owner) if jf_item_id and kind == "movie" else 0)
    last = _short(dates[0]) if dates else (_short(md._date_words(item.get("last_played"))[0]) if item and item.get("last_played") else None)
    f.update(diary=dates, watch_count=count, last_watched=last)

    # --- 6. request / downloading ---
    req = _requested(snaps, tmdb_id) if tmdb_id else None
    f["requested_when"] = req.get("when") if req else None
    f["requested_by"] = req.get("requested_by") if req else None
    dl_keys = ([f"tmdb:{tmdb_id}"] if kind == "movie" and tmdb_id else
               [f"tvdb:{tvdb}"] if kind == "tv" and str(tvdb or "").isdigit() else [])
    f["downloading_pct"] = md._dl_pct(dl_keys, snaps) if dl_keys and not f["jf_failed"] else None   # M-50: by key

    # --- 7. numbers, facts, people, shelves ---
    runtime_min = (item or {}).get("runtime_min") or (t or {}).get("runtime") if kind == "movie" else None
    if ep:
        runtime_min = ep.get("runtime_min")
    mins = (int("".join(c for c in left if c.isdigit()) or 0) if in_progress and left else None) or runtime_min
    ends = None
    if mins and (kind == "movie" or ep):
        ends = (shell._now_home() + timedelta(minutes=mins)).strftime("%H:%M")
    community = score_text(item["community_rating"] if item and item.get("community_rating") else (t or {}).get("vote"))
    f["numbers"] = {"tmdb": community, "imdb": None, "rt": None, "mc": None, "mc_band": None,
                    "runtime": runtime_text(runtime_min) if runtime_min else None, "ends": ends}
    f["logos"] = logos()
    added = md._date_words(item.get("added"))[0] if item and item.get("added") else None
    f["file"] = file_panel(files, kind, added)
    f["facts"] = {"runtime": runtime_text(runtime_min) if runtime_min else None,
                  "languages": _languages(files), "added": added, "releases": [], "seasons": None}
    people = (item or {}).get("people") or []
    f["cast_h"], f["maker_h"] = CAST_H, MAKER_H
    f["directors"] = show_directors(item, seasons) if kind == "tv" and not ep else []   # a show page's second card row (2026-10-11); not episodes
    f["trailer"], f["trailer_key"] = _trailer((item or {}).get("trailer"), raw)   # media-ux4: in-page player key
    lib_keys = on_server_keys(jelly, "movie") | on_server_keys(jelly, "tv")
    f["collection"], f["shelves"] = None, []
    ctx = {"kind": kind, "tmdb": tmdb_id, "t": t, "title": title, "people": people,
           "crew_people": (ep or {}).get("people") or show_crew(item, seasons), "on_server": on_server,
           "lib_keys": lib_keys, "arr": arr, "jf_trailer": (item or {}).get("trailer"), "pending": pending}
    _sections(f, [p for p in PARTS if p not in pending], ctx, ex)
    _sections(f, [p for p in PARTS if p in pending], ctx, dict(BLANK))   # placeholders: the Jellyfin-only fallback
    f.update(episode_flow(page_item, ep, item, f["seasons"], f.get("cast")))   # TV episode flow (WP-E3, 2026-10-16)
    # JY-192 (U6): the TV title page's Seasons + Episodes shelves (the template draws them in TV mode only)
    f["tv"] = tv_shelves(f["seasons"], page_item["season_no"] if page_item and page_item["kind"] in ("episode", "season")
                         else None, ep["id"] if ep else None, f["next_ep"])
    f["wl_on"] = bool(keys_for(request, [f"tmdb:{tmdb_id}"])) if tmdb_id else False
    f["follow_flash"] = media_follow.flash_text(request)
    f["back"] = request.url.path
    # Search now (media-ux5): a lazy-loaded form, shown only when the title is in Radarr / Sonarr (never on an episode
    # page - it would search the whole series); the page itself makes no *arr call.
    f["arr_search"] = (media_arr_search.lazy_href(kind, tmdb_id, tvdb, request.url.path)
                       if not ep else None)
    f["search_flash"] = media_arr_search.flash_text(request.query_params)
    # Quality (WP-R1): "Quality · 1080p" + Switch, lazy-loaded like Search now; drawn here only for the no-JS confirm step
    f["quality_href"] = media_quality.lazy_href(kind, tmdb_id, tvdb, request.url.path) if not ep else None
    f["quality_block"] = (media_quality.block(kind, tmdb_id, tvdb, request.url.path, ask=True)
                          if f["quality_href"] and request.query_params.get("quality_ask") == "1" else None)
    f["quality_flash"] = media_quality.flash_text(request.query_params)
    f["upgrade"] = _upgrade(snaps, jelly, kind, tmdb_id, tvdb, title) if not ep else None   # F4b: snapshot only
    f["upgrade_flash"] = media_arr_search.upgrade_flash(request.query_params)
    f["status_line"] = status_line(f)
    f["awards"] = film_awards(kind, tmdb_id, jelly, jf_item_id)   # Awards (2026-10-08): media.db only, no call
    # F2: the ONE request that fills every placeholder (out-of-band swaps), naming only the parts still pending
    f["parts_href"] = (f"{request.url.path}/part/all?p=" + ",".join(p for p in PARTS if p in pending)) if pending else None
    if kind and (jf_id or on_server):  # an off-server title keeps the Discover section it was found in
        request.state.media_section = "movies" if kind == "movie" else "tv"
    _play_ids(f, play_ids)
    return guest_controls(f, kind, tmdb_id)


def build_parts(names, kind: str | None = None, tmdb_id: int | None = None, jf_id: str | None = None, *,
                snaps, back: str) -> dict:
    """A part request's `film` (F2): only the named sections, from the item data the page has just cached (never a
    second Jellyfin read) and the title's background read (awaited, bounded by EXTRAS_WAIT)."""
    jsrc = shell.find_detail_source(JELLYFIN_SNAPSHOT_ID, snaps)
    jelly = (jsrc or {}).get("data") or {}
    arr_snap = snaps.get(ARR_SNAPSHOT_ID)
    arr = (arr_snap.data if arr_snap else {}) or {}
    side = _jellyfin_side(kind, tmdb_id, jf_id, jelly, media_item.peek)
    base, ep, row = side["base"], side["ep"], side["row"]
    item = base["item"] if base else None
    seasons = (base or {}).get("seasons") or []
    if item:
        kind = "movie" if item["kind"] == "movie" else "tv"
        if not tmdb_id and str(item.get("tmdb") or "").isdigit():
            tmdb_id = int(item["tmdb"])
    f: dict = {"kind": kind, "tmdb": tmdb_id, "pending": set(), "numbers": {}, "facts": {}, "logos": logos(),
               "cast_h": CAST_H, "maker_h": MAKER_H, "req_state": "idle", "req_msg": None, "req_future": None,
               "makers": [], "crew": [], "cast": [], "providers": [], "shelves": [], "collection": None,
               "show_request": False, "late_trailer": None, "t": None, "play": None, "follow_flash": None, "back": back}
    if not (kind and tmdb_id):
        return f
    ex = settle(extras_for(kind, tmdb_id, (item or {}).get("imdb"), wait=True))
    body = ex["raw"]
    raw, t = ({}, None) if not isinstance(body, dict) else (body, md.title_from(body, kind, tmdb_id))
    title = (item["title"] if item else (t or {}).get("title") or (row or {}).get("title") or "Title unavailable")
    on_server = bool(item or row or (jf_id and not side["jf_failed"]) or (t and t["status_word"] in md.ON_DISK))
    jf_item_id = item["id"] if item else (row["jf_id"] if row else None)
    f.update(t=t, title=title, year=(item or {}).get("year") or (t or {}).get("year"),
             play={"href": shell._deep_link((jsrc or {}).get("href"), jf_item_id, None), "jf_id": jf_item_id}
             if jf_item_id else None)
    ctx = {"kind": kind, "tmdb": tmdb_id, "t": t, "title": title, "people": (item or {}).get("people") or [],
           "crew_people": (ep or {}).get("people") or show_crew(item, seasons), "on_server": on_server,
           "lib_keys": on_server_keys(jelly, "movie") | on_server_keys(jelly, "tv"), "arr": arr,
           "jf_trailer": (item or {}).get("trailer"), "pending": set(), "late": True}
    _sections(f, names, ctx, ex)
    return guest_controls(f, kind, tmdb_id)


def _play_ids(f: dict, play_ids: dict) -> None:
    """Each Play button carries `jf_id` - the Jellyfin item id its href names - for the template's `data-jf-id` (the TV
    shell hands that id to the Jellyfin app, WP-B6 route 1b)."""
    for slot, jf in play_ids.items():
        target = f.get(slot) if slot == "play" else (f.get("episode") or {}).get("play")
        if target and target.get("href") and jf:
            target["jf_id"] = str(jf)


def guest_controls(f: dict, kind, tmdb_id) -> dict:
    """Joey TV WP-B3 step 4 (Q19): on the media front a title / item page carries no household control - no Search now,
    Quality, upgrade note, file-strip badges, Follow (show / collection) or Jellyseerr link, and the Request block only
    where hub.guest.allows() serves the request route (GUEST since WP-B4), with the signed-in friend's own request
    state (`req_mine`: pending / approved / declined, hub.media_guest_requests). Private front: `f` untouched."""
    if not guest.is_media():
        return f
    f["ratings_later"] = None   # JY-119: a friend's view draws the stored ratings but never starts the OMDb / Seerr reads
    f.update(arr_search=None, quality_href=None, quality_block=None, upgrade=None, jellyseerr_href=None)
    if f.get("file"):
        f["file"] = {**f["file"], "badges": []}
    if f.get("collection"):
        f["collection"] = {**f["collection"], "followable": False}
    f["providers"] = [{**g, "href": None} for g in f.get("providers") or []]   # names stay, no JustWatch link
    if f.get("trailer") and not f.get("trailer_key"):   # a trailer only as a YouTube video (Q41), never another site
        f["trailer"] = None
    if not (kind in ("movie", "tv") and tmdb_id and guest.allows("GET", f"/media/title/{kind}/{tmdb_id}/request")):
        f["show_request"] = False
    if f.get("show_request"):
        from hub import media_guest_requests   # late: it imports media_discover
        f["req_mine"] = media_guest_requests.title_mine(kind, tmdb_id)
    return f


def film_awards(kind, tmdb_id, jelly: dict, jf_item_id) -> list[dict]:
    """The Awards section rows (AWARDS_PLAN A5): this title's nominations across every ceremony, from the media.db
    award tables (matched on its TMDB id, or a show's TheTVDB key from the library row). Never fails the page."""
    if kind not in ("movie", "tv"):
        return []
    keys = {f"tmdb:{tmdb_id}"} if tmdb_id else set()
    for r in (jelly or {}).get("movies" if kind == "movie" else "shows") or []:
        if isinstance(r, dict) and jf_item_id and r.get("jf_id") == jf_item_id and r.get("item_key"):
            keys.add(r["item_key"])
    if not keys:
        return []
    try:
        from hub import media_awards_db, media_awards_pages
        return media_awards_pages.section_rows(media_awards_db.work_awards(sorted(keys), kind), kind)
    except Exception as exc:  # the page never fails on the awards lookup
        log.warning("awards lookup failed: %s", type(exc).__name__)
        return []


# ---- routes ----

def _render(request: Request, src, film: dict, view, from_query, snaps=None):
    later = mss.chain(film.pop("ratings_later", None), film.pop("state_later", None))
    resp = shell.render_page(request, "media_film.html", {
        "status": shell.build_status(shell.get_snapshots() if snaps is None else snaps), "src": src, "film": film})
    if later is not None:   # WP-E1: the episode ratings' missing reads, after the response - never before the render
        resp.background = BackgroundTask(later)
    return shell._maybe_set_cookie(resp, view, from_query)


def is_prefetch(request: Request) -> bool:
    """A link prefetch (F2, hub/static/joey.js): the page's reads run - Jellyfin read and cached, the upstream read
    started - but nothing is rendered or written, and the answer is an empty 204 the browser throws away."""
    return request.headers.get("x-joey-prefetch") == "1"


def _prefetched(what: str) -> Response:
    log.info("film prefetch: %s", what)   # the kind of page only - never the path or an id
    return Response(status_code=204)


@router.get("/media/title/{kind}/{tmdb_id}", response_class=HTMLResponse)
def title_page(request: Request, kind: str, tmdb_id: int, step: str = "", requested: str = "", error: str = "",
               future: str = "", quality: str = "", qnet: str = ""):
    kind = md._kind(kind)
    view, from_query = shell.resolve_owner_view(request)
    snaps = shell.get_snapshots(request=request)  # media-speed: one snapshot read per request, shared
    src = shell.find_detail_source(JELLYSEERR_SNAPSHOT_ID, snaps, detail=md.DISCOVER_DETAIL)
    if src is None:
        return Response(status_code=204) if is_prefetch(request) else shell.not_found_page(request)
    state, msg = (("done", None) if requested == "1" else ("error", md.ERRORS[error]) if error in md.ERRORS
                  else ("confirm" if step == "confirm" else "idle", None))
    film = build_film(kind, tmdb_id, view=view, request=request, req_state=state, req_msg=msg, snaps=snaps, defer=True)
    if is_prefetch(request):
        return _prefetched("title")
    film["req_future"] = media_arr_search.future_note(future) if state == "done" else None   # media-ux5 item 7
    # WP-R1: the Quality chips on the no-JS confirm step; "Requested in 4K" + the safety net's warning when done
    film["req_profiles"] = (media_quality.choices(kind) if state == "confirm" and film.get("show_request")
                            and not guest.is_media() else [])   # Joey TV WP-B4: no Quality on the media front (Q19)
    film["req_quality"] = media_quality.name_of(kind, quality) if state == "done" else None
    film["req_qnote"] = media_quality.net_note(qnet, kind) if state == "done" else None
    return _render(request, src, film, view, from_query, snaps)


@router.get("/media/item/{jf_id}", response_class=HTMLResponse)
def item_page(request: Request, jf_id: str, season: str = ""):
    if not media_item.ITEM_RE.match(jf_id):
        raise HTTPException(404, "No such item")
    view, from_query = shell.resolve_owner_view(request)
    snaps = shell.get_snapshots(request=request)  # media-speed: one snapshot read per request, shared
    src = shell.find_detail_source(JELLYFIN_SNAPSHOT_ID, snaps)
    if src is None:
        raise HTTPException(404, "No such item")
    open_season = int(season) if season.isdigit() and len(season) <= 3 else None  # media-ux3: "This season"
    film = build_film(jf_id=jf_id, view=view, request=request, snaps=snaps, open_season=open_season, defer=True)
    if is_prefetch(request):
        return _prefetched("item")
    return _render(request, src, film, view, from_query, snaps)


# ---- deferred parts (F2): `name` is one part, or `all` with `p=<part>,<part>` (the page's one request) ----

def _parts(request: Request, name: str, p: str, **where):
    if name != "all" and name not in PARTS:
        raise HTTPException(404, "No such part")
    names = [n for n in dict.fromkeys(p.split(",") if name == "all" else [name]) if n in PARTS]
    back = request.url.path.rsplit("/part/", 1)[0]
    film = None
    if names:
        try:
            film = build_parts(names, snaps=shell.get_snapshots(request=request), back=back, **where)
        except Exception as exc:  # a part never fails the page: its placeholder just empties
            log.warning("film part failed: %s", type(exc).__name__)
    return shell.templates.TemplateResponse(request, "_film_parts.html", {"film": film, "names": names})


@router.get("/media/title/{kind}/{tmdb_id}/part/{name}", response_class=HTMLResponse)
def title_part(request: Request, kind: str, tmdb_id: int, name: str, p: str = ""):
    return _parts(request, name, p[:200], kind=md._kind(kind), tmdb_id=tmdb_id)


@router.get("/media/item/{jf_id}/part/{name}", response_class=HTMLResponse)
def item_part(request: Request, jf_id: str, name: str, p: str = ""):
    if not media_item.ITEM_RE.match(jf_id):
        raise HTTPException(404, "No such item")
    return _parts(request, name, p[:200], jf_id=jf_id)
