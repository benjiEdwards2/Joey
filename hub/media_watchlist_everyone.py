"""Everyone's watchlist (WP-RQ3, 2026-10-22): B. (owner "you", private front only) sees every watchlist in media.db -
his own, Georgina's and each friend's (`jf:<id>`, added on the media front) - grouped by person, and requests titles
ahead of time as himself (the admin key: Seerr auto-approves).

* GET /media/watchlist/everyone - the page. It renders from media.db and the jellyfin / jellyseerr snapshots only: a
  friend's name comes from an in-process copy of Jellyfin's /Users (NAMES_TTL); while that is cold the group reads
  "Friend" and the read runs after the response (a BackgroundTask), so the next view has the name. Names are never logged.
* A row Not on server has Request: it opens B.'s normal confirm step (`_request_block.html` from GET
  /media/title/{kind}/{tmdb}/request?step=confirm - Quality chips, season ticks) inside the row. That is the existing
  private request path; nothing here sends a single request.
* Request all: GET /media/watchlist/everyone/request-all (htmx; `?all=1` on the page without JS) is the confirm panel for
  the list AS FILTERED - the titles Not on server and not requested, once each however many lists hold them, ONE quality
  chip row per kind, shows = Season 1 only (JY-232: B., 2026-10-27, "go s1"). The POST sends them one by one through media_discover._send (the request
  function the single path uses), at most CAP per submit, then 303s back with words ("Requested 7 · 1 failed: ...").
  The quality safety net (media_quality.ensure) for a non-default pick runs after that answer.

A title is a row under each person whose list holds it (grouping by person is the page; Request all sends it once).
Owner "her" and the media front get the 404 page; hub.guest classifies every route here PRIVATE.
"""
from __future__ import annotations

import logging
import re
import sqlite3
import threading
import time
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool

from hub import guest, media_text, media_watchlist_db as wl, shell
from hub.ids import JELLYFIN_SNAPSHOT_ID, JELLYSEERR_SNAPSHOT_ID
from hub.media_watchlist import on_server_keys
from hub.media_write import flash_keys, form_of, is_htmx, owner_for, same_origin
from hub.shell import templates  # the ONE shared Jinja env (M-23 / H-31)

log = logging.getLogger("hub.media_watchlist_everyone")
router = APIRouter()

PAGE = "/media/watchlist/everyone"
ALL = PAGE + "/request-all"
CAP = 20             # Request all: titles sent per submit (sequential; the rest wait for the next submit)
NAMES_TTL = 3600     # s: Jellyfin display names
NAMES_RETRY = 60     # s: a failed /Users read is not retried before this
SENT_TTL = 3600      # s: a title Request all sent reads Requested until the jellyseerr snapshot has it
FRIEND = "Friend"
HOUSE = {"you": "You", "her": "Georgina"}
KINDS = {"movie": "Films", "tv": "TV"}
FAILED_CODES = ("exists", "declined", "network")
SHOW_SEASONS = [1]   # JY-232 (B., 2026-10-27: "JY-232: go s1"): Request all sends a show as Season 1 only

flash_keys("rqn", "rqf", "rql")   # Request all's answer on the page after the 303

_lock = threading.Lock()
_names: dict = {}                 # {"at": t, "map": {jf id: name}, "failed_at": t}
_sent: dict[tuple[str, int], float] = {}
_clock = time.monotonic           # test seam


def clear() -> None:
    with _lock:
        _names.clear()
        _sent.clear()


# ---- friend names (a cache; never read before a response) ----

def names() -> dict:
    """{jf id: display name} as last read; {} while cold."""
    with _lock:
        return dict(_names.get("map") or {})


def names_due() -> bool:
    with _lock:
        at, failed = _names.get("at"), _names.get("failed_at")
    now = _clock()
    if failed is not None and now - failed < NAMES_RETRY:
        return False
    return at is None or now - at >= NAMES_TTL


def fill_names() -> None:
    """Read Jellyfin /Users into the cache (the page's BackgroundTask). Logs carry the exception TYPE / status only."""
    from hub import media_jellyfin
    creds = media_jellyfin.creds()
    if creds is None:
        return
    try:
        users = media_jellyfin.get(*creds, "/Users")
        if not isinstance(users, list):
            raise ValueError("not a list")
    except Exception as exc:
        log.warning("jellyfin user names skipped: %s", media_text.why(exc))
        with _lock:
            _names["failed_at"] = _clock()
        return
    out = {}
    for u in users:
        uid = str(u.get("Id") or "").replace("-", "").lower() if isinstance(u, dict) else ""
        name = str(u.get("Name") or "").strip()[:60] if isinstance(u, dict) else ""
        if re.fullmatch(r"[0-9a-f]{32}", uid) and name:
            out[uid] = name
    with _lock:
        _names.update(at=_clock(), map=out, failed_at=None)


def label_of(owner: str, known: dict) -> str:
    return HOUSE.get(owner) or known.get(owner[3:]) or FRIEND


# ---- the gate ----

def _allowed(request: Request) -> bool:
    """Owner "you" on the private front only (the media front never serves it: hub.guest has it PRIVATE too)."""
    return not guest.is_media() and owner_for(request) == "you"


# ---- the rows ----

def _sent_keys() -> set:
    now = _clock()
    with _lock:
        for k in [k for k, at in _sent.items() if now - at >= SENT_TTL]:
            del _sent[k]
        return set(_sent)


def _filters(who, kind) -> tuple[str, str]:
    who = str(who or "")
    who = who if who in HOUSE or re.fullmatch(r"jf:[0-9a-f]{32}", who) else ""
    kind = str(kind or "")
    return who, kind if kind in KINDS else ""


def build(data: dict | None, who: str, kind: str) -> dict:
    """Groups (You, Georgina, then friends by name) of the filtered rows, each with its status word and Request flag,
    and `pending`: the titles Request all would send (deduplicated, in page order). No upstream call."""
    try:
        rows, failed = wl.all_rows(kind or None), False
    except (sqlite3.Error, OSError) as exc:
        log.warning("everyone's watchlist read failed: %s", type(exc).__name__)
        rows, failed = [], True
    on_keys = {k: on_server_keys(data, k) for k in KINDS}
    from hub.media_requests import snapshot_rows  # late, as media_watchlist: a removed request stops showing at once
    words = wl.request_words(snapshot_rows(shell.get_snapshots(), JELLYSEERR_SNAPSHOT_ID))
    sent, known = _sent_keys(), names()
    owners = list(dict.fromkeys(r["owner"] for r in rows if r["owner"] in HOUSE or str(r["owner"]).startswith("jf:")))
    house = [o for o in HOUSE if o in owners]
    friends = sorted((o for o in owners if o not in HOUSE), key=lambda o: (label_of(o, known).lower(), o))
    people = [{"owner": o, "label": label_of(o, known)} for o in house + friends]
    if who not in owners:
        who = ""
    groups, pending, seen = [], [], set()
    for p in people:
        if who and p["owner"] != who:
            continue
        out = []
        for r in rows:
            if r["owner"] != p["owner"] or r["kind"] not in KINDS:
                continue
            word = wl.status_word(r, on_keys[r["kind"]], words)
            key = (r["kind"], r["tmdb_id"])
            if word == wl.NOT_ON and key in sent:
                word = "Requested"
            can = word == wl.NOT_ON
            out.append({**r, "status_word": word, "can_request": can, "added_text": media_text.short_date(r["added_at"]),
                        "href": f"/media/title/{r['kind']}/{r['tmdb_id']}"})
            if can and key not in seen:
                seen.add(key)
                pending.append(out[-1])
        if out:
            groups.append({**p, "rows": out})
    shown = sum(len(g["rows"]) for g in groups)
    missing = sum(1 for g in groups for r in g["rows"] if r["status_word"] != wl.ON_DISK)
    return {"groups": groups, "people": people, "who": who, "kind": kind, "pending": pending, "failed": failed,
            "friends_cold": bool(friends) and names_due(),
            "head_line": f"{media_text.plural(shown, 'title')} · {missing} not on the server"}


def href(who: str = "", kind: str = "", **extra) -> str:
    q = {k: v for k, v in (("who", who), ("kind", kind), *extra.items()) if v}
    return PAGE + (f"?{urlencode(q)}" if q else "")


def flash_words(params) -> tuple[str | None, str | None]:
    """(good line, warning line) from `?rqn=<sent>&rqf=<code>-<n>.<code>-<n>&rql=<left>` after Request all."""
    raw_n, raw_f, raw_l = params.get("rqn") or "", params.get("rqf") or "", params.get("rql") or ""
    if not raw_n.isdigit() and not raw_f:
        return None, None
    from hub.media_discover import ERRORS
    fails = []
    for part in raw_f.split("."):
        code, _, n = part.partition("-")
        if code in FAILED_CODES and n.isdigit() and int(n) > 0:
            fails.append(f"{n} failed: {ERRORS[code]}")
    sent = int(raw_n) if raw_n.isdigit() and len(raw_n) <= 3 else 0
    left = f"{raw_l} left · Request all again" if raw_l.isdigit() and int(raw_l) > 0 else None
    words = " · ".join(p for p in [f"Requested {sent}" if sent else None, *fails, left] if p) or "Nothing to request"
    return (words, None) if not fails else (None, words)


def _panel_ctx(ctx: dict) -> dict:
    """The Request all panel: the first CAP titles, one quality chip row per kind present (an explicit step: the
    profile lists may be read here, as the single Request confirm reads them)."""
    from hub import media_quality   # late: it imports media_discover
    batch = ctx["pending"][:CAP]
    kinds = [k for k in KINDS if any(r["kind"] == k for r in batch)]
    films, shows = (sum(1 for r in batch if r["kind"] == k) for k in KINDS)
    parts = [media_text.plural(films, "film") if films else None,
             f"{media_text.plural(shows, 'show')} (Season 1)" if shows else None]
    return {"batch": batch, "more": max(0, len(ctx["pending"]) - CAP), "summary": " · ".join(p for p in parts if p),
            "qrows": [{"kind": k, "label": KINDS[k], "profiles": media_quality.choices(k)} for k in kinds],
            "who": ctx["who"], "kind": ctx["kind"], "back": href(ctx["who"], ctx["kind"])}


# ---- routes ----

@router.get(PAGE, response_class=HTMLResponse)
def everyone_page(request: Request, who: str = "", kind: str = "", all: str = ""):
    if not _allowed(request):
        return shell.not_found_page(request)
    from hub import media_pages   # function-level, as media_watchlist (media_pages reaches back)
    who, kind = _filters(who, kind)
    request.state.media_section = "server"   # Activity is lit (no tab of its own, like a title page)
    holder = {}

    def page_ctx(data, view):
        ctx = build(data, who, kind)
        holder["cold"] = ctx["friends_cold"]
        good, warn = flash_words(request.query_params)
        ctx.update(flash=good, flash_warn=warn, who_on=ctx["who"], kind_on=ctx["kind"],   # `who` is the shell's identity
                   all_href=href(ctx["who"], ctx["kind"], all="1"),
                   all_get=ALL + "?" + urlencode({"who": ctx["who"], "kind": ctx["kind"]}),
                   chip_href=href, panel=_panel_ctx(ctx) if all == "1" and ctx["pending"] else None)
        return ctx

    resp = media_pages._detail_page(request, "media_watchlist_everyone.html", JELLYFIN_SNAPSHOT_ID, page_ctx,
                                    always_build=True)
    if holder.get("cold"):
        resp.background = BackgroundTask(fill_names)
    return resp


@router.get(ALL, response_class=HTMLResponse)
def request_all_panel(request: Request, who: str = "", kind: str = ""):
    """htmx: the confirm panel; without htmx, the page with the panel drawn (`?all=1`)."""
    if not _allowed(request):
        return shell.not_found_page(request)
    who, kind = _filters(who, kind)
    if not is_htmx(request):
        return RedirectResponse(href(who, kind, all="1"), status_code=303)
    snap = shell.get_snapshots(request=request).get(JELLYFIN_SNAPSHOT_ID)
    ctx = build(snap.data if snap else None, who, kind)
    return templates.TemplateResponse(request, "_wl_request_all.html", {"p": _panel_ctx(ctx)})


@router.post(ALL, dependencies=[Depends(same_origin)])
async def request_all(request: Request):
    if not _allowed(request):
        raise HTTPException(404, "No page here")
    return await run_in_threadpool(_request_all, request, await form_of(request))


def send_all(batch: list[dict], profiles: dict) -> dict:
    """Each title through media_discover._send (the single path's request function) as B. - the admin key, no
    X-Api-User - films with seasons [] and shows with SHOW_SEASONS (Season 1 only, JY-232). -> {"sent": n, "failed": {code: n}, "ensure": [...]}."""
    from hub import media_discover as md, media_requests
    sent, failed, net = 0, {}, []
    for r in batch:
        kind, tmdb = r["kind"], int(r["tmdb_id"])
        prof = profiles.get(kind)
        code = md._send(kind, tmdb, list(SHOW_SEASONS) if kind == "tv" else [], prof["id"] if prof else None)
        if code is None:
            sent += 1
            with _lock:
                _sent[(kind, tmdb)] = _clock()
            md._cache.pop(f"film:/api/v1/{kind}/{tmdb}", None)   # the title page re-reads its request status
            if prof and not prof["default"]:
                net.append((kind, tmdb, prof["id"]))
        else:
            failed[code] = failed.get(code, 0) + 1
    if sent:
        media_requests.forget_lookups()   # as the single path: Search now re-reads Radarr / Sonarr
    return {"sent": sent, "failed": failed, "ensure": net}


def _ensure_all(net: list[tuple]) -> None:
    """After the answer: the quality safety net for each title sent with a non-default profile (it logs its own failures)."""
    from hub import media_quality
    for kind, tmdb, pid in net:
        media_quality.ensure(kind, tmdb, pid)


def _request_all(request: Request, f: dict):
    from hub import media_quality
    who, kind = _filters(f.get("who"), f.get("kind"))
    snap = shell.get_snapshots(request=request).get(JELLYFIN_SNAPSHOT_ID)
    ctx = build(snap.data if snap else None, who, kind)
    batch = ctx["pending"][:CAP]
    profiles = {k: media_quality.pick(k, f.get(f"profile_{k}") or None)
                for k in KINDS if any(r["kind"] == k for r in batch)}   # 422 for a profile the app does not offer
    out = send_all(batch, profiles)
    left = max(0, len(ctx["pending"]) - len(batch))
    q = {"rqn": out["sent"], "rqf": ".".join(f"{c}-{n}" for c, n in out["failed"].items()), "rql": left}
    resp = RedirectResponse(href(ctx["who"], ctx["kind"], **{k: str(v) for k, v in q.items() if v or k == "rqn"}),
                            status_code=303)
    if out["ensure"]:
        resp.background = BackgroundTask(_ensure_all, out["ensure"])
    return resp
