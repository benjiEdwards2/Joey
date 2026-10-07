"""media-ux2 item 2 (2026-10-08): a "To rate" section at the top of /media/movies and /media/tv, reusing the
Diary > To rate inbox (_to_rate) and the POST /media/rate route. Films page: films only; TV page: shows / seasons /
episodes per the owner's level. Absent when nothing waits; a plain-form rating returns to the same page."""
import pytest

from hub import media_db
from tests.hub.test_media_her import env as her_env, main_html  # noqa: F401  (fixture)
from tests.hub.test_media_rate import env, jelly_data, main_of, TV, HX  # noqa: F401  (env fixture)


def section(html):
    """The To rate section of a library page, or None when the page has none."""
    body = main_of(html)
    if ">To rate · " not in body:
        return None
    return body.split(">To rate · ", 1)[1].split("</section>", 1)[0]


def test_films_page_lists_only_films_waiting(env):
    build, _ = env
    media_db.set_rating("tmdb:4", 7, "movie", "Already Rated")
    with build() as client:
        sec = section(client.get("/media/movies").text)
    assert sec is not None and sec.startswith("1<")                    # "To rate · 1"
    assert sec.count('class="ratepick"') == 1 and "Heat" in sec
    assert "Quiet Show" not in sec and "Already Rated" not in sec and "Long Ago" not in sec
    assert 'name="kind" value="movie"' in sec and 'name="back" value="/media/movies"' in sec
    assert 'hx-post="/media/rate"' in sec


def test_tv_page_lists_only_tv_at_the_owner_level(env):
    build, _ = env
    with build() as client:
        sec = section(client.get("/media/tv").text)
    assert sec.count('class="ratepick"') == 1 and "Quiet Show" in sec and "Heat" not in sec
    assert 'name="back" value="/media/tv"' in sec and 'name="item_key" value="jf:s1"' in sec
    media_db.set_setting("you", "rating_level", "episode")
    with build(jelly_data(TV)) as client:
        sec = section(client.get("/media/tv").text)
        films = section(client.get("/media/movies").text)
    assert sec.count('class="ratepick"') == 3 and 'name="level" value="episode"' in sec
    assert "Colin from Accounts · S01E08 · High Needs People<" in sec and "Heat" not in sec
    assert films.count('class="ratepick"') == 1 and "Heat" in films


def test_section_is_absent_when_nothing_waits(env):
    build, _ = env
    with build(jelly_data([])) as client:
        for path in ("/media/movies", "/media/tv"):
            html = client.get(path).text
            assert section(html) is None and "ratepick" not in html, path
            assert "Nothing waiting to be rated" not in html
    media_db.set_rating("tmdb:4", 7, "movie", "Already Rated")
    media_db.set_rating("tmdb:1", 8, "movie", "Heat")                  # every film waiting is now rated
    with build() as client:
        assert section(client.get("/media/movies").text) is None
        assert section(client.get("/media/tv").text) is not None        # the show still waits


@pytest.mark.parametrize("back", ["/media/movies", "/media/tv"])
def test_plain_form_rating_returns_to_the_same_page_and_the_row_is_gone(env, back):
    build, _ = env
    media_db.set_rating("tmdb:4", 7, "movie", "Already Rated")         # one row left on each page
    with build() as client:
        sec = section(client.get(back).text)
        key = "tmdb:1" if back == "/media/movies" else "jf:s1"
        kind = "movie" if back == "/media/movies" else "tv"
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
        her = main_html(client.get("/media/movies?owner_view=her").text)
        her_tv = main_html(client.get("/media/tv?owner_view=her").text)
        you = main_html(client.get("/media/movies?owner_view=you").text)
    her_sec = her.split(">To rate · ", 1)[1].split("</section>", 1)[0]
    assert "Paper Lanterns" in her_sec and "Harbour Lights" not in her_sec
    assert "Garden Lane" in her_tv.split(">To rate · ", 1)[1].split("</section>", 1)[0]
    you_sec = you.split(">To rate · ", 1)[1].split("</section>", 1)[0]
    assert "Harbour Lights" in you_sec and "Paper Lanterns" not in you_sec
    media_db.set_rating("tmdb:202", 4, "movie", "Paper Lanterns", owner="her")
    with her_env() as client:
        assert ">To rate · " not in main_html(client.get("/media/movies?owner_view=her").text)
