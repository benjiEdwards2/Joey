"""The "part of" banners (media-ux3, 2026-10-08): an episode / season page shows its show as a wide banner under the
hero ("Quiet Show · Season 4 · Episode 3 · 3 of 6 watched", This season / All seasons), the series page opens
`?season=N`, and a film page moves its collection from the bottom shelves to a banner directly under Overview with
the parts in release order and the page's own film flagged. Jellyfin + Jellyseerr faked (test_media_film's env)."""
import re

import pytest

from tests.hub.film_page import whole
from tests.hub.helpers import env, FILM, ITEMS, PLAIN, prow  # noqa: F401  (re-export: defined in tests/hub/helpers.py)
from tests.hub.conftest import main_of  # noqa: F401
from tests.hub import helpers as tmi
from pathlib import Path

CSS = (Path(__file__).resolve().parents[2] / "hub" / "static" / "control-surface.css").read_text(encoding="utf-8")


def words(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html)).strip()


def banner(b):
    return b.split('<section class="sec partof-sec">', 1)[1].split("</section>", 1)[0]


def collection(b):
    return b.split('<section class="sec colsec" id="collection">', 1)[1].split("</section>", 1)[0]


# ---- episode / season pages ----

def test_episode_banner_words_and_links(env):
    client, _ = env()
    with client:
        b = main_of(client.get("/media/item/ep3").text)
    ban = banner(b)
    line = ban.split('<p class="partof-line">', 1)[1].split("</p>", 1)[0]
    assert words(line) == "Quiet Show · Season 4 · Episode 3 · 3 of 6 watched"
    assert '<a class="btn btn-glass" href="/media/item/ser1?season=4#season-4">' in ban and "This season</a>" in ban
    assert '<a class="btn btn-glass" href="/media/item/ser1#seasons">' in ban and "All seasons</a>" in ban
    assert 'src="/img/jf:ser1?h=240' in ban                                   # the show's poster


def test_episode_banner_sits_directly_under_the_hero(env):
    client, _ = env()
    with client:
        b = main_of(client.get("/media/item/ep3").text)
    hero_end, ban = b.index("</header>"), b.index('<section class="sec partof-sec">')
    assert hero_end < ban < b.index('<div class="stats numbers">') < b.index('id="seasons"')


def test_banner_without_a_backdrop_is_a_plain_panel(env):
    client, _ = env()
    with client:
        ban = banner(main_of(client.get("/media/item/ep3").text))
    assert '<div class="partof">' in ban and "partof-bd" not in ban


def test_banner_with_the_shows_backdrop(env, monkeypatch):
    monkeypatch.setitem(ITEMS["ser1"], "BackdropImageTags", ["abc"])
    client, _ = env()
    with client:
        ban = banner(main_of(client.get("/media/item/ep3").text))
    assert '<div class="partof has-bd">' in ban
    assert "<div class=\"partof-bd\" style=\"--bd: url('/img/jfb:ser1?h=1280')\" aria-hidden=\"true\"></div>" in ban


def test_season_page_banner_links_to_all_seasons_only(env, monkeypatch):
    monkeypatch.setitem(ITEMS, "sea1", {"Id": "sea1", "Type": "Season", "Name": "Season 4", "SeriesId": "ser1",
                                        "SeriesName": "Quiet Show", "IndexNumber": 4, "UserData": {}})
    client, _ = env()
    with client:
        b = main_of(client.get("/media/item/sea1").text)
    ban = banner(b)
    assert words(ban.split('<p class="partof-line">', 1)[1].split("</p>", 1)[0]) == "Quiet Show · Season 4 · 3 of 6 watched"
    assert 'href="/media/item/ser1#seasons"' in ban and "This season" not in ban
    assert '<details class="seasonbox epseason" id="season-4" open>' in b


def test_series_page_has_no_banner_and_anchors_its_seasons(env):
    client, _ = env()
    with client:
        b = main_of(client.get("/media/item/ser1").text)
    assert "partof-sec" not in b and '<section class="sec seasons" id="seasons">' in b


def test_film_page_has_no_episode_banner(env):
    client, _ = env()
    with client:
        assert "partof-sec" not in main_of(client.get("/media/item/mov1").text)


# ---- ?season=N on the series page ----

@pytest.fixture()
def two_seasons(monkeypatch):
    monkeypatch.setattr(tmi, "SEASONS", [{"Id": "sea0", "Name": "Season 3", "IndexNumber": 3},
                                         {"Id": "sea1", "Name": "Season 4", "IndexNumber": 4}])
    # E1 (2026-10-13): the show's episodes come from ONE read and name their season, so Season 3 needs its own rows
    # (the old per-season fake answered every season with the same six)
    third = [{**e, "Id": "s3" + e["Id"], "SeasonId": "sea0", "SeasonName": "Season 3", "ParentIndexNumber": 3}
             for e in tmi.EPISODES]
    monkeypatch.setattr(tmi, "EPISODES", third + tmi.EPISODES)


def opened(b):
    return re.findall(r'<details class="seasonbox epseason" id="season-(\d+)" open>', b)


def test_series_page_opens_the_next_episodes_season_by_default(env, two_seasons):
    client, _ = env()
    with client:
        assert opened(main_of(client.get("/media/item/ser1").text)) == ["3"]


def test_season_param_opens_that_season(env, two_seasons):
    client, _ = env()
    with client:
        assert opened(main_of(client.get("/media/item/ser1?season=4").text)) == ["4"]
        assert opened(main_of(client.get("/media/item/ser1?season=x").text)) == ["3"]      # junk is ignored
        assert opened(main_of(client.get("/media/item/ser1?season=9").text)) == ["4"]      # unknown: the latest


def test_episode_banner_links_carry_the_episodes_own_season(env, two_seasons, monkeypatch):
    monkeypatch.setitem(ITEMS["ep3"], "ParentIndexNumber", 3)
    client, _ = env()
    with client:
        ban = banner(main_of(client.get("/media/item/ep3").text))
    assert 'href="/media/item/ser1?season=3#season-3"' in ban and "Season 3 · Episode 3" in words(ban)


# ---- film series banner ----

def test_collection_sits_directly_under_overview(env):
    client, _ = env()
    with client:
        b = main_of(whole(client, "/media/item/mov1"))
    ov, col = b.index('<div class="seclabel">Overview</div>'), b.index('id="collection"')
    assert ov < col < b.index('<div class="seclabel">File</div>') < b.index('<div class="seclabel">Similar</div>')
    assert '<div class="seclabel">Harbour Collection</div>' not in b                 # no longer a bottom shelf
    assert '<div class="seclabel">Recommended</div>' in b


def test_collection_banner_words_follow_form_and_current_film(env):
    client, _ = env()
    with client:
        b = main_of(whole(client, "/media/title/movie/603"))
    col = collection(b)
    head = col.split('<div class="carousel partof-parts">', 1)[0]
    assert words(head.split('<p class="partof-line">', 1)[1].split("</p>", 1)[0]) == "Harbour Collection · 3 films · 2 on server"
    assert 'action="/media/follow/collection/9"' in head and "Follow series</button>" in head
    cards = col.split('<div class="carousel partof-parts">', 1)[1]
    assert cards.count("is-current") == 1 and cards.count('aria-current="page"') == 1
    current = cards.split('<a class="card-poster is-current" href="/media/title/movie/603" aria-current="page">', 1)[1]
    assert '<span class="st-current">This film</span>' in current.split("</a>", 1)[0]
    assert cards.count("This film") == 1


def test_item_and_title_pages_share_the_banner(env):
    client, _ = env()
    with client:
        a = collection(main_of(whole(client, "/media/item/mov1")))
        b = collection(main_of(whole(client, "/media/title/movie/603")))
    assert a.replace("/media/item/mov1", "/media/title/movie/603") == b              # only `back` differs


def test_parts_run_in_release_order(env):
    client, both = env()
    both.seerr.table["/api/v1/collection/9"] = {"name": "Harbour Collection", "parts": [
        {**prow(605, "Harbour Lights 3"), "releaseDate": "2024-01-01"},
        {**prow(603, "Harbour Lights", 5), "releaseDate": "2019-05-05"},
        {**prow(606, "Harbour Lights 0"), "releaseDate": ""},
        {**prow(604, "Harbour Lights 2"), "releaseDate": "2022-01-01"}]}
    with client:
        cards = collection(main_of(whole(client, "/media/title/movie/603"))).split("partof-parts", 1)[1]
    hrefs = re.findall(r'href="/media/title/movie/(\d+)"', cards)
    assert hrefs == ["603", "604", "605", "606"]                                     # undated last


def test_collection_backdrop_then_first_part_then_none(env):
    client, both = env()
    parts = [prow(603, "Harbour Lights", 5), {**prow(604, "Harbour Lights 2"), "backdropPath": "/p2b.jpg"}]
    with client:
        both.seerr.table["/api/v1/collection/9"] = {"name": "HC", "backdropPath": "/colb.jpg", "parts": parts}
        a = collection(main_of(whole(client, "/media/title/movie/603")))
        from hub import media_discover
        media_discover.clear_cache()
        both.seerr.table["/api/v1/collection/9"] = {"name": "HC", "parts": parts}
        b = collection(main_of(whole(client, "/media/title/movie/603")))
        media_discover.clear_cache()
        both.seerr.table["/api/v1/collection/9"] = {"name": "HC", "parts": parts[:1]}
        c = collection(main_of(whole(client, "/media/title/movie/603")))
    assert "url('/img/tmdb:/colb.jpg?h=1280')" in a and '<div class="partof partof-col has-bd">' in a
    assert "url('/img/tmdb:/p2b.jpg?h=1280')" in b
    assert "partof-bd" not in c and '<div class="partof partof-col">' in c


def test_no_collection_no_banner(env):
    client, _ = env()
    with client:
        b = main_of(client.get("/media/title/movie/701").text)
    assert 'id="collection"' not in b and "Follow series" not in b


def test_following_state_inside_the_banner(env):
    client, _ = env()
    with client:
        client.post("/media/follow/collection/9", data={"back": "/media/title/movie/603"})
        head = collection(main_of(client.get("/media/title/movie/603").text)).split("partof-parts", 1)[0]
    assert 'action="/media/follow/collection/9/unfollow"' in head and "Following series ✓" in head


# ---- the look ----

def test_banner_css_scrim_and_phone_stack():
    assert re.search(r"\.partof-bd \{[^}]*linear-gradient\(90deg, var\(--pagehead-side-0\)", CSS)
    phone = CSS.split("@media (max-width: 640px) {\n  .partof {", 1)[1].split("\n}", 1)[0]
    assert "flex-direction: column" in phone and ".partof-btns .btn" in phone and "flex: 1 1 100%" in phone
    assert ".partof-parts .card-poster.is-current" in CSS
