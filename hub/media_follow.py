"""Follow (2026-10-07): follow a person (actor / director) or a film series (TMDB collection) and have their NEW
films requested through Jellyseerr automatically. Films only — TV credits are ignored everywhere.

Rules (B., 2026-10-07):
  * actor  -> a film where they are top-5 billed (cast `order` 0-4);
  * director -> any film where their crew job is "Director" (any billing); a person who does both: either rule;
  * series -> any film in the collection's `parts`;
  * future only (tightened by B., 2026-10-08): a film qualifies only when it has a KNOWN release date that is
    strictly after today. Unknown / "TBA" dates never qualify (untitled projects in development stay out until
    TMDB gives them a date — the 6-hourly check picks them up then). Nothing already released is ever added.
A film recorded in media_follow_adds as requested / already is never requested again by that follow (so a film
deleted in Radarr is not re-added); a failed request is retried next run.

The check reads Jellyseerr live (person combined_credits / collection) and requests through the SAME call the
Discover Request button uses (media_discover._send). At most MAX_PER_RUN requests a run; the rest wait for the
next run. Runs right after a Follow (a response background task) and on the hub's own loop (first ~2 min after
start, then every 6 h). MEDIA_FOLLOW=off disables the loop. No Jellyseerr keys -> no calls at all.
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

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.background import BackgroundTask

from hub import media_db, media_discover as md, server_alerts
from hub.media_write import form_of, same_origin

log = logging.getLogger("hub.media_follow")

KINDS = ("person", "collection")
MAX_PER_RUN = 10
FIRST_DELAY_S = 120
EVERY_S = 6 * 3600
TOP_BILLED = 5
REASONS = {"cast": "top-5 cast", "director": "director", "collection": "collection"}
KEEP = ("requested", "already")   # outcomes that close a title for its follow; "failed" retries next run
ENV_WEBHOOK = "MEDIA_DISCORD_WEBHOOK"

DDL = (
    """CREATE TABLE IF NOT EXISTS media_follows(
  id INTEGER PRIMARY KEY, kind TEXT CHECK(kind IN ('person','collection')), tmdb_id INTEGER, name TEXT,
  followed_at TEXT, poster TEXT, dept TEXT, link TEXT, UNIQUE(kind, tmdb_id))""",
    """CREATE TABLE IF NOT EXISTS media_follow_adds(
  follow_id INTEGER, tmdb_id INTEGER, title TEXT, release_date TEXT, reason TEXT, outcome TEXT, note TEXT,
  at TEXT, poster TEXT, PRIMARY KEY(follow_id, tmdb_id))""",
)

_lock = threading.Lock()  # the after-Follow run and the loop never overlap


def disabled() -> bool:
    return os.environ.get("MEDIA_FOLLOW", "on").strip().lower() in ("off", "0", "false", "no")


# ---- storage ----

def ensure() -> sqlite3.Connection:
    db = media_db.connect()
    for ddl in DDL:
        db.execute(ddl)
    db.commit()
    return db


def _reader():
    return ensure() if media_db.db_path().is_file() else None


def follow(kind: str, tmdb_id: int, name: str, poster: str | None = None, dept: str | None = None,
           today: date | None = None, link: str | None = None) -> int:
    """Follow (idempotent: a second Follow keeps the first date). -> the follow id."""
    with closing(ensure()) as db:
        db.execute("INSERT OR IGNORE INTO media_follows(kind, tmdb_id, name, followed_at, poster, dept, link) "
                   "VALUES(?,?,?,?,?,?,?)", (kind, int(tmdb_id), name[:120], (today or date.today()).isoformat(),
                                            poster, (dept or "")[:40], link))
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


def follows() -> list[dict]:
    """Every follow, newest first, with its `added` count (requested / already)."""
    db = _reader()
    if db is None:
        return []
    with closing(db):
        return [dict(r) for r in db.execute(
            "SELECT f.*, (SELECT COUNT(*) FROM media_follow_adds a WHERE a.follow_id = f.id "
            "AND a.outcome IN ('requested','already')) AS added FROM media_follows f ORDER BY f.followed_at DESC, f.id DESC")]


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


def _closed(db, follow_id: int) -> set[int]:
    return {r["tmdb_id"] for r in db.execute(
        "SELECT tmdb_id FROM media_follow_adds WHERE follow_id = ? AND outcome IN ('requested','already')", (follow_id,))}


def _record(db, follow_id: int, c: dict, outcome: str, note: str | None) -> None:
    with db:
        db.execute("INSERT INTO media_follow_adds(follow_id, tmdb_id, title, release_date, reason, outcome, note, at, poster) "
                   "VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(follow_id, tmdb_id) DO UPDATE SET outcome = excluded.outcome, "
                   "note = excluded.note, at = excluded.at",
                   (follow_id, c["tmdb_id"], c["title"], c["date"], c["reason"], outcome, note,
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


def _cand(c: dict, reason: str) -> dict | None:
    try:
        tmdb_id = int(c.get("id"))
    except (TypeError, ValueError):
        return None
    if tmdb_id <= 0:
        return None
    info = c.get("mediaInfo")
    return {"tmdb_id": tmdb_id, "title": str(c.get("title") or c.get("name") or "Untitled")[:200],
            "date": _date(c.get("releaseDate")), "reason": reason, "poster": md._ref(c.get("posterPath")),
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
    return f"Joey Media: added {c['title']}{f' ({year})' if year else ''} — {c['reason']} · following {follow_name}"


def _notify(c: dict, follow_name: str) -> None:
    url = webhook()
    if url:
        server_alerts.post(url, message(c, follow_name))  # never raises; status / type only


# ---- the check ----

def _films_for(f: dict) -> list[dict] | None:
    if f["kind"] == "person":
        body = md._get(f"/api/v1/person/{f['tmdb_id']}/combined_credits")
        return person_films(body) if isinstance(body, dict) else None
    body = md._get(f"/api/v1/collection/{f['tmdb_id']}")
    return collection_films(body) if isinstance(body, dict) else None


def run_once(only: int | None = None, cap: int = MAX_PER_RUN) -> dict:
    """One idempotent pass over every follow (or just follow id `only`). -> counts; never raises."""
    counts = {"follows": 0, "requested": 0, "already": 0, "failed": 0, "deferred": 0}
    if md._creds() is None:
        counts["skipped_no_keys"] = True
        return counts
    if not _lock.acquire(blocking=False):
        counts["busy"] = True
        return counts
    try:
        with closing(ensure()) as db:
            rows = [dict(r) for r in db.execute("SELECT * FROM media_follows ORDER BY id")]
            for f in rows:
                if only is not None and f["id"] != only:
                    continue
                counts["follows"] += 1
                films = _films_for(f)
                if films is None:
                    log.warning("follow check: credits unavailable for one follow")
                    continue
                closed = _closed(db, f["id"])
                for c in sorted(films, key=lambda c: (c["date"] or "9999", c["tmdb_id"])):
                    if c["tmdb_id"] in closed or not qualifies(c["date"]):
                        continue
                    if f["kind"] == "person" and not _top_billed(c, f["tmdb_id"]):
                        continue
                    if isinstance(c["status"], int) and c["status"] >= 2:   # requested / available / blocked in Jellyseerr
                        word = md.status_word(c["status"])
                        _record(db, f["id"], c, "already", word if word != "Not in library" else "In Jellyseerr")
                        counts["already"] += 1
                        continue
                    if counts["requested"] + counts["failed"] >= cap:
                        counts["deferred"] += 1
                        continue
                    code = md._send("movie", c["tmdb_id"], [])
                    if code is None:
                        md._cache.pop(f"film:/api/v1/movie/{c['tmdb_id']}", None)
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


# ---- routes: Follow / Unfollow (instant, reversible, behind same_origin) and the Following tab ----
router = APIRouter()
FOLLOWING = "/media/following"
FLASH = {"on": "Following — new films are requested automatically", "off": "Unfollowed"}
KIND_WORDS = {"Directing": "Director"}
NEEDS_SEERR = "Follow needs Jellyseerr"
EMPTY = "Follow an actor, director or film series from their page."


def _kind_of(kind: str) -> str:
    if kind not in KINDS:
        raise HTTPException(404, "Nothing to follow")
    return kind


def _back(value: str, default: str) -> str:
    """Only a local /media/ path (no scheme, no //) is a redirect target."""
    v = str(value or "")
    return v if v.startswith("/media/") and "//" not in v and "\\" not in v and len(v) < 300 else default


def _flashed(url: str, word: str) -> str:
    base = url.split("#", 1)[0]
    return base + ("&" if "?" in base else "?") + f"follow={word}"


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
    body = _cget(f"/api/v1/collection/{tmdb_id}")
    if not isinstance(body, dict):
        return {}
    films = sorted(collection_films(body), key=lambda c: (c["date"] or "9999", c["tmdb_id"]))
    return {"name": str(body.get("name") or "")[:120] or None, "poster": md._ref(body.get("posterPath")),
            "first": films[0]["tmdb_id"] if films else None}


def page_href(kind: str, tmdb_id: int, link: str | None = None) -> str:
    if kind == "person":
        return f"/media/person/{tmdb_id}"
    return link if link and _back(link, "") else FOLLOWING


def kind_word(f: dict) -> str:
    if f["kind"] == "collection":
        return "Film series"
    return KIND_WORDS.get(f.get("dept") or "", "Actor · top-5 billed")


@router.post("/media/follow/{kind}/{tmdb_id}", dependencies=[Depends(same_origin)])
async def follow_route(request: Request, kind: str, tmdb_id: int):
    kind = _kind_of(kind)
    if tmdb_id <= 0:
        raise HTTPException(404, "Nothing to follow")
    form = await form_of(request)
    got = _describe(kind, tmdb_id)
    fallback = " ".join(str(form.get("name") or "").split())[:120]
    name = got.get("name") or fallback or ("Person" if kind == "person" else "Film series")
    back = _back(form.get("back"), "")
    link = None
    if kind == "collection":
        link = (back if back.startswith(("/media/title/movie/", "/media/item/")) else
                f"/media/title/movie/{got['first']}" if got.get("first") else None)
    try:
        fid = follow(kind, tmdb_id, name, got.get("poster"), got.get("dept"), link=link)
    except (sqlite3.Error, OSError) as exc:
        log.warning("follow not saved: %s", type(exc).__name__)
        raise HTTPException(503, "Couldn't save the follow") from None
    back = back or page_href(kind, tmdb_id, link)
    task = BackgroundTask(run_once, only=fid) if md._creds() else None   # B. sees results quickly
    return RedirectResponse(_flashed(back, "on"), status_code=303, background=task)


@router.post("/media/follow/{kind}/{tmdb_id}/unfollow", dependencies=[Depends(same_origin)])
async def unfollow_route(request: Request, kind: str, tmdb_id: int):
    kind = _kind_of(kind)
    form = await form_of(request)
    try:
        unfollow(kind, tmdb_id)
    except (sqlite3.Error, OSError) as exc:
        log.warning("unfollow not saved: %s", type(exc).__name__)
        raise HTTPException(503, "Couldn't save the change") from None
    return RedirectResponse(_flashed(_back(form.get("back"), FOLLOWING), "off"), status_code=303)


def _year(value) -> int | None:
    text = str(value or "")[:4]
    return int(text) if text.isdigit() else None


def following_ctx() -> dict:
    rows = [{**f, "href": page_href(f["kind"], f["tmdb_id"], f.get("link")), "kind_word": kind_word(f),
             "since": md._date_words(f["followed_at"])[0]} for f in follows()]
    adds = [{**a, "year": _year(a["release_date"]), "href": f"/media/title/movie/{a['tmdb_id']}",
             "when": md._date_words(a["at"])[0], "word": {"requested": "Requested", "already": "Already there",
                                                          "failed": "Failed"}.get(a["outcome"], a["outcome"])}
            for a in recent_adds(20)]
    return {"follows": rows, "adds": adds, "needs": NEEDS_SEERR if md._creds() is None else None, "empty": EMPTY}


@router.get(FOLLOWING, response_class=HTMLResponse)
def following_page(request: Request):
    return md._page(request, "media_following.html", following_ctx)


def flash_text(request: Request) -> str | None:
    return FLASH.get(request.query_params.get("follow") or "")


def home_items(limit: int = 12) -> list[dict] | None:
    """The Media home shelf: None when nothing is followed, else the newest requested / already adds."""
    if not any_follows():
        return None
    return [{"title": a["title"], "poster": a["poster"], "item_key": f"tmdb:{a['tmdb_id']}",
             "sub": " · ".join(str(x) for x in (_year(a["release_date"]), a["follow_name"]) if x),
             "href": f"/media/title/movie/{a['tmdb_id']}"} for a in recent_adds(limit, KEEP)]
