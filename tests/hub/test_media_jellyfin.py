"""hub/media_jellyfin.py (W2, M-12): one Jellyfin client — creds, get, and an owner's user id. "her" is exactly
JELLYFIN_USER_HER, never a fallback to the admin; ids are cached per owner and per wanted name."""
import pytest

from hub import media_jellyfin as jf, media_write

USERS = [{"Id": "u-plain", "Name": "Georgina", "Policy": {}},
         {"Id": "u-admin", "Name": "Ben", "Policy": {"IsAdministrator": True}}]


@pytest.fixture()
def users(monkeypatch):
    jf.clear_cache()
    calls = []
    monkeypatch.delenv("JELLYFIN_USER", raising=False)
    monkeypatch.delenv("JELLYFIN_USER_HER", raising=False)
    yield lambda b, h: calls.append(1) or USERS
    jf.clear_cache()


def test_creds_need_both_values(monkeypatch):
    monkeypatch.setenv("JELLYFIN_URL", "http://jf.invalid/ ")
    monkeypatch.delenv("JELLYFIN_API_KEY", raising=False)
    assert jf.creds() is None
    monkeypatch.setenv("JELLYFIN_API_KEY", "k")
    assert jf.creds() == ("http://jf.invalid", {"Authorization": "MediaBrowser Token=k"})


def test_you_is_the_named_user_else_the_first_admin(users, monkeypatch):
    assert jf.user_id("you", "b", {}, users) == "u-admin"
    monkeypatch.setenv("JELLYFIN_USER", "Georgina")
    assert jf.user_id("you", "b", {}, users) == "u-plain"          # a new wanted name is looked up again


def test_her_is_exactly_the_named_user_never_the_admin(users, monkeypatch):
    assert jf.user_id("her", "b", {}, users) is None                 # unset: nobody
    monkeypatch.setenv("JELLYFIN_USER_HER", "Nobody")
    assert jf.user_id("her", "b", {}, users) is None                 # no such user: never the admin
    monkeypatch.setenv("JELLYFIN_USER_HER", "Georgina")
    assert jf.user_id("her", "b", {}, users) == "u-plain"


def test_ids_are_cached_per_owner():
    calls = []
    jf.clear_cache()
    read = lambda b, h: calls.append(1) or USERS  # noqa: E731
    for _ in range(3):
        jf.user_id("you", "b", {}, read)
    assert len(calls) == 1
    jf.clear_cache()


def test_diary_search_goes_through_the_one_jellyseerr_reader(monkeypatch):
    """M-13: /media/search maps media_discover's _get results; no second Jellyseerr client."""
    from hub import media_discover as md
    monkeypatch.setenv("JELLYSEERR_URL", "http://seerr.invalid")
    monkeypatch.setenv("JELLYSEERR_API_KEY", "k")
    seen = []
    monkeypatch.setattr(md, "_get", lambda path: seen.append(path) or {"results": [
        {"mediaType": "movie", "id": 603, "title": "The Matrix", "releaseDate": "1999-03-31", "posterPath": "/m.jpg"},
        {"mediaType": "person", "id": 1, "name": "Keanu"}]})
    rows = media_write._search("matrix & co")
    assert seen == ["/api/v1/search?query=matrix%20%26%20co"]
    assert rows == [{"item_key": "tmdb:603", "kind": "movie", "title": "The Matrix", "year": 1999, "poster": "tmdb:/m.jpg"}]
    monkeypatch.setattr(md, "_get", lambda path: None)
    assert media_write._search("matrix") is None
