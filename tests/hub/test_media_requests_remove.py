"""Remove a request (2026-10-08): the Requests page's Remove button. Jellyseerr DELETE /api/v1/request/{id}, then —
only when nothing is on disk — Radarr / Sonarr `monitored: false`. Never a file delete, never an *arr entry delete.
All HTTP is faked at `requests.get / put / delete / post`; no network."""
import copy
import importlib
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import requests
import yaml
from fastapi.testclient import TestClient

from hub import media_hidden
from tests.hub.helpers import make_area, FakeResponse as R, write_envelope
from tests.hub.helpers import not_quality, not_season_state  # WP-T1, WP-R1
from tests.hub.conftest import main_of  # noqa: F401  (shared helper; other test modules import it from here)

SAMPLE = json.loads((Path(__file__).resolve().parents[2] / "config" / "sample_snapshots" / "jellyseerr.json")
                    .read_text(encoding="utf-8"))["data"]
SEERR = "http://seerr.secret-host.invalid:5055"
SKEY = "k-SECRET-seerr"
RADARR = "http://radarr.secret-host.invalid:7878"
RKEY = "r-SECRET-radarr"
SONARR = "http://sonarr.secret-host.invalid:8989"
TKEY = "s-SECRET-sonarr"
ORIGIN_BAD = {"Origin": "https://evil.invalid"}


class Fake:
    """Jellyseerr + Radarr + Sonarr. `movies` / `series` are the apps' libraries."""

    def __init__(self):
        self.calls = []                     # (method, url, params, json)
        self.delete_status = 204
        self.seerr_raise = None
        self.arr_raise = None
        self.put_status = 202
        self.movies = [{"id": 7, "tmdbId": 1001, "title": "Midnight Harbour", "monitored": True, "hasFile": False,
                        "path": "/movies/Midnight Harbour (2025)", "qualityProfileId": 1}]
        self.series = [{"id": 9, "tvdbId": 82002, "tmdbId": 2002, "title": "Night Ferry", "monitored": True,
                        "statistics": {"episodeFileCount": 0, "sizeOnDisk": 0}}]

    def _hdr(self, url, headers):
        want = {SEERR: SKEY, RADARR: RKEY, SONARR: TKEY}
        base = next(b for b in want if url.startswith(b))
        assert headers == {"X-Api-Key": want[base]}
        return base

    def get(self, url, params=None, headers=None, timeout=None, **kw):
        self.calls.append(("GET", url, params, None))
        base = self._hdr(url, headers)
        if self.arr_raise and base != SEERR:
            raise self.arr_raise(f"Max retries exceeded with url: {url}?apikey={RKEY}")
        if url == f"{RADARR}/api/v3/movie":
            return R([m for m in self.movies if m["tmdbId"] == (params or {}).get("tmdbId")])
        if url == f"{SONARR}/api/v3/series":
            if params and "tvdbId" in params:
                return R([s for s in self.series if s["tvdbId"] == params["tvdbId"]])
            return R(self.series)
        return R({}, 404)

    def put(self, url, json=None, headers=None, timeout=None, **kw):
        self.calls.append(("PUT", url, None, json))
        self._hdr(url, headers)
        return R(json, self.put_status)

    def delete(self, url, headers=None, timeout=None, **kw):
        self.calls.append(("DELETE", url, None, None))
        self._hdr(url, headers)
        if self.seerr_raise:
            raise self.seerr_raise(f"Max retries exceeded with url: {url} key={SKEY}")
        return R(None, self.delete_status)

    def post(self, url, **kw):
        self.calls.append(("POST", url, None, kw.get("json")))
        return R({}, 201)

    def of(self, method):
        return [c for c in self.calls if c[0] == method]


@pytest.fixture()
def env(tmp_path, monkeypatch):
    area = make_area("alpha", "req-t", snapshot="jellyseerr", stale_after_minutes=180, detail="/media/requests")
    path = tmp_path / "areas.yaml"
    path.write_text(yaml.safe_dump({"areas": [area]}), encoding="utf-8")
    monkeypatch.setenv("AREAS_PATH", str(path))
    for k, v in (("JELLYSEERR_URL", SEERR), ("JELLYSEERR_API_KEY", SKEY), ("RADARR_URL", RADARR),
                 ("RADARR_API_KEY", RKEY), ("SONARR_URL", SONARR), ("SONARR_API_KEY", TKEY)):
        monkeypatch.setenv(k, v)
    snaps = tmp_path / "snaps"
    monkeypatch.setenv("SNAPSHOT_DIR", str(snaps))
    media_hidden.clear()

    def build(data=None):
        write_envelope(snaps, "jellyseerr", age_minutes=1, data=copy.deepcopy(data or SAMPLE))
        import hub.main
        importlib.reload(hub.main)
        fake = Fake()
        for m in ("get", "put", "delete", "post"):
            monkeypatch.setattr(requests, m, getattr(fake, m))
        return TestClient(hub.main.app), fake, snaps

    yield build
    media_hidden.clear()


def remove(client, rid):
    return client.post(f"/media/requests/{rid}/remove", follow_redirects=False)


# ---- the page ----

def test_each_row_has_a_remove_button_outside_the_row_link_with_an_inline_confirm(env):
    client, _, _ = env()
    with client:
        body = main_of(client.get("/media/requests").text)
    assert body.count('<summary class="btn btn-secondary btn-sm">Remove</summary>') == 4
    assert 'action="/media/requests/13/remove"' in body and "Remove the request for Midnight Harbour?" in body
    assert "confirm(" not in body                                     # guide 6: never a browser dialog
    # the whole row is still the link; the Remove form is never inside it
    for row in body.split('<div class="row has-form reqrow"')[1:]:
        link = row.split('<a class="rowlink"', 1)[1].split("</a>", 1)[0]
        assert "<form" not in link and "<details" not in link and "Remove" not in link
    assert '<a class="rowlink" href="http://nas.local:5055/movie/1001" target="_blank" rel="noopener">' in body
    assert "Radarr stops searching. Nothing is deleted." in body       # pending film
    assert "Already on disk — the files stay." in body                 # the Available one


# ---- removing ----

def test_remove_film_deletes_request_unmonitors_radarr_and_drops_the_row(env):
    client, fake, _ = env()
    with client:
        r = remove(client, 13)
        assert r.status_code == 303 and r.headers["location"] == "/media/requests?done=stopped&app=radarr"
        page = main_of(client.get(r.headers["location"]).text)
    assert fake.of("DELETE") == [("DELETE", f"{SEERR}/api/v1/request/13", None, None)]
    puts = fake.of("PUT")
    assert len(puts) == 1 and puts[0][1] == f"{RADARR}/api/v3/movie/7"
    assert puts[0][3]["monitored"] is False and puts[0][3]["path"] == "/movies/Midnight Harbour (2025)"  # own resource
    assert "Removed · Radarr stopped searching" in page
    assert "Midnight Harbour" not in page and "Night Ferry" in page    # gone at once, the rest stay
    assert "2 approved · 1 available · 1 declined" in page and "0 pending" not in page  # the count drops with it (E3: zeros left off)


def test_remove_tv_unmonitors_sonarr_series_by_tvdb(env):
    client, fake, _ = env()
    with client:
        r = remove(client, 14)
    assert r.headers["location"] == "/media/requests?done=stopped&app=sonarr"
    assert ("GET", f"{SONARR}/api/v3/series", {"tvdbId": 82002}, None) in fake.calls
    puts = fake.of("PUT")
    assert [p[1] for p in puts] == [f"{SONARR}/api/v3/series/9"] and puts[0][3]["monitored"] is False


def test_tv_without_tvdb_falls_back_to_tmdb_match(env):
    data = copy.deepcopy(SAMPLE)
    for row in data["requests"]:
        row["tvdb_id"] = None
    client, fake, _ = env(data)
    with client:
        r = remove(client, 14)
    assert r.headers["location"] == "/media/requests?done=stopped&app=sonarr"
    assert ("GET", f"{SONARR}/api/v3/series", None, None) in fake.calls
    assert [p[1] for p in fake.of("PUT")] == [f"{SONARR}/api/v3/series/9"]


def test_film_with_a_file_on_disk_is_left_alone(env):
    client, fake, _ = env()
    fake.movies[0]["hasFile"] = True
    with client:
        r = remove(client, 13)
        page = main_of(client.get(r.headers["location"]).text)
    assert r.headers["location"] == "/media/requests?done=ondisk&app=radarr"
    assert fake.of("DELETE") == [("DELETE", f"{SEERR}/api/v1/request/13", None, None)]
    assert fake.of("PUT") == []
    assert "Removed · already on disk, Radarr left as is" in page


def test_series_with_episode_files_is_left_alone(env):
    client, fake, _ = env()
    fake.series[0]["statistics"] = {"episodeFileCount": 3, "sizeOnDisk": 12345}
    with client:
        r = remove(client, 14)
    assert r.headers["location"] == "/media/requests?done=ondisk&app=sonarr" and fake.of("PUT") == []


def test_available_request_never_touches_the_arr_apps(env):
    client, fake, _ = env()
    with client:
        r = remove(client, 12)                                         # Desert Crossing: Available
    assert r.headers["location"] == "/media/requests?done=ondisk&app=radarr"
    assert [c for c in fake.calls if not c[1].startswith(SEERR)] == []


def test_title_not_in_radarr_is_just_removed(env):
    client, fake, _ = env()
    fake.movies = []
    with client:
        r = remove(client, 13)
        page = main_of(client.get(r.headers["location"]).text)
    assert r.headers["location"] == "/media/requests?done=removed" and fake.of("PUT") == []
    assert '<p class="metaline st-good" role="status">Removed</p>' in page


def test_already_unmonitored_needs_no_put(env):
    client, fake, _ = env()
    fake.movies[0]["monitored"] = False
    with client:
        r = remove(client, 13)
    assert r.headers["location"] == "/media/requests?done=stopped&app=radarr" and fake.of("PUT") == []


def test_never_a_file_delete_or_arr_entry_delete(env):
    client, fake, _ = env()
    with client:
        for rid in (13, 14, 12, 11):
            remove(client, rid)
    deletes = fake.of("DELETE")
    assert deletes and all(d[1].startswith(f"{SEERR}/api/v1/request/") for d in deletes)
    blob = json.dumps(fake.calls)
    assert "deleteFiles" not in blob and "/moviefile" not in blob and "/episodefile" not in blob
    assert "/api/v1/media/" not in blob                                # no Jellyseerr media/file removal either


def test_jellyseerr_404_counts_as_removed(env):
    client, fake, _ = env()
    fake.delete_status = 404
    with client:
        r = remove(client, 13)
    assert r.headers["location"] == "/media/requests?done=stopped&app=radarr"


def test_unknown_request_is_refused_without_any_call(env):
    client, fake, _ = env()
    with client:
        r = remove(client, 999)
        page = main_of(client.get(r.headers["location"]).text)
    assert r.headers["location"] == "/media/requests?error=missing" and not_season_state(not_quality(fake.calls)) == []   # WP-T1  # WP-R1: + the quality task
    assert "That request is no longer listed" in page


# ---- guards and errors ----

def test_remove_requires_same_origin(env):
    client, fake, _ = env()
    with client:
        r = client.post("/media/requests/13/remove", headers=ORIGIN_BAD, follow_redirects=False)
        page = main_of(client.get("/media/requests").text)
    assert r.status_code == 403 and not_season_state(not_quality(fake.calls)) == []   # WP-T1: the page's background list read only  # WP-R1: + the quality task
    assert "Midnight Harbour" in page


def test_remove_get_is_not_a_route(env):
    client, fake, _ = env()
    with client:
        assert client.get("/media/requests/13/remove").status_code in (404, 405)
    assert fake.calls == []


def test_jellyseerr_unreachable_is_a_plain_word_and_never_leaks(env, caplog):
    client, fake, _ = env()
    fake.seerr_raise = requests.ConnectionError
    with caplog.at_level(logging.WARNING), client:
        r = remove(client, 13)
        page = client.get(r.headers["location"]).text
    assert r.headers["location"] == "/media/requests?error=unreachable"
    body = main_of(page)
    assert '<p class="metaline st-warn" role="status">Couldn\'t reach Seerr</p>' in body.replace("&#39;", "'")
    assert "Midnight Harbour" in body and fake.of("PUT") == []         # nothing hidden, nothing unmonitored
    for text in (page, caplog.text, r.headers["location"]):
        assert "secret-host" not in text and "SECRET" not in text


def test_jellyseerr_refusal_shows_status_only(env):
    client, fake, _ = env()
    fake.delete_status = 500
    with client:
        r = remove(client, 13)
        page = main_of(client.get(r.headers["location"]).text)
    assert r.headers["location"] == "/media/requests?error=refused&code=500"
    assert "Seerr refused (HTTP 500)" in page and "Midnight Harbour" in page


def test_arr_failure_still_removes_and_is_sanitized(env, caplog):
    client, fake, _ = env()
    fake.arr_raise = requests.ConnectionError
    with caplog.at_level(logging.WARNING), client:
        r = remove(client, 13)
        page = client.get(r.headers["location"]).text
    assert r.headers["location"] == "/media/requests?done=arrfail&app=radarr"
    assert "Removed · couldn&#39;t stop the Radarr search" in page or "Removed · couldn't stop the Radarr search" in page
    assert "radarr unmonitor failed: ConnectionError" in caplog.text
    for text in (page, caplog.text):
        assert "secret-host" not in text and "SECRET" not in text


def test_arr_put_refused_is_status_only(env, caplog):
    client, fake, _ = env()
    fake.put_status = 400
    with caplog.at_level(logging.WARNING), client:
        r = remove(client, 13)
    assert r.headers["location"] == "/media/requests?done=arrfail&app=radarr"
    assert "radarr unmonitor failed: HTTP 400" in caplog.text


def test_arr_not_configured_says_so(env, monkeypatch):
    client, fake, _ = env()
    monkeypatch.delenv("RADARR_URL")
    with client:
        r = remove(client, 13)
    assert r.headers["location"] == "/media/requests?done=arrunset&app=radarr"
    assert [c[0] for c in fake.calls] == ["DELETE"]


def test_flash_params_include_app():
    from hub import main
    assert "done" in main.FLASH_PARAMS and "app" in main.FLASH_PARAMS


# ---- hidden until the next sweep ----

def test_a_newer_snapshot_is_the_truth_again(env):
    client, fake, snaps = env()
    with client:
        remove(client, 13)
        assert "Midnight Harbour" not in main_of(client.get("/media/requests").text)
        # the next sweep (taken well after the removal) still lists it: show it again rather than hide forever
        ts = (datetime.now(timezone.utc) + timedelta(seconds=media_hidden.GRACE_S + 5)).isoformat()
        env_json = json.loads((snaps / "jellyseerr.json").read_text(encoding="utf-8"))
        env_json["updated_at"] = env_json["fetched_at"] = ts
        (snaps / "jellyseerr.json").write_text(json.dumps(env_json), encoding="utf-8")
        assert "Midnight Harbour" in main_of(client.get("/media/requests").text)


def test_hidden_unit_rules():
    media_hidden.clear()
    now = datetime.now(timezone.utc)
    old = (now - timedelta(minutes=5)).isoformat()
    media_hidden.hide("g", 1)
    assert media_hidden.is_hidden("g", 1, old) and media_hidden.is_hidden("g", "1", None)
    assert not media_hidden.is_hidden("g", 2, old) and not media_hidden.is_hidden("other", 1, old)
    assert media_hidden.visible("g", [{"id": 1}, {"id": 2}], lambda r: r["id"], old) == [{"id": 2}]
    fresh = (now + timedelta(seconds=media_hidden.GRACE_S + 1)).isoformat()
    assert not media_hidden.is_hidden("g", 1, fresh) and not media_hidden.is_hidden("g", 1, old)  # forgotten
    media_hidden.clear()


def test_removed_request_leaves_the_film_page_requested_line(env):
    """The film page's "Requested …" and the watchlist's status read the same visible rows."""
    from hub import media_requests
    client, _, snaps = env()
    with client:
        from hub.store import get_snapshots
        assert any(r["id"] == 13 for r in media_requests.snapshot_rows(get_snapshots()))
        remove(client, 13)
        assert not any(r["id"] == 13 for r in media_requests.snapshot_rows(get_snapshots()))
