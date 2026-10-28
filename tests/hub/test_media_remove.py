"""JY-265 phase 1: Remove on a title page, request only (spec docs/specs/JY-265-remove.md).

Seerr (request read + delete, shapes from tests/hub/fixtures/seerr_request*.json), Radarr / Sonarr (tests/hub/fake_arr.py)
and the Discord webhook are faked at requests.get / put / delete / post; no network. B.'s picks, 2026-10-28: Q1 A (owner
"you" only; everyone else gets the ordinary 404 page), Q4 A (unmonitor, keep the entry), Q9 A (a Discord line).
"""
import copy
import importlib
import json
import logging
import sqlite3
from pathlib import Path

import pytest
import requests
import yaml
from fastapi.testclient import TestClient

from hub import media_hidden, media_remove
from tests.hub.conftest import main_of
from tests.hub.fake_arr import FakeArr, RADARR, SONARR, Resp
from tests.hub.helpers import make_area, write_envelope

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = json.loads((ROOT / "config" / "sample_snapshots" / "jellyseerr.json").read_text(encoding="utf-8"))["data"]
FIX = Path(__file__).resolve().parent / "fixtures"
SEERR = "http://seerr.secret-host.invalid:5055"
SKEY = "k-SECRET-seerr"
HOOK = "https://discord.invalid/api/webhooks/123/SECRET-hook"
ORIGIN_BAD = {"Origin": "https://evil.invalid"}
SECRETS = ("secret-host", "SECRET", SKEY, HOOK)

FILM = "/media/remove/movie/1001"      # Midnight Harbour: Pending, nothing on disk (SAMPLE row 13)
SHOW = "/media/remove/tv/2002"         # Night Ferry: Approved, Seasons 1-2 (SAMPLE row 14)
ON_DISK = "/media/remove/movie/1003"   # Desert Crossing: Available (SAMPLE row 12)


class Fake:
    """Seerr's request read / delete + FakeArr + the Discord webhook, each call counted."""

    def __init__(self):
        self.arr = FakeArr()
        self.seerr: list[tuple] = []           # (method, path)
        self.discord: list[str] = []
        self.delete_status = 204
        self.read_status: dict[int, int] = {}  # request id -> forced status of the live read
        self.seerr_raise = None
        shape = json.loads((FIX / "seerr_request.json").read_text(encoding="utf-8"))["body"]
        self.live = {}
        for row in SAMPLE["requests"]:
            body = copy.deepcopy(shape)
            body.update(id=row["id"], type=row["kind"], status=2)
            body["media"].update(tmdbId=row["tmdb_id"], mediaType=row["kind"],
                                 status=5 if row["status_text"] == "Available" else 2)
            self.live[row["id"]] = body

    def _seerr(self, method, url, headers):
        assert headers == {"X-Api-Key": SKEY}
        path = url[len(SEERR):]
        self.seerr.append((method, path))
        if self.seerr_raise:
            raise self.seerr_raise(f"Max retries exceeded with url: {url} key={SKEY}")
        return path

    def get(self, url, params=None, headers=None, timeout=None, **kw):
        assert timeout
        if FakeArr.handles(url):
            return self.arr.get(url, params=params, headers=headers, timeout=timeout)
        path = self._seerr("GET", url, headers)
        if path.startswith("/api/v1/request/"):
            rid = int(path.rsplit("/", 1)[1])
            if rid in self.read_status:
                return Resp({}, self.read_status[rid])
            return Resp(copy.deepcopy(self.live[rid])) if rid in self.live else Resp({"message": "Request not found."}, 404)
        return Resp({}, 404)

    def delete(self, url, headers=None, timeout=None, **kw):
        assert timeout
        if FakeArr.handles(url):
            return self.arr.delete(url, headers=headers, timeout=timeout, **kw)
        path = self._seerr("DELETE", url, headers)
        if self.delete_status == 204:
            self.live.pop(int(path.rsplit("/", 1)[1]), None)
        return Resp(None, self.delete_status)

    def put(self, url, json=None, headers=None, timeout=None, **kw):
        assert FakeArr.handles(url), url
        return self.arr.put(url, json=json, headers=headers, timeout=timeout)

    def post(self, url, json=None, headers=None, timeout=None, **kw):
        if url == HOOK:
            self.discord.append(json["content"])
            return Resp({}, 204)
        if FakeArr.handles(url):
            return self.arr.post(url, json=json, headers=headers, timeout=timeout)
        self._seerr("POST", url, headers)
        return Resp({}, 404)

    def total(self) -> int:
        return len(self.seerr) + len(self.arr.calls) + len(self.discord)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    area = make_area("alpha", "req-t", snapshot="jellyseerr", stale_after_minutes=180, detail="/media/requests")
    path = tmp_path / "areas.yaml"
    path.write_text(yaml.safe_dump({"areas": [area]}), encoding="utf-8")
    monkeypatch.setenv("AREAS_PATH", str(path))
    monkeypatch.setenv("MEDIA_DB_PATH", str(tmp_path / "media.db"))
    monkeypatch.setenv("JELLYSEERR_URL", SEERR)
    monkeypatch.setenv("JELLYSEERR_API_KEY", SKEY)
    monkeypatch.setenv("SERVER_DISCORD_WEBHOOK", HOOK)
    monkeypatch.setenv("REMOVE_API", "on")
    snaps = tmp_path / "snaps"
    monkeypatch.setenv("SNAPSHOT_DIR", str(snaps))
    media_hidden.clear()
    media_remove.clear()

    def build(data=None):
        write_envelope(snaps, "jellyseerr", age_minutes=1, data=copy.deepcopy(data or SAMPLE))
        import hub.main
        importlib.reload(hub.main)
        fake = Fake()
        for k, v in fake.arr.env().items():
            monkeypatch.setenv(k, v)
        for m in ("get", "put", "delete", "post"):
            monkeypatch.setattr(requests, m, getattr(fake, m))
        return TestClient(hub.main.app), fake

    yield build
    media_hidden.clear()
    media_remove.clear()


def confirm_rids(page: str) -> str:
    return page.split('name="rids" value="', 1)[1].split('"', 1)[0]


def remove(client, url, rids=None, scope="request", **kw):
    if rids is None:
        rids = confirm_rids(client.get(url + "?step=confirm&scope=request").text)
    return client.post(url, data={"scope": scope, "rids": rids}, follow_redirects=False, **kw)


def audit(tmp_db: Path) -> list[dict]:
    with sqlite3.connect(tmp_db) as db:
        db.row_factory = sqlite3.Row
        return [dict(r) for r in db.execute("SELECT * FROM media_removals ORDER BY id")]


# ---- who sees it (Q1 A) ----

def test_owner_sees_pick_then_confirm_with_what_will_happen(env):
    client, fake = env()
    with client:
        pick = main_of(client.get(FILM).text)
        conf = main_of(client.get(FILM + "?step=confirm&scope=request").text)
    assert "Midnight Harbour (2025)" in pick and 'value="request" checked' in pick and "Request only" in pick
    assert 'name="step" value="confirm"' in pick and ">Next</button>" in pick
    assert 'method="post" action="/media/remove/movie/1001"' in conf and 'name="rids" value="13"' in conf
    for line in ("Seerr deletes", "Radarr stops searching for it (unmonitored). Its entry stays",
                 "Nothing on disk is deleted.", "Your ratings, diary and poster stay."):
        assert line in conf, line
    assert conf.index(">Cancel</a>") < conf.index("Remove request</button>")       # Cancel first, the default focus
    assert 'href="/media/title/movie/1001" autofocus>Cancel' in conf
    assert fake.total() == 0                                                        # no network on render


def test_confirm_for_a_show_names_the_requester_and_seasons(env):
    client, fake = env()
    with client:
        conf = main_of(client.get(SHOW + "?step=confirm&scope=request").text)
    assert "Night Ferry (2023)" in conf and "(Seasons 1–2)" in conf and "Sonarr stops searching" in conf
    assert fake.total() == 0


def test_on_disk_confirm_says_the_files_stay(env):
    client, _ = env()
    with client:
        conf = main_of(client.get(ON_DISK + "?step=confirm&scope=request").text)
    assert "already on disk: Radarr is left as it is and the files stay" in conf


def test_her_gets_the_ordinary_404_page_and_nothing_is_sent(env, monkeypatch):
    from hub.identity import IDENTITY_HEADER
    monkeypatch.setenv("OWNER_EMAIL_YOU", "you@example.invalid")
    as_her = {IDENTITY_HEADER: "her@example.invalid"}
    client, fake = env()
    with client:
        got = [client.get(FILM, headers=as_her), client.get(FILM + "?step=confirm&scope=request", headers=as_her),
               client.post(FILM, data={"scope": "request", "rids": "13"}, headers=as_her, follow_redirects=False)]
        for r in got:   # the hub's one 404 page (shell.not_found_page), the same bytes every time
            assert r.status_code == 404 and "No page here" in r.text and r.text == got[0].text
        as_you = {IDENTITY_HEADER: "you@example.invalid"}
        assert client.get(FILM, headers=as_you).status_code == 200
    assert fake.total() == 0 and media_remove.recent() == []


def test_friends_on_the_media_front_get_the_404_page_flag_on_or_off(monkeypatch, tmp_path):
    from tests.hub.fake_jellyfin import FRIEND_ID
    from tests.hub.guest_pages import guest_client, sign_in
    for flag in ("on", "off"):
        monkeypatch.setenv("REMOVE_API", flag)
        client, fake = guest_client(monkeypatch, tmp_path / flag, {"jellyseerr": copy.deepcopy(SAMPLE)})
        with client as c:
            sign_in(c, fake, FRIEND_ID)
            base = c.get("/no-such-page", follow_redirects=False)
            for r in (c.get(FILM, follow_redirects=False), c.post(FILM, data={"scope": "request", "rids": "13"},
                                                                  follow_redirects=False)):
                assert r.status_code == 404 and r.text == base.text, (flag, r.status_code)


def test_routes_are_private_in_the_guest_table():
    from hub import guest
    for method in ("GET", "POST"):
        assert not guest.allows(method, FILM) and guest._matches(guest.PRIVATE, method, FILM)
    assert not guest.household_route("GET", FILM) and not guest.household_route("POST", FILM)


def test_can_remove_gate_is_owner_you_on_the_private_front_with_the_flag(monkeypatch):
    from hub import guest
    monkeypatch.setenv("REMOVE_API", "on")
    monkeypatch.setattr(media_remove, "owner_for", lambda request: "you")
    monkeypatch.setattr(guest, "is_media", lambda: False)
    assert media_remove.can_remove(None)
    monkeypatch.setattr(guest, "is_media", lambda: True)
    assert not media_remove.can_remove(None)
    monkeypatch.setattr(guest, "is_media", lambda: False)
    monkeypatch.setattr(media_remove, "owner_for", lambda request: "her")
    assert not media_remove.can_remove(None)
    monkeypatch.setattr(media_remove, "owner_for", lambda request: "you")
    for off in ("", "off", "1", "true"):
        monkeypatch.setenv("REMOVE_API", off)
        assert not media_remove.can_remove(None)


# ---- the flag ----

def test_flag_off_is_the_404_page_and_sends_nothing(env, monkeypatch):
    client, fake = env()
    monkeypatch.setenv("REMOVE_API", "off")
    with client:
        got = [client.get(FILM), client.get(FILM + "?step=confirm&scope=request"),
               client.post(FILM, data={"scope": "request", "rids": "13"}, follow_redirects=False)]
        for r in got:
            assert r.status_code == 404 and "No page here" in r.text and r.text == got[0].text
    assert fake.total() == 0


def test_unknown_kind_or_id_is_the_404_page(env):
    client, fake = env()
    with client:
        for url in ("/media/remove/person/1001", "/media/remove/movie/0", "/media/remove/movie/-4"):
            assert client.get(url).status_code == 404, url
    assert fake.total() == 0


# ---- the page with no request ----

def test_no_request_no_remove_line(env):
    client, _ = env({**SAMPLE, "requests": []})
    with client:
        page = main_of(client.get(FILM).text)
    assert "nothing to remove" in page and "<form" not in page


# ---- the remove ----

def test_removing_a_pending_film_request_deletes_it_and_unmonitors_radarr(env):
    client, fake = env()
    with client:
        r = remove(client, FILM)
        assert r.status_code == 303 and r.headers["location"] == f"{FILM}?done=stopped&app=radarr"
        done = main_of(client.get(r.headers["location"]).text)
    assert ("GET", "/api/v1/request/13") in fake.seerr and ("DELETE", "/api/v1/request/13") in fake.seerr
    assert fake.seerr.index(("GET", "/api/v1/request/13")) < fake.seerr.index(("DELETE", "/api/v1/request/13"))
    puts = [c for c in fake.arr.calls if c[0] == "PUT"]
    assert len(puts) == 1 and puts[0][1] == RADARR and puts[0][2] == "/api/v3/movie/7"
    assert puts[0][4]["monitored"] is False and puts[0][4]["path"] == "/data/media/movies/Midnight Harbour (2025)"
    assert "Request removed · Radarr stopped searching. Its entry stays." in done


def test_removing_a_show_request_unmonitors_the_sonarr_series(env):
    client, fake = env()
    with client:
        r = remove(client, SHOW)
    assert r.headers["location"] == f"{SHOW}?done=stopped&app=sonarr"
    assert ("DELETE", "/api/v1/request/14") in fake.seerr
    assert ("GET", SONARR, "/api/v3/series", {"tvdbId": 82002}, None) in fake.arr.calls
    puts = [c for c in fake.arr.calls if c[0] == "PUT"]
    assert [p[2] for p in puts] == ["/api/v3/series/9"] and puts[0][4]["monitored"] is False
    assert puts[0][4]["seasons"] == fake.arr.series[0]["seasons"]            # the rest of the resource rides along


def test_a_title_on_disk_is_left_alone_in_radarr(env):
    client, fake = env()
    with client:
        r = remove(client, ON_DISK)
    assert r.headers["location"] == f"{ON_DISK}?done=ondisk&app=radarr"
    assert ("DELETE", "/api/v1/request/12") in fake.seerr and fake.arr.calls == []


def test_live_seerr_says_available_so_radarr_is_left_alone(env):
    client, fake = env()
    fake.live[13]["media"]["status"] = 5                                         # it arrived since the snapshot
    with client:
        r = remove(client, FILM)
    assert r.headers["location"] == f"{FILM}?done=ondisk&app=radarr" and fake.arr.calls == []


def test_a_film_with_a_file_in_radarr_is_not_unmonitored(env):
    client, fake = env()
    fake.arr.movies[0]["hasFile"] = True
    with client:
        r = remove(client, FILM)
    assert r.headers["location"] == f"{FILM}?done=ondisk&app=radarr"
    assert [c for c in fake.arr.calls if c[0] != "GET"] == []


def test_already_gone_in_seerr_counts_as_removed_without_a_delete(env):
    client, fake = env()
    fake.live.pop(13)
    with client:
        r = remove(client, FILM)
    assert r.headers["location"] == f"{FILM}?done=stopped&app=radarr"
    assert ("DELETE", "/api/v1/request/13") not in fake.seerr


def test_phase_1_never_deletes_anything_in_the_arr_apps(env):
    client, fake = env()
    with client:
        for url in (FILM, SHOW, ON_DISK):
            remove(client, url)
    assert [c for c in fake.arr.calls if c[0] in ("DELETE", "POST")] == []
    blob = json.dumps(fake.arr.calls) + json.dumps(fake.seerr)
    for word in ("deleteFiles", "/moviefile", "/episodefile", "/queue", "/api/v1/media/"):
        assert word not in blob, word


def test_the_row_leaves_the_title_page_at_once(env):
    from hub import media_requests
    from hub.store import get_snapshots
    client, _ = env()
    with client:
        assert any(r["id"] == 13 for r in media_requests.snapshot_rows(get_snapshots()))
        remove(client, FILM)
        assert not any(r["id"] == 13 for r in media_requests.snapshot_rows(get_snapshots()))
        assert "Nothing left to remove" in main_of(client.get(FILM + "?done=stopped&app=radarr").text)


# ---- refusals: stale confirm, Seerr down, the scope ----

def test_a_stale_confirm_is_refused_and_nothing_is_sent(env):
    client, fake = env()
    with client:
        r = remove(client, FILM, rids="13,99")
        page = main_of(client.get(r.headers["location"]).text)
    assert r.headers["location"].startswith(f"{FILM}?error=changed")
    assert "This changed since you looked. Check again." in page and fake.total() == 0


def test_a_post_without_the_confirm_ids_is_refused(env):
    client, fake = env()
    with client:
        r = client.post(FILM, data={"scope": "request"}, follow_redirects=False)
        r2 = remove(client, FILM, rids="13", scope="whole")
    assert "error=changed" in r.headers["location"] and r2.headers["location"] == f"{FILM}?error=scope"
    assert fake.total() == 0


def test_a_live_request_for_another_title_is_refused(env):
    client, fake = env()
    fake.live[13]["media"]["tmdbId"] = 4242
    with client:
        r = remove(client, FILM)
    assert "error=changed" in r.headers["location"]
    assert fake.seerr == [("GET", "/api/v1/request/13")] and fake.arr.calls == []


def test_seerr_unreachable_removes_nothing_and_never_leaks(env, caplog):
    client, fake = env()
    fake.seerr_raise = requests.ConnectionError
    with caplog.at_level(logging.WARNING), client:
        r = remove(client, FILM)
        page = client.get(r.headers["location"]).text
    assert r.headers["location"] == f"{FILM}?error=unreachable"
    assert "Seerr can&#39;t be reached. Nothing was removed." in page or "Seerr can't be reached" in page
    assert [c for c in fake.seerr if c[0] == "DELETE"] == [] and fake.arr.calls == []
    for text in (page, caplog.text, r.headers["location"]):
        for s in SECRETS:
            assert s not in text


def test_seerr_refusing_the_delete_is_recorded_as_failed(env, tmp_path):
    client, fake = env()
    fake.delete_status = 500
    with client:
        r = remove(client, FILM)
    assert r.headers["location"] == f"{FILM}?error=refused" and fake.arr.calls == [] and fake.discord == []
    row = audit(tmp_path / "media.db")[-1]
    assert row["outcome"] == "failed" and json.loads(row["steps"]) == [
        {"app": "seerr", "step": "delete request 13", "outcome": "HTTP 500"}]


# ---- CSRF and the rate limit ----

def test_cross_site_post_is_refused(env):
    client, fake = env()
    with client:
        r = client.post(FILM, data={"scope": "request", "rids": "13"}, headers=ORIGIN_BAD, follow_redirects=False)
    assert r.status_code == 403 and fake.total() == 0


def test_same_origin_and_htmx_posts_pass(env):
    client, _ = env()
    with client:
        r = remove(client, FILM, headers={"Origin": "http://testserver"})
    assert r.status_code == 303 and "done=" in r.headers["location"]


def test_the_rate_limit_refuses_the_eleventh_remove_in_an_hour(env, monkeypatch):
    client, fake = env()
    monkeypatch.setattr(media_remove, "RATE_MAX", 2)
    with client:
        assert "done=" in remove(client, FILM).headers["location"]
        assert "done=" in remove(client, SHOW).headers["location"]
        r = remove(client, ON_DISK)
        page = main_of(client.get(r.headers["location"]).text)
    assert r.headers["location"].startswith(f"{ON_DISK}?error=rate&at=")
    assert "Too many removes in the last hour. Try again at" in page
    assert ("DELETE", "/api/v1/request/12") not in fake.seerr


def test_one_remove_at_a_time(env):
    client, fake = env()
    assert media_remove._lock.acquire(blocking=False)
    try:
        with client:
            r = remove(client, FILM)
    finally:
        media_remove._lock.release()
    assert r.headers["location"] == f"{FILM}?error=busy" and fake.seerr == []


def test_get_with_a_post_body_never_removes(env):
    client, fake = env()
    with client:
        client.get(FILM + "?scope=request&rids=13")
    assert fake.total() == 0


# ---- the audit log and Discord (Q9 A) ----

def test_one_audit_row_per_remove_with_no_path_url_or_key(env, tmp_path):
    client, _ = env()
    with client:
        remove(client, FILM)
        remove(client, SHOW)
    rows = audit(tmp_path / "media.db")
    assert [(r["kind"], r["tmdb_id"], r["scope"], r["outcome"], r["owner"], r["front"]) for r in rows] == [
        ("movie", 1001, "request", "done", "you", "private"), ("tv", 2002, "request", "done", "you", "private")]
    assert rows[0]["title"] == "Midnight Harbour (2025)" and json.loads(rows[0]["request_ids"]) == [13]
    assert rows[1]["tvdb_id"] == 82002 and rows[0]["files"] == 0 and rows[0]["bytes"] == 0
    assert json.loads(rows[0]["steps"]) == [{"app": "seerr", "step": "delete request 13", "outcome": "ok"},
                                            {"app": "radarr", "step": "unmonitor", "outcome": "ok"}]
    assert rows[0]["at"].endswith("+00:00")
    blob = json.dumps(rows)
    for s in (*SECRETS, "/data/", "http"):
        assert s not in blob, s


def test_refused_posts_write_no_audit_row(env, tmp_path):
    client, _ = env()
    with client:
        remove(client, FILM, rids="99")
        client.post(FILM, data={"scope": "request", "rids": "13"}, headers=ORIGIN_BAD)
    assert not (tmp_path / "media.db").exists() or audit(tmp_path / "media.db") == []


def test_one_discord_line_per_remove_with_no_secrets(env):
    client, fake = env()
    with client:
        remove(client, FILM)
        remove(client, ON_DISK)
    assert fake.discord == [
        "Joey Media: removed the request for Midnight Harbour (2025) · Radarr stopped searching · nothing on disk deleted",
        "Joey Media: removed the request for Desert Crossing (2019) · already on disk, Radarr left as it is · nothing on disk deleted"]
    for line in fake.discord:
        for s in (*SECRETS, "http", "Sample Person", "@"):
            assert s not in line, s


def test_no_webhook_no_discord_call(env, monkeypatch):
    client, fake = env()
    monkeypatch.delenv("SERVER_DISCORD_WEBHOOK")
    with client:
        assert "done=" in remove(client, FILM).headers["location"]
    assert fake.discord == []


def test_discord_line_words():
    assert media_remove.discord_line("Night Ferry (2023)", "tv", "arrfail", "done") == (
        "Joey Media: removed the request for Night Ferry (2023) · couldn't stop the Sonarr search · nothing on disk deleted")
    assert media_remove.discord_line("X", "movie", "removed", "partial").startswith("Joey Media: remove partly failed for X")


def test_the_audit_table_arrives_through_the_media_store_steps(tmp_path, monkeypatch):
    from hub import media_store
    monkeypatch.setenv("MEDIA_DB_PATH", str(tmp_path / "m.db"))
    media_store.forget()
    with media_store.connect() as db:
        cols = [r[1] for r in db.execute("PRAGMA table_info(media_removals)")]
    assert cols == ["id", "at", "owner", "front", "kind", "tmdb_id", "tvdb_id", "title", "scope", "picked", "files",
                    "bytes", "request_ids", "steps", "outcome"]


def test_an_existing_v5_db_with_data_upgrades_to_v6_and_keeps_every_row(tmp_path, monkeypatch):
    """Review fix (2026-10-28): a live v5 media.db - ratings, a diary entry, a follow - gains media_removals at v6
    and loses nothing."""
    from contextlib import closing
    from hub import media_db, media_store
    db = tmp_path / "v5.db"
    monkeypatch.setenv("MEDIA_DB_PATH", str(db))
    media_store.reset()
    media_store.forget()
    media_db.set_rating("tmdb:603", 9, "movie", "Harbour Lights", year=2019)
    media_db.add_manual_watch(item_key="tmdb:603", kind="movie", title="Harbour Lights", year=2019, poster=None,
                              watched_on="2026-10-12", place=None, note=None, owner="you")
    with closing(sqlite3.connect(db)) as conn:
        conn.execute("DROP TABLE media_removals")
        conn.execute("PRAGMA user_version = 5")                          # a live v5 file, as deployed today
        conn.commit()
        tables = sorted(r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'"))
        before = {t: conn.execute(f'SELECT * FROM "{t}" ORDER BY rowid').fetchall()
                  for t in tables if t != "sqlite_sequence"}
    assert "media_removals" not in before and before["rating"] and before["diary"]
    media_store.reset()
    media_store.forget()
    with closing(media_store.connect()) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == media_store.SCHEMA_VERSION == 7
        assert conn.execute("SELECT COUNT(*) FROM media_removals").fetchone()[0] == 0
        for t, rows in before.items():
            assert [tuple(r) for r in conn.execute(f'SELECT * FROM "{t}" ORDER BY rowid')] == rows, t
    media_store.forget()
    with closing(media_store.connect()) as conn:                        # a second open: idempotent, still the latest (v7 since JY-264)
        assert conn.execute("PRAGMA user_version").fetchone()[0] == media_store.SCHEMA_VERSION == 7
    media_store.reset()


@pytest.mark.parametrize("title", ["@everyone", "@here now", "<@123456789>", "<@&987654321>", "<@!42> Film"])
def test_discord_line_neutralises_mentions(title):
    line = media_remove.discord_line(title, "movie", "stopped", "done")
    for bad in ("@everyone", "@here", "<@1", "<@&", "<@!"):
        assert bad not in line
    assert "@​" in line


def test_the_discord_post_allows_no_mentions(env, monkeypatch):
    client, fake = env()
    sent = []
    real = fake.post

    def post(url, json=None, **kw):
        if url == HOOK:
            sent.append(json)
        return real(url, json=json, **kw)
    monkeypatch.setattr(requests, "post", post)
    with client:
        remove(client, FILM)
    assert sent and sent[0]["allowed_mentions"] == {"parse": []}
