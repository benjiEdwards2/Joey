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
from tests.hub.test_media_shelves import LINK, shelf_area
from tests.hub.test_registry import make_area, write_registry
from tests.hub.test_store import write_envelope

URL = "http://jf.secret-host.invalid:8096"
KEY = "jf-SECRET-key-123"
NOW = datetime.now(timezone.utc)
YESTERDAY = (date.today() - timedelta(days=1)).isoformat() + "T00:00:00.0000000Z"
TOMORROW = (date.today() + timedelta(days=3)).isoformat() + "T00:00:00.0000000Z"
TICKS = 600_000_000
STREAMS = [{"Type": "Video", "Codec": "hevc", "Height": 2160, "Width": 3840, "VideoRangeType": "HDR10"},
           {"Type": "Audio", "Codec": "eac3", "Channels": 6, "Profile": "Dolby Digital Plus + Dolby Atmos", "IsDefault": True}]
SOURCES = [{"Container": "mkv", "Size": 20 * 1024 ** 3, "MediaStreams": STREAMS}]


def ep(i, name, played=False, pos=0, premiere=YESTERDAY, season="sea1"):
    return {"Id": f"ep{i}", "Name": name, "IndexNumber": i, "PremiereDate": premiere, "SeasonId": season,
            "UserData": {"Played": played, "PlaybackPositionTicks": pos}}


ITEMS = {
    "mov1": {"Id": "mov1", "Type": "Movie", "Name": "Harbour Lights", "ProductionYear": 2019,
             "Overview": "A ferry pilot returns home.", "Genres": ["Drama", "Thriller"], "RunTimeTicks": 112 * TICKS,
             "CommunityRating": 7.84, "OfficialRating": "M", "ProviderIds": {"Tmdb": "603"},
             "UserData": {"Played": False, "PlaybackPositionTicks": 80 * TICKS},
             "People": [{"Name": "Ada Actor", "Type": "Actor", "Role": "Pilot"}, {"Name": "Dee Director", "Type": "Director"}],
             "MediaSources": SOURCES},
    "ep3": {"Id": "ep3", "Type": "Episode", "Name": "Penny for Your Thoughts", "SeriesId": "ser1",
            "SeasonId": "sea1", "SeriesName": "Quiet Show", "ParentIndexNumber": 4, "IndexNumber": 3,
            "PremiereDate": "2026-10-12T00:00:00.0000000Z", "RunTimeTicks": 45 * TICKS, "Overview": "Coins go missing.",
            "UserData": {"Played": True, "PlaybackPositionTicks": 0}, "MediaSources": SOURCES},
    "ser1": {"Id": "ser1", "Type": "Series", "Name": "Quiet Show", "ProductionYear": 2020, "Genres": ["Comedy"],
             "ProviderIds": {"Tmdb": "100"}, "Overview": "A quiet show.", "UserData": {"Played": False}},
}
SEASONS = [{"Id": "sea1", "Name": "Season 4", "IndexNumber": 4}]
EPISODES = [ep(1, "One", True), ep(2, "Two", True), ep(3, "Three", True), ep(4, "Four", pos=5 * TICKS),
            ep(5, "Five"), ep(6, "Six", premiere=TOMORROW)]


class R:
    def __init__(self, body, status=200):
        self._b, self.status_code = body, status

    def json(self):
        return self._b


class Fake:
    def __init__(self):
        self.calls, self.fail = [], False

    def get(self, url, params=None, headers=None, timeout=None, **kw):
        assert url.startswith(URL) and headers == {"Authorization": f"MediaBrowser Token={KEY}"}
        path = url[len(URL):]
        self.calls.append((path, params))
        if self.fail:
            raise requests.ConnectionError(url)
        if path == "/Users":
            return R([{"Id": "u1", "Name": "Ben", "Policy": {"IsAdministrator": True}}])
        if path == "/System/Info/Public":
            return R({"Id": "pubsrv"})
        if path.startswith("/Users/u1/Items/"):
            it = ITEMS.get(path.rsplit("/", 1)[1])
            return R(it) if it else R({}, 404)
        if path == "/Shows/ser1/Seasons":
            return R({"Items": SEASONS})
        if path == "/Shows/ser1/Episodes":
            return R({"Items": EPISODES})
        return R({}, 404)


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


def main_of(html):
    # Restyle Phase 3: facts are joined by a dim <span class="sep"> · </span>; the pins read the words.
    return html.split("<main", 1)[1].replace('<span class="sep"> · </span>', " · ")


def current(html, label):
    nav = html.split(f'aria-label="{label}"', 1)[1].split("</nav>", 1)[0]
    return re.findall(r'aria-current="page">([^<]+?)(?:\s*<|\s*$)', nav)


def deep(jf_id, server="srv-1"):
    return f"{LINK}/web/#/details?id={jf_id}&amp;serverId={server}"


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
    assert "Drama · Thriller" in b and "1h 52m" in b and "7.8 / 10" in b and ">M<" in b
    assert f'href="{deep("mov1")}" target="_blank" rel="noopener"' in b
    assert "Resume ▶ · 32 min left" in b                       # 112 - 80 minutes
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
    assert 'href="/media/item/ser1">Quiet Show</a>' in b          # the show, beneath the episode header
    assert "S04E03 · Penny for Your Thoughts" in b and "Aired 12 Oct 2026" in b and "Coins go missing." in b
    assert "Play again ▶" in b and f'href="{deep("ep3")}"' in b
    assert "Quiet Show (2020)" in b and "A quiet show." in b        # the SHOW's page content below
    assert "3 of 6 watched" in b
    squares = {n: cls for cls, n in re.findall(r'<a class="ep([^"]*)" href="/media/item/ep(\d)"', b)}
    assert "watched" in squares["1"] and "progress" in squares["4"] and "unaired" in squares["6"]
    assert squares["5"] == "" and 'title="Six (not aired)"' in b and 'title="Four (in progress)"' in b
    assert "watched · in progress · not aired" in b
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
    assert r.status_code == 200 and "Quiet Show (2020)" in b and "TV show" in b
    assert "3 of 6 watched" in b and 'value="jf:ser1"' in b
    assert f'href="{deep("ep4")}"' in b and "Next to watch: S4 E4 ▶" in b   # in-progress episode is next
    assert "On your server · 6 episodes · 2 to watch · S4 E4 next" in b


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


def test_file_summary_for_item_reads_one_item(env):
    client, fake = env()
    with client:
        out = media_files.file_summary_for_item("mov1")
        assert media_files.file_summary_for_item("mov1") == out
    assert out["files"] == 1 and {"word": "4K", "icon": "res"} in out["video"]
    assert [p for p, _ in fake.calls].count("/Users/u1/Items/mov1") == 1


# ---- link re-pointing ----

LINKED = {
    "summary": "x", "server_id": "srv-1",
    "now_playing": [{"title": "Playing Now Title", "user": "Sam", "progress_pct": 42, "play_method": "Direct",
                     "poster": "jf:np", "backdrop": "jfb:np", "jf_id": "np1", "item_key": "jf:np1"}],
    "up_next": [{"title": "Dust and Daylight", "remaining_text": "31 min left", "poster": None, "jf_id": "resume-id",
                 "item_key": "jf:ser9", "show_key": "jf:ser9", "season_key": "jf:sea9", "episode_key": "jf:resume-id"}],
    "latest": [{"title": "Fresh Film", "type": "Movie", "item_key": "tmdb:5", "poster": None, "jf_id": "new-id",
                "added_at": NOW.isoformat()}],
    "history": {"recent": [{"title": "Quiet Show · S01E02 · B", "kind": "episode", "poster": None,
                            "when": "today", "watched_at": NOW.isoformat(), "jf_id": "e2", "item_key": "jf:ser1",
                            "show_key": "jf:ser1", "season_key": "jf:sea1", "episode_key": "jf:e2",
                            "season": 1, "episode": 2, "show_title": "Quiet Show"}]},
}


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
