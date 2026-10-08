"""media-ux2 item 3 (2026-10-08): "By year" is gone from the Movies and TV Shows tab rows; /media/years stays
reachable by URL (and still lights the right section), with no in-app link to it from the Movies / TV pages."""
import pytest
from fastapi.testclient import TestClient

from hub import media_nav
from tests.hub.test_media_frame import env, current, nav_html  # noqa: F401  (env fixture)
from tests.hub.test_media_shelves import JELLY, ARR


def test_movies_and_tv_tabs_have_no_by_year():
    tabs = {s["id"]: [label for label, _ in s["tabs"]] for s in media_nav.SECTIONS}
    assert tabs["movies"] == ["My films", "Watchlist", "Tonight", "To rate", "Awards"]   # media-ux4: + To rate; 2026-10-08: + Awards
    assert tabs["tv"] == ["My shows", "Watchlist", "Tonight", "To rate", "Awards"]
    assert not [h for s in media_nav.SECTIONS for _, h in s["tabs"] if h.startswith(media_nav.YEARS)]


@pytest.mark.parametrize("route", ["/media/movies", "/media/tv", "/media/movies/tonight", "/media/tv/watchlist"])
def test_movies_tv_pages_link_nowhere_to_years(env, route):
    main = env(jellyfin=JELLY, arr=ARR)
    with TestClient(main.app) as c:
        html = c.get(route).text
    assert "By year" not in html and "/media/years" not in html


@pytest.mark.parametrize("route, section", [("/media/years", "Movies"), ("/media/years?kind=movie", "Movies"),
                                            ("/media/years?kind=tv", "TV Shows")])
def test_years_page_still_served_under_its_section_with_no_current_tab(env, route, section):
    main = env(jellyfin=JELLY, arr=ARR)
    with TestClient(main.app) as c:
        r = c.get(route)
    assert r.status_code == 200
    assert current(r.text, "sectabs") == [section]
    assert current(r.text, "sectabs sub") == []           # no tab claims the page
    assert "By year" not in nav_html(r.text, "sectabs sub")
