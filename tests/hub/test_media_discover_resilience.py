"""E1 (2026-10-13): Discover never blocks the page. Shelf and provider-list reads wait 3 s; the last good rows (memory
and disk) are served with their age when a read fails; a failure is remembered 60 s; nothing stored = "Discover
unavailable" at once. `requests` is the test_media_discover Fake — nothing hits the network."""
import logging

import requests

from hub import media_discover as md
from tests.hub.conftest import main_of
from tests.hub.test_media_discover import FAKE_KEY, env  # noqa: F401  (env fixture)
from tests.hub.test_media_services import tiles, wire


def shelf_gets(fake):
    return [g for g in fake.gets if g.startswith("/api/v1/discover/")]


def later(monkeypatch, seconds):
    """Move both clocks Discover reads (wall time for the 10-min TTL, monotonic for the failure memo) on."""
    wall, mono = md.time.time, md.time.monotonic
    monkeypatch.setattr(md.time, "time", lambda: wall() + seconds)
    monkeypatch.setattr(md.time, "monotonic", lambda: mono() + seconds)


def test_shelf_and_provider_reads_wait_three_seconds_title_reads_eight(env):
    client, fake = env()
    seen = {}
    plain = fake.get

    def get(url, headers=None, timeout=None, **kw):
        seen[url.split(":5055", 1)[1]] = timeout
        return plain(url, headers=headers, timeout=timeout, **kw)
    md.requests.get = get
    with client:
        client.get("/media/discover")
        client.get("/media/title/movie/603")
    assert md.SHELF_TIMEOUT == 3 and md.TIMEOUT == 8
    assert {p: t for p, t in seen.items() if p.startswith("/api/v1/discover/")} == {
        p: 3 for p in ("/api/v1/discover/trending", "/api/v1/discover/movies", "/api/v1/discover/tv",
                       "/api/v1/discover/movies/upcoming", "/api/v1/discover/tv/upcoming")}
    assert seen["/api/v1/watchproviders/movies?watchRegion=AU"] == 3
    assert seen["/api/v1/movie/603"] == 8


def test_a_failed_refresh_serves_the_last_good_rows_with_their_age(env, monkeypatch):
    client, fake = env()
    with client:
        client.get("/media/discover")
        later(monkeypatch, 12 * 60)          # past the 10-min fresh TTL
        fake.fail = True
        r = client.get("/media/discover")
    body = main_of(r.text)
    assert r.status_code == 200 and "Discover unavailable" not in body
    assert '<h2 class="seclabel">Trending · 12m ago</h2>' in body
    assert '<h2 class="seclabel">Popular films · 12m ago</h2>' in body and "Film Five" in body
    assert FAKE_KEY not in r.text and "secret-host" not in r.text


def test_the_failure_is_remembered_a_minute_then_read_again(env, monkeypatch):
    client, fake = env()
    with client:
        client.get("/media/discover")
        later(monkeypatch, 11 * 60)
        fake.fail = True
        client.get("/media/discover")
        n = len(shelf_gets(fake))
        fake.fail = False
        client.get("/media/discover")
        assert len(shelf_gets(fake)) == n             # inside FAIL_TTL: no wait on Seerr, last rows served
        later(monkeypatch, 11 * 60 + md.FAIL_TTL + 1)
        r = client.get("/media/discover")
    assert len(shelf_gets(fake)) == n + 5             # the minute is up: read again, fresh rows, no age
    assert '<h2 class="seclabel">Trending</h2>' in main_of(r.text)


def test_last_good_rows_survive_a_restart_on_disk(env, monkeypatch):
    client, fake = env()
    with client:
        client.get("/media/discover")
    md.clear_cache()                                  # a restart: memory gone, the disk copy stays
    fake.fail = True
    with client:
        fresh = client.get("/media/discover")
    assert shelf_gets(fake)[5:] == []                 # under 10 min on disk: served as fresh, no read
    assert '<h2 class="seclabel">Trending</h2>' in main_of(fresh.text) and "Trend Film" in fresh.text
    md.clear_cache()
    later(monkeypatch, 3 * 3600)
    with client:
        old = client.get("/media/discover")
    assert '<h2 class="seclabel">Trending · 3h ago</h2>' in main_of(old.text)
    assert "Discover unavailable" not in old.text


def test_nothing_stored_and_failing_says_unavailable_without_waiting_again(env):
    client, fake = env()
    fake.fail = True
    with client:
        first = client.get("/media/discover")
        n = len(fake.gets)
        second = client.get("/media/discover")
    assert main_of(first.text).count("Discover unavailable") == 5
    assert main_of(second.text).count("Discover unavailable") == 5 and len(fake.gets) == n


def test_the_provider_list_falls_back_to_the_last_one_kept(env, monkeypatch):
    client, fake = env()
    wire(fake)
    with client:
        good, _ = tiles(client.get("/media/discover").text)
    md.clear_cache()                                  # the services match is rebuilt from the provider list
    later(monkeypatch, md.PROVIDER_TTL + 60)

    def boom(url, headers=None, timeout=None, **kw):
        fake.gets.append(url.split(":5055", 1)[1])
        raise requests.ConnectionError(url)
    md.requests.get = boom
    with client:
        stale, _ = tiles(client.get("/media/discover").text)
        n = len(fake.gets)
        client.get("/media/discover")
    assert stale == good and len(good) == 10
    assert not [g for g in fake.gets[n:] if "watchproviders" in g]   # remembered: not re-asked inside the minute


def test_a_service_page_serves_its_last_rows_with_their_age(env, monkeypatch):
    client, fake = env()
    wire(fake)
    with client:
        client.get("/media/discover/service/8")
        later(monkeypatch, md.SERVICE_TTL + 3600)

        def boom(url, headers=None, timeout=None, **kw):
            if "watchProviders=" in url:
                raise requests.ConnectionError(url)
            return fake.get(url, headers=headers, timeout=timeout, **kw)
        md.requests.get = boom
        r = client.get("/media/discover/service/8")
    body = main_of(r.text)
    assert r.status_code == 200 and "Service Film A" in body and "Unavailable" not in body
    assert ">Popular films · 7h ago</div>" in body


def test_failure_logs_name_the_type_only(env, monkeypatch, caplog):
    client, fake = env()
    fake.fail = True
    with caplog.at_level(logging.WARNING, logger="hub.media_discover"), client:
        client.get("/media/discover")
    assert "jellyseerr read failed: ConnectionError" in caplog.text
    assert "secret-host" not in caplog.text and FAKE_KEY not in caplog.text
