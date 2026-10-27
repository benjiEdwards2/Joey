"""JY-105 (B., 2026-10-27: "look B; ratings 9-10; 5 sources; refresh daily; friends: their own ratings; TV: row, never
first focus"): the "Because you rated these 9 or 10" shelf on Media Overview.

* refresh() - run by the warm-up inside its 24 h library pass (hub/media_warmup.py run_pass), never by a page. For
  each owner in media.db: the top SOURCES title-level ratings of MIN_SCORE+ with a `tmdb:` key (score desc, newest
  rating first on a tie), Seerr's recommendations for each (one read per source per pass, paced), minus what that
  owner has rated or watched on the server. Written to one JSON file in the meta cache dir, keyed by owner (joey-hub
  writes it, joey-media reads it: both mount the cache volume). A failed read keeps that source's last rows.
* shelf() - the Overview shelf for the page's owner, from that file only (no call on render). Round-robin across the
  sources, a title once, at most SHELF_MAX. No entry = no shelf.
Logs carry exception TYPES only.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from contextlib import closing

from hub import media_db, media_discover as md, media_store

log = logging.getLogger("hub.media_because")

FILE = "because_shelf.json"
TITLE = "Because you rated these 9 or 10"
SOURCES = 5
MIN_SCORE = 9
PAUSE_S = 0.3

_mem: dict = {"key": None, "viewers": {}}   # the file's (mtime, size) -> its viewers, so a render reads it once


def shelf_max() -> int:
    from hub import media_home   # late: media_home imports this module
    return media_home.SHELF_MAX


def _path():
    return md.meta_dir() / FILE


# ---- warm-up side ----

def _tmdb(key) -> int | None:
    key = str(key or "")
    return int(key[5:]) if key.startswith("tmdb:") and key[5:].isdigit() else None


def sources_by_owner() -> dict[str, list[dict]]:
    """{owner: [{title, score, kind, tmdb}]} - each owner's top SOURCES, score desc then newest rating first."""
    db = media_store.reader()
    if db is None:
        return {}
    out: dict[str, list[dict]] = {}
    try:
        with closing(db):
            rows = db.execute("SELECT owner, item_key, kind, title, score FROM rating WHERE level = 'show' AND "
                              "score >= ? AND item_key LIKE 'tmdb:%' ORDER BY owner, score DESC, rated_at DESC",
                              (MIN_SCORE,)).fetchall()
    except sqlite3.Error as exc:
        log.warning("because sources read failed: %s", type(exc).__name__)
        return {}
    for r in rows:
        tmdb, mine = _tmdb(r["item_key"]), out.setdefault(r["owner"], [])
        if tmdb is not None and len(mine) < SOURCES:
            mine.append({"title": r["title"], "score": r["score"], "kind": media_db.norm_kind(r["kind"]),
                         "tmdb": tmdb})
    return {o: s for o, s in out.items() if s}


def _seen(owner: str, jelly: dict) -> set:
    """The `tmdb:` keys `owner` has rated (any score or level) or watched on the server: play history, diary (an
    episode counts for its show), and for you / her the Jellyfin snapshot's played films and shows of that profile."""
    shows = {}
    for prof in (jelly, jelly.get("her") if isinstance(jelly.get("her"), dict) else {}):
        for r in prof.get("shows") or []:
            if isinstance(r, dict) and r.get("jf_id"):
                shows.setdefault(f"jf:{r['jf_id']}", r.get("item_key"))
    keys: set = set()
    db = media_store.reader()
    if db is not None:
        try:
            with closing(db):
                keys |= {r[0] for r in db.execute("SELECT item_key FROM rating WHERE owner = ?", (owner,))}
                for table in ("play", "diary"):
                    for r in db.execute(f"SELECT item_key, show_key FROM {table} WHERE owner = ?", (owner,)):
                        keys.add(r[0])
                        keys.add(shows.get(r[1], r[1]))
        except sqlite3.Error as exc:
            log.warning("because seen read failed: %s", type(exc).__name__)
    prof = jelly if owner == "you" else jelly.get("her") if owner == "her" else None
    for field in ("movies", "shows"):
        for r in ((prof or {}).get(field) or []) if isinstance(prof, dict) else []:
            if isinstance(r, dict) and r.get("played"):
                keys.add(r.get("item_key"))
    return {k for k in keys if k}


def read() -> dict:
    """{owner: [source, ...]} from the cache file; {} when it is missing or unreadable. Memoised on (mtime, size)."""
    path = _path()
    try:
        st = os.stat(path)
    except OSError:
        return {}
    key = (str(path), st.st_mtime_ns, st.st_size)
    if _mem["key"] != key:
        try:
            got = json.loads(path.read_text(encoding="utf-8"))
            viewers = got.get("viewers") if isinstance(got, dict) else None
        except (OSError, ValueError):
            viewers = None
        _mem.update(key=key, viewers=viewers if isinstance(viewers, dict) else {})
    return _mem["viewers"]


def _write(viewers: dict) -> None:
    path = _path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps({"at": time.time(), "viewers": viewers}), encoding="utf-8")
        os.replace(tmp, path)   # atomic: joey-media never reads half a file
    except OSError as exc:
        log.warning("because cache write failed: %s", type(exc).__name__)


def refresh(snaps=None, pause: float = PAUSE_S) -> dict:
    """Rebuild the cache. -> counts {viewers, sources, failed}; never raises. No Seerr keys: the cache is left alone.
    `snaps` comes from the warm-up (media_warmup.run_pass reads the store; this module never does)."""
    if md._creds() is None:
        return {"skipped_no_keys": True}
    snap = (snaps or {}).get("jellyfin")
    jelly = (snap.data if snap else {}) or {}
    old = read()
    fetched: dict = {}
    counts = {"viewers": 0, "sources": 0, "failed": 0}
    viewers: dict = {}
    for owner, srcs in sources_by_owner().items():
        seen, entry = _seen(owner, jelly), []
        for s in srcs:
            k = (s["kind"], s["tmdb"])
            if k not in fetched:
                try:
                    body, _code = md._fetch(f"/api/v1/{s['kind']}/{s['tmdb']}/recommendations")
                except Exception as exc:   # one bad source never stops the pass
                    log.warning("because read failed: %s", type(exc).__name__)
                    body = None
                ok = isinstance(body, dict) and isinstance(body.get("results"), list)
                fetched[k] = md._rows(body["results"], s["kind"]) if ok else None
                counts["sources" if ok else "failed"] += 1
                if pause:
                    time.sleep(pause)
            got = fetched[k]
            if got is None:   # failed: the last rows this owner had for the same source, if any
                got = next((p.get("rows") or [] for p in old.get(owner) or []
                            if isinstance(p, dict) and (p.get("kind"), p.get("tmdb")) == k), [])
            rows = [r for r in got if f"tmdb:{r.get('tmdb_id')}" not in seen]
            entry.append({**s, "rows": rows[:shelf_max()]})
        viewers[owner] = entry
        counts["viewers"] += 1
    _write(viewers)
    log.info("because shelf: %(viewers)s viewers, %(sources)s sources read, %(failed)s failed", counts)
    return counts


# ---- render side (cache only) ----

def merge(entry) -> list[tuple[dict, dict]]:
    """[(row, source)] round-robin across the sources in order, each title once, at most SHELF_MAX."""
    srcs = [s for s in entry or [] if isinstance(s, dict) and isinstance(s.get("rows"), list)]
    out, placed, cap = [], set(), shelf_max()
    for i in range(max((len(s["rows"]) for s in srcs), default=0)):
        for s in srcs:
            if i < len(s["rows"]) and isinstance(s["rows"][i], dict):
                r = s["rows"][i]
                key = (r.get("kind"), r.get("tmdb_id"))
                if key in placed:
                    continue
                placed.add(key)
                out.append((r, s))
                if len(out) >= cap:
                    return out
    return out


def shelf(view: str, jelly: dict) -> dict | None:
    """The page owner's shelf (`media_db.owner_of(view)`: never anyone else's), or None when the cache has nothing.
    `jelly` is the page's (view) Jellyfin data: its library lists say On server and give the item page."""
    from hub import media_home, media_library

    entry = read().get(media_db.owner_of(view))
    picked = merge(entry)
    if not picked:
        return None
    lib = {}
    for field in ("movies", "shows"):
        for r in (jelly or {}).get(field) or []:
            if isinstance(r, dict) and r.get("item_key") and not media_library.empty_series(r):
                lib.setdefault(r["item_key"], r)
    items = []
    for r, s in picked:
        key = f"tmdb:{r.get('tmdb_id')}"
        row = lib.get(key)
        on = row is not None or r.get("status_word") in md.ON_DISK
        href = (media_home.item_href(row.get("jf_id")) if row else None) or r.get("href") \
            or media_home.row_href(None, key, r.get("kind"))
        items.append({"title": r.get("title"), "sub": f"{s.get('title')} ★{s.get('score')}", "poster": r.get("poster"),
                      "href": href, "tag": "On server" if on else "Request",
                      "tag_cls": "st-available" if on else "st-off"})
    return {"id": "because", "title": TITLE, "see_all_href": None, "items": items, "quiet_text": None,
            "tv_later": True}
