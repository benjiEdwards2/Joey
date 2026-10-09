"""Move on from Continue watching (2026-10-08): "Mark watched" and "Reset progress" on resume items — the hub
and Media home Continue watching shelves, Activity → Live's Up next, and the film / episode page when it shows
"Resume ▶". Live Jellyfin writes, server-side only (env JELLYFIN_URL + JELLYFIN_API_KEY):

- Mark watched:   POST /UserPlayedItems/{id}?userId={uid}                         (Jellyfin 10.9+)
                  else POST /Users/{uid}/PlayedItems/{id}                         (older servers: a 404/405 falls back)
- Reset progress: POST /UserItems/{id}/UserData?userId={uid} {"PlaybackPositionTicks": 0}
                  else POST /Users/{uid}/Items/{id}/UserData

The Jellyfin user is the viewer's: "you" = JELLYFIN_USER (media_files._user_id: by name, else the first admin),
"her" = exactly JELLYFIN_USER_HER (never a fallback to the admin). A signed-in viewer always acts as themselves;
only the local, not-signed-in "both" view may name the owner of a row (the form's `owner`).

After success the item leaves the cached resume list at once (media_hidden, until a newer jellyfin snapshot) and the
page flashes "Marked watched" / "Progress reset". A watched mark reaches Joey's diary through the usual path: the next
jellyfin sweep's history (IsPlayed, by DatePlayed) carries it and the diary page's sync_diary_from_history inserts it.
Failures are words; logs carry an HTTP status or exception type only.

Watched / unwatched (media-ux3, 2026-10-08): the same routes serve the film / episode page toggle, each episode row
and a season's header (`scope=season`, the season's Jellyfin id — Jellyfin marks all its episodes):
- Mark unwatched: DELETE /UserPlayedItems/{id}?userId={uid}  else DELETE /Users/{uid}/PlayedItems/{id}
Marking watched hides the item (and, for a season, each of its episodes) from Continue watching until the next sweep;
a season marked unwatched hides its in-progress episodes (their saved positions are gone). Unwatched never deletes a
diary entry. The redirect may carry `season=N` so the episode list reopens that season.

Hide (media-ux2, 2026-10-08): a Next Up suggestion (remaining_text "Next episode") also offers "Hide":
POST /media/resume/{id}/hide stores (owner, series, suggested episode) in media.db `nextup_hidden` (no Jellyfin call)
and apply_hidden drops that suggestion everywhere until Next Up suggests a different episode. Flash "Hidden".
"""
from __future__ import annotations

import logging
import re
from urllib.parse import urlencode

import requests
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from starlette.concurrency import run_in_threadpool

from hub import media_db, media_files, media_hidden, media_item, media_jellyfin as jellyfin, shell
from hub.media_write import flash_keys, form_of, safe_back, same_origin

log = logging.getLogger("hub.media_resume")
router = APIRouter()

GROUP = "resume"
TIMEOUT = 8
DEFAULT_BACK = "/media/playing"
NEXT_EPISODE = "Next episode"   # the connector's word for a next-up row (nothing to reset)
DONE = {"watched": "Marked watched", "unwatched": "Marked unwatched", "reset": "Progress reset", "hide": "Hidden",
        "season-watched": "Season marked watched", "season-unwatched": "Season marked unwatched"}
ERRORS = {"jfunset": "Jellyfin is not connected", "jfuser": "No Jellyfin user for this profile",
          "jfdown": "Couldn't reach Jellyfin", "jfrefused": "Jellyfin refused",
          "hidefail": "Couldn't hide it"}
FALLBACK_STATUS = (404, 405)


def clear_cache() -> None:
    jellyfin.clear_cache()   # her user id now lives in media_jellyfin's cache


# ---- what the pages show ----

def key(owner: str, jf_id) -> str:
    return f"{owner}:{jf_id}"


def hide_rows(rows, owner: str, updated_at=None) -> list:
    return media_hidden.visible(GROUP, rows, lambda r: key(owner, r.get("jf_id")) if r.get("jf_id") else None, updated_at)


def series_of(row: dict) -> str | None:
    """The series key a Next Up row belongs to (`show_key`, else the episode row's item_key, which is its series)."""
    key = str((row or {}).get("show_key") or (row or {}).get("item_key") or "")
    return key if media_db.KEY_RE.match(key) else None


def drop_dismissed(rows, owner: str, dismissed: dict) -> list:
    """Next Up suggestions the owner hid (media-ux2): a row goes while its series' hidden episode IS the one
    suggested; once Next Up suggests a different episode the note no longer matches and the row shows again.
    Resume rows (a saved position) are never hidden this way."""
    if not dismissed:
        return list(rows or [])
    return [r for r in rows or [] if not (isinstance(r, dict) and not in_progress(r) and r.get("jf_id")
                                          and dismissed.get((owner, series_of(r))) == str(r["jf_id"]))]


def apply_hidden(snaps: dict, snapshot_id: str = "jellyfin") -> dict:
    """The snapshots with marked / reset items dropped from B.'s `up_next` and Georgina's `her.up_next` (until a
    newer sweep), and Next Up suggestions each owner hid (media.db, until the suggestion changes). Untouched (same
    objects) when nothing is hidden, so the common read costs one small query."""
    snap = snaps.get(snapshot_id)
    if snap is None or not isinstance(snap.data, dict):
        return snaps
    dismissed = media_db.next_up_hidden()
    if not dismissed and not media_hidden.any_in(GROUP):
        return snaps
    from dataclasses import replace
    data = dict(snap.data)
    data["up_next"] = drop_dismissed(hide_rows(data.get("up_next"), "you", snap.updated_at), "you", dismissed)
    if isinstance(data.get("her"), dict):
        her = drop_dismissed(hide_rows(data["her"].get("up_next"), "her", snap.updated_at), "her", dismissed)
        data["her"] = {**data["her"], "up_next": her}
    return {**snaps, snapshot_id: replace(snap, data=data)}


def in_progress(row: dict) -> bool:
    """A resume row (position saved) rather than a next-up suggestion."""
    text = str((row or {}).get("remaining_text") or "")
    return bool(text) and text != NEXT_EPISODE


flash_keys("done", "error", "code")


def flash_text(params) -> tuple[str | None, str | None]:
    done, err, code = params.get("done") or "", params.get("error") or "", params.get("code") or ""
    if done in DONE:
        return DONE[done], None
    if err in ERRORS:
        return None, ERRORS[err] + (f" (HTTP {code})" if err == "jfrefused" and re.fullmatch(r"\d{3}", code) else "")
    return None, None


# ---- Jellyfin ----

def _her_user_id(base: str, headers: dict) -> str | None:
    """Georgina's Jellyfin user id: exactly JELLYFIN_USER_HER (media_jellyfin), never the admin."""
    return jellyfin.user_id("her", base, headers, lambda b, h: media_files._get(b, h, "/Users"))


def _post(base, headers, path, params=None, body=None):
    return requests.post(f"{base}{path}", params=params, json=body, headers=headers, timeout=TIMEOUT)


def _delete(base, headers, path, params=None):
    return requests.delete(f"{base}{path}", params=params, headers=headers, timeout=TIMEOUT)


def act(action: str, owner: str, jf_id: str) -> tuple[str | None, int | None]:
    """Run one action as the owner's Jellyfin user -> (None, None) on success, else (ERRORS code, HTTP status)."""
    creds = media_files._creds()
    if creds is None:
        return "jfunset", None
    base, headers = creds
    try:
        uid = media_files._user_id(base, headers) if owner == "you" else _her_user_id(base, headers)
        if not uid:
            return "jfuser", None
        if action == "watched":
            resp = _post(base, headers, f"/UserPlayedItems/{jf_id}", {"userId": uid})
            if resp.status_code in FALLBACK_STATUS:   # a server older than 10.9
                resp = _post(base, headers, f"/Users/{uid}/PlayedItems/{jf_id}")
        elif action == "unwatched":
            resp = _delete(base, headers, f"/UserPlayedItems/{jf_id}", {"userId": uid})
            if resp.status_code in FALLBACK_STATUS:
                resp = _delete(base, headers, f"/Users/{uid}/PlayedItems/{jf_id}")
        else:
            body = {"PlaybackPositionTicks": 0}
            resp = _post(base, headers, f"/UserItems/{jf_id}/UserData", {"userId": uid}, body)
            if resp.status_code in FALLBACK_STATUS:
                resp = _post(base, headers, f"/Users/{uid}/Items/{jf_id}/UserData", None, body)
    except Exception as exc:  # type only — requests errors embed the URL
        log.warning("jellyfin %s failed: %s", action, type(exc).__name__)
        return "jfdown", None
    if 200 <= resp.status_code < 300:
        return None, None
    log.warning("jellyfin %s refused: HTTP %s", action, resp.status_code)
    return "jfrefused", resp.status_code


# ---- routes ----

def _back(value) -> str:
    """Only a local page path is a redirect target (media_write.safe_back); its query is dropped (no stale flash)."""
    return safe_back(value, DEFAULT_BACK)


def owner_of(request: Request, form: dict) -> str:
    """The signed-in viewer's own owner; the local 'both' view may pick the row's owner."""
    view = shell.resolve_owner_view(request)[0]
    if view in ("you", "her"):
        return view
    return form.get("owner") if form.get("owner") in ("you", "her") else "you"


def season_episodes(show_id, season_id: str) -> list[dict]:
    """The episodes of one season from the show's item data (media_item's cache — the page just rendered it)."""
    if not media_item.ITEM_RE.match(str(show_id or "")):
        return []
    data = media_item._data(str(show_id)) or {}
    season = next((s for s in data.get("seasons") or [] if str(s.get("id")) == season_id), None)
    return list((season or {}).get("episodes") or [])


def _to_hide(action: str, scope: str | None, jf_id: str, show_id) -> list[str]:
    """Which ids leave Continue watching after a successful action (media-ux3): a watched mark hides the item and,
    for a season, every episode in it; a season marked unwatched hides its in-progress episodes (positions reset);
    reset hides the item; a single item marked unwatched hides nothing (a watched item isn't a resume row)."""
    if action == "unwatched" and scope != "season":
        return []
    ids = [] if action == "unwatched" else [jf_id]
    if scope == "season":
        ids += [e["jf_id"] for e in season_episodes(show_id, jf_id)
                if e.get("jf_id") and (action == "watched" or e.get("in_progress"))]
    return ids


async def _run(request: Request, jf_id: str, action: str):
    """The form is read on the event loop; the Jellyfin calls (and the season read behind _to_hide) run in a worker
    thread (M-40)."""
    if not media_item.ITEM_RE.match(jf_id):
        raise HTTPException(404, "No such item")
    return await run_in_threadpool(_apply, request, jf_id, action, await form_of(request))


def _apply(request: Request, jf_id: str, action: str, form: dict):
    owner, back = owner_of(request, form), _back(form.get("back"))
    scope = "season" if form.get("scope") == "season" and action in ("watched", "unwatched") else None
    season = str(form.get("season") or "")
    keep = {"season": season} if re.fullmatch(r"\d{1,3}", season) else {}  # the episode list reopens that season
    code, status = act(action, owner, jf_id)
    if code is not None:
        return RedirectResponse(f"{back}?" + urlencode({"error": code, **({"code": status} if status else {}), **keep}),
                                status_code=303)
    for hid in _to_hide(action, scope, jf_id, form.get("show")):
        media_hidden.hide(GROUP, key(owner, hid))
    media_item._cache.clear()  # the film / episode / show pages re-read the new watch state
    done = f"season-{action}" if scope else action
    return RedirectResponse(f"{back}?" + urlencode({"done": done, **keep}), status_code=303)


@router.post("/media/resume/{jf_id}/watched", dependencies=[Depends(same_origin)])
async def mark_watched(request: Request, jf_id: str):
    return await _run(request, jf_id, "watched")


@router.post("/media/resume/{jf_id}/unwatched", dependencies=[Depends(same_origin)])
async def mark_unwatched(request: Request, jf_id: str):
    return await _run(request, jf_id, "unwatched")


@router.post("/media/resume/{jf_id}/reset", dependencies=[Depends(same_origin)])
async def reset_progress(request: Request, jf_id: str):
    return await _run(request, jf_id, "reset")


@router.post("/media/resume/{jf_id}/hide", dependencies=[Depends(same_origin)])
async def hide_next_up(request: Request, jf_id: str):
    """Hide a Next Up suggestion (media-ux2, 2026-10-08) for the owner: media.db only, no Jellyfin call (it has no
    per-item Next Up dismiss). It stays hidden until Next Up suggests a different episode of that series."""
    if not media_item.ITEM_RE.match(jf_id):
        raise HTTPException(404, "No such item")
    form = await form_of(request)
    owner, back = owner_of(request, form), _back(form.get("back"))
    series = str(form.get("series") or "")
    if not media_db.KEY_RE.match(series):
        raise HTTPException(422, "Invalid series")
    try:
        await run_in_threadpool(media_db.hide_next_up, owner, series, jf_id)
    except Exception as exc:  # sqlite / OS errors: a word, never a 500
        log.warning("next up hide not saved: %s", type(exc).__name__)
        return RedirectResponse(f"{back}?error=hidefail", status_code=303)
    return RedirectResponse(f"{back}?done=hide", status_code=303)
