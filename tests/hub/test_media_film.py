"""The film page (F10): one Cinema-layout page for every title. Jellyfin and Jellyseerr are both faked at
`requests.get`; no network. The Jellyfin side reuses the fixtures of test_media_item."""
import html as htmllib
import importlib
import re
from datetime import date

import pytest
import requests
from fastapi.testclient import TestClient

from hub import media_db, media_discover, media_files, media_film, media_item
from tests.hub.test_media_item import ITEMS, KEY, SOURCES, STREAMS, URL, Fake as JFFake, R, deep
from tests.hub.test_media_shelves import shelf_area
from tests.hub.test_registry import make_area, make_tile, write_registry
from tests.hub.test_store import write_envelope

SEERR = "http://seerr.secret-host.invalid:5055"
SKEY = "k-SECRET-0123456789"
YEAR = date.today().year
HX = {"HX-Request": "true"}

LIB_MOVIES = [{"item_key": "tmdb:603", "jf_id": "mov1", "title": "Harbour Lights", "year": 2019},
              {"item_key": "tmdb:604", "jf_id": "mov2", "title": "Harbour Lights 2", "year": 2022}]
LIB_SHOWS = [{"item_key": "tmdb:100", "jf_id": "ser1", "title": "Quiet Show", "year": 2020}]


def prow(i, title, status=None):
    r = {"id": i, "title": title, "releaseDate": "2020-01-01", "posterPath": f"/p{i}.jpg", "mediaType": "movie"}
    if status:
        r["mediaInfo"] = {"status": status}
    return r


FILM = {"id": 603, "title": "Harbour Lights", "releaseDate": "2019-05-05", "tagline": "Come home", "runtime": 112,
        "overview": "A ferry pilot returns home.", "voteAverage": 7.4, "posterPath": "/hl.jpg", "backdropPath": "/hlb.jpg",
        "genres": [{"name": "Drama"}], "mediaInfo": {"status": 5},
        "credits": {"cast": [{"name": "Ada Actor", "character": "Pilot", "profilePath": "/ada.jpg"},
                             {"name": "Bo Bit", "character": "Deckhand"}],
                    "crew": [{"name": "Dee Director", "job": "Director"}, {"name": "Cy Camera", "job": "Cinematographer"}]},
        "collection": {"id": 9, "name": "Harbour Collection"},
        "watchProviders": [{"iso_3166_1": "AU", "flatrate": [{"name": "Netflix"}], "rent": [{"name": "Apple TV"}]},
                           {"iso_3166_1": "US", "flatrate": [{"name": "USOnly"}]}],
        "relatedVideos": [{"url": "https://www.youtube.com/watch?v=seerr1", "site": "YouTube", "type": "Trailer"}],
        "releases": {"results": [{"iso_3166_1": "AU", "release_dates": [
            {"type": 3, "release_date": "2019-05-05T00:00:00.000Z"}, {"type": 4, "release_date": "2019-08-01T00:00:00.000Z"}]}]}}
PLAIN = {"id": 701, "title": "Plain Film", "releaseDate": "2024-01-01", "posterPath": "/pf.jpg", "backdropPath": "/pfb.jpg",
         "overview": "Nothing yet.", "mediaInfo": {"status": 1}}
SHOW = {"id": 100, "name": "Quiet Show", "firstAirDate": "2020-01-01", "numberOfSeasons": 1, "numberOfEpisodes": 6,
        "posterPath": "/qs.jpg", "createdBy": [{"name": "Cass Creator"}], "mediaInfo": {"status": 5},
        "seasons": [{"seasonNumber": 4, "name": "Season 4", "episodeCount": 6, "airDate": "2020-01-01"}]}


class Seerr:
    def __init__(self):
        self.table = {
            "/api/v1/movie/603": FILM, "/api/v1/movie/701": PLAIN, "/api/v1/tv/100": SHOW,
            "/api/v1/movie/603/ratingscombined": {"rt": {"criticsScore": 92}, "imdb": {"criticsScore": 7.9}},
            "/api/v1/movie/603/similar": {"results": [prow(11, "Similar One", 5), prow(12, "Similar Two")]},
            "/api/v1/movie/603/recommendations": {"results": [prow(13, "Rec One")]},
            "/api/v1/collection/9": {"parts": [prow(603, "Harbour Lights", 5), prow(604, "Harbour Lights 2"), prow(605, "Harbour Lights 3")]}}
        self.post_status = 201
        self.posts = []

    def get(self, path):
        return R(self.table[path]) if path in self.table else R({}, 404)


class Both:
    """requests.get / post for both services."""

    def __init__(self):
        self.jf, self.seerr, self.fail_jf, self.fail_seerr, self.calls = JFFake(), Seerr(), False, False, []

    def get(self, url, params=None, headers=None, timeout=None, **kw):
        self.calls.append(url)
        if url.startswith(URL):
            self.jf.fail = self.fail_jf
            return self.jf.get(url, params=params, headers=headers, timeout=timeout)
        assert url.startswith(SEERR) and headers == {"X-Api-Key": SKEY}
        if self.fail_seerr:
            raise requests.ConnectionError(url)
        return self.seerr.get(url[len(SEERR):])

    def post(self, url, json=None, headers=None, timeout=None, **kw):
        self.seerr.posts.append((url, json))
        return R({}, self.seerr.post_status)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    area = shelf_area()
    area["tiles"].append(make_tile("disc-t", snapshot="jellyseerr", stale_after_minutes=180, detail="/media/discover"))
    monkeypatch.setenv("AREAS_PATH", str(write_registry(tmp_path, area, make_area("beta"))))
    monkeypatch.setenv("MEDIA_DB_PATH", str(tmp_path / "media.db"))
    monkeypatch.setenv("SNAPSHOT_DIR", str(tmp_path / "snaps"))
    monkeypatch.setenv("PLAY_RECORDER", "off")
    for k, v in (("JELLYFIN_URL", URL), ("JELLYFIN_API_KEY", KEY), ("JELLYSEERR_URL", SEERR), ("JELLYSEERR_API_KEY", SKEY)):
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("JELLYFIN_USER", raising=False)
    monkeypatch.setattr(media_film, "BADGES_DIR", tmp_path / "badges")

    def build(arr=None, seerr_snap=None, jelly_extra=None):
        snaps = tmp_path / "snaps"
        write_envelope(snaps, "jellyfin", age_minutes=1,
                       data={"summary": "x", "server_id": "srv-1", "movies": LIB_MOVIES, "shows": LIB_SHOWS, **(jelly_extra or {})})
        write_envelope(snaps, "arr", age_minutes=1, data={"summary": "x", **(arr or {})})
        write_envelope(snaps, "jellyseerr", age_minutes=1, data={"summary": "x", "requests": seerr_snap or []})
        import hub.main
        importlib.reload(hub.main)
        for clear in (media_files.clear_cache, media_item.clear_cache, media_discover.clear_cache):
            clear()
        both = Both()
        monkeypatch.setattr(requests, "get", both.get)
        monkeypatch.setattr(requests, "post", both.post)
        return TestClient(hub.main.app), both

    return build


def main_of(html):
    return html.split("<main", 1)[1]


def status(html):
    return htmllib.unescape(re.search(r'id="status-line">([^<]*)<', html).group(1))


def set_ud(monkeypatch, item="mov1", **ud):
    monkeypatch.setitem(ITEMS[item], "UserData", {"Played": False, "PlaybackPositionTicks": 0, **ud})


# ---- status line ----

def test_status_on_server_watched_and_rated(env, monkeypatch):
    set_ud(monkeypatch, Played=True)
    client, _ = env()
    with client:
        media_db.add_manual_watch(item_key="tmdb:603", kind="movie", title="Harbour Lights", year=2019, poster=None,
                                  watched_on=f"{YEAR}-10-12", place=None, note=None, owner="you")
        media_db.set_rating("tmdb:603", 9, "movie", "Harbour Lights", year=2019)
        html = client.get("/media/item/mov1").text
    assert status(html) == "On your server · 4K · HDR10 · watched 12 Oct · you rated 9"


def test_status_on_server_unwatched(env, monkeypatch):
    set_ud(monkeypatch)
    client, _ = env()
    with client:
        html = client.get("/media/title/movie/603").text
    assert status(html) == "On your server · 4K · HDR10 · not watched yet"


def test_status_not_on_server_requested_processing_and_downloading(env):
    client, both = env(seerr_snap=[{"tmdb_id": 701, "requested_by": "Sam", "when": "3 hours ago", "status_text": "Approved"}],
                       arr={"downloading": [{"title": "Plain Film", "kind": "movie", "pct": 42, "status_text": "Downloading",
                                             "time_left": "", "item_key": "tmdb:701"}]})
    both.seerr.table["/api/v1/movie/701"] = {**PLAIN, "mediaInfo": {"status": 3}}
    with client:
        html = client.get("/media/title/movie/701").text
    assert status(html) == "Not on your server · Requested 3 hours ago · Processing · downloading 42 %"
    assert "Requested 3 hours ago by Sam" in html


def test_status_plain_not_on_server(env):
    client, _ = env()
    with client:
        assert status(client.get("/media/title/movie/701").text) == "Not on your server"


def test_status_series(env):
    client, _ = env()
    with client:
        assert status(client.get("/media/title/tv/100").text) == "On your server · 6 episodes · 2 to watch · S4 E4 next"


# ---- numbers strip ----

def test_numbers_with_imdb_and_rt(env, monkeypatch):
    set_ud(monkeypatch, PlaybackPositionTicks=80 * 600_000_000)
    client, _ = env()
    with client:
        media_db.set_rating("tmdb:603", 10, "movie", "Harbour Lights", year=2019)
        b = main_of(client.get("/media/title/movie/603").text)
    assert "7.8 / 10" in b and "IMDb 7.9" in b and "RT 92 %" in b and "1 h 52 m" in b
    assert re.search(r"ends \d\d:\d\d if you start now", b) and ">M<" in b
    assert 'class="chip score score-10"' in b                      # gold at 10 (the number is there too)


def test_numbers_without_ratings_endpoint_and_picker_when_unrated(env):
    client, both = env()
    del both.seerr.table["/api/v1/movie/603/ratingscombined"]
    with client:
        b = main_of(client.get("/media/title/movie/603").text)
    assert "IMDb" not in b.split('class="filmbody"')[0] and "RT " not in b.split('class="filmbody"')[0]
    assert 'class="ratebox ratepick"' in b and 'value="tmdb:603"' in b and 'href="#rate"' in b


def test_ratings_flat_rt_shape():
    assert media_film.parse_ratings({"criticsScore": 88}) == {"rt": "88 %"}
    assert media_film.parse_ratings({"imdb": {"criticsScore": 6.04}}) == {"imdb": "6.0"}
    assert media_film.parse_ratings(None) == {}


def test_community_falls_back_to_tmdb_vote_when_not_on_server(env):
    client, both = env()
    both.seerr.table["/api/v1/movie/701"] = {**PLAIN, "voteAverage": 6.51}
    with client:
        assert "6.5 / 10" in main_of(client.get("/media/title/movie/701").text)


# ---- button row ----

def test_buttons_resume_play_again_next_and_none(env, monkeypatch):
    client, _ = env()
    with client:
        set_ud(monkeypatch, PlaybackPositionTicks=80 * 600_000_000)
        b = main_of(client.get("/media/title/movie/603").text)
        assert "Resume ▶ · 32 min left" in b and f'href="{deep("mov1")}"' in b
        assert b.index("Resume ▶") < b.index('href="#rate"')
        media_item.clear_cache()
        set_ud(monkeypatch, Played=True)
        assert "Play again ▶" in main_of(client.get("/media/title/movie/603").text)
        s = main_of(client.get("/media/title/tv/100").text)
        assert "Next to watch: S4 E4 ▶" in s and f'href="{deep("ep4")}"' in s
        none = main_of(client.get("/media/title/movie/701").text)
    assert "playbtn" not in none and "▶" not in none


def test_request_button_only_when_not_available(env):
    client, _ = env()
    with client:
        assert 'id="request-block"' not in client.get("/media/title/movie/603").text
        b = main_of(client.get("/media/title/movie/701").text)
    assert 'id="request-block"' in b and 'hx-get="/media/title/movie/701/request?step=confirm"' in b
    assert "Open in Jellyseerr ↗" in b and f'href="{SEERR}/movie/701"' in b


def test_trailer_jellyfin_then_jellyseerr_then_none(env, monkeypatch):
    client, both = env()
    with client:
        b = main_of(client.get("/media/title/movie/603").text)
        assert 'href="https://www.youtube.com/watch?v=seerr1" target="_blank" rel="noopener">Trailer ↗' in b
        monkeypatch.setitem(ITEMS["mov1"], "RemoteTrailers", [{"Url": "https://www.youtube.com/watch?v=jf1"}])
        media_item.clear_cache()
        b = main_of(client.get("/media/title/movie/603").text)
        assert 'watch?v=jf1" target="_blank"' in b and "seerr1" not in b and "<iframe" not in b
        assert "Trailer" not in main_of(client.get("/media/title/movie/701").text)


# ---- quality pills ----

def test_dolby_style_pills_and_hdr_pill(env):
    client, _ = env()
    with client:
        html = client.get("/media/title/movie/603").text
    strip = html.split('class="filestrip"', 1)[1].split("</div>", 1)[0]
    assert strip.count('class="pill dolby"') == 2 and strip.count('<svg class="dd"') == 2
    assert "<span>Dolby Digital Plus</span>" in strip and "<span>Dolby Atmos</span>" in strip
    assert '<span class="pill hdr"><span>HDR10</span></span>' in strip
    assert "<span>4K</span>" in strip and '<span class="pill">' in strip      # plain pills stay plain


def test_badge_pill_mapping():
    for word, id_, tone in (("DTS-HD", "dts-hd", "dts"), ("DTS", "dts", "dts"), ("HDR10+", "hdr10plus", "hdr"),
                            ("HLG", "hlg", "hdr"), ("Dolby Vision", "dolby-vision", "dolby"), ("TrueHD", "dolby-truehd", "dolby"),
                            ("Dolby Digital", "dolby-digital", "dolby")):
        p = media_files.badge_pill(word)
        assert (p["id"], p["tone"]) == (id_, tone), word
    assert media_files.badge_pill("1080p")["tone"] == "plain" and media_files.badge_pill("1080p")["id"] is None
    assert media_files.badge_pill("Atmos")["label"] == "Dolby Atmos"


def test_override_image_replaces_the_pill(env, tmp_path):
    badges = tmp_path / "badges"
    badges.mkdir()
    (badges / "dolby-atmos.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>", encoding="utf-8")
    client, _ = env()
    with client:
        html = client.get("/media/title/movie/603").text
    strip = html.split('class="filestrip"', 1)[1].split("</div>", 1)[0]
    assert '<img class="pillimg" src="/static/badges/dolby-atmos.svg" alt="Dolby Atmos"' in strip
    assert "<span>Dolby Atmos</span>" not in strip and strip.count('class="pill dolby"') == 1


def test_badges_folder_ships_readme_only():
    from pathlib import Path
    folder = Path(media_film.__file__).resolve().parent / "static" / "badges"
    assert [p.name for p in folder.iterdir()] == ["README.md"]


# ---- people, providers, facts, shelves ----

def test_cast_portraits_initials_makers_and_providers(env):
    client, _ = env()
    with client:
        b = main_of(client.get("/media/title/movie/603").text)
    assert '<img class="castpic" src="/img/tmdb:/ada.jpg?h=120"' in b
    assert 'class="castpic initials" aria-hidden="true">B' in b and ">Bo Bit<" in b and "Deckhand" in b
    assert 'href="/media/discover?q=Dee%20Director"' in b and "Cy Camera" not in b
    assert ">Netflix</a>" in b and ">Apple TV</a>" in b and "USOnly" not in b
    assert 'href="https://www.justwatch.com/au/search?q=Harbour%20Lights"' in b
    assert "Come home" in b and "A ferry pilot returns home." in b


def test_series_makers_are_creators(env):
    client, _ = env()
    with client:
        b = main_of(client.get("/media/title/tv/100").text)
    assert "<h3>Creators</h3>" in b and "Cass Creator" in b


def test_facts_languages_release_dates_added_and_watched(env, monkeypatch):
    streams = STREAMS[:1] + [{"Type": "Audio", "Codec": "eac3", "Channels": 6, "IsDefault": True, "Language": "eng"},
                             {"Type": "Subtitle", "Codec": "srt", "Language": "fre"}]
    monkeypatch.setitem(ITEMS["mov1"], "MediaSources", [{**SOURCES[0], "MediaStreams": streams}])
    monkeypatch.setitem(ITEMS["mov1"], "DateCreated", "2026-03-02T10:00:00.0000000Z")
    client, _ = env()
    with client:
        media_db.add_manual_watch(item_key="tmdb:603", kind="movie", title="Harbour Lights", year=2019, poster=None,
                                  watched_on="2025-10-12", place=None, note=None, owner="you")
        b = main_of(client.get("/media/title/movie/603").text)
    assert "Audio English · Subtitles French" in b
    assert "<dt>Cinema</dt><dd>5 May 2019</dd>" in b and "<dt>Digital</dt><dd>1 Aug 2019</dd>" in b
    assert "Added to your server 2 Mar 2026" in b and "Watched 1 time · 12 Oct 2025" in b


def test_arr_calendar_tops_up_release_dates_and_next_episode(env):
    client, both = env(arr={"this_week": [
        {"title": "Plain Film", "kind": "movie", "date": "2026-11-03", "label": "Disc", "item_key": "tmdb:701"},
        {"title": "Quiet Show · S05E01 · Back", "kind": "episode", "date": "2026-11-04", "label": "Premiere", "item_key": "tvdb:1"}]})
    with client:
        assert "<dt>Disc</dt><dd>3 Nov 2026</dd>" in main_of(client.get("/media/title/movie/701").text)
        assert "Next episode S05E01 airs 4 Nov 2026" in main_of(client.get("/media/title/tv/100").text)


def test_shelves_mark_server_status(env):
    client, _ = env()
    with client:
        b = main_of(client.get("/media/title/movie/603").text)
    col = b.split("<h3>Harbour Collection</h3>", 1)[1].split("</section>", 1)[0]
    assert "Harbour Lights 2" in col and col.count(">On server<") == 2 and col.count(">Not on server<") == 1
    sim = b.split("<h3>Similar</h3>", 1)[1].split("</section>", 1)[0]
    assert 'href="/media/title/movie/11"' in sim and sim.count(">On server<") == 1 and sim.count(">Not on server<") == 1
    assert "<h3>Recommended</h3>" in b and "Rec One" in b and "?h=240" in b


def test_not_on_server_series_keeps_lazy_season_hooks(env):
    client, both = env()
    both.seerr.table["/api/v1/tv/200"] = {**SHOW, "id": 200, "mediaInfo": {"status": 1}}
    with client:
        b = main_of(client.get("/media/title/tv/200").text)
    assert 'hx-get="/media/title/tv/200/season/4" hx-trigger="toggle once"' in b


# ---- one page, two URL families ----

def test_both_url_families_render_the_same_title(env):
    client, _ = env()
    with client:
        a = client.get("/media/title/movie/603").text
        b = client.get("/media/item/mov1").text
    assert "Harbour Lights (2019)" in a and "Harbour Lights (2019)" in b and status(a) == status(b)
    assert f'href="{deep("mov1")}"' in a and f'href="{deep("mov1")}"' in b
    assert 'aria-current="page">Movies' in a and 'aria-current="page">Movies' in b


def test_episode_route_shows_episode_header_over_show_page(env):
    client, _ = env()
    with client:
        b = main_of(client.get("/media/item/ep3").text)
    assert b.index("S04E03 · Penny for Your Thoughts") < b.index("Quiet Show (2020)")
    assert "Aired 12 Oct 2026" in b and "Coins go missing." in b and "Episode of <a" in b
    assert "Cass Creator" in b and 'aria-current="page">TV Shows' in b


# ---- failure and safety ----

def test_everything_failing_still_200_with_words(env):
    client, both = env()
    both.fail_jf = both.fail_seerr = True
    with client:
        plain = client.get("/media/title/movie/701")
        listed = client.get("/media/title/movie/603")        # on the library snapshot, but nothing reachable
        item = client.get("/media/item/mov1")
    assert plain.status_code == 200 and status(plain.text) == "Not on your server"
    assert "Title unavailable" in plain.text
    assert listed.status_code == 200 and status(listed.text) == media_item.DOWN_TEXT
    assert item.status_code == 200 and status(item.text) == media_item.DOWN_TEXT and f'href="{deep("mov1")}"' in item.text
    for r in (plain, listed, item):
        assert KEY not in r.text and SKEY not in r.text and "secret-host" not in r.text


def test_not_connected_makes_no_call(env, monkeypatch):
    client, both = env()
    monkeypatch.delenv("JELLYSEERR_API_KEY")
    both.calls.clear()
    with client:
        r = client.get("/media/title/movie/701")
    assert r.status_code == 200 and "Not connected" in r.text and both.calls == []


def test_partial_failure_degrades_sections_only(env):
    client, both = env()
    for k in list(both.seerr.table):
        if k.endswith(("similar", "recommendations", "ratingscombined")) or "collection" in k:
            del both.seerr.table[k]
    with client:
        r = client.get("/media/title/movie/603")
    b = main_of(r.text)
    assert r.status_code == 200 and "Harbour Lights (2019)" in b and "<h3>Similar</h3>" not in b and "IMDb" not in b


def test_no_key_or_jellyfin_host_in_html(env):
    client, _ = env()
    with client:
        for url in ("/media/title/movie/603", "/media/title/movie/701", "/media/title/tv/100", "/media/item/mov1", "/media/item/ep3"):
            html = client.get(url).text
            assert KEY not in html and SKEY not in html and "jf.secret-host" not in html
            assert html.count("seerr.secret-host") <= 1          # only the one "Open in Jellyseerr" link


def test_cache_hit_and_request_invalidates_title(env):
    client, both = env()
    with client:
        client.get("/media/title/movie/701")
        n = len([c for c in both.calls if c.endswith("/api/v1/movie/701")])
        client.get("/media/title/movie/701")
        assert len([c for c in both.calls if c.endswith("/api/v1/movie/701")]) == n == 1
        assert client.post("/media/title/movie/701/request", headers=HX).status_code == 200
        both.seerr.table["/api/v1/movie/701"] = {**PLAIN, "mediaInfo": {"status": 3}}
        assert "Processing" in status(client.get("/media/title/movie/701").text)


def test_watchlist_and_request_flows_on_the_page(env):
    client, both = env()
    with client:
        b = main_of(client.get("/media/title/movie/701").text)
        assert 'hx-post="/media/watchlist/add"' in b and "+ Watchlist" in b
        client.post("/media/watchlist/add", content="tmdb_id=701&kind=movie&title=Plain+Film",
                    headers={"content-type": "application/x-www-form-urlencoded"})
        assert "On your watchlist" in main_of(client.get("/media/title/movie/701").text)
        confirm = client.get("/media/title/movie/701?step=confirm")
        assert "Confirm request" in confirm.text
        done = client.get("/media/title/movie/701?requested=1")
    assert "Requested ✓" in done.text
    assert "playbtn" not in main_of(done.text)               # no Play link for a title that is not on the server
