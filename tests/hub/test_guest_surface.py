"""Joey TV WP-B1 (2026-10-21): GuestGate on the media front - private and unknown paths are the ordinary Joey 404
(byte-identical), / goes to the guest home, no identity goes to sign-in (a forged Access header changes nothing),
/healthz names the front and the home, the private front 404s the public guest hostname (Q25a), the gate is the
innermost middleware, and hub.access_jwt.AccessGate never acts on the media front (it acts only on the private one).
Fixture names are invented ("Sample Friend"); no real address appears."""
import importlib
import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hub import access_jwt, guest, identity
from hub.identity import IDENTITY_HEADER, Identity

REPO_ROOT = Path(__file__).resolve().parents[2]
FORGED = {IDENTITY_HEADER: "forged@example.test"}
FRIEND = Identity(owner="jf:" + "f00d" * 8, name="Sample Friend", jf_user_id="f00d" * 8)   # a well-formed key (WP-B2: malformed jf: owners fail closed)
DENIED_GETS = ["/server", "/whoami", "/weather", "/a/calendar", "/docs", "/openapi.json", "/media/downloads",
               "/media/apps", "/media/following", "/media/server/history", "/money", "/signin/anything-else",
               "/media/title/movie/603/request"]


@pytest.fixture()
def app(monkeypatch):
    """hub.main on the real registry (config/areas.yaml), no snapshots."""
    monkeypatch.setenv("AREAS_PATH", str(REPO_ROOT / "config" / "areas.yaml"))
    monkeypatch.setenv("OWNER_EMAIL_YOU", "you@example.com")
    import hub.main
    importlib.reload(hub.main)
    return hub.main.app


@pytest.fixture()
def media(monkeypatch):
    monkeypatch.setenv("JOEY_FRONT", "media")


@pytest.fixture()
def friend(monkeypatch):
    monkeypatch.setattr(guest, "identity_provider", lambda scope: FRIEND)


@pytest.fixture()
def client(app):
    with TestClient(app) as c:
        yield c


def home() -> str:
    return guest.home_path()


def get(c, path, **kw):
    return c.get(path, follow_redirects=False, **kw)


# ---- private paths are the ordinary 404 ----

def test_private_paths_are_ordinary_404(media, client):
    unknown = get(client, "/no-such-page-xyz")
    assert unknown.status_code == 404 and unknown.headers["content-type"].startswith("text/html")
    for path in DENIED_GETS:
        r = get(client, path)
        assert (r.status_code, r.content) == (404, unknown.content), path
    sweep = client.post("/media/arr/sweep", follow_redirects=False)
    assert (sweep.status_code, sweep.content) == (404, unknown.content)
    assert client.post("/media/follow/movie/1", follow_redirects=False).content == unknown.content
    assert client.head("/server").status_code == 404


def test_signed_in_friend_gets_the_same_404(media, friend, client):
    unknown = get(client, "/no-such-page-xyz")
    for path in ("/server", "/media/downloads", "/a/calendar"):
        assert get(client, path).content == unknown.content, path


def test_root_redirects_to_the_guest_home(media, client):
    r = get(client, "/")
    assert r.status_code == 303 and r.headers["location"] == home() == "/a/media"


@pytest.mark.parametrize("headers", [{}, FORGED], ids=["no-header", "forged-access-header"])
def test_forged_access_header_ignored(media, client, headers):
    """No identity -> sign-in, with or without a forged Cf-Access-Authenticated-User-Email."""
    r = get(client, home(), headers=headers)
    assert r.status_code == 303 and r.headers["location"] == "/signin?next=%2Fa%2Fmedia"
    q = get(client, "/media/movies?sort=new", headers=headers)
    assert q.headers["location"] == "/signin?next=%2Fmedia%2Fmovies%3Fsort%3Dnew"


def test_media_identity_never_comes_from_the_access_header(media, client):
    from starlette.requests import Request
    scope = {"type": "http", "headers": [(IDENTITY_HEADER.lower().encode(), b"you@example.com")], "state": {}}
    assert identity.resolve_identity(Request(scope)).owner is None
    scope["state"]["identity"] = FRIEND
    assert identity.resolve_identity(Request(scope)) == FRIEND


def test_signed_in_friend_reaches_the_guest_home(media, friend, client):
    assert get(client, home()).status_code == 200


def test_public_paths_need_no_identity(media, client):
    assert get(client, "/healthz").status_code == 200
    assert get(client, "/static/joey.js").status_code == 200


# ---- /healthz contract (D-P18: the shell's BackPolicy reads `home`) ----

def test_healthz_names_the_media_front_and_home(media, client):
    body = get(client, "/healthz").json()
    assert body["front"] == "media" and body["home"] == "/a/media"


def test_healthz_on_the_private_front_has_no_home(client):
    body = get(client, "/healthz").json()
    assert body["front"] == "private" and "home" not in body


# ---- AccessGate x GuestGate ----

@pytest.fixture()
def enforce(monkeypatch):
    monkeypatch.setenv("ACCESS_JWT_VERIFY", "1")
    monkeypatch.setenv("ACCESS_AUD", "a" * 64)
    monkeypatch.setattr(access_jwt, "_fetch_jwks", lambda url: (_ for _ in ()).throw(AssertionError("no fetch")))
    access_jwt.reset()
    yield
    access_jwt.reset()


def test_access_gate_never_acts_on_the_media_front(media, enforce, client, caplog):
    """Even with ACCESS_JWT_VERIFY=1 in the environment (joey-media never carries it, Q23), the media front is
    GuestGate's alone: no 401, no key fetch, no access_jwt log line."""
    with caplog.at_level(logging.DEBUG):
        assert get(client, home(), headers=FORGED).status_code == 303
        assert get(client, "/server", headers=FORGED).status_code == 404
        assert get(client, "/healthz").status_code == 200
    assert not [r for r in caplog.records if "access_jwt" in r.getMessage()]


def test_access_gate_still_enforces_on_the_private_front(enforce, client):
    assert get(client, "/server", headers=FORGED).status_code == 401
    assert get(client, "/healthz").status_code == 200


def test_gate_order_guest_innermost_then_access(app):
    classes = [m.cls for m in app.user_middleware]
    assert classes[-1] is guest.GuestGate
    assert classes[-2] is access_jwt.AccessGate
    assert classes[-3].__name__ == "ShellMiddleware"


def test_denied_path_is_logged_by_the_shell(media, client, caplog):
    """GuestGate is innermost: ShellMiddleware's one request line still sees its 404."""
    with caplog.at_level(logging.INFO, logger="hub"):
        get(client, "/server")
    assert "GET /server owner=none -> 404" in [r.getMessage() for r in caplog.records]


# ---- step 8: the owner word in media mode ----

def test_owner_word_is_the_stored_identity_never_the_name(media, friend, client, caplog):
    with caplog.at_level(logging.INFO, logger="hub"):
        get(client, "/media/movies", headers=FORGED)
    lines = [r.getMessage() for r in caplog.records]
    assert any(ln.startswith(f"GET /media/movies owner={FRIEND.owner} -> ") for ln in lines), lines
    assert not any("Sample Friend" in ln or "forged@" in ln for ln in lines)


def test_from_lan_is_false_on_the_media_front(media):
    """joey-media's every visitor arrives through cloudflared from a bridge address: never "on the home network"."""
    from types import SimpleNamespace
    from hub import shell
    req = SimpleNamespace(headers={}, client=SimpleNamespace(host="172.19.0.4"))
    assert shell.from_lan(req) is False


# ---- Q25a: the private front's Host guard ----

@pytest.mark.parametrize("host", ["media.joeyhome.net", "MEDIA.joeyhome.net", "media.joeyhome.net:443"])
def test_private_front_404s_the_public_guest_host(client, host):
    r = get(client, "/healthz", headers={"host": host})
    assert r.status_code == 404 and r.headers["content-type"].startswith("text/html")
    assert get(client, "/", headers={"host": host}).status_code == 404
    assert get(client, "/healthz", headers={"host": "joeyhome.net"}).status_code == 200


def test_host_guard_override(client, monkeypatch):
    monkeypatch.setenv("MEDIA_PUBLIC_HOST", "media.example.test")
    assert get(client, "/healthz", headers={"host": "media.example.test"}).status_code == 404
    assert get(client, "/healthz", headers={"host": "media.joeyhome.net"}).status_code == 200


def test_media_front_has_no_host_guard(media, client):
    assert get(client, "/healthz", headers={"host": "media.joeyhome.net"}).status_code == 200


# ---- the private front is unchanged ----

def test_private_front_serves_private_pages(client):
    assert get(client, "/").status_code == 200
    assert get(client, "/a/calendar").status_code == 200
    assert get(client, "/no-such-page-xyz").status_code == 404
