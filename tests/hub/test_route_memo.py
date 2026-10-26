"""JY-252 (2026-10-26): the suite's FastAPI dependency-analysis memo (tests/route_memo.py) is on, pinned to the
FastAPI the hub ships, and leaves request handling exactly as it was: every dependency still runs once per request on
every fresh app, a route's own `dependencies=[...]` never pile up across apps, and the hub's same-origin guard still
refuses a cross-site write after each reload."""
import importlib
import re
from pathlib import Path

import fastapi
import fastapi.routing
from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.testclient import TestClient

from tests import route_memo

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_memo_is_on_for_the_pinned_fastapi():
    pins = re.findall(r"^fastapi==(\S+)$", (REPO_ROOT / "hub" / "requirements.txt").read_text(encoding="utf-8"), re.M)
    # bumping FastAPI? re-check route_memo against the new get_dependant / _populate_api_route_state, then move the pin
    assert pins == [route_memo.MEMO_FASTAPI_VERSION] == [fastapi.__version__]
    assert getattr(fastapi.routing.get_dependant, "jy252_memo", False)
    assert route_memo.install() is True  # idempotent: a second install keeps the one memo


def _app(calls: list) -> FastAPI:
    """A fresh app over ONE module-level router, as a reload of hub.main builds."""
    app = FastAPI()
    app.include_router(ROUTER)
    app.state.calls = calls
    return app


def _route_guard(request: Request):
    request.app.state.calls.append("route-guard")


def _param_dep(request: Request, q: int = 0):
    request.app.state.calls.append(f"param-dep q={q}")
    return q


ROUTER = APIRouter(dependencies=[Depends(_route_guard)])


@ROUTER.post("/things/{tid}", dependencies=[Depends(_route_guard)])
def _write(tid: int, request: Request, q: int = Depends(_param_dep)):
    request.app.state.calls.append(f"endpoint tid={tid} q={q}")
    return {"tid": tid, "q": q}


def test_dependencies_run_once_per_request_on_every_fresh_app():
    for n in range(3):
        calls: list = []
        with TestClient(_app(calls)) as c:
            r = c.post(f"/things/{n}?q={n + 1}")
            assert r.status_code == 200 and r.json() == {"tid": n, "q": n + 1}
            # the router's and the route's guard (same callable: FastAPI's per-request cache runs it once), the param
            # dependency, the endpoint; never a guard per earlier app
            assert calls == ["route-guard", f"param-dep q={n + 1}", f"endpoint tid={n} q={n + 1}"], calls
            assert c.post("/things/x").status_code == 422  # validation still per request


def test_each_route_gets_its_own_dependency_list():
    seen = fastapi.routing.get_dependant.seen
    a = fastapi.routing.get_dependant(path="/things/{tid}", call=_write, scope="function")
    b = fastapi.routing.get_dependant(path="/things/{tid}", call=_write, scope="function")
    assert a is not b and a.dependencies is not b.dependencies and a.dependencies == b.dependencies
    a.dependencies.insert(0, "inserted")  # what _populate_api_route_state does with a route's own dependencies
    assert "inserted" not in b.dependencies
    assert all("inserted" not in d.dependencies for d in seen.values())


def test_the_hubs_same_origin_guard_still_refuses_after_each_reload(monkeypatch, tmp_path):
    import hub.main

    for _ in range(3):
        importlib.reload(hub.main)
        with TestClient(hub.main.app) as c:
            r = c.post("/media/follow/person/77", headers={"Origin": "https://elsewhere.example"})
            assert r.status_code == 403 and "Cross-site write refused" in r.text
