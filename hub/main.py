"""Joey hub — FastAPI skeleton. Every route and the tab bar render from
areas.yaml; no area name appears in this code (WP17 verify greps for that).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from hub.registry import Registry, load_registry
from hub.store import get_snapshots, tile_state

HUB_DIR = Path(__file__).resolve().parent
REPO_ROOT = HUB_DIR.parent
IDENTITY_HEADER = "Cf-Access-Authenticated-User-Email"

log = logging.getLogger("hub")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

registry: Registry | None = None
registry_loaded_at: str | None = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Load the registry at startup, failing fast with the aggregated violation list."""
    global registry, registry_loaded_at
    areas_path = os.environ.get("AREAS_PATH", str(REPO_ROOT / "config" / "areas.yaml"))
    registry = load_registry(areas_path)  # ValueError here aborts startup by design
    registry_loaded_at = datetime.now(timezone.utc).isoformat()
    log.info("registry loaded from %s: %d areas", areas_path, len(registry.areas))
    yield


app = FastAPI(title="Joey hub", lifespan=lifespan)


@app.middleware("http")
async def log_identity(request: Request, call_next):
    email = request.headers.get(IDENTITY_HEADER, "-")
    response = await call_next(request)
    log.info('%s %s user=%s -> %d', request.method, request.url.path, email, response.status_code)
    return response


app.mount("/static", StaticFiles(directory=str(HUB_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(HUB_DIR / "templates"))


OWNER_VIEWS = ("both", "you", "her")
OWNER_COOKIE = "owner_view"
OWNER_COOKIE_MAX_AGE = 30 * 24 * 3600  # 30 days, per device (WP19)


def resolve_owner_view(request: Request) -> tuple[str, bool]:
    """Query param wins (and sets the cookie); else cookie; else 'both'.

    Semantics per Q9 (answered 2026-08-25): you = you+shared, her = her+shared.
    Returns (view, came_from_query).
    """
    q = request.query_params.get(OWNER_COOKIE)
    if q in OWNER_VIEWS:
        return q, True
    c = request.cookies.get(OWNER_COOKIE)
    return (c if c in OWNER_VIEWS else "both"), False


def owner_visible(tile, view: str) -> bool:
    return view == "both" or tile.owner.value == "shared" or tile.owner.value == view


def _maybe_set_cookie(response, view: str, from_query: bool):
    if from_query:
        response.set_cookie(OWNER_COOKIE, view, max_age=OWNER_COOKIE_MAX_AGE, samesite="lax")
    return response


def build_status(snaps) -> dict:
    """Cockpit status strip: feed health computed from registry vs snapshots."""
    wanted: dict[str, str] = {}   # connector id -> first area name using it
    for a in registry.areas:
        for t in a.tiles:
            if t.snapshot and t.snapshot not in wanted:
                wanted[t.snapshot] = a.name
    stale = sorted({
        wanted[cid] for cid, s in snaps.items()
        if cid in wanted and any(
            t.snapshot == cid and t.stale_after_minutes and s.age_minutes > t.stale_after_minutes
            for a in registry.areas for t in a.tiles)
    })
    return {
        "feeds_total": len(wanted),
        "feeds_ok": sum(1 for cid in wanted if cid in snaps),
        "stale": stale,
    }


@app.get("/", response_class=HTMLResponse)
def hub_page(request: Request):
    view, from_query = resolve_owner_view(request)
    snaps = get_snapshots()
    cards = []
    for a in registry.areas:
        summary = next(t for t in a.tiles if t.id == a.summary_tile)
        if not owner_visible(summary, view):
            continue  # hub summary cards respect the filter (Q24 assumption)
        cards.append({"area": a, "tile": summary, "st": tile_state(summary, snaps)})
    resp = templates.TemplateResponse(request, "hub.html", {
        "areas": registry.areas, "active_id": None, "cards": cards, "owner_view": view,
        "status": build_status(snaps),
    })
    return _maybe_set_cookie(resp, view, from_query)


@app.get("/a/{area_id}", response_class=HTMLResponse)
def area_page(request: Request, area_id: str):
    view, from_query = resolve_owner_view(request)
    area = next((a for a in registry.areas if a.id == area_id), None)
    if area is None:
        return templates.TemplateResponse(request, "404.html", {
            "areas": registry.areas, "active_id": None, "missing_id": area_id,
            "owner_view": view,
        }, status_code=404)
    snaps = get_snapshots()
    tiles = [{"tile": t, "st": tile_state(t, snaps)}
             for t in area.tiles if owner_visible(t, view)]
    resp = templates.TemplateResponse(request, "area.html", {
        "areas": registry.areas, "active_id": area.id, "area": area, "tiles": tiles,
        "owner_view": view, "status": build_status(snaps),
    })
    return _maybe_set_cookie(resp, view, from_query)


@app.get("/healthz")
def healthz():
    return {
        "status": "ok",
        "areas": len(registry.areas) if registry else 0,
        "registry_loaded_at": registry_loaded_at,
    }


@app.get("/whoami")
def whoami(request: Request):
    return JSONResponse({"email": request.headers.get(IDENTITY_HEADER, "-")})
