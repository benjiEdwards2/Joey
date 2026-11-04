"""F3 (2026-10-12): "Search all monitored" on Activity › Requests and › Downloads. Two buttons — Search missing /
Search upgrades — each a two-step confirm (htmx GET /media/arr/sweep?step=confirm, then a same-origin POST) that 303s
back with a flash word. JY-302 (2026-11-03): the POST reads each app's wanted list and sends MoviesSearch / EpisodeSearch
with ids of titles ON JELLYFIN only, never a library-wide command. Radarr / Sonarr are faked at requests.get / .post;
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


# JY-302 fixture: on Jellyfin = film tmdb 100, show tmdb 9000 / tvdb 7000; show tvdb 8100 is Sonarr's empty folder
# (0 episodes, so NOT on the server). Off-server monitored titles: film tmdb 200 (Radarr id 12), show tvdb 8000.
JELLYFIN = {"summary": "x", "movies": [{"item_key": "tmdb:100", "title": "On Server", "jf_id": "a"}],
            "shows": [{"item_key": "tmdb:9000", "tvdb": "7000", "episodes": 5, "title": "Show On", "jf_id": "b"},
                      {"item_key": "tvdb:8100", "episodes": 0, "title": "Empty Folder", "jf_id": "c"}]}
WANTED = {
    RADARR: {"missing": [{"id": 11, "tmdbId": 100}, {"id": 12, "tmdbId": 200}],
             "cutoff": [{"id": 11, "tmdbId": 100}, {"id": 12, "tmdbId": 200}]},
    SONARR: {"missing": [{"id": 501, "seriesId": 1, "series": {"id": 1, "tvdbId": 7000, "tmdbId": 9000}},
                         {"id": 502, "seriesId": 1, "series": {"id": 1, "tvdbId": 7000}},
                         {"id": 503, "seriesId": 2, "series": {"id": 2, "tvdbId": 8000, "tmdbId": 8001}},
                         {"id": 504, "seriesId": 3, "series": {"id": 3, "tvdbId": 8100}}],
             "cutoff": [{"id": 502, "seriesId": 1, "series": {"id": 1, "tvdbId": 7000}},
                        {"id": 503, "seriesId": 2, "series": {"id": 2, "tvdbId": 8000}}]}}
OFF_SERVER = {"movieIds": {12}, "episodeIds": {503, 504}}


class Arr:
    def __init__(self):
        self.posts, self.down = [], set()      # (url, json, headers, timeout); bases that fail
        self.gets = []                         # (url, params)
        self.status = 201
        self.wanted = {b: {k: list(v) for k, v in w.items()} for b, w in WANTED.items()}

    def get(self, url, params=None, headers=None, timeout=None, **kw):
        self.gets.append((url, dict(params or {})))
        base = RADARR if url.startswith(RADARR) else SONARR
        if base in self.down:
            raise requests.ConnectionError(f"Max retries exceeded with url: {url}?apikey={RKEY}{TKEY}")
        which = url.rsplit("/", 1)[1]
        rows = self.wanted[base][which]
        page, size = int(params["page"]), int(params["pageSize"])
        return R({"records": rows[(page - 1) * size:page * size], "totalRecords": len(rows)}, 200)

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
        write_envelope(tmp_path / "snaps", "jellyfin", age_minutes=1, data=JELLYFIN)
        import hub.main
        importlib.reload(hub.main)
        arr = Arr()
        monkeypatch.setattr(requests, "post", arr.post)
        monkeypatch.setattr(requests, "get", arr.get)
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
    assert "Search for better copies of 1 film and 1 show on Jellyfin below their quality cutoff?" in html and ">Search upgrades</button>" in html
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
    assert 'name="kind" value="missing"' in body and "Search 1 film and 1 show on Jellyfin that are missing files?" in body


@pytest.mark.parametrize("back", ["https://evil.invalid/x", "//evil.invalid", "/server"])
def test_back_is_a_local_media_page_only(env, back):
    client, _ = env()
    with client:
        html = client.get("/media/arr/sweep", params={"step": "confirm", "kind": "missing", "back": back}, headers=HX).text
    assert 'name="back" value="/media/requests"' in html


# ---- running it ----

@pytest.mark.parametrize("kind, radarr, sonarr", [
    ("missing", {"name": "MoviesSearch", "movieIds": [11]}, {"name": "EpisodeSearch", "episodeIds": [501, 502]}),
    ("upgrades", {"name": "MoviesSearch", "movieIds": [11]}, {"name": "EpisodeSearch", "episodeIds": [502]}),
])
def test_post_sends_id_scoped_commands_for_titles_on_jellyfin_only(env, kind, radarr, sonarr):
    client, arr = env()
    with client:
        r = sweep(client, kind)
        assert r.status_code == 303
        assert r.headers["location"] == "/media/downloads?sweep=started&ran=radarr%2Csonarr"
        page = main_of(client.get(r.headers["location"]).text)
    sent = sorted(((u, j) for u, j, _, _ in arr.posts), key=lambda x: x[0])
    assert sent == [(CMD[RADARR], radarr), (CMD[SONARR], sonarr)]
    assert {(u, h["X-Api-Key"]) for u, _, h, _ in arr.posts} == {(CMD[RADARR], RKEY), (CMD[SONARR], TKEY)}
    assert all(t == 10 for *_, t in arr.posts)                              # each its own 10 s timeout
    which = "missing" if kind == "missing" else "cutoff"
    assert all(u.endswith(f"/api/v3/wanted/{which}") and p["monitored"] == "true" for u, p in arr.gets)
    assert "Search started · Radarr · Sonarr" in page


def test_regression_no_library_wide_command_and_no_bare_body(env):
    """JY-302 AC1: before the fix the POST body was {"name": "MissingMoviesSearch"} with no ids."""
    client, arr = env()
    with client:
        sweep(client, "missing")
        sweep(client, "upgrades")
    assert arr.posts
    for _, body, _, _ in arr.posts:
        assert body["name"] in ("MoviesSearch", "EpisodeSearch")
        assert body.get("movieIds") or body.get("episodeIds")


@pytest.mark.parametrize("kind", ["missing", "upgrades"])
def test_off_server_monitored_titles_are_never_searched(env, kind):
    """AC4: a monitored film / show in the arr but not on Jellyfin (and Sonarr's empty folder) is in no id list."""
    client, arr = env()
    with client:
        sweep(client, kind)
    for _, body, _, _ in arr.posts:
        for field, off in OFF_SERVER.items():
            assert not set(body.get(field) or []) & off


def test_no_jellyfin_snapshot_searches_nothing(env, tmp_path):
    client, arr = env()
    (tmp_path / "snaps" / "jellyfin.json").unlink()
    with client:
        r = sweep(client, "missing")
        page = main_of(client.get(r.headers["location"]).text)
    assert r.headers["location"] == "/media/downloads?sweep=empty" and not arr.posts
    assert "Nothing to search" in page and "Search started" not in page


def test_one_app_with_nothing_on_jellyfin_sends_no_command_for_it(env):
    client, arr = env()
    arr.wanted[RADARR]["missing"] = [{"id": 12, "tmdbId": 200}]             # only an off-server film is missing
    with client:
        r = sweep(client, "missing")
    assert [u for u, *_ in arr.posts] == [CMD[SONARR]]
    assert r.headers["location"] == "/media/downloads?sweep=started&ran=sonarr"


def test_ids_are_batched_and_logged(env, monkeypatch, caplog):
    client, arr = env()
    monkeypatch.setattr(mas, "SWEEP_BATCH", 1)
    monkeypatch.setattr(mas, "WANTED_PAGE", 1)                              # paging too: one row per page
    with client, caplog.at_level(logging.INFO, logger="hub.media_arr_search"):
        sweep(client, "missing")
    son = [j for u, j, _, _ in arr.posts if u == CMD[SONARR]]
    assert son == [{"name": "EpisodeSearch", "episodeIds": [501]}, {"name": "EpisodeSearch", "episodeIds": [502]}]
    assert "sonarr missing sweep: 1 titles on Jellyfin, 2 ids in 2 batches, 2 off-server skipped" in caplog.text
    assert "radarr missing sweep: 1 titles on Jellyfin, 1 ids in 1 batches, 1 off-server skipped" in caplog.text


def test_confirm_counts_only_titles_on_jellyfin(env):
    client, arr = env()
    arr.wanted[RADARR]["missing"] = [{"id": 11, "tmdbId": 100}, {"id": 12, "tmdbId": 200}, {"id": 13, "tmdbId": 100}]
    with client:
        html = client.get("/media/arr/sweep?step=confirm&kind=missing", headers=HX).text
    assert "Search 2 films and 1 show on Jellyfin that are missing files?" in html and not arr.posts


def test_confirm_falls_back_to_plain_words_when_an_app_is_down(env):
    client, arr = env()
    arr.down.add(SONARR)
    with client:
        html = client.get("/media/arr/sweep?step=confirm&kind=missing", headers=HX).text
    assert "Search films and shows on Jellyfin that are missing files?" in html


def test_library_wide_command_names_are_gone_from_hub():
    """AC5: grep hub/ for the library-wide arr commands."""
    from pathlib import Path
    hub = Path(mas.__file__).resolve().parent
    names = ("Missing" + "MoviesSearch", "Missing" + "EpisodeSearch", "CutoffUnmet" + "MoviesSearch",
             "CutoffUnmet" + "EpisodeSearch")
    hits = [str(f) for f in hub.rglob("*") if f.is_file() and f.suffix in (".py", ".html", ".md", ".js")
            and any(n in f.read_text(encoding="utf-8", errors="ignore") for n in names)]
    assert hits == []


def test_one_app_down_still_runs_the_other(env, caplog):
    client, arr = env()
    arr.down.add(RADARR)
    with client, caplog.at_level(logging.WARNING):
        r = sweep(client, "missing", back="/media/requests")
        assert r.headers["location"] == "/media/requests?sweep=partial&ran=sonarr"
        page = main_of(client.get(r.headers["location"]).text)
    assert [u for u, *_ in arr.posts] == [CMD[SONARR]]                     # Radarr failed its read; Sonarr still asked
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
    assert [(u, j) for u, j, _, _ in arr.posts] == [(CMD[RADARR], {"name": "MoviesSearch", "movieIds": [11]})]


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

    def stuck(app, kind, server=None):
        started.set()
        release.wait(5)
        return "started"
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


def test_jy275_an_upgrades_sweep_then_checks_rows_and_missing_does_not(env, monkeypatch):
    """JY-275 (2026-11-04): after a started "Search upgrades" sweep the hub Why?-checks the cutoff-unmet rows in the
    background (media_upgrade_why.check_all) so viable ones flag; "Search missing" does not."""
    from hub import media_upgrade_why
    seen = []
    monkeypatch.setattr(media_upgrade_why, "check_all", lambda snaps: seen.append(snaps))
    client, _ = env()
    with client:
        sweep(client, "missing")
        assert seen == []
        sweep(client, "upgrades")
    assert len(seen) == 1
