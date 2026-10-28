"""JY-260: pick each title's TMDB poster, render the Joey poster into the local store, serve it, and (phase 2, behind
B.'s own key) write it back to Jellyfin. Spec docs/specs/JY-260-posters.md.

* `POSTERS=off|dry|on` (default dry since phase 2). `dry`: the background loop (hub/tasks.py) renders every film,
  series and real season into the store (hub/media_posters_store.py) and /img serves it from there. `on`: the same,
  plus the Jellyfin write-back (hub/media_posters_write.py), which runs only while B.'s poster write key is set.
* Phase 2 (B. 2026-10-28, "a full replacement of all"): no approval wait. POSTERS_AUTO_MIN_RATING stays as a lever,
  default 0 = every poster; a pick under a set threshold is rendered but neither served nor written.
* The pick (Q3A): Jellyfin's own RemoteImages list for the item (its bundled TMDB key, no new secret). Text-less
  (no language) first, then English, then anything else; within each, more votes, then more pixels. Art is fetched
  only from image.tmdb.org, capped at 5 MB like /img.
* The backfill (Q9A): recently added first, then A-Z, POSTERS_PER_PASS a pass, a pass every TICK_S while work is
  left (hourly once done). Progress lives in media.db (`poster`, `poster_progress`), so a restart resumes where it
  stopped: an item whose version is already stored is passed over with no network call. The memory gate skips a pass
  under MIN_AVAILABLE_MB. New titles arrive through the jellyfin snapshot like any other.
* The review page (hub/media_posters_pages.py) reads only local files and media.db: no network on render.
Logs carry counts and exception types only, never a URL, key or name.
"""

from __future__ import annotations

import hashlib
import logging
import os
import sqlite3
import threading
import time
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

from hub import images, media_item, media_jellyfin, media_store, upstream
from hub import media_posters_render as render
from hub import media_posters_store as store

log = logging.getLogger("hub.media_posters")

MODES = ("off", "dry", "on")
DEFAULT_MODE = "dry"   # phase 2 (2026-10-28): render into the store and serve from it; write-back needs its own key
FIRST_DELAY_S = 180
TICK_S = 300          # a pass every 5 min while the backfill has work left ...
EVERY_S = 3600        # ... and hourly once it is through (new titles, template changes, drift)
PER_PASS = 30
PAUSE_S = 2.0
TMDB_ART = "https://image.tmdb.org/t/p/"
DEFAULT_TEMPLATE_DIR = "/data/posters/template"
AUTO_MIN_RATING = 0.0   # phase 2: every poster (B. 2026-10-28); the 6.0 rule of phase 1 is superseded
SEASONS_TTL_S = 24 * 3600   # a series' season list is re-read at most daily
BACKDROPS_TTL_S = 30 * 24 * 3600   # JY-262 follow-up: a title's ranked backdrops are re-read at most monthly
MIN_AVAILABLE_MB = 1300   # a pass is skipped below this (the NAS floor is 1,200 MB; renders cost ~13 MB each)
MEMORY_STALE_MIN = 15
FAILS_BEFORE_BACKOFF = 3   # an item failing this many times in a row (render or write) ...
BACKOFF_S = 24 * 3600      # ... is passed over this long, so it cannot hold the pass limit (review 2026-10-28)
_tick = {"at": 0.0, "more": True}

DDL = (
    """CREATE TABLE IF NOT EXISTS poster(
        jf_id TEXT PRIMARY KEY, kind TEXT NOT NULL, title TEXT, ver TEXT, template TEXT, status TEXT NOT NULL,
        reverted INTEGER NOT NULL DEFAULT 0, bytes INTEGER, rendered_at TEXT,
        orig_ext TEXT, orig_tag TEXT, wrote INTEGER NOT NULL DEFAULT 0, pending_ver TEXT, live_ver TEXT, live_tag TEXT,
        locked_by_us INTEGER NOT NULL DEFAULT 0, manual INTEGER NOT NULL DEFAULT 0,
        fails INTEGER NOT NULL DEFAULT 0, retry_at TEXT, lock_owner TEXT, lock_until TEXT,
        written_at TEXT, checked_at TEXT, last_error TEXT)""",
    "CREATE TABLE IF NOT EXISTS poster_progress(key TEXT PRIMARY KEY, value TEXT NOT NULL)",
)
# columns added after the table's first shape (94b3c34): an older file gains them on first use (verifier note 6)
ADDED_COLUMNS = {"title": "TEXT", "wrote": "INTEGER NOT NULL DEFAULT 0", "pending_ver": "TEXT",
                 "manual": "INTEGER NOT NULL DEFAULT 0", "fails": "INTEGER NOT NULL DEFAULT 0", "retry_at": "TEXT",
                 "lock_owner": "TEXT", "lock_until": "TEXT"}
LOCK_TTL_S = 300   # an item lock older than this is stale (a crashed holder); one write is at most ~6 x 20 s calls
CLAIM_TRIES, CLAIM_RETRY_S = 3, 0.2   # a "database is locked" claim is retried, then the item counts as busy
_ddl_done: set[str] = set()
_ddl_lock = threading.Lock()


def mode() -> str:
    v = os.environ.get("POSTERS", "").strip().lower()
    return v if v in MODES else DEFAULT_MODE


def disabled() -> bool:
    return mode() == "off"


def _int_env(name: str, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(os.environ.get(name, "").strip())))
    except ValueError:
        return default


def per_pass() -> int:
    return _int_env("POSTERS_PER_PASS", PER_PASS, 1, 500)


def auto_min_rating() -> float:
    """POSTERS_AUTO_MIN_RATING (default 0 = every poster, B. 2026-10-28). Above 0, a pick whose TMDB rating is under
    it (or unrated) is rendered for the review page but not served or written."""
    try:
        return max(0.0, min(10.0, float(os.environ.get("POSTERS_AUTO_MIN_RATING", "").strip())))
    except ValueError:
        return AUTO_MIN_RATING


def auto_approves(chosen: dict | None) -> bool:
    floor = auto_min_rating()
    if floor <= 0:
        return True
    rating = (chosen or {}).get("rating")
    return isinstance(rating, (int, float)) and not isinstance(rating, bool) and rating >= floor


def out_dir() -> Path:
    return store.out_dir()


def template_dir() -> Path:
    """B.'s kit (POSTERS_TEMPLATE_DIR, the NAS folder mounted read-only), else the starter kit in the image."""
    folder = Path(os.environ.get("POSTERS_TEMPLATE_DIR", "").strip() or DEFAULT_TEMPLATE_DIR)
    return folder if (folder / "template.json").is_file() else render.STARTER


def template_state() -> tuple[render.Template | None, list[str], bool]:
    """(template, problems, is_starter). Local files only. B.'s kit when it is good; when it is refused, the starter
    kit with B.'s kit's problems (the review page shows them). None only if the starter kit itself were refused."""
    folder = template_dir()
    try:
        return render.load_template(folder), [], folder == render.STARTER
    except render.TemplateError as exc:
        problems = exc.problems
    try:
        return render.load_template(render.STARTER), problems, True
    except render.TemplateError as exc:
        return None, problems + exc.problems, True


def memory_mb(snaps) -> float | None:
    """NAS available memory in MB from the `system` snapshot (the connector's /proc/meminfo MemAvailable, as the
    Server area reads it), or None when there is no fresh reading."""
    snap = (snaps or {}).get("system")
    if snap is None or (getattr(snap, "age_minutes", 0) or 0) > MEMORY_STALE_MIN:
        return None
    data = getattr(snap, "data", snap)
    free = data.get("ram_free_gb") if isinstance(data, dict) else None
    if isinstance(free, bool) or not isinstance(free, (int, float)):
        return None
    return float(free) * 1024


# ---- the pick ----

def _lang_rank(lang) -> int:
    lang = (lang or "").strip().lower() if isinstance(lang, str) or lang is None else "?"
    return 0 if not lang else (1 if lang == "en" else 2)


def ranked_posters(remote) -> list[dict]:
    """Every usable TMDB poster in pick() order (text-less, English, other; then votes, then pixels), each URL once."""
    rows, seen = [], set()
    rest = list(remote) if isinstance(remote, list) else []
    while True:
        best = pick([im for im in rest if isinstance(im, dict) and im.get("Url") not in seen])
        if best is None:
            return rows
        seen.add(best["url"])
        rows.append(best)


def pick(remote) -> dict | None:
    """The poster to use from a RemoteImages `Images` list, or None.
    -> {url, lang, votes, rating (TMDB 0-10 or None), width, height, fallback}."""
    best, best_key = None, None
    for im in remote if isinstance(remote, list) else []:
        if not isinstance(im, dict):
            continue
        url = im.get("Url")
        if not isinstance(url, str) or not url.startswith(TMDB_ART):
            continue
        votes = im.get("VoteCount") if isinstance(im.get("VoteCount"), int) else 0
        rating = im.get("CommunityRating")
        rating = float(rating) if isinstance(rating, (int, float)) and not isinstance(rating, bool) else None
        w = im.get("Width") if isinstance(im.get("Width"), int) else 0
        h = im.get("Height") if isinstance(im.get("Height"), int) else 0
        key = (_lang_rank(im.get("Language")), -votes, -(w * h))
        if best_key is None or key < best_key:
            lang = im.get("Language") or None
            best, best_key = {"url": url, "lang": lang, "votes": votes, "rating": rating, "width": w, "height": h,
                              "fallback": (None, "en", "other")[key[0]]}, key
    return best


def remote_backdrops(jf_id: str) -> list:
    """The item's TMDB backdrop list through Jellyfin (GET only), the same request form as the posters
    (RemoteImageController.GetRemoteImages looks the item up without a user, so the read key needs no userId - unlike
    GET /Items/{id}, see the JY-260 hotfix). Raises on no answer / non-2xx."""
    creds = media_jellyfin.creds()
    if creds is None:
        raise RuntimeError("Jellyfin not configured")
    body = media_jellyfin.get(*creds, f"/Items/{jf_id}/RemoteImages",
                              {"type": "Backdrop", "providerName": "TheMovieDb", "includeAllLanguages": "true"})
    return (body or {}).get("Images") or [] if isinstance(body, dict) else []


def rank_backdrops(remote, full: bool = False) -> list[dict]:
    """The top two TMDB backdrops (B. 2026-10-28, option A): text-less ones (no language) when any exist, else all;
    then CommunityRating, then VoteCount, then width, highest first. Art only from image.tmdb.org; duplicates once.
    -> [{url, lang, rating, votes, width}] (0 to 2)."""
    rows = []
    for im in remote if isinstance(remote, list) else []:
        if not isinstance(im, dict):
            continue
        url = im.get("Url")
        if not isinstance(url, str) or not url.startswith(TMDB_ART):
            continue
        rating = im.get("CommunityRating")
        rating = float(rating) if isinstance(rating, (int, float)) and not isinstance(rating, bool) else 0.0
        votes = im.get("VoteCount") if isinstance(im.get("VoteCount"), int) else 0
        width = im.get("Width") if isinstance(im.get("Width"), int) else 0
        lang = (im.get("Language") or "").strip().lower() if isinstance(im.get("Language"), str) else ""
        rows.append({"url": url, "lang": lang or None, "rating": rating, "votes": votes, "width": width})
    clean = [r for r in rows if r["lang"] is None]
    pool = clean or rows
    pool.sort(key=lambda r: (-r["rating"], -r["votes"], -r["width"]))
    out, seen = [], set()
    for r in pool:
        if r["url"] not in seen:
            seen.add(r["url"])
            out.append(r)
    return out if full else out[:2]


def w1280(url: str) -> str:
    """TMDB's 1280-wide size of an image URL (RemoteImages lists `original`, which can be a multi-MB 4K file)."""
    return url.replace("/t/p/original/", "/t/p/w1280/", 1)


def backdrops_on() -> bool:
    """POSTERS_BACKDROPS (default on): fetch and store the ranked TMDB backdrops in the poster pass."""
    return os.environ.get("POSTERS_BACKDROPS", "").strip().lower() not in ("off", "0", "no")


def backdrops_due(side: dict | None, now: float | None = None) -> bool:
    try:
        return (now or time.time()) - float((side or {}).get("backdrops_at") or 0) >= BACKDROPS_TTL_S
    except (TypeError, ValueError):
        return True


def fetch_backdrops(jf_id: str) -> dict:
    """Rank the title's TMDB backdrops and store the top two (backdrop1, backdrop2); a slot TMDB no longer fills is
    cleared. -> {"picks": [...], "stored": n}. Raises on an upstream failure (nothing changed: retried next pass)."""
    picks = rank_backdrops(remote_backdrops(jf_id))
    got = []
    for pick in picks:
        body = fetch_art(w1280(pick["url"]))
        if body is None:
            raise RuntimeError("backdrop unavailable")
        got.append(store.backdrop_jpeg(body))
    for n, (pick, jpeg) in enumerate(zip(picks, got), start=1):
        ver = hashlib.sha256(f"{pick['url']}|{store.BACKDROP_W}|q{store.BACKDROP_QUALITY}".encode()).hexdigest()[:10]
        if store.backdrop_version(jf_id, n) != ver:
            store.save_backdrop(jf_id, n, ver, jpeg)
    for n in store.BACKDROP_SLOTS[len(picks):]:
        store.clear_backdrop(jf_id, n)
    return {"picks": picks, "stored": len(picks)}


def pick_season(remote) -> dict | None:
    """A season's own TMDB poster: text-less first (then English, then other), then rating, then votes."""
    rows = ranked_posters(remote)
    if not rows:
        return None
    lang = {None: 0, "en": 1}
    return min(rows, key=lambda r: (lang.get(r["fallback"], 2), -(r["rating"] or 0), -r["votes"]))


def plan_season_art(series_id: str, seasons: list[dict], series_url: str | None, prior: dict) -> dict:
    """B. 2026-10-28: "If a season has more than 2 seasons. Can you continue to grab new images or closely related
    images?" Every season of a show gets a different picture: its own TMDB season poster (text-less first, then
    rating, then votes); else the next unused series poster in rank order (the series keeps #1); else a series TMDB
    backdrop, cropped to 2:3 by the renderer's centred cover crop, the ones not used as the show's Home / title
    backdrops (#1, #2) first. Stable: a season keeps its borrowed picture across passes unless its own poster appears;
    a new season takes the next unused one. -> {season jf_id: chosen (pick() shape + "source")}. GET reads only:
    one RemoteImages per season, the series' poster and backdrop lists only when a season needs one. Raises on an
    upstream failure (the caller keeps the previous plan)."""
    plan: dict = {}
    used = {series_url} if series_url else set()
    for x in seasons:
        own = pick_season(remote_images(x["jf_id"]))
        if own:
            plan[x["jf_id"]] = {**own, "source": "own"}
            used.add(own["url"])
    for x in seasons:   # stable: a borrowed picture stays with its season
        before = (prior or {}).get(x["jf_id"]) or {}
        if x["jf_id"] not in plan and before.get("source") in ("series", "backdrop") and before.get("url") not in used:
            plan[x["jf_id"]] = before
            used.add(before["url"])
    pool = None
    for x in seasons:
        if x["jf_id"] in plan:
            continue
        if pool is None:   # read once, only when a season needs a picture
            bds = rank_backdrops(remote_backdrops(series_id), full=True)
            pool = ([{**c, "source": "series", "fallback": "series"} for c in ranked_posters(remote_images(series_id))]
                    + [{"url": b["url"], "lang": b["lang"], "votes": b["votes"], "rating": b["rating"],
                        "width": b["width"], "height": 0, "fallback": "backdrop", "source": "backdrop"}
                       for b in bds[2:] + bds[:2]])
        nxt = next((c for c in pool if c["url"] not in used), None)
        if nxt is None and series_url:   # nothing left at all: the series poster, as before
            nxt = {"url": series_url, "lang": None, "votes": 0, "rating": None, "width": 0, "height": 0,
                   "fallback": "series", "source": "series"}
        if nxt is not None:
            plan[x["jf_id"]] = nxt
            used.add(nxt["url"])
        else:   # no picture anywhere: settled (the season renders as "no TMDB poster"), not re-planned every pass
            plan[x["jf_id"]] = {"source": "none"}
    return plan


def remote_images(jf_id: str) -> list:
    """The item's TMDB poster list through Jellyfin (GET only). Raises on no answer / non-2xx."""
    creds = media_jellyfin.creds()
    if creds is None:
        raise RuntimeError("Jellyfin not configured")
    body = media_jellyfin.get(*creds, f"/Items/{jf_id}/RemoteImages",
                              {"type": "Primary", "providerName": "TheMovieDb", "includeAllLanguages": "true"})
    return (body or {}).get("Images") or [] if isinstance(body, dict) else []


def seasons_of(series_id: str) -> list[dict]:
    """The series' real seasons through Jellyfin (GET only): [{jf_id, n}] in order. Specials (season 0) and seasons
    with no number are left out; `isMissing=false` drops seasons with no episodes on disk. LocationType is NOT used:
    on B.'s Jellyfin a season with episodes but no season folder reports "Virtual" (checked 2026-10-28)."""
    creds = media_jellyfin.creds()
    if creds is None:
        raise RuntimeError("Jellyfin not configured")
    body = media_jellyfin.get(*creds, f"/Shows/{series_id}/Seasons", {"isMissing": "false"})
    items = (body or {}).get("Items") or [] if isinstance(body, dict) else []
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        n, sid = it.get("IndexNumber"), str(it.get("Id") or "")
        if isinstance(n, int) and not isinstance(n, bool) and n >= 1 and media_item.ITEM_RE.match(sid):
            out.append({"jf_id": sid, "n": n})
    return sorted(out, key=lambda x: x["n"])


def fetch_art(url: str) -> bytes | None:
    """The poster bytes from image.tmdb.org (GET, capped at images.MAX_BYTES), or None."""
    if not url.startswith(TMDB_ART):
        return None
    resp = upstream.session("tmdb").get(url, timeout=images.TIMEOUT, stream=True)
    try:
        if resp.status_code != 200:
            return None
        ctype = str(resp.headers.get("content-type", "")).split(";")[0].strip().lower()
        if ctype not in images.EXT:
            return None
        return images._read_capped(resp)
    finally:
        close = getattr(resp, "close", None)
        if close:
            close()


# ---- targets ----

def targets(jelly: dict) -> list[dict]:
    """Every film and series in the jellyfin snapshot (both profiles, de-duplicated), recently added first, then A-Z."""
    profiles = [jelly] + ([jelly["her"]] if isinstance(jelly.get("her"), dict) else [])
    out, seen = [], set()
    for prof in profiles:
        for field, kind in (("movies", "movie"), ("shows", "tv")):
            for r in prof.get(field) or []:
                jf = str(r.get("jf_id") or "") if isinstance(r, dict) else ""
                if not jf or jf in seen or not media_item.ITEM_RE.match(jf):
                    continue
                seen.add(jf)
                out.append({"jf_id": jf, "kind": kind, "title": str(r.get("title") or ""),
                            "year": r.get("year") if isinstance(r.get("year"), int) else None,
                            "added_at": str(r.get("added_at") or "")})
    return order(out)


def order(rows: list[dict]) -> list[dict]:
    """Q9A: recently added first, then A-Z (case-insensitive); a series' seasons follow it, in order."""
    rows = sorted(rows, key=lambda r: ((r.get("title") or "").casefold(),
                                       r.get("season") if isinstance(r.get("season"), int) else 0))
    return sorted(rows, key=lambda r: r.get("added_at") or "", reverse=True)


def _text_hash(title: str, sub: str) -> str:
    return hashlib.sha256(f"{title}\0{sub}".encode("utf-8")).hexdigest()[:12]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---- media.db: per-item state + the backfill progress ----

def _ensure(db) -> None:
    key = str(media_store.db_path())
    if key in _ddl_done:
        return
    with _ddl_lock:
        for ddl in DDL:
            db.execute(ddl)
        have = {r[1] for r in db.execute("PRAGMA table_info(poster)")}
        for col, decl in ADDED_COLUMNS.items():
            if col not in have:
                db.execute(f"ALTER TABLE poster ADD COLUMN {col} {decl}")
        db.commit()
        _ddl_done.add(key)


def connect():
    """A write connection with the poster tables (created on first use per file per process)."""
    db = media_store.connect()
    _ensure(db)
    return db


def states() -> dict[str, dict]:
    """jf_id -> its `poster` row; {} when there is no media.db or no table yet (reads never create either)."""
    db = media_store.reader()
    if db is None:
        return {}
    try:
        with closing(db):
            return {r["jf_id"]: dict(r) for r in db.execute("SELECT * FROM poster")}
    except sqlite3.Error:
        return {}


def state(jf_id: str) -> dict | None:
    return states().get(jf_id)


def set_state(jf_id: str, **fields) -> None:
    """Update one item's row (only the named columns change), inserting it when new (`kind` and `status` are needed
    then). Column names come from this package's own calls, never from a request."""
    with closing(connect()) as db:
        cur = db.execute(f"UPDATE poster SET {', '.join(f'{c} = ?' for c in fields)} WHERE jf_id = ?",
                         (*fields.values(), jf_id))
        if cur.rowcount == 0:
            db.execute(f"INSERT INTO poster(jf_id, {', '.join(fields)}) VALUES (?, {', '.join('?' for _ in fields)})",
                       (jf_id, *fields.values()))
        db.commit()


def _stamp(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def in_backoff_until(retry_at, now: datetime | None = None) -> bool:
    return bool(retry_at) and _stamp(now or datetime.now(timezone.utc)) < str(retry_at)


def in_backoff(row: dict | None, now: datetime | None = None) -> bool:
    retry = (row or {}).get("retry_at")
    if not retry:
        return False
    return _stamp(now or datetime.now(timezone.utc)) < str(retry)


def record_failure(jf_id: str, error: str, now: datetime | None = None, **insert) -> int:
    """One more failure in a row for an item (render or write); the 3rd backs it off for 24 h (logged, shown on the
    review page). `insert` gives `kind` / `title` / `status` for an item with no row yet. -> its failure count."""
    now = now or datetime.now(timezone.utc)
    fails = int((state(jf_id) or {}).get("fails") or 0) + 1
    retry = _stamp(now + timedelta(seconds=BACKOFF_S)) if fails >= FAILS_BEFORE_BACKOFF else None
    set_state(jf_id, **({} if state(jf_id) else insert), fails=fails, retry_at=retry, last_error=error[:200])
    if retry:
        log.warning("posters: an item failed %s times in a row; backing off 24 h (shown on /media/posters)", fails)
    return fails


def backing_off() -> list[dict]:
    """Rows in backoff, for the review page."""
    now = datetime.now(timezone.utc)
    return sorted((r for r in states().values() if in_backoff(r, now)), key=lambda r: r.get("retry_at") or "")


def claim(jf_id: str, owner: str, now: datetime | None = None) -> bool:
    """Take an item's write lock (one atomic UPDATE in media.db, so it holds across threads, the background loop and
    any other process on the file). False while another holder's lock is fresh. A crashed holder's lock goes stale
    after LOCK_TTL_S.
    The holder calls it again as a heartbeat (same owner = extend). A busy database ("database is locked") is retried
    CLAIM_TRIES times, CLAIM_RETRY_S apart, then reads as busy (False): the item is skipped this pass."""
    for attempt in range(CLAIM_TRIES):
        at = now or datetime.now(timezone.utc)
        try:
            with closing(connect()) as db:
                cur = db.execute("UPDATE poster SET lock_owner = ?, lock_until = ? WHERE jf_id = ? "
                                 "AND (lock_owner IS NULL OR lock_owner = ? OR lock_until < ?)",
                                 (owner, _stamp(at + timedelta(seconds=LOCK_TTL_S)), jf_id, owner, _stamp(at)))
                db.commit()
                return cur.rowcount == 1
        except sqlite3.OperationalError as exc:
            if attempt + 1 == CLAIM_TRIES:
                log.warning("posters: item lock unavailable (%s); skipped this pass", type(exc).__name__)
                return False
            time.sleep(CLAIM_RETRY_S)
    return False


def release(jf_id: str, owner: str) -> None:
    with closing(connect()) as db:
        db.execute("UPDATE poster SET lock_owner = NULL, lock_until = NULL WHERE jf_id = ? AND lock_owner = ?",
                   (jf_id, owner))
        db.commit()


def progress() -> dict[str, str]:
    db = media_store.reader()
    if db is None:
        return {}
    try:
        with closing(db):
            return {r["key"]: r["value"] for r in db.execute("SELECT key, value FROM poster_progress")}
    except sqlite3.Error:
        return {}


def _set_progress(**values) -> None:
    with closing(connect()) as db:
        db.executemany("INSERT INTO poster_progress(key, value) VALUES (?, ?) "
                       "ON CONFLICT(key) DO UPDATE SET value = excluded.value", [(k, str(v)) for k, v in values.items()])
        db.commit()


# ---- the review page's and /img's reads (local files + media.db) ----

def rows() -> list[dict]:
    """Every stored item's sidecar + its media.db state, Q9A order."""
    st = states()
    now = datetime.now(timezone.utc)
    out = []
    for side in store.all_meta():
        row = st.get(side["jf_id"]) or {}
        out.append({**side, "reverted": bool(row.get("reverted")), "live": row.get("live_ver") is not None,
                    "manual": bool(row.get("manual")), "wrote": bool(row.get("wrote")),
                    "backoff": row.get("retry_at") if in_backoff(row, now) else None})
    return order(out)


def image_path(jf_id: str) -> Path | None:
    """The stored master JPEG for a Jellyfin id, or None (bad id / not rendered)."""
    return store.master(jf_id) if media_item.ITEM_RE.match(jf_id or "") else None


def served(jf_id: str, h: int) -> Path | None:
    """What /img serves for jf:<jf_id> at height h: the published stored poster, or None (POSTERS=off included)."""
    return None if disabled() else store.lookup(jf_id, h)


def url_version(ref) -> str:
    """Jinja `img_v`: the published store version of a `jf:` poster ref or a `jfs:<id>/<n>` stored backdrop ("" when
    there is none, POSTERS=off, or any other ref), which Joey's pages put on the /img URL as `&v=`. One small local
    file read; no network."""
    if disabled() or not isinstance(ref, str):
        return ""
    if ref.startswith("jfs:"):
        jf_id, _, n = ref[4:].partition("/")
        ver = (store.backdrop_version(jf_id, int(n)) if n in ("1", "2") and media_item.ITEM_RE.match(jf_id)
               else None) or ""
        return ver if images.V_RE.match(ver) else ""
    if not ref.startswith("jf:"):
        return ""
    jf_id = ref[3:]
    if not media_item.ITEM_RE.match(jf_id):
        return ""
    ver = store.current(jf_id) or ""
    return ver if images.V_RE.match(ver) else ""


def stored_backdrop(jf_id, n: int) -> str | None:
    """`jfs:<jf_id>/<n>` when backdrop n of that title is stored and published (and POSTERS is not off), else None.
    The page then draws it as /img/jfs:..?v=<ver>. Local file reads only."""
    if disabled() or not isinstance(jf_id, str) or not media_item.ITEM_RE.match(jf_id):
        return None
    return f"jfs:{jf_id}/{n}" if store.backdrop_path(jf_id, n) is not None else None


def served_backdrop(jf_id: str, n: int) -> Path | None:
    return None if disabled() else store.backdrop_path(jf_id, n)


# ---- the pass ----

def memory_ok(snaps) -> bool:
    free = memory_mb(snaps)
    if free is not None and free >= MIN_AVAILABLE_MB:
        return True
    if free is None:
        log.warning("posters: pass skipped, NAS available memory unknown (no fresh system snapshot)")
    else:
        log.warning("posters: pass skipped, NAS available memory %.0f MB is under %s MB", free, MIN_AVAILABLE_MB)
    return False


def tick(snaps_fn, now: float | None = None) -> dict | None:
    """The loop's 5-minute tick: a pass while the backfill has work left (or the last one was skipped for memory),
    else one an hour. -> the pass's counts, or None when no pass was due."""
    now = time.time() if now is None else now
    if not _tick["more"] and now - _tick["at"] < EVERY_S:
        return None
    counts = dry_pass(snaps_fn())
    _tick["at"] = now
    _tick["more"] = bool(counts.get("more")) or bool(counts.get("skipped_memory"))
    return counts


def _write_back(m: str, counts: dict, limit: int, pause: float) -> dict:
    """POSTERS=on: the write pass (queued reverts first; nothing without the key)."""
    if m == "on":
        from hub import media_posters_write as write
        counts["write"] = write.write_pass(limit=limit, pause=pause)
    return counts


def dry_pass(snaps: dict, pause: float = PAUSE_S, limit: int | None = None) -> dict:
    """Render what is new or stale into the store (at most `limit`, POSTERS_PER_PASS), then, with POSTERS=on, the
    write-back (which itself does nothing without the write key). -> counts; never raises."""
    m = mode()
    if m == "off":
        return {"off": True}
    counts = {"titles": 0, "rendered": 0, "cached": 0, "no_source": 0, "failed": 0, "truncated": 0, "backoff": 0,
              "backdrops": 0, "more": False}
    if not memory_ok(snaps):
        counts["skipped_memory"] = True
        return counts
    tpl, problems, _ = template_state()
    if problems:
        counts["template_error"] = len(problems)
        log.warning("posters: template rejected (%s problems), %s", len(problems),
                    "using the starter kit" if tpl else "nothing rendered")
    limit = per_pass() if limit is None else limit
    if tpl is None:
        return _write_back(m, counts, limit, pause)
    snap = (snaps or {}).get("jellyfin")   # the caller (hub.tasks) reads the snapshots: this module never does
    jelly = getattr(snap, "data", snap) or {}
    try:
        out_dir().mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        log.warning("posters: store unavailable: %s", type(exc).__name__)
        counts["failed"] = 1
        return _write_back(m, counts, limit, pause)
    known = states()
    started = time.time()

    def full():
        return counts["rendered"] + counts["no_source"] + counts["failed"] + counts["backdrops"] >= limit

    def bd(t: dict, side: dict | None) -> None:
        """JY-262 follow-up: a film's or series' two top-ranked TMDB backdrops into the store, at most monthly."""
        if not backdrops_on() or not side or not side.get("jf_id") or full() or not backdrops_due(side):
            return
        if in_backoff_until(side.get("backdrops_retry_at")):   # 3 failures in a row: passed over for 24 h
            counts["backoff"] += 1
            return
        try:
            got = fetch_backdrops(t["jf_id"])
            meta = store.read_meta(t["jf_id"]) or side
            meta = {k: v for k, v in meta.items() if k not in ("backdrops_fails", "backdrops_retry_at")}
            store.write_meta(t["jf_id"], {**meta, "backdrops": [x["url"] for x in got["picks"]],
                                          "backdrops_at": time.time()})
            counts["backdrops"] += 1
            if pause:
                time.sleep(pause)
        except Exception as exc:   # nothing stored: retried next pass; the 3rd failure in a row backs off 24 h
            counts["failed"] += 1
            log.warning("posters: backdrops failed: %s", type(exc).__name__)
            meta = store.read_meta(t["jf_id"]) or side
            fails = int(meta.get("backdrops_fails") or 0) + 1
            retry = (_stamp(datetime.now(timezone.utc) + timedelta(seconds=BACKOFF_S))
                     if fails >= FAILS_BEFORE_BACKOFF else None)
            try:
                store.write_meta(t["jf_id"], {**meta, "backdrops_fails": fails, "backdrops_retry_at": retry})
            except (OSError, ValueError):
                pass

    def one(t: dict, sub: str, extra: dict, fallback_url: str | None = None, given: dict | None = None) -> dict | None:
        """Render one item unless its version is already stored (`given`: the season art plan's pick, whose URL is
        part of the version, so a season's picture change re-renders it). -> its sidecar (None on failure)."""
        counts["titles"] += 1
        text = _text_hash(t["title"], sub + ("|" + given["url"] if given else ""))
        ver = store.version(tpl.version, text)
        row = known.get(t["jf_id"]) or {}
        if row.get("template") == tpl.version and (row.get("ver") == ver or row.get("status") == "no_source"):
            counts["cached"] += 1
            return store.read_meta(t["jf_id"]) or {}
        if in_backoff(row):   # failed 3 times in a row: passed over for 24 h, never counted against the limit
            counts["backoff"] += 1
            return store.read_meta(t["jf_id"])
        try:
            chosen = given if given is not None else pick(remote_images(t["jf_id"]))
            if chosen is None and fallback_url:   # a season with no TMDB season poster: the series' poster
                chosen = {"url": fallback_url, "lang": None, "votes": 0, "rating": None, "width": 0, "height": 0,
                          "fallback": "series"}
            art = fetch_art(chosen["url"]) if chosen else None
            if art is None and chosen and "/t/p/original/" in chosen["url"]:   # over the 5 MB cap (a 4K backdrop)
                art = fetch_art(w1280(chosen["url"]))
            auto = auto_approves(chosen)
            old = store.read_meta(t["jf_id"]) or {}   # the ranked backdrops outlive a poster re-render
            side = {**{k: old[k] for k in ("backdrops", "backdrops_at", "season_art", "season_art_fails",
                                           "season_art_retry_at") if k in old},
                    **t, **extra, "sub": sub, "template": tpl.version, "text": text, "ver": ver,
                    "rendered_at": _now(), "pick": chosen, "auto": auto}
            size = None
            if chosen is None:
                side["status"] = "no_source"
                counts["no_source"] += 1
            elif art is None:
                raise RuntimeError("art unavailable")
            else:
                try:
                    master = render.render(tpl, art, t["title"], sub)
                except render.RenderError:   # e.g. a 4096 x 2304 backdrop under 5 MB but over the decode cap
                    smaller = (fetch_art(w1280(chosen["url"])) if "/t/p/original/" in chosen["url"] else None)
                    if smaller is None:
                        raise
                    master = render.render(tpl, smaller, t["title"], sub)   # TMDB's 1280-wide copy
                size = store.save(t["jf_id"], ver, master, publish=auto and not row.get("reverted"))
                side["status"] = "rendered"
                if render.layout_title(tpl, t["title"]).truncated:   # past the hard floor: B. checks it on the page
                    side["truncated"] = True
                    counts["truncated"] += 1
                counts["rendered"] += 1
            store.write_meta(t["jf_id"], side)
            set_state(t["jf_id"], kind=t["kind"], title=t["title"], ver=ver, template=tpl.version,
                      status=side["status"], bytes=size, rendered_at=side["rendered_at"], last_error=None, fails=0,
                      retry_at=None)
            _set_progress(last=t["jf_id"], at=side["rendered_at"])
            if pause:
                time.sleep(pause)
            return side
        except Exception as exc:   # one bad title never stops the pass; it retries next pass, backing off after 3
            counts["failed"] += 1
            log.warning("posters: title failed: %s", type(exc).__name__)
            try:
                record_failure(t["jf_id"], type(exc).__name__, kind=t["kind"], title=t["title"], status="failed")
            except sqlite3.Error:
                pass
            return None

    for t in targets(jelly if isinstance(jelly, dict) else {}):
        if full():
            counts["more"] = True
            break
        if t["kind"] != "tv":
            bd(t, one(t, render.sub_line(t["kind"], year=t["year"]), {}))
            continue
        side = store.read_meta(t["jf_id"]) or {}
        if in_backoff(known.get(t["jf_id"])) and not side.get("seasons"):
            counts["backoff"] += 1
            continue
        seasons = side.get("seasons") if isinstance(side.get("seasons"), list) else None
        try:
            fresh = time.time() - float(side.get("seasons_at") or 0) < SEASONS_TTL_S
        except (TypeError, ValueError):
            fresh = False
        if seasons is None or not fresh:
            try:
                seasons, stamp = seasons_of(t["jf_id"]), time.time()
            except Exception as exc:
                counts["failed"] += 1
                log.warning("posters: season list failed: %s", type(exc).__name__)
                try:
                    record_failure(t["jf_id"], type(exc).__name__, kind="tv", title=t["title"], status="failed")
                except sqlite3.Error:
                    pass
                continue
        else:
            stamp = side["seasons_at"]
        series = one(t, render.sub_line("tv", seasons=[x["n"] for x in seasons]),
                     {"seasons": seasons, "seasons_at": stamp})
        if series and series.get("seasons_at") != stamp:   # stored poster, newer season list
            series = {**series, "seasons": seasons, "seasons_at": stamp}
            store.write_meta(t["jf_id"], series)
        bd(t, series)
        url = ((series or {}).get("pick") or {}).get("url")
        prior = (series or {}).get("season_art") if isinstance((series or {}).get("season_art"), dict) else {}
        art_plan = prior
        due = seasons and (not fresh or any(x["jf_id"] not in prior for x in seasons))   # daily, or a new season
        if due and in_backoff_until((series or {}).get("season_art_retry_at")):   # 3 failed plans in a row: 24 h
            counts["backoff"] += 1
            due = False
        if due:
            try:
                art_plan = plan_season_art(t["jf_id"], seasons, url, prior)
                if series and series.get("jf_id"):
                    meta = store.read_meta(t["jf_id"]) or series
                    meta = {k: v for k, v in meta.items() if k not in ("season_art_fails", "season_art_retry_at")}
                    series = {**meta, "season_art": art_plan}
                    store.write_meta(t["jf_id"], series)
            except Exception as exc:   # the previous plan stays; retried next pass, backing off after 3 in a row
                counts["failed"] += 1
                log.warning("posters: season art plan failed: %s", type(exc).__name__)
                if series and series.get("jf_id"):
                    meta = store.read_meta(t["jf_id"]) or series
                    fails = int(meta.get("season_art_fails") or 0) + 1
                    retry = (_stamp(datetime.now(timezone.utc) + timedelta(seconds=BACKOFF_S))
                             if fails >= FAILS_BEFORE_BACKOFF else None)
                    try:
                        store.write_meta(t["jf_id"], {**meta, "season_art_fails": fails, "season_art_retry_at": retry})
                    except (OSError, ValueError):
                        pass
        for x in seasons:
            if full():
                counts["more"] = True
                break
            one({"jf_id": x["jf_id"], "kind": "season", "title": t["title"], "year": None,
                 "added_at": t["added_at"]}, render.sub_line("season", season=x["n"]),
                {"series_id": t["jf_id"], "season": x["n"]}, fallback_url=url,
                given=art_plan.get(x["jf_id"]) if (art_plan.get(x["jf_id"]) or {}).get("url") else None)
        if counts["more"]:
            break
    if not counts["more"] and not counts["failed"]:
        try:
            if not progress().get("backfill_done"):
                _set_progress(backfill_done=_now())
                log.info("posters: backfill complete")
        except sqlite3.Error as exc:
            log.warning("posters: progress not saved: %s", type(exc).__name__)
    _write_back(m, counts, limit, pause)
    counts["seconds"] = round(time.time() - started, 1)
    if counts["rendered"] or counts["no_source"] or counts["failed"]:
        log.info("posters (%s): %s rendered, %s no TMDB poster, %s failed, %s stored already, %s s", m,
                 counts["rendered"], counts["no_source"], counts["failed"], counts["cached"], counts["seconds"])
    if counts["truncated"]:
        log.warning("posters: %s title(s) too long even at the size floor, cut short (marked on /media/posters)",
                    counts["truncated"])
    return counts
