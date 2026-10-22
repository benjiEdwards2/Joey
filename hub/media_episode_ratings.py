"""Per-episode ratings for the TV episode flow (WP-E1, 2026-10-16; EPISODES_CONTRACT §2 `ratings`, §4 E1).

Source: IMDb via OMDb (the same optional `OMDB_API_KEY`, daily budget and refusal stop as hub/media_omdb.py), TMDB via
the Jellyseerr season read as the fallback.

  * One OMDb call per season: `GET https://www.omdbapi.com/?i=<series imdb>&Season=<n>&apikey=…` answers every
    episode's `imdbRating`, its own imdb id, `Title` and `Released`. Vote counts need a call per episode
    (`?i=<episode imdb>` → `imdbVotes`): only for the page's current season, at most VOTES_MAX per page view.
  * Answers live in media.db `episode_rating` (schema step 5). A season is re-read when its `fetched_at` is older than
    TTL (7 days) AND it is still airing (an episode aired within RECENT_DAYS, or nothing of it has aired yet); else it is
    kept forever. Votes follow the same rule on their own `votes_at`.
  * A season OMDb does not know ("not found", no episodes) is remembered TTL; a failed call (no answer, timeout,
    non-2xx, bad JSON, HTTP 401) FAIL_TTL — in memory and on disk beside the Jellyseerr meta cache (`media_discover`),
    so a restart keeps the wait. A refused key / OMDb's own limit also stops OMDb for the rest of the UTC day.
  * Nothing here calls anything from a request thread. `build_ratings` draws what is stored (media.db) and cached
    (the Jellyseerr season reads, `meta_peek`) and hands back a callable the page runs as its BackgroundTask, after the
    response, to read what is missing; the next view draws it.
  * TMDB fallback: when the show has no IMDb id, or nothing of it is stored from OMDb, the Jellyseerr
    `/api/v1/tv/{tmdb}/season/{n}` read (`voteAverage`, `voteCount`, `airDate`) — `source: "TMDB"`.

Logs carry counts and status words only — never a URL, key, imdb id or response body.
"""
from __future__ import annotations

import logging
import re
import sqlite3
import threading
import time
from contextlib import closing
from datetime import date, datetime, timedelta, timezone

from hub import media_discover as md, media_omdb, media_store, upstream
from hub.media_cache import LRU

log = logging.getLogger("hub.media_episode_ratings")

TTL = 7 * 24 * 3600          # a stored season / vote count is re-read after this, while the season is still airing
FAIL_TTL = media_omdb.FAIL_TTL
RECENT_DAYS = 120            # "still airing": an episode aired within this many days
VOTES_MAX = 12               # per-episode vote reads per page view (current season only)
SEASONS_MAX = 12             # seasons read per show (media_item.MAX_SEASONS)
TREND_MIN = 3                # a season needs this many rated episodes to count in the trend
SCALE = (0.0, 10.0)

DDL = """CREATE TABLE IF NOT EXISTS episode_rating(
  series_imdb TEXT NOT NULL, season INT NOT NULL, episode INT NOT NULL, rating REAL, votes INT, episode_imdb TEXT,
  fetched_at TEXT, released TEXT, title TEXT, votes_at TEXT, PRIMARY KEY(series_imdb, season, episode))"""


def migrate(db) -> None:
    """media.db step 5 (WP-E1, 2026-10-16; media_store.STEPS): the episode_rating table. Idempotent."""
    db.execute(DDL)
    db.commit()


# ---- clocks (tests freeze these) ----

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _today() -> date:
    return date.today()


# ---- memo of OMDb answers that are not rows: "none" (TTL) / "failed" (FAIL_TTL) ----

_mem: LRU = LRU()             # memo key -> (at, state)
_lock = threading.Lock()      # guards _running only
_running: set[str] = set()    # shows whose background read is in flight (a second view's job skips them)


def clear_cache() -> None:
    _mem.clear()
    with _lock:
        _running.clear()


def _memo(key: str) -> str | None:
    hit = _mem.get(key)
    if hit is None:
        disk = md._meta_disk(key)
        if disk is not None and isinstance(disk[1], dict) and disk[1].get("state") in ("none", "failed"):
            hit = (disk[0], disk[1]["state"])
            _mem[key] = hit
    if hit is None:
        return None
    ttl = FAIL_TTL if hit[1] == "failed" else TTL
    return hit[1] if time.time() - hit[0] < ttl else None


def _remember(key: str, state: str) -> None:
    now = time.time()
    _mem[key] = (now, state)
    md._meta_store(key, now, {"state": state})


def _season_key(imdb: str, n: int) -> str:
    return f"omdbep:{imdb}:{n}"


def _vote_key(ep_imdb: str) -> str:
    return f"omdbvote:{ep_imdb}"


# ---- OMDb ----

def _omdb(params: dict) -> tuple[str, dict | None]:
    """One budgeted OMDb call -> (word, body): ok · none (OMDb has nothing) · failed · stopped (no key, cap, refused)."""
    key = media_omdb._key()
    if not key or not media_omdb._budget():
        return "stopped", None
    try:
        resp = upstream.session("omdb").get(media_omdb.URL, params={**params, "apikey": key},
                                            timeout=media_omdb.TIMEOUT)
    except Exception as exc:  # type only - the exception text holds the URL, which holds the key
        log.warning("omdb episode read failed: %s", type(exc).__name__)
        return "failed", None
    if resp.status_code == 401:
        log.warning("omdb episode read refused: HTTP 401")
        media_omdb._day[2] = True
        return "failed", None
    if not 200 <= resp.status_code < 300:
        log.warning("omdb episode read failed: HTTP %s", resp.status_code)
        return "failed", None
    try:
        body = resp.json()
    except Exception as exc:
        log.warning("omdb episode read failed: %s", type(exc).__name__)
        return "failed", None
    if not isinstance(body, dict):
        return "failed", None
    error = str(body.get("Error") or "").lower()
    if any(e in error for e in media_omdb.KEY_ERRORS):
        log.warning("omdb episode read refused: key or daily limit")
        media_omdb._day[2] = True
        return "failed", None
    if str(body.get("Response")) == "False":
        return "none", None
    return "ok", body


def _int(v) -> int | None:
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def _rating(v) -> float | None:
    try:
        r = float(str(v).strip())
    except (TypeError, ValueError):
        return None
    return round(r, 1) if SCALE[0] < r <= SCALE[1] else None


def _iso(v) -> str | None:
    s = str(v or "")[:10]
    return s if re.match(r"^\d{4}-\d{2}-\d{2}$", s) else None


def parse_season(body) -> tuple[list[dict], int | None]:
    """OMDb season body -> ([{episode, rating, episode_imdb, title, released}], totalSeasons)."""
    rows = []
    if not isinstance(body, dict):
        return rows, None
    for e in body.get("Episodes") or []:
        num = _int(e.get("Episode")) if isinstance(e, dict) else None
        if num is None:
            continue
        ep_imdb = str(e.get("imdbID") or "")
        rows.append({"episode": num, "rating": _rating(e.get("imdbRating")),
                     "episode_imdb": ep_imdb if media_omdb.IMDB_RE.match(ep_imdb) else None,
                     "title": str(e.get("Title") or "")[:200] or None, "released": _iso(e.get("Released"))})
    return rows, _int(body.get("totalSeasons"))


def parse_votes(body) -> int:
    """'12,345' -> 12345; N/A or anything else -> 0."""
    raw = str((body or {}).get("imdbVotes") or "").replace(",", "")
    return int(raw) if raw.isdigit() else 0


def season_ratings(imdb_id: str, n: int) -> tuple[str, list[dict], int | None]:
    """ONE OMDb season read, stored. -> (word, rows, totalSeasons); word ok / none / failed / stopped. Background only."""
    word, body = _omdb({"i": imdb_id, "Season": n})
    rows, total = parse_season(body) if word == "ok" else ([], None)
    if word == "ok" and not rows:
        word = "none"
    if word in ("none", "failed"):
        _remember(_season_key(imdb_id, n), word)
    if word == "ok":
        _store_season(imdb_id, n, rows)
    return word, rows, total


def _store_season(imdb: str, n: int, rows: list[dict]) -> None:
    at = _now().isoformat()
    with closing(media_store.connect()) as db, db:
        db.executemany(
            "INSERT INTO episode_rating(series_imdb, season, episode, rating, episode_imdb, fetched_at, released, title) "
            "VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(series_imdb, season, episode) DO UPDATE SET rating = excluded.rating, "
            "episode_imdb = excluded.episode_imdb, fetched_at = excluded.fetched_at, released = excluded.released, "
            "title = excluded.title",
            [(imdb, n, r["episode"], r["rating"], r["episode_imdb"], at, r["released"], r["title"]) for r in rows])


def _store_votes(imdb: str, n: int, number: int, votes: int) -> None:
    with closing(media_store.connect()) as db, db:
        db.execute("UPDATE episode_rating SET votes = ?, votes_at = ? WHERE series_imdb = ? AND season = ? AND episode = ?",
                   (votes, _now().isoformat(), imdb, n, number))


def stored(imdb: str | None) -> dict[int, dict[int, dict]]:
    """{season: {episode: row}} for one show from media.db; {} with no id, no DB (reads never create it) or any error."""
    if not imdb:
        return {}
    db = media_store.reader()
    if db is None:
        return {}
    out: dict[int, dict[int, dict]] = {}
    try:
        with closing(db):
            for r in db.execute("SELECT * FROM episode_rating WHERE series_imdb = ?", (imdb,)):
                out.setdefault(r["season"], {})[r["episode"]] = dict(r)
    except sqlite3.Error as exc:
        log.warning("episode ratings read failed: %s", type(exc).__name__)
        return {}
    return out


# ---- the refresh rule ----

def _older(stamp: str | None, now: datetime) -> bool:
    try:
        at = datetime.fromisoformat(str(stamp))
    except (TypeError, ValueError):
        return True
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    return (now - at).total_seconds() >= TTL


def airing(dates, today: date) -> bool:
    """Still airing: an episode aired within RECENT_DAYS, or none of the known dates has aired yet."""
    days = [d for d in (_parse_day(x) for x in dates) if d is not None]
    aired = [d for d in days if d <= today]
    if not aired:
        return True
    return max(aired) >= today - timedelta(days=RECENT_DAYS)


def _parse_day(v) -> date | None:
    iso = _iso(v)
    try:
        return date.fromisoformat(iso) if iso else None
    except ValueError:
        return None


def season_due(rows: dict[int, dict] | None, now: datetime | None = None, today: date | None = None) -> bool:
    """Does a stored season need an OMDb re-read? Never stored: yes. Else only when older than TTL AND still airing."""
    if not rows:
        return True
    now, today = now or _now(), today or _today()
    oldest = min((r.get("fetched_at") or "" for r in rows.values()), default="")
    return _older(oldest, now) and airing([r.get("released") for r in rows.values()], today)


def votes_due(row: dict, season_airing: bool, now: datetime | None = None) -> bool:
    if row.get("rating") is None or not row.get("episode_imdb"):
        return False
    if row.get("votes_at") is None:
        return True
    return season_airing and _older(row["votes_at"], now or _now())


# ---- TMDB fallback (the Jellyseerr season read) ----

def _tmdb_path(tmdb, n: int) -> str:
    return f"/api/v1/tv/{tmdb}/season/{n}"


def tmdb_rows(body) -> dict[int, dict]:
    """Jellyseerr season body -> {episode: {rating, votes, title, released}} (voteAverage 0 = unrated)."""
    out: dict[int, dict] = {}
    if not isinstance(body, dict):
        return out
    for e in body.get("episodes") or []:
        num = e.get("episodeNumber") if isinstance(e, dict) else None
        if not isinstance(num, int) or isinstance(num, bool):
            continue
        votes = e.get("voteCount")
        out[num] = {"rating": _rating(e.get("voteAverage")), "title": str(e.get("name") or "")[:200] or None,
                    "votes": votes if isinstance(votes, int) and not isinstance(votes, bool) and votes > 0 else 0,
                    "released": _iso(e.get("airDate"))}
    return out


def _tmdb_peek(tmdb, n: int):
    """The cached season body (any age up to the meta keep), or None. Never a call."""
    got = md.meta_peek(_tmdb_path(tmdb, n), ttl=md.META_KEEP_S)
    return None if got is md.MISSING else got


# ---- the context block ----

def _year(dates) -> int | None:
    years = [d.year for d in (_parse_day(x) for x in dates) if d is not None]
    if years:
        return min(years)
    for x in dates:   # a Jellyfin date in words ('14 Mar 2026')
        m = re.search(r"\b(19|20)\d{2}\b", str(x or ""))
        if m:
            return int(m.group(0))
    return None


def _season_number(s: dict, i: int) -> int:
    if s.get("n") is not None:
        return s["n"]
    return s["number"] if s.get("number") is not None else i + 1


def _avg(eps: list[dict]) -> float | None:
    rated = [e["rating"] for e in eps if e["aired"] and e["rating"] is not None]
    return round(sum(rated) / len(rated), 1) if rated else None


def _trend(seasons: list[dict]) -> str | None:
    full = [s for s in seasons if s["avg"] is not None
            and sum(1 for e in s["eps"] if e["aired"] and e["rating"] is not None) >= TREND_MIN]
    if len(full) < 2:
        return None
    prev, last = full[-2], full[-1]
    d = round(last["avg"] - prev["avg"], 1)
    if d == 0:
        return f"S{last['n']} level with S{prev['n']}"
    return f"S{last['n']} {'up' if d > 0 else 'down'} {abs(d):.1f} on S{prev['n']}"


def _best(seasons: list[dict]) -> dict | None:
    best = None
    for s in seasons:
        for e in s["eps"]:
            if e["aired"] and e["rating"] is not None and (best is None or e["rating"] > best["rating"]):
                best = {"season": s["n"], "number": e["number"], "name": e["name"], "rating": e["rating"]}
    return best


def _current(seasons: list[dict], page_season) -> int:
    ns = [s["n"] for s in seasons]
    if page_season in ns:
        return page_season
    for s in seasons:   # the next-up episode's season
        if any(e["in_progress"] or (e["aired"] and not e["seen"] and e["jf_id"]) for e in s["eps"]):
            return s["n"]
    aired = [s["n"] for s in seasons if s["aired"]]
    return aired[-1] if aired else ns[-1]


def build_ratings(item: dict | None, seasons: list[dict], kind: str, page_season=None, hrefs=None, *,
                  page_episode=None):
    """(the contract's `ratings` dict | None, a background callable | None) for a series / season / episode page.

    `item` is the SHOW's media_item read (`imdb`, `tmdb`), `seasons` the page's `episode_list` output (watch state per
    episode), `hrefs(jf_id)` an episode's page link, `page_episode` the episode page's number. Draws only what is
    stored / cached; the callable reads what is missing (OMDb seasons, the current season's votes, TMDB seasons) and
    is meant for the response's BackgroundTask. `ratings` is None when nothing of the show is rated yet."""
    if kind not in ("series", "season", "episode") or not item:
        return None, None
    imdb = str(item.get("imdb") or "").strip()
    imdb = imdb if media_omdb.IMDB_RE.match(imdb) else None
    tmdb = str(item.get("tmdb") or "")
    tmdb = int(tmdb) if tmdb.isdigit() else None
    jf = {}
    for i, s in enumerate(seasons or []):
        n = _season_number(s, i)
        if n >= 1:
            jf[n] = {e["number"]: e for e in s.get("episodes") or [] if isinstance(e.get("number"), int)}
    imdb_rows = stored(imdb)
    source = "IMDb" if any(imdb_rows.values()) else None
    tmdb_bodies: dict[int, dict] = {}
    if source is None and tmdb and md._creds() is not None:
        for n in jf:
            got = tmdb_rows(_tmdb_peek(tmdb, n))
            if got:
                tmdb_bodies[n] = got
        source = "TMDB" if tmdb_bodies else None
    rated = imdb_rows if source == "IMDb" else tmdb_bodies
    numbers = sorted(set(jf) | (set(n for n in rated if n >= 1) if source == "IMDb" else set()))[:SEASONS_MAX]
    today = _today()
    out = []
    for n in numbers:
        mine, theirs = jf.get(n, {}), rated.get(n, {})
        eps = []
        for num in sorted(set(mine) | set(theirs)):
            j, r = mine.get(num), theirs.get(num) or {}
            day = _parse_day(r.get("released"))
            aired = bool(j["aired"]) if j else (day is not None and day <= today) or r.get("rating") is not None
            jf_id = j.get("jf_id") if j else None
            eps.append({"number": num, "rating": r.get("rating") if aired else None,
                        "votes": int(r.get("votes") or 0), "aired": aired,
                        "seen": bool(j and j.get("played")), "in_progress": bool(j and j.get("in_progress")),
                        "jf_id": jf_id, "href": hrefs(jf_id) if hrefs and jf_id else None,
                        "name": (j or {}).get("name") or r.get("title") or f"Episode {num}"})
        dates = [r.get("released") for r in theirs.values()] + [(e or {}).get("air_date") for e in mine.values()]
        out.append({"n": n, "year": _year(dates), "avg": _avg(eps), "votes": sum(e["votes"] for e in eps),
                    "seen": sum(1 for e in eps if e["seen"]), "total": len(eps),
                    "aired": sum(1 for e in eps if e["aired"]), "eps": eps})
    current = _current(out, page_season) if out else None
    later = _plan(imdb, tmdb, list(jf), imdb_rows, current, source)
    if not out or not any(e["rating"] is not None for s in out for e in s["eps"]):
        return None, later
    ratings = {"source": source, "seasons": out, "best": _best(out), "trend": _trend(out), "current": current,
               "episode": None}
    if kind == "episode":
        season = next((s for s in out if s["n"] == current), None)
        e = next((x for x in (season or {}).get("eps", []) if x["number"] == page_episode), None)
        if e is not None:
            avg = season["avg"]
            vs = (None if e["rating"] is None or avg is None or e["rating"] == avg
                  else "above" if e["rating"] > avg else "below")
            ratings["episode"] = {"rating": e["rating"], "votes": e["votes"], "vs_avg": vs}
        else:
            ratings["episode"] = {"rating": None, "votes": 0, "vs_avg": None}
    return ratings, later


# ---- the background read ----

def _plan(imdb, tmdb, jf_seasons: list[int], rows: dict, current, source):
    """What a view's BackgroundTask should read, or None when everything it would draw is stored and fresh."""
    now, today = _now(), _today()
    omdb_on = bool(imdb and media_omdb._key())
    seasons = []
    if omdb_on:
        for n in sorted(set(jf_seasons) | {s for s in rows if s >= 1})[:SEASONS_MAX]:
            if season_due(rows.get(n), now, today) and _memo(_season_key(imdb, n)) is None:
                seasons.append(n)
    votes = []
    if omdb_on and current is not None and rows.get(current):
        live = airing([r.get("released") for r in rows[current].values()], today)
        for num in sorted(rows[current]):
            r = rows[current][num]
            if votes_due(r, live, now) and _memo(_vote_key(r["episode_imdb"])) is None:
                votes.append((num, r["episode_imdb"]))
        votes = votes[:VOTES_MAX]
    tmdb_need = []
    if source != "IMDb" and not seasons and tmdb and md._creds() is not None:
        tmdb_need = [n for n in jf_seasons if md.meta_peek(_tmdb_path(tmdb, n)) is md.MISSING]
    if not (seasons or votes or tmdb_need):
        return None

    def run() -> dict:
        return fill(imdb, tmdb, seasons, current, votes, jf_seasons)
    run.plan = {"seasons": seasons, "votes": len(votes), "tmdb": tmdb_need}   # tests read it
    return run


def fill(imdb, tmdb, seasons: list[int], current, votes: list[tuple[int, str]], jf_seasons: list[int]) -> dict:
    """The BackgroundTask: OMDb season reads (OMDb's totalSeasons adds the seasons Jellyfin lacks), then the current
    season's vote counts (episode ids the season read has just stored included), then — when OMDb has nothing of the
    show — the Jellyseerr season reads. One job per show at a time. -> counts, for the log and the tests."""
    lock_key = imdb or f"tmdb:{tmdb}"
    with _lock:
        if lock_key in _running:
            return {"skipped": 1}
        _running.add(lock_key)
    counts = {"seasons": 0, "none": 0, "votes": 0, "tmdb": 0, "failed": 0, "stopped": 0}
    try:
        stopped = False
        queue, seen = list(seasons), set(seasons)
        while queue and not stopped:
            n = queue.pop(0)
            word, _, total = season_ratings(imdb, n)
            counts[{"ok": "seasons"}.get(word, word)] += 1
            stopped = word == "stopped"
            if word == "ok" and total:
                have = stored(imdb)
                for m in range(1, min(total, SEASONS_MAX) + 1):
                    if m not in seen and m not in have and _memo(_season_key(imdb, m)) is None:
                        seen.add(m)
                        queue.append(m)
        if imdb and current is not None and not stopped:
            rows = stored(imdb).get(current) or {}
            live = airing([r.get("released") for r in rows.values()], _today())
            want = dict(votes)
            for num in sorted(rows):   # ids the season read has just stored
                r = rows[num]
                if num not in want and votes_due(r, live) and _memo(_vote_key(r["episode_imdb"])) is None:
                    want[num] = r["episode_imdb"]
            for num, ep_imdb in list(sorted(want.items()))[:VOTES_MAX]:
                word, body = _omdb({"i": ep_imdb})
                if word == "stopped":
                    counts["stopped"] += 1
                    break
                if word == "failed":
                    counts["failed"] += 1
                    _remember(_vote_key(ep_imdb), "failed")
                    continue
                _store_votes(imdb, current, num, parse_votes(body) if word == "ok" else 0)
                counts["votes"] += 1
        if tmdb and md._creds() is not None and not any(stored(imdb).values()):
            for n in jf_seasons:
                if md.meta_peek(_tmdb_path(tmdb, n)) is md.MISSING:
                    md.meta_get(_tmdb_path(tmdb, n))
                    counts["tmdb"] += 1
    except Exception as exc:  # a background job never raises into the server log (type only: no URL, no id)
        log.warning("episode ratings fill failed: %s", type(exc).__name__)
        counts["failed"] += 1
    finally:
        with _lock:
            _running.discard(lock_key)
    log.info("episode ratings fill: %s season reads, %s vote reads, %s tmdb reads, %s failed",
             counts["seasons"], counts["votes"], counts["tmdb"], counts["failed"])
    return counts
