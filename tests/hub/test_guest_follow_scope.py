"""JY-251 (2026-10-25): Follow is a household control (Q19). Follows have no owner (media_follows), so a friend on the
media front must see neither the household's follow state nor a Follow control, on any page, and must never change the
household's follows. The TV session showed "Following George Kay ✓" on Lupin's Created by row as joeytest
(hub/templates/_film_makers.html drew the row with no front check). Fixture names are invented."""
import sqlite3
from contextlib import closing

import pytest

from hub import guest, media_follow
from hub.identity import Identity
from tests.hub.film_page import whole
from tests.hub.helpers import env  # noqa: F401
from tests.hub.test_media_follow_shows import seed_creator, son_env  # noqa: F401

FRIEND = Identity(owner="jf:" + "f00d" * 8, name="Sample Friend", jf_user_id="f00d" * 8)
SAME_ORIGIN = {"Origin": "http://testserver"}
WRITES = ["/media/follow/person/77", "/media/follow/person/77/unfollow", "/media/follow/person/88",
          "/media/follow/collection/9", "/media/follow/collection/9/unfollow", "/media/follow/show/100",
          "/media/follow/show/100/unfollow", "/media/follow/show/101"]


def household_follows():
    """The household follows Cass Creator (as a TV maker), the Harbour series and Quiet Show."""
    media_follow.follow("person", 77, "Cass Creator", dept=media_follow.CREATOR)
    media_follow.follow("collection", 9, "Harbour Collection")
    media_follow.follow("show", 100, "Quiet Show")


def rows():
    with closing(media_follow.ensure()) as db:
        return sorted(tuple(r) for r in db.execute("SELECT kind, tmdb_id, name, dept FROM media_follows"))


@pytest.fixture()
def private(son_env):
    client, both, _son, _ = son_env()
    seed_creator(both)
    with client:
        household_follows()
        yield client


@pytest.fixture()
def friend(private, monkeypatch):
    monkeypatch.setenv("JOEY_FRONT", "media")
    monkeypatch.setattr(guest, "identity_provider", lambda scope: FRIEND)
    return private


def created_by(page: str) -> str:
    return page.split('<div class="microlabel">Created by</div>', 1)[1].split("</section>", 1)[0]


def test_private_front_still_shows_the_households_creator_follow(private):
    row = created_by(whole(private, "/media/title/tv/100"))
    assert "Following Cass Creator ✓" in row


def test_friend_show_title_has_no_creator_follow_state_or_button(friend):
    page = whole(friend, "/media/title/tv/100")
    assert "Cass Creator" in created_by(page)                       # the card still shows
    assert "Following Cass Creator" not in page
    assert "Follow Cass Creator" not in page
    assert "/media/follow" not in page


def test_friend_makers_part_alone_has_no_follow(friend):
    """The Created by row is a deferred part; the part URL itself (GUEST) carries no follow either."""
    r = friend.get("/media/title/tv/100/part/makers")
    assert r.status_code == 200
    assert "Following" not in r.text and "/media/follow" not in r.text


@pytest.mark.parametrize("path", ["/media/title/tv/100", "/media/title/movie/603", "/media/person/77"])
def test_friend_pages_carry_no_household_follow_state(friend, path):
    assert friend.get(path).status_code == 200, path
    page = whole(friend, path)
    assert "Following" not in page, path
    assert "/media/follow" not in page, path


def test_private_library_show_item_shows_the_households_creator_follow(private):
    """Control for the item tests below: the library show item (ser1 = TMDB 100) draws the Created by Follow row."""
    assert "Following Cass Creator ✓" in whole(private, "/media/item/ser1")


def test_friend_library_show_item_has_no_creator_follow(friend):
    page = whole(friend, "/media/item/ser1")
    assert "Following" not in page and "Follow Cass Creator" not in page and "/media/follow" not in page


def test_friend_item_makers_part_alone_has_no_follow(friend):
    r = friend.get("/media/item/ser1/part/makers")
    assert r.status_code == 200
    assert "Following" not in r.text and "/media/follow" not in r.text


@pytest.mark.parametrize("path", ["/", "/media/discover"])
def test_friend_home_and_discover_have_no_follow_shelf(friend, path):
    r = friend.get(path)
    assert r.status_code == 200, path
    assert "people you follow" not in r.text and "Following" not in r.text and "/media/follow" not in r.text


@pytest.mark.parametrize("path", WRITES)
def test_friend_cannot_write_household_follows(friend, path):
    before = rows()
    r = friend.post(path, data={"back": "/media/title/tv/100", "name": "X", "tv": "1"}, headers=SAME_ORIGIN,
                    follow_redirects=False)
    assert r.status_code == 404, (path, r.status_code)
    assert rows() == before, path


def test_follow_routes_are_private_on_the_media_front():
    for path in WRITES:
        assert not guest.allows("POST", path), path
