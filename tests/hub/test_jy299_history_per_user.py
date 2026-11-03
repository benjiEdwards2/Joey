"""JY-299 (B., 2026-11-02: "Ensure History is linked to the user connecting to the hub media. I am the only one that
can see everything."). History (/media/history -> /media/diary since JY-298) and Play stats (/media/server/history):
a friend sees only their own rows (their History built from their recorded plays), owner "you" sees everyone's with
each row named, her stays her own, the TV (media front + TV user agent) follows the same rule, and no identity or a
query string / cookie never widens anything."""
from datetime import datetime, timedelta, timezone

import pytest

from hub import guest, media_db, media_plays_db
from tests.hub.fake_jellyfin import ALIAS_ID, FRIEND_ID, OTHER_ID
from tests.hub.test_guest_owner import client, fake, sign_in  # noqa: F401 - the media-front fixtures
from tests.hub.test_media_plays import env  # noqa: F401 - the private-front page fixture

FRIEND = f"jf:{FRIEND_ID}"
OTHER = f"jf:{OTHER_ID}"
TV = {"user-agent": "Mozilla/5.0 " + guest.TV_UA_TOKEN}


def _plays():
    now = datetime.now(timezone.utc) - timedelta(hours=2)
    for owner, name, title, jf in (("you", "Sample Admin", "B Film", "b1"), ("her", "Sample Partner", "G Film", "g1"),
                                   (FRIEND, "Sample Friend", "F Film", "f1"), (OTHER, "Other Friend", "O Film", "o1")):
        base = {"user_name": name, "owner": owner, "jf_id": jf, "kind": "movie", "title": title,
                "item_key": f"jf:{jf * 16}"[:35], "runtime_min": 100}
        media_plays_db.record_sighting({**base, "position_pct": 2}, now)
        media_plays_db.record_sighting({**base, "position_pct": 95}, now + timedelta(minutes=95))


def test_recent_finished_reads_one_friend_only_and_fails_closed():
    _plays()
    assert [p["title"] for p in media_plays_db.recent_finished(FRIEND)] == ["F Film"]
    for bad in ("you", "her", "both", None, "jf:bad", ""):
        assert media_plays_db.recent_finished(bad) == []


def test_friend_history_lists_their_own_plays_to_rate_and_nobody_elses(client, fake):
    _plays()
    for headers in ({}, TV):
        sign_in(client, fake, FRIEND_ID)
        for q in ("", "?owner_view=you", "?owner=you", "?owner_view=both"):
            body = client.get("/media/diary" + q, headers=headers).text
            assert "F Film" in body, (headers, q)
            assert not any(t in body for t in ("B Film", "G Film", "O Film", "Other Friend", "Sample Admin")), q
        stats = client.get("/media/server/history?w=all", headers=headers)   # Play stats is private-front only
        assert stats.status_code == 404 and "Other Friend" not in stats.text


def test_the_owner_sees_everyone_named_on_history_and_play_stats(client, fake):
    _plays()
    for t in (("F Film", FRIEND), ("O Film", OTHER), ("G Film", "her")):
        media_db.add_manual_watch("tmdb:9" + str(len(t[0])) + t[1][-1], "movie", t[0] + " Logged",
                                  watched_on=datetime.now(timezone.utc).date().isoformat(), owner=t[1])
    for headers in ({}, TV):
        sign_in(client, fake, ALIAS_ID)
        diary = client.get("/media/diary", headers=headers).text
        assert all(f"{t} Logged" in diary for t in ("F Film", "O Film", "G Film"))
        assert "Sample Friend" in diary and "Other Friend" in diary


def test_no_identity_on_the_media_front_reads_nothing(client, fake):
    _plays()
    client.cookies.clear()
    for path in ("/media/diary", "/media/server/history?w=all", "/media/diary?owner_view=you"):
        body = client.get(path, follow_redirects=False).text
        assert not any(t in body for t in ("F Film", "B Film", "O Film", "Sample Friend")), path


def test_play_stats_owner_sees_everyone_named_others_only_their_own():
    from hub import media_plays
    _plays()
    you = media_plays.history_context("all", "you")
    assert you["stats"]["plays"] == 4
    assert {p["who"] for p in you["people"]} >= {"You", "Sample Friend", "Other Friend"} and len(you["people"]) == 4
    for view, plays in (("her", 1), (FRIEND, 1), ("both", 2)):
        ctx = media_plays.history_context("all", view)
        assert ctx["stats"]["plays"] == plays and ctx["people"] == [], view
        assert "by_person" not in ctx["stats"]
    assert media_plays.history_context("all", "jf:bad")["stats"]["plays"] == 0


def test_play_stats_page_names_people_for_the_owner_only(env):
    from fastapi.testclient import TestClient
    from tests.hub.test_media_her import main_html
    _plays()
    with TestClient(env.app) as c:
        you = main_html(c.get("/media/server/history?w=all&owner_view=you").text)
        her = main_html(c.get("/media/server/history?w=all&owner_view=her").text)
    assert ">By person<" in you and "Sample Friend" in you and "Other Friend" in you
    assert ">By person<" not in her and "Sample Friend" not in her and "F Film" not in her


def test_scope_is_everyone_for_you_only():
    assert media_db.diary_scope("you") == "everyone"
    assert media_db.diary_scope("her") == "mine" and media_db.diary_scope(FRIEND) == "mine"
    media_db.set_setting("her", "diary_scope", "everyone")
    assert media_db.diary_scope("her") == "mine"
