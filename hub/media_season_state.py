"""Season state words (WP-T1, 2026-10-19): whether a show's seasons still have episodes to come or aired episodes not
downloaded, read from Sonarr, so a season is never called finished while more is due ("WAR: 3 of 8, all watched" while
5 episodes are still to air).

Reads (server-side only; SONARR_URL / SONARR_API_KEY through media_requests._arr_creds, the kept "arr" session):
* GET /api/v3/series - the whole series list, ONE call for every show on every page, kept TTL (10 min). Each entry
  carries `status`, `nextAiring` and per-season `statistics` (episodeFileCount, episodeCount, totalEpisodeCount,
  nextAiring, previousAiring). Matched by TheTVDB id, else TMDB id - never by title (Jellyfin and Sonarr titles differ
  by a "(2026)" suffix).
* GET /api/v3/episode?seriesId=&seasonNumber= - a show / season / episode page only (`detail`), for each season that
  still has unaired or missing episodes (at most EP_SEASONS_MAX, the latest first): exact aired / to-come counts and
  the next air date. Kept with the series (same TTL).

Pages NEVER call Sonarr before the render: `season_states` reads the cache only, and `later` hands back a callable the
route runs as its response's BackgroundTask (like the episode ratings and awards pages), so the first view may lack the
words and the next has them. A failed read keeps the last good answer (served however old) and is not retried for
FAIL_TTL; a Sonarr failure never fails a page. Logs carry an HTTP status or an exception TYPE only.

Words (always words, never colour alone): "Complete" · "5 to come · next airs 2 Nov" ("date TBA" without a date) ·
"2 aired, not downloaded" (combined: "2 aired, not downloaded · 5 to come · next airs 2 Nov") · "Waiting for the first
episode · airs 5 Dec" · "Season 3 announced" (a placeholder season: at most one episode, none aired). A series that has
everything Sonarr knows of says "Complete" when Sonarr calls it ended, else "Up to date".
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone

from hub import media_requests as mr, media_text, upstream
from hub.ids import home_tz

log = logging.getLogger("hub.media_season_state")

TTL = 600              # s: the series list and each season's episode list
FAIL_TTL = 60          # s: a failed read is not retried before this
TIMEOUT = 8
EP_SEASONS_MAX = 3     # episode-list reads per show (its latest incomplete seasons)

_lock = threading.Lock()
_index: dict = {"at": None, "tvdb": {}, "tmdb": {}, "failed_at": None}   # the series list (last good kept)
_episodes: dict[tuple, tuple[float, list]] = {}                          # (series id, season) -> (time, episodes)
_ep_failed: dict[tuple, float] = {}
_running: set = set()
_clock = time.monotonic


def clear_cache() -> None:
    with _lock:
        _index.update(at=None, tvdb={}, tmdb={}, failed_at=None)
        _episodes.clear()
        _ep_failed.clear()
        _running.clear()


def connected() -> bool:
    return mr._arr_creds("sonarr") is not None


# ---- pure words ----

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _day(stamp) -> str | None:
    """An air timestamp as the household's calendar day, ISO ('2026-11-02'), or None."""
    at = media_text.parse(stamp)
    if at is None:
        return None
    tz = home_tz()
    return (at.astimezone(tz) if tz is not None else at.astimezone()).date().isoformat()


def _when(next_air: str | None, lead: str) -> str:
    """'next airs 2 Nov' / 'airs 5 Dec 2027' (the year only when it is not this one), else 'date TBA'."""
    words = media_text.short_date(next_air) if next_air else None
    return f"{lead} {words}" if words else "date TBA"


def season_word(n, files: int, total: int, aired: int, to_come: int, missing: int, next_air: str | None) -> str | None:
    """One season's state in words (see the module doc); None when Sonarr lists no episode for it."""
    if total <= 0:
        return None
    if total <= 1 and aired == 0 and files == 0:
        return f"Season {n} announced" + (f" · {_when(next_air, 'airs')}" if next_air else "")
    if files == 0 and aired == 0:
        return f"Waiting for the first episode · {_when(next_air, 'airs')}"
    parts = []
    if missing > 0:
        parts.append(f"{missing} aired, not downloaded")
    if to_come > 0:
        parts.append(f"{to_come} to come · {_when(next_air, 'next airs')}")
    if parts:
        return " · ".join(parts)
    return "Complete" if files >= total else None


def series_word(status: str | None, seasons: list[dict]) -> str | None:
    """The series' state in words over its numbered seasons. Placeholder seasons ("Season 4 announced") speak only
    when nothing else is due."""
    real = [s for s in seasons if not s["placeholder"]]
    files = sum(s["files"] for s in seasons)
    aired = sum(s["aired"] for s in seasons)
    if not seasons or sum(s["total"] for s in seasons) <= 0:
        return None
    nxt = min((s["next_air"] for s in real if s["next_air"] and s["to_come"]), default=None)
    if files == 0 and aired == 0:
        nxt = min((s["next_air"] for s in seasons if s["next_air"]), default=None)
        return f"Waiting for the first episode · {_when(nxt, 'airs')}"
    missing = sum(s["missing"] for s in real)
    to_come = sum(s["to_come"] for s in real)
    parts = []
    if missing > 0:
        parts.append(f"{missing} aired, not downloaded")
    if to_come > 0:
        parts.append(f"{to_come} to come · {_when(nxt, 'next airs')}")
    if parts:
        return " · ".join(parts)
    held = [s for s in seasons if s["placeholder"]]
    if held:
        return f"Season {held[-1]['n']} announced"
    return "Complete" if str(status or "").lower() == "ended" else "Up to date"


def _int(v) -> int:
    return v if isinstance(v, int) and not isinstance(v, bool) and v > 0 else 0


def _season_from_stats(n: int, st: dict) -> dict:
    """A season's counts from the series list's statistics alone (no episode list read yet): `episodeCount` is
    Sonarr's aired-and-monitored (or has a file) count, so `aired` is close, not exact, until the episode list lands."""
    files, total = _int(st.get("episodeFileCount")), _int(st.get("totalEpisodeCount"))
    aired = 0 if not st.get("previousAiring") and files == 0 else min(total, max(_int(st.get("episodeCount")), files))
    return {"n": n, "files": files, "total": total, "aired": aired, "to_come": max(0, total - aired),
            "missing": max(0, aired - files), "next_air": _day(st.get("nextAiring"))}


def _season_from_episodes(n: int, eps: list[dict], now: datetime) -> dict:
    """A season's exact counts from its episode list: aired = has a file or its air time has passed."""
    files = aired = missing = 0
    upcoming = []
    for e in eps:
        at = media_text.parse(e.get("airDateUtc"))
        has = bool(e.get("hasFile"))
        files += has
        if has or (at is not None and at <= now):
            aired += 1
            missing += not has
        elif at is not None:
            upcoming.append(at)
    total = len(eps)
    return {"n": n, "files": files, "total": total, "aired": aired, "to_come": total - aired, "missing": missing,
            "next_air": _day(min(upcoming).isoformat()) if upcoming else None}


def build(entry: dict, episodes: dict | None = None, now: datetime | None = None) -> dict:
    """The page's state for one Sonarr series entry (+ any cached episode lists {season: [episodes]}). Pure."""
    now = now or _now()
    seasons = []
    for s in entry.get("seasons") or []:
        n = s.get("seasonNumber") if isinstance(s, dict) else None
        if not isinstance(n, int) or isinstance(n, bool) or n < 1:
            continue     # specials (season 0) never count
        eps = (episodes or {}).get(n)
        one = (_season_from_episodes(n, eps, now) if eps   # an empty list (an unread or odd answer): the statistics
               else _season_from_stats(n, s.get("statistics") or {}))
        one["placeholder"] = one["total"] <= 1 and one["aired"] == 0 and one["files"] == 0
        one["word"] = season_word(n, one["files"], one["total"], one["aired"], one["to_come"], one["missing"],
                                  one["next_air"])
        seasons.append(one)
    seasons.sort(key=lambda s: s["n"])
    status = str(entry.get("status") or "") or None
    return {"status": status, "files": sum(s["files"] for s in seasons), "total": sum(s["total"] for s in seasons),
            "to_come": sum(s["to_come"] for s in seasons if not s["placeholder"]),
            "missing": sum(s["missing"] for s in seasons if not s["placeholder"]),
            "word": series_word(status, seasons), "seasons": seasons,
            "by_n": {s["n"]: s for s in seasons}, "series_id": entry.get("id")}


# ---- the cache (no call) ----

def _key(v) -> int | None:
    s = str(v or "")
    return int(s) if s.isdigit() and 0 < len(s) <= 10 and int(s) > 0 else None


def _entry(tvdb=None, tmdb=None) -> dict | None:
    with _lock:
        hit = _index["tvdb"].get(_key(tvdb)) if _key(tvdb) else None
        return hit or (_index["tmdb"].get(_key(tmdb)) if _key(tmdb) else None)


def season_states(tvdb=None, tmdb=None) -> dict | None:
    """The show's state from the cache alone - never a Sonarr call. None when Sonarr is not connected, the list has not
    been read yet, or Sonarr does not have the show (then every page keeps its words unchanged)."""
    if not connected():
        return None
    entry = _entry(tvdb, tmdb)
    if entry is None:
        return None
    sid = entry.get("id")
    with _lock:
        eps = {n: v[1] for (i, n), v in _episodes.items() if i == sid}
    return build(entry, eps)


def _index_due() -> bool:
    with _lock:
        at, failed = _index["at"], _index["failed_at"]
    if failed is not None and _clock() - failed < FAIL_TTL:
        return False
    return at is None or _clock() - at >= TTL


def _seasons_due(entry: dict) -> list[int]:
    """The seasons whose episode list a detail page wants re-read: incomplete (by the list's statistics), latest first."""
    sid, out = entry.get("id"), []
    for s in sorted(entry.get("seasons") or [], key=lambda s: -(s.get("seasonNumber") or 0) if isinstance(s, dict) else 0):
        n = s.get("seasonNumber") if isinstance(s, dict) else None
        st = (s.get("statistics") or {}) if isinstance(s, dict) else {}
        if not isinstance(n, int) or n < 1 or _int(st.get("episodeFileCount")) >= _int(st.get("totalEpisodeCount")):
            continue
        with _lock:
            hit, failed = _episodes.get((sid, n)), _ep_failed.get((sid, n))
        if (hit is None or _clock() - hit[0] >= TTL) and (failed is None or _clock() - failed >= FAIL_TTL):
            out.append(n)
        if len(out) >= EP_SEASONS_MAX:
            break
    return out


def later(keys, detail: bool = False):
    """The BackgroundTask for a page that drew `keys` [(tvdb, tmdb), ...]: re-reads the series list when stale and, with
    `detail` (a show / season / episode page), the episode lists of the shows' incomplete seasons. None when nothing
    is due (or Sonarr is not connected) - the page attaches no task."""
    if not connected():
        return None
    keys = [(tvdb, tmdb) for tvdb, tmdb in keys if _key(tvdb) or _key(tmdb)]
    if not keys:
        return None
    index_due = _index_due()
    seasons = []
    if detail and not index_due:
        for tvdb, tmdb in keys:
            entry = _entry(tvdb, tmdb)
            if entry is not None:
                seasons += [(entry["id"], n) for n in _seasons_due(entry)]
    if not index_due and not seasons:
        return None

    def run() -> dict:
        return refresh(keys if detail else [], index_due, seasons)
    run.plan = {"index": index_due, "seasons": seasons, "detail": detail}   # tests read it
    return run


# ---- the reads (background only) ----

def _get(path: str, params: dict | None = None):
    base, headers = mr._arr_creds("sonarr")
    resp = upstream.session("arr").get(f"{base}{path}", params=params, headers=headers, timeout=TIMEOUT)
    if not 200 <= resp.status_code < 300:
        raise RuntimeError(f"HTTP {resp.status_code}")
    return resp.json()


def _read_index() -> bool:
    try:
        body = _get("/api/v3/series")
        if not isinstance(body, list):
            raise ValueError("not a list")
    except Exception as exc:  # status / type only
        log.warning("sonarr series list failed: %s", media_text.why(exc))
        with _lock:
            _index["failed_at"] = _clock()
        return False
    tvdb, tmdb = {}, {}
    for e in body:
        if isinstance(e, dict) and e.get("id"):
            if _key(e.get("tvdbId")):
                tvdb[_key(e["tvdbId"])] = e
            if _key(e.get("tmdbId")):
                tmdb[_key(e["tmdbId"])] = e
    with _lock:
        _index.update(at=_clock(), tvdb=tvdb, tmdb=tmdb, failed_at=None)
    return True


def _read_season(sid, n: int) -> bool:
    try:
        body = _get("/api/v3/episode", {"seriesId": sid, "seasonNumber": n})
        if not isinstance(body, list):
            raise ValueError("not a list")
    except Exception as exc:
        log.warning("sonarr episode list failed: %s", media_text.why(exc))
        with _lock:
            _ep_failed[(sid, n)] = _clock()
        return False
    eps = [e for e in body if isinstance(e, dict) and e.get("seasonNumber") == n]
    with _lock:
        _episodes[(sid, n)] = (_clock(), eps)
        _ep_failed.pop((sid, n), None)
        if len(_episodes) > 512:
            _episodes.clear()
    return True


def refresh(keys, index_due: bool = True, seasons=()) -> dict:
    """The background read: the series list (when due), then the named (series id, season) episode lists - plus, when
    the list was only read now, the incomplete seasons of the `keys` shows. One job per key set at a time. -> counts."""
    tag = (index_due, tuple(sorted(map(str, keys))), tuple(seasons))
    with _lock:
        if tag in _running:
            return {"skipped": 1}
        _running.add(tag)
    counts = {"index": 0, "seasons": 0, "failed": 0}
    try:
        if index_due:
            ok = _read_index()
            counts["index" if ok else "failed"] += 1
            if ok:
                for tvdb, tmdb in keys:
                    entry = _entry(tvdb, tmdb)
                    if entry is not None:
                        seasons = list(seasons) + [(entry["id"], n) for n in _seasons_due(entry)]
        for sid, n in dict.fromkeys(seasons):
            counts["seasons" if _read_season(sid, n) else "failed"] += 1
    except Exception as exc:  # a background job never raises into the server
        log.warning("sonarr season state failed: %s", media_text.why(exc))
        counts["failed"] += 1
    finally:
        with _lock:
            _running.discard(tag)
    return counts


def chain(*jobs):
    """One BackgroundTask callable running each non-None job in turn (a page with episode ratings AND season state)."""
    jobs = [j for j in jobs if j is not None]
    if not jobs:
        return None
    if len(jobs) == 1:
        return jobs[0]

    def run():
        for j in jobs:
            try:
                j()
            except Exception as exc:
                log.warning("background job failed: %s", type(exc).__name__)
    return run


# ---- words the pages share ----

def episodes_words(state: dict | None, fallback: str) -> str:
    """'3 of 8 episodes' while Sonarr has fewer files than episodes, else the page's own words."""
    if state and 0 < state["files"] < state["total"]:
        return f"{state['files']} of {state['total']} episodes"
    return fallback


def waiting(state: dict | None) -> bool:
    """Sonarr has the show and no file of it yet."""
    return bool(state) and state["files"] == 0


def waiting_words(state: dict | None) -> str:
    """'waiting for the first episode · airs 5 Dec' (date TBA without one); without Sonarr's answer, the bare words."""
    word = (state or {}).get("word") or ""
    if word.startswith("Waiting for the first episode"):
        return "w" + word[1:]
    return "waiting for the first episode"
