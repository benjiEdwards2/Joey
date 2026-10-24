"""Request quality profile (WP-R1, 2026-10-21): pick 1080p or 4K when requesting a film or show, and switch a title
between them later from its page - Seerr's "Advanced › Quality Profile", in Joey.

Seerr has ONE Radarr and ONE Sonarr server (neither `is4k`), so the choice is the arr app's QUALITY PROFILE, never
Seerr's 4K flag. Reads and writes (server-side only; creds as media_requests._arr_creds, the kept "arr" session):

* `profiles(kind)` - Radarr / Sonarr `GET /api/v3/qualityprofile` (names as the app has them; `is_4k` when the name
  says 4k / 2160 / uhd), the default being the Seerr server's `activeProfileId` (`GET /api/v1/settings/radarr|sonarr`,
  else the first non-4K profile). Kept TTL; a failed read keeps the last good list and is not retried for FAIL_TTL.
* `current(kind, tmdb)` - the arr entry's `qualityProfileId` (media_requests' 5-minute lookup cache). Never a
  request's own stored profileId: requests from before 2026-10-06 carry ids that no longer exist.
* `switch(...)` - PUT the app's own resource with `qualityProfileId` changed (every other field kept), then the title's
  MoviesSearch / SeriesSearch. The app keeps the file it has until a release of the new profile arrives.
* `ensure(...)` - the request's safety net: Seerr's `POST /api/v1/request` takes `profileId` (no `serverId` needed -
  seerr MediaRequestSubscriber applies it to the default server), and after a request for a non-default profile the
  entry is read back (FOLLOW_TRIES reads, FOLLOW_WAIT s apart) and corrected when it differs.

Pages never wait on these before a render except an explicit step (the Request confirm, the Switch confirm): the
title page lazy-loads GET /media/title/{kind}/{tmdb}/quality, and the Requests page reads caches only (`attach`)
with the missing reads run after the response (`later`). JY-110: a film's last seen profile is kept however old
(`_films`, re-read after the response as before), and Joey's own request / switch puts the entry it just read or wrote
straight into the caches (`_seen`), so a new 4K title has its chip on the next view. Failures are words; logs carry
an HTTP status or an exception TYPE only.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool

from hub import media_arr_search as mas, media_discover as md, media_item, media_requests as mr, media_text, upstream
from hub.media_write import bad, flash_keys, form_of, is_htmx, same_origin

log = logging.getLogger("hub.media_quality")
router = APIRouter()

TTL = 600            # s: the profile list
FAIL_TTL = 60        # s: a failed read is not retried before this
TIMEOUT = 8
LATER_MAX = 10       # Requests page: film lookups run after one response, at most
K4 = re.compile(r"4k|2160|uhd", re.I)
NAMES = mas.NAMES

_lock = threading.Lock()
_memo: dict[str, dict] = {}   # kind -> {"at", "rows", "failed_at"} (the last good rows kept)
_films: dict[int, int | None] = {}   # JY-110: tmdb -> the Radarr entry's last seen qualityProfileId (None: not there)
_clock = time.monotonic


def clear_cache() -> None:
    with _lock:
        _memo.clear()
        _films.clear()


def _film(tmdb, pid) -> None:
    if isinstance(tmdb, int) and tmdb > 0:
        with _lock:
            if len(_films) > 1024:
                _films.clear()
            _films[tmdb] = pid


def _seen(kind: str, entry: dict, pid: int | None = None) -> None:
    """JY-110: a title's arr entry Joey just read or wrote (with `pid` once PUT) into the Requests page's caches."""
    entry = {**entry, "qualityProfileId": pid} if pid is not None else entry
    if kind == "tv":
        from hub import media_season_state as mss   # late, as _row_pid
        mss.put(entry)
    else:
        _film(entry.get("tmdbId"), entry.get("qualityProfileId"))


def _app(kind: str) -> str:
    return mas.app_of(kind)


# ---- the profile list ----

def _seerr_default(app: str) -> int | None:
    """The Seerr server's activeProfileId for this app (the default, non-4K server), or None."""
    body = md._get(f"/api/v1/settings/{app}")
    servers = [s for s in body if isinstance(s, dict)] if isinstance(body, list) else []
    pick = next((s for s in servers if s.get("isDefault") and not s.get("is4k")), None)
    if pick is None and len(servers) == 1:
        pick = servers[0]
    v = (pick or {}).get("activeProfileId")
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def _read(kind: str) -> list[dict]:
    app = _app(kind)
    base, headers = mr._arr_creds(app)
    resp = upstream.session("arr").get(f"{base}/api/v3/qualityprofile", headers=headers, timeout=TIMEOUT)
    if not 200 <= resp.status_code < 300:
        raise RuntimeError(f"HTTP {resp.status_code}")
    body = resp.json()
    if not isinstance(body, list):
        raise ValueError("not a list")
    rows = [{"id": p["id"], "name": str(p.get("name") or f"Profile {p['id']}")[:60],
             "is_4k": bool(K4.search(str(p.get("name") or "")))}
            for p in body if isinstance(p, dict) and isinstance(p.get("id"), int) and p["id"] > 0]
    if not rows:
        raise ValueError("no profiles")
    want = _seerr_default(app)
    default = want if want in {r["id"] for r in rows} else next((r["id"] for r in rows if not r["is_4k"]), rows[0]["id"])
    for r in rows:
        r["default"] = r["id"] == default
    return rows


def profiles(kind: str) -> list[dict]:
    """[{id, name, is_4k, default}] for the app behind `kind`; [] when it is not connected or has never answered.
    Never raises."""
    app = _app(kind)
    if mr._arr_creds(app) is None:
        return []
    with _lock:
        m = dict(_memo.get(kind) or {})
    now = _clock()
    if m.get("at") is not None and now - m["at"] < TTL:
        return m["rows"]
    if m.get("failed_at") is not None and now - m["failed_at"] < FAIL_TTL:
        return m.get("rows") or []
    try:
        rows = media_item.once(("quality", kind), lambda: _read(kind))
    except Exception as exc:  # status / type only
        log.warning("%s quality profiles failed: %s", app, media_text.why(exc))
        with _lock:
            _memo[kind] = {**m, "failed_at": _clock()}
        return m.get("rows") or []
    with _lock:
        _memo[kind] = {"at": _clock(), "rows": rows, "failed_at": None}
    return rows


def peek(kind: str) -> list[dict]:
    """The last good profile list, however old - never a call (the Requests page, flash words)."""
    with _lock:
        return list((_memo.get(kind) or {}).get("rows") or [])


def by_id(rows: list[dict], pid) -> dict | None:
    return next((r for r in rows if r["id"] == pid), None) if isinstance(pid, int) else None


def choices(kind: str) -> list[dict]:
    """The Request confirm step's chips: the profiles when there are two or more, else [] (no row)."""
    rows = profiles(kind)
    return rows if len(rows) > 1 else []


def pick(kind: str, raw) -> dict | None:
    """The profile the Request form named (`raw`: its `profile` value or None) -> the profile, or None for none sent.
    An id the app does not offer raises 422."""
    if raw is None:
        return None
    got = by_id(profiles(kind), int(raw) if str(raw).isdigit() and len(str(raw)) <= 9 else None)
    if got is None:
        raise bad("Pick a quality")
    return got


def name_of(kind: str, pid) -> str | None:
    """The cached name of a non-default profile id (the request's done line, a flash), else None - never a call."""
    p = by_id(peek(kind), int(pid) if str(pid or "").isdigit() and len(str(pid)) <= 9 else None)
    return p["name"] if p and not p["default"] else None


# ---- a title's profile ----

def describe(kind: str, entry: dict | None) -> dict | None:
    p = by_id(profiles(kind), (entry or {}).get("qualityProfileId")) if entry else None
    return {"id": p["id"], "name": p["name"], "is_4k": p["is_4k"]} if p else None


def current(kind: str, tmdb: int, tvdb: int | None = None) -> dict | None:
    """{id, name, is_4k} of the title's arr entry, or None (not in the app / unknown profile / unreachable)."""
    return describe(kind, mas.find(kind, tmdb, tvdb, kept=True))


def target_of(rows: list[dict], cur: dict) -> dict | None:
    """What "Switch to …" offers: the default from a 4K profile, else the first 4K profile - never the current one."""
    if cur.get("is_4k"):
        want = next((r for r in rows if r["default"]), None)
    else:
        want = next((r for r in rows if r["is_4k"]), None)
    return want if want and want["id"] != cur["id"] else None


def _put(app: str, base: str, headers: dict, entry: dict, pid: int) -> None:
    path = "movie" if app == "radarr" else "series"
    resp = upstream.session("arr").put(f"{base}/api/v3/{path}/{int(entry['id'])}",
                                       json={**entry, "qualityProfileId": pid}, headers=headers, timeout=TIMEOUT)
    if not 200 <= resp.status_code < 300:
        raise RuntimeError(f"HTTP {resp.status_code}")


SWITCH = {"switched": "Switched to {name} · searching",
          "nosearch": "Switched to {name} · couldn't start the search",
          "same": "Already {name}",
          "unknown": "That quality is not offered",
          "unset": "{app} is not connected",
          "missing": "Not in {app}",
          "unreachable": "{app} unreachable",
          "refused": "{app} refused"}
SWITCH_OK = ("switched", "nosearch", "same")


def _switch(kind: str, tmdb: int, pid: int, tvdb: int | None = None) -> tuple[str, int | None]:
    """-> (SWITCH code, HTTP status or None). Reads the entry live (a write path never trusts the lookup cache)."""
    app = _app(kind)
    creds = mr._arr_creds(app)
    if creds is None:
        return "unset", None
    if by_id(profiles(kind), pid) is None:
        return "unknown", None
    base, headers = creds
    try:
        entry = mr._find(app, base, headers, tmdb, tvdb)
        if entry is None:
            return "missing", None
        if entry.get("qualityProfileId") == pid:
            _seen(kind, entry)
            return "same", None
        try:
            _put(app, base, headers, entry, pid)
        finally:
            mr.forget_lookups()
        _seen(kind, entry, pid)
    except Exception as exc:
        why = media_text.why(exc)
        log.warning("%s quality switch failed: %s", app, why)
        return ("refused", int(why[5:])) if why.startswith("HTTP ") else ("unreachable", None)
    try:
        mas._command(app, base, headers, entry)
    except Exception as exc:
        log.warning("%s search after quality switch failed: %s", app, media_text.why(exc))
        return "nosearch", None
    return "switched", None


def words(code: str, kind: str, pid, status: int | None = None) -> str:
    name = next((r["name"] for r in peek(kind) if r["id"] == pid), "that quality")
    word = SWITCH.get(code, SWITCH["unreachable"]).format(name=name, app=NAMES[_app(kind)])
    return word + (f" (HTTP {status})" if code == "refused" and status else "")


def switch(kind: str, tmdb: int, pid: int, tvdb: int | None = None) -> tuple[str, bool]:
    """Move the title to profile `pid` in Radarr / Sonarr and search -> (words, ok)."""
    code, status = _switch(kind, tmdb, pid, tvdb)
    return words(code, kind, pid, status), code in SWITCH_OK


# ---- the request's safety net ----

NET = {"notyet": "{app} hasn't added it yet — check its quality on the title page later",
       "failed": "Couldn't confirm the quality in {app}",
       "unset": "{app} is not connected — the quality rests with Seerr"}


def ensure(kind: str, tmdb: int, pid: int, tvdb: int | None = None) -> str:
    """After a successful request for a non-default profile: read the arr entry back (FOLLOW_TRIES reads, FOLLOW_WAIT s
    apart) and, when its profile differs, PUT it and search. -> "ok" | "set" | "notyet" | "failed" | "unset"."""
    app = _app(kind)
    creds = mr._arr_creds(app)
    if creds is None:
        return "unset"
    base, headers = creds
    try:
        entry = None
        for attempt in range(mas.FOLLOW_TRIES):
            if attempt:
                time.sleep(mas.FOLLOW_WAIT)
            entry = mr._find(app, base, headers, tmdb, tvdb)
            if entry is not None:
                break
        if entry is None:
            if kind == "tv":
                from hub import media_season_state as mss   # late, as _row_pid
                mss.expire()
            return "notyet"
        if entry.get("qualityProfileId") == pid:
            _seen(kind, entry)
            return "ok"
        try:
            _put(app, base, headers, entry, pid)
        finally:
            mr.forget_lookups()
        _seen(kind, entry, pid)
    except Exception as exc:
        log.warning("%s quality safety net failed: %s", app, media_text.why(exc))
        return "failed"
    try:
        mas._command(app, base, headers, entry)
    except Exception as exc:
        log.warning("%s search after the quality safety net failed: %s", app, media_text.why(exc))
    return "set"


def net_note(code, kind: str) -> str | None:
    """The request's done-state warning for a safety-net outcome worth saying, else None."""
    hit = NET.get(str(code or ""))
    return hit.format(app=NAMES[_app(kind)]) if hit else None


flash_keys("quality", "qnet", "qswitch", "qp", "qk")


# ---- the title page: Quality · 1080p  [Switch to 4K] ----

def lazy_href(kind: str | None, tmdb, tvdb, back: str) -> str | None:
    """The hero's lazy-load URL for the quality line, or None (no TMDB id / app not connected)."""
    if kind not in ("movie", "tv") or not isinstance(tmdb, int) or tmdb <= 0 or not mas.connected(kind):
        return None
    q = {"back": back, **({"tvdb": mas._tvdb(tvdb)} if mas._tvdb(tvdb) else {})}
    return f"/media/title/{kind}/{tmdb}/quality?" + urlencode(q)


def block(kind: str, tmdb: int, tvdb, back: str, ask: bool = False, flash: tuple | None = None,
          now: dict | None = None) -> dict | None:
    """What `_quality_block.html` draws, or None (hidden: not in the app, profiles unknown, or an unknown profile).
    `now` (after a switch): the profile just set, instead of a re-read."""
    tvdb = mas._tvdb(tvdb)
    entry = mas.find(kind, tmdb, tvdb, kept=True) if tmdb > 0 else None
    rows = profiles(kind) if entry is not None else []
    cur = now or describe(kind, entry)
    if cur is None or not rows:
        return None
    target = target_of(rows, cur)
    return {"kind": kind, "tmdb": tmdb, "tvdb": tvdb, "back": mas._back(back, kind, tmdb), "current": cur,
            "target": target, "ask": bool(ask and target), "title": str(entry.get("title") or "this title")[:200],
            "app": NAMES[_app(kind)], "flash": flash}


def flash_text(params) -> tuple[str | None, str | None]:
    """(good line, warning line) from `?qswitch=<code>&qp=<id>[&code=<status>]` (the no-JS switch); else (None, None)."""
    code, pid, status = params.get("qswitch") or "", params.get("qp") or "", params.get("code") or ""
    if code not in SWITCH:
        return None, None
    kind = "tv" if params.get("qk") == "tv" else "movie"
    word = words(code, kind, int(pid) if pid.isdigit() and len(pid) <= 9 else None,
                 int(status) if re.fullmatch(r"\d{3}", status) else None)
    return (word, None) if code in SWITCH_OK else (None, word)


@router.get("/media/title/{kind}/{tmdb_id}/quality", response_class=HTMLResponse)
def quality_step(request: Request, kind: str, tmdb_id: int, step: str = "", tvdb: str = "", back: str = ""):
    """htmx: the quality line (idle) or its confirm panel (step=confirm); "" when hidden. Without htmx: back to the page,
    which draws the same panel from `?quality_ask=1`."""
    kind = md._kind(kind)
    page = mas._back(back, kind, tmdb_id)
    if not is_htmx(request):
        return RedirectResponse(page + ("?quality_ask=1" if step == "confirm" else ""), status_code=303)
    q = block(kind, tmdb_id, tvdb, page, ask=step == "confirm")
    return md._partial(request, "_quality_block.html", q=q) if q else HTMLResponse("")


@router.post("/media/title/{kind}/{tmdb_id}/quality", dependencies=[Depends(same_origin)])
async def quality_switch(request: Request, kind: str, tmdb_id: int):
    kind = md._kind(kind)
    form = await form_of(request)
    page = mas._back(form.get("back"), kind, tmdb_id)
    raw, tvdb = str(form.get("profile") or ""), mas._tvdb(form.get("tvdb"))
    pid = int(raw) if raw.isdigit() and len(raw) <= 9 else None
    if pid is None or tmdb_id <= 0:
        code, status = "unknown", None
    else:
        code, status = await run_in_threadpool(_switch, kind, tmdb_id, pid, tvdb)   # off the loop (M-40)
    if is_htmx(request):
        def draw():
            word = words(code, kind, pid, status)
            ok = code in SWITCH_OK
            now = (by_id(peek(kind), pid) if code in ("switched", "nosearch") else None)
            now = {"id": now["id"], "name": now["name"], "is_4k": now["is_4k"]} if now else None
            return block(kind, tmdb_id, tvdb, page, flash=(word, None) if ok else (None, word), now=now), word, ok
        q, word, ok = await run_in_threadpool(draw)
        # the entry or the list went away: the words alone
        q = q or {"current": None, "target": None, "ask": False, "flash": (word, None) if ok else (None, word)}
        return md._partial(request, "_quality_block.html", q=q)
    q = {"qswitch": code, "qk": kind, **({"qp": pid} if pid else {}), **({"code": status} if status else {})}
    return RedirectResponse(f"{page}?" + urlencode(q), status_code=303)


# ---- the Requests page: a "4K" chip after the title (caches only) ----

def _row_pid(kind: str, r: dict):
    if kind == "tv":
        from hub import media_season_state as mss   # late: the Sonarr list this page already keeps
        return (mss._entry(r.get("tvdb_id"), r.get("tmdb_id")) or {}).get("qualityProfileId")
    creds = mr._arr_creds("radarr")
    tmdb = r.get("tmdb_id")
    if creds is None or not isinstance(tmdb, int) or tmdb <= 0:
        return None
    hit, entry = mr.kept("radarr", creds[0], tmdb, None)
    if hit:
        _film(tmdb, (entry or {}).get("qualityProfileId"))
    with _lock:
        return _films.get(tmdb)


def attach(rows: list[dict]) -> None:
    """Each row's `quality`: the profile name when it is not the default, from caches only (the Sonarr series list
    the page keeps for its season words, the films' last seen profiles, the last good profile list). Never a call."""
    for r in rows:
        kind = "tv" if r.get("kind") == "tv" else "movie"
        p = by_id(peek(kind), _row_pid(kind, r))
        r["quality"] = p["name"] if p and not p["default"] else None


def later(rows: list[dict]):
    """The BackgroundTask for the Requests page: the profile lists when stale, and the Radarr lookup of each film row
    not kept yet (at most LATER_MAX). Shows ride on the season state's own Sonarr list. None when nothing is due."""
    kinds = [k for k in ("movie", "tv") if mas.connected(k) and any(
        ("tv" if r.get("kind") == "tv" else "movie") == k for r in rows)]
    stale = []
    for k in kinds:
        with _lock:
            m = _memo.get(k) or {}
        fresh = m.get("at") is not None and _clock() - m["at"] < TTL
        failed = m.get("failed_at") is not None and _clock() - m["failed_at"] < FAIL_TTL
        if not fresh and not failed:
            stale.append(k)
    films = []
    creds = mr._arr_creds("radarr")
    if creds is not None:
        for r in rows:
            tmdb = r.get("tmdb_id")
            if r.get("kind") != "tv" and isinstance(tmdb, int) and tmdb > 0 and not mr.kept("radarr", creds[0], tmdb, None)[0]:
                films.append(tmdb)
        films = list(dict.fromkeys(films))[:LATER_MAX]
    if not stale and not films:
        return None

    def run() -> None:
        for k in stale:
            profiles(k)
        for tmdb in films:
            mas.find("movie", tmdb, None, kept=True)   # logs and swallows its own failures
            hit, entry = mr.kept("radarr", creds[0], tmdb, None)   # a failed read is not kept: the last seen stays
            if hit:
                _film(tmdb, (entry or {}).get("qualityProfileId"))
    run.plan = {"profiles": stale, "films": films}   # tests read it
    return run
