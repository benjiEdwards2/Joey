"""Month in Review + Wrapped (WP E6, 2026-10-13; review_features M1, with M10's words). A SUMMARY of what was watched in
a month or a year, never a ranking UI (the By-year rankings were deleted, decision 2026-10-09): no Rank / Place, no
podium of the viewer's own films. Pure reads: media.db (`diary`, `play`, `rating`, the award tables) plus the jellyfin
snapshot's library rows (film runtimes and years, show progress). No table of its own.

Data-source rules (no fabricated number anywhere):
  * Films, episodes, days, rewatches, firsts and lasts, most watched shows: the diary (Jellyfin history synced in plus
    watches logged by hand), one line per (item key, date), so a watch both synced and logged, or the both view's two
    owners watching together, counts once. Days also count a recorded play's local date.
  * Hours: recorded plays first (`play`, each capped at its runtime, media_plays_db._hours); then the runtime the
    jellyfin snapshot carries for each diary film that no play covers (watched before the recorder's start, or missed
    by it: no play of that film within a day). An episode without a play adds nothing (no runtime is known for it).
    With neither source the hours are None: "—" in a strip, dropped from a sentence. `hours_note` names the sources
    ("Plays since 6 Oct + film runtimes", "Films only").
  * Busiest weekday / hour and "mostly Sunday nights": recorded plays only (the diary has dates, not times), and
    "mostly" needs MOSTLY_MIN plays.
  * Scores: the view owner's ratings (media_db.owner_of: the both view reads B.'s, like every score in Joey).
  * Award winners you saw: wins at the ceremonies HELD that year (award_edition.year) of a title in the diary (up to
    the end of that year) or the year's plays; the badge is media_awards_badges.badge_of over those wins.
  * The recorder's start date is the earliest `play` row (any owner), never a constant.
Owner: media_db.owner_filter(view) — the signed-in owner (a friend's `jf:<id>` on the media front reads only that
friend's rows, JY-190); both when not signed in. Kept in memory per (file, owner,
year, month, media.db row signature, jellyfin snapshot, today), at most CACHE_MAX entries.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from collections import Counter
from contextlib import closing
from datetime import date, datetime, timedelta

from hub import media_awards_badges, media_db, media_home, media_plays_db, media_store, media_text
from hub.ids import home_now, home_tz

log = logging.getLogger("hub.media_wrapped")

TOP_RATED_MAX = 12
SHOWS_MAX = 8
REWATCH_MAX = 6
WINNERS_MAX = 24
MOSTLY_MIN = 3          # plays before "mostly Sunday nights" is said
CACHE_MAX = 32
PARTS = ((5, 12, "mornings"), (12, 17, "afternoons"), (17, 21, "evenings"))   # anything else is "nights"
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")

_now = home_now          # a module name of its own so tests can pin "today"
_cache: dict = {}
_lock = threading.Lock()


def clear() -> None:
    with _lock:
        _cache.clear()


# ---- small words ----

def day_part(hour: int) -> str:
    return next((word for lo, hi, word in PARTS if lo <= hour < hi), "nights")


def _day(value: str) -> str:
    """'2026-03-14' -> '14 Mar' (the year is the page's own)."""
    d = date.fromisoformat(value[:10])
    return f"{d.day} {d.strftime('%b')}"


def _long_day(d: date) -> str:
    return f"{d.day} {d.strftime('%b')} {d.year}"


def score_text(value) -> str:
    """7.43 -> '7.4', 8.0 -> '8', None -> '—' (guide §2: whole scores show no decimal)."""
    if value is None:
        return "—"
    value = round(float(value), 1)
    return f"{value:g}" if value == int(value) else f"{value:.1f}"


# ---- reads ----

def _bounds(year: int, month: int | None = None) -> tuple[date, date]:
    if month:
        return date(year, month, 1), date(year + (month == 12), month % 12 + 1, 1)
    return date(year, 1, 1), date(year + 1, 1, 1)


def _local(d: date) -> datetime:
    tz = home_tz()
    return datetime(d.year, d.month, d.day, tzinfo=tz) if tz else datetime(d.year, d.month, d.day).astimezone()


def _local_start(stamp) -> datetime | None:
    dt = media_text.parse(stamp)
    return dt.astimezone(home_tz()) if dt else None


def _owner_sql(owner) -> tuple[str, list]:
    """One owner's rows (you / her / a friend's `jf:<id>`), or the household's for the both view (owner None).
    JY-190 (Y1): a friend key used to fall through to the household's rows."""
    return (" AND owner = ?", [owner]) if owner is not None else (" AND " + media_db.household_sql(), [])


def _signature(db) -> tuple | None:
    """What changes whenever a read below would answer differently: row counts + newest ids / stamps."""
    try:
        return tuple(db.execute(
            "SELECT (SELECT COUNT(*) || ':' || COALESCE(MAX(id), 0) FROM diary),"
            " (SELECT COUNT(*) || ':' || COALESCE(MAX(id), 0) || ':' || COALESCE(MAX(last_seen_at), '') FROM play),"
            " (SELECT COUNT(*) || ':' || COALESCE(MAX(rated_at), '') FROM rating),"
            " (SELECT COUNT(*) FROM award_nomination WHERE won = 1),"
            " (SELECT COUNT(*) || ':' || COALESCE(MAX(resolved_at), '') FROM award_entity)").fetchone())
    except sqlite3.Error as exc:
        log.warning("wrapped signature failed: %s", type(exc).__name__)
        return None


def _read(db, owner, start: date, end: date) -> tuple[list[dict], list[dict], str | None]:
    """(diary rows up to `end`, oldest first; the window's plays; the earliest play stamp of any household owner)."""
    osql, oargs = _owner_sql(owner)
    diary = [dict(r) for r in db.execute(
        "SELECT id, owner, item_key, kind, title, year, poster, watched_on, source, show_key, season, episode, show_title"
        " FROM diary WHERE watched_on < ? AND watched_on IS NOT NULL" + osql + " ORDER BY watched_on, id",
        [end.isoformat(), *oargs])]
    plays = [dict(r) for r in db.execute(
        "SELECT owner, jf_id, item_key, show_key, kind, title, show_title, runtime_min, started_at, last_seen_at, poster"
        " FROM play WHERE started_at >= ? AND started_at < ?" + osql + " ORDER BY started_at",
        [media_plays_db._iso(_local(start)), media_plays_db._iso(_local(end)), *oargs])]
    first = db.execute(f"SELECT MIN(started_at) FROM play WHERE {media_db.household_sql()}").fetchone()[0]
    return diary, plays, first


def _years(db, owner) -> set[int]:
    osql, oargs = _owner_sql(owner)
    out = set()
    for sql in ("SELECT DISTINCT substr(watched_on, 1, 4) FROM diary WHERE watched_on IS NOT NULL" + osql,
                "SELECT DISTINCT substr(started_at, 1, 4) FROM play WHERE started_at IS NOT NULL" + osql):
        out |= {int(r[0]) for r in db.execute(sql, oargs) if str(r[0] or "").isdigit()}
    return out


def _wins(db, year: int) -> list[dict]:
    return [dict(r) for r in db.execute(
        "SELECT e.qid, e.kind, e.label, e.poster, e.tmdb_movie, e.tmdb_tv, e.tvdb, n.body_id, ed.year, c.name AS cat,"
        " c.rank, n.work_title FROM award_nomination n"
        " JOIN award_edition ed ON ed.body_id = n.body_id AND ed.ordinal = n.ordinal"
        " JOIN award_category c ON c.body_id = n.body_id AND c.cat_key = n.cat_key"
        " JOIN award_entity e ON e.qid = n.work_qid WHERE n.won = 1 AND ed.year = ?", (year,))]


# ---- the jellyfin snapshot's library rows ----

def _index(jelly: dict) -> tuple[dict, dict]:
    """({key: film row}, {key: show row}) over both owners' lists, by item_key and by `jf:<id>` (runtime, year and the
    canonical key are facts of the title, not of who owns the list)."""
    films, shows = {}, {}
    for src in (jelly or {}, (jelly or {}).get("her") or {}):
        for field, out in (("movies", films), ("shows", shows)):
            for r in src.get(field) or []:
                if isinstance(r, dict):
                    for k in (r.get("item_key"), f"jf:{r['jf_id']}" if r.get("jf_id") else None):
                        if k:
                            out.setdefault(k, r)
    return films, shows


def _canon(key, idx: dict) -> str:
    """A diary key in its library form ('jf:mov1' -> 'tmdb:603' when the snapshot knows it)."""
    row = idx.get(key)
    return (row or {}).get("item_key") or key


def _int_year(value) -> int | None:
    text = str(value or "")[:4]
    return int(text) if text.isdigit() and len(text) == 4 else None


# ---- the summary ----

def _lines(rows: list[dict]) -> list[dict]:
    """One line per (item key, date); `rewatch` as the diary marks it (a film, or an episode row, with an earlier diary
    row of the same owner and key)."""
    first: dict = {}
    seen, out = set(), []
    for r in rows:
        f = first.setdefault((r["owner"], r["item_key"]), r["watched_on"])
        r["rewatch"] = (r["kind"] == "movie" or r.get("season") is not None) and f < r["watched_on"]
        k = (r["item_key"], r["watched_on"])
        if k not in seen:
            seen.add(k)
            out.append(r)
    return out


def _dedupe_plays(plays: list[dict], owner) -> list[dict]:
    """The both view: one play per (item, local day) — two profiles watching together are one watch (the longer)."""
    if owner is not None:
        return plays
    best: dict = {}
    for p in plays:
        start = _local_start(p["started_at"])
        k = (p.get("jf_id") or p.get("item_key"), start.date() if start else None)
        if k not in best or media_plays_db._hours(p) > media_plays_db._hours(best[k]):
            best[k] = p
    return list(best.values())


def _hours(films, plays, film_idx, rec_start: date | None, start: date) -> tuple[float | None, str | None]:
    """(minutes | None, note): every recorded play, plus the runtime of each diary film no play covers (a watch before
    the recorder's start, or one it missed: no play of that film within a day of the diary date)."""
    play_min = sum(media_plays_db._hours(p) * 60 for p in plays)
    played = set()
    for p in plays:
        at = _local_start(p["started_at"])
        for k in (p.get("item_key"), f"jf:{p['jf_id']}" if p.get("jf_id") else None):
            if k and at:
                played.add((_canon(k, film_idx), at.date()))
    diary_min, used = 0.0, False
    for r in films:
        d, ck = date.fromisoformat(r["watched_on"]), _canon(r["item_key"], film_idx)
        if any((ck, d + timedelta(days=n)) in played for n in (-1, 0, 1)):
            continue
        rt = (film_idx.get(r["item_key"]) or {}).get("runtime_min")
        if isinstance(rt, (int, float)) and not isinstance(rt, bool) and rt > 0:
            diary_min += rt
            used = True
    if not plays and not used:
        return None, None
    since = f" since {_day(rec_start.isoformat())}" if plays and rec_start and start < rec_start else ""
    if plays and used:
        note = f"Plays{since} + film runtimes"
    elif plays:
        note = f"Plays{since}" if since else None
    else:
        note = "Films only"
    return play_min + diary_min, note


def _title(r: dict) -> str:
    return (r.get("show_title") or r["title"]) if r["kind"] != "movie" else r["title"]


def _href(r: dict, kind: str, lib: dict | None) -> str | None:
    jf = (lib or {}).get("jf_id")
    key = (r.get("show_key") or r["item_key"]) if kind == "tv" else r["item_key"]
    return media_home.row_href(jf, key, kind) or media_home.row_href(None, (lib or {}).get("item_key"), kind)


def _streak(days: set[str]) -> int:
    best = run = 0
    prev = None
    for d in sorted(date.fromisoformat(x) for x in days):
        run = run + 1 if prev and d - prev == timedelta(days=1) else 1
        best, prev = max(best, run), d
    return best


def _compute(db, view: str, jelly: dict, year: int, month: int | None) -> dict:
    owner = media_db.owner_filter(view)
    start, end = _bounds(year, month)
    diary, plays, first_play = _read(db, owner, start, end)
    plays = _dedupe_plays(plays, owner)
    lines = _lines(diary)
    win = [r for r in lines if r["watched_on"] >= start.isoformat()]
    films = [r for r in win if r["kind"] == "movie"]
    episodes = [r for r in win if r["kind"] != "movie"]
    film_idx, show_idx = _index(jelly)
    rec = _local_start(first_play)
    rec_start = rec.date() if rec else None

    minutes, hours_note = _hours(films, plays, film_idx, rec_start, start)
    starts = [s for s in (_local_start(p["started_at"]) for p in plays) if s]
    days = {r["watched_on"] for r in win} | {s.date().isoformat() for s in starts}

    # scores: the view owner's ratings of the window's films, one per film
    score_owner = media_db.owner_of(view)
    keys = {k for r in films for k in (r["item_key"], _canon(r["item_key"], film_idx))}
    ratings = media_db.get_ratings(keys, score_owner)
    rated: dict = {}
    for r in films:
        ck = _canon(r["item_key"], film_idx)
        sc = ratings.get(r["item_key"]) or ratings.get(ck)
        if sc:
            rated[ck] = (sc, r)
    scores = [sc for sc, _ in rated.values()]
    average = sum(scores) / len(scores) if scores else None
    best = max(rated.values(), key=lambda v: (v[0], v[1]["watched_on"]), default=None)

    pairs = Counter((s.weekday(), day_part(s.hour)) for s in starts)
    mostly = None
    if len(starts) >= MOSTLY_MIN and pairs:
        (wd, part), _ = min(pairs.items(), key=lambda kv: (-kv[1], kv[0][0], kv[0][1]))
        mostly = f"{WEEKDAYS[wd]} {part}"

    out = {
        "year": year, "month": month, "label": start.strftime("%B") if month else str(year),
        "empty": not win and not plays,
        "films": len(films), "episodes": len(episodes), "minutes": minutes,
        "hours_text": media_text.duration(minutes) if minutes else "—", "hours_note": hours_note,
        "days": len(days), "average": average, "average_text": score_text(average), "rated": len(scores),
        "best": {"title": best[1]["title"], "score": best[0]} if best else None, "mostly": mostly,
        "recorder_start": rec_start,
    }
    out["sentence"] = sentence(out)
    if month:
        return out

    # ---- Wrapped extras ----
    by_month = Counter(r["watched_on"][:7] for r in win)
    busy = min(by_month.items(), key=lambda kv: (-kv[1], kv[0])) if by_month else None
    wd = Counter(s.weekday() for s in starts)
    hr = Counter(s.hour for s in starts)
    top_wd = min(wd.items(), key=lambda kv: (-kv[1], kv[0])) if wd else None
    top_hr = min(hr.items(), key=lambda kv: (-kv[1], kv[0])) if hr else None
    out.update({
        "streak": _streak(days),
        "busiest_month": ({"text": date.fromisoformat(busy[0] + "-01").strftime("%B"),
                           "note": media_text.plural(busy[1], "watch", "watches")} if busy else None),
        "busiest_weekday": ({"text": WEEKDAYS[top_wd[0]], "note": media_text.plural(top_wd[1], "play")}
                            if top_wd else None),
        "busiest_hour": ({"text": f"{top_hr[0]:02d}:00", "note": media_text.plural(top_hr[1], "play")}
                         if top_hr else None),
    })

    top = sorted(rated.values(), key=lambda v: (-v[0], v[1]["watched_on"], v[1]["title"]))
    out["top_rated"] = [{"title": r["title"], "score": sc, "poster": r.get("poster") or (film_idx.get(r["item_key"]) or {}).get("poster"),
                         "href": _href(r, "movie", film_idx.get(r["item_key"])), "when": _day(r["watched_on"])}
                        for sc, r in top if sc >= 9][:TOP_RATED_MAX]

    # most watched shows: episodes per show; progress words while episodes are left (the view owner's own list)
    groups: dict = {}
    for r in episodes:
        k = r.get("show_key") or r["item_key"]
        g = groups.setdefault(k, {"key": k, "title": _title(r), "poster": None, "episodes": 0, "last": r["watched_on"],
                                  "row": r})
        g["episodes"] += 1
        g["poster"] = g["poster"] or r.get("poster")
        g["last"] = max(g["last"], r["watched_on"])
    own = ((jelly or {}).get("her") or {}).get("shows") if view == "her" else (jelly or {}).get("shows")
    own_idx = _index({"shows": own or []})[1]
    shows = sorted(groups.values(), key=lambda g: (-g["episodes"], g["title"]))[:SHOWS_MAX]
    runtimes = media_plays_db.show_runtimes(
        f"jf:{s['jf_id']}" for g in shows if (s := own_idx.get(g["key"])) and s.get("jf_id"))
    for g in shows:
        s = own_idx.get(g["key"])
        words = media_text.progress_words(s.get("unplayed"), s.get("episodes"),
                                          runtimes.get(f"jf:{s.get('jf_id')}")) if s else None
        g["progress"] = words if words and words != "All watched" else None
        g["href"] = _href(g.pop("row"), "tv", show_idx.get(g["key"]))
        g["poster"] = g["poster"] or (show_idx.get(g["key"]) or {}).get("poster")
    out["shows"] = shows

    # firsts and lasts
    firsts = []
    if win:
        for label, r in (("First watch", win[0]), ("Last watch", win[-1])):
            if label == "Last watch" and r is win[0]:
                break
            kind = "movie" if r["kind"] == "movie" else "tv"
            lib = (film_idx if kind == "movie" else show_idx).get(r.get("show_key") or r["item_key"])
            firsts.append({"label": label, "title": _title(r), "poster": r.get("poster"), "href": _href(r, kind, lib),
                           "note": _day(r["watched_on"])})
    dated = []
    for r in films:
        lib = film_idx.get(r["item_key"]) or {}
        y = _int_year(r.get("year")) or _int_year(lib.get("year"))
        if y:
            dated.append((y, r, lib))
    if dated:
        old, new = min(dated, key=lambda t: (t[0], t[1]["watched_on"])), max(dated, key=lambda t: (t[0], t[1]["watched_on"]))
        for label, (y, r, lib) in (("Oldest film", old), ("Newest film", new)):
            if label == "Newest film" and r is old[1]:
                break
            firsts.append({"label": label, "title": r["title"], "poster": r.get("poster") or lib.get("poster"),
                           "href": _href(r, "movie", lib), "note": str(y)})
    out["firsts"] = firsts

    # rewatches
    re_rows = [r for r in win if r["rewatch"]]
    shown, picked = set(), []
    for r in reversed(re_rows):
        kind = "movie" if r["kind"] == "movie" else "tv"
        k = r.get("show_key") or r["item_key"]
        if k in shown:
            continue
        shown.add(k)
        lib = (film_idx if kind == "movie" else show_idx).get(k)
        picked.append({"title": _title(r), "poster": r.get("poster") or (lib or {}).get("poster"),
                       "href": _href(r, kind, lib), "when": _day(r["watched_on"])})
    out["rewatches"] = {"count": len(re_rows), "rows": picked[:REWATCH_MAX]}

    out["winners"] = _winners(db, year, lines, plays, film_idx, show_idx)
    sources = []
    if rec_start:
        sources.append(f"Plays recorded by Joey since {_long_day(rec_start)}")
    if any(r.get("source") == "jellyfin" for r in win):
        sources.append("Jellyfin history")
    if any(r.get("source") == "manual" for r in win):
        sources.append("Diary")
    out["sources"] = " · ".join(sources)
    return out


def _winners(db, year: int, lines, plays, film_idx, show_idx) -> list[dict]:
    """Titles seen (diary up to the end of the year, the year's plays) that won at a ceremony held that year."""
    seen: dict[tuple, dict] = {}
    for r in list(lines) + list(plays):
        for k in (r.get("item_key"), r.get("show_key")):
            if not k:
                continue
            film = r.get("kind") == "movie"
            ck = _canon(k, film_idx if film else show_idx)
            seen.setdefault(("movie" if film else "tv", ck), r)
    if not seen:
        return []
    by_qid: dict[str, list[dict]] = {}
    for w in _wins(db, year):
        by_qid.setdefault(w["qid"], []).append(w)
    out = []
    for qid, wins in by_qid.items():
        w = wins[0]
        match = next((seen[p] for p in (("movie", f"tmdb:{w['tmdb_movie']}") if w["tmdb_movie"] else None,
                                         ("tv", f"tmdb:{w['tmdb_tv']}") if w["tmdb_tv"] else None,
                                         ("tv", f"tvdb:{w['tvdb']}") if w["tvdb"] else None) if p and p in seen), None)
        if match is None:
            continue
        kind = "movie" if match.get("kind") == "movie" else "tv"
        badge = media_awards_badges.badge_of(wins)
        key = (match.get("show_key") or match.get("item_key")) if kind == "tv" else match.get("item_key")
        lib = (film_idx if kind == "movie" else show_idx).get(key)
        title = (lib or {}).get("title") or (_title(match) if match.get("title") else None)
        out.append({"title": title or w["label"] or w["work_title"],
                    "poster": match.get("poster") or (lib or {}).get("poster") or w["poster"],
                    "href": _href({**match, "item_key": match.get("item_key") or key}, kind, lib),
                    "award": badge, "_rank": media_awards_badges._rank(badge["body_id"]) if badge else 99})
    out.sort(key=lambda x: (x["_rank"], x["title"] or ""))
    for x in out:
        x.pop("_rank")
    return out[:WINNERS_MAX]


def sentence(s: dict) -> str:
    """'12 films · 38 episodes · 41h 20m · mostly Sunday nights · best: Anora 9' — a part with nothing to say is left
    out (no '0 episodes', no hours without a source)."""
    parts = [media_text.plural(s["films"], "film") if s["films"] else None,
             media_text.plural(s["episodes"], "episode") if s["episodes"] else None,
             s["hours_text"] if s["minutes"] else None,
             f"mostly {s['mostly']}" if s["mostly"] else None,
             f"best: {s['best']['title']} {s['best']['score']}" if s["best"] else None]
    return " · ".join(p for p in parts if p)


def summary(view: str, jelly: dict | None, year: int, month: int | None = None, stamp=None) -> dict:
    """The month's (month given) or the year's summary for this owner view; an empty summary without a media.db."""
    db = media_store.reader()
    if db is None:
        return _empty(year, month)
    try:
        with closing(db):
            sig = _signature(db)
            key = (str(media_db.db_path()), media_db.owner_filter(view), media_db.owner_of(view), view == "her",
                   year, month, sig, stamp, _now().date())
            if sig is not None:
                with _lock:
                    hit = _cache.get(key)
                if hit is not None:
                    return hit
            out = _compute(db, view, jelly or {}, year, month)
    except sqlite3.Error as exc:
        log.warning("wrapped read failed: %s", type(exc).__name__)
        return _empty(year, month)
    if sig is not None:
        with _lock:
            if len(_cache) >= CACHE_MAX:
                _cache.clear()
            _cache[key] = out
    return out


def _empty(year: int, month: int | None) -> dict:
    out = {"year": year, "month": month, "label": date(year, month or 1, 1).strftime("%B") if month else str(year),
           "empty": True, "films": 0, "episodes": 0, "minutes": None, "hours_text": "—", "hours_note": None, "days": 0,
           "average": None, "average_text": "—", "rated": 0, "best": None, "mostly": None, "recorder_start": None,
           "streak": 0, "busiest_month": None, "busiest_weekday": None, "busiest_hour": None, "top_rated": [],
           "shows": [], "firsts": [], "rewatches": {"count": 0, "rows": []}, "winners": [], "sources": ""}
    out["sentence"] = ""
    return out


def years(view: str) -> set[int]:
    """Years with a diary row or a recorded play for this owner view."""
    db = media_store.reader()
    if db is None:
        return set()
    try:
        with closing(db):
            return _years(db, media_db.owner_filter(view))
    except sqlite3.Error as exc:
        log.warning("wrapped years failed: %s", type(exc).__name__)
        return set()


def month_card(view: str, jelly: dict | None, stamp=None) -> dict:
    """The Diary's Month in Review: this home-time month, or — while it has nothing yet — the month before it.
    {label, lead, s (summary | None), href, link_text}."""
    now = _now()
    cur = summary(view, jelly, now.year, now.month, stamp)
    if not cur["empty"]:
        shown, label, lead = cur, "This month", None
    else:
        py, pm = (now.year, now.month - 1) if now.month > 1 else (now.year - 1, 12)
        prev = summary(view, jelly, py, pm, stamp)
        shown = None if prev["empty"] else prev
        label, lead = f"{now.strftime('%B')} · nothing yet", (prev["label"] if shown else None)
    y = shown["year"] if shown else now.year
    return {"label": label, "lead": lead, "s": shown, "href": f"/media/diary/year/{y}", "link_text": f"All of {y} →"}


def stepper(view: str, year: int) -> dict:
    """‹ › between the years that have data, plus the current year."""
    have = years(view) | {_now().year}
    prev = max((y for y in have if y < year), default=None)
    nxt = min((y for y in have if y > year), default=None)
    return {"prev": prev, "next": nxt}
