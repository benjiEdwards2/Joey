"""Activity > Downloads: pause, resume and remove torrents (JY-301, 2026-11-03), owner only, behind DOWNLOAD_CONTROLS=1.

A LIVE write path to qBittorrent, shaped like the P4 cap (hub/server_quiet.py, whose `_login` it reuses): server-side
only, one short-lived login per action, every write a POST behind `same_origin`, GET only explains (a redirect back to
the page). Calls: `torrents/info?hashes=` to confirm before and after, `torrents/stop|start` (5.x) falling back to
`torrents/pause|resume` on 404, `torrents/delete` with `deleteFiles`.

deleteFiles=true needs TWO POSTs: `POST /media/downloads/remove files=1` makes no qBittorrent call, it draws a confirm
card (name + size) holding a one-time token kept here; only `POST /media/downloads/delete-files hash= token=` with that
token sends `deleteFiles=true`. Every other route sends `false` or nothing.

Answers chosen from the spec's questions (B. may revisit): Q1 A delete-with-files behind the second fold; Q2 A pause all /
resume all included; Q3 A no more of the API; Q4 A no extra row detail; Q5 A arr "remove and blocklist" is a later item.
No URL, user, password or hash in any flash or log line.
"""
from __future__ import annotations

import logging
import os
import re
import secrets
import threading
import time
from datetime import datetime, timezone
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from hub import guest, shell, upstream
from hub.media_write import owner_for, same_origin
from hub.server_quiet import TIMEOUT, _creds, _login
from hub.store import parse_utc

log = logging.getLogger("hub.media_download_actions")
router = APIRouter()

BACK = "/media/downloads"
HASH_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
TOKEN_TTL = 300   # seconds a delete-files confirm card stays valid
FLASHES = {"paused": "Paused", "resumed": "Resumed", "removed": "Removed", "deleted": "Files deleted",
           "down": "qBittorrent is not reachable", "refused": "Login refused", "gone": "Already gone"}
BAD = ("down", "refused", "gone")
STATE_WORDS = {"paused": "Paused", "resumed": "Queued"}   # the overlay word until a newer snapshot lands

_kept: dict = {}      # hash -> (UTC time, "paused" | "resumed" | "removed"); "all" -> same for pause/resume all
_tokens: dict = {}    # token -> (hash, monotonic expiry)
_lock = threading.Lock()


def clear_cache() -> None:
    with _lock:
        _kept.clear()
        _tokens.clear()


def enabled() -> bool:
    return os.environ.get("DOWNLOAD_CONTROLS", "").strip() == "1" and _creds() is not None


def allowed(request: Request) -> bool:
    """The buttons render and the routes answer: flag on, QBIT_* set, private front, owner 'you'."""
    return enabled() and not guest.is_media() and owner_for(request) == "you"


def _gate(request: Request) -> None:
    if not allowed(request):
        raise HTTPException(404, "Not found")


def valid_hash(h) -> bool:
    return isinstance(h, str) and bool(HASH_RE.match(h))


class _Fail(Exception):
    def __init__(self, word: str):
        super().__init__(word)
        self.word = word


def _post(s, base, path, data, cookies):
    return s.post(base + path, data=data, cookies=cookies, headers={"Referer": base}, timeout=TIMEOUT)


def _info(s, base, h, cookies) -> list:
    resp = s.get(base + "/api/v2/torrents/info", params={"hashes": h}, cookies=cookies,
                 headers={"Referer": base}, timeout=TIMEOUT)
    if resp.status_code != 200:
        log.warning("qBittorrent torrents/info refused: HTTP %s", resp.status_code)
        raise _Fail("down")
    return resp.json() or []


def act(op: str, h: str) -> str:
    """op in pause | resume | remove | purge; h a valid hash or 'all' (pause / resume only). Returns a FLASHES key.
    Never raises; logs HTTP status / exception type only."""
    creds = _creds()
    if creds is None:
        return "down"
    base, user, pw = creds
    s = upstream.session("qbittorrent")
    try:
        cookies = _login(s, base, user, pw)
        if cookies is None:
            return "refused"
        if h != "all" and not _info(s, base, h, cookies):
            return "gone"
        if op in ("pause", "resume"):
            new, old = ("stop", "pause") if op == "pause" else ("start", "resume")
            resp = _post(s, base, f"/api/v2/torrents/{new}", {"hashes": h}, cookies)
            if resp.status_code == 404:   # qBittorrent before 5.0
                resp = _post(s, base, f"/api/v2/torrents/{old}", {"hashes": h}, cookies)
        else:
            resp = _post(s, base, "/api/v2/torrents/delete",
                         {"hashes": h, "deleteFiles": "true" if op == "purge" else "false"}, cookies)
        if resp.status_code != 200:
            log.warning("qBittorrent %s refused: HTTP %s", op, resp.status_code)
            return "down"
        if h != "all":
            after = _info(s, base, h, cookies)
            if op in ("remove", "purge") and after:
                log.warning("qBittorrent %s not confirmed", op)
                return "down"
    except _Fail as f:
        return f.word
    except Exception as exc:  # type only - requests errors embed the URL
        log.warning("qBittorrent %s failed: %s", op, type(exc).__name__)
        return "down"
    word = {"pause": "paused", "resume": "resumed", "remove": "removed", "purge": "deleted"}[op]
    with _lock:
        _kept[h] = (datetime.now(timezone.utc), "removed" if op in ("remove", "purge") else word)
    return word


def overlay(rows: list, updated_at) -> list:
    """Confirmed actions newer than the snapshot win: removed rows drop, paused / resumed rows take the new word."""
    seen = parse_utc(updated_at) if updated_at else None
    with _lock:
        kept = {k: v for k, v in _kept.items() if seen is None or v[0] > seen}
    out = []
    for r in rows or []:
        h = str(r.get("hash") or "").lower()
        k = kept.get(h)
        if k is None and "all" in kept and (h not in kept):
            k = kept["all"]
        if k is None:
            out.append(r)
        elif k[1] != "removed":
            out.append({**r, "state_text": STATE_WORDS[k[1]], "speed_text": "",
                        **({"eta_text": ""} if k[1] == "paused" else {})})
    return out


def page(request: Request, rows: list, params) -> dict:
    """The page's controls context: {on, flash, flash_bad, count}; on False = no buttons at all."""
    if not allowed(request):
        return {"on": False}
    flag = params.get("dl") or ""
    return {"on": True, "flash": FLASHES.get(flag), "flash_bad": flag in BAD,
            "count": len(rows or []), "ask_all": params.get("dl_ask") if params.get("dl_ask") in ("pause", "resume") else None}


async def _form(request: Request) -> dict:
    return {k: v[-1] for k, v in parse_qs((await request.body()).decode("utf-8", "replace")).items()}


def _back(word: str) -> RedirectResponse:
    return RedirectResponse(f"{BACK}?dl={word}", status_code=303)


def _row_hash(form: dict) -> str:
    h = str(form.get("hash") or "")
    if not valid_hash(h):   # 'all', empty, malformed, over-long, upper case: no upstream call
        raise HTTPException(400, "Bad torrent id")
    return h


# ---- GET explains (no write): straight back to the page ----

OPS = ("pause", "resume", "remove", "delete-files", "pause-all", "resume-all")


def explain(request: Request):
    _gate(request)
    return RedirectResponse(BACK, status_code=303)


for _op in OPS:
    router.add_api_route(f"/media/downloads/{_op}", explain, methods=["GET"])


# ---- POST writes ----

@router.post("/media/downloads/pause", dependencies=[Depends(same_origin)])
async def pause(request: Request):
    _gate(request)
    return _back(act("pause", _row_hash(await _form(request))))


@router.post("/media/downloads/resume", dependencies=[Depends(same_origin)])
async def resume(request: Request):
    _gate(request)
    return _back(act("resume", _row_hash(await _form(request))))


@router.post("/media/downloads/pause-all", dependencies=[Depends(same_origin)])
async def pause_all(request: Request):
    _gate(request)
    return _back(act("pause", "all"))


@router.post("/media/downloads/resume-all", dependencies=[Depends(same_origin)])
async def resume_all(request: Request):
    _gate(request)
    return _back(act("resume", "all"))


@router.post("/media/downloads/remove", response_class=HTMLResponse, dependencies=[Depends(same_origin)])
async def remove(request: Request):
    """files != 1: remove from the queue, keep files (deleteFiles=false). files=1: NO call - the second confirm card."""
    _gate(request)
    form = await _form(request)
    h = _row_hash(form)
    if form.get("files") != "1":
        return _back(act("remove", h))
    token = secrets.token_urlsafe(24)
    now = time.monotonic()
    with _lock:
        for t in [t for t, (_, exp) in _tokens.items() if exp < now]:
            _tokens.pop(t, None)
        _tokens[token] = (h, now + TOKEN_TTL)
    snap = shell.get_snapshots(request=request).get("qbittorrent")
    row = next((r for r in ((snap.data if snap else None) or {}).get("active") or []
                if str(r.get("hash") or "").lower() == h), {})
    return shell.render_page(request, "media_download_purge.html", {
        "hash": h, "token": token, "name": row.get("name") or "This download", "size": row.get("size_text") or ""})


@router.post("/media/downloads/delete-files", dependencies=[Depends(same_origin)])
async def delete_files(request: Request):
    """The second confirm: deleteFiles=true only with a live one-time token minted for this same hash."""
    _gate(request)
    form = await _form(request)
    h = _row_hash(form)
    with _lock:
        got = _tokens.pop(str(form.get("token") or ""), None)
    if got is None or got[0] != h or got[1] < time.monotonic():
        return RedirectResponse(BACK, status_code=303)
    return _back(act("purge", h))
