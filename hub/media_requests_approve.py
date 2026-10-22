"""Approve / Decline a request (WP-RQ1, 2026-10-22): the Requests page shows B. every Seerr request (friends',
Georgina's, his own; pending first) and, on each PENDING row, what was asked for - the quality profile (the request's
`profileId`, named through media_quality's cached list; null = the Seerr server's default) and, for TV, the seasons -
with Approve (quality chips + season ticks, as the Request confirm) and Decline (an inline confirm, never a browser
dialog). Seerr stays the record. Admin `X-Api-Key` (media_discover._creds), the kept "seerr" session; verified against
Seerr v3.5.0 `server/routes/request.ts` on 2026-10-22:

* Approve: `GET /api/v1/request/{id}` (live: still pending? what is stored?). When the quality or the seasons differ,
  `PUT /api/v1/request/{id}` first. Seerr's edit assigns `serverId`, `profileId`, `rootFolder`, `languageProfileId`
  (TV) and `tags` straight from the body - nothing is kept from the stored request - so the stored values ride along
  unchanged; `seasons` is a `number[]` (missing or empty -> a 500), `userId` is left out (the requester is kept). 202 =
  "No seasons available to request" (every ticked season is held by another request or on disk). Only then
  `POST /api/v1/request/{id}/approve`. Nothing changed -> no PUT (an unneeded edit could only fail: quotas, 202).
  After a non-default profile, media_quality.ensure is the safety net that the arr entry carries it.
* Decline: `POST /api/v1/request/{id}/decline`. Both answer 409 once the request is no longer pending.

Only owner "you" on the private front: the routes are PRIVATE in hub.guest (the media front 404s them) and 403 for
her. A decision shows at once: the row is kept in memory as Approved / Declined (media_hidden's clock: until a
jellyseerr snapshot taken after it). Failures are words; logs carry an HTTP status or an exception TYPE only.
"""
from __future__ import annotations

import logging
import threading
from urllib.parse import parse_qs, urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool

from hub import guest, media_discover as md, media_hidden, media_quality, media_requests as mr, upstream
from hub.media_write import MAX_BODY, bad, flash_keys, owner_for, same_origin

log = logging.getLogger("hub.media_requests_approve")
router = APIRouter()

TIMEOUT = mr.TIMEOUT
GROUP = "request-decided"          # media_hidden's clock for the in-memory decision
KEEP = ("serverId", "rootFolder", "tags")   # stored values the edit PUT must carry (Seerr assigns them from the body)
KEEP_TV = ("languageProfileId",)
_decided: dict[int, dict] = {}     # request id -> {"status_text", "profile_id", "seasons"?}
_lock = threading.Lock()

flash_keys("decided", "dp", "ds", "qnet")


def clear() -> None:
    with _lock:
        _decided.clear()


# ---- who may decide ----

def can_decide(request: Request) -> bool:
    """Owner "you" on the private front only (the media front never serves these routes; her view never decides)."""
    return not guest.is_media() and owner_for(request) == "you"


def _owner_only(request: Request) -> None:
    if guest.is_media():   # the GuestGate already 404s these paths; a backstop that fails closed
        raise HTTPException(404, "Not found")
    if owner_for(request) != "you":
        raise HTTPException(403, "Only the admin can approve or decline requests")


# ---- words ----

def season_words(nums) -> str | None:
    """[1, 2, 4] -> "Seasons 1–2, 4"; [3] -> "Season 3"; [] / None -> None."""
    nums = sorted({n for n in nums or [] if isinstance(n, int) and not isinstance(n, bool) and n >= 0})
    if not nums:
        return None
    spans: list[list[int]] = []
    for n in nums:
        if spans and n == spans[-1][1] + 1:
            spans[-1][1] = n
        else:
            spans.append([n, n])
    return ("Season " if len(nums) == 1 else "Seasons ") + ", ".join(str(a) if a == b else f"{a}–{b}" for a, b in spans)


def _profile(kind: str, pid) -> dict | None:
    """The cached profile a request names - its id, or the default for null - else None. Never a call."""
    rows = media_quality.peek(kind)
    if pid is None:
        return next((r for r in rows if r["default"]), None)
    return media_quality.by_id(rows, pid)


def asked(row: dict) -> str | None:
    """What the requester chose, in words: "4K · Seasons 1–2" (the profile only while the list is cached)."""
    kind = "tv" if row.get("kind") == "tv" else "movie"
    p = _profile(kind, row.get("profile_id"))
    parts = [p["name"] if p and len(media_quality.peek(kind)) > 1 else None,
             season_words(row.get("seasons")) if kind == "tv" else None]
    return " · ".join(x for x in parts if x) or None


def flash_text(params) -> str | None:
    """The good line after a decision: "Approved · 4K · Seasons 1–2" / "Declined"; anything odd -> None."""
    what = params.get("decided") or ""
    if what == "declined":
        return "Declined"
    if what != "approved":
        return None
    kind = "tv" if params.get("ds") is not None else "movie"
    raw = params.get("dp") or ""
    p = media_quality.by_id(media_quality.peek(kind), int(raw)) if raw.isdigit() and len(raw) <= 9 else None
    seasons = [int(x) for x in (params.get("ds") or "").split(",") if x.isdigit() and len(x) <= 3]
    return " · ".join(x for x in ("Approved", p["name"] if p else None, season_words(seasons)) if x)


def net_text(params) -> str | None:
    """The warning line when the quality safety net could not confirm the profile, else None."""
    if params.get("decided") != "approved":
        return None
    return media_quality.net_note(params.get("qnet"), "tv" if params.get("ds") is not None else "movie")


# ---- the page: the decision overlay + each pending row's form (caches only) ----

def overlay(rows: list[dict], counts: dict, updated_at=None) -> tuple[list[dict], dict]:
    """Rows decided here since the snapshot was taken read as decided (copies), and the counts follow them."""
    if not media_hidden.any_in(GROUP):
        return rows, counts
    counts, out = dict(counts), []
    for r in rows:
        rid = r.get("id")
        with _lock:
            d = _decided.get(rid) if isinstance(rid, int) else None
        if d and media_hidden.is_hidden(GROUP, rid, updated_at):
            if r.get("status_text") == "Pending" and counts.get("pending"):
                counts["pending"] -= 1
                key = "approved" if d["status_text"] == "Approved" else "declined"
                counts[key] = counts.get(key, 0) + 1
            r = {**r, **d}
        out.append(r)
    return out, counts


def attach(rows: list[dict], decide: bool) -> None:
    """Each row's `asked` words; with `decide`, each pending row's `decide` form context (the quality chips from the
    cached profile list - the requested one checked, else the default - and, for TV, the requested seasons ticked until
    the lazy season list arrives). Never a call."""
    for r in rows:
        kind = "tv" if r.get("kind") == "tv" else "movie"
        pending = r.get("status_text") == "Pending"
        r["asked"] = asked(r) if pending else None
        if not (decide and pending and isinstance(r.get("id"), int)):
            r["decide"] = None
            continue
        rows_p = media_quality.peek(kind)
        want = _profile(kind, r.get("profile_id")) or next((p for p in rows_p if p["default"]), None)
        chips = [{**p, "checked": want is not None and p["id"] == want["id"]} for p in rows_p] if len(rows_p) > 1 else []
        seasons = [{"number": n, "name": f"Season {n}", "ticked": True, "disabled": False, "status_word": None}
                   for n in r.get("seasons") or [] if n >= 1] if kind == "tv" else []
        r["decide"] = {"profiles": chips, "seasons": seasons}


# ---- the lazy season list (TV) ----

def _row(rid: int) -> dict | None:
    row, snap = mr._row(rid)
    if row is None:
        return None
    rows, _ = overlay([row], {}, snap.updated_at if snap else None)
    return rows[0]


def season_list(row: dict) -> list[dict]:
    """The show's seasons from Seerr's title body (the film page's cached read) with the requested ones ticked; a season
    another request holds or that is on disk is shown but cannot be ticked (Seerr's edit would drop it). Specials are
    left out. Unreadable -> the requested seasons alone."""
    from hub import media_film   # late: a heavy module, needed only for this fragment
    asked_for = set(row.get("seasons") or [])
    data = media_film._cget(f"/api/v1/tv/{row.get('tmdb_id')}") if isinstance(row.get("tmdb_id"), int) else None
    if not isinstance(data, dict):
        return [{"number": n, "name": f"Season {n}", "ticked": True, "disabled": False, "status_word": None}
                for n in sorted(asked_for) if n >= 1]
    info = data.get("mediaInfo") if isinstance(data.get("mediaInfo"), dict) else {}
    out = []
    for s in md._seasons(data, info):
        if s["number"] < 1:
            continue
        mine = s["number"] in asked_for
        out.append({"number": s["number"], "name": s["name"], "ticked": mine,
                    "disabled": not mine and s["code"] not in (None, 1, 7),
                    "status_word": None if mine or s["code"] in (None, 1, 7) else s["status_word"]})
    return out


@router.get("/media/requests/{rid}/seasons", response_class=HTMLResponse)
def seasons_part(request: Request, rid: int):
    """htmx: a pending TV request's season ticks for its Approve panel."""
    _owner_only(request)
    row = _row(rid) if rid > 0 else None
    if row is None or row.get("kind") != "tv" or row.get("status_text") != "Pending":
        raise HTTPException(404, "No such request")
    return md._partial(request, "_request_seasons.html", seasons=season_list(row))


# ---- the writes ----

def _seerr(method: str, path: str, **kw):
    creds = md._creds()
    return getattr(upstream.session("seerr"), method)(f"{creds[0]}{path}", headers={"X-Api-Key": creds[1]},
                                                      timeout=TIMEOUT, **kw)


def _status_of(resp) -> tuple[str | None, int | None]:
    """A Seerr answer to a write -> (None, None) on 2xx, else (mr.ERRORS code, HTTP status or None)."""
    if 200 <= resp.status_code < 300:
        return None, None
    if resp.status_code == 404:
        return "missing", None
    if resp.status_code == 409:
        return "notpending", None
    return "refused", resp.status_code


def _int_list(values) -> list[int]:
    return sorted({v for v in values if isinstance(v, int) and not isinstance(v, bool)}) if isinstance(values, list) else []


def approve(rid: int, kind: str, prof: dict | None, seasons: list[int]) -> tuple[str | None, int | None, dict]:
    """Edit (only when something differs) then approve -> (error code or None, HTTP status or None, what was approved:
    {"profile": the profile in force or None, "seasons": [...] (TV)})."""
    done: dict = {"profile": prof, "seasons": seasons}
    if md._creds() is None:
        return "unset", None, done
    try:
        resp = _seerr("get", f"/api/v1/request/{rid}")
        code, status = _status_of(resp)
        if code:
            log.warning("seerr request read refused: HTTP %s", resp.status_code)
            return code, status, done
        live = resp.json()
        if not isinstance(live, dict) or live.get("status") != 1:
            return "notpending", None, done
        live_pid = live.get("profileId") if isinstance(live.get("profileId"), int) else None
        live_seasons = _int_list([s.get("seasonNumber") for s in live.get("seasons") or [] if isinstance(s, dict)])
        if prof is None:   # no chips were sent (one profile / list unknown): what Seerr has stays
            done["profile"] = _profile(kind, live_pid)
        pid_changed = prof is not None and prof["id"] != live_pid and not (live_pid is None and prof["default"])
        seasons_changed = kind == "tv" and seasons != live_seasons
        if pid_changed or seasons_changed:
            body: dict = {"mediaType": kind}
            for k in KEEP + (KEEP_TV if kind == "tv" else ()):
                if live.get(k) is not None:
                    body[k] = live[k]
            pid = prof["id"] if pid_changed else live_pid
            if pid is not None:
                body["profileId"] = pid
            if kind == "tv":
                body["seasons"] = seasons
            resp = _seerr("put", f"/api/v1/request/{rid}", json=body)
            if resp.status_code == 202:   # Seerr: "No seasons available to request"
                return "noseasons", None, done
            code, status = _status_of(resp)
            if code:
                log.warning("seerr request edit refused: HTTP %s", resp.status_code)
                return code, status, done
        resp = _seerr("post", f"/api/v1/request/{rid}/approve")
        code, status = _status_of(resp)
        if code:
            log.warning("seerr request approve refused: HTTP %s", resp.status_code)
        return code, status, done
    except Exception as exc:  # type only — requests errors embed the URL and key
        log.warning("seerr request approve failed: %s", type(exc).__name__)
        return "unreachable", None, done


def decline(rid: int) -> tuple[str | None, int | None]:
    if md._creds() is None:
        return "unset", None
    try:
        resp = _seerr("post", f"/api/v1/request/{rid}/decline")
    except Exception as exc:  # type only
        log.warning("seerr request decline failed: %s", type(exc).__name__)
        return "unreachable", None
    code, status = _status_of(resp)
    if code:
        log.warning("seerr request decline refused: HTTP %s", resp.status_code)
    return code, status


def _after(row: dict, decided: dict) -> None:
    """The decision shows at once, and every cache that read the request's state forgets it."""
    rid = row["id"]
    with _lock:
        _decided[rid] = decided
    media_hidden.hide(GROUP, rid)
    md._cache.pop(f"film:/api/v1/{row.get('kind')}/{row.get('tmdb_id')}", None)   # the film page re-reads its status
    mr.forget_lookups()
    from hub import media_guest_requests as mgr   # late: it imports media_discover
    mgr.forget_mine(row.get("requested_by_id"))   # the friend's own list says Approved / Declined at once


def _form(body: bytes) -> dict[str, list[str]]:
    if len(body) > MAX_BODY:
        raise bad("Too large")
    return parse_qs(body.decode("utf-8", "replace"), keep_blank_values=True)


def _to(**params) -> RedirectResponse:
    return RedirectResponse(f"{mr.PAGE}?" + urlencode(params), status_code=303)


def _failed(code: str, status: int | None) -> RedirectResponse:
    return _to(error=code, **({"code": status} if status else {}))


@router.post("/media/requests/{rid}/approve", dependencies=[Depends(same_origin)])
async def approve_request(request: Request, rid: int):
    _owner_only(request)
    form = _form(await request.body())
    return await run_in_threadpool(_approve, rid, form)


def _approve(rid: int, form: dict[str, list[str]]):
    row = _row(rid) if rid > 0 else None
    if row is None:
        return _to(error="missing")
    if row.get("status_text") != "Pending":
        return _to(error="notpending")
    kind = "tv" if row.get("kind") == "tv" else "movie"
    raw = (form.get("profile") or [""])[-1]
    prof = media_quality.pick(kind, raw or None)   # 422 "Pick a quality" for an id the app does not offer
    seasons: list[int] = []
    if kind == "tv":
        try:
            seasons = sorted({int(v) for v in form.get("seasons") or []})
        except ValueError:
            raise bad("Pick at least one season") from None
        if not seasons or seasons[0] < 1 or len(seasons) > 100:
            raise bad("Pick at least one season")
    code, status, done = approve(rid, kind, prof, seasons)
    if code:
        return _failed(code, status)
    p = done["profile"]
    _after(row, {"status_text": "Approved", "profile_id": p["id"] if p else row.get("profile_id"),
                 **({"seasons": seasons} if kind == "tv" else {})})
    qnet = None
    if p and not p["default"] and isinstance(row.get("tmdb_id"), int) and row["tmdb_id"] > 0:
        # WP-R1's safety net: Seerr hands the title to Radarr / Sonarr on approve; make sure it carries the profile
        qnet = media_quality.ensure(kind, row["tmdb_id"], p["id"], row.get("tvdb_id") if kind == "tv" else None)
    return _to(decided="approved", **({"dp": p["id"]} if p else {}),
               **({"ds": ",".join(map(str, seasons))} if kind == "tv" else {}),
               **({"qnet": qnet} if media_quality.net_note(qnet, kind) else {}))


@router.post("/media/requests/{rid}/decline", dependencies=[Depends(same_origin)])
def decline_request(request: Request, rid: int):
    _owner_only(request)
    row = _row(rid) if rid > 0 else None
    if row is None:
        return _to(error="missing")
    if row.get("status_text") != "Pending":
        return _to(error="notpending")
    code, status = decline(rid)
    if code:
        return _failed(code, status)
    _after(row, {"status_text": "Declined"})
    return _to(decided="declined")
