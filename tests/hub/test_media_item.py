"""Item URL family of the film page (F9 -> F10): /media/item/{jf_id} from a faked Jellyfin, the Play deep link,
the episode map, the failure fallback, nav section, and the link re-pointing of every row that
carries a Jellyfin id. `requests.get` is faked; no network."""
import html as htmllib
import importlib
import re
from datetime import date, datetime, timedelta, timezone

import pytest
import requests
from fastapi.testclient import TestClient

from hub import media_db, media_files, media_item, media_plays_db
from tests.hub.helpers import (  # noqa: F401  (re-export: defined in tests/hub/helpers.py)
    deep, ep, EPISODES, JellyfinFake as Fake, ITEMS, KEY, LINK, LINKED, make_area, NOW, FakeResponse as R,
    SEASONS, shelf_area, SOURCES, STREAMS, TICKS, TOMORROW, URL, write_envelope, write_registry, YESTERDAY)
from tests.hub.conftest import main_of  # noqa: F401  (shared helper; other test modules import it from here)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("AREAS_PATH", str(write_registry(tmp_path, shelf_area(), make_area("beta"))))
    monkeypatch.setenv("MEDIA_DB_PATH", str(tmp_path / "media.db"))
    monkeypatch.setenv("SNAPSHOT_DIR", str(tmp_path / "snaps"))
    monkeypatch.setenv("PLAY_RECORDER", "off")
    monkeypatch.setenv("JELLYFIN_URL", URL)
    monkeypatch.setenv("JELLYFIN_API_KEY", KEY)
    monkeypatch.delenv("JELLYFIN_USER", raising=False)

    def build(jellyfin=None):
        write_envelope(tmp_path / "snaps", "jellyfin", age_minutes=1,
                       data=jellyfin or {"summary": "x", "server_id": "srv-1"})
        import hub.main
        importlib.reload(hub.main)
        media_files.clear_cache()
        media_item.clear_cache()
        fake = Fake()
        monkeypatch.setattr(media_files.requests, "get", fake.get)
        return TestClient(hub.main.app), fake

    return build


def current(html, label):
    nav = html.split(f'aria-label="{label}"', 1)[1].split("</nav>", 1)[0]
    return re.findall(r'aria-current="page">([^<]+?)(?:\s*<|\s*$)', nav)


def test_movie_page(env):
    client, _ = env()
    with client:
        media_db.add_manual_watch(item_key="tmdb:603", kind="movie", title="Harbour Lights", year=2019, poster=None,
                                  watched_on="2026-10-12", place=None, note=None, owner="you")
        r = client.get("/media/item/mov1")
        html = r.text
    assert r.status_code == 200
    b = main_of(html)
    assert "Harbour Lights (2019)" in b and "A ferry pilot returns home." in b
    assert "Drama · Thriller" in b and "1h 52m" in b and '<span class="sp-name">TMDB</span><b class="sp-val">7.8</b>' in b and ">M<" in b  # media-ux4 (2026-10-08, B.): one pill style
    assert f'href="{deep("mov1")}" target="_blank" rel="noopener"' in b
    assert "Resume ▶ · 32m left" in b                       # 112 - 80 minutes
    assert b.index("Resume ▶") < b.index('href="#rate"')       # Play first, then Rate
    assert 'class="ratepick"' in b and 'value="tmdb:603"' in b
    assert "Watched 1 time · 12 Oct 2026" in b
    assert "fmtbadges" in b and "<b>4K</b>" in b and "<small>HEVC</small>" in b
    assert 'class="castname">Ada Actor</span><span class="castrole">as Pilot</span>' in b
    assert 'href="/media/discover?q=Dee%20Director"' in b      # Jellyfin director, no Jellyseerr
    assert current(html, "Media sections") == ["Movies"]


def test_played_film_says_play_again_and_shows_its_rating(env):
    client, _ = env()
    ITEMS["mov1"]["UserData"] = {"Played": True, "PlaybackPositionTicks": 0}
    try:
        with client:
            media_db.set_rating("tmdb:603", 9, "movie", "Harbour Lights", year=2019)
            b = main_of(client.get("/media/item/mov1").text)
    finally:
        ITEMS["mov1"]["UserData"] = {"Played": False, "PlaybackPositionTicks": 80 * TICKS}
    assert "Play again ▶" in b and "Rated 9 out of 10" in b and "ratepick" not in b


def test_episode_page_and_map(env):
    client, fake = env()
    with client:
        r = client.get("/media/item/ep3")
        html = r.text
    b = main_of(html)
    assert r.status_code == 200
    assert 'href="/media/item/ser1#seasons"' in b          # the show: the part-of banner (media-ux4 dropped the "Episode of" line)
    assert "S04E03 · Penny for Your Thoughts" in b and "Aired 12 Oct 2026" in b and "Coins go missing." in b
    assert "Play again ▶" in b and f'href="{deep("ep3")}"' in b
    assert "Quiet Show (2020)" in b and "A quiet show." in b        # the SHOW's page content below
    assert "3 of 6 watched" in b
    # Episode list (2026-10-08, replaced the numbered squares + their legend): one whole-row link per episode with
    # its state in words; the row's class carries the state too.
    rows = {n: key for key, n in re.findall(r'<div class="row has-form epline ep-(\w+)" id="ep-ep(\d)">', b)}
    assert rows == {"1": "watched", "2": "watched", "3": "watched", "4": "progress", "5": "todo", "6": "unaired"}
    assert '<a class="rowlink" href="/media/item/ep6">' in b and ">E6 · Six</div>" in b and ">Not aired</div>" in b
    assert ">In progress</div>" in b  # EPISODES carry no runtime, so no minutes-left figure
    assert "Squares in order" not in b and "watched · in progress · not aired" not in b
    assert current(html, "Media sections") == ["TV Shows"]
    paths = [p for p, _ in fake.calls]
    assert "/Shows/ser1/Seasons" in paths and "/Shows/ser1/Episodes" in paths and "/Users/u1/Items/ser1" in paths
    ep_call = next(q for p, q in fake.calls if p == "/Shows/ser1/Episodes")
    assert ep_call["userId"] == "u1" and ep_call["seasonId"] == "sea1"


def test_episode_rating_follows_the_owners_level(env):
    client, _ = env()
    with client:
        assert 'value="jf:ser1"' in main_of(client.get("/media/item/ep3").text)       # default level: show
        media_db.set_setting("you", "rating_level", "episode")
        b = main_of(client.get("/media/item/ep3").text)
        assert 'value="jf:ep3"' in b and 'value="episode"' in b and "Quiet Show · S04E03 · Penny" in b
        media_db.set_setting("you", "rating_level", "season")
        assert 'value="jf:sea1"' in main_of(client.get("/media/item/ep3").text)


def test_series_page(env):
    client, _ = env()
    with client:
        r = client.get("/media/item/ser1")
        b = main_of(r.text)
    assert r.status_code == 200 and "Quiet Show (2020)" in b and ">TV<" in b
    assert "3 of 6 watched" in b and 'value="jf:ser1"' in b
    assert f'href="{deep("ep4")}"' in b and "Next to watch: S4 E4 ▶" in b   # in-progress episode is next
    assert "On server · 6 episodes · 2 to watch · S4 E4 next" in b


def test_bad_id_is_404(env):
    client, fake = env()
    with client:
        assert client.get("/media/item/bad%20id").status_code == 404
        assert client.get("/media/item/" + "a" * 65).status_code == 404
        assert client.get("/media/item/a.b").status_code == 404
    assert fake.calls == []


def test_upstream_failure_still_renders_with_words(env):
    client, fake = env()
    fake.fail = True
    with client:
        r = client.get("/media/item/mov1")
    b = main_of(r.text)
    assert r.status_code == 200
    assert "Couldn't reach Jellyfin — showing what Joey knows" in htmllib.unescape(b) and "Jellyfin item" in b
    assert f'href="{deep("mov1")}"' in b and ">Play ▶<" in b      # the deep link needs no upstream
    assert KEY not in r.text and "secret-host" not in r.text


def test_unknown_item_and_no_env_fall_back_too(env, monkeypatch):
    client, _ = env()
    with client:
        assert "Couldn't reach Jellyfin" in htmllib.unescape(client.get("/media/item/nope").text)
        monkeypatch.delenv("JELLYFIN_API_KEY")
        media_item.clear_cache()
        assert client.get("/media/item/mov1").status_code == 200


def test_second_view_is_a_cache_hit(env):
    client, fake = env()
    with client:
        client.get("/media/item/ser1")
        n = len(fake.calls)
        client.get("/media/item/ser1")
        assert len(fake.calls) == n
        media_item.clear_cache()
        client.get("/media/item/ser1")
        assert len(fake.calls) > n


def test_server_id_falls_back_to_the_public_info_once(env):
    client, fake = env(jellyfin={"summary": "x"})
    with client:
        b = main_of(client.get("/media/item/mov1").text)
        client.get("/media/item/ser1")
    assert f'href="{deep("mov1", "pubsrv")}"' in b
    assert [p for p, _ in fake.calls].count("/System/Info/Public") == 1


def test_no_url_or_key_in_the_page(env):
    client, _ = env()
    with client:
        for jf in ("mov1", "ep3", "ser1"):
            html = client.get(f"/media/item/{jf}").text
            assert KEY not in html and "secret-host" not in html


# ---- link re-pointing ----


def test_playing_diary_history_rows_link_to_item_pages(env):
    client, _ = env(jellyfin=LINKED)
    with client:
        playing = main_of(client.get("/media/playing").text)
        assert 'href="/media/item/np1"' in playing and 'href="/media/item/resume-id"' in playing
        assert 'href="/media/item/new-id"' in playing and "/web/#/details" not in playing
        diary = main_of(client.get("/media/diary").text)
        assert '<a class="rowlink" href="/media/item/ser1">' in diary  # whole-row overlay (2026-10-06)
        hist = main_of(client.get("/media/history").text)
        assert 'href="/media/item/e2"' in hist and "/web/#/details" not in hist


def test_server_history_top_rows_link_to_item_pages(env):
    client, _ = env()
    now = NOW
    for jf, kind, title, show, key in (("e1", "episode", "Pilot", "Quiet", "jf:ser1"), ("m1", "movie", "Long Road", None, "tmdb:1")):
        for pos in (1, 100):
            media_plays_db.record_sighting({
                "user_name": "u", "owner": "you", "jf_id": jf, "item_key": key, "show_key": "jf:ser1" if show else None,
                "title": title, "show_title": show, "kind": kind, "runtime_min": 30, "position_pct": pos, "poster": None},
                now - timedelta(minutes=30 if pos == 1 else 0))
    with client:
        body = main_of(client.get("/media/server/history?w=all").text)
    assert 'href="/media/item/ser1">' in body and 'href="/media/item/m1">' in body  # whole-row links (2026-10-06)


def test_rows_without_a_jellyfin_id_are_unchanged(env):
    client, _ = env(jellyfin={**LINKED, "latest": [{"title": "No Id", "type": "Movie", "item_key": "tmdb:5",
                                                    "poster": None, "added_at": NOW.isoformat()}]})
    with client:
        playing = main_of(client.get("/media/playing").text)
    assert "No Id" in playing and 'href="/media/item/None"' not in playing
    assert media_item.ITEM_RE.match("abc-123") and not media_item.ITEM_RE.match("jf:1")
