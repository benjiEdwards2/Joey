"""JY-195 (U9, 2026-10-25): the friends' Home as shelves (B.'s Gate 1 pick "4A") and the TV empty states (E1/E2/Y4).

Home = Continue watching, Recently added, New on Joey this month, Top rated on Joey, Films under 100 minutes, then
Recently watched; an empty shelf is left out. Shelves 3-5 come from the scrubbed snapshot library lists only (no live
call on render, rule 7) and never carry household watch state. A brand-new friend gets a welcome line. On the TV an
empty Watchlist / To rate / Diary / Diary > To rate is one words-first state, not a grey box. Spec:
docs/specs/JY-195-home-shelves.md."""
import re
import sys
from datetime import datetime, timedelta, timezone

import pytest

from hub import guest, media_guest_home
from tests.hub.fake_jellyfin import FRIEND_ID
from tests.hub.guest_pages import TV_UA, guest_client, movie, shelf_titles, sign_in

NOW = datetime.now(timezone.utc)


def ago(days: float) -> str:
    return (NOW - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S.0000000Z")


def film(n: int, title: str, *, days: float = 400, rating=None, minutes=None, **extra) -> dict:
    jf = f"{n:04d}" * 8
    return {"title": title, "jf_id": jf, "item_key": f"tmdb:{9000 + n}", "poster": f"jf:{jf}", "year": 2024,
            "added_at": ago(days), "community_rating": rating, "runtime_min": minutes, **extra}


def show(n: int, title: str, *, days: float = 400, rating=None, episodes=8) -> dict:
    jf = f"5{n:03d}" * 8
    return {"title": title, "jf_id": jf, "item_key": f"tmdb:{8000 + n}", "poster": f"jf:{jf}", "year": 2023,
            "added_at": ago(days), "community_rating": rating, "episodes": episodes}


MOVIES = [
    film(1, "Fresh Film", days=3, rating=6.1, minutes=130),
    film(2, "Short Gem", days=200, rating=8.8, minutes=84),
    film(3, "Short Other", days=300, rating=7.0, minutes=99),
    film(4, "Long Classic", days=500, rating=9.3, minutes=171),
    film(5, "Unrated Short", days=500, rating=None, minutes=90),
    film(6, "Household Watched Film", days=40, rating=7.5, minutes=100,
         played=True, last_played_at="2026-10-20T20:00:00Z", unplayed=0),
]
SHOWS = [show(1, "Fresh Show", days=10, rating=8.1), show(2, "Old Show", days=600, rating=9.0),
         show(3, "Empty Folder Show", days=1, rating=9.9, episodes=0)]
JELLY = {"server_id": "srv-1", "summary": "x", "library": {"movies": 6, "episodes": 20},
         "latest": [{"title": "Fresh Film", "jf_id": "0001" * 8, "item_key": "tmdb:9001", "type": "Movie",
                     "poster": "jf:" + "0001" * 8, "added_at": ago(3)}],
         "movies": MOVIES, "shows": SHOWS,
         "history": {"recent": [{"title": "SENTINEL_HOUSE_HIST", "jf_id": "h1", "kind": "movie", "when": "today"}]},
         "up_next": [{"title": "SENTINEL_HOUSE_UPNEXT", "jf_id": "u1"}],
         "now_playing": [{"title": "SENTINEL_HOUSE_NOW", "user": "SENTINEL_USER", "jf_id": "n1"}]}


@pytest.fixture()
def fc(monkeypatch, tmp_path):
    client, fake = guest_client(monkeypatch, tmp_path, {"jellyfin": JELLY})
    with client as c:
        c.fake = fake
        sign_in(c, fake, FRIEND_ID)
        yield c


def page(c, path, tv=False):
    r = c.get(path, headers={"User-Agent": TV_UA} if tv else {})
    assert r.status_code == 200, path
    return r.text


def main(html: str) -> str:
    return html.split("<main", 1)[1]


def shelf(html: str, title: str) -> str:
    """The HTML of one shelf section, by its heading."""
    for sec in re.findall(r'<section class="sec">(.*?)</section>', main(html), re.S):
        if shelf_titles(sec)[:1] == [title]:
            return sec
    raise AssertionError(f"no shelf {title!r}")


def titles_in(sec: str) -> list[str]:
    return re.findall(r'<span class="row-title">(.*?)</span>', sec)


# ---- the shelves (pure) ----

def test_library_shelves_are_month_top_rated_and_short_films():
    out = {s["id"]: s for s in media_guest_home.library_shelves({"movies": MOVIES, "shows": SHOWS}, NOW)}
    assert [s["title"] for s in out.values()] == ["New on Joey this month", "Top rated on Joey",
                                                   "Films under 100 minutes"]
    assert [i["title"] for i in out["month"]["items"]] == ["Fresh Film", "Fresh Show"]          # newest first, 30 days
    assert out["month"]["items"][0]["sub"].startswith("Added ")
    assert [i["title"] for i in out["top"]["items"]] == ["Long Classic", "Old Show", "Short Gem", "Fresh Show",
                                                         "Household Watched Film", "Short Other", "Fresh Film"]
    assert out["top"]["items"][0]["sub"] == "Film · 9.3" and out["top"]["items"][1]["sub"] == "Show · 9.0"
    assert [i["title"] for i in out["short"]["items"]] == ["Short Gem", "Short Other", "Unrated Short"]
    assert out["short"]["items"][0]["sub"] == "1h 24m"
    every = [i["title"] for s in out.values() for i in s["items"]]
    assert "Empty Folder Show" not in every                                  # not a library title (WP-T1)
    assert all(i["href"] for s in out.values() for i in s["items"])


def test_library_shelves_cap_at_shelf_max_and_drop_empty_ones():
    many = [film(100 + n, f"F{n}", days=1, rating=7, minutes=200) for n in range(40)]
    out = media_guest_home.library_shelves({"movies": many, "shows": []}, NOW)
    assert [s["id"] for s in out] == ["month", "top"]                        # no film under 100 min: left out
    assert all(len(s["items"]) == media_guest_home.SHELF_MAX for s in out)
    assert media_guest_home.library_shelves({}, NOW) == []


# ---- Home, through the media front ----

@pytest.mark.parametrize("tv", [False, True])
def test_a_new_friend_gets_a_welcome_and_the_library_shelves(fc, tv):
    html = page(fc, guest.home_path(), tv)
    assert shelf_titles(html) == ["Recently added", "New on Joey this month", "Top rated on Joey",
                                  "Films under 100 minutes"]                 # >= 4 on the TV, nothing to continue
    body = main(html)
    assert re.search(r'class="welcome"[^>]*>Welcome, [^<]+<span>— here’s what’s on Joey</span>', body)
    assert '<p class="empty">' not in body                                   # no grey box on Home


def test_continue_and_watched_bracket_the_library_shelves_and_drop_the_welcome(fc):
    fc.fake.resume[FRIEND_ID] = [movie("aaaa" * 8, "Friend Resume Film", "603", at_min=30)]
    fc.fake.history[FRIEND_ID] = [movie("eeee" * 8, "Friend Watched Film", "604", played_at=ago(1))]
    media_guest_home.clear_cache()
    html = page(fc, guest.home_path(), tv=True)
    assert shelf_titles(html) == ["Continue watching", "Recently added", "New on Joey this month",
                                  "Top rated on Joey", "Films under 100 minutes", "Recently watched"]
    assert 'class="welcome"' not in html


def test_home_adds_no_live_read(fc):
    page(fc, guest.home_path())
    paths = [c[1] for c in fc.fake.calls if not c[1].startswith("/Users")]   # less the session check
    assert sorted(set(paths)) == ["/Items", "/UserItems/Resume"]           # the two cached per-user reads, no more
    assert len([p for p in paths if p == "/Items"]) == 1


def test_library_shelves_never_carry_household_watch_state(fc):
    html = page(fc, guest.home_path(), tv=True)
    assert "SENTINEL_" not in html and "2026-10-20T20:00:00Z" not in html
    top = shelf(html, "Top rated on Joey")
    assert "Household Watched Film" in top                                   # library-wide: the title is there ...
    marks = top.replace("Household Watched Film", "").lower()
    assert "watched" not in marks and 'class="bar"' not in marks            # ... but nobody's watched mark is


def test_the_page_is_called_home(fc):
    desk = page(fc, guest.home_path())
    assert re.search(r"<title>Home · Joey Media</title>", desk)
    assert ">Home<" in main(desk) and ">Overview<" not in desk


def test_an_empty_library_is_one_words_first_state(monkeypatch, tmp_path):
    client, fake = guest_client(monkeypatch, tmp_path, {"jellyfin": {"latest": [], "movies": [], "shows": []}})
    with client as c:
        sign_in(c, fake, FRIEND_ID)
        html = page(c, guest.home_path(), tv=True)
    assert shelf_titles(html) == [] and 'class="bigempty' in html and '<p class="empty">' not in main(html)


# ---- the TV empty states ----

EMPTY = [("/media/movies/watchlist", "Nothing on your watchlist yet", "Press + Watchlist on any film"),
         ("/media/tv/watchlist", "Nothing on your watchlist yet", "Press + Watchlist on any show"),
         ("/media/movies/to-rate", "Nothing to rate right now", "Films you finish show up here"),
         ("/media/tv/to-rate", "Nothing to rate right now", "Shows you finish show up here"),
         ("/media/history", "Nothing watched yet", "Finish a film or episode and it shows up here"),
         ("/media/diary", "Your diary is empty", "Films and episodes you finish are logged here")]


@pytest.mark.parametrize("path,heading,line", EMPTY)
def test_tv_empty_states_are_words_first_not_a_grey_box(fc, path, heading, line):
    body = main(page(fc, path, tv=True))
    state = re.search(r'<section class="sec bigempty"[^>]*>(.*?)</section>', body, re.S)
    assert state, path
    s = state.group(1)
    assert f'<h2 class="bigempty-h">{heading}</h2>' in s and line in s
    assert re.search(r'<a class="btn btn-primary" href="/media/(movies|tv)">Browse (films|shows)</a>', s)
    assert '<svg class="ic"' in s and "data-first" not in s                  # G3 keeps first focus on the sub-tab
    assert '<p class="empty">' not in body


def test_tv_watchlist_drops_the_private_count_line(fc):
    body = main(page(fc, "/media/movies/watchlist", tv=True))
    assert "on your watchlist ·" not in body and "not on the server" not in body


def test_tv_history_drops_the_rate_tv_by_chips_when_nothing_waits(fc):
    body = main(page(fc, "/media/history", tv=True))
    assert "Rate TV by" not in body and '<h2 class="seclabel">To rate</h2>' not in body


@pytest.mark.parametrize("path", [p for p, _h, _l in EMPTY])
def test_desktop_keeps_its_one_line_empty_state(fc, path):
    assert "bigempty" not in page(fc, path)


def test_the_tv_css_block_for_the_empty_state_and_welcome(fc):
    css = fc.get("/static/tv.css").text
    block = css.split("JY-195", 1)[1]
    for sel in ("html.tv .bigempty", "html.tv .bigempty-h", "html.tv .welcome"):
        assert sel in block, sel
    assert "border:" not in re.search(r"html\.tv \.bigempty \{[^}]*\}", block).group(0)


def test_two_renders_on_one_snapshot_scrub_and_sort_once(fc, monkeypatch):
    # JY-195 review (2026-10-25): the scrub and the library shelves are memoised per snapshot version, view and day
    media_guest_home.clear_cache()
    calls = {"scrub": 0, "shelves": 0}
    real_view, real_shelves = media_guest_home.media_home.view_jelly, media_guest_home.library_shelves

    def view_spy(*a, **kw):
        if sys._getframe(1).f_code.co_name == "_snapshot_view":   # Home's scrub, not other page parts
            calls["scrub"] += 1
        return real_view(*a, **kw)

    def shelves_spy(*a, **kw):
        calls["shelves"] += 1
        return real_shelves(*a, **kw)

    monkeypatch.setattr(media_guest_home.media_home, "view_jelly", view_spy)
    monkeypatch.setattr(media_guest_home, "library_shelves", shelves_spy)
    first, second = page(fc, guest.home_path()), page(fc, guest.home_path())
    assert calls == {"scrub": 1, "shelves": 1}
    assert shelf_titles(first) == shelf_titles(second)
    assert first.count("Long Classic") == second.count("Long Classic") >= 1     # copies: decoration never leaks
