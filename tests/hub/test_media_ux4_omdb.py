"""media-ux4 item 2 (2026-10-08): Metacritic via OMDb. Optional env OMDB_API_KEY; one lookup by IMDb id; `Metascore`,
else the Ratings "Metacritic" entry; every answer remembered 7 days (memory + disk beside the meta cache); a per-process
daily cap; a refused key stops calls for the day; no key / failure => no pill. The key never reaches a log or the page.
OMDb is faked at `requests.get`; no network."""
import json
import logging
import time

import pytest
import requests

from hub import media_discover, media_omdb
from tests.hub.conftest import main_of  # noqa: F401
from tests.hub.helpers import env, FakeResponse as R  # noqa: F401  (re-export: defined in tests/hub/helpers.py)

KEY = "omdbSECRETkey42"
TT = "tt0133093"


class BadJson(R):
    def json(self):
        raise ValueError("not json")


class Omdb:
    def __init__(self, body=None, status=200, exc=None, bad_json=False):
        self.body, self.status, self.exc, self.bad_json, self.calls = body, status, exc, bad_json, []

    def get(self, url, params=None, headers=None, timeout=None, **kw):
        self.calls.append((url, dict(params or {})))
        if self.exc:
            raise self.exc
        return (BadJson if self.bad_json else R)(self.body, self.status)


@pytest.fixture()
def omdb(monkeypatch):
    media_omdb.clear_cache()
    monkeypatch.setenv("OMDB_API_KEY", KEY)

    def install(**kw):
        fake = Omdb(**kw)
        monkeypatch.setattr(media_omdb.requests, "get", fake.get)
        return fake

    yield install
    media_omdb.clear_cache()


# ---- the lookup ----

def test_no_key_or_bad_id_makes_no_call(omdb, monkeypatch):
    fake = omdb(body={"Metascore": "74"})
    assert media_omdb.metascore("not-an-id") is None and media_omdb.metascore(None) is None
    monkeypatch.delenv("OMDB_API_KEY")
    assert media_omdb.metascore(TT) is None
    assert fake.calls == []


def test_metascore_by_imdb_id(omdb):
    fake = omdb(body={"Title": "The Matrix", "Metascore": "74", "Response": "True"})
    assert media_omdb.metascore(TT) == 74
    assert fake.calls == [("https://www.omdbapi.com/", {"i": TT, "apikey": KEY})]


def test_ratings_entry_is_the_fallback_and_na_is_none(omdb):
    omdb(body={"Metascore": "N/A", "Ratings": [{"Source": "Internet Movie Database", "Value": "8.7/10"},
                                               {"Source": "Metacritic", "Value": "68/100"}]})
    assert media_omdb.metascore(TT) == 68
    assert media_omdb.parse({"Metascore": "N/A", "Ratings": []}) is None
    assert media_omdb.parse({"Metascore": "N/A", "Ratings": [{"Source": "Metacritic", "Value": "N/A"}]}) is None
    assert media_omdb.parse({"Metascore": "250"}) is None and media_omdb.parse(None) is None


def test_na_is_remembered_so_the_title_costs_one_call(omdb):
    fake = omdb(body={"Metascore": "N/A", "Response": "True"})
    assert media_omdb.metascore(TT) is None
    assert media_omdb.metascore(TT) is None
    assert len(fake.calls) == 1


def test_cache_hit_survives_a_restart_on_disk(omdb):
    fake = omdb(body={"Metascore": "74"})
    assert media_omdb.metascore(TT) == 74
    media_omdb.clear_cache()                                    # a new process: memory empty, disk kept
    assert media_omdb.metascore(TT) == 74 and len(fake.calls) == 1
    files = list(media_discover.meta_dir().glob("*.json"))
    stored = [json.loads(f.read_text(encoding="utf-8")) for f in files]
    assert any(s["path"] == f"omdb:{TT}" and s["body"] == {"metascore": 74} for s in stored)
    assert all(KEY not in f.read_text(encoding="utf-8") for f in files)


def test_an_answer_is_kept_seven_days_then_asked_again(omdb, monkeypatch):
    fake = omdb(body={"Metascore": "74"})
    assert media_omdb.metascore(TT) == 74
    real = time.time
    monkeypatch.setattr(media_omdb.time, "time", lambda: real() + 6.9 * 86400)
    assert media_omdb.metascore(TT) == 74 and len(fake.calls) == 1
    monkeypatch.setattr(media_omdb.time, "time", lambda: real() + 7.1 * 86400)
    fake.body = {"Metascore": "75"}
    assert media_omdb.metascore(TT) == 75 and len(fake.calls) == 2


def test_daily_cap_stops_new_calls(omdb, monkeypatch):
    monkeypatch.setattr(media_omdb, "DAILY_CAP", 2)
    fake = omdb(body={"Metascore": "60"})
    assert [media_omdb.metascore(f"tt100000{i}") for i in range(3)] == [60, 60, None]
    assert len(fake.calls) == 2
    assert media_omdb.metascore("tt1000000") == 60               # a cached title still answers over the cap
    assert media_omdb.DAILY_CAP < 1000                           # module default respects the 1,000/day free tier
    monkeypatch.setattr(media_omdb, "DAILY_CAP", 800)


def test_failure_is_sanitized_and_remembered(omdb, caplog):
    fake = omdb(exc=requests.ConnectionError(f"https://www.omdbapi.com/?i={TT}&apikey={KEY} failed"))
    with caplog.at_level(logging.WARNING, logger="hub.media_omdb"):
        assert media_omdb.metascore(TT) is None
        assert media_omdb.metascore(TT) is None
    assert len(fake.calls) == 1                                  # a failure is remembered too (for FAIL_TTL)
    assert "ConnectionError" in caplog.text and KEY not in caplog.text and "apikey" not in caplog.text


@pytest.mark.parametrize("kw", [{"exc": requests.ConnectionError("down")}, {"body": {"x": 1}, "status": 503},
                                {"bad_json": True}])
def test_a_failure_is_remembered_ten_minutes_not_seven_days(omdb, monkeypatch, kw):
    """M-51 (W2): a network error, a 5xx or a bad body waits FAIL_TTL (10 min), restarts included, then asks again."""
    fake = omdb(**kw)
    assert media_omdb.metascore(TT) is None
    media_omdb.clear_cache()                                     # a restart: the short wait is on disk too
    real = time.time
    monkeypatch.setattr(media_omdb.time, "time", lambda: real() + 9 * 60)
    assert media_omdb.metascore(TT) is None and len(fake.calls) == 1
    monkeypatch.setattr(media_omdb.time, "time", lambda: real() + 11 * 60)
    fake.exc, fake.bad_json, fake.body, fake.status = None, False, {"Metascore": "74"}, 200
    assert media_omdb.metascore(TT) == 74 and len(fake.calls) == 2


def test_a_slow_title_does_not_hold_up_another(omdb, monkeypatch):
    """M-43 (W2): the lock is per title — a lookup stuck on OMDb never queues a different title behind it."""
    import threading
    slow_started, release = threading.Event(), threading.Event()

    def get(url, params=None, timeout=None, **kw):
        if params["i"] == TT:
            slow_started.set()
            release.wait(5)
        return R({"Metascore": "60"}, 200)

    monkeypatch.setattr(media_omdb.requests, "get", get)
    worker = threading.Thread(target=media_omdb.metascore, args=(TT,))
    worker.start()
    try:
        assert slow_started.wait(5)
        t0 = time.monotonic()
        assert media_omdb.metascore("tt7654321") == 60
        assert time.monotonic() - t0 < 1.0
    finally:
        release.set()
        worker.join(5)


def test_http_error_logs_the_status_only(omdb, caplog):
    omdb(body={"Error": f"bad {KEY}"}, status=500)
    with caplog.at_level(logging.WARNING, logger="hub.media_omdb"):
        assert media_omdb.metascore(TT) is None
    assert "HTTP 500" in caplog.text and KEY not in caplog.text


@pytest.mark.parametrize("body, status", [({"Response": "False", "Error": "Invalid API key!"}, 200),
                                          ({"Response": "False", "Error": "Request limit reached!"}, 200),
                                          ({"Response": "False", "Error": "Invalid API key!"}, 401)])
def test_a_refused_key_stops_calls_for_the_day_without_marking_titles(omdb, body, status, caplog):
    fake = omdb(body=body, status=status)
    with caplog.at_level(logging.WARNING, logger="hub.media_omdb"):
        assert media_omdb.metascore(TT) is None
        assert media_omdb.metascore("tt7654321") is None
    assert len(fake.calls) == 1 and KEY not in caplog.text
    media_omdb._day[2] = False                                   # tomorrow (or a fixed key): the title is asked again
    fake.body, fake.status = {"Metascore": "74"}, 200
    assert media_omdb.metascore(TT) == 74


# ---- the film page ----

def film_page(env, monkeypatch, body, path="/media/title/movie/603", imdb=TT, status=200):
    client, both = env()
    both.seerr.table["/api/v1/movie/603"] = {**both.seerr.table["/api/v1/movie/603"], "externalIds": {"imdbId": imdb}}
    omdb_fake = Omdb(body=body, status=status)
    seerr_get = both.get

    def get(url, params=None, headers=None, timeout=None, **kw):
        if url.startswith(media_omdb.URL):
            return omdb_fake.get(url, params=params, headers=headers, timeout=timeout)
        return seerr_get(url, params=params, headers=headers, timeout=timeout)

    monkeypatch.setattr(requests, "get", get)
    with client:
        html = client.get(path).text
    return html, omdb_fake


@pytest.mark.parametrize("score, band", [("74", "good"), ("61", "good"), ("60", "mid"), ("40", "mid"), ("39", "bad")])
def test_metacritic_pill_tinted_by_band_with_the_number(env, omdb, monkeypatch, score, band):
    html, fake = film_page(env, monkeypatch, {"Metascore": score})
    b = main_of(html)
    assert (f'<span class="scorepill sp-mc sp-mc-{band}" title="Metacritic {score}"><img class="sp-logo" '
            f'src="/static/logos/mc.svg" alt="" width="16" height="16"><span class="sp-name">Metacritic</span>'
            f'<b class="sp-val">{score}</b></span>') in b
    box = b.split('<div class="scorepills">', 1)[1]
    assert box.index("sp-rt") < box.index("sp-mc") < box.index("sp-tmdb")       # IMDb · RT · Metacritic · TMDB · Yours
    assert KEY not in html and fake.calls[0][1]["i"] == TT


def test_no_key_no_pill_and_no_call(env, monkeypatch):
    html, fake = film_page(env, monkeypatch, {"Metascore": "74"})
    assert "sp-mc" not in main_of(html) and fake.calls == []


def test_na_or_failure_no_pill(env, omdb, monkeypatch):
    html, _ = film_page(env, monkeypatch, {"Metascore": "N/A"})
    assert "sp-mc" not in main_of(html)
    media_omdb.clear_cache()
    html, _ = film_page(env, monkeypatch, {}, status=503)
    assert "sp-mc" not in main_of(html) and "Metacritic" not in main_of(html)


def test_imdb_id_sources():
    from hub.media_film import imdb_id
    assert imdb_id({"externalIds": {"imdbId": TT}}, None) == TT
    assert imdb_id({"imdbId": "tt7654321"}, None) == "tt7654321"
    assert imdb_id({}, {"imdb": "tt1234567"}) == "tt1234567"
    assert imdb_id({"externalIds": {"imdbId": "nope"}}, {"imdb": None}) is None


def test_the_jellyfin_imdb_id_is_used_when_jellyseerr_has_none(env, omdb, monkeypatch):
    from tests.hub import helpers as tmi
    monkeypatch.setitem(tmi.ITEMS["mov1"], "ProviderIds", {"Tmdb": "603", "Imdb": "tt1234567"})
    html, fake = film_page(env, monkeypatch, {"Metascore": "81"}, path="/media/item/mov1", imdb=None)
    assert fake.calls and fake.calls[0][1]["i"] == "tt1234567" and "sp-mc-good" in html
