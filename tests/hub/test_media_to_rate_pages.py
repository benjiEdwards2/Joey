"""media-ux2 item 2 (2026-10-08): a "To rate" section at the top of /media/movies and /media/tv, reusing the
Diary > To rate inbox (_to_rate) and the POST /media/rate route. Films page: films only; TV page: shows / seasons /
episodes per the owner's level. Absent when nothing waits; a plain-form rating returns to the same page.
Reworded for media-ux4 (2026-10-08, B.): the section moved off the list pages to a "To rate" TAB beside Tonight
(/media/movies/to-rate, /media/tv/to-rate) — the same rows, filters and redirect, asserted on the tab pages now.
"""
import re

import pytest

from hub import media_db, media_nav, media_write
from tests.hub.conftest import main_raw as main_of  # noqa: F401
from tests.hub.test_media_her import env as her_env, main_html  # noqa: F401
from tests.hub.test_media_rate import env, HX, jelly_data, TV  # noqa: F401


def section(html):
    """The inbox of a To rate tab page (from its count line), or None when nothing waits there."""
    body = main_of(html)
    if 'class="ratepick"' not in body:
        return None
    return body.split('<p class="metaline">', 1)[1].split('<p class="metaline">', 1)[0]


def test_films_page_lists_only_films_waiting(env):
    build, _ = env
    media_db.set_rating("tmdb:4", 7, "movie", "Already Rated")
    with build() as client:
        sec = section(client.get("/media/movies/to-rate").text)
    assert sec is not None and sec.startswith("1 film watched")          # the count line
    assert sec.count('class="ratepick"') == 1 and "Heat" in sec
    assert "Quiet Show" not in sec and "Already Rated" not in sec and "Long Ago" not in sec
    assert 'name="kind" value="movie"' in sec and 'name="back" value="/media/movies/to-rate"' in sec
    assert 'hx-post="/media/rate"' in sec


def test_tv_page_lists_only_tv_at_the_owner_level(env):
    build, _ = env
    with build() as client:
        sec = section(client.get("/media/tv/to-rate").text)
    assert sec.count('class="ratepick"') == 1 and "Quiet Show" in sec and "Heat" not in sec
    assert 'name="back" value="/media/tv/to-rate"' in sec and 'name="item_key" value="jf:s1"' in sec
    media_db.set_setting("you", "rating_level", "episode")
    with build(jelly_data(TV)) as client:
        sec = section(client.get("/media/tv/to-rate").text)
        films = section(client.get("/media/movies/to-rate").text)
    assert sec.count('class="ratepick"') == 3 and 'name="level" value="episode"' in sec
    assert "Colin from Accounts · S01E08 · High Needs People<" in sec and "Heat" not in sec
    assert films.count('class="ratepick"') == 1 and "Heat" in films


def test_section_is_absent_when_nothing_waits(env):
    build, _ = env
    with build(jelly_data([])) as client:
        for path in ("/media/movies/to-rate", "/media/tv/to-rate"):
            html = client.get(path).text
            assert section(html) is None and "ratepick" not in html, path
            assert "Nothing waiting to be rated" not in html
    media_db.set_rating("tmdb:4", 7, "movie", "Already Rated")
    media_db.set_rating("tmdb:1", 8, "movie", "Heat")                  # every film waiting is now rated
    with build() as client:
        assert section(client.get("/media/movies/to-rate").text) is None
        assert section(client.get("/media/tv/to-rate").text) is not None        # the show still waits


@pytest.mark.parametrize("back", ["/media/movies/to-rate", "/media/tv/to-rate"])
def test_plain_form_rating_returns_to_the_same_page_and_the_row_is_gone(env, back):
    build, _ = env
    media_db.set_rating("tmdb:4", 7, "movie", "Already Rated")         # one row left on each page
    with build() as client:
        sec = section(client.get(back).text)
        key = "tmdb:1" if back == "/media/movies/to-rate" else "jf:s1"
        kind = "movie" if back == "/media/movies/to-rate" else "tv"
        form = {"item_key": key, "kind": kind, "title": "x", "score": "7", "back": back}
        r = client.post("/media/rate", data=form, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == back
        assert sec is not None and section(client.get(back).text) is None
    assert media_db.get_ratings([key]) == {key: 7}


def test_back_is_a_fixed_list_never_an_open_redirect(env):
    build, _ = env
    with build() as client:
        for back in ("https://evil.example/", "//evil.example", "/media/movies/../x", "/a/alpha", ""):
            r = client.post("/media/rate", data={"item_key": "tmdb:1", "kind": "movie", "title": "Heat",
                                                 "score": "5", "back": back}, follow_redirects=False)
            assert r.status_code == 303 and r.headers["location"] == "/media/history", back
        r = client.post("/media/rate", data={"item_key": "tmdb:1", "kind": "movie", "title": "Heat", "score": "5",
                                             "back": "/media/tv"}, headers=HX)
        assert r.status_code == 200 and "Rated 5 out of 10" in r.text        # htmx: the in-place rated row, as on History


def test_history_inbox_rows_carry_no_back(env):
    build, _ = env
    media_db.set_rating("tmdb:4", 7, "movie", "Already Rated")
    with build() as client:
        html = client.get("/media/history").text
    assert 'name="back"' not in html and html.count('class="ratepick"') == 2


def test_her_view_sees_her_own_waiting_rows(her_env):
    media_db.set_rating("tmdb:202", 7, "movie", "Paper Lanterns")    # B. rated it; she has not
    with her_env() as client:
        her = client.get("/media/movies/to-rate?owner_view=her").text
        her_tv = client.get("/media/tv/to-rate?owner_view=her").text
        you = client.get("/media/movies/to-rate?owner_view=you").text
    her_sec = section(her)
    assert "Paper Lanterns" in her_sec and "Harbour Lights" not in her_sec
    assert "Garden Lane" in section(her_tv)
    you_sec = section(you)
    assert "Harbour Lights" in you_sec and "Paper Lanterns" not in you_sec
    media_db.set_rating("tmdb:202", 4, "movie", "Paper Lanterns", owner="her")
    with her_env() as client:
        assert section(client.get("/media/movies/to-rate?owner_view=her").text) is None


# ---- merged from test_media_ux4_to_rate_tab.py ----
# media-ux4 item 7 (2026-10-08): "To rate" is a TAB next to Tonight in the Movies and TV Shows tab rows
# (My films · Watchlist · Tonight · To rate), at /media/movies/to-rate and /media/tv/to-rate, with an amber count when
# something waits; the To rate section left the top of the list pages; a plain-form rating returns to the tab.
# nav-tidy (2026-10-13, B.): the rows are now My films|My shows · To rate · Awards (Watchlist and Tonight left the nav),
# and every label is sentence case ("To rate").


def subtabs(html):
    """[(label, href, current, count)] of the second (sub-section) tab row."""
    nav = html.split('<nav class="sectabs sub"', 1)[1].split("</nav>", 1)[0]
    out = []
    for href, cur, inner in re.findall(r'<a href="([^"]+)"( aria-current="page")?>(.*?)</a>', nav, re.S):
        count = re.search(r'<span class="waitcount">(\d+)<span class="vh"> ([a-z ]+)</span>', inner)
        out.append((inner.split("<", 1)[0].strip(), href, bool(cur), (int(count.group(1)), count.group(2)) if count else None))
    return out


def test_sections_list_to_rate_after_the_list_tab():
    tabs = {s["id"]: s["tabs"] for s in media_nav.SECTIONS}
    # Awards (2026-10-08) follows To rate: the pair is read at its place, not at the end of the row
    assert tabs["movies"][0:2] == [("My films", "/media/movies"), ("To rate", "/media/movies/to-rate")]
    assert tabs["tv"][0:2] == [("My shows", "/media/tv"), ("To rate", "/media/tv/to-rate")]


def test_tab_row_carries_the_to_rate_count_per_kind(env):
    build, _ = env
    with build() as client:
        films = subtabs(client.get("/media/movies").text)
        tv = subtabs(client.get("/media/tv").text)
    assert [t[0] for t in films] == ["My films", "To rate", "Awards"]   # nav-tidy (2026-10-13)
    assert films[1] == ("To rate", "/media/movies/to-rate", False, (2, "to rate"))   # Heat + Already Rated
    assert films[0][2] is True                                                       # My films is current
    assert tv[1] == ("To rate", "/media/tv/to-rate", False, (1, "to rate"))           # Quiet Show (show level)


def test_tab_page_is_current_and_lists_its_kind(env):
    build, _ = env
    with build() as client:
        html = client.get("/media/movies/to-rate").text
    tabs = subtabs(html)
    assert [t[0] for t in tabs if t[2]] == ["To rate"]
    body = main_of(html)
    assert '<div class="listbox libposters">' in body or '<div class="listbox">' in body
    assert body.count('class="ratepick"') == 2 and "Heat" in body and "Quiet Show" not in body
    assert "2 films watched in the last 30 days, not rated yet" in body


def test_tv_tab_count_follows_the_owner_level(env):
    build, _ = env
    media_db.set_setting("you", "rating_level", "episode")
    with build(jelly_data(TV)) as client:
        tv = subtabs(client.get("/media/tv/to-rate").text)
        body = main_of(client.get("/media/tv/to-rate").text)
    assert tv[1][3] == (3, "to rate") and tv[1][2] is True   # [1]: To rate sits before Awards (nav-tidy 2026-10-13)
    assert body.count('name="level" value="episode"') == 3 and "3 titles watched" in body


def test_tab_shows_without_a_count_when_nothing_waits(env):
    build, _ = env
    with build(jelly_data([])) as client:
        films = client.get("/media/movies/to-rate").text
        tv = client.get("/media/tv/to-rate").text
    for html in (films, tv):
        assert subtabs(html)[1][0] == "To rate" and subtabs(html)[1][3] is None
        assert '<p class="empty">Nothing to rate.</p>' in main_of(html) and "ratepick" not in main_of(html)


@pytest.mark.parametrize("path", ["/media/movies", "/media/tv"])
def test_list_pages_no_longer_hold_a_to_rate_section(env, path):
    build, _ = env
    with build() as client:
        body = main_of(client.get(path).text)
    assert "ratepick" not in body and ">To rate · " not in body


def test_rate_back_allows_the_tabs_and_keeps_the_list_pages():
    for p in ("/media/movies/to-rate", "/media/tv/to-rate", "/media/movies", "/media/tv", "/media/history"):
        assert media_write.RATE_BACK[p] == p


def test_htmx_rating_on_the_tab_swaps_in_place(env):
    build, _ = env
    with build() as client:
        r = client.post("/media/rate", headers=HX, data={"item_key": "tmdb:1", "kind": "movie", "title": "Heat",
                                                         "score": "8", "back": "/media/movies/to-rate"})
        assert r.status_code == 200 and "Rated 8 out of 10" in r.text and "<html" not in r.text
        films = subtabs(client.get("/media/movies").text)
    assert films[1][3] == (1, "to rate")                                              # one fewer waiting


def test_to_rate_tab_label_and_body_copy_are_sentence_case(env):
    """nav-tidy (2026-10-13, B.), superseding awards-year's "To Rate" (2026-10-09): the tab reads "To rate" on Movies,
    TV shows and Activity (and the tab pages' <title>); the count's screen-reader words and "Nothing to rate." too."""
    build, _ = env
    with build(jelly_data([])) as client:
        films = client.get("/media/movies/to-rate").text
        diary = client.get("/media/history").text
    labels = {s["id"]: [t[0] for t in s["tabs"] if t[0].lower() == "to rate"] for s in media_nav.SECTIONS}
    assert labels["movies"] == labels["tv"] == labels["server"] == ["To rate"]
    assert "<title>To rate · Joey</title>" in films and "<title>To rate · Joey</title>" in diary
    assert ">To Rate" not in films and ">To Rate" not in diary
    assert [t[0] for t in subtabs(diary) if t[2]] == ["To rate"]
    assert '<p class="empty">Nothing to rate.</p>' in main_of(films)
    assert '<div class="seclabel">To rate</div>' in main_of(diary)
