"""Server → Downloads "Quiet (5 Mbps) · Full speed" (P4, 2026-10-22): the qBittorrent global download cap as a toggle.

Why: the 2026-10-12 evaluation found qBittorrent saturating the NAS download link was the biggest cause of slow pages
(E0: B. set a cap by hand). B. accepted the defaults 2026-10-22: Joey may write the cap; Quiet = 5 Mbps (env QUIET_MBPS),
Full = unlimited (0). A LIVE write path, server-side only (env QBIT_URL + QBIT_USER + QBIT_PASS, the connector's names):
the password never reaches the browser, a log line or a flash. Two-step like the stack run: GET `/server/downloads/cap
?mode=` explains what happens -> POST behind `same_origin` -> login (`/api/v2/auth/login`, the feed's call; the SID
cookie is passed per call, the kept Session stays stateless) -> `POST /api/v2/transfer/setDownloadLimit limit=<bytes/s>`
-> `GET /api/v2/transfer/info` to confirm -> 303 back to `/server?cap=<word>#downloads`.

The page reads the mode from the qbittorrent snapshot (`dl_limit_bps`, 120 s loop); a confirmed change is kept here and
wins until a newer snapshot lands, so the page after the redirect already shows the new mode. qBittorrent keeps the cap
in KiB/s (625000 -> 610 KiB/s = 624640 B/s back), so modes compare by the words a person reads ("5 Mbps"), not bytes.
"""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timezone
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from hub import shell, upstream
from hub.ids import QBIT_SNAPSHOT_ID
from hub.media_write import same_origin
from hub.server import SERVER_LAYOUT
from hub.store import parse_utc

log = logging.getLogger("hub.server_quiet")
router = APIRouter()

QUIET_BPS = 625_000            # 5 Mbps in bytes/s (env QUIET_MBPS overrides)
MODES = ("quiet", "full")
TIMEOUT = 10
SLEEP_DEFAULT = "22:00–07:00"
CONFIRM_LINES = {
    "quiet": ("This caps qBittorrent's total download speed at {quiet} so pages, streams and DNS stay quick.",
              "Downloads keep going, just slower; seeding is not touched."),
    "full": ("This removes qBittorrent's download cap: downloads run as fast as the line allows.",
             "While they do, Joey's pages and streams may slow down (the 2026-10-12 finding)."),
}
FLASHES = {"quiet": "Quiet mode on", "full": "Full speed", "failed": "Couldn't reach qBittorrent"}

_kept: dict = {}   # "set" -> (UTC time of the confirmed change, confirmed bytes/s)
_lock = threading.Lock()


def clear_cache() -> None:
    with _lock:
        _kept.clear()


def _creds() -> tuple[str, str, str] | None:
    url, user, pw = (os.environ.get(n, "").strip() for n in ("QBIT_URL", "QBIT_USER", "QBIT_PASS"))
    return (url.rstrip("/"), user, pw) if url and user and pw else None


def quiet_bps() -> int:
    """Quiet's cap in bytes/s: QUIET_MBPS (a positive number of Mbps) or QUIET_BPS."""
    try:
        mbps = float(os.environ.get("QUIET_MBPS", "").strip())
    except ValueError:
        return QUIET_BPS
    return round(mbps * 1e6 / 8) if mbps > 0 else QUIET_BPS


def limit_text(bps: int) -> str:
    """The connector's `dl_limit_text` words (connectors/feeds/qbittorrent.py `_limit_text`; the hub image ships
    without connectors/, so the few lines are repeated): 0 -> 'Unlimited', 625000 -> '5 Mbps'."""
    if bps <= 0:
        return "Unlimited"
    mbps = bps * 8 / 1e6
    if mbps < 0.1:
        return f"{round(bps * 8 / 1000)} kbps"
    return f"{mbps:.0f} Mbps" if mbps >= 9.95 else f"{mbps:.1f}".rstrip("0").rstrip(".") + " Mbps"


def mode_of(bps: int) -> str:
    if bps <= 0:
        return "full"
    return "quiet" if limit_text(bps) == limit_text(quiet_bps()) else "custom"


def sleep_window() -> str:
    return os.environ.get("NAS_SLEEP_WINDOW", "").strip() or SLEEP_DEFAULT


def status(snaps) -> dict:
    """{configured, mode: quiet | full | custom | None, text}. Not configured = the hub lacks QBIT_* or the qbittorrent
    snapshot is absent / carries no `dl_limit_bps` (an envelope from before P4). No call: the snapshot is the source."""
    snap = (snaps or {}).get(QBIT_SNAPSHOT_ID)
    bps = (snap.data or {}).get("dl_limit_bps") if snap is not None else None
    if _creds() is None or not isinstance(bps, int) or isinstance(bps, bool):
        return {"configured": False, "mode": None, "text": ""}
    with _lock:
        kept = _kept.get("set")
    seen = parse_utc(snap.updated_at)
    if kept is not None and (seen is None or kept[0] > seen):   # a confirmed change newer than the last sweep
        bps = kept[1]
    bps = max(0, bps)
    return {"configured": True, "mode": mode_of(bps),
            "text": "Unlimited" if bps == 0 else f"Capped at {limit_text(bps)}"}


def _fail(mode: str) -> dict:
    return {"ok": False, "mode": mode, "text": FLASHES["failed"]}


def _login(s, base: str, user: str, pw: str) -> dict | None:
    """The feed's login: 5.x answers 204 + cookie, older builds 200 'Ok.' / 'Fails.'; the cookie is the proof."""
    resp = s.post(base + "/api/v2/auth/login", data={"username": user, "password": pw},
                  headers={"Referer": base}, timeout=TIMEOUT)
    if resp.status_code not in (200, 204):
        log.warning("qBittorrent login refused: HTTP %s", resp.status_code)
        return None
    jar = {c.name: c.value for c in resp.cookies if c.name == "SID" or c.name.startswith("QBT_SID")}
    if not jar:
        log.warning("qBittorrent login refused: no session cookie")
    return jar or None


def set_mode(mode: str) -> dict:
    """quiet | full -> {ok, mode, text}. Logs in, sets the global download limit, re-reads transfer/info and only says
    ok when the cap read back matches. Never raises; logs HTTP status / exception type only."""
    creds = _creds()
    if mode not in MODES or creds is None:
        return _fail(mode)
    base, user, pw = creds
    want = quiet_bps() if mode == "quiet" else 0
    s = upstream.session("qbittorrent")
    try:
        cookies = _login(s, base, user, pw)
        if cookies is None:
            return _fail(mode)
        hdrs = {"Referer": base}
        resp = s.post(base + "/api/v2/transfer/setDownloadLimit", data={"limit": want}, cookies=cookies,
                      headers=hdrs, timeout=TIMEOUT)
        if resp.status_code != 200:
            log.warning("qBittorrent setDownloadLimit refused: HTTP %s", resp.status_code)
            return _fail(mode)
        info = s.get(base + "/api/v2/transfer/info", cookies=cookies, headers=hdrs, timeout=TIMEOUT)
        got = info.json().get("dl_rate_limit") if info.status_code == 200 else None
        got = max(0, int(got))
    except Exception as exc:  # type only — requests errors embed the URL
        log.warning("qBittorrent cap failed: %s", type(exc).__name__)
        return _fail(mode)
    if mode_of(got) != mode:
        log.warning("qBittorrent cap not confirmed: read back %s", mode_of(got))
        return _fail(mode)
    with _lock:
        _kept["set"] = (datetime.now(timezone.utc), got)
    return {"ok": True, "mode": mode, "text": FLASHES[mode]}


def page(snaps, params) -> dict:
    """The Server page's Downloads row: status + the sleep window + the flash word after a POST (junk ignored)."""
    st = status(snaps)
    flag = params.get("cap") or ""
    return {**st, "sleep": sleep_window(), "quiet_label": limit_text(quiet_bps()),
            "flash": FLASHES.get(flag), "flash_bad": flag == "failed"}


@router.get("/server/downloads/cap", response_class=HTMLResponse)
def cap_step(request: Request, mode: str = ""):
    if mode not in MODES:
        return RedirectResponse("/server#downloads", status_code=303)
    area = next((a for a in shell.registry.areas if a.layout == SERVER_LAYOUT), None)
    if area is None:
        return shell.not_found_page(request)
    st = status(shell.get_snapshots(request=request))
    quiet = limit_text(quiet_bps())
    msg = ("qBittorrent is not connected on the hub (QBIT_URL, QBIT_USER, QBIT_PASS)." if not st["configured"]
           else f"{'Quiet mode' if mode == 'quiet' else 'Full speed'} is already on." if st["mode"] == mode else None)
    return shell.render_page(request, "server_quiet.html", {
        "area": area, "mode": mode, "st": st, "msg": msg, "quiet": quiet,
        "lines": [line.format(quiet=quiet) for line in CONFIRM_LINES[mode]],
    }, active_id=area.id)


@router.post("/server/downloads/cap", dependencies=[Depends(same_origin)])
async def cap_now(request: Request):
    mode = parse_qs((await request.body()).decode("utf-8", "replace")).get("mode", [""])[-1]
    if mode not in MODES or _creds() is None:
        return RedirectResponse("/server#downloads", status_code=303)
    out = set_mode(mode)
    return RedirectResponse(f"/server?cap={mode if out['ok'] else 'failed'}#downloads", status_code=303)
