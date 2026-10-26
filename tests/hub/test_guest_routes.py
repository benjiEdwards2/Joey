"""Joey TV WP-B1 (2026-10-21): the guest front's route allow-list (hub/guest.py) - the unit cases, the
route-classification gate (every route of hub.main.app in exactly one table, an unclassified route named), and the
frozen interfaces (Identity fields, the TV user-agent token, OWNER_KEY_RE imported not redefined)."""
import ast
import dataclasses
import importlib
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from starlette.routing import Mount, Route

from hub import guest, identity
from hub.registry import load_registry

REPO_ROOT = Path(__file__).resolve().parents[2]
AREAS = load_registry(REPO_ROOT / "config" / "areas.yaml")   # the real registry as the fixture registry


def shelves_id(registry=AREAS) -> str:
    return next(a.id for a in registry.areas if a.layout == "shelves")


# ---- step 2: allows() ----

@pytest.mark.parametrize("method, path, expected", [
    ("GET", "/media/title/movie/603", True),
    ("GET", "/media/downloads", False),
    ("POST", "/media/follow/movie/1", False),
    ("GET", "/a/calendar", False),
    ("HEAD", "/healthz", True),
    ("GET", "/healthz", True),
    ("GET", "/static/joey.css", True),
    ("GET", "/img/poster/abc", True),
    ("POST", "/media/rate", True),
    ("DELETE", "/media/rate/movie:603", True),
    ("POST", "/media/resume/0123456789abcdef0123456789abcdef/watched", True),
    ("GET", "/media/server/history", False),               # Q18: the household play log is PRIVATE
    ("POST", "/media/title/movie/603/search", False),      # Q19
    ("GET", "/media/title/movie/603/arr", False),
    ("GET", "/media/title/movie/603/request", True),       # GUEST since WP-B4 (friend requests, X-Api-User)
    ("POST", "/media/title/movie/603/request", True),
    ("GET", "/signin", True),                              # GUEST since WP-B2 (sign-in, public)
    ("POST", "/signin/password", True),
    ("POST", "/signin/qc/start", True),
    ("GET", "/signin/qc/poll", True),
    ("POST", "/signout", True),
    ("GET", "/signin/anything-else", False),               # only the WP-B2 routes, nothing under them
    ("GET", "/signout", False),
    ("GET", "/app/version.json", True),                    # WP-B8: public (Q37)
    ("HEAD", "/app", True),
    ("POST", "/app/version.json", False),
    ("GET", "/", False),                                   # GuestGate redirects / before asking allows()
    ("GET", "/no-such-page-xyz", False),
    ("PUT", "/media/rate", False),
    ("GET", "/media/rate", False),
    ("OPTIONS", "/media/movies", False),
])
def test_allows_cases(method, path, expected):
    assert guest.allows(method, path, AREAS) is expected


def test_the_guest_home_is_the_registry_shelves_area():
    home = f"/a/{shelves_id()}"
    assert guest.home_path(AREAS) == home
    assert guest.allows("GET", home, AREAS) is True
    assert guest.allows("HEAD", home, AREAS) is True
    assert guest.allows("POST", home, AREAS) is False
    others = [a.id for a in AREAS.areas if a.layout != "shelves"]
    assert others and not any(guest.allows("GET", f"/a/{i}", AREAS) for i in others)


def test_no_registry_means_no_guest_home():
    assert guest.home_path(type("R", (), {"areas": []})()) is None


@pytest.mark.parametrize("value, expected", [(None, "private"), ("", "private"), ("  ", "private"),
                                             ("private", "private"), ("media", "media"), (" Media ", "media")])
def test_front_reads_joey_front_on_every_call(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv("JOEY_FRONT", raising=False)
    else:
        monkeypatch.setenv("JOEY_FRONT", value)
    assert guest.front() == expected


def test_bogus_joey_front_raises(monkeypatch):
    monkeypatch.setenv("JOEY_FRONT", "bogus")
    with pytest.raises(ValueError, match="JOEY_FRONT"):
        guest.front()
    with pytest.raises(ValueError, match="JOEY_FRONT"):
        guest.startup()


def test_bogus_joey_front_stops_startup(tmp_path, monkeypatch):
    """The lifespan validates first: the container crash-loops visibly instead of serving the wrong front."""
    from fastapi.testclient import TestClient
    import hub.main
    importlib.reload(hub.main)
    monkeypatch.setenv("JOEY_FRONT", "bogus")
    with pytest.raises(ValueError, match="JOEY_FRONT"):
        with TestClient(hub.main.app):
            pass


def test_nav_visibility_derives_from_allows():
    assert guest.href_allowed("/media/movies", AREAS) and guest.href_allowed("/media/history?x=1", AREAS)
    assert not guest.href_allowed("/media/playing", AREAS) and not guest.href_allowed("/media/following", AREAS)


# ---- step 3: the route-classification gate ----

def _included(route):
    """FastAPI 0.138 keeps each include_router as an _IncludedRouter: (its prefix, its routes), else None."""
    original = getattr(route, "original_router", None)
    if original is None:
        return None
    return getattr(route.include_context, "prefix", "") or "", original.routes


def route_pairs(routes, prefix: str = "") -> set:
    """(method, path template) for every route: APIRoute / Route methods (HEAD folded into GET), FastAPI's docs routes,
    and a Mount as GET <path>/{path:path}."""
    out = set()
    for r in routes:
        inc = _included(r)
        if inc is not None:
            out |= route_pairs(inc[1], prefix + inc[0])
        elif isinstance(r, Mount):
            out.add(("GET", prefix + r.path + "/{path:path}"))
        elif isinstance(r, (APIRoute, Route)):
            out |= {(m, prefix + r.path) for m in (r.methods or {"GET"}) - {"HEAD"}}
        else:
            out.add(("?", f"{type(r).__name__}:{getattr(r, 'path', r)}"))   # an unknown route kind is unclassified
    return out


def classification_problems(app) -> list[str]:
    tables = {"GUEST": set(guest.GUEST), "PRIVATE": set(guest.PRIVATE), "RESERVED": set(guest.RESERVED)}
    pairs = route_pairs(app.routes)
    problems = []
    for method, path in sorted(pairs):
        homes = [name for name, table in tables.items() if (method, path) in table]
        if len(homes) != 1:
            problems.append(f"{method} {path}: in {homes or 'no table'}")
    for name in ("GUEST", "PRIVATE"):   # RESERVED may name routes their WP has not built yet
        problems += [f"{m} {p}: stale {name} entry" for m, p in sorted(tables[name] - pairs)]
    return problems


def test_every_route_classified():
    import hub.main
    importlib.reload(hub.main)
    assert classification_problems(hub.main.app) == []


def test_tables_have_no_duplicates_and_no_overlap():
    for table in (guest.GUEST, guest.PRIVATE, guest.RESERVED):
        assert len(table) == len(set(table))
    assert not set(guest.GUEST) & set(guest.PRIVATE)
    assert not set(guest.GUEST) & set(guest.RESERVED)
    assert not set(guest.PRIVATE) & set(guest.RESERVED)
    assert set(guest.PUBLIC) <= set(guest.GUEST)


def test_an_extra_route_is_reported_by_name():
    """Meta: a throwaway app with the real routes plus @app.get('/x-new') fails the gate, naming /x-new."""
    import hub.main
    importlib.reload(hub.main)
    scratch = FastAPI()
    scratch.router.routes.extend(hub.main.app.routes)

    @scratch.get("/x-new")
    def x_new():
        return {}

    problems = classification_problems(scratch)
    assert problems == ["GET /x-new: in no table"]


def test_a_removed_route_is_reported_stale():
    scratch = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    problems = classification_problems(scratch)
    assert "GET /media/movies: stale GUEST entry" in problems
    assert "GET /server: stale PRIVATE entry" in problems


def _sample(template: str) -> str:
    fill = {"kind": "movie", "tmdb_id": "603", "jf_id": "0123456789abcdef0123456789abcdef", "provider_id": "8",
            "person_id": "287", "name": "x", "n": "1", "item_key": "movie:603", "ref:path": "poster/x",
            "path:path": "joey.css", "area_id": "calendar", "rid": "1", "app": "radarr", "arr_id": "1",
            "year": "2026", "rest:path": "x", "session_id": "abc", "item_id": "0123456789abcdef0123456789abcdef"}
    out = template
    for k, v in fill.items():
        out = out.replace("{" + k + "}", v)
    assert "{" not in out, template
    return out


def test_every_guest_route_is_allowed_and_every_private_or_reserved_one_denied():
    for method, template in guest.GUEST:
        assert guest.allows(method, _sample(template), AREAS), (method, template)
    for method, template in guest.PRIVATE + guest.RESERVED:
        assert not guest.allows(method, _sample(template), AREAS), (method, template)


# ---- step 4: frozen interfaces ----

def test_identity_fields_are_frozen_with_defaults():
    fields = [(f.name, f.default) for f in dataclasses.fields(identity.Identity)]
    assert fields == [("owner", dataclasses.MISSING), ("name", dataclasses.MISSING), ("email", None),
                      ("jf_user_id", None), ("jf_token", None)]
    assert identity.Identity.__dataclass_params__.frozen
    who = identity.Identity(owner="jf:" + "f" * 32, name="Sample Friend", jf_user_id="f" * 32, jf_token="secret-tok")
    assert "secret-tok" not in repr(who)   # a token never reaches a log line through repr


def test_tv_ua_token():
    assert guest.TV_UA_TOKEN == "JoeyTV/"


def test_guest_imports_owner_key_re_and_never_redefines_it():
    tree = ast.parse((REPO_ROOT / "hub" / "guest.py").read_text(encoding="utf-8"))
    imported = [a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module == "hub.identity"
                for a in n.names]
    assert "OWNER_KEY_RE" in imported
    assigned = [t.id for n in ast.walk(tree) if isinstance(n, (ast.Assign, ast.AnnAssign))
                for t in (n.targets if isinstance(n, ast.Assign) else [n.target]) if isinstance(t, ast.Name)]
    assert "OWNER_KEY_RE" not in assigned
    assert guest.OWNER_KEY_RE is identity.OWNER_KEY_RE


# ---- step 11: the dev identity seam (Q31) ----

@pytest.mark.parametrize("hub_dev, front, honoured", [
    ("1", "media", True), ("1", None, False), ("0", "media", False), (None, "media", False), ("1", "private", False),
])
def test_guest_dev_owner_only_with_hub_dev_on_the_media_front(monkeypatch, hub_dev, front, honoured):
    monkeypatch.setenv("GUEST_DEV_OWNER", "jf:devfriend")
    for key, value in (("HUB_DEV", hub_dev), ("JOEY_FRONT", front)):
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)
    who = guest.dev_identity()
    assert (who is not None) is honoured
    if honoured:
        assert who.owner == "jf:devfriend"
