"""F3 (2026-10-12): "Search all monitored" on Activity › Requests and › Downloads. Two buttons — Search missing /
Search upgrades — each a two-step confirm (htmx GET /media/arr/sweep?step=confirm, then a same-origin POST) that sends
Radarr + Sonarr whole-library commands and 303s back with a flash word. Radarr / Sonarr are faked at requests.post;
no network."""
import html as htmllib
import importlib
import logging

import pytest
import requests
from fastapi.testclient import TestClient

from hub import media_arr_search as mas
from tests.hub.conftest import main_of
from tests.hub.helpers import FakeResponse as R, make_area, make_tile, write_envelope, write_registry

RADARR = "http://radarr.secret-host.invalid:7878"
RKEY = "r-SECRET-radarr-key"
SONARR = "http://sonarr.secret-host.invalid:8989"
TKEY = "s-SECRET-sonarr-key"
HX = {"HX-Request": "true"}
BAD_ORIGIN = {"Origin": "https://evil.invalid"}
CMD = {RADARR: f"{RADARR}/api/v3/command", SONARR: f"{SONARR}/api/v3/command"}


class Arr:
    def __init__(self):
        self.posts, self.down = [], set()      # (url, json, headers, timeout); bases that fail
        self.status = 201

    def post(self, url, json=None, headers=None, timeout=None, **kw):
        self.posts.append((url, json, headers, timeout))
        base = RADARR if url.startswith(RADARR) else SONARR
        if base in self.down:
            raise requests.ConnectionError(f"Max retries exceeded with url: {url}?apikey={RKEY}{TKEY}")
        return R({"id": 1, "name": (json or {}).get("name")}, self.status)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    area = make_area("alpha", "req-t", snapshot="jellyseerr", stale_after_minutes=180, detail="/media/requests")
    area["tiles"].append(make_tile("dl-t", snapshot="qbittorrent", stale_after_minutes=10, detail="/media/downloads"))
    monkeypatch.setenv("AREAS_PATH", str(write_registry(tmp_path, area)))
    monkeypatch.setenv("SNAPSHOT_DIR", str(tmp_path / "snaps"))
    monkeypatch.setenv("MEDIA_DB_PATH", str(tmp_path / "media.db"))
    monkeypatch.setattr(mas, "_started", {})

    def build(radarr=True, sonarr=True):
        for name, on, url, key in (("RADARR", radarr, RADARR, RKEY), ("SONARR", sonarr, SONARR, TKEY)):
            if on:
                monkeypatch.setenv(f"{name}_URL", url)
                monkeypatch.setenv(f"{name}_API_KEY", key)
            else:
                monkeypatch.delenv(f"{name}_URL", raising=False)
                monkeypatch.delenv(f"{name}_API_KEY", raising=False)
        write_envelope(tmp_path / "snaps", "jellyseerr", age_minutes=1, data={"summary": "x", "requests": []})
        write_envelope(tmp_path / "snaps", "qbittorrent", age_minutes=1, data={"summary": "x", "active": []})
        import hub.main
        importlib.reload(hub.main)
        arr = Arr()
        monkeypatch.setattr(requests, "post", arr.post)
        return TestClient(hub.main.app), arr
    return build


def sweep(client, kind="missing", back="/media/downloads", **headers):
    return client.post("/media/arr/sweep", data={"kind": kind, "back": back}, headers=headers, follow_redirects=False)


# ---- the row on both tabs ----

@pytest.mark.parametrize("path", ["/media/requests", "/media/downloads"])
def test_both_tabs_show_the_row(env, path):
    client, arr = env()
    with client:
        body = htmllib.unescape(main_of(client.get(path).text))
    assert 'id="arr-sweep"' in body
    for kind, word in (("missing", "Search missing"), ("upgrades", "Search upgrades")):
        assert f'hx-get="/media/arr/sweep?step=confirm&kind={kind}&back={path}"' in body
        assert f'href="{path}?sweep_ask={kind}"' in body                      # works without JS too
        assert word in body
    assert body.count("Radarr · Sonarr") == 2
    assert not arr.posts                                                     # the page itself never calls the apps
    assert RKEY not in body and "secret-host" not in body


def test_unconfigured_shows_not_connected_and_no_buttons(env):
    client, _ = env(radarr=False, sonarr=False)
    with client:
        body = main_of(client.get("/media/requests").text)
    row = body.split('id="arr-sweep"', 1)[1].split("</div>", 1)[0]
    assert "Not connected" in row and "Search missing" not in row and "/media/arr/sweep" not in body


def test_one_app_configured_names_only_that_app(env):
    client, _ = env(radarr=False)
    with client:
        body = main_of(client.get("/media/downloads").text)
    assert body.count(">Search missing<span class=\"metaline\">Sonarr</span>") == 1
    assert "Radarr" not in body.split('id="arr-sweep"', 1)[1].split("</div>\n</div>", 1)[0]


# ---- the confirm step ----

def test_confirm_step_renders_the_card_in_place(env):
    client, arr = env()
    with client:
        r = client.get("/media/arr/sweep?step=confirm&kind=upgrades&back=%2Fmedia%2Fdownloads", headers=HX)
    assert r.status_code == 200
    html = r.text
    assert 'id="arr-sweep"' in html
    assert 'action="/media/arr/sweep"' in html and 'name="kind" value="upgrades"' in html
    assert 'name="back" value="/media/downloads"' in html
    assert "below its quality cutoff" in html and ">Search upgrades</button>" in html
    assert "Started" not in html                                            # never run: no throttle note
    assert "confirm(" not in html and not arr.posts


def test_cancel_returns_the_buttons(env):
    client, _ = env()
    with client:
        html = client.get("/media/arr/sweep?step=idle&back=%2Fmedia%2Frequests", headers=HX).text
    assert "<form" not in html and "Search missing" in html and "Search upgrades" in html


def test_confirm_without_htmx_goes_back_to_the_page_which_draws_the_card(env):
    client, _ = env()
    with client:
        r = client.get("/media/arr/sweep?step=confirm&kind=missing&back=%2Fmedia%2Frequests", follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/media/requests?sweep_ask=missing"
        body = main_of(client.get(r.headers["location"]).text)
    assert 'name="kind" value="missing"' in body and "has no file yet" in body


@pytest.mark.parametrize("back", ["https://evil.invalid/x", "//evil.invalid", "/server"])
def test_back_is_a_local_media_page_only(env, back):
    client, _ = env()
    with client:
        html = client.get("/media/arr/sweep", params={"step": "confirm", "kind": "missing", "back": back}, headers=HX).text
    assert 'name="back" value="/media/requests"' in html


# ---- running it ----

@pytest.mark.parametrize("kind, radarr, sonarr", [
    ("missing", "MissingMoviesSearch", "MissingEpisodeSearch"),
    ("upgrades", "CutoffUnmetMoviesSearch", "CutoffUnmetEpisodeSearch"),
])
def test_post_sends_exactly_the_two_commands(env, kind, radarr, sonarr):
    client, arr = env()
    with client:
        r = sweep(client, kind)
        assert r.status_code == 303
        assert r.headers["location"] == "/media/downloads?sweep=started&ran=radarr%2Csonarr"
        page = main_of(client.get(r.headers["location"]).text)
    sent = sorted((u, j) for u, j, _, _ in arr.posts)
    assert sent == [(CMD[RADARR], {"name": radarr}), (CMD[SONARR], {"name": sonarr})]
    assert {(u, h["X-Api-Key"]) for u, _, h, _ in arr.posts} == {(CMD[RADARR], RKEY), (CMD[SONARR], TKEY)}
    assert all(t == 10 for *_, t in arr.posts)                              # each its own 10 s timeout
    assert "Search started · Radarr · Sonarr" in page


def test_one_app_down_still_runs_the_other(env, caplog):
    client, arr = env()
    arr.down.add(RADARR)
    with client, caplog.at_level(logging.WARNING):
        r = sweep(client, "missing", back="/media/requests")
        assert r.headers["location"] == "/media/requests?sweep=partial&ran=sonarr"
        page = main_of(client.get(r.headers["location"]).text)
    assert len(arr.posts) == 2                                              # Sonarr was still asked
    assert "Search started · Sonarr only" in page
    assert "radarr sweep failed: ConnectionError" in caplog.text
    assert "secret-host" not in caplog.text and RKEY not in caplog.text and TKEY not in caplog.text


def test_refused_status_counts_as_failed(env, caplog):
    client, arr = env()
    arr.status = 503
    with client, caplog.at_level(logging.WARNING):
        r = sweep(client)
        assert r.headers["location"] == "/media/downloads?sweep=failed"
        page = htmllib.unescape(main_of(client.get(r.headers["location"]).text))
    assert "Couldn't start the search" in page
    assert "sweep failed: HTTP 503" in caplog.text


def test_both_down_is_the_failed_word_and_starts_no_throttle(env):
    client, arr = env()
    arr.down.update({RADARR, SONARR})
    with client:
        r = sweep(client)
        assert r.headers["location"] == "/media/downloads?sweep=failed"
        html = client.get("/media/arr/sweep?step=confirm&kind=missing", headers=HX).text
    assert "Started" not in html


def test_unconfigured_post_sends_nothing(env):
    client, arr = env(radarr=False, sonarr=False)
    with client:
        r = sweep(client)
    assert r.headers["location"] == "/media/downloads?sweep=failed" and not arr.posts


def test_only_the_configured_app_is_called_and_that_is_a_full_start(env):
    client, arr = env(sonarr=False)
    with client:
        r = sweep(client, "upgrades")
    assert r.headers["location"] == "/media/downloads?sweep=started&ran=radarr"
    assert [(u, j) for u, j, _, _ in arr.posts] == [(CMD[RADARR], {"name": "CutoffUnmetMoviesSearch"})]


def test_same_origin_is_enforced(env):
    client, arr = env()
    with client:
        r = sweep(client, **BAD_ORIGIN)
    assert r.status_code == 403 and not arr.posts


def test_unknown_kind_is_refused(env):
    client, arr = env()
    with client:
        r = sweep(client, "everything")
    assert r.status_code == 422 and not arr.posts


def test_post_back_falls_back_to_requests(env):
    client, _ = env()
    with client:
        r = sweep(client, back="https://evil.invalid/media/x")
    assert r.headers["location"].startswith("/media/requests?sweep=started")


# ---- throttle ----

def test_a_repeat_within_ten_minutes_says_so_and_still_runs(env, monkeypatch):
    client, arr = env()
    now = [1000.0]
    monkeypatch.setattr(mas, "_clock", lambda: now[0])
    with client:
        sweep(client, "missing")
        now[0] += 4 * 60 + 30
        html = client.get("/media/arr/sweep?step=confirm&kind=missing", headers=HX).text
        assert "Started 4m ago · run again?" in html   # E3 (U27): the guide's "2h 47m" lengths
        other = client.get("/media/arr/sweep?step=confirm&kind=upgrades", headers=HX).text
        assert "Started" not in other                                       # per kind
        assert sweep(client, "missing").headers["location"].startswith("/media/downloads?sweep=started")
        assert len(arr.posts) == 4                                          # allowed again
        now[0] += 10 * 60
        assert "Started" not in client.get("/media/arr/sweep?step=confirm&kind=missing", headers=HX).text


def test_flash_words():
    assert mas.sweep_flash({"sweep": "started", "ran": "radarr,sonarr"}) == ("Search started · Radarr · Sonarr", None)
    assert mas.sweep_flash({"sweep": "partial", "ran": "radarr"}) == ("Search started · Radarr only", None)
    assert mas.sweep_flash({"sweep": "failed"}) == (None, "Couldn't start the search")
    assert mas.sweep_flash({"sweep": "started", "ran": "<script>"}) == (None, None)
    assert mas.sweep_flash({}) == (None, None)


def test_a_stuck_app_does_not_block_the_hub(env, monkeypatch):
    """Wave-2 rule (M-40): the commands run in worker threads; /healthz answers while both are still waiting."""
    import threading
    import time
    client, _ = env()
    started, release = threading.Event(), threading.Event()

    def stuck(app, kind):
        started.set()
        release.wait(5)
        return True
    monkeypatch.setattr(mas, "_sweep_one", stuck)
    out = {}
    with client:
        worker = threading.Thread(target=lambda: out.setdefault("r", sweep(client)))
        worker.start()
        try:
            assert started.wait(5)
            t0 = time.monotonic()
            assert client.get("/healthz").status_code == 200
            elapsed = time.monotonic() - t0
        finally:
            release.set()
            worker.join(10)
    assert elapsed < 1.5 and out["r"].status_code == 303
