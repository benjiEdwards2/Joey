"""Server → Updates actions (WP-U1, 2026-10-06): "Update now" and "Ignore" on the Server page.

Update now is a LIVE call path to What's Up Docker 9.3 (env WUD_URL + WUD_USER/WUD_PASS,
HTTP Basic), server-side only: POST /api/containers/{id}/triggers/dockercompose/local, no
body (app/api/container.ts `runTriggerForContainer`, docs getwud.app "Run trigger for
container"). WUD does NOT apply include/exclude on that endpoint — it runs whatever it is
asked — so the hub is the only guard.

Manual updates (2026-10-12): rows whose `auto` is not true (the notify-only containers carry
`wud.trigger.exclude=dockercompose.local`) run a second trigger, `dockercompose.manual`, set
`WUD_TRIGGER_DOCKERCOMPOSE_MANUAL_AUTO=false` on the NAS (WUD 9.3 Trigger.ts `init()` only
registers for auto execution when `auto` is true) — so it fires only when asked from here.
The `wud` container itself is always refused: B. updates WUD by hand. So is any `joey-*` container
(2026-10-12): Joey's own containers are not in the media-server compose the WUD triggers manage —
they update on the next Joey deploy (`hub.server.update_hold`, one name rule).

Two-step like the Jellyseerr Request: GET `?step=confirm` -> POST behind `same_origin`.

Update all (2026-10-12): `/server/updates/all/run` — the same two steps over every pending,
non-ignored row `refusal()` lets through (wud / joey-* listed apart with the reason), gluetun
first, each through the per-row trigger + `record_run`. A WUD that doesn't answer ends the run
(no point timing out once per row); the flash counts "N requested · M refused".
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

from hub import media_db, shell
from hub.media_write import same_origin
from hub.server import (HOLD_TEXT, SERVER_LAYOUT, WUD_SELF, WUD_SNAPSHOT_ID, key_tag,  # one definition (H-24)
                        split_updates, update_hold)

log = logging.getLogger("hub.server_updates")
router = APIRouter()

TIMEOUT = 10
TRIGGER_TYPE, TRIGGER_NAME = "dockercompose", "local"
MANUAL_TRIGGER_NAME = "manual"      # WUD_TRIGGER_DOCKERCOMPOSE_MANUAL_AUTO=false (NAS)
SELF_NAME = WUD_SELF                # never recreated from the hub
VPN_ROUTED = ("prowlarr", "qbittorrent")   # live in gluetun's network namespace
VPN_NAME = "gluetun"
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
CONFIRM_TEXT = ("This asks WUD to recreate the container now via the dockercompose.local trigger. "
                "The app will be unavailable for about a minute.")
MANUAL_CONFIRM_TEXT = ("This is a manual update: the container is excluded from automatic updates, so "
                       "this asks WUD to recreate it now via the dockercompose.manual trigger. "
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

def _creds() -> tuple[str, str, str] | None:
    vals = [os.environ.get(n, "").strip() for n in ("WUD_URL", "WUD_USER", "WUD_PASS")]
    return (vals[0].rstrip("/"), vals[1], vals[2]) if all(vals) else None


def trigger_path(container_id: str, trigger_name: str = TRIGGER_NAME) -> str:
    """Verified against WUD 9.3 (app/api/container.ts): POST, no body, 200 `{}` on success,
    404 for an unknown container/trigger, 500 when the trigger itself fails."""
    return (f"/api/containers/{quote(container_id, safe='')}"
            f"/triggers/{TRIGGER_TYPE}/{trigger_name}")


def trigger_name(row: dict) -> str:
    """`local` for rows WUD auto-updates, `manual` for the excluded ones."""
    return TRIGGER_NAME if row.get("auto") is True else MANUAL_TRIGGER_NAME


def run_trigger(container_id: str, trigger_name: str = TRIGGER_NAME) -> tuple[str, str | None]:
    """-> ('requested', None) | ('refused', 'HTTP 4xx/5xx') | ('unreachable', '<ExcType>')."""
    creds = _creds()
    if not creds:
        return "unreachable", "not configured"
    try:
        resp = requests.post(creds[0] + trigger_path(container_id, trigger_name), auth=(creds[1], creds[2]),
                             timeout=TIMEOUT)
    except Exception as exc:  # type only — requests errors embed the URL
        log.warning("wud trigger failed: %s", type(exc).__name__)
        return "unreachable", type(exc).__name__
    if 200 <= resp.status_code < 300:
        return "requested", None
    log.warning("wud trigger refused: HTTP %s", resp.status_code)
    return "refused", f"HTTP {resp.status_code}"


# ---- routes ----

def _pending_rows() -> list[dict]:
    snap = shell.get_snapshots().get(WUD_SNAPSHOT_ID)
    rows = ((snap.data or {}).get("containers") or []) if snap else []
    return [c for c in rows if isinstance(c, dict) and c.get("update_available")]


def _pending_row(name: str) -> dict | None:
    return next((c for c in _pending_rows() if c.get("name") == name), None)


def refusal(row: dict | None, name: str) -> str | None:
    """Why Update now must not run for this row, in words; None when it may."""
    if row is None:
        return f"No update is pending for {name} in the latest WUD sweep."
    hold = update_hold(name)
    if hold:                            # wud: by hand; joey-*: the next Joey deploy
        return HOLD_TEXT[hold] + "."
    if not row.get("id"):
        return "The WUD snapshot has no container id yet — try again after the next hourly sweep."
    if _creds() is None:
        return "WUD is not configured on the hub (WUD_URL, WUD_USER, WUD_PASS)."
    return None


def _major(tag) -> int | None:
    m = re.match(r"v?(\d+)", str(tag or ""))
    return int(m.group(1)) if m else None


def warnings(row: dict | None, name: str) -> list[str]:
    """Extra lines on the confirm step: VPN-routed apps and major version jumps."""
    if row is None:
        return []
    out = []
    if name in VPN_ROUTED:
        out.append(f"{name} routes through gluetun (VPN) — expect a brief network drop while it restarts.")
    if name == VPN_NAME:
        out.append("qBittorrent and Prowlarr share gluetun's network — if they lose their connection after "
                   "this update, restart them (or update them here) too.")
    old, new = _major(row.get("current_tag")), _major(row.get("new_tag"))
    if old is not None and new is not None and new > old:
        out.append(f"Major version jump ({row.get('current_tag')} → {row.get('new_tag')}) — "
                   "check the release notes for breaking changes first.")
    return out


def plan_all() -> tuple[list[dict], list[dict]]:
    """Update all: (rows to run, in order — gluetun first, then the band's order — each with its `trigger` and
    `warnings`; rows left out as {name, why}: wud / joey-* / no id, then the ignored ones)."""
    shown, ignored = split_updates(_pending_rows(), get_ignores())
    run, skip = [], []
    for row in shown:
        name = str(row.get("name") or "")
        why = refusal(row, name)
        if why:
            skip.append({"name": name, "why": why})
        else:
            run.append({**row, "trigger": f"{TRIGGER_TYPE}.{trigger_name(row)}", "warnings": warnings(row, name)})
    run.sort(key=lambda r: r.get("name") != VPN_NAME)   # stable: gluetun first, the rest keep their order
    return run, skip + [{"name": str(c.get("name") or "?"), "why": "Ignored."} for c in ignored]


def _page(request: Request, ctx: dict, status: int = 200, template: str = "server_update.html"):
    area = next((a for a in shell.registry.areas if a.layout == SERVER_LAYOUT), None)
    if area is None:
        return shell.not_found_page(request)
    # the shared shell env (hub/shell.py) carries every global (identity, static_v, ...)
    return shell.render_page(request, template, {
        "area": area, "confirm_text": CONFIRM_TEXT, **ctx}, active_id=area.id, status=status)


def _name(name: str) -> str | None:
    return name if NAME_RE.match(name or "") else None


def _back(**flash) -> RedirectResponse:
    return RedirectResponse("/server?" + urlencode(flash) + "#updates", status_code=303)


# Update all: declared before the per-row routes so "all" never reaches /server/updates/{name}/run.
def _all_msg(run: list) -> str | None:
    if _creds() is None:
        return "WUD is not configured on the hub (WUD_URL, WUD_USER, WUD_PASS)."
    return None if run else "Nothing to update — no pending row can run from here."


@router.get("/server/updates/all/run", response_class=HTMLResponse)
def run_all_step(request: Request, step: str = ""):
    if step != "confirm":
        return RedirectResponse("/server#updates", status_code=303)
    run, skip = plan_all()
    return _page(request, {"rows": run, "skipped": skip, "msg": _all_msg(run)}, template="server_update_all.html")


@router.post("/server/updates/all/run", dependencies=[Depends(same_origin)])
def run_all(request: Request):
    run, skip = plan_all()
    why = _all_msg(run)
    if why:
        return _page(request, {"rows": run, "skipped": skip, "msg": why}, 409, template="server_update_all.html")
    done = 0
    for i, row in enumerate(run):
        outcome, note = run_trigger(str(row["id"]), trigger_name(row))
        try:
            record_run(str(row["name"]), key_tag(row), outcome, note)
        except (sqlite3.Error, OSError) as exc:
            log.warning("server update run not recorded: %s", type(exc).__name__)
        done += outcome == "requested"
        if outcome == "unreachable":          # WUD is down: don't time out once per remaining row
            return _back(flash="all", n=done, m=len(run) - done, u=1)
    return _back(flash="all", n=done, m=len(run) - done)


@router.get("/server/updates/{name}/run", response_class=HTMLResponse)
def run_step(request: Request, name: str, step: str = ""):
    if step != "confirm":
        return RedirectResponse("/server#updates", status_code=303)
    if _name(name) is None:
        return _page(request, {"name": "?", "row": None, "msg": "No such container"}, 404)
    row = _pending_row(name)
    return _page(request, {"name": name, "row": row, "msg": refusal(row, name),
                           "confirm_text": CONFIRM_TEXT if (row or {}).get("auto") is True
                           else MANUAL_CONFIRM_TEXT, "warnings": warnings(row, name)})


@router.post("/server/updates/{name}/run", dependencies=[Depends(same_origin)])
def run_now(request: Request, name: str):
    if _name(name) is None:
        return _page(request, {"name": "?", "row": None, "msg": "No such container"}, 404)
    row = _pending_row(name)
    why = refusal(row, name)
    if why:
        return _page(request, {"name": name, "row": row, "msg": why}, 409)
    outcome, note = run_trigger(str(row["id"]), trigger_name(row))
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
    n, m = params.get("n") or "", params.get("m") or ""
    if kind == "all" and n.isdigit() and m.isdigit():
        return f"{int(n)} requested · {int(m)} refused" + (" · WUD unreachable" if params.get("u") == "1" else "")
    return None
