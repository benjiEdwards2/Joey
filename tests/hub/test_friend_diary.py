"""Joey TV WP-B3 step 3 (2026-10-21, Q21 default): the friend diary comes from the play recorder. When a friend's play
(owner `jf:<id>`) closes at >= 90 % (media_plays_db.FINISHED_PCT), the recorder in joey-hub writes ONE diary row owned
by `jf:<id>` - the title's own key, one row per title per day (the diary's UNIQUE), so later polls of the same finished
play add nothing. An 80 % play writes none. You / her keep their diary from the Jellyfin history sweep
(media_db.sync_diary_from_history): the recorder never writes their rows. No per-friend history sweeps."""
from datetime import datetime, timezone

import pytest

from hub import identity, media_db, media_plays
from tests.hub.fake_jellyfin import ALIAS_ID, FRIEND_ID

FRIEND = "jf:" + FRIEND_ID
NOW = datetime(2026, 10, 21, 9, 30, tzinfo=timezone.utc)
TICKS = 600_000_000


@pytest.fixture(autouse=True)
def owners(monkeypatch):
    """The household's Jellyfin ids without a /Users read: the alias user is `you`, anyone else a friend."""
    monkeypatch.setenv("JELLYFIN_USER_ALIASES", "Sample Alias")
    monkeypatch.setattr(identity, "_household", (frozenset({ALIAS_ID}), None))


def session(uid: str, pct: int, *, episode: bool = False) -> dict:
    item = ({"Id": "e1e1" * 8, "Type": "Episode", "Name": "The Fourth", "SeriesName": "Friend Show",
             "SeriesId": "5e5e" * 8, "SeasonId": "5a5a" * 8, "ParentIndexNumber": 1, "IndexNumber": 4,
             "RunTimeTicks": 45 * TICKS} if episode else
            {"Id": "f1f1" * 8, "Type": "Movie", "Name": "Friend Film", "ProviderIds": {"Tmdb": "603"},
             "RunTimeTicks": 100 * TICKS})
    return {"UserId": uid, "UserName": "Sample Friend", "NowPlayingItem": item,
            "PlayState": {"PositionTicks": item["RunTimeTicks"] * pct // 100}}


def poll(monkeypatch, *sessions, now=NOW) -> int:
    monkeypatch.setattr(media_plays, "_creds", lambda: ("http://jellyfin.test:8096", {}))
    monkeypatch.setattr(media_plays.jellyfin, "get", lambda base, headers, path: list(sessions))
    return media_plays.poll_once(now)


def test_a_92_percent_friend_play_writes_one_diary_row(monkeypatch):
    assert poll(monkeypatch, session(FRIEND_ID, 92)) == 1
    rows = media_db.list_diary(owner=FRIEND)
    assert [(r["item_key"], r["kind"], r["title"], r["owner"]) for r in rows] == [("tmdb:603", "movie", "Friend Film",
                                                                                  FRIEND)]
    assert poll(monkeypatch, session(FRIEND_ID, 97)) == 1          # the next poll of the finished play
    assert len(media_db.list_diary(owner=FRIEND)) == 1


def test_a_finished_friend_play_polled_on_is_one_play_row_and_one_diary_row(monkeypatch):
    """playfix (2026-10-21): the polls after the finish line update the finished play, never a second play row, and the
    diary keeps the one row the first finished poll wrote."""
    from datetime import timedelta
    from hub import media_store
    for minute, pct in enumerate((50, 92, 95, 97, 100)):
        assert poll(monkeypatch, session(FRIEND_ID, pct), now=NOW + timedelta(minutes=minute)) == 1
    db = media_store.reader()
    try:
        plays = db.execute("SELECT position_pct, finished FROM play WHERE owner = ?", (FRIEND,)).fetchall()
    finally:
        db.close()
    assert [tuple(p) for p in plays] == [(100, 1)]
    (row,) = media_db.list_diary(owner=FRIEND)
    assert (row["item_key"], row["watched_on"][:10]) == ("tmdb:603", "2026-10-21")


def test_an_80_percent_friend_play_writes_none(monkeypatch):
    poll(monkeypatch, session(FRIEND_ID, 80))
    assert media_db.list_diary(owner=FRIEND) == []


def test_a_friends_finished_episode_is_one_episode_row(monkeypatch):
    poll(monkeypatch, session(FRIEND_ID, 95, episode=True))
    (row,) = media_db.list_diary(owner=FRIEND)
    assert (row["item_key"], row["kind"], row["show_key"], row["season"], row["episode"], row["show_title"],
            row["episode_title"]) == ("jf:" + "e1e1" * 8, "tv", "jf:" + "5e5e" * 8, 1, 4, "Friend Show", "The Fourth")


def test_you_and_her_diaries_are_not_written_by_the_recorder(monkeypatch):
    poll(monkeypatch, session(ALIAS_ID, 95))
    assert media_db.list_diary(owner="you") == [] and media_db.list_diary(owner="her") == []
    assert media_db.list_diary(owner=None) == []


def test_the_history_sweep_still_writes_your_diary():
    n = media_db.sync_diary_from_history([{"item_key": "tmdb:11", "kind": "movie", "title": "Alpha",
                                           "watched_at": "2026-10-20T10:00:00Z"}], owner="you")
    assert n == 1 and [r["item_key"] for r in media_db.list_diary(owner="you")] == ["tmdb:11"]
