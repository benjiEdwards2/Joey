"""media-ux2 item 7 (2026-10-08): Media home drops the "This week" and "Recently watched" shelves. The data stays:
Server -> Library keeps its This week rows and Diary > To rate (/media/history) keeps Recently watched."""
from fastapi.testclient import TestClient

from tests.hub.test_media_frame import env  # noqa: F401  (env fixture)
from tests.hub.helpers import ARR, JELLY
from tests.hub.conftest import main_raw as main_of


def test_media_home_has_no_this_week_or_recently_watched(env):
    main = env(jellyfin=JELLY, arr=ARR)
    with TestClient(main.app) as c:
        home = main_of(c.get("/a/alpha").text)
    assert ">This week" not in home and "Recently watched" not in home
    assert "Due Show" not in home and "Nothing due this week" not in home and "poster-tag" not in home
    assert "Harbour Lights" not in home                       # a Recently watched row
    assert ">Continue watching" in home and ">Recently added" in home


def test_the_data_still_shows_where_it_lives(env):
    main = env(jellyfin=JELLY, arr=ARR)
    with TestClient(main.app) as c:
        lib = main_of(c.get("/media/library").text)
        hist = main_of(c.get("/media/history").text)
    assert ">This week" in lib
    assert ">Recently watched</div>" in hist and "Harbour Lights" in hist


# ---- media-ux2 item 8 (2026-10-08): the Joey hub page (/) drops Continue watching; Media keeps it ----

def test_hub_page_has_no_continue_watching_but_media_home_does(env):
    main = env(jellyfin=JELLY, arr=ARR)
    with TestClient(main.app) as c:
        hub_page = main_of(c.get("/").text)
        home = main_of(c.get("/a/alpha").text)
    assert "Continue watching" not in hub_page and 'id="continue"' not in hub_page
    assert 'id="recent"' in hub_page and "Recently watched" in hub_page   # the hub's own band stays
    assert ">Continue watching" in home and "Dust and Daylight" in home
