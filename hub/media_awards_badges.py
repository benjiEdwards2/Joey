"""Poster winner badges (awards-ui item 3, 2026-10-09): a small round badge at the bottom right of a poster showing the
mark of the title's most prestigious win (Oscars > Cannes > BAFTA > Golden Globes > Emmys > Critics' Choice > SAG >
the guilds), "+N" when it won at more ceremonies, and a gold frame on the poster. Only WINS earn a badge; a
nomination alone shows nothing outside the Awards pages. Label / title: "Won Best Picture · Oscars 2025".

Data: ONE query per page for every poster on it (`media_awards_db.win_rows`, ids as JSON arrays), remembered for
TTL seconds per set of keys, so a library grid of hundreds of posters stays one indexed lookup. Never per card.
"""

from __future__ import annotations

import logging
import re
import sqlite3
import threading
import time

from hub import media_awards_db as adb
from hub import media_db
from hub import media_awards_icons as icons
from hub import media_awards_seed as seed

log = logging.getLogger("hub.media_awards_badges")

PRESTIGE = tuple(b["id"] for b in sorted(seed.BODIES, key=lambda b: b["prestige"]))   # M-21: from the seed
TTL = 60.0
CACHE_MAX = 128
KEY_RE = re.compile(r"^(tmdb|tvdb):(\d{1,10})$")
_cache: dict[tuple, tuple[float, dict]] = {}
_lock = threading.Lock()


def _rank(body_id: str) -> int:
    return PRESTIGE.index(body_id) if body_id in PRESTIGE else len(PRESTIGE)


def badge_of(wins: list[dict]) -> dict | None:
    """wins (win_rows rows of one work) -> {body_id, logo, more, label} for the most prestigious ceremony (its best
    ranked category, newest year first); None when there are none."""
    if not wins:
        return None
    top = min(wins, key=lambda w: (_rank(w["body_id"]), w["rank"] if w["rank"] is not None else 9999, -(w["year"] or 0),
                                   w["cat"] or ""))
    bodies = {w["body_id"] for w in wins}
    name = (seed.BY_ID.get(top["body_id"]) or {}).get("name", top["body_id"])
    more = len(bodies) - 1
    label = " · ".join(x for x in (f"Won {top['cat']}" if top["cat"] else "Won", f"{name} {top['year']}" if top["year"]
                                   else name, f"+{more} more ceremon{'y' if more == 1 else 'ies'}" if more else None) if x)
    return {"body_id": top["body_id"], "logo": icons.override(top["body_id"]), "more": more, "label": label}


def _split(pairs, qids):
    movie, tv, tvdb = set(), set(), set()
    for kind, key in pairs:
        m = KEY_RE.match(str(key or ""))
        if not m:
            continue
        n = int(m.group(2))
        if m.group(1) == "tvdb":
            tvdb.add(n)
        elif kind == "tv":
            tv.add(n)
        else:
            movie.add(n)
    return movie, tv, tvdb, {q for q in qids if adb.is_qid(q)}


def lookup(pairs=(), qids=()) -> dict:
    """{(kind, item_key): badge} for ('movie' | 'tv', 'tmdb:<id>' | 'tvdb:<id>') pairs and {qid: badge} for QIDs —
    winners only. One query (cached TTL s per key set); a database error logs its type and returns {}."""
    movie, tv, tvdb, qs = _split(pairs, qids)
    if not (movie or tv or tvdb or qs):
        return {}
    ck = (str(media_db.db_path()), tuple(sorted(movie)), tuple(sorted(tv)), tuple(sorted(tvdb)), tuple(sorted(qs)))
    now = time.monotonic()
    with _lock:
        hit = _cache.get(ck)
        if hit and now - hit[0] < TTL:
            return hit[1]
    try:
        rows = adb.win_rows(movie, tv, tvdb, qs)
    except (sqlite3.Error, OSError) as exc:
        log.warning("award badges skipped: %s", type(exc).__name__)
        return {}
    by_work: dict[str, list[dict]] = {}
    for r in rows:
        by_work.setdefault(r["qid"], []).append(r)
    out: dict = {}
    for qid, wins in by_work.items():
        b = badge_of(wins)
        r = wins[0]
        if qid in qs:
            out[qid] = b
        if r["tmdb_movie"] in movie:
            out[("movie", f"tmdb:{r['tmdb_movie']}")] = b
        if r["tmdb_tv"] in tv:
            out[("tv", f"tmdb:{r['tmdb_tv']}")] = b
        if r["tvdb"] in tvdb:
            out[("tv", f"tvdb:{r['tvdb']}")] = b
    with _lock:
        if len(_cache) >= CACHE_MAX:
            _cache.clear()
        _cache[ck] = (now, out)
    return out


def _pair(r: dict, kind: str | None):
    k = r.get("kind") if r.get("kind") in ("movie", "tv") else kind
    key = r.get("item_key") if KEY_RE.match(str(r.get("item_key") or "")) else (
        f"tmdb:{r['tmdb_id']}" if str(r.get("tmdb_id") or "").isdigit() else None)
    return (k or "movie", key) if key else None


def attach(rows, kind: str | None = None):
    """Set r['award'] (badge | None) on every row dict (library rows by item_key, Discover / TMDB rows by tmdb_id; the
    row's own `kind` wins over `kind`). One lookup for all of them. -> rows."""
    rows = [r for r in rows or [] if isinstance(r, dict)]
    pairs = {p for p in (_pair(r, kind) for r in rows) if p}
    try:
        got = lookup(pairs) if pairs else {}
    except Exception as exc:  # a badge is a nicety: never fail the page
        log.warning("award badges skipped: %s", type(exc).__name__)
        got = {}
    for r in rows:
        p = _pair(r, kind)
        r["award"] = got.get(p) if p else None
    return rows
