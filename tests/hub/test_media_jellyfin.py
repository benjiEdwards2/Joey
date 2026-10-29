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


# --- JY-264 P4: post / delete / get_bytes / auth_header / get timeout ---------------------------------------------

class _R:
    def __init__(self, status=200, body=None):
        self.status_code, self._b, self.content, self.headers = status, body or {}, b"img", {"Content-Type": "image/jpeg"}

    def json(self):
        return self._b


@pytest.fixture()
def wire(monkeypatch):
    seen = []

    def make(method, status=200):
        def f(url, **kw):
            seen.append((method, url, kw))
            return _R(status, {"ok": 1})
        return f
    state = {"status": 200}
    for m in ("get", "post", "delete"):
        monkeypatch.setattr(jf.requests, m, lambda url, _m=m, **kw: make(_m, state["status"])(url, **kw))
    return seen, state


def test_auth_header_is_the_12_2_token_form(monkeypatch):
    monkeypatch.setenv("JELLYFIN_API_KEY", " k ")
    assert jf.auth_header() == {"Authorization": "MediaBrowser Token=k"}
    assert jf.auth_header("tok") == {"Authorization": "MediaBrowser Token=tok"}
    monkeypatch.delenv("JELLYFIN_API_KEY")
    assert jf.auth_header() == {}


def test_post_delete_get_bytes_pass_url_headers_and_default_timeout(wire):
    seen, _ = wire
    h = {"Authorization": "x"}
    assert jf.post("http://b", h, "/p", params={"a": 1}, json={"j": 1}).status_code == 200
    assert jf.delete("http://b", h, "/d").status_code == 200
    assert jf.get_bytes("http://b", h, "/Items/1/Images/Primary", timeout=3).content == b"img"
    assert [(m, u) for m, u, _ in seen] == [("post", "http://b/p"), ("delete", "http://b/d"),
                                            ("get", "http://b/Items/1/Images/Primary")]
    assert seen[0][2]["headers"] == h and seen[0][2]["json"] == {"j": 1} and seen[0][2]["timeout"] == jf.TIMEOUT
    assert seen[2][2]["timeout"] == 3


def test_post_and_delete_return_non_2xx_for_the_caller_get_raises(wire):
    _, state = wire
    state["status"] = 404
    assert jf.post("http://b", {}, "/p").status_code == 404      # callers check, as their own helpers did
    assert jf.delete("http://b", {}, "/d").status_code == 404
    with pytest.raises(RuntimeError, match="HTTP 404"):
        jf.get("http://b", {}, "/g", timeout=3)


def test_get_timeout_override(wire):
    seen, _ = wire
    jf.get("http://b", {}, "/g", {"q": 1}, 3)
    jf.get("http://b", {}, "/g")
    assert [kw["timeout"] for _, _, kw in seen] == [3, jf.TIMEOUT]
