"""Server -> "Power down" (JY-274, 2026-11-05): the hub side of powerctl (powerctl/README.md).

Owner "you" only (her view and friends get 403; the media front never serves the route, hub/guest.py PRIVATE).
The confirm is a <dialog> on the Server page (header pill, built like the sign-out one); GET `/server/power` just
redirects to /server. The POST, behind `same_origin`, checks owner, then calls `POST {POWER_URL}/power-down` with
`Bearer POWER_TOKEN` (2 s cap): 202 -> "Shutting down in 60 s", 409 -> "already pending", anything else -> an error and the NAS untouched.
Every owner POST is appended to `power.log` (JSON lines beside media.db: time, who, outcome; never the token or URL)
BEFORE the page is rendered. The Server page's "Last shutdown" line reads that file (no request on page load).
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

import requests
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool

from hub import guest, ids, media_store, shell
from hub.media_write import owner_for, same_origin
from hub.server import SERVER_LAYOUT
from hub.store import ago_text, parse_utc

log = logging.getLogger("hub.server_power")
router = APIRouter()

TIMEOUT = 2
LATE_FROM, EARLY_UNTIL = (21, 30), (7, 0)
_lock = threading.Lock()

WHAT = ("This turns off the NAS and everything on it: Joey, Jellyfin, the downloads and the other services. "
        "The media stack is stopped cleanly first. This page will stop answering.")
LATE = "It is after 21:30: friends watching now will be cut off until 07:00."
BACK = "It comes back on at 07:00 on the ADM power schedule (or with the power button on the NAS)."
MESSAGES = {"started": "Shutting down in 60 s. The page will stop answering.",
            "pending": "A power down is already pending.",
            "refused": "powerctl refused the request. The NAS is untouched.",
            "unreachable": "powerctl unreachable. The NAS is untouched.",
            "off": "powerctl is not connected on the hub (POWER_URL, POWER_TOKEN). The NAS is untouched.",
            }


def _creds() -> tuple[str, str] | None:
    url, token = (os.environ.get(n, "").strip() for n in ("POWER_URL", "POWER_TOKEN"))
    return (url.rstrip("/"), token) if url and token else None


def configured() -> bool:
    return _creds() is not None


def log_path() -> Path:
    return media_store.db_path().parent / "power.log"


def local_now() -> datetime:
    """Melbourne wall time (monkeypatched in tests)."""
    return ids.home_now()


def is_late(now: datetime | None = None) -> bool:
    t = (now or local_now()).timetuple()[3:5]
    return t >= LATE_FROM or t < EARLY_UNTIL


def record(who: str, outcome: str) -> None:
    """Append one line (UTC time, who, outcome). A write failure is logged by type and never blocks the request."""
    line = json.dumps({"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "who": who,
                       "outcome": outcome})
    try:
        with _lock:
            path = log_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
    except OSError as exc:
        log.warning("power.log write failed: %s", type(exc).__name__)


def last_shutdown(now: datetime | None = None) -> str:
    """'Last shutdown: 3h ago by Benji' from the newest `started` line; 'Last shutdown: none yet' without one."""
    found = None
    try:
        with log_path().open(encoding="utf-8") as f:
            for raw in f:
                try:
                    row = json.loads(raw)
                except ValueError:
                    continue
                if isinstance(row, dict) and row.get("outcome") == "started":
                    found = row
    except OSError:
        pass
    at = parse_utc(found.get("at")) if found else None
    if not at:
        return "Last shutdown: none yet"
    now = now or datetime.now(timezone.utc)
    return f"Last shutdown: {ago_text((now - at).total_seconds() / 60.0)} by {found.get('who') or 'unknown'}"


def can_press(request: Request) -> bool:
    return not guest.is_media() and owner_for(request) == "you"


def header(request: Request) -> dict:
    """The Server page's header bit: the pill (owner + configured) and the last-shutdown line. Local reads only."""
    return {"pill": can_press(request) and configured(), "last": last_shutdown(), "what": WHAT,
            "late": LATE if is_late() else None, "back": BACK}


def _who(request: Request) -> str:
    ident = shell.identity_of(request)
    if ident.owner == "you" and ident.email:
        return ident.name
    return os.environ.get("OWNER_NAME_YOU") or "Benji"


def _owner_only(request: Request) -> None:
    if not can_press(request):
        raise HTTPException(403, "Only the admin can power down the NAS")


def power_down() -> str:
    """-> 'started' | 'pending' (409) | 'refused' (any other HTTP answer) | 'unreachable' | 'off' (no env)."""
    creds = _creds()
    if not creds:
        return "off"
    try:
        resp = requests.post(creds[0] + "/power-down", headers={"Authorization": f"Bearer {creds[1]}"},
                             timeout=TIMEOUT)
    except Exception as exc:  # type only: requests errors embed the URL
        log.warning("powerctl power-down failed: %s", type(exc).__name__)
        return "unreachable"
    if resp.status_code == 202:
        return "started"
    if resp.status_code == 409:
        return "pending"
    log.warning("powerctl power-down refused: HTTP %s", resp.status_code)
    return "refused"


def _page(request: Request, outcome: str | None = None):
    area = next((a for a in shell.registry.areas if a.layout == SERVER_LAYOUT), None)
    if area is None:
        return shell.not_found_page(request)
    return shell.render_page(request, "server_power.html", {
        "area": area, "what": WHAT, "late": LATE if is_late() else None, "back": BACK, "last": last_shutdown(),
        "configured": configured(), "outcome": outcome,
        "message": MESSAGES.get(outcome or "") or (None if configured() else MESSAGES["off"]),
    }, active_id=area.id)


@router.get("/server/power")
def confirm(request: Request):
    _owner_only(request)
    return RedirectResponse("/server", status_code=303)


@router.post("/server/power", response_class=HTMLResponse, dependencies=[Depends(same_origin)])
async def press(request: Request):
    _owner_only(request)
    outcome = await run_in_threadpool(power_down)
    record(_who(request), outcome)   # the log line first, then the page
    return _page(request, outcome)
