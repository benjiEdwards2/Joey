"""JY-190 (Y1, TV UI review 2026-10-23): the Diary's month card on a friend's screen counts the friend's own rows.

It read the household's diary and plays (5 films, 136 episodes, 39h on the friend's TV) while the line under it said
"0 this week". A friend must never see a household number: the card, and Wrapped's summary under it, read only the
rows owned by the friend's `jf:<id>`. The private front is unchanged (you / her / both)."""
import re
from contextlib import closing
from datetime import date, timedelta

from hub import media_store, media_wrapped
from tests.hub.fake_jellyfin import FRIEND_ID
from tests.hub.guest_pages import guest_client, sign_in
from tests.hub.helpers import diary, eps, jelly, local, play, wrap  # noqa: F401  (wrap: the fixture)

FRIEND = "jf:" + FRIEND_ID
OTHER = "jf:" + "beef" * 8


def household_month(day: date) -> None:
    """The household's October: 3 films, 4 episodes, 3 recorded plays (one on a busy Wednesday evening)."""
    for i, title in enumerate(("Anora", "Old Film", "Mid Film")):
        diary(f"tmdb:{i + 1}", "movie", title, (day - timedelta(days=i)).isoformat(), owner="you" if i else "her")
    eps("jf:" + "5e5e" * 8, "House Show", [(day - timedelta(days=i)).isoformat() for i in range(4)])
    for i in range(3):
        play(f"h{i}", "movie", "Anora", local(day - timedelta(days=i), 20), 130, runtime=139)


def test_a_friends_month_card_counts_only_their_rows(wrap):
    build, _ = wrap
    today = media_wrapped._now().date()
    with build():
        media_store.connect().close()
        household_month(today)
        diary("tmdb:603", "movie", "Friend Film", today.isoformat(), owner=FRIEND)
        diary("tmdb:604", "movie", "Other Friend Film", today.isoformat(), owner=OTHER)
        play("f1", "movie", "Friend Film", local(today, 21), 100, runtime=100, owner=FRIEND, item_key="tmdb:603")
        card = media_wrapped.month_card(FRIEND, jelly())
        house = media_wrapped.month_card("both", jelly())
    s = card["s"]
    assert card["label"] == "This month"
    assert (s["films"], s["episodes"], s["days"]) == (1, 0, 1)
    assert s["minutes"] == 100 and s["hours_text"] == "1h 40m"
    assert (house["s"]["films"], house["s"]["episodes"]) == (3, 4)          # the private front's both view: unchanged


def test_a_friend_with_no_rows_sees_no_household_month(wrap):
    build, _ = wrap
    today = media_wrapped._now().date()
    with build():
        media_store.connect().close()
        household_month(today)
        card = media_wrapped.month_card(FRIEND, jelly())
    assert card["s"] is None and card["label"].endswith("nothing yet")


def test_the_friends_diary_page_never_shows_household_numbers(monkeypatch, tmp_path):
    today = date(2026, 10, 13)
    monkeypatch.setattr(media_wrapped, "_now", lambda: local(today, 20))
    client, fake = guest_client(monkeypatch, tmp_path, {"jellyfin": jelly()})
    with client as c:
        sign_in(c, fake, FRIEND_ID)
        media_store.connect().close()
        household_month(today)
        diary("tmdb:603", "movie", "Friend Film", today.isoformat(), owner=FRIEND)
        html = c.get("/media/diary").text
    card = html.split('class="panel monthcard"', 1)[1].split("</section>", 1)[0]
    stats = dict(re.findall(r'class="microlabel">([^<]+)</div><div class="stat-[a-z]+[^"]*">([^<]+)<', card))
    assert stats["Films"] == "1" and stats["Episodes"] == "0" and stats["Days watched"] == "1", stats
    assert "Anora" not in html and "House Show" not in html


def test_the_private_views_still_read_their_own_rows(wrap):
    build, _ = wrap
    today = media_wrapped._now().date()
    with build():
        media_store.connect().close()
        household_month(today)
        diary("tmdb:603", "movie", "Friend Film", today.isoformat(), owner=FRIEND)
        you, her = media_wrapped.month_card("you", jelly()), media_wrapped.month_card("her", jelly())
    assert (you["s"]["films"], you["s"]["episodes"]) == (2, 4)
    assert (her["s"]["films"], her["s"]["episodes"]) == (1, 0)
    with closing(media_store.reader()) as db:
        assert db.execute("SELECT COUNT(*) FROM diary WHERE owner = ?", (FRIEND,)).fetchone()[0] == 1


def test_a_friends_shows_carry_no_household_progress_words(wrap):
    """Review should-fix (2026-10-25): the progress words ("6 left · ~4h 30m") come from the household's Jellyfin list,
    so on a friend's card they would be B.'s state. A friend's shows carry none."""
    build, _ = wrap
    today = media_wrapped._now().date()
    with build():
        media_store.connect().close()
        eps("tmdb:100", "Quiet Show", [today.isoformat(), (today - timedelta(days=1)).isoformat()], owner=FRIEND)
        w = media_wrapped.summary(FRIEND, jelly(), today.year)
        you = media_wrapped.summary("you", jelly(), today.year)
    assert [(g["title"], g["episodes"], g["progress"]) for g in w["shows"]] == [("Quiet Show", 2, None)]
    assert you["shows"] == []


def test_a_friends_summary_never_carries_the_households_earliest_date(wrap):
    """JY-247: `recorder_start` was the household's earliest play; a friend's is their own, or None with no plays."""
    build, _ = wrap
    today = media_wrapped._now().date()
    early = date(today.year, 1, 3)
    with build():
        media_store.connect().close()
        play("h0", "movie", "Anora", local(early, 20), 130, runtime=139)
        play("f1", "movie", "Friend Film", local(today, 21), 100, runtime=100, owner=FRIEND, item_key="tmdb:603")
        mine = media_wrapped.summary(FRIEND, jelly(), today.year)
        none = media_wrapped.summary("jf:" + "cafe" * 8, jelly(), today.year)
        house = media_wrapped.summary("both", jelly(), today.year)
    assert mine["recorder_start"] == today
    assert none["recorder_start"] is None
    assert house["recorder_start"] == early                                  # the private front: unchanged
