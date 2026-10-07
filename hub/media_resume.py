"""Move on from Continue watching (2026-10-08): "Mark watched" and "Reset progress" on resume items — the hub
and Media home Continue watching shelves, Server → Playing's Up next, and the film / episode page when it shows
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
"""
from __future__ import annotations

import logging
import os
import re
import time
from urllib.parse import urlencode

import requests
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse

from hub import media_files, media_hidden, media_item
from hub.media_write import form_of, same_origin

log = logging.getLogger("hub.media_resume")
router = APIRouter()

GROUP = "resume"
TIMEOUT = 8
DEFAULT_BACK = "/media/playing"
NEXT_EPISODE = "Next episode"   # the connector's word for a next-up row (nothing to reset)
DONE = {"watched": "Marked watched", "reset": "Progress reset"}
ERRORS = {"jfunset": "Jellyfin is not connected", "jfuser": "No Jellyfin user for this profile",
          "jfdown": "Couldn't reach Jellyfin", "jfrefused": "Jellyfin refused"}
FALLBACK_STATUS = (404, 405)

_her_uid: list = [0.0, None, None]  # [fetched_at, name, uid]


def clear_cache() -> None:
    _her_uid[:] = [0.0, None, None]


# ---- what the pages show ----

def key(owner: str, jf_id) -> str:
    return f"{owner}:{jf_id}"


def hide_rows(rows, owner: str, updated_at=None) -> list:
    return media_hidden.visible(GROUP, rows, lambda r: key(owner, r.get("jf_id")) if r.get("jf_id") else None, updated_at)


def apply_hidden(snaps: dict, snapshot_id: str = "jellyfin") -> dict:
    """The snapshots with marked / reset items dropped from B.'s `up_next` and Georgina's `her.up_next`. Untouched
    (same objects) when nothing is hidden, so the common read costs nothing."""
    snap = snaps.get(snapshot_id)
    if snap is None or not media_hidden.any_in(GROUP) or not isinstance(snap.data, dict):
        return snaps
    from dataclasses import replace
    data = dict(snap.data)
    data["up_next"] = hide_rows(data.get("up_next"), "you", snap.updated_at)
    if isinstance(data.get("her"), dict):
        data["her"] = {**data["her"], "up_next": hide_rows(data["her"].get("up_next"), "her", snap.updated_at)}
    return {**snaps, snapshot_id: replace(snap, data=data)}


def in_progress(row: dict) -> bool:
    """A resume row (position saved) rather than a next-up suggestion."""
    text = str((row or {}).get("remaining_text") or "")
    return bool(text) and text != NEXT_EPISODE


def flash_text(params) -> tuple[str | None, str | None]:
    done, err, code = params.get("done") or "", params.get("error") or "", params.get("code") or ""
    if done in DONE:
        return DONE[done], None
    if err in ERRORS:
        return None, ERRORS[err] + (f" (HTTP {code})" if err == "jfrefused" and re.fullmatch(r"\d{3}", code) else "")
    return None, None


# ---- Jellyfin ----

def _her_user_id(base: str, headers: dict) -> str | None:
    name = os.environ.get("JELLYFIN_USER_HER", "").strip()
    if not name:
        return None
    if _her_uid[2] and _her_uid[1] == name and time.time() - _her_uid[0] < media_files.UID_TTL:
        return _her_uid[2]
    users = media_files._get(base, headers, "/Users")
    uid = next((u["Id"] for u in users if isinstance(u, dict) and u.get("Name") == name and u.get("Id")), None) \
        if isinstance(users, list) else None
    if uid:
        _her_uid[:] = [time.time(), name, uid]
    return uid


def _post(base, headers, path, params=None, body=None):
    return requests.post(f"{base}{path}", params=params, json=body, headers=headers, timeout=TIMEOUT)


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
    """Only a local page path (no scheme, no //) is a redirect target; its query is dropped (no stale flash)."""
    v = str(value or "").split("#", 1)[0].split("?", 1)[0]
    ok = v == "/" or v.startswith(("/media/", "/a/"))
    return v if ok and "//" not in v and "\\" not in v and len(v) < 300 else DEFAULT_BACK


def owner_of(request: Request, form: dict) -> str:
    """The signed-in viewer's own owner; the local 'both' view may pick the row's owner."""
    from hub.main import resolve_owner_view  # late: hub.main includes this router
    view = resolve_owner_view(request)[0]
    if view in ("you", "her"):
        return view
    return form.get("owner") if form.get("owner") in ("you", "her") else "you"


async def _run(request: Request, jf_id: str, action: str):
    if not media_item.ITEM_RE.match(jf_id):
        raise HTTPException(404, "No such item")
    form = await form_of(request)
    owner, back = owner_of(request, form), _back(form.get("back"))
    code, status = act(action, owner, jf_id)
    if code is not None:
        return RedirectResponse(f"{back}?" + urlencode({"error": code, **({"code": status} if status else {})}),
                                status_code=303)
    media_hidden.hide(GROUP, key(owner, jf_id))
    media_item._cache.clear()  # the film / episode / show pages re-read the new watch state
    return RedirectResponse(f"{back}?done={action}", status_code=303)


@router.post("/media/resume/{jf_id}/watched", dependencies=[Depends(same_origin)])
async def mark_watched(request: Request, jf_id: str):
    return await _run(request, jf_id, "watched")


@router.post("/media/resume/{jf_id}/reset", dependencies=[Depends(same_origin)])
async def reset_progress(request: Request, jf_id: str):
    return await _run(request, jf_id, "reset")
