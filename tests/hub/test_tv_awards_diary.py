"""JY-196 (U10, B.'s Gate 1 2026-10-25: "3B · 5A"): Awards and the Diary on the friends' TV.

3B: Awards get a TV view (ceremony chips, the edition line, one poster shelf per category group, gold win chips, On Joey /
Not on Joey) - no picker sheet, no <select>, no <details>, no filter chips. 5A: a slim friend-only Diary (one-row month
card, big All / Films / TV chips, no Log a watch, "OK to rate" folds the 1-10 strip). TV mode only: desktop and phone
render as before. Friends never see household numbers or titles."""
import re
from contextlib import closing
from datetime import date

import pytest

from hub import media_awards_db as adb, media_awards_pages as ap, media_home, media_store, media_wrapped
from tests.hub.fake_jellyfin import FRIEND_ID
from tests.hub.guest_pages import TV_UA, guest_client, sign_in
from tests.hub.helpers import diary, jelly, local, play
from tests.hub.test_awards_db import seed_oscars
from tests.hub.test_guest_month_card import household_month
from tests.hub.tv_css import design_px

FRIEND = "jf:" + FRIEND_ID
TV = {"User-Agent": TV_UA}


@pytest.fixture()
def friend(monkeypatch, tmp_path):
    client, fake = guest_client(monkeypatch, tmp_path, {"jellyfin": jelly()})
    with client as c:
        sign_in(c, fake, FRIEND_ID)
        yield c


def main_of(html: str) -> str:
    return html.split("<main", 1)[1].split("</main>", 1)[0]


def seeded():
    with closing(adb.ensure()) as db:
        seed_oscars(db)


# ---- Awards (3B) ----

def test_the_ballot_carries_one_shelf_per_category_group():
    seeded()
    c = ap.awards_ctx("movie", "", "", False, {"movies": [{"item_key": "tmdb:11", "jf_id": "jfalpha", "title": "Alpha",
                                                          "poster": "jf:jfalpha", "year": 2024}]}, FRIEND)[0]
    shelves = c["ballot"]["shelves"]
    assert [(s["key"], s["label"], [r["title"] for r in s["rows"]]) for s in shelves] == [
        ("headline", "Best Picture", ["Alpha", "Beta", "Delta", "Gamma"]),
        ("acting", "Acting", ["Alpha", "Beta"])]
    alpha = shelves[0]["rows"][0]
    assert (alpha["wins"], alpha["on_server"], alpha["seen"]) == (2, True, False)   # a friend: no seen state
    assert shelves[0]["rows"][1]["on_server"] is False


def test_tv_awards_is_chips_and_shelves(friend):
    seeded()
    main = main_of(friend.get("/media/movies/awards", headers=TV).text)
    chips = re.search(r'<nav class="chips awtv-cer"[^>]*>(.*?)</nav>', main, re.S).group(1)
    first = re.search(r"<a [^>]*>[^<]*</a>", chips).group(0)
    assert "Oscars" in first and 'aria-current="true"' in first and "data-first" in first
    assert "body=globes&amp;year=2025" in chips                                     # ceremony links keep the year
    assert "97th Academy Awards · 2 Mar 2025 · films of 2024" in main
    heads = [re.sub(r"<[^>]+>", "", h) for h in re.findall(r'<h2 class="seclabel">(.*?)</h2>', main, re.S)]
    assert heads == ["Best Picture · 4", "Acting · 2"]
    assert main.count('class="card-poster') == 6
    assert re.search(r'awwin[^>]*>2 wins<', main) and "Not on Joey" in main
    # JY-259 P3 (2026-10-28, Q8 A): the sub-tab fold is the one <details> on the TV page; the awards body has none
    body = re.sub(r'<details class="tv-tabmore".*?</details>', "", main, flags=re.S)
    for gone in ("<select", "<details", "awctl", "awfilters", "Next up", "awsheet", "awfilm"):
        assert gone not in body, gone


def test_tv_awards_draws_the_categories_view(friend):
    # JY-270 P2 (2026-10-29, B. "All recommended"): replaces test_tv_awards_ignores_the_categories_view - the TV now
    # keeps v=categories and draws one shelf per category, the winner first with a gold "Won"
    seeded()
    main = main_of(friend.get("/media/movies/awards?v=categories", headers=TV).text)
    assert "awtv-cer" in main and "awgrid" not in main and "awtv-cat" in main
    heads = [re.sub(r"<[^>]+>", "", h) for h in re.findall(r'<h2 class="seclabel">(.*?)</h2>', main, re.S)]
    assert "Best Actor · 2" in heads and "Best Picture · 4" in heads
    actor = main.split("Best Actor<span", 1)[1].split("</section>", 1)[0]
    assert actor.index("Ann Actor") < actor.index("Bob B") and re.search(r'awwin[^>]*>Won<', actor)
    view = re.search(r'<nav class="chips awtv-view"[^>]*>(.*?)</nav>', main, re.S).group(1)
    assert re.search(r'aria-current="true"[^>]*>Categories<', view) and ">Films<" in view
    assert "awtv-cer" in main_of(friend.get("/media/tv/awards", headers=TV).text)


def test_tv_awards_year_row(friend):
    # JY-270 years (B. 2026-10-30): the stepper + list replace P2's six-chip row
    seeded()
    with closing(adb.ensure()) as db:
        seed_oscars(db, ordinal=96, year=2024, held_on="2024-03-10")
    main = main_of(friend.get("/media/movies/awards?body=oscars&year=2024", headers=TV).text)
    yr = re.search(r'<nav class="chips awtv-yr"[^>]*>(.*?)</nav>', main, re.S).group(1)
    assert re.search(r'<button type="button" class="chip awtv-yrbtn" data-tv-year[^>]*>.*?awtv-yrword">2024<', yr, re.S)
    lst = re.search(r'<div class="awtv-yrlist" id="awtv-yrlist" role="listbox"[^>]*hidden>(.*?)</div>', yr, re.S).group(1)
    assert re.search(r'aria-selected="true">2024<', lst) and ">Latest<" in lst and "year=2025" in lst
    assert "96th Academy Awards" in main
    note = main_of(friend.get("/media/movies/awards?body=oscars&year=2023", headers=TV).text)
    assert "awtv-note" in note and "No Oscars in 2023" in note


def test_tv_year_nav_steps_and_wraps_only_at_the_ends():
    ys = [{"year": y, "href": f"?y={y}", "on": y == 2016, "has_data": y != 2019} for y in range(2025, 2005, -1)]
    mid = ap.tv_year_nav(ys, 2016, {"year": 2025, "href": "?y="})
    assert (mid["year"], mid["prev"], mid["next"]) == (2016, 2015, 2017)
    assert [c["label"] for c in mid["list"]][:3] == ["Latest", "2025", "2024"] and len(mid["list"]) == 21
    assert next(c for c in mid["list"] if c["label"] == "2019")["dim"]
    top = ap.tv_year_nav([{**y, "on": y["year"] == 2025} for y in ys], 2025, None)
    assert (top["prev"], top["next"]) == (2024, 2006) and top["list"][0]["label"] == "2025"   # newest: Right wraps
    low = ap.tv_year_nav([{**y, "on": y["year"] == 2006} for y in ys], 2006, None)
    assert (low["prev"], low["next"]) == (2025, 2007)                                         # oldest: Left wraps
    assert ap.tv_year_nav([], None, None) is None


def test_desktop_awards_is_unchanged(friend):
    seeded()
    main = main_of(friend.get("/media/movies/awards").text)
    assert "awctl" in main and "awfilm" in main and "awtv" not in main


# ---- Diary (5A) ----

def friends_diary(today: date) -> None:
    media_store.connect().close()
    household_month(today)                                            # the household's month: must never show
    diary("tmdb:603", "movie", "Friend Film", today.isoformat(), owner=FRIEND)
    play("f1", "movie", "Friend Film", local(today, 21), 100, runtime=100, owner=FRIEND, item_key="tmdb:603")


def test_tv_diary_is_slim_and_friend_only(friend, monkeypatch):
    today = date(2026, 10, 13)
    monkeypatch.setattr(media_wrapped, "_now", lambda: local(today, 20))
    friends_diary(today)
    main = main_of(friend.get("/media/diary", headers=TV).text)
    card = re.search(r'<section class="panel monthcard tvmonth".*?</section>', main, re.S).group(0)
    words = " ".join(re.sub(r"<[^>]+>", " ", card).split())
    assert words == "This month 1 film 0 episodes 1h 40m watched", words
    assert "Days watched" not in main and "Average score" not in main
    for gone in ("Log a watch", "logwatch", "this week", "all time", "Play stats", "Milestones"):
        assert gone not in main, gone
    assert "Anora" not in main and "House Show" not in main          # no household title
    assert "Friend Film" in main
    fold = re.search(r'<details class="tvrate">\s*<summary[^>]*>OK to rate</summary>(.*?)</details>', main, re.S)
    assert fold and 'class="ratepick"' in fold.group(1)
    assert re.search(r'<nav class="chips diarychips"', main)


def test_desktop_diary_is_unchanged(friend):
    friends_diary(date.today())
    main = main_of(friend.get("/media/diary").text)
    assert "Log a watch" in main and "this week" in main and "tvrate" not in main and "tvmonth" not in main
    assert 'class="panel monthcard"' in main


def test_tv_to_rate_rows_fold_the_strip(friend, monkeypatch):
    rows = [{"item_key": "tmdb:603", "kind": "movie", "title": "Friend Film", "year": 2024, "poster": None,
             "jf_id": None, "when": "Watched 12 Oct", "level": "show"}]
    monkeypatch.setattr(media_home, "_to_rate", lambda recent, ratings: rows)
    tv = main_of(friend.get("/media/history", headers=TV).text)
    assert "Rate TV by" not in tv and "this week" not in tv
    assert re.search(r'<h2 class="seclabel">To rate<span class="sep"> · </span>1</h2>', tv)
    fold = re.search(r'<details class="tvrate">\s*<summary[^>]*>OK to rate</summary>(.*?)</details>', tv, re.S)
    assert fold and 'class="ratepick"' in fold.group(1) and "Skip" in fold.group(1)
    desk = main_of(friend.get("/media/history").text)
    assert "Rate TV by" in desk and "tvrate" not in desk


def test_tv_css_has_the_jy196_block(friend):
    css = design_px(friend.get("/static/tv.css").text)
    block = css.split("==== JY-196 (U10", 1)[1]
    for sel in (".awtv-cer", ".awwin", ".tvmonth", ".diarychips", ".tvrate"):
        assert sel in block, sel
    assert re.search(r"\.awtv-cer\s*\{[^}]*flex-wrap:\s*wrap", block)          # the chips never run past the safe edge

