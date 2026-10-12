"""Server → "Restart + update media stack" (2026-10-12): the hub side of stackctl (stackctl/README.md).

WUD can recreate one container at a time but cannot pull + restart the whole media-server compose, so a tiny helper
on the NAS (`stackctl`, Docker socket + the compose folder) does it on request. This is a LIVE write path, server-side
only (env STACKCTL_URL + STACKCTL_TOKEN, `Authorization: Bearer`): the token never reaches the browser, a log line or
a flash. Two-step like Update now: GET `/server/stack/run?step=confirm` explains exactly what happens -> POST behind
`same_origin` -> `POST {STACKCTL_URL}/media/pull-up` (202 started, 409 already running) -> 303 back with a flash word.
The Server page shows stackctl's last run (`GET /status`, 2 s timeout) when STACKCTL_URL is set; failures log the HTTP
status or exception type only and degrade to words.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

import requests
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from hub import shell
from hub.media_write import same_origin
from hub.server import SERVER_LAYOUT
from hub.store import ago_text, parse_utc

log = logging.getLogger("hub.server_stack")
router = APIRouter()

RUN_TIMEOUT, STATUS_TIMEOUT = 10, 2
CONFIRM_LINES = (
    "This pulls the newest image for, and recreates, every container in the media-server stack "
    "(/volume1/media-server/docker-compose.yml) except WUD and stackctl itself.",
    "Jellyfin and the other manual-only apps (gluetun, qBittorrent, Prowlarr, Uptime Kuma) WILL update too.",
    "Seerr stays on v3.5.0: its image tag is pinned in the compose file.",
    "Playback and downloads drop for a few minutes while the containers restart.",
    "Joey itself is not touched — it is not in that compose file.",
)
FLASHES = {"started": "Media stack update started — playback and downloads drop for a few minutes",
           "busy": "A media stack update is already running",
           "refused": "stackctl refused the request",
           "unreachable": "stackctl unreachable"}


def _creds() -> tuple[str, str] | None:
    url, token = (os.environ.get(n, "").strip() for n in ("STACKCTL_URL", "STACKCTL_TOKEN"))
    return (url.rstrip("/"), token) if url and token else None


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def pull_up() -> str:
    """-> 'started' | 'busy' (a run is going) | 'refused' (any other HTTP answer) | 'unreachable'."""
    creds = _creds()
    if not creds:
        return "unreachable"
    try:
        resp = requests.post(creds[0] + "/media/pull-up", headers=_headers(creds[1]), timeout=RUN_TIMEOUT)
    except Exception as exc:  # type only — requests errors embed the URL
        log.warning("stackctl pull-up failed: %s", type(exc).__name__)
        return "unreachable"
    if resp.status_code == 202:
        return "started"
    if resp.status_code == 409:
        return "busy"
    log.warning("stackctl pull-up refused: HTTP %s", resp.status_code)
    return "refused"


def status(now: datetime | None = None) -> dict:
    """The Server page's line: {connected, state: off | unreachable | idle | running | ok | failed, text}."""
    creds = _creds()
    if not creds:
        return {"connected": False, "state": "off", "text": "Not connected"}
    try:
        resp = requests.get(creds[0] + "/status", headers=_headers(creds[1]), timeout=STATUS_TIMEOUT)
        body = resp.json() if resp.status_code == 200 else None
    except Exception as exc:
        log.warning("stackctl status failed: %s", type(exc).__name__)
        body = None
    if not isinstance(body, dict):
        return {"connected": True, "state": "unreachable", "text": "stackctl unreachable"}
    now = now or datetime.now(timezone.utc)

    def ago(key):
        at = parse_utc(body.get(key))
        return ago_text((now - at).total_seconds() / 60.0) if at else None
    if body.get("running"):
        return {"connected": True, "state": "running", "text": "Updating now" + (f" · started {ago('started_at')}"
                                                                             if ago("started_at") else "")}
    if body.get("finished_at") is None:
        return {"connected": True, "state": "idle", "text": "No run yet"}
    when = ago("finished_at")
    if body.get("exit_code") == 0:
        return {"connected": True, "state": "ok", "text": "Last run finished OK" + (f" · {when}" if when else "")}
    return {"connected": True, "state": "failed",
            "text": f"Last run failed (exit {body.get('exit_code')})" + (f" · {when}" if when else "")}


def flash_text(params) -> str | None:
    return FLASHES.get(params.get("stack") or "")


@router.get("/server/stack/run", response_class=HTMLResponse)
def run_step(request: Request, step: str = ""):
    if step != "confirm":
        return RedirectResponse("/server#updates", status_code=303)
    area = next((a for a in shell.registry.areas if a.layout == SERVER_LAYOUT), None)
    if area is None:
        return shell.not_found_page(request)
    st = status()
    msg = ("stackctl is not connected on the hub (STACKCTL_URL, STACKCTL_TOKEN)." if not st["connected"]
           else "A media stack update is already running." if st["state"] == "running" else None)
    return shell.render_page(request, "server_stack.html", {"area": area, "lines": CONFIRM_LINES, "msg": msg,
                                                           "st": st}, active_id=area.id)


@router.post("/server/stack/run", dependencies=[Depends(same_origin)])
def run_now(request: Request):
    if _creds() is None:
        return RedirectResponse("/server#updates", status_code=303)
    return RedirectResponse(f"/server?stack={pull_up()}#updates", status_code=303)
