"""The film page (F10): one Cinema-layout page for every title. Jellyfin and Jellyseerr are both faked at
`requests.get`; no network. The Jellyfin side reuses the fixtures of test_media_item."""
import html as htmllib
import importlib
import re
from datetime import date
from pathlib import Path

import pytest
import requests
from fastapi.testclient import TestClient

from hub import media_db, media_discover, media_files, media_film, media_item
from tests.hub.film_page import whole
from tests.hub.conftest import main_of  # noqa: F401
from tests.hub.helpers import (  # noqa: F401
    Both, deep, env, FILM, ITEMS, JellyfinFake as JFFake, KEY, LIB_MOVIES, LIB_SHOWS, make_area, make_tile,
    PLAIN, prow, FakeResponse as R, SEERR_URL as SEERR, Seerr, shelf_area, SHOW, SKEY, SOURCES, STREAMS, URL,
    write_envelope, write_registry)


YEAR = date.today().year
HX = {"HX-Request": "true"}


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
    assert status(html) == "On server · 4K · HDR10 · watched 12 Oct · you rated 9"


def test_status_on_server_unwatched(env, monkeypatch):
    set_ud(monkeypatch)
    client, _ = env()
    with client:
        html = client.get("/media/title/movie/603").text
    assert status(html) == "On server · 4K · HDR10 · not watched yet"


def test_status_not_on_server_requested_processing_and_downloading(env):
    client, both = env(seerr_snap=[{"tmdb_id": 701, "requested_by": "Sam", "when": "3 hours ago", "status_text": "Approved"}],
                       arr={"downloading": [{"title": "Plain Film", "kind": "movie", "pct": 42, "status_text": "Downloading",
                                             "time_left": "", "item_key": "tmdb:701"}]})
    both.seerr.table["/api/v1/movie/701"] = {**PLAIN, "mediaInfo": {"status": 3}}
    with client:
        html = client.get("/media/title/movie/701").text
    assert status(html) == "Not on server · Requested 3 hours ago · Processing · Downloading · 42%"
    assert "<dt>Requested</dt><dd>3 hours ago · Sam</dd>" in html            # U6 (2026-10-13): no verb repeating its label


def test_status_plain_not_on_server(env):
    client, _ = env()
    with client:
        assert status(client.get("/media/title/movie/701").text) == "Not on server"


def test_status_series(env):
    client, _ = env()
    with client:
        assert status(client.get("/media/title/tv/100").text) == "On server · 6 episodes · 2 left · S4 E4 next"   # E6 (2026-10-13): the progress words, as My shows (E5)


# ---- numbers strip ----

def test_numbers_with_imdb_and_rt(env, monkeypatch):
    set_ud(monkeypatch, PlaybackPositionTicks=80 * 600_000_000)
    client, _ = env()
    with client:
        media_db.set_rating("tmdb:603", 10, "movie", "Harbour Lights", year=2019)
        b = main_of(whole(client, "/media/title/movie/603"))
    # Restyle Phase 3: the numbers are a stats strip (micro label over a big value).
    assert 'alt="TMDB" width="16" height="16"><b class="sp-val">7.8</b>' in b and 'alt="IMDb" width="16" height="16"><b class="sp-val">7.9</b>' in b  # media-ux4 (2026-10-08, B.): one pill style
    assert 'alt="Rotten Tomatoes" width="16" height="16"><b class="sp-val">92%</b>' in b
    assert "1h 52m" in b and re.search(r"ends \d\d:\d\d if you start now", b) and ">M<" in b
    assert 'score-9" title="Your rating: 10 out of 10">10<' in b and "gold-glow" not in b and "gold-text-glow" not in b


def test_numbers_without_ratings_endpoint_and_picker_when_unrated(env):
    client, both = env()
    del both.seerr.table["/api/v1/movie/603/ratingscombined"]
    with client:
        b = main_of(client.get("/media/title/movie/603").text)
    assert "sp-imdb" not in b and "sp-rt" not in b     # no pill without its source (media-ux4: pills, not stats)
    assert 'class="ratepick"' in b and 'value="tmdb:603"' in b and 'href="#rate"' in b


def test_ratings_flat_rt_shape():
    assert media_film.parse_ratings({"criticsScore": 88}) == {"rt": "88%"}   # media-ux4: one format, no space
    assert media_film.parse_ratings({"imdb": {"criticsScore": 6.04}}) == {"imdb": "6.0"}
    assert media_film.parse_ratings(None) == {}


def test_community_falls_back_to_tmdb_vote_when_not_on_server(env):
    client, both = env()
    both.seerr.table["/api/v1/movie/701"] = {**PLAIN, "voteAverage": 6.51}
    with client:
        assert 'alt="TMDB" width="16" height="16"><b class="sp-val">6.5</b>' in main_of(client.get("/media/title/movie/701").text)  # media-ux4 (2026-10-08, B.): one pill style


# ---- button row ----

def test_buttons_resume_play_again_next_and_none(env, monkeypatch):
    client, _ = env()
    with client:
        set_ud(monkeypatch, PlaybackPositionTicks=80 * 600_000_000)
        b = main_of(client.get("/media/title/movie/603").text)
        assert "Resume ▶ · 32m left" in b and f'href="{deep("mov1")}"' in b
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
    assert 'aria-label="Open in Seerr"' in b and f'href="{SEERR}/movie/701"' in b


def test_trailer_jellyfin_then_jellyseerr_then_none(env, monkeypatch):
    client, both = env()
    with client:
        b = main_of(whole(client, "/media/title/movie/603"))
        assert 'href="https://www.youtube.com/watch?v=seerr1" target="_blank" rel="noopener">' in b and ">Trailer</a>" in b   # media-ux4: a word button
        monkeypatch.setitem(ITEMS["mov1"], "RemoteTrailers", [{"Url": "https://www.youtube.com/watch?v=jf1"}])
        media_item.clear_cache()
        b = main_of(whole(client, "/media/title/movie/603"))
        assert 'watch?v=jf1" target="_blank"' in b and "seerr1" not in b and "<iframe" not in b
        assert "Trailer" not in main_of(whole(client, "/media/title/movie/701"))


# ---- format badges (film-quality: text badges, bold word over a sub-label; no brand glyphs) ----

def test_format_badges_are_text_with_sub_labels(env):
    client, _ = env()
    with client:
        html = client.get("/media/title/movie/603").text
    strip = html.split('class="fmtbadges"', 1)[1].split("</div>", 1)[0]
    assert '<b>4K</b><small>ULTRA HD</small>' in strip and '<b>H.265</b><small>HEVC</small>' in strip
    assert '<b>HDR10</b></span>' in strip and '<b>5.1</b><small>SURROUND</small>' in strip
    assert 'title="Dolby Digital Plus"><b>DD+</b><small>DOLBY</small>' in strip
    assert 'title="Dolby Atmos"><b>Atmos</b><small>DOLBY</small>' in strip
    assert "<svg" not in strip and "MKV" not in strip                      # no glyphs; container is in Release


def test_badge_pill_mapping():
    for word, id_ in (("DTS-HD", "dts-hd"), ("DTS", "dts"), ("HDR10+", "hdr10plus"), ("HLG", "hlg"),
                      ("Dolby Vision", "dolby-vision"), ("TrueHD", "dolby-truehd"), ("Dolby Digital", "dolby-digital")):
        assert media_files.badge_pill(word)["id"] == id_, word
    assert media_files.badge_pill("1080p") == {"id": None, "label": "1080p"}
    assert media_files.badge_pill("Atmos")["label"] == "Dolby Atmos"


def test_override_image_replaces_the_pill(env, tmp_path):
    badges = tmp_path / "badges"
    badges.mkdir()
    (badges / "dolby-atmos.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>", encoding="utf-8")
    client, _ = env()
    with client:
        html = client.get("/media/title/movie/603").text
    strip = html.split('class="fmtbadges"', 1)[1].split("</div>", 1)[0]
    assert '<img class="fmtimg" src="/static/badges/dolby-atmos.svg" alt="Dolby Atmos"' in strip
    assert "<b>Atmos</b>" not in strip and "<b>DD+</b>" in strip


def test_badges_folder_ships_readme_only():
    from pathlib import Path
    folder = Path(media_film.__file__).resolve().parent / "static" / "badges"
    assert [p.name for p in folder.iterdir()] == ["README.md"]


# ---- people, providers, facts, shelves ----

def test_cast_portraits_initials_makers_and_providers(env):
    client, _ = env()
    with client:
        b = main_of(whole(client, "/media/title/movie/603"))
    assert f'<img class="castpic" src="/img/tmdb:/ada.jpg?h={media_film.CAST_H}"' in b
    assert 'class="castpic initials" aria-hidden="true">B' in b and ">Bo Bit<" in b and "as Deckhand" in b
    assert 'href="/media/person/find?name=Dee%20Director"' in b
    assert "<dt>Cinematography</dt>" in b and "Cy Camera" in b              # crew grid (film-quality)
    # JY-280 P2 (2026-11-03) + JY-286: a film's where-to-watch is the streaming logos only (alt = the name), under the hero's buttons
    assert 'alt="Netflix"' in b and ">Netflix<" not in b and "Apple TV" not in b and "USOnly" not in b
    assert 'href="https://www.justwatch.com/au/search?q=Harbour%20Lights"' in b
    assert "A ferry pilot returns home." in b
    # F2: the tagline is drawn inline only - it is there once the title body is cached (the next open, or a prefetch)
    assert "Come home" not in b and "Come home" in main_of(client.get("/media/title/movie/603").text)


def test_series_makers_are_creators(env):
    client, _ = env()
    with client:
        b = main_of(whole(client, "/media/title/tv/100"))   # F2: makers is a deferred part (was a timing flake)
    # JY-317 (B. 2026-11-06, "Stop placing them in circles"): a show's creators are the film's chips, not headshot cards
    assert '<a class="chip makerchip" href="/media/person/' in b and '<span class="makerchip-role">Creator</span>Cass Creator</a>' in b
    assert '<div class="microlabel">Created by</div>' not in b and "makercard" not in b


def test_facts_languages_release_dates_added_and_watched(env, monkeypatch):
    streams = STREAMS[:1] + [{"Type": "Audio", "Codec": "eac3", "Channels": 6, "IsDefault": True, "Language": "eng"},
                             {"Type": "Subtitle", "Codec": "srt", "Language": "fre"}]
    monkeypatch.setitem(ITEMS["mov1"], "MediaSources", [{**SOURCES[0], "MediaStreams": streams}])
    monkeypatch.setitem(ITEMS["mov1"], "DateCreated", "2026-03-02T10:00:00.0000000Z")
    client, _ = env()
    with client:
        media_db.add_manual_watch(item_key="tmdb:603", kind="movie", title="Harbour Lights", year=2019, poster=None,
                                  watched_on="2025-10-12", place=None, note=None, owner="you")
        b = main_of(whole(client, "/media/title/movie/603"))
    assert "<dt>Audio</dt><dd>English · 1 track</dd>" in b and "<dt>Subtitles</dt><dd>French · Text (SRT)</dd>" in b
    assert "<dt>Cinema</dt><dd>5 May 2019</dd>" in b and "<dt>Digital</dt><dd>1 Aug 2019</dd>" in b
    added = b.split('class="filegrid"', 1)[1].split("</div>\n", 1)[0]
    assert '<div class="microlabel">Added</div><div class="filestat-value">2 Mar 2026</div>' in added
    assert "<dt>Watched</dt><dd>1 time · 12 Oct 2025</dd>" in b             # U6 (2026-10-13): no verb repeating its label


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
        b = main_of(whole(client, "/media/title/movie/603"))
    col = b.split('<section class="sec colsec" id="collection">', 1)[1].split("</section>", 1)[0]  # media-ux3 banner
    assert "Harbour Lights 2" in col and col.count(">On server<") == 2 and col.count(">Not on server<") == 1
    # Re-pointed 2026-10-30 (JY-269 phase 3): Similar + Recommended are now ONE "More on Joey" row on the web
    sim = b.split('<h2 class="seclabel">More on Joey</h2>', 1)[1].split("</section>", 1)[0]
    assert 'href="/media/title/movie/11"' in sim and ">On server<" in sim and ">Not on server<" in sim
    assert '<h2 class="seclabel">Similar</h2>' not in b and "Rec One" in sim and "?h=240" in sim


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
        b = main_of(whole(client, "/media/item/ep3"))
    assert '<h1 class="hero-detail-title">Penny for Your Thoughts</h1>' in b       # JY-315: the episode title is the h1
    assert "Aired 12 Oct 2026" in b and "Coins go missing." in b
    assert "Episode of" not in b      # media-ux4 (2026-10-08, B.): the line is gone; the part-of banner links the show
    assert "Cass Creator" in b and 'aria-current="page">TV shows' in b


# ---- failure and safety ----

def test_everything_failing_still_200_with_words(env):
    client, both = env()
    both.fail_jf = both.fail_seerr = True
    with client:
        plain = client.get("/media/title/movie/701")
        listed = client.get("/media/title/movie/603")        # on the library snapshot, but nothing reachable
        item = client.get("/media/item/mov1")
    assert plain.status_code == 200 and status(plain.text) == "Not on server"
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
        b = main_of(whole(client, "/media/title/movie/603"))   # F2: after the deferred parts landed
    assert r.status_code == 200 and "Harbour Lights (2019)" in b and ">Similar</div>" not in b and "sp-imdb" not in b


def test_no_key_or_jellyfin_host_in_html(env):
    client, _ = env()
    with client:
        for url in ("/media/title/movie/603", "/media/title/movie/701", "/media/title/tv/100", "/media/item/mov1", "/media/item/ep3"):
            html = client.get(url).text
            assert KEY not in html and SKEY not in html and "jf.secret-host" not in html
            assert html.count("seerr.secret-host") <= 1          # only the one "Open in Seerr" link


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
        assert 'hx-post="/media/watchlist/add"' in b and 'aria-label="Add to watchlist"' in b
        client.post("/media/watchlist/add", content="tmdb_id=701&kind=movie&title=Plain+Film",
                    headers={"content-type": "application/x-www-form-urlencoded"})
        assert "On your watchlist" in main_of(client.get("/media/title/movie/701").text)
        confirm = client.get("/media/title/movie/701?step=confirm")
        assert "Confirm request" in confirm.text
        done = client.get("/media/title/movie/701?requested=1")
    assert "Requested ✓" in done.text
    assert "playbtn" not in main_of(done.text)               # no Play link for a title that is not on the server


# ---- merged from test_media_ux4_trailer.py ----
# media-ux4 item 9 (2026-10-08): trailers embedded. The Trailer button keeps a plain link to the video (no JS) and, when it
# is a YouTube video, carries its key; a click opens an in-page <dialog> into which the script creates a
# youtube-nocookie.com iframe (autoplay, rel=0) — nothing in the initial HTML loads from YouTube — and closing removes it.
# Keys come from Jellyfin RemoteTrailers, then Jellyseerr's TMDB relatedVideos.


ROOT = Path(__file__).resolve().parents[2]
CSS = (ROOT / "hub" / "static" / "control-surface.css").read_text(encoding="utf-8")
CONTRACT = (ROOT / "docs" / "connector-contract.md").read_text(encoding="utf-8")
KEY_ux4_trailer = "dQw4w9WgXcQ"


def with_video(both, **video):
    both.seerr.table["/api/v1/movie/603"] = {**FILM, "relatedVideos": [
        {"url": f"https://www.youtube.com/watch?v={KEY_ux4_trailer}", "site": "YouTube", "type": "Trailer", "key": KEY_ux4_trailer, **video}]}


def button(b):
    m = re.search(r'<a class="btn btn-glass trailer-btn" href="([^"]+)" target="_blank" rel="noopener"([^>]*)>(.*?)</a>', b, re.S)
    return m and (m.group(1), m.group(2), re.sub(r"<svg.*?</svg>", "", m.group(3), flags=re.S))


def test_button_is_a_word_link_with_the_youtube_key(env):
    client, both = env()
    with_video(both)
    with client:
        b = main_of(whole(client, "/media/title/movie/603"))
    href, attrs, words = button(b)
    assert href == f"https://www.youtube.com/watch?v={KEY_ux4_trailer}" and words == "Trailer"
    assert f'data-yt="{KEY_ux4_trailer}"' in attrs and 'aria-haspopup="dialog"' in attrs
    hero = b.split("</header>", 1)[0]
    assert "trailer-btn" in hero and '<svg class="ic"' in hero.split("trailer-btn", 1)[1].split("</a>", 1)[0]


def test_dialog_ships_empty_and_no_iframe_is_in_the_initial_html(env):
    client, both = env()
    with_video(both)
    with client:
        html = client.get("/media/title/movie/603").text
    dlg = html.split('<dialog class="trailerdlg" id="trailer"', 1)[1].split("</dialog>", 1)[0]
    assert 'aria-label="Trailer: Harbour Lights"' in dlg and '<form method="dialog">' in dlg and ">Close</button>" in dlg
    assert '<div class="trailerframe"></div>' in dlg
    assert "<iframe" not in html                                      # created only on click
    assert not re.search(r'(src|href)="https://www\.youtube-nocookie\.com', html)


def test_script_builds_the_nocookie_embed_on_click_and_removes_it_on_close(env):
    client, both = env()
    with_video(both)
    with client:
        html = client.get("/media/title/movie/603").text
    script = html.split("</dialog>", 1)[1].split("</script>", 1)[0]
    assert "'https://www.youtube-nocookie.com/embed/' + a.getAttribute('data-yt') + '?autoplay=1&rel=0'" in script
    assert "createElement('iframe')" in script and "dlg.showModal()" in script and "e.preventDefault()" in script
    assert "document.addEventListener('close'" in script and ".replaceChildren()" in script
    assert "/^[A-Za-z0-9_-]{11}$/" in script and "window.joeyTrailer" in script     # validated; bound once per tab


def test_jellyfin_trailer_wins_and_short_or_foreign_urls_stay_plain_links(env, monkeypatch):
    client, both = env()
    with_video(both)
    monkeypatch.setitem(ITEMS["mov1"], "RemoteTrailers", [{"Url": "https://youtu.be/AAAAAAAAAAA"}])
    with client:
        b = main_of(client.get("/media/item/mov1").text)
        assert button(b)[0] == "https://youtu.be/AAAAAAAAAAA" and 'data-yt="AAAAAAAAAAA"' in button(b)[1]
        monkeypatch.setitem(ITEMS["mov1"], "RemoteTrailers", [{"Url": "https://vimeo.com/12345"}])
        media_item.clear_cache()
        media_film.drain_extras()   # JY-236: the first (cold) page queued the Jellyseerr read; wait for it, or a slow machine renders before raw is cached
        b = main_of(client.get("/media/item/mov1").text)
    assert button(b)[0] == f"https://www.youtube.com/watch?v={KEY_ux4_trailer}"     # the keyed Jellyseerr video beats a non-YouTube link


def test_no_key_means_a_plain_link_and_no_dialog(env):
    client, _ = env()                                                    # FILM's video id "seerr1" is not a YouTube id
    with client:
        html = whole(client, "/media/title/movie/603")
        cached = client.get("/media/title/movie/603").text
    href, attrs, _ = button(main_of(html))
    assert href == "https://www.youtube.com/watch?v=seerr1" and "data-yt" not in attrs
    assert "<iframe" not in html
    # F2: a cold page ships the empty dialog while its trailer is still a pending part; once known (cached), no dialog
    assert "<dialog" not in cached and "youtube-nocookie" not in cached


@pytest.mark.parametrize("url, key", [
    (f"https://www.youtube.com/watch?v={KEY_ux4_trailer}", KEY_ux4_trailer), (f"https://youtube.com/watch?v={KEY_ux4_trailer}&t=3", KEY_ux4_trailer),
    (f"https://youtu.be/{KEY_ux4_trailer}", KEY_ux4_trailer), (f"https://www.youtube.com/embed/{KEY_ux4_trailer}", KEY_ux4_trailer),
    (f"https://m.youtube.com/shorts/{KEY_ux4_trailer}", KEY_ux4_trailer), (f"https://www.youtube-nocookie.com/embed/{KEY_ux4_trailer}", KEY_ux4_trailer),
    ("https://www.youtube.com/watch?v=short", None), ("https://evil.example/watch?v=" + KEY_ux4_trailer, None),
    ("https://vimeo.com/123", None), ("", None), (None, None),
    ("https://www.youtube.com/watch?v=" + KEY_ux4_trailer[:10] + '"', None)])
def test_youtube_key(url, key):
    assert media_film.youtube_key(url) == key


def test_trailer_prefers_the_relatedvideos_key_field():
    raw = {"relatedVideos": [{"url": "https://www.youtube.com/watch?v=xx", "site": "YouTube", "type": "Trailer", "key": KEY_ux4_trailer},
                             {"url": "https://www.youtube.com/watch?v=BBBBBBBBBBB", "site": "YouTube", "type": "Teaser"}]}
    assert media_film._trailer(None, raw) == ("https://www.youtube.com/watch?v=xx", KEY_ux4_trailer)
    assert media_film._trailer(None, {}) == (None, None)


def test_player_css_and_the_recorded_privacy_exception():
    assert ".trailerdlg::backdrop { background: var(--scrim); }" in CSS
    assert ".trailerframe { aspect-ratio: 16 / 9;" in CSS and ".trailerframe iframe { display: block; width: 100%;" in CSS
    assert "Trailer player (media-ux4, 2026-10-08) — a recorded privacy exception" in CONTRACT
    assert "only when the user presses Trailer" in CONTRACT and "frame-src https://www.youtube-nocookie.com" in CONTRACT


# ---- merged from test_media_ux4_makers.py ----
# media-ux4 item 4 (2026-10-08): director / creators more prominent. The hero's inline "Director Guy Ritchie" text is a
# "Directed by" block of headshot cards (TMDB profile through the /img proxy, initials when none) with the name larger,
# each card ONE link to /media/person/{id} (a Discover search when TMDB gives no id); TV shows say "Created by" with up to
# four cards; on a phone the cards are a sideways row.


CSS_ux4_makers = (Path(__file__).resolve().parents[2] / "hub" / "static" / "control-surface.css").read_text(encoding="utf-8")


def hero(b):
    return b.split("</header>", 1)[0]


def cards(h):
    block = h.split('<div class="makers">', 1)[1].split("\n  </div>", 1)[0]   # E4: the makerrow (site pills left the hero)
    label = re.search(r'<div class="microlabel">([^<]+)</div>', block).group(1)
    found = re.findall(r'<a class="makercard" href="([^"]+)">(<img class="makerpic" src="([^"]+)"[^>]*>|<span class="makerpic '
                       r'initials" aria-hidden="true">([^<]*)</span>)<span class="makername">([^<]+)</span></a>', block)
    return label, [(href, src or None, initials or None, name) for href, _, src, initials, name in found]


def chips(h):
    """JY-280: the film hero's Director / Writer chips as (role, name, href)."""
    return [(role, name, href) for href, role, name in re.findall(
        r'<a class="chip makerchip" href="([^"]+)"><span class="makerchip-role">([^<]+)</span>([^<]+)</a>', h)]


def test_film_hero_has_director_and_writer_chips_linking_to_person_pages(env):
    # JY-280 (P1, AC 3): the film's "Directed by" cards became one chip per Director / Writer, each one person link
    client, both = env()
    both.seerr.table["/api/v1/movie/603"] = {**FILM, "credits": {**FILM["credits"], "crew": [
        {"id": 77, "name": "Guy Ritchie", "job": "Director", "profilePath": "/guy.jpg"},
        {"id": 78, "name": "Wren Writer", "job": "Screenplay"}, {"id": 79, "name": "Cy Camera", "job": "Director of Photography"}]}}
    with client:
        h = hero(main_of(whole(client, "/media/title/movie/603")))
    assert chips(h) == [("Director", "Guy Ritchie", "/media/person/77?from=title#land"),
                        ("Writer", "Wren Writer", "/media/person/78?from=title#land")]
    assert '<div class="makers">' not in h and "makercard" not in h


def test_no_tmdb_id_falls_back_to_the_person_find_link(env):
    client, _ = env()                                   # FILM's director has no id
    with client:
        found = chips(hero(main_of(client.get("/media/title/movie/603").text)))
    assert ("Director", "Dee Director", "/media/person/find?name=Dee%20Director&amp;from=title#land") in found


def test_series_says_created_by_with_up_to_four_chips(env):
    # JY-317 (B. 2026-11-06, "Stop placing them in circles. For shows and movies."): was up to four headshot cards;
    # now up to four "Creator" chips, each one link to the person page, as the film's Director / Writer chips
    client, both = env()
    both.seerr.table["/api/v1/tv/100"] = {**SHOW, "createdBy": [
        {"id": 10 + i, "name": f"Maker {chr(65 + i)} Person", "profilePath": f"/m{i}.jpg" if i % 2 == 0 else None}
        for i in range(5)]}
    with client:
        h = hero(main_of(whole(client, "/media/title/tv/100")))
    found = chips(h)
    assert len(found) == 4 and found[0] == ("Creator", "Maker A Person", "/media/person/10?from=title#land")
    assert found[1] == ("Creator", "Maker B Person", "/media/person/11?from=title#land")
    assert "makerpic" not in h and "makercard" not in h


def test_jellyfin_director_without_jellyseerr_still_gets_a_chip(env, monkeypatch):
    from tests.hub import helpers as tmi
    monkeypatch.setitem(tmi.ITEMS["mov1"], "People", [
        {"Name": "Ada Actor", "Type": "Actor", "Role": "Pilot"},
        {"Name": "Dee Director", "Type": "Director", "Id": "p77", "PrimaryImageTag": "t"},
        {"Name": "Wes Words", "Type": "Writer"}])
    client, both = env()
    both.fail_seerr = True
    with client:
        found = chips(hero(main_of(client.get("/media/item/mov1").text)))
    assert found == [("Director", "Dee Director", "/media/person/find?name=Dee%20Director&amp;from=title#land"),
                     ("Writer", "Wes Words", "/media/person/find?name=Wes%20Words&amp;from=title#land")]


def test_chips_sit_under_the_facts_line_before_the_status_and_the_action_row(env):
    # JY-280 (AC 3): chips under the facts line (E4's order otherwise kept)
    client, _ = env()
    with client:
        h = hero(main_of(client.get("/media/title/movie/603").text))
    assert h.index('class="facts-line"') < h.index('<div class="makerchips">') < h.index('id="status-line"') < h.index('class="hero-detail-btns"')
    assert "sitepill" not in h


def test_film_hero_is_taller_with_a_bigger_poster_and_one_overview(env):
    # JY-280 (AC 1, 2): the film poster carries tl-movie (300 / 230 / 170 px), the hero is taller; the overview is said once
    client, _ = env()
    with client:
        b = main_of(whole(client, "/media/title/movie/603"))
    h = hero(b)
    assert re.search(r'class="[^"]*hero-detail-poster tl-movie', h) and 'class="tl-syn"' in h
    assert '<h2 class="seclabel">Overview</h2>' not in b and b.count("A ferry pilot returns home.") == 1
    for rule in (r"\.pagehead\.hero-detail:has\(\.tl-movie\) \{ min-height: min\(78vh, 900px\)",
                 r"\.hero-detail-poster\.tl-movie \{ width: 300px", r"\.hero-detail-poster\.tl-movie \{ width: 230px",
                 r"\.hero-detail-poster\.tl-movie \{ width: 170px"):
        assert re.search(rule, CSS_ux4_makers), rule


def test_show_hero_keeps_its_poster_size_and_takes_the_film_chips(env):
    # JY-317 (B. 2026-11-06): was "keeps its cards"; a show's hero now takes the film's maker chips (no headshot cards)
    client, _ = env()
    with client:
        h = hero(main_of(whole(client, "/media/title/tv/100")))
    assert "tl-movie" not in h and '<div class="makerchips">' in h and "makercard" not in h


def test_film_cast_tile_without_a_photo_shows_initials(env):
    # JY-280: restores the old cards' initials fallback on the 2:3 tiles (FILM's "Bo Bit" has no profilePath, no id)
    client, _ = env()
    with client:
        b = main_of(whole(client, "/media/title/movie/603"))
    tile = b.split('<section class="sec castsec casttiles">', 1)[1].split("</section>", 1)[0]
    assert '<div class="castcard"><span class="castpic initials" aria-hidden="true">BB</span>' in tile and ">Bo Bit<" in tile


def test_tv_mode_film_cast_has_no_casttiles():
    # JY-283 / JY-317 (2026-11-06): every web cast row is `.casttiles` now; the TV keeps its own branch (tvt.person tiles)
    from pathlib import Path
    tpl = (Path(media_film.__file__).resolve().parent / "templates" / "_film_cast.html").read_text(encoding="utf-8")
    tv, web = tpl.split("{% if tv_mode(request) %}", 1)[1].split("{% elif film.cast %}", 1)
    assert 'class="sec castsec' not in tv and "tvt.person" in tv
    assert '<section class="sec castsec casttiles">' in web


def test_film_cast_tiles_are_2_3_boxier_and_lead_the_body(env):
    # JY-280 (AC 5): 2:3 tiles, 4 px radius, each a person link, in the body before the stats card
    client, both = env()
    both.seerr.table["/api/v1/movie/603"] = {**FILM, "credits": {**FILM["credits"], "cast": [
        {"id": 55, "name": "Ada Actor", "character": "Pilot", "profilePath": "/ada.jpg"}]}}
    with client:
        b = main_of(whole(client, "/media/title/movie/603"))
    body = b.split("</header>", 1)[1]
    assert '<a class="castcard" href="/media/person/55"><img class="castpic" src="/img/tmdb:/ada.jpg?h=' in body
    assert body.index('<h2 class="seclabel">Cast</h2>') < body.index('class="stats numbers')
    assert '<section class="sec castsec casttiles">' in body
    tile = body.split('<section class="sec castsec casttiles">', 1)[1].split("</section>", 1)[0]
    assert f'<img class="castpic" src="/img/tmdb:/ada.jpg?h={media_film.CAST_H}"' in tile and 'width="180" height="270"' in tile
    assert re.search(r"\.castsec\.casttiles \.castpic \{[^}]*aspect-ratio: 2 / 3; border-radius: 4px;", CSS_ux4_makers)



def test_maker_headshot_size_is_a_proxy_size():
    from hub import images
    assert media_film.MAKER_H in images.SIZES and media_film.MAKERS_MAX == 4


def test_phone_row_scrolls_sideways_and_wraps_from_640():
    row = CSS_ux4_makers.split(".makerrow {", 1)[1].split("}", 1)[0]
    assert "display: flex" in row and "overflow-x: auto" in row and "flex-wrap" not in row
    wide = CSS_ux4_makers.split("@media (min-width: 640px) {\n  .hero-detail-in", 1)[1].split("\n}", 1)[0]
    assert ".makerrow { flex-wrap: wrap; overflow: visible; }" in wide
    assert ".makername { font-size: 16px; font-weight: 600;" in CSS_ux4_makers and ".makerpic { width: 52px; height: 52px;" in CSS_ux4_makers


def test_cast_is_circles_and_more_on_joey_is_posters_on_the_web(env):
    """JY-269 phase 3: web cast = circle row linking /media/person/{id}, then ONE "More on Joey" poster row (on-server
    titles first); skeleton shapes while each deferred part loads."""
    from pathlib import Path
    client, _ = env()
    with client:
        b = main_of(whole(client, "/media/title/movie/603"))
    cast = b.split('<section class="sec castsec casttiles">', 1)[1].split("</section>", 1)[0]
    assert '<div class="castrow">' in cast and "as Pilot" in cast
    assert b.index('class="sec castsec') < b.index('<h2 class="seclabel">More on Joey</h2>')
    more = b.split('<h2 class="seclabel">More on Joey</h2>', 1)[1].split("</section>", 1)[0]
    assert more.index(">On server<") < more.index(">Not on server<") and 'class="card-poster"' in more
    hrefs = [h for h in more.split('href="')[1:]]
    assert len(hrefs) == len({h.split('"', 1)[0] for h in hrefs})                    # each title once
    css = (Path(media_film.__file__).resolve().parent / "static" / "control-surface.css").read_text(encoding="utf-8")
    # JY-283 / JY-317 (B. 2026-11-06, "Stop placing them in circles."): the JY-269 88 px circle rule is gone; 2:3 tiles
    assert "border-radius: 50%" not in "".join(r for r in re.findall(r"html:not\(\.tv\) \.castsec[^{]*\{[^}]*\}", css))
    assert "html:not(.tv) .castsec.casttiles .castpic { width: 100%; height: auto; aspect-ratio: 2 / 3; border-radius: 4px;" in css
    tpl = Path(media_film.__file__).resolve().parent / "templates"
    assert 'href="/media/person/{{ c.id }}"' in (tpl / "_film_cast.html").read_text(encoding="utf-8")
    assert 'castsec casttiles webskel' in (tpl / "_film_cast.html").read_text(encoding="utf-8")
    assert 'moresec webskel' in (tpl / "_film_shelves.html").read_text(encoding="utf-8")


def test_web_cast_circle_links_to_the_person_page_when_the_cast_has_ids(env, monkeypatch):
    """JY-269 P3 review: the fixture cast had no person ids, so the link was never rendered. With an id the circle is a
    link to /media/person/{id}; without one it is a plain div (Jellyfin's own actors)."""
    cast = [{**FILM["credits"]["cast"][0], "id": 1001}, FILM["credits"]["cast"][1]]
    monkeypatch.setitem(FILM, "credits", {**FILM["credits"], "cast": cast})
    client, _ = env()
    with client:
        b = main_of(whole(client, "/media/title/movie/603"))
    sec = b.split('<section class="sec castsec casttiles">', 1)[1].split("</section>", 1)[0]
    assert '<a class="castcard" href="/media/person/1001">' in sec and "Ada Actor" in sec
    assert '<div class="castcard">' in sec and "Bo Bit" in sec
