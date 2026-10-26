"""JY-054 verifier must-fix (2026-10-27): with PLAYER_API off, ANY method on the player prefixes (`/api/play`,
`/media/watch` and everything under them) answers exactly what an unknown path answers - TRACE, PROPFIND and a made-up
method included, never a 405 with an Allow header that names the route. For you, her, no identity and a friend (the media
front). Flag on: unchanged. No live call."""
import pytest

from hub import guest
from tests.hub.test_player_api import FRIEND, HER, YOU, call, client, env, jf  # noqa: F401  (fixtures)

ODD = ["TRACE", "PROPFIND", "FOO"]
PATHS = ["/media/watch/x", "/media/watch", "/media/watch/" + "ab" * 16, "/api/play", "/api/play/",
         "/api/play/sessions", "/api/play/sessions/x/stop", "/api/play/items/" + "ab" * 16 + "/tracks"]
UNKNOWN = "/no-such-path-xyz"


def same_as_unknown(client, method, path, headers):
    want = call(client, method, UNKNOWN, headers)
    got = call(client, method, path, headers)
    assert (got.status_code, got.content) == (want.status_code, want.content), (method, path)
    assert "allow" not in got.headers, (method, path)
    assert got.headers.get("content-type") == want.headers.get("content-type"), (method, path)
    return got


@pytest.mark.parametrize("who", ["you", "her", "nobody"])
def test_flag_off_any_method_on_the_player_prefixes_is_the_unknown_path_404(client, jf, env, who):
    env.setenv("PLAYER_API", "off")
    headers = {"you": YOU, "her": HER, "nobody": None}[who]
    for method in ODD + ["GET", "POST", "DELETE"]:
        for path in PATHS:
            r = same_as_unknown(client, method, path, headers)
            assert (r.status_code, r.content) == (404, b'{"detail":"Not Found"}'), (method, path)
    assert jf.calls == []


def test_flag_off_on_the_media_front_a_friend_gets_the_ordinary_404_for_any_method(client, jf, env):
    env.setenv("PLAYER_API", "off")
    env.setenv("JOEY_FRONT", "media")
    env.setattr(guest, "identity_provider", lambda scope: FRIEND)
    for method in ODD + ["GET", "POST"]:
        for path in PATHS:
            assert same_as_unknown(client, method, path, None).status_code == 404, (method, path)
    assert jf.calls == []


def test_flag_off_a_lookalike_path_is_left_alone(client, jf, env):
    env.setenv("PLAYER_API", "off")
    for path in ("/api/playlist", "/media/watched", "/media/watchlist"):
        r = call(client, "TRACE", path, YOU)
        assert r.status_code != 500, path


def test_flag_on_the_routes_still_answer(client, jf, env):
    r = call(client, "POST", "/api/play/sessions", YOU, {"item_id": "junk"})
    assert r.status_code == 400   # past the flag: the API's own refusal, as before
    assert call(client, "GET", "/media/watch/not-an-id", YOU).status_code == 404
