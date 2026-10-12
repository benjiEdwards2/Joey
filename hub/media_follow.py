"""Follow (2026-10-07): follow a person (actor / director) or a film series (TMDB collection) and have their NEW
films requested through Jellyseerr automatically. F5 (2026-10-12) adds shows and TV makers: a followed SHOW stays
monitored in Sonarr with every new season (see "shows" below), and a person followed as a TV maker (dept CREATOR —
followed from a show's "Created by" row, or from the person page of someone with TV Creator / Director credits) also
gets their NEW shows requested. Anyone else's TV credits are ignored, as before.

Rules (B., 2026-10-07):
  * actor  -> a film where they are top-5 billed (cast `order` 0-4);
  * director -> any film where their crew job is "Director" (any billing); a person who does both: either rule;
  * series -> any film in the collection's `parts`;
  * TV maker (dept CREATOR only) -> a show where their TV crew job is "Creator" or "Director", or "Executive Producer"
    when they are a Creator somewhere (a showrunner's later shows often carry only that credit); requested with
    `seasons: "all"`, the Discover "All seasons + future" payload. "New" = a known first air date after today;
  * future only (tightened by B., 2026-10-08): a film qualifies only when it has a KNOWN release date that is
    strictly after today. Unknown / "TBA" dates never qualify (untitled projects in development stay out until
    TMDB gives them a date — the 6-hourly check picks them up then). Nothing already released is ever added.
A title recorded in media_follow_adds as requested / already is never requested again by that follow (so a film
deleted in Radarr is not re-added); a failed request is retried next run.

The check reads Jellyseerr live (person combined_credits / collection) and requests through the SAME call the
Discover Request button uses (media_discover._send). At most MAX_PER_RUN requests a run; the rest wait for the
next run. Runs right after a Follow (a response background task) and on the hub's own loop (first ~2 min after
start, then every 6 h). MEDIA_FOLLOW=off disables the loop. No Jellyseerr keys -> no Jellyseerr calls at all
(followed shows need Sonarr only).
Each successful add posts one Discord message (MEDIA_DISCORD_WEBHOOK, else SERVER_DISCORD_WEBHOOK; neither ->
silent). Failures log the exception type / HTTP status only.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
from contextlib import closing
from datetime import date

import requests
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool

from hub import (media_arr_search, media_db, media_discover as md, media_requests as mr, media_store, media_text,
                 server_alerts, shell)
from hub.media_write import flash_keys, form_of, safe_back, same_origin

log = logging.getLogger("hub.media_follow")

KINDS = ("person", "collection", "show")
CREATOR = "creator"   # a person's dept when followed as a TV maker: their new SHOWS are requested too (F5)
MAX_PER_RUN = 10
FIRST_DELAY_S = 120
EVERY_S = 6 * 3600
TOP_BILLED = 5
REASONS = {"cast": "top-5 cast", "director": "director", "collection": "collection"}
SHOW_JOBS = {"Creator": "creator", "Director": "director"}   # TV crew job -> reason, strongest first
EP_JOB = ("Executive Producer", "executive producer")       # counts only for someone who is a Creator somewhere
KEEP = ("requested", "already")   # outcomes that close a title for its follow; "failed" retries next run
ENV_WEBHOOK = "MEDIA_DISCORD_WEBHOOK"

FOLLOWS_DDL = """CREATE TABLE IF NOT EXISTS {name}(
  id INTEGER PRIMARY KEY, kind TEXT CHECK(kind IN ('person','collection','show')), tmdb_id INTEGER, name TEXT,
  followed_at TEXT, poster TEXT, dept TEXT, link TEXT, UNIQUE(kind, tmdb_id))"""
ADDS_DDL = """CREATE TABLE IF NOT EXISTS {name}(
  follow_id INTEGER, media TEXT NOT NULL DEFAULT 'movie', tmdb_id INTEGER, title TEXT, release_date TEXT, reason TEXT,
  outcome TEXT, note TEXT, at TEXT, poster TEXT, PRIMARY KEY(follow_id, media, tmdb_id))"""
DDL = (FOLLOWS_DDL.format(name="media_follows"), ADDS_DDL.format(name="media_follow_adds"))
FOLLOWS_COLS = "id, kind, tmdb_id, name, followed_at, poster, dept, link"
ADDS_COLS = "follow_id, tmdb_id, title, release_date, reason, outcome, note, at, poster"


def migrate_shows(db) -> None:
    """media.db step 3 (F5, 2026-10-12; media_store.STEPS): `media_follows.kind` also takes 'show' and an add is keyed
    on (follow_id, media, tmdb_id) — a film and a show may share a TMDB number. SQLite can't alter a CHECK or a key,
    so each table is rebuilt (rows copied, existing adds become media 'movie'). Idempotent: a table already in the new
    shape is left alone (a new file gets it from DDL in step 1)."""
    def sql(name):
        row = db.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)).fetchone()
        return row[0] if row else ""
    if "'show'" not in sql("media_follows"):
        db.execute(FOLLOWS_DDL.format(name="media_follows_f5"))
        db.execute(f"INSERT INTO media_follows_f5({FOLLOWS_COLS}) SELECT {FOLLOWS_COLS} FROM media_follows")
        db.execute("DROP TABLE media_follows")
        db.execute("ALTER TABLE media_follows_f5 RENAME TO media_follows")
    if "media TEXT" not in sql("media_follow_adds"):
        db.execute(ADDS_DDL.format(name="media_follow_adds_f5"))
        db.execute(f"INSERT INTO media_follow_adds_f5({ADDS_COLS}) SELECT {ADDS_COLS} FROM media_follow_adds")
        db.execute("DROP TABLE media_follow_adds")
        db.execute("ALTER TABLE media_follow_adds_f5 RENAME TO media_follow_adds")
    db.commit()

_lock = threading.Lock()  # the after-Follow run and the loop never overlap


def disabled() -> bool:
    return os.environ.get("MEDIA_FOLLOW", "on").strip().lower() in ("off", "0", "false", "no")


# ---- storage ----

def ensure() -> sqlite3.Connection:
    """A connection for a write (media_store creates the tables below with the rest of media.db)."""
    return media_store.connect()


def _reader():
    return media_store.reader()


def follow(kind: str, tmdb_id: int, name: str, poster: str | None = None, dept: str | None = None,
           today: date | None = None, link: str | None = None) -> int:
    """Follow (idempotent: a second Follow keeps the first date). -> the follow id. A person followed again as a TV
    maker (dept CREATOR) is widened to films + shows; nothing ever narrows a follow but Unfollow."""
    with closing(ensure()) as db:
        db.execute("INSERT OR IGNORE INTO media_follows(kind, tmdb_id, name, followed_at, poster, dept, link) "
                   "VALUES(?,?,?,?,?,?,?)", (kind, int(tmdb_id), name[:120], (today or date.today()).isoformat(),
                                            poster, (dept or "")[:40], link))
        if dept == CREATOR:
            db.execute("UPDATE media_follows SET dept = ? WHERE kind = ? AND tmdb_id = ?", (CREATOR, kind, int(tmdb_id)))
        db.commit()
        return db.execute("SELECT id FROM media_follows WHERE kind = ? AND tmdb_id = ?",
                          (kind, int(tmdb_id))).fetchone()["id"]


def unfollow(kind: str, tmdb_id: int) -> None:
    with closing(ensure()) as db:
        with db:
            row = db.execute("SELECT id FROM media_follows WHERE kind = ? AND tmdb_id = ?", (kind, int(tmdb_id))).fetchone()
            if row:
                db.execute("DELETE FROM media_follow_adds WHERE follow_id = ?", (row["id"],))
                db.execute("DELETE FROM media_follows WHERE id = ?", (row["id"],))


def get(kind: str, tmdb_id: int) -> dict | None:
    db = _reader()
    if db is None:
        return None
    with closing(db):
        row = db.execute("SELECT * FROM media_follows WHERE kind = ? AND tmdb_id = ?", (kind, int(tmdb_id))).fetchone()
        return dict(row) if row else None


_ADDED = ("(SELECT COUNT(*) FROM media_follow_adds a WHERE a.follow_id = f.id "
          "AND a.outcome IN ('requested','already'){media}) AS {label}")
_MOVIE, _TV = " AND a.media = 'movie'", " AND a.media = 'tv'"


def follows() -> list[dict]:
    """Every follow, newest first, with its `added` count (requested / already) and that count split into
    `added_films` / `added_shows`."""
    db = _reader()
    if db is None:
        return []
    with closing(db):
        return [dict(r) for r in db.execute(
            f"SELECT f.*, {_ADDED.format(media='', label='added')}, "
            f"{_ADDED.format(media=_MOVIE, label='added_films')}, {_ADDED.format(media=_TV, label='added_shows')} "
            "FROM media_follows f "
            "ORDER BY f.followed_at DESC, f.id DESC")]


def followed(kind: str) -> set[int]:
    """The TMDB ids followed as `kind` (one cheap media.db read; a page's Follow state, never an upstream call).
    Never raises: an unreadable file is an empty set."""
    db = _reader()
    if db is None:
        return set()
    try:
        with closing(db):
            return {r["tmdb_id"] for r in db.execute("SELECT tmdb_id FROM media_follows WHERE kind = ?", (kind,))}
    except sqlite3.Error as exc:
        log.warning("follow lookup failed: %s", type(exc).__name__)
        return set()


def any_follows() -> bool:
    db = _reader()
    if db is None:
        return False
    with closing(db):
        return db.execute("SELECT 1 FROM media_follows LIMIT 1").fetchone() is not None


def recent_adds(limit: int = 20, outcomes: tuple | None = None) -> list[dict]:
    db = _reader()
    if db is None:
        return []
    sql = ("SELECT a.*, f.name AS follow_name FROM media_follow_adds a JOIN media_follows f ON f.id = a.follow_id")
    args: list = []
    if outcomes:
        sql += f" WHERE a.outcome IN ({','.join('?' * len(outcomes))})"
        args += list(outcomes)
    with closing(db):
        return [dict(r) for r in db.execute(sql + " ORDER BY a.at DESC, a.rowid DESC LIMIT ?", [*args, limit])]


def _closed(db, follow_id: int) -> set[tuple[str, int]]:
    return {(r["media"], r["tmdb_id"]) for r in db.execute(
        "SELECT media, tmdb_id FROM media_follow_adds WHERE follow_id = ? AND outcome IN ('requested','already')",
        (follow_id,))}


def _record(db, follow_id: int, c: dict, outcome: str, note: str | None) -> None:
    with db:
        db.execute("INSERT INTO media_follow_adds(follow_id, media, tmdb_id, title, release_date, reason, outcome, note, "
                   "at, poster) VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(follow_id, media, tmdb_id) DO UPDATE SET "
                   "outcome = excluded.outcome, note = excluded.note, at = excluded.at",
                   (follow_id, c.get("media", "movie"), c["tmdb_id"], c["title"], c["date"], c["reason"], outcome, note,
                    media_db._now().isoformat(), c["poster"]))


# ---- the rules (pure) ----

def _date(value) -> str:
    return str(value or "")[:10]


def qualifies(release: str, today: date | None = None) -> bool:
    """Future only: a known release date strictly after today. Unknown / unparseable dates never qualify."""
    try:
        return date.fromisoformat(str(release)[:10]) > (today or date.today())
    except ValueError:
        return False


def _cand(c: dict, reason: str, media: str = "movie") -> dict | None:
    try:
        tmdb_id = int(c.get("id"))
    except (TypeError, ValueError):
        return None
    if tmdb_id <= 0:
        return None
    info = c.get("mediaInfo")
    return {"media": media, "tmdb_id": tmdb_id, "title": str(c.get("title") or c.get("name") or "Untitled")[:200],
            "date": _date(c.get("firstAirDate") if media == "tv" else c.get("releaseDate")), "reason": reason,
            "poster": md._ref(c.get("posterPath")),
            "status": info.get("status") if isinstance(info, dict) else None}


def _order(value) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def person_films(body) -> list[dict]:
    """combined_credits -> the films this person directed, plus their film cast credits (TV ignored entirely).
    Jellyseerr's person credits carry no billing `order` (server/models/Person.ts maps cast credits field by field
    and drops it), so a cast row without one has `billing: None` and the check reads the film's own credits
    (server/models/common.ts Cast keeps `order`) before it counts. A row that does carry `order` is decided here."""
    if not isinstance(body, dict):
        return []
    out: dict[int, dict] = {}
    for c in body.get("crew") or []:
        if isinstance(c, dict) and c.get("mediaType") == "movie" and c.get("job") == "Director":
            row = _cand(c, REASONS["director"])
            if row:
                out.setdefault(row["tmdb_id"], {**row, "billing": 0})
    for c in body.get("cast") or []:
        if not (isinstance(c, dict) and c.get("mediaType") == "movie"):
            continue
        order = _order(c.get("order"))
        if order is not None and order >= TOP_BILLED:
            continue
        row = _cand(c, REASONS["cast"])
        if row:
            out.setdefault(row["tmdb_id"], {**row, "billing": order})
    return list(out.values())


def person_shows(body) -> list[dict]:
    """combined_credits -> the shows this person makes (TV crew: Creator / Director, plus Executive Producer for a
    Creator). Each show once, under its strongest reason."""
    crew = [c for c in (body.get("crew") or [] if isinstance(body, dict) else [])
            if isinstance(c, dict) and c.get("mediaType") == "tv"]
    jobs = dict(SHOW_JOBS)
    if any(c.get("job") == "Creator" for c in crew):
        jobs[EP_JOB[0]] = EP_JOB[1]
    out: dict[int, dict] = {}
    for job, reason in jobs.items():
        for c in crew:
            row = _cand(c, reason, "tv") if c.get("job") == job else None
            if row:
                out.setdefault(row["tmdb_id"], {**row, "billing": 0})
    return list(out.values())


def person_titles(body, shows: bool = False) -> list[dict]:
    """A person's films (person_films), plus their shows (person_shows) when followed as a TV maker."""
    return person_films(body) + (person_shows(body) if shows else [])


def tv_maker(body) -> bool:
    """Has this person made TV (Creator / Director credits)? The person page's Follow then covers shows too."""
    return bool(person_shows(body))


def billed_order(movie_body, person_id: int) -> int | None:
    """The person's cast `order` in a Jellyseerr /movie/{id} body, None when not in its cast."""
    cast = ((movie_body or {}).get("credits") or {}).get("cast") if isinstance(movie_body, dict) else None
    orders = [_order(c.get("order")) for c in cast or [] if isinstance(c, dict) and c.get("id") == person_id]
    orders = [o for o in orders if o is not None]
    return min(orders) if orders else None


def _top_billed(c: dict, person_id: int) -> bool:
    if c["billing"] is not None:
        return c["billing"] < TOP_BILLED
    from hub.media_film import _cget  # the film page's 10-min cache: a film opened since is not read twice
    order = billed_order(_cget(f"/api/v1/movie/{c['tmdb_id']}"), person_id)
    return order is not None and order < TOP_BILLED


def collection_films(body) -> list[dict]:
    parts = body.get("parts") if isinstance(body, dict) else None
    out: dict[int, dict] = {}
    for c in parts if isinstance(parts, list) else []:
        if isinstance(c, dict) and c.get("mediaType", "movie") == "movie":
            row = _cand(c, REASONS["collection"])
            if row:
                out.setdefault(row["tmdb_id"], row)
    return list(out.values())


# ---- Discord ----

def webhook() -> str | None:
    return os.environ.get(ENV_WEBHOOK, "").strip() or server_alerts.webhook()


def message(c: dict, follow_name: str) -> str:
    year = c["date"][:4] if c["date"][:4].isdigit() else ""
    what = "show " if c.get("media") == "tv" else ""
    return f"Joey Media: added {what}{c['title']}{f' ({year})' if year else ''} — {c['reason']} · following {follow_name}"


def _notify(c: dict, follow_name: str) -> None:
    url = webhook()
    if url:
        server_alerts.post(url, message(c, follow_name))  # never raises; status / type only


# ---- the check ----

def _titles_for(f: dict) -> list[dict] | None:
    if f["kind"] == "person":
        body = md._get(f"/api/v1/person/{f['tmdb_id']}/combined_credits")
        return person_titles(body, shows=f.get("dept") == CREATOR) if isinstance(body, dict) else None
    body = md._get(f"/api/v1/collection/{f['tmdb_id']}")
    return collection_films(body) if isinstance(body, dict) else None


def run_once(only: int | None = None, cap: int = MAX_PER_RUN) -> dict:
    """One idempotent pass over every follow (or just follow id `only`). -> counts; never raises. Followed shows
    need Sonarr only (_keep_shows); people and series need Jellyseerr."""
    counts = {"follows": 0, "requested": 0, "already": 0, "failed": 0, "deferred": 0, "shows_set": 0}
    if not _lock.acquire(blocking=False):
        counts["busy"] = True
        return counts
    try:
        with closing(ensure()) as db:
            rows = [dict(r) for r in db.execute("SELECT * FROM media_follows ORDER BY id")
                    if only is None or r["id"] == only]
            shows = [f for f in rows if f["kind"] == "show"]
            counts["follows"] += len(shows)
            counts["shows_set"] = _keep_shows(shows)
            if md._creds() is None:
                counts["skipped_no_keys"] = True
                return counts
            for f in rows:
                if f["kind"] == "show":
                    continue
                counts["follows"] += 1
                titles = _titles_for(f)
                if titles is None:
                    log.warning("follow check: credits unavailable for one follow")
                    continue
                closed = _closed(db, f["id"])
                for c in sorted(titles, key=lambda c: (c["date"] or "9999", c["tmdb_id"])):
                    if (c["media"], c["tmdb_id"]) in closed or not qualifies(c["date"]):
                        continue
                    if f["kind"] == "person" and c["media"] == "movie" and not _top_billed(c, f["tmdb_id"]):
                        continue
                    if isinstance(c["status"], int) and c["status"] >= 2:   # requested / available / blocked in Jellyseerr
                        word = md.status_word(c["status"])
                        _record(db, f["id"], c, "already", word if word != "Not in library" else "In Seerr")
                        counts["already"] += 1
                        continue
                    if counts["requested"] + counts["failed"] >= cap:
                        counts["deferred"] += 1
                        continue
                    code = md._send(c["media"], c["tmdb_id"], "all" if c["media"] == "tv" else [])
                    if code is None:
                        md._cache.pop(f"film:/api/v1/{c['media']}/{c['tmdb_id']}", None)
                        _record(db, f["id"], c, "requested", None)
                        counts["requested"] += 1
                        _notify(c, f["name"])
                    elif code == "exists":
                        _record(db, f["id"], c, "already", md.ERRORS[code])
                        counts["already"] += 1
                    else:
                        _record(db, f["id"], c, "failed", md.ERRORS[code])
                        counts["failed"] += 1
    except (sqlite3.Error, OSError) as exc:
        log.warning("follow check failed: %s", type(exc).__name__)
    finally:
        _lock.release()
    if counts["deferred"]:
        log.info("follow check: %s deferred to the next run", counts["deferred"])
    log.info("follow check: %(follows)s follows, %(requested)s requested, %(already)s already, %(failed)s failed", counts)
    return counts


# ---- shows (F5, 2026-10-12): Sonarr keeps a followed show monitored, new seasons included ----
# B.: "follow … the show, so I can auto-request future seasons once announced". Follow = Sonarr's own series resource
# PUT back with `monitored: true, monitorNewItems: "all"` (every other field kept, no search, seasons untouched); a show
# Sonarr doesn't have yet is requested first through the "All seasons + future" path (Jellyseerr `seasons: "all"`, then
# media_arr_search.follow_all). Unfollow = the same PUT with `monitorNewItems: "none"` only. Nothing is ever deleted.
# The page's Follow state is a media.db read; Sonarr is called only on the POSTs and by the 6-hourly check.

_why = media_text.why
SONARR_NOTE = {"set": ("Sonarr: monitored, new seasons too", True),
               "reqfail": ("Not in Sonarr, and Seerr didn't take the request — use Request", False),
               "unset": ("Sonarr is not connected — new seasons are not set to follow", False),
               "failed": ("Couldn't set Sonarr to follow new seasons", False),
               "stopped": ("Sonarr: new seasons are no longer added · what you have stays", True),
               "missing": ("Not in Sonarr — nothing to change there", True),
               "stopfail": ("Couldn't tell Sonarr to stop adding new seasons", False)}


def sonarr_note(code) -> dict | None:
    """{text, ok} for a `?sonarr=<code>` flash; `req-<code>` = requested, then media_arr_search.FUTURE's line."""
    code = str(code or "")
    req = code.startswith("req-")
    hit = media_arr_search.FUTURE.get(code[4:]) if req else SONARR_NOTE.get(code)
    return {"text": ("Requested every season · " if req else "") + hit[0], "ok": hit[1]} if hit else None


def _sonarr_put(entry: dict, **fields) -> None:
    """PUT the series back as Sonarr's own resource with `fields` changed (every other field kept)."""
    base, headers = mr._arr_creds("sonarr")
    media_arr_search._ok(requests.put(f"{base}/api/v3/series/{int(entry['id'])}", json={**entry, **fields},
                                      headers=headers, timeout=media_arr_search.TIMEOUT))


def keep_show(tmdb_id: int) -> str:
    """Follow show: Sonarr monitors it with every new season. -> a SONARR_NOTE code ("req-…" when it was requested)."""
    if mr._arr_creds("sonarr") is None:
        return "unset"
    entry = media_arr_search.find("tv", tmdb_id)
    if entry is not None:
        try:
            _sonarr_put(entry, monitored=True, monitorNewItems="all")
            return "set"
        except Exception as exc:
            log.warning("sonarr follow-show failed: %s", _why(exc))
            return "failed"
    code = md._send("tv", tmdb_id, "all")        # not in Sonarr: the "All seasons + future" request
    if code not in (None, "exists"):
        return "reqfail"
    md._cache.pop(f"film:/api/v1/tv/{tmdb_id}", None)
    return "req-" + media_arr_search.follow_all(tmdb_id)


def _keep_shows(rows: list[dict]) -> int:
    """The 6-hourly check for followed shows: one Sonarr series-list read, then the follow PUT for any followed show
    Sonarr has that isn't monitored with new seasons (it arrived after the Follow, or was changed by hand). -> PUTs."""
    creds = mr._arr_creds("sonarr")
    if not rows or creds is None:
        return 0
    base, headers = creds
    try:
        resp = requests.get(f"{base}/api/v3/series", headers=headers, timeout=media_arr_search.TIMEOUT)
        media_arr_search._ok(resp)
        body = resp.json()
    except Exception as exc:
        log.warning("follow check: sonarr list failed: %s", _why(exc))
        return 0
    series = {s.get("tmdbId"): s for s in body if isinstance(s, dict) and s.get("id")} if isinstance(body, list) else {}
    done = 0
    for f in rows:
        entry = series.get(f["tmdb_id"])
        if entry is None or (entry.get("monitored") is True and entry.get("monitorNewItems") == "all"):
            continue
        try:
            _sonarr_put(entry, monitored=True, monitorNewItems="all")
            done += 1
        except Exception as exc:
            log.warning("follow check: sonarr follow-show failed: %s", _why(exc))
    return done


def stop_show(tmdb_id: int) -> str:
    """Unfollow show: Sonarr stops adding new seasons (`monitorNewItems: "none"`); monitored and files stay."""
    if mr._arr_creds("sonarr") is None:
        return "unset"
    entry = media_arr_search.find("tv", tmdb_id)
    if entry is None:
        return "missing"
    try:
        _sonarr_put(entry, monitorNewItems="none")
        return "stopped"
    except Exception as exc:
        log.warning("sonarr unfollow-show failed: %s", _why(exc))
        return "stopfail"


# ---- routes: Follow / Unfollow (instant, reversible, behind same_origin) and the Following tab ----
router = APIRouter()
FOLLOWING = "/media/following"
FLASH = {"on": "Following — new films are requested automatically", "off": "Unfollowed",
         "show": "Following — new seasons are added automatically",
         "creator": "Following — their new films and shows are requested automatically"}
flash_keys("follow", "sonarr")
KIND_WORDS = {"Directing": "Director"}
NEEDS_SEERR = "Follow needs Seerr"
EMPTY = "Follow an actor, director, creator, film series or show from their page."


def _kind_of(kind: str) -> str:
    if kind not in KINDS:
        raise HTTPException(404, "Nothing to follow")
    return kind


def _back(value: str, default: str) -> str:
    """Only a local /media/ path is a redirect target (media_write.safe_back); its query is kept for _flashed."""
    return safe_back(value, default, keep_query=True, prefixes=("/media/",), exact=())


def _flashed(url: str, word: str, sonarr: str | None = None) -> str:
    base = url.split("#", 1)[0]
    return base + ("&" if "?" in base else "?") + f"follow={word}" + (f"&sonarr={sonarr}" if sonarr else "")


def _describe(kind: str, tmdb_id: int) -> dict:
    """{name, poster, dept, first} from Jellyseerr (cached reads); empty when unavailable. `first` is a film of
    the series (its page is the series' page in Joey — there is no collection page)."""
    if md._creds() is None:
        return {}
    if kind == "person":
        body = md.meta_get(f"/api/v1/person/{tmdb_id}")
        if isinstance(body, dict):
            return {"name": str(body.get("name") or "")[:120] or None, "poster": md._ref(body.get("profilePath")),
                    "dept": str(body.get("knownForDepartment") or "")[:40] or None}
        return {}
    from hub.media_film import _cget
    if kind == "show":   # the show page's own cached body
        body = _cget(f"/api/v1/tv/{tmdb_id}")
        return ({"name": str(body.get("name") or "")[:120] or None, "poster": md._ref(body.get("posterPath"))}
                if isinstance(body, dict) else {})
    body = _cget(f"/api/v1/collection/{tmdb_id}")
    if not isinstance(body, dict):
        return {}
    films = sorted(collection_films(body), key=lambda c: (c["date"] or "9999", c["tmdb_id"]))
    return {"name": str(body.get("name") or "")[:120] or None, "poster": md._ref(body.get("posterPath")),
            "first": films[0]["tmdb_id"] if films else None}


def page_href(kind: str, tmdb_id: int, link: str | None = None) -> str:
    if kind == "person":
        return f"/media/person/{tmdb_id}"
    if link and _back(link, ""):
        return link
    return f"/media/title/tv/{tmdb_id}" if kind == "show" else FOLLOWING


def kind_word(f: dict) -> str:
    if f["kind"] == "collection":
        return "Film series"
    if f["kind"] == "show":
        return "Show · future seasons"
    if f.get("dept") == CREATOR:
        return "Creator · films + shows"
    return KIND_WORDS.get(f.get("dept") or "", "Actor · top-5 billed")


@router.post("/media/follow/{kind}/{tmdb_id}", dependencies=[Depends(same_origin)])
async def follow_route(request: Request, kind: str, tmdb_id: int):
    kind = _kind_of(kind)
    if tmdb_id <= 0:
        raise HTTPException(404, "Nothing to follow")
    form = await form_of(request)
    if kind == "show":   # Sonarr / Jellyseerr writes: off the loop too
        return await run_in_threadpool(_follow_show, tmdb_id, form)
    return await run_in_threadpool(_follow, kind, tmdb_id, form)   # M-40: Jellyseerr read off the loop


def _follow_show(tmdb_id: int, form: dict):
    got = _describe("show", tmdb_id)
    name = got.get("name") or " ".join(str(form.get("name") or "").split())[:120] or "Show"
    back = _back(form.get("back"), "")
    page = back.split("?", 1)[0]
    link = page if page.startswith(("/media/title/tv/", "/media/item/")) else f"/media/title/tv/{tmdb_id}"
    try:
        follow("show", tmdb_id, name, got.get("poster"), link=link)
    except (sqlite3.Error, OSError) as exc:
        log.warning("follow not saved: %s", type(exc).__name__)
        raise HTTPException(503, "Couldn't save the follow") from None
    return RedirectResponse(_flashed(back or link, "show", keep_show(tmdb_id)), status_code=303)


def _follow(kind: str, tmdb_id: int, form: dict):
    got = _describe(kind, tmdb_id)
    fallback = " ".join(str(form.get("name") or "").split())[:120]
    name = got.get("name") or fallback or ("Person" if kind == "person" else "Film series")
    back = _back(form.get("back"), "")
    link = None
    if kind == "collection":
        link = (back if back.startswith(("/media/title/movie/", "/media/item/")) else
                f"/media/title/movie/{got['first']}" if got.get("first") else None)
    tv = kind == "person" and form.get("tv") == "1"   # followed as a TV maker: new shows too
    try:
        fid = follow(kind, tmdb_id, name, got.get("poster"), CREATOR if tv else got.get("dept"), link=link)
    except (sqlite3.Error, OSError) as exc:
        log.warning("follow not saved: %s", type(exc).__name__)
        raise HTTPException(503, "Couldn't save the follow") from None
    back = back or page_href(kind, tmdb_id, link)
    task = BackgroundTask(run_once, only=fid) if md._creds() else None   # B. sees results quickly
    return RedirectResponse(_flashed(back, "creator" if tv else "on"), status_code=303, background=task)


@router.post("/media/follow/{kind}/{tmdb_id}/unfollow", dependencies=[Depends(same_origin)])
async def unfollow_route(request: Request, kind: str, tmdb_id: int):
    kind = _kind_of(kind)
    form = await form_of(request)
    try:
        await run_in_threadpool(unfollow, kind, tmdb_id)
    except (sqlite3.Error, OSError) as exc:
        log.warning("unfollow not saved: %s", type(exc).__name__)
        raise HTTPException(503, "Couldn't save the change") from None
    sonarr = await run_in_threadpool(stop_show, tmdb_id) if kind == "show" else None
    return RedirectResponse(_flashed(_back(form.get("back"), FOLLOWING), "off", sonarr), status_code=303)


_year = media_text.year


def _add_href(a: dict) -> str:
    return f"/media/title/{'tv' if a.get('media') == 'tv' else 'movie'}/{a['tmdb_id']}"


def _added_words(f: dict) -> str:
    """'3 added', or for a TV maker '2 films · 1 show' (requested / already)."""
    if f.get("dept") != CREATOR:
        return f"{f['added']} added"
    films, shows = f.get("added_films") or 0, f.get("added_shows") or 0
    return f"{films} film{'s' if films != 1 else ''} · {shows} show{'s' if shows != 1 else ''}"


def following_ctx(request: Request | None = None) -> dict:
    """People and film series (one group), followed shows (their own group, each with Unfollow), the latest adds."""
    rows = [{**f, "href": page_href(f["kind"], f["tmdb_id"], f.get("link")), "kind_word": kind_word(f),
             "since": md._date_words(f["followed_at"])[0], "added_words": _added_words(f)} for f in follows()]
    params = request.query_params if request is not None else {}
    adds = [{**a, "year": _year(a["release_date"]), "href": _add_href(a),
             "when": md._date_words(a["at"])[0], "word": {"requested": "Requested", "already": "Already there",
                                                          "failed": "Failed"}.get(a["outcome"], a["outcome"])}
            for a in recent_adds(20)]
    return {"follows": [f for f in rows if f["kind"] != "show"], "shows": [f for f in rows if f["kind"] == "show"],
            "adds": adds, "needs": NEEDS_SEERR if md._creds() is None else None, "empty": EMPTY,
            "sonarr_note": sonarr_note(params.get("sonarr"))}


@router.get(FOLLOWING, response_class=HTMLResponse)
def following_page(request: Request):
    return md._page(request, "media_following.html", lambda: following_ctx(request))


def flash_text(request: Request) -> str | None:
    return FLASH.get(request.query_params.get("follow") or "")


def home_items(limit: int = 12) -> list[dict] | None:
    """The Media home shelf: None when nothing is followed, else the newest requested / already adds."""
    if not any_follows():
        return None
    return [{"title": a["title"], "poster": a["poster"], "item_key": f"tmdb:{a['tmdb_id']}",
             "sub": " · ".join(str(x) for x in (_year(a["release_date"]), a["follow_name"]) if x),
             "href": _add_href(a)} for a in recent_adds(limit, KEEP)]


def show_ctx(request, film) -> dict | None:
    """What `_follow_show.html` draws on a show page (not an episode): the Follow state from media.db (never an
    upstream call — F2) and the flash. Pages call it as the `follow_show(request, film)` global."""
    tmdb = film.get("tmdb") if isinstance(film, dict) else None
    if not isinstance(tmdb, int) or tmdb <= 0 or film.get("kind") != "tv" or film.get("episode"):
        return None
    try:
        on = get("show", tmdb) is not None
    except Exception as exc:  # the page never fails on the follow lookup
        log.warning("follow lookup failed: %s", type(exc).__name__)
        on = False
    params = request.query_params if request is not None else {}
    word = params.get("follow") or ""
    return {"tmdb": tmdb, "following": on, "name": film.get("title") or "",
            "back": film.get("back") or f"/media/title/tv/{tmdb}",
            "flash": FLASH.get(word) if word in ("show", "off", "creator") else None,
            "note": sonarr_note(params.get("sonarr"))}


shell.templates.env.globals["follow_show"] = show_ctx
shell.templates.env.globals["followed"] = followed   # the show page's "Created by" Follow buttons (one read)
