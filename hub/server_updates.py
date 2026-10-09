"""Server → Updates actions (WP-U1, 2026-10-06): "Update now" and "Ignore" on the Server page.

Update now is a LIVE call path to What's Up Docker 9.3 (env WUD_URL + WUD_USER/WUD_PASS,
HTTP Basic), server-side only: POST /api/containers/{id}/triggers/dockercompose/local, no
body (app/api/container.ts `runTriggerForContainer`, docs getwud.app "Run trigger for
container"). WUD does NOT apply include/exclude on that endpoint — it runs whatever it is
asked — so the hub is the only guard: it refuses any row whose `auto` is not true (the
notify-only containers carry `wud.trigger.exclude=dockercompose.local`).

Two-step like the Jellyseerr Request: GET `?step=confirm` -> POST behind `same_origin`.
Failures log and record status/type only — never the URL or login — and degrade to words.

media.db tables (own `ensure()`, the shared SCHEMA in media_db is untouched):
`server_update_ignores(container, tag, ignored_at)` and `server_update_runs(container, tag,
requested_at, outcome, note)` — single-owner page, owner `you` implicit.
"""

from __future__ import annotations

import logging
import os
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from urllib.parse import quote, urlencode

import requests
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from hub import media_db
from hub.media_write import same_origin
from hub.shell import templates

log = logging.getLogger("hub.server_updates")
router = APIRouter()

TIMEOUT = 10
TRIGGER_TYPE, TRIGGER_NAME = "dockercompose", "local"
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
CONFIRM_TEXT = ("This asks WUD to recreate the container now via the dockercompose.local trigger. "
                "The app will be unavailable for about a minute.")

DDL = (
    """CREATE TABLE IF NOT EXISTS server_update_ignores(
  container TEXT, tag TEXT, ignored_at TEXT, PRIMARY KEY(container, tag))""",
    """CREATE TABLE IF NOT EXISTS server_update_runs(
  id INTEGER PRIMARY KEY, container TEXT, tag TEXT, requested_at TEXT, outcome TEXT, note TEXT)""",
)


# ---- media.db ----

def ensure(db) -> None:
    for stmt in DDL:
        db.execute(stmt)
    db.commit()


def _connect():
    db = media_db.connect()
    ensure(db)
    return db


def _read():
    """A connection when media.db exists (tables created on demand), else None."""
    if not media_db.db_path().is_file():
        return None
    try:
        return _connect()
    except (sqlite3.Error, OSError) as exc:
        log.warning("server updates db unreadable: %s", type(exc).__name__)
        return None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def get_ignores() -> set[tuple[str, str]]:
    db = _read()
    if db is None:
        return set()
    try:
        with closing(db):
            return {(r["container"], r["tag"]) for r in
                    db.execute("SELECT container, tag FROM server_update_ignores")}
    except sqlite3.Error as exc:
        log.warning("get_ignores failed: %s", type(exc).__name__)
        return set()


def set_ignore(container: str, tag: str) -> None:
    with closing(_connect()) as db, db:
        db.execute("INSERT INTO server_update_ignores(container, tag, ignored_at) VALUES(?,?,?) "
                   "ON CONFLICT(container, tag) DO UPDATE SET ignored_at = excluded.ignored_at",
                   (container, tag, _now().isoformat()))


def clear_ignores(container: str) -> None:
    if not media_db.db_path().is_file():
        return
    with closing(_connect()) as db, db:
        db.execute("DELETE FROM server_update_ignores WHERE container = ?", (container,))


def record_run(container: str, tag: str, outcome: str, note: str | None) -> None:
    with closing(_connect()) as db, db:
        db.execute("INSERT INTO server_update_runs(container, tag, requested_at, outcome, note) "
                   "VALUES(?,?,?,?,?)", (container, tag, _now().isoformat(), outcome, note))


def last_requested() -> dict[str, dict]:
    """container -> its latest 'requested' run {tag, requested_at}."""
    db = _read()
    if db is None:
        return {}
    try:
        with closing(db):
            rows = db.execute("SELECT container, tag, requested_at FROM server_update_runs "
                              "WHERE outcome = 'requested' ORDER BY id")
            return {r["container"]: {"tag": r["tag"], "requested_at": r["requested_at"]} for r in rows}
    except sqlite3.Error as exc:
        log.warning("last_requested failed: %s", type(exc).__name__)
        return {}


# ---- WUD ----

def key_tag(row: dict) -> str:
    """The tag an ignore/run is keyed on: the new tag, or the current tag for a digest update."""
    return str(row.get("new_tag") or row.get("current_tag") or "")


def _creds() -> tuple[str, str, str] | None:
    vals = [os.environ.get(n, "").strip() for n in ("WUD_URL", "WUD_USER", "WUD_PASS")]
    return (vals[0].rstrip("/"), vals[1], vals[2]) if all(vals) else None


def trigger_path(container_id: str) -> str:
    """Verified against WUD 9.3 (app/api/container.ts): POST, no body, 200 `{}` on success,
    404 for an unknown container/trigger, 500 when the trigger itself fails."""
    return (f"/api/containers/{quote(container_id, safe='')}"
            f"/triggers/{TRIGGER_TYPE}/{TRIGGER_NAME}")


def run_trigger(container_id: str) -> tuple[str, str | None]:
    """-> ('requested', None) | ('refused', 'HTTP 4xx/5xx') | ('unreachable', '<ExcType>')."""
    creds = _creds()
    if not creds:
        return "unreachable", "not configured"
    try:
        resp = requests.post(creds[0] + trigger_path(container_id), auth=(creds[1], creds[2]),
                             timeout=TIMEOUT)
    except Exception as exc:  # type only — requests errors embed the URL
        log.warning("wud trigger failed: %s", type(exc).__name__)
        return "unreachable", type(exc).__name__
    if 200 <= resp.status_code < 300:
        return "requested", None
    log.warning("wud trigger refused: HTTP %s", resp.status_code)
    return "refused", f"HTTP {resp.status_code}"


# ---- routes ----

def _pending_row(name: str) -> dict | None:
    from hub import main as hub  # late: hub.main includes this router
    from hub.server import WUD_SNAPSHOT_ID

    snap = hub.get_snapshots().get(WUD_SNAPSHOT_ID)
    rows = ((snap.data or {}).get("containers") or []) if snap else []
    return next((c for c in rows if isinstance(c, dict) and c.get("name") == name
                 and c.get("update_available")), None)


def refusal(row: dict | None, name: str) -> str | None:
    """Why Update now must not run for this row, in words; None when it may."""
    if row is None:
        return f"No update is pending for {name} in the latest WUD sweep."
    if row.get("auto") is not True:
        return (f"{name} is excluded from automatic updates (wud.trigger.exclude) — "
                "update it by hand.")
    if not row.get("id"):
        return "The WUD snapshot has no container id yet — try again after the next hourly sweep."
    if _creds() is None:
        return "WUD is not configured on the hub (WUD_URL, WUD_USER, WUD_PASS)."
    return None


def _page(request: Request, ctx: dict, status: int = 200):
    from hub import main as hub
    from hub.server import SERVER_LAYOUT

    area = next((a for a in hub.registry.areas if a.layout == SERVER_LAYOUT), None)
    base = {"areas": hub.registry.visible_areas}
    if area is None:
        return templates.TemplateResponse(request, "404.html", {
            **base, "active_id": None, "missing_text": "No page here"}, status_code=404)
    # the shared shell env (hub/shell.py) carries every global (identity, static_v, ...)
    return templates.TemplateResponse(request, "server_update.html", {
        **base, "active_id": area.id, "area": area, "confirm_text": CONFIRM_TEXT, **ctx}, status_code=status)


def _name(name: str) -> str | None:
    return name if NAME_RE.match(name or "") else None


def _back(**flash) -> RedirectResponse:
    return RedirectResponse("/server?" + urlencode(flash) + "#updates", status_code=303)


@router.get("/server/updates/{name}/run", response_class=HTMLResponse)
def run_step(request: Request, name: str, step: str = ""):
    if step != "confirm":
        return RedirectResponse("/server#updates", status_code=303)
    if _name(name) is None:
        return _page(request, {"name": "?", "row": None, "msg": "No such container."}, 404)
    row = _pending_row(name)
    return _page(request, {"name": name, "row": row, "msg": refusal(row, name)})


@router.post("/server/updates/{name}/run", dependencies=[Depends(same_origin)])
def run_now(request: Request, name: str):
    if _name(name) is None:
        return _page(request, {"name": "?", "row": None, "msg": "No such container."}, 404)
    row = _pending_row(name)
    why = refusal(row, name)
    if why:
        return _page(request, {"name": name, "row": row, "msg": why}, 409)
    outcome, note = run_trigger(str(row["id"]))
    try:
        record_run(name, key_tag(row), outcome, note)
    except (sqlite3.Error, OSError) as exc:
        log.warning("server update run not recorded: %s", type(exc).__name__)
    if outcome == "requested":
        return _back(flash="requested", c=name)
    if outcome == "refused":
        return _back(flash="refused", code=note.removeprefix("HTTP "))
    return _back(flash="unreachable")


@router.post("/server/updates/{name}/ignore", dependencies=[Depends(same_origin)])
def ignore(request: Request, name: str):
    row = _pending_row(name) if _name(name) else None
    if row is None:
        return _page(request, {"name": name if _name(name) else "?", "row": None,
                               "msg": refusal(None, name if _name(name) else "that container")}, 409)
    try:
        set_ignore(name, key_tag(row))
    except (sqlite3.Error, OSError) as exc:
        log.warning("server update ignore failed: %s", type(exc).__name__)
        return _back(flash="dberror")
    return _back(flash="ignored", c=name)


@router.post("/server/updates/{name}/unignore", dependencies=[Depends(same_origin)])
def unignore(request: Request, name: str):
    if _name(name) is None:
        return _back()
    try:
        clear_ignores(name)
    except (sqlite3.Error, OSError) as exc:
        log.warning("server update unignore failed: %s", type(exc).__name__)
        return _back(flash="dberror")
    return _back(flash="unignored", c=name)


def flash_text(params) -> str | None:
    """The one flash line on /server, from the redirect's query; anything odd -> None."""
    kind, name, code = params.get("flash"), params.get("c") or "", params.get("code") or ""
    name = name if NAME_RE.match(name) else ""
    if kind == "requested" and name:
        return f"Update requested for {name}"
    if kind == "refused":
        return f"WUD refused (HTTP {code})" if re.fullmatch(r"\d{3}", code) else "WUD refused"
    if kind == "unreachable":
        return "WUD unreachable"
    if kind == "ignored" and name:
        return f"Ignoring this update for {name}"
    if kind == "unignored" and name:
        return f"{name} is back in Updates"
    if kind == "dberror":
        return "Couldn't save that — try again"
    return None
