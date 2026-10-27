"""JY-057 (2026-10-27): the hub side of the Joey TV shell player, behind the same PLAYER_API flag.

* The media-front gate serves the five JY-053 player routes to a signed-in household member only (JY-053 Q3 A), with
  the member's own session token; a friend, no session and any other method keep the ordinary Joey 404 page, and
  `allows()` keeps denying them (no nav link derives from them). Flag off: unchanged (tests/hub/test_player_api.py).
* The TV Play mark: `&player=joey` on the Jellyfin deep links only for flag on + media front + a Joey TV user agent at
  versionCode 2026102701 (1.0.3) or later + a household member. Everyone else keeps today's link byte for byte.
* The start answer's additive `up_next`, from the hub's item cache only.
Names, ids, tokens and hosts are invented; no live call."""
import re

import pytest

from hub import guest, media_front, media_item
from hub.identity import Identity
from tests.hub.fake_jellyfin import ALIAS_ID, FRIEND_ID, PUBLIC_URL
from tests.hub.guest_pages import guest_client, sign_in
from tests.hub.test_player_api import (  # noqa: F401  (fixtures)
    ALIAS, FRIEND, ITEM, ROUTES, START, YOU, call, client, env, err, jf, start)
from tests.hub.test_player_page import EP2, EP3, episode_cache, seed

HER_ON_MEDIA = Identity(owner="her", name="Sample Her", jf_user_id="b7" * 16, jf_token="tok-her-media-777")
TV_103 = "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/155.0 Safari/537.36 JoeyTV/1.0.3 (2026102701)"
TV_102 = "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/155.0 Safari/537.36 JoeyTV/1.0.2 (2026102501)"
DESKTOP = "Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 Chrome/155.0 Safari/537.36"


def on_media(env, who):
    """The real tables (nothing moved), the media front, `who` signed in (None = no session)."""
    env.setenv("JOEY_FRONT", "media")
    env.setattr(guest, "identity_provider", (lambda scope: who) if who is not None else None)


# ---- the gate: household only, flag on ----

@pytest.mark.parametrize("who", [ALIAS, HER_ON_MEDIA])
def test_household_on_the_media_front_reaches_every_player_route(client, jf, env, who):
    on_media(env, who)
    body = start(client, headers=None)
    info = jf.calls[-1]
    assert f'Token="{who.jf_token}"' in info["headers"]["Authorization"]
    assert info["json"]["UserId"] == who.jf_user_id and "/Users/Me" not in jf.paths()
    sid = body["session_id"]
    s = call(client, "POST", f"/api/play/sessions/{sid}/stream")
    assert s.status_code == 200 and f'Token="{who.jf_token}"' in s.json()["headers"]["Authorization"]
    assert call(client, "POST", f"/api/play/sessions/{sid}/progress", json={"position_ticks": 10}).status_code == 204
    assert call(client, "GET", f"/api/play/items/{ITEM}/tracks").status_code == 200
    assert call(client, "POST", f"/api/play/sessions/{sid}/stop", json={"position_ticks": 20}).status_code == 204


@pytest.mark.parametrize("who", [FRIEND, None])
def test_a_friend_and_no_session_keep_the_ordinary_404_page(client, jf, env, who):
    on_media(env, who)
    unknown = call(client, "GET", "/no-such-page-xyz")
    for method, path in ROUTES:
        r = call(client, method, path, json=START)
        assert (r.status_code, r.content) == (unknown.status_code, unknown.content), (method, path)
    assert jf.calls == []


def test_flag_off_the_household_gets_the_ordinary_404_page_too(client, jf, env):
    on_media(env, ALIAS)
    env.setenv("PLAYER_API", "off")
    unknown = call(client, "GET", "/no-such-page-xyz")
    for method, path in ROUTES:
        r = call(client, method, path, json=START)
        assert (r.status_code, r.content) == (unknown.status_code, unknown.content), (method, path)
    assert jf.calls == []


def test_a_wrong_method_or_another_path_is_the_404_page_for_the_household(client, jf, env):
    on_media(env, ALIAS)
    unknown = call(client, "GET", "/no-such-page-xyz")
    for method, path in [("GET", "/api/play/sessions"), ("PUT", "/api/play/sessions"), ("HEAD", "/api/play/sessions"),
                         ("POST", f"/api/play/items/{ITEM}/tracks"), ("GET", "/api/play/sessions/abc/stream"),
                         ("POST", "/api/play/other"), ("POST", "/api/play"), ("DELETE", "/api/play/sessions/abc/stop")]:
        r = call(client, method, path)
        assert r.status_code == unknown.status_code, (method, path)
        if method != "HEAD":
            assert r.content == unknown.content, (method, path)
    assert jf.calls == []


def test_allows_still_denies_every_player_route():
    for method, path in ROUTES:
        assert not guest.allows(method, path), (method, path)
    assert all(e in guest.PRIVATE for e in guest.HOUSEHOLD_PLAYER)
    assert not set(guest.HOUSEHOLD_PLAYER) & set(guest.GUEST)


def test_the_household_table_names_exactly_the_five_routes():
    assert sorted(guest.HOUSEHOLD_PLAYER) == sorted([
        ("POST", "/api/play/sessions"), ("POST", "/api/play/sessions/{session_id}/stream"),
        ("POST", "/api/play/sessions/{session_id}/progress"), ("POST", "/api/play/sessions/{session_id}/stop"),
        ("GET", "/api/play/items/{item_id}/tracks")])


# ---- the start answer's up_next (additive, from the cache) ----

def test_start_carries_up_next_from_the_cache_with_no_extra_call(client, jf):
    episode_cache()
    body = start(client, item_id=EP2)
    assert body["up_next"] == {"item_id": EP3, "label": "S2 · E3 · The Breakwater", "runtime": "48m"}
    assert [c["path"] for c in jf.calls] == ["/Users/Me", f"/Items/{EP2}/PlaybackInfo"]


def test_up_next_is_null_for_a_film_the_last_aired_episode_and_a_cold_cache(client, jf):
    episode_cache()
    seed(EP3, {"kind": "episode", "id": EP3, "title": "The Breakwater", "show_id": "5a" * 16, "season_no": 2,
               "episode_no": 3})
    assert start(client, item_id=EP3)["up_next"] is None   # E4 has not aired
    seed(ITEM, {"kind": "movie", "id": ITEM, "title": "Harbour Lights"})
    assert start(client)["up_next"] is None
    media_item._cache.clear()
    assert start(client, item_id=EP2)["up_next"] is None


# ---- the TV Play mark ----

def test_tv_player_needs_the_flag_the_media_front_the_shell_version_and_the_household(monkeypatch):
    class Req:
        def __init__(self, ua, cookies=None):
            self.headers, self.cookies, self.scope = {"user-agent": ua}, cookies or {}, {"query_string": b""}

    who = {"ident": ALIAS}
    monkeypatch.setattr(media_front, "_viewer_owner", lambda request: who["ident"].owner if who["ident"] else None)
    monkeypatch.setenv("JOEY_FRONT", "media")
    monkeypatch.setenv("PLAYER_API", "on")
    assert media_front.tv_player(Req(TV_103))
    assert media_front.tv_player(Req(TV_103.replace("1.0.3 (2026102701)", "1.1.0 (2026110301)")))
    assert not media_front.tv_player(Req(TV_102))
    assert not media_front.tv_player(Req(DESKTOP, {"tv": "1"}))          # the cookie is TV mode, not the shell
    assert not media_front.tv_player(Req(TV_103.replace("(2026102701)", "(junk)")))
    assert not media_front.tv_player(None)
    who["ident"] = FRIEND
    assert not media_front.tv_player(Req(TV_103))
    who["ident"] = None
    assert not media_front.tv_player(Req(TV_103))
    who["ident"] = ALIAS
    monkeypatch.setenv("PLAYER_API", "off")
    assert not media_front.tv_player(Req(TV_103))
    monkeypatch.setenv("PLAYER_API", "on")
    monkeypatch.delenv("JOEY_FRONT")
    assert not media_front.tv_player(Req(TV_103))


def test_the_mark_is_one_more_fragment_parameter():
    link = PUBLIC_URL + "/web/#/details?id=" + "ab" * 16 + "&serverId=srv-1"
    assert media_front.tv_play_href(link) == link + "&player=joey"
    assert media_front.tv_play_href(None) is None


JF = "f11f" * 8
SHOW = "5e7105e7" * 4
E1 = "e0000001" * 4
LIB = {"server_id": "srv-1", "library": {"movies": 1, "episodes": 1},
       "movies": [{"title": "Library Film", "jf_id": JF, "item_key": "tmdb:603", "year": 1999, "poster": "jf:" + JF}],
       "shows": [{"title": "Sample Show", "jf_id": SHOW, "item_key": f"jf:{SHOW}"}], "latest": []}
EPISODE = {"Id": E1, "Name": "Pilot Light", "Type": "Episode", "IndexNumber": 1, "ParentIndexNumber": 1,
           "SeasonId": "5ea50001" * 4, "SeasonName": "Season 1", "SeriesId": SHOW, "SeriesName": "Sample Show",
           "PremiereDate": "2026-09-01T00:00:00Z", "RunTimeTicks": 43 * 600_000_000}


@pytest.fixture()
def front(monkeypatch, tmp_path):
    client, fake = guest_client(monkeypatch, tmp_path, {"jellyfin": LIB})
    fake.items[JF] = {"Id": JF, "Type": "Movie", "Name": "Library Film", "ProductionYear": 1999,
                      "ProviderIds": {"Tmdb": "603"}, "RunTimeTicks": 120 * 600_000_000}
    fake.items[SHOW] = {"Id": SHOW, "Type": "Series", "Name": "Sample Show", "ProductionYear": 2026}
    fake.items[E1] = {**EPISODE, "Overview": "What happens."}
    fake.episodes[SHOW] = [EPISODE]
    monkeypatch.setenv("PLAYER_API", "on")
    with client as c:
        c.fake = fake
        yield c, monkeypatch


def play_hrefs(html: str) -> list[str]:
    """Every Jellyfin deep link on the page (Play buttons and episode cards), unescaped."""
    return [h.replace("&amp;", "&") for h in re.findall(r'href="(' + re.escape(PUBLIC_URL) + r'/web/#/details[^"]*)"', html)]


def page_links(c, ua, path):
    r = c.get(path, headers={"User-Agent": ua})
    assert r.status_code == 200, path
    return play_hrefs(r.text)


def test_household_on_a_103_shell_gets_the_mark_on_every_play_link(front):
    c, _ = front
    sign_in(c, c.fake, ALIAS_ID)
    for path in (f"/media/item/{JF}", f"/media/item/{SHOW}", f"/media/item/{E1}"):
        links = page_links(c, TV_103, path)
        assert links and all(h.endswith("&player=joey") for h in links), (path, links)


@pytest.mark.parametrize("case", ["flag off", "1.0.2 shell", "desktop with the tv cookie", "friend"])
def test_everyone_else_keeps_todays_link_byte_for_byte(front, case):
    c, env = front
    sign_in(c, c.fake, FRIEND_ID if case == "friend" else ALIAS_ID)
    ua = {"1.0.2 shell": TV_102, "desktop with the tv cookie": DESKTOP}.get(case, TV_103)
    if case == "desktop with the tv cookie":
        c.cookies.set("tv", "1")
    for path in (f"/media/item/{JF}", f"/media/item/{SHOW}"):
        env.setenv("PLAYER_API", "off")
        today = page_links(c, ua, path)
        if case != "flag off":
            env.setenv("PLAYER_API", "on")
        links = page_links(c, ua, path)
        assert links and links == today, (case, path)
        assert not any("player=joey" in h for h in links), (case, path)
