"""WP-U1 (2026-10-21): "Why?" + "Grab anyway" on Activity › Downloads › Upgrades, and the last-search line.

Built for the live case (Brothers (2026) S01E01, Sonarr episode 362, series 15): the interactive search answered 30
releases, all rejected, nearly all by the "1080p" profile's minimum custom-format score (1000). The fixture below is that
answer trimmed and renamed (synthetic titles). Radarr / Sonarr are faked at requests.get / requests.post; no network.
Covers: the page draws Why? and the last-search line with no arr call; the confirm (htmx + no-JS); the search (params,
timeout, 1 h cache); the grouped reasons, hint and top 5; Grab anyway (confirm, POST body from the kept answer, flash,
failures); same-origin 403; unknown rows 404; logs never carry a URL, key or release title."""
import html as htmllib
import importlib
import logging

import pytest
import requests
from fastapi.testclient import TestClient

from hub import media_upgrade_why as why
from hub import media_upgrades as mu
from tests.hub.conftest import main_raw
from tests.hub.helpers import FakeResponse as R, JELLY, make_area, make_tile, shelf_area, write_envelope, write_registry

RADARR = "http://radarr.secret-host.invalid:7878"
RKEY = "r-SECRET-radarr-key"
SONARR = "http://sonarr.secret-host.invalid:8989"
SKEY = "s-SECRET-sonarr-key"
HX = {"HX-Request": "true"}
BAD_ORIGIN = {"Origin": "https://evil.invalid"}

UP = {"radarr": [{"item_key": "tmdb:11", "title": "Alpha Film", "year": 2020, "arr_id": 7, "have": "WEBDL-720p",
                  "want": "Bluray-1080p", "profile": "HD-1080p", "poster": None}],
      "sonarr": [{"item_key": "tvdb:7021", "title": "Brother Show", "arr_id": 15, "episodes": 1, "have": "HDTV-1080p",
                  "want": "WEB/Bluray 1080p", "profile": "1080p", "sample": "S01E01", "episode_id": 362, "poster": None},
                 {"item_key": "tvdb:7022", "title": "Old Envelope Show", "arr_id": 16, "episodes": 2, "have": "SDTV",
                  "want": "WEB 1080p", "sample": "S01E02", "poster": None}],     # no episode_id: an older envelope
      "totals": {"movies": 1, "episodes": 3, "series": 2},
      "last_search": [{"name": "upgrades", "app": "sonarr", "status": "completed", "ended": "2026-10-20T13:59:30Z",
                       "message": "Completed search for 1 episodes. 0 reports downloaded."}]}

CF = ("Custom Formats LQ Release Group have score -1000 below Series profile minimum 1000",
      "Custom Formats No-RlsGroup have score -10000 below Series profile minimum 1000",
      "Custom Formats MULTI have score -50 below Series profile minimum 1000")


def rel(i, rejections, approved=False):
    return {"guid": f"guid-{i}", "indexerId": 10 + i % 3, "indexer": f"Indexer {'ABC'[i % 3]}",
            "title": f"Synthetic.Show.S01E01.Release.{i}", "quality": {"quality": {"name": "HDTV-1080p"}},
            "size": 1_500_000_000 + i, "seeders": i, "releaseGroup": f"GRP{i}", "protocol": "torrent",
            "approved": approved, "rejected": not approved, "rejections": list(rejections)}


def thirty(unknown_has_cf=True):
    """The live answer, trimmed: 20 custom-format only, 7 + 'not wanted', 2 + 'too small', 1 'Unknown Series'."""
    out = [rel(i, [CF[i % 3]]) for i in range(20)]
    out += [rel(20 + i, ["HDTV-1080p is not wanted in profile", CF[0]]) for i in range(7)]
    out += [rel(27 + i, [CF[1], "294.6 MB is smaller than minimum allowed 480.0 MB (for 32min)"]) for i in range(2)]
    out += [rel(29, ["Unknown Series"] + ([CF[2]] if unknown_has_cf else []))]
    return out


class Arr:
    """requests.get / requests.post for both apps: records calls; `releases` answers /api/v3/release."""

    def __init__(self):
        self.gets, self.posts = [], []
        self.releases = thirty()
        self.get_fail = self.post_status = self.post_fail = None
        self.post_status = 200

    def get(self, url, params=None, headers=None, timeout=None, **kw):
        self.gets.append((url, params, headers, timeout))
        if self.get_fail is not None:
            if isinstance(self.get_fail, int):
                return R({}, self.get_fail)
            raise self.get_fail
        assert url.endswith("/api/v3/release"), url
        return R(self.releases)

    def post(self, url, json=None, headers=None, timeout=None, **kw):
        self.posts.append((url, json, headers, timeout))
        if self.post_fail is not None:
            raise self.post_fail
        return R({}, self.post_status)


@pytest.fixture()
def site(tmp_path, monkeypatch):
    area = shelf_area()
    area["tiles"].append(make_tile("dl-t", snapshot="qbittorrent", stale_after_minutes=10, detail="/media/downloads"))
    monkeypatch.setenv("AREAS_PATH", str(write_registry(tmp_path, area, make_area("beta"))))
    monkeypatch.setenv("MEDIA_DB_PATH", str(tmp_path / "media.db"))
    monkeypatch.setenv("SNAPSHOT_DIR", str(tmp_path / "snaps"))
    for k in ("JELLYSEERR_URL", "JELLYSEERR_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("RADARR_URL", RADARR)
    monkeypatch.setenv("RADARR_API_KEY", RKEY)
    monkeypatch.setenv("SONARR_URL", SONARR)
    monkeypatch.setenv("SONARR_API_KEY", SKEY)

    def build(upgrades=UP):
        snaps = tmp_path / "snaps"
        write_envelope(snaps, "jellyfin", age_minutes=1, data={**JELLY, "movies": [], "shows": []})
        write_envelope(snaps, "arr", age_minutes=1,
                       data={"summary": "x", **({"upgrades": upgrades} if upgrades is not None else {})})
        write_envelope(snaps, "jellyseerr", age_minutes=1, data={"summary": "x", "requests": []})
        write_envelope(snaps, "qbittorrent", age_minutes=1, data={"summary": "x", "active": []})
        import hub.main
        importlib.reload(hub.main)
        arr = Arr()
        monkeypatch.setattr(requests, "get", arr.get)
        monkeypatch.setattr(requests, "post", arr.post)
        return TestClient(hub.main.app), arr
    return build


def page(client, path="/media/downloads"):
    return htmllib.unescape(main_raw(client.get(path).text))


def area_of(html, dom="why-sonarr-15"):
    return html.split(f'<div id="{dom}"', 1)[1].split("\n</div>", 1)[0]


def ask(client, app="sonarr", arr_id=15, **headers):
    return client.post(f"/media/upgrades/why/{app}/{arr_id}", headers=headers, follow_redirects=False)


def grab(client, pick, app="sonarr", arr_id=15, extra=None, **headers):
    return client.post(f"/media/upgrades/why/{app}/{arr_id}/grab", data={"pick": pick, **(extra or {})},
                       headers=headers, follow_redirects=False)


# ---- the words: unit ----

def test_reason_groups_the_live_rejection_texts():
    assert why.reason(CF[0]) == ("cf:1000", "custom-format score below the profile minimum (1000)")
    assert why.reason(CF[1])[0] == why.reason(CF[2])[0] == "cf:1000"          # one group whatever the format's score
    assert why.reason("HDTV-1080p is not wanted in profile")[1] == "quality not wanted in profile"
    assert why.reason("294.6 MB is smaller than minimum allowed 480.0 MB (for 32min)")[1] == "too small"
    assert why.reason("Unknown Series")[1] == "unknown series"
    assert why.reason("Something brand new")[1] == "Something brand new"     # unknown: verbatim, its own group


def test_summarize_the_live_answer():
    res = why.summarize(thirty(), "sonarr", "1080p", "S01E01")
    assert res["summary"] == "S01E01 · 30 releases · all rejected"
    assert [(r["n"], r["text"]) for r in res["reasons"]] == [
        (30, "custom-format score below the profile minimum (1000)"), (7, "quality not wanted in profile"),
        (2, "too small"), (1, "unknown series")]
    assert res["hint"] == ("The 1080p profile's minimum custom-format score (1000) rejects every release for this title "
                           "— lower it in Sonarr › Settings › Profiles, or grab one anyway.")
    c = res["candidates"]
    assert len(c) == 5 and [x["guid"] for x in c] == [f"guid-{i}" for i in range(5)]     # the app's own order
    assert c[1]["facts"] == ["HDTV-1080p", "1.4 GB", "1 seeder", "Indexer B", "GRP1"]
    assert c[1]["first"] == CF[1] and c[1]["rejected"] and not c[1]["unknown"]


def test_summarize_hint_all_but_one_and_not_when_something_is_accepted():
    # JY-108 (B., 2026-10-24: "1A 2A") rewrites the old "every rejection" rule on purpose; see the spec.
    one_other = why.summarize(thirty(unknown_has_cf=False), "sonarr", "1080p")   # 29 of 30 carry the minimum
    assert one_other["hint"] == ("The 1080p profile's minimum custom-format score (1000) rejects 29 of 30 releases for "
                                 "this title — lower it in Sonarr › Settings › Profiles, or grab one anyway.")
    mixed = thirty() + [rel(30, [], approved=True)]
    res = why.summarize(mixed, "sonarr", None)                        # something accepted: still no hint
    assert res["hint"] is None and res["summary"] == "31 releases · 1 accepted · 30 rejected"
    assert res["candidates"][0]["guid"] == "guid-30" and res["candidates"][0]["first"] is None   # accepted first
    assert why.summarize(thirty(), "radarr", None)["hint"].startswith("The profile's minimum custom-format score (1000)")
    assert "Radarr › Settings › Profiles" in why.summarize(thirty(), "radarr", None)["hint"]


def test_summarize_hint_first_release_rule():
    rels = [rel(0, [CF[0]])] + [rel(i, ["Unknown Series"]) for i in range(1, 5)]   # 1 of 5: below half, but the best one
    assert why.summarize(rels, "sonarr", "1080p")["hint"].startswith(
        "The 1080p profile's minimum custom-format score (1000) rejects 1 of 5 releases for this title")


def test_summarize_hint_half_rule():
    other = ["Unknown Series"]
    two_of_four = [rel(0, other), rel(1, [CF[0]]), rel(2, other), rel(3, [CF[1]])]   # exactly half, best one is not it
    assert "rejects 2 of 4 releases for this title" in why.summarize(two_of_four, "sonarr", None)["hint"]
    three_of_five = [rel(0, other), rel(1, other), rel(2, [CF[0]]), rel(3, [CF[1]]), rel(4, [CF[2]])]
    assert "rejects 3 of 5 releases for this title" in why.summarize(three_of_five, "sonarr", None)["hint"]


def test_summarize_no_hint_below_half_and_not_the_best():
    other = ["Unknown Series"]
    two_of_five = [rel(0, other), rel(1, other), rel(2, other), rel(3, [CF[0]]), rel(4, [CF[1]])]
    assert why.summarize(two_of_five, "sonarr", None)["hint"] is None
    none_at_all = [rel(i, other) for i in range(4)]
    assert why.summarize(none_at_all, "sonarr", None)["hint"] is None


def test_summarize_hint_says_every_release_only_when_n_equals_m():
    every = why.summarize([rel(i, [CF[i % 3]]) for i in range(3)], "sonarr", None)["hint"]
    assert "rejects every release for this title" in every and " of 3 " not in every
    partial = why.summarize([rel(0, [CF[0]]), rel(1, [CF[1]]), rel(2, ["Unknown Series"])], "sonarr", None)["hint"]
    assert "rejects 2 of 3 releases for this title" in partial and "every release" not in partial


def test_summarize_edges():
    assert why.summarize([], "radarr")["summary"] == "No releases found"
    assert why.summarize([rel(1, ["Unknown Series"])], "sonarr")["summary"] == "1 release · rejected"
    one = why.summarize([rel(1, [{"reason": "x", "message": "Unknown Series"}])], "sonarr")   # dict-shaped rejection
    assert one["reasons"] == [{"n": 1, "text": "unknown series"}] and one["candidates"][0]["unknown"]
    small = {**rel(2, []), "size": 300 * 1024 ** 2, "seeders": None, "approved": True, "rejected": False}
    assert why.summarize([small], "sonarr")["candidates"][0]["facts"] == ["HDTV-1080p", "300.0 MB", "Indexer C", "GRP2"]


# ---- the last-search line (unit + page) ----

def snaps_with(last):
    from types import SimpleNamespace
    return {"arr": SimpleNamespace(data={"upgrades": {**UP, "last_search": last}})}


def test_last_search_words():
    nothing = mu.last_search(snaps_with(UP["last_search"]))
    assert nothing == [{"parts": ["Last upgrade search", "Sonarr", "21 Oct 00:59", "1 searched"], "warn": "0 downloaded"}]
    found = mu.last_search(snaps_with([{"name": "missing", "app": "radarr", "status": "completed",
                                        "ended": "2026-10-20T14:00:00Z",
                                        "message": "Completed search for 3 movies. 2 reports downloaded."}]))
    assert found == [{"parts": ["Last missing search", "Radarr", "21 Oct 01:00", "3 searched", "2 downloaded"],
                      "warn": None}]
    odd = mu.last_search(snaps_with([{"name": "upgrades", "app": "sonarr", "status": "completed", "ended": None,
                                      "message": "Something else"}]))
    assert odd == [{"parts": ["Last upgrade search", "Sonarr", "Something else"], "warn": None}]   # verbatim
    running = mu.last_search(snaps_with([{"name": "upgrades", "app": "sonarr", "status": "started", "ended": None,
                                          "message": None}]))
    assert running == [{"parts": ["Last upgrade search", "Sonarr", "running"], "warn": None}]
    failed = mu.last_search(snaps_with([{"name": "upgrades", "app": "radarr", "status": "failed",
                                         "ended": "2026-10-20T14:00:00Z", "message": "boom"}]))
    assert failed[0]["warn"] == "failed"
    assert mu.last_search(snaps_with([])) == [] and mu.last_search({}) == []


def test_downloads_shows_the_last_search_line_found_nothing_absent(site):
    client, arr = site()
    with client:
        body = page(client)
    assert ('<p class="metaline lastsearch">Last upgrade search · Sonarr · 21 Oct 00:59 · 1 searched · '
            '<span class="st-warn">0 downloaded</span></p>') in body
    client, arr = site(upgrades={**UP, "last_search": [{"name": "upgrades", "app": "sonarr", "status": "completed",
                                                       "ended": "2026-10-20T14:00:00Z",
                                                       "message": "Completed search for 4 episodes. 1 reports downloaded."}]})
    with client:
        body = page(client)
    assert '<p class="metaline lastsearch">Last upgrade search · Sonarr · 21 Oct 01:00 · 4 searched · 1 downloaded</p>' in body
    client, arr = site(upgrades={k: v for k, v in UP.items() if k != "last_search"})   # older envelope
    with client:
        body = page(client)
    assert "lastsearch" not in body and arr.gets == [] and arr.posts == []


# ---- the page: Why? on each row, no call ----

def test_each_upgrades_row_has_why_and_the_page_makes_no_arr_call(site):
    client, arr = site()
    with client:
        body = page(client)
    blk = body.split('id="upgrades"', 1)[1].split("</section>", 1)[0]
    assert blk.count(">Why?</a>") == 3 and blk.count('<div class="row has-form">') == 3
    a = area_of(blk)
    assert 'hx-get="/media/upgrades/why/sonarr/15?step=confirm"' in a
    assert 'href="/media/downloads?why=sonarr:15&why_step=confirm#why-sonarr-15"' in a      # no-JS
    assert 'hx-get="/media/upgrades/why/radarr/7?step=confirm"' in blk
    assert "Below cutoff · 1 episode · HDTV-1080p → wants WEB/Bluray 1080p" in blk
    assert arr.gets == [] and arr.posts == []


def test_confirm_step_htmx_and_no_js_make_no_call(site):
    client, arr = site()
    with client:
        r = client.get("/media/upgrades/why/sonarr/15?step=confirm", headers=HX)
        assert r.status_code == 200
        card = htmllib.unescape(r.text)
        assert "Ask Sonarr to search the indexers now? Takes up to a minute." in card
        assert 'hx-post="/media/upgrades/why/sonarr/15"' in card and 'method="post"' in card
        nojs = client.get("/media/upgrades/why/sonarr/15?step=confirm", follow_redirects=False)
        assert nojs.status_code == 303
        assert nojs.headers["location"] == "/media/downloads?why=sonarr%3A15&why_step=confirm#why-sonarr-15"
        body = page(client, "/media/downloads?why=sonarr:15&why_step=confirm")
    assert "Ask Sonarr to search the indexers now?" in area_of(body)
    assert "Ask Radarr" not in body                                                  # that row only
    assert arr.gets == [] and arr.posts == []


@pytest.mark.parametrize("path", ["/media/upgrades/why/sonarr/99?step=confirm", "/media/upgrades/why/lidarr/7",
                                  "/media/upgrades/why/radarr/15?step=confirm"])
def test_unknown_rows_are_404(site, path):
    client, arr = site()
    with client:
        assert client.get(path, headers=HX).status_code == 404
        assert client.post(path.split("?")[0], headers=HX).status_code == 404
    assert arr.gets == []


# ---- the search ----

def test_why_runs_the_interactive_search_once_and_draws_the_answer(site):
    client, arr = site()
    with client:
        r = ask(client, **HX)
        assert r.status_code == 200
        out = htmllib.unescape(r.text)
        assert ask(client, **HX).status_code == 200                                  # within the hour: kept
    assert arr.gets == [(f"{SONARR}/api/v3/release", {"episodeId": 362}, {"X-Api-Key": SKEY}, 90)]
    assert "S01E01 · 30 releases · all rejected · searched just now" in out
    assert "<li>30 × custom-format score below the profile minimum (1000)</li>" in out
    assert "<li>7 × quality not wanted in profile</li>" in out and "<li>1 × unknown series</li>" in out
    assert "The 1080p profile's minimum custom-format score (1000) rejects every release for this title" in out
    assert out.count('class="whycand"') == 5 and out.count(">Grab anyway</a>") == 5
    assert "Synthetic.Show.S01E01.Release.0" in out and f"Rejected · {CF[0]}" in out
    assert 'hx-get="/media/upgrades/why/sonarr/15?step=grab&pick=2"' in out
    assert 'href="/media/downloads?why=sonarr:15&why_step=grab&pick=2#why-sonarr-15"' in out
    assert "guid-" not in out                                                        # guids stay server-side


def test_the_kept_answer_expires_after_an_hour(site, monkeypatch):
    client, arr = site()
    now = [1000.0]
    monkeypatch.setattr(why, "_clock", lambda: now[0])
    with client:
        ask(client, **HX)
        now[0] += why.TTL - 1
        ask(client, **HX)
        assert len(arr.gets) == 1
        now[0] += 2
        ask(client, **HX)
    assert len(arr.gets) == 2


def test_radarr_searches_by_movie_id(site):
    client, arr = site()
    with client:
        out = htmllib.unescape(ask(client, "radarr", 7, **HX).text)
    assert arr.gets == [(f"{RADARR}/api/v3/release", {"movieId": 7}, {"X-Api-Key": RKEY}, 90)]
    assert "30 releases · all rejected" in out and "S01E01 ·" not in out
    assert "lower it in Radarr › Settings › Profiles" in out


def test_why_without_js_redirects_to_the_page_which_draws_the_kept_answer(site):
    client, arr = site()
    with client:
        r = ask(client)
        assert r.status_code == 303 and r.headers["location"] == "/media/downloads?why=sonarr%3A15#why-sonarr-15"
        body = page(client, "/media/downloads?why=sonarr:15")
        plain = page(client)
    assert "30 releases · all rejected" in area_of(body)
    assert "30 releases" not in plain                                                # other views: just Why?
    assert len(arr.gets) == 1


@pytest.mark.parametrize("fail, word", [
    (requests.ConnectionError(f"Max retries exceeded with url: {SONARR}/api/v3/release?apikey={SKEY}"),
     "Couldn't reach Sonarr · try again"),
    (requests.ReadTimeout("read timed out"), "Couldn't reach Sonarr · try again"),
    (500, "Sonarr refused the search")])
def test_a_failed_search_is_a_word_and_is_not_kept(site, caplog, fail, word):
    client, arr = site()
    arr.get_fail = fail
    with caplog.at_level(logging.INFO), client:
        out = htmllib.unescape(ask(client, **HX).text)
        nojs = ask(client)
    assert f'<p class="metaline st-warn" role="status">{word}</p>' in out and ">Why?</a>" in out
    assert "wf=" in nojs.headers["location"] and len(arr.gets) == 2                  # nothing kept
    for secret in (SKEY, RKEY, "secret-host", "apikey"):
        assert secret not in caplog.text


def test_no_episode_id_and_not_connected(site, monkeypatch):
    client, arr = site()
    with client:
        out = htmllib.unescape(ask(client, "sonarr", 16, **HX).text)
        assert "No episode id yet · try after the next refresh" in out
        monkeypatch.delenv("SONARR_URL")
        out = htmllib.unescape(ask(client, **HX).text)
    assert "Sonarr is not connected" in out and arr.gets == []


# ---- Grab anyway ----

def test_grab_confirm_names_the_release_and_makes_no_call(site):
    client, arr = site()
    with client:
        ask(client, **HX)
        out = htmllib.unescape(client.get("/media/upgrades/why/sonarr/15?step=grab&pick=4", headers=HX).text)
        body = page(client, "/media/downloads?why=sonarr:15&why_step=grab&pick=4")
    for html in (out, area_of(body)):
        assert "Grab Synthetic.Show.S01E01.Release.4 from Indexer B?" in html
        assert ("Sonarr will download it even though it rejected it; an 'Unknown Series' release may still fail to "
                "import.") in html
        assert '<input type="hidden" name="pick" value="4">' in html and 'hx-post="/media/upgrades/why/sonarr/15/grab"' in html
    assert len(arr.gets) == 1 and arr.posts == []


def test_grab_posts_the_kept_release_and_flashes(site, caplog):
    client, arr = site()
    with caplog.at_level(logging.INFO), client:
        ask(client, **HX)
        out = htmllib.unescape(grab(client, 3, extra={"guid": "attacker-guid", "indexerId": "999"}, **HX).text)
    assert arr.posts == [(f"{SONARR}/api/v3/release", {"guid": "guid-3", "indexerId": 10}, {"X-Api-Key": SKEY}, 30)]
    assert '<p class="metaline st-good" role="status">Grab sent · check Downloads in a minute</p>' in out
    assert "30 releases · all rejected" in out                                       # the answer stays drawn
    assert "Synthetic" not in caplog.text


@pytest.mark.parametrize("setup, word", [
    ({"post_status": 404}, "Sonarr no longer holds that release · ask Why? again"),
    ({"post_status": 500}, "Sonarr refused the grab (HTTP 500)"),
    ({"post_fail": requests.ConnectionError(f"{SONARR}?apikey={SKEY} Synthetic.Show")}, "Couldn't reach Sonarr")])
def test_grab_failures_are_words(site, caplog, setup, word):
    client, arr = site()
    for k, v in setup.items():
        setattr(arr, k, v)
    with caplog.at_level(logging.INFO), client:
        ask(client, **HX)
        out = htmllib.unescape(grab(client, 0, **HX).text)
    assert f'<p class="metaline st-warn" role="status">{word}</p>' in out
    for secret in (SKEY, "secret-host", "Synthetic", "guid-"):
        assert secret not in caplog.text


def test_a_404_grab_forgets_the_kept_answer_so_why_searches_again(site):
    """Sonarr keeps interactive-search releases ~30 min; past that a grab is 404 and the next Why? must not reuse ours."""
    client, arr = site()
    arr.post_status = 404
    with client:
        ask(client, **HX)
        out = htmllib.unescape(grab(client, 0, **HX).text)
        assert "Sonarr no longer holds that release · ask Why? again" in out and ">Why?</a>" in out
        ask(client, **HX)
    assert len(arr.gets) == 2


def test_grab_without_a_kept_answer_or_a_bad_pick_sends_nothing(site):
    client, arr = site()
    with client:
        out = htmllib.unescape(grab(client, 0, **HX).text)
        assert "That search has expired · ask Why? again" in out
        ask(client, **HX)
        assert "That search has expired" in htmllib.unescape(grab(client, 9, **HX).text)
        assert "That search has expired" in htmllib.unescape(grab(client, "x", **HX).text)
    assert arr.posts == []


def test_grab_without_js_redirects_with_the_flash(site):
    client, arr = site()
    with client:
        ask(client, **HX)
        r = grab(client, 1)
        assert r.status_code == 303
        assert r.headers["location"] == "/media/downloads?why=sonarr%3A15&grab=sent#why-sonarr-15"
        body = page(client, "/media/downloads?why=sonarr:15&grab=sent")
        arr.post_status = 500
        r = grab(client, 1)
        assert r.headers["location"] == "/media/downloads?why=sonarr%3A15&grab=refused&gcode=500#why-sonarr-15"
        bad = page(client, "/media/downloads?why=sonarr:15&grab=refused&gcode=500")
    assert "Grab sent · check Downloads in a minute" in area_of(body) and "30 releases" in area_of(body)
    assert "Sonarr refused the grab (HTTP 500)" in area_of(bad)


def test_cross_site_writes_are_refused(site):
    client, arr = site()
    with client:
        assert ask(client, **BAD_ORIGIN).status_code == 403
        assert grab(client, 0, **BAD_ORIGIN).status_code == 403
    assert arr.gets == [] and arr.posts == []
