"""media-ux4 item 5c (2026-10-08, regression): an episode page of a fully watched show (Ted Lasso S04E07, banner "10 of
10 watched") showed "Mark watched" in the hero. The hero read the episode's OWN item (its own 10-minute cache entry)
while the banner and the episode rows read the show's season list (a different cache entry, read at another time), so
the two could disagree. The hero now takes the episode's state from the same season list the banner counts — matched
by id, else by season + episode number (a duplicate Jellyfin item) — and acts on that episode's id."""
import copy

import pytest

import tests.hub.test_media_item as tmi
from tests.hub.test_media_watched import hero_btns, wenv  # noqa: F401  (fixture)
from tests.hub.test_media_resume import env, main_of  # noqa: F401  (fixture)

TICKS = tmi.TICKS


@pytest.fixture()
def all_watched():
    """Season 4 fully watched in the show's season list (the banner says 3 of 3 watched). The fakes hold the SAME
    list object, so it is swapped in place and restored."""
    saved = tmi.EPISODES[:]
    tmi.EPISODES[:] = [tmi.ep(i, f"E{i}", True) for i in range(1, 4)]
    yield
    tmi.EPISODES[:] = saved


def test_hero_follows_the_season_list_when_the_episode_read_is_stale(wenv, all_watched, monkeypatch):
    monkeypatch.setitem(tmi.ITEMS, "ep3", {**copy.deepcopy(tmi.ITEMS["ep3"]),
                                           "UserData": {"Played": False, "PlaybackPositionTicks": 0}})
    client, _, _ = wenv()
    with client:
        b = main_of(client.get("/media/item/ep3").text)
    assert "3 of 3 watched" in b
    btns = hero_btns(b)
    assert 'action="/media/resume/ep3/unwatched"' in btns and ">Mark unwatched</button>" in btns
    assert ">Mark watched</button>" not in btns and "Play again ▶" in btns


def test_stale_in_progress_episode_read_offers_no_move_on_pair(wenv, all_watched, monkeypatch):
    monkeypatch.setitem(tmi.ITEMS, "ep3", {**copy.deepcopy(tmi.ITEMS["ep3"]),
                                           "UserData": {"Played": False, "PlaybackPositionTicks": 9 * TICKS}})
    client, _, _ = wenv()
    with client:
        btns = hero_btns(main_of(client.get("/media/item/ep3").text))
    assert "/media/resume/ep3/reset" not in btns and ">Mark unwatched</button>" in btns


def test_a_duplicate_episode_item_takes_the_listed_episodes_state_and_id(wenv, all_watched, monkeypatch):
    monkeypatch.setitem(tmi.ITEMS, "ep3dup", {**copy.deepcopy(tmi.ITEMS["ep3"]), "Id": "ep3dup",
                                              "UserData": {"Played": False, "PlaybackPositionTicks": 0}})
    client, _, _ = wenv()
    with client:
        btns = hero_btns(main_of(client.get("/media/item/ep3dup").text))
    assert 'action="/media/resume/ep3/unwatched"' in btns and ">Mark unwatched</button>" in btns


def test_unwatched_episode_still_offers_mark_watched_on_itself(wenv, monkeypatch):
    monkeypatch.setitem(tmi.ITEMS, "ep5", {**copy.deepcopy(tmi.ITEMS["ep3"]), "Id": "ep5", "IndexNumber": 5,
                                           "UserData": {"Played": False, "PlaybackPositionTicks": 0}})
    client, _, _ = wenv()
    with client:
        btns = hero_btns(main_of(client.get("/media/item/ep5").text))
    assert 'action="/media/resume/ep5/watched"' in btns and ">Mark watched</button>" in btns
