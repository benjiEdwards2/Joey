"""JY-301 (2026-11-03): pause / resume / remove torrents from Activity > Downloads, against a FAKE qBittorrent that records
every call (`requests.get` / `requests.post` monkeypatched; conftest routes `upstream.session` through them, so nothing
reaches the network or the live qBittorrent). Owner only, flag DOWNLOAD_CONTROLS=1, deleteFiles=true only after TWO POSTs."""
import importlib
import json
import logging
import re
from pathlib import Path

import pytest
import requests
from fastapi.testclient import TestClient

from hub import guest, media_download_actions as mda
from hub.identity import IDENTITY_HEADER
from tests.hub.helpers import write_envelope
from tests.hub.test_server_quiet import Resp

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / "config" / "sample_snapshots"
URL, USER, PASSWORD = "http://qbit.secret-host.invalid:8080", "joeywriter", "QBITSECRETpass"
H = "abcdefabcdefabcdefabcdefabcdefabcdefabcd"            # Example.Movie (Downloading) in the sample snapshot
PAUSED = "acebdfacebdfacebdfacebdfacebdfacebdfaceb"       # Fixture.Distro.Image (Paused)
EVIL = {"origin": "https://evil.example"}
AS_YOU = {IDENTITY_HEADER: "you@example.invalid"}
AS_HER = {IDENTITY_HEADER: "her@example.invalid"}


class FakeQbit:
    """qBittorrent 5.x (stop / start) by default; `old=True` answers 404 there like 4.x and serves pause / resume."""

    def __init__(self):
        self.calls, self.old, self.present = [], False, {H, PAUSED}
        self.login, self.down = Resp(204, None, {"SID": "sid123"}), False

    def writes(self):
        return [c for c in self.calls if c["method"] == "POST" and not c["url"].endswith("/auth/login")]

    def post(self, url, **kw):
        self.calls.append({"method": "POST", "url": url, **kw})
        if self.down:
            raise requests.ConnectionError(URL)
        if url.endswith("/api/v2/auth/login"):
            return self.login
        path = url.split("/api/v2/", 1)[1]
        if path in ("torrents/stop", "torrents/start"):
            return Resp(404 if self.old else 200)
        if path in ("torrents/pause", "torrents/resume"):
            return Resp(200 if self.old else 404)
        if path == "torrents/delete":
            self.present.discard(kw["data"]["hashes"])
            return Resp(200)
        raise AssertionError(url)

    def get(self, url, **kw):
        self.calls.append({"method": "GET", "url": url, **kw})
        if self.down:
            raise requests.ConnectionError(URL)
        assert url.endswith("/api/v2/torrents/info"), url
        h = kw["params"]["hashes"]
        return Resp(200, [{"hash": h, "state": "downloading"}] if h in self.present else [])


@pytest.fixture(autouse=True)
def _fresh():
    mda.clear_cache()
    yield
    mda.clear_cache()


@pytest.fixture()
def qbit(monkeypatch):
    fake = FakeQbit()
    monkeypatch.setattr(requests, "post", fake.post)
    monkeypatch.setattr(requests, "get", fake.get)
    return fake


@pytest.fixture()
def env(tmp_path, monkeypatch, qbit):
    monkeypatch.delenv("AREAS_PATH", raising=False)
    snaps = tmp_path / "snaps"
    snaps.mkdir()
    monkeypatch.setenv("SNAPSHOT_DIR", str(snaps))
    monkeypatch.setenv("OWNER_EMAIL_YOU", "you@example.invalid")

    def build(flag=True, creds=True):
        for name, value in (("QBIT_URL", URL + "/"), ("QBIT_USER", USER), ("QBIT_PASS", PASSWORD), ("DOWNLOAD_CONTROLS", "1")):
            if (flag if name == "DOWNLOAD_CONTROLS" else creds):
                monkeypatch.setenv(name, value)
            else:
                monkeypatch.delenv(name, raising=False)
        for p in SAMPLES.glob("*.json"):
            if not p.stem.startswith("_"):
                write_envelope(snaps, p.stem, age_minutes=1, data=json.loads(p.read_text(encoding="utf-8"))["data"])
        import hub.main
        importlib.reload(hub.main)
        return TestClient(hub.main.app)
    build.qbit = qbit
    return build


def post(c, path, data=None, headers=None):
    return c.post(path, data=data or {}, headers=headers, follow_redirects=False)


def sent(fake, path):
    return [c["data"] for c in fake.writes() if c["url"].endswith(path)]


# ---- 1. each action sends exactly one correct call with the right hash ----

@pytest.mark.parametrize("route, path, word", [("pause", "torrents/stop", "paused"), ("resume", "torrents/start", "resumed")])
def test_pause_and_resume_send_one_call(env, route, path, word):
    with env() as c:
        r = post(c, f"/media/downloads/{route}", {"hash": H})
    assert r.status_code == 303 and r.headers["location"] == f"/media/downloads?dl={word}"
    assert [c["data"] for c in env.qbit.writes()] == [{"hashes": H}] and env.qbit.writes()[0]["url"].endswith(path)


def test_remove_keep_files_sends_one_delete_false_and_the_row_drops(env):
    with env() as c:
        r = post(c, "/media/downloads/remove", {"hash": H})
        assert r.headers["location"] == "/media/downloads?dl=removed"
        page = c.get(r.headers["location"]).text
    assert [c["data"] for c in env.qbit.writes()] == [{"hashes": H, "deleteFiles": "false"}]
    assert "Removed" in page and "Example.Movie.2024.2160p.WEB-DL" not in page.split("Finished today")[0]


def test_pause_overlays_the_row_until_a_newer_snapshot(env):
    with env() as c:
        page = c.get(post(c, "/media/downloads/pause", {"hash": H}).headers["location"]).text
    row = page.split("Example.Movie.2024.2160p.WEB-DL", 1)[1].split("</form>", 1)[0]
    assert "Paused" in row and "Resume" in row


# ---- 2. deleteFiles=true only after the second confirm POST ----

def test_delete_files_needs_two_posts(env):
    with env() as c:
        first = post(c, "/media/downloads/remove", {"hash": H, "files": "1"})
        assert first.status_code == 200 and env.qbit.calls == []           # the first POST calls nothing at all
        token = re.search(r'name="token" value="([^"]+)"', first.text).group(1)
        assert "Example.Movie.2024.2160p.WEB-DL" in first.text and "delete-files" in first.text
        r = post(c, "/media/downloads/delete-files", {"hash": H, "token": token})
        assert r.headers["location"] == "/media/downloads?dl=deleted"
        assert sent(env.qbit, "torrents/delete") == [{"hashes": H, "deleteFiles": "true"}]
        # the token is single use
        post(c, "/media/downloads/delete-files", {"hash": H, "token": token})
    assert len(sent(env.qbit, "torrents/delete")) == 1


@pytest.mark.parametrize("form", [
    {"hash": H}, {"hash": H, "token": ""}, {"hash": H, "token": "forged"}, {"hash": H, "files": "1"},
    {"hash": H, "deleteFiles": "true"}, {"hash": H, "files": "1", "deleteFiles": "true", "confirm": "1"},
])
def test_no_single_post_can_send_delete_files_true(env, form):
    with env() as c:
        for route in ("pause", "resume", "remove", "delete-files", "pause-all", "resume-all"):
            post(c, f"/media/downloads/{route}", form)
    assert all(d.get("deleteFiles") != "true" for d in (c["data"] for c in env.qbit.writes()))


def test_a_token_for_one_hash_cannot_delete_another(env):
    with env() as c:
        token = re.search(r'name="token" value="([^"]+)"',
                          post(c, "/media/downloads/remove", {"hash": H, "files": "1"}).text).group(1)
        post(c, "/media/downloads/delete-files", {"hash": PAUSED, "token": token})
    assert env.qbit.writes() == []


# ---- 3. all / hash validation ----

@pytest.mark.parametrize("route, path", [("pause-all", "torrents/stop"), ("resume-all", "torrents/start")])
def test_all_sends_hashes_all(env, route, path):
    with env() as c:
        assert post(c, f"/media/downloads/{route}").status_code == 303
    assert sent(env.qbit, path) == [{"hashes": "all"}]


@pytest.mark.parametrize("bad", ["all", "", "xyz", H[:-1], H + "0", H + "a" * 30, H.upper(), H + "|" + PAUSED])
def test_row_routes_reject_bad_hashes(env, bad):
    with env() as c:
        for route in ("pause", "resume", "remove", "delete-files"):
            assert post(c, f"/media/downloads/{route}", {"hash": bad, "token": "x"}).status_code == 400
    assert env.qbit.calls == []


def test_a_64_hex_v2_hash_is_accepted():
    assert mda.valid_hash("a" * 64) and mda.valid_hash("0" * 40) and not mda.valid_hash("a" * 41)


# ---- 4. 5.x stop / start and older pause / resume ----

@pytest.mark.parametrize("route, new, old", [("pause", "stop", "pause"), ("resume", "start", "resume")])
def test_older_qbittorrent_falls_back_on_404(env, route, new, old):
    env.qbit.old = True
    with env() as c:
        assert post(c, f"/media/downloads/{route}", {"hash": H}).headers["location"].endswith(f"dl={route}d")
    assert [w["url"].rsplit("/", 1)[1] for w in env.qbit.writes()] == [new, old]


# ---- 5. failures: named flash, no state change ----

def test_login_refused(env):
    env.qbit.login = Resp(403)
    with env() as c:
        r = post(c, "/media/downloads/pause", {"hash": H})
        assert r.headers["location"] == "/media/downloads?dl=refused"
        assert "Login refused" in c.get(r.headers["location"]).text
    assert env.qbit.writes() == []


def test_upstream_down(env):
    env.qbit.down = True
    with env() as c:
        r = post(c, "/media/downloads/remove", {"hash": H})
        assert r.headers["location"] == "/media/downloads?dl=down"
        assert "qBittorrent is not reachable" in c.get(r.headers["location"]).text


def test_unknown_hash_is_already_gone(env):
    env.qbit.present = set()
    with env() as c:
        r = post(c, "/media/downloads/pause", {"hash": H})
        assert r.headers["location"] == "/media/downloads?dl=gone"
        assert "Already gone" in c.get(r.headers["location"]).text
    assert env.qbit.writes() == []


# ---- 6. cross-site, GET ----

def test_cross_site_posts_are_refused_and_get_never_writes(env):
    with env() as c:
        for route in ("pause", "resume", "remove", "delete-files", "pause-all", "resume-all"):
            assert post(c, f"/media/downloads/{route}", {"hash": H}, headers=EVIL).status_code == 403
            assert c.get(f"/media/downloads/{route}?hash={H}", follow_redirects=False).status_code == 303
    assert env.qbit.calls == []


# ---- 7 / 8. friends, media front, flag ----

def test_owner_sees_buttons_her_sees_none_and_gets_404(env):
    with env() as c:
        mine = c.get("/media/downloads", headers=AS_YOU).text
        hers = c.get("/media/downloads", headers=AS_HER).text
        for route in ("pause", "resume", "remove", "delete-files", "pause-all", "resume-all"):
            assert post(c, f"/media/downloads/{route}", {"hash": H}, headers=AS_HER).status_code == 404
    assert "/media/downloads/pause" in mine and "Pause all" in mine and "Resume" in mine
    assert "/media/downloads/" not in hers.replace('href="/media/downloads"', "") and "Pause all" not in hers
    assert "Example.Movie.2024.2160p.WEB-DL" in hers
    assert env.qbit.calls == []


def test_flag_off_or_no_creds_hides_buttons_and_404s(env):
    for kw in ({"flag": False}, {"creds": False}):
        with env(**kw) as c:
            page = c.get("/media/downloads").text
            assert "Pause all" not in page and "/media/downloads/pause" not in page
            for route in ("pause", "remove", "delete-files", "pause-all"):
                assert post(c, f"/media/downloads/{route}", {"hash": H}).status_code == 404
    assert env.qbit.calls == []


def test_routes_are_private_in_the_guest_table():
    for route in ("pause", "resume", "remove", "delete-files", "pause-all", "resume-all"):
        assert not guest.allows("POST", f"/media/downloads/{route}")
        assert not guest.allows("GET", f"/media/downloads/{route}")
    assert all(not p.startswith("/media/downloads") for _, p in guest.GUEST)


def test_the_media_front_never_serves_them(monkeypatch, tmp_path):
    from tests.hub.fake_jellyfin import FRIEND_ID
    from tests.hub.guest_pages import guest_client, sign_in
    monkeypatch.setenv("DOWNLOAD_CONTROLS", "1")
    client, fake = guest_client(monkeypatch, tmp_path, {})
    with client as c:
        sign_in(c, fake, FRIEND_ID)
        for route in ("pause", "remove", "delete-files", "pause-all"):
            assert c.post(f"/media/downloads/{route}", data={"hash": H}, follow_redirects=False).status_code == 404
        assert c.get("/media/downloads", follow_redirects=False).status_code == 404


# ---- 9. no secrets in logs or flashes ----

def test_no_secret_url_user_or_hash_in_logs_or_flashes(env, caplog):
    caplog.set_level(logging.DEBUG)
    with env() as c:
        pages = []
        for setup in (lambda q: setattr(q, "down", True), lambda q: setattr(q, "login", Resp(401)),
                      lambda q: (setattr(q, "down", False), setattr(q, "login", Resp(204, None, {"SID": "s"})))):
            setup(env.qbit)
            r = post(c, "/media/downloads/pause", {"hash": H})
            pages.append(r.headers["location"] + c.get(r.headers["location"]).text.split("<main", 1)[1].split("Movies", 1)[0])
    blob = caplog.text + "".join(pages)
    for secret in (PASSWORD, USER, "secret-host", "8080", H, "sid123"):
        assert secret not in blob, secret
