"""JY-054 (2026-10-27): Joey's own web / phone player page (`/media/watch/<item>`, look A), the Play link switch on the
title and episode pages, and the API's additive `resume` option. Spec: docs/specs/JY-054-web-phone-player.md.

Flag off = the unknown-path 404 for every method and caller; household only on the private front (no identity = the
same 404), the ordinary Joey 404 on the media front; the page renders from the item cache only (no live call); the Play
links point at the player only with the flag on, on the private front, for you / her. Ids, tokens, names and hosts are
invented; no live call is made."""
import re
import statistics
import time
from urllib.parse import urlsplit

import pytest

from hub import guest, media_item, player_api
from tests.hub.conftest import main_of  # noqa: F401
from tests.hub.helpers import deep, env as film_env  # noqa: F401  (the film page fixture, under its own name)
from tests.hub.test_player_api import (  # noqa: F401  (fixtures)
    ALIAS, FRIEND, HER, ITEM, PROFILE, Resp, START, TOKENS, UIDS, YOU, call, client, env, err, jf, start)

UNKNOWN = (404, b'{"detail":"Not Found"}')
SHOW, EP2, EP3, FILM = "5a" * 16, "e2" * 16, "e3" * 16, "f1" * 16
METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]


def watch_paths(item=ITEM):
    return [f"/media/watch/{item}", f"/media/watch/{item}/", "/media/watch", "/media/watch/",
            "/media/watch/not-an-id", f"/media/watch/{item}/extra", f"/media/watch/{item.upper()}"]


def seed(jf_id, item, seasons=None):
    """The item read the title / episode page has just cached (media_item's own cache, no Jellyfin call)."""
    media_item._cache[media_item._ck(jf_id)] = (time.time(), {"item": item, "seasons": seasons or [], "files": None})


def episode_cache():
    eps = [{"number": n, "name": name, "jf_id": i, "aired": aired, "runtime": "48m", "still": f"jf:{i}",
            "played": False, "in_progress": False}
           for n, name, i, aired in ((1, "Pilot", "e1" * 16, True), (2, "Low Tide", EP2, True),
                                     (3, "The Breakwater", EP3, True), (4, "Not Yet", "e4" * 16, False))]
    seasons = [{"id": "s1" * 16, "number": 2, "name": "Season 2", "episodes": eps}]
    seed(SHOW, {"kind": "series", "id": SHOW, "title": "Harbour Lights", "year": "2024"}, seasons)
    seed(EP2, {"kind": "episode", "id": EP2, "title": "Low Tide", "year": "2024", "runtime": "52m",
               "official_rating": "M", "show_title": "Harbour Lights", "show_id": SHOW, "season_no": 2,
               "episode_no": 2, "code": "S02E02"})


# ---- the flag and who may open the page ----

@pytest.mark.parametrize("value", [None, "", "off", "1", "true"])
def test_flag_off_every_watch_path_is_the_unknown_path_404(client, jf, env, value):
    if value is None:
        env.delenv("PLAYER_API")
    else:
        env.setenv("PLAYER_API", value)
    seed(ITEM, {"kind": "movie", "id": ITEM, "title": "Harbour Lights"})
    for method in METHODS:
        assert (call(client, method, "/no-such-path-xyz", YOU).status_code,
                call(client, method, "/no-such-path-xyz", YOU).content) == UNKNOWN
        for path in watch_paths():
            for headers in (YOU, HER, None):
                r = call(client, method, path, headers)
                assert (r.status_code, r.content) == UNKNOWN, (method, path)
                assert "allow" not in r.headers and "location" not in r.headers, (method, path)
    assert jf.calls == []


def test_flag_on_you_and_her_get_the_page_with_no_live_call(client, jf):
    seed(ITEM, {"kind": "movie", "id": ITEM, "title": "Harbour Lights", "year": "2019"})
    for who in (YOU, HER):
        r = client.get(f"/media/watch/{ITEM}", headers=who)
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
        assert r.headers["cache-control"] == "no-store"
        page = r.text
        assert f'data-item="{ITEM}"' in page and 'id="player"' in page
        assert re.search(r'<script src="/static/hls\.min\.js\?v=[0-9a-f]+" defer></script>', page)
        assert re.search(r'<script src="/static/player\.js\?v=[0-9a-f]+" defer></script>', page)
        assert re.search(r'<link rel="stylesheet" href="/static/player\.css\?v=[0-9a-f]+">', page)
        assert "<video" in page and "disableremoteplayback" in page and 'x-webkit-airplay="deny"' in page
        assert "playsinline" in page and " src=" not in page.split("<video", 1)[1].split(">", 1)[0]
        for secret in (*TOKENS.values(), "jf-lan.test", "jf-public.test", "Token=", "api_key", "ApiKey"):
            assert secret not in page, secret
    assert jf.calls == []


def test_dashed_upper_case_id_serves_the_same_item(client, jf):
    seed(ITEM, {"kind": "movie", "id": ITEM, "title": "Harbour Lights"})
    dashed = f"{ITEM[:8]}-{ITEM[8:12]}-{ITEM[12:16]}-{ITEM[16:20]}-{ITEM[20:]}".upper()
    r = client.get(f"/media/watch/{dashed}", headers=YOU)
    assert r.status_code == 200 and f'data-item="{ITEM}"' in r.text


def test_flag_on_no_identity_bad_id_and_other_methods_are_the_unknown_path_404(client, jf, env):
    seed(ITEM, {"kind": "movie", "id": ITEM, "title": "Harbour Lights"})
    assert (client.get(f"/media/watch/{ITEM}").status_code, client.get(f"/media/watch/{ITEM}").content) == UNKNOWN
    for path in ("/media/watch", "/media/watch/", "/media/watch/not-an-id", f"/media/watch/{ITEM}/extra",
                 f"/media/watch/{ITEM}/", "/media/watch/" + "a" * 31, "/media/watch/" + "g" * 32):
        r = call(client, "GET", path, YOU)
        assert (r.status_code, r.content) == UNKNOWN, path
    for method in ("POST", "PUT", "PATCH", "DELETE", "OPTIONS"):
        r = call(client, method, f"/media/watch/{ITEM}", YOU)
        assert (r.status_code, r.content) == UNKNOWN and "allow" not in r.headers, method
    env.delenv("OWNER_EMAIL_YOU")   # Access not configured: nobody is household
    assert call(client, "GET", f"/media/watch/{ITEM}", YOU).content == UNKNOWN[1]
    assert jf.calls == []


@pytest.mark.parametrize("who", [FRIEND, ALIAS, None])
def test_media_front_is_the_ordinary_404_for_a_friend_the_alias_and_no_session(client, jf, env, who):
    env.setenv("JOEY_FRONT", "media")
    if who is not None:
        env.setattr(guest, "identity_provider", lambda scope: who)
    unknown = call(client, "GET", "/no-such-page-xyz")
    for path in watch_paths():
        for method in ("GET", "POST"):
            r = call(client, method, path)
            assert (r.status_code, r.content) == (unknown.status_code, unknown.content), (method, path)
    assert unknown.status_code in (303, 404)
    assert jf.calls == []


def test_watch_routes_are_private_on_the_media_front():
    for method in METHODS:
        for path in (f"/media/watch/{ITEM}", "/media/watch"):
            assert not guest.allows(method, path), (method, path)


# ---- what the page shows, from the cache only ----

def test_episode_page_shows_the_title_episode_line_and_up_next_from_the_cache(client, jf):
    episode_cache()
    page = client.get(f"/media/watch/{EP2}", headers=YOU).text
    assert "<title>Harbour Lights · S2 · E2 · Low Tide</title>" in page
    assert ">Harbour Lights<" in page and ">S2 · E2 · Low Tide<" in page
    assert "2024" in page and "52m" in page and ">M<" in page
    assert f'href="/media/item/{EP2}"' in page and "Back to Joey" in page
    up = re.search(r'<aside class="pl-end"[^>]*data-next="([^"]+)"', page)
    assert up and up.group(1) == f"/media/watch/{EP3}"
    assert "S2 · E3 · The Breakwater" in page and f"/img/jf:{EP3}" in page
    assert jf.calls == []


def test_last_aired_episode_and_a_film_have_no_up_next(client, jf):
    episode_cache()
    page = client.get(f"/media/watch/{EP3}", headers=YOU).text   # not cached itself: neutral words, still 200
    assert "pl-end" not in page
    seed(FILM, {"kind": "movie", "id": FILM, "title": "Harbour Lights", "year": "2019", "runtime": "1h 52m"})
    film = client.get(f"/media/watch/{FILM}", headers=YOU).text
    assert ">Harbour Lights<" in film and "1h 52m" in film and "pl-end" not in film
    assert f'href="/media/item/{FILM}"' in film
    seed(EP3, {"kind": "episode", "id": EP3, "title": "The Breakwater", "show_title": "Harbour Lights",
               "show_id": SHOW, "season_no": 2, "episode_no": 3})
    assert "pl-end" not in client.get(f"/media/watch/{EP3}", headers=YOU).text   # E4 has not aired
    assert jf.calls == []


def test_a_cold_cache_renders_neutral_words_and_warms_after_the_response(client, jf, env):
    warmed = []
    env.setattr(media_item, "warm", lambda jf_id: warmed.append(jf_id) or "fetched")
    r = client.get(f"/media/watch/{ITEM}", headers=YOU)
    assert r.status_code == 200 and "Jellyfin item" in r.text
    assert warmed == [ITEM]          # the BackgroundTask ran after the response (TestClient runs it before returning)
    assert jf.calls == []
    seed(ITEM, {"kind": "movie", "id": ITEM, "title": "Harbour Lights"})
    warmed.clear()
    client.get(f"/media/watch/{ITEM}", headers=YOU)
    assert warmed == []              # cached: nothing to warm


def test_page_render_is_inside_the_hub_page_budget(client, jf):
    episode_cache()
    client.get(f"/media/watch/{EP2}", headers=YOU)
    times = []
    for _ in range(60):
        t0 = time.perf_counter()
        assert client.get(f"/media/watch/{EP2}", headers=YOU).status_code == 200
        times.append((time.perf_counter() - t0) * 1000)
    p95 = statistics.quantiles(times, n=20)[18]
    print(f"\nJY-054 /media/watch render: p50 {statistics.median(times):.1f} ms, p95 {p95:.1f} ms (budget 50 ms)")
    assert p95 <= 50


# ---- the Play link switch on the title and episode pages ----

PLAYER_LINK = re.compile(r'<a class="btn btn-white" href="/media/watch/([^"]+)"([^>]*)>')


@pytest.fixture()
def film(film_env, monkeypatch):
    monkeypatch.setenv("OWNER_EMAIL_YOU", "you@example.test")
    return film_env


def test_flag_off_play_links_are_todays_jellyfin_hand_off(film, monkeypatch):
    monkeypatch.delenv("PLAYER_API", raising=False)
    client, _ = film()
    with client:
        b = main_of(client.get("/media/title/movie/603", headers=YOU).text)
        s = main_of(client.get("/media/item/ser1", headers=YOU).text)
    assert f'href="{deep("mov1")}" target="_blank" rel="noopener"' in b
    assert "/media/watch/" not in b and "/media/watch/" not in s


def test_flag_on_household_play_links_open_the_player_in_the_same_tab(film, monkeypatch):
    monkeypatch.setenv("PLAYER_API", "on")
    client, _ = film()
    with client:
        for who in (YOU, HER):
            b = main_of(client.get("/media/title/movie/603", headers=who).text)
            m = PLAYER_LINK.search(b)
            assert m and m.group(1) == "mov1", b[:2000]
            assert 'hx-boost="false"' in m.group(2) and "target=" not in m.group(2)
            assert "/web/#/details" not in b
        e = main_of(client.get("/media/item/ep3", headers=YOU).text)
        s = main_of(client.get("/media/title/tv/100", headers=YOU).text)
    m = PLAYER_LINK.search(e)
    assert m and m.group(1) == "ep3" and 'hx-boost="false"' in m.group(2)
    assert PLAYER_LINK.search(s).group(1) == "ep4"   # Next to watch
    rows = re.findall(r'<a class="btn btn-secondary btn-sm" href="(/media/watch/[^"]+)"([^>]*)>', s)
    assert rows and all('hx-boost="false"' in a and "target=" not in a for _, a in rows)
    assert "/web/#/details" not in s


def test_flag_on_without_a_household_identity_keeps_the_hand_off(film, monkeypatch):
    monkeypatch.setenv("PLAYER_API", "on")
    client, _ = film()
    with client:
        b = main_of(client.get("/media/title/movie/603").text)   # no Access identity (the local "both" view)
    assert f'href="{deep("mov1")}" target="_blank" rel="noopener"' in b and "/media/watch/" not in b


# ---- the API's `resume` option (contract addition, 2026-10-27) ----

ITEM_PATH = f"/Users/{UIDS[TOKENS['you']]}/Items/{ITEM}"


def with_item(jf, body=None, status=200, fail=None):
    """The fake Jellyfin also answers the item read: `body` (UserData + Chapters), a status or an exception."""
    plain = jf.handle

    def handle(method, url, params=None, json=None, headers=None, timeout=None, **kw):
        path = urlsplit(url).path
        if method == "GET" and re.fullmatch(r"/Users/[0-9a-f]{32}/Items/[0-9a-f]{32}", path):
            jf.calls.append({"method": method, "path": path, "params": params, "json": json,
                             "headers": headers or {}, "timeout": timeout})
            if fail is not None:
                raise fail("fake failure")
            return Resp(status, body)
        return plain(method, url, params=params, json=json, headers=headers, timeout=timeout, **kw)
    jf.handle = handle


ITEM_BODY = {"Id": ITEM, "UserData": {"PlaybackPositionTicks": 14_210_000_000, "Played": False},
             "Chapters": [{"Name": "Cold open", "StartPositionTicks": 0},
                          {"Name": "The ferry", "StartPositionTicks": 3_790_000_000, "ImageTag": "x"},
                          {"Name": "Bad", "StartPositionTicks": "12"}, "junk"]}


def test_resume_starts_at_the_members_own_position_with_chapters(client, jf):
    with_item(jf, ITEM_BODY)
    body = start(client, resume=True)
    assert body["resumed"] is True and body["start_ticks"] == 14_210_000_000
    assert body["chapters"] == [{"name": "Cold open", "start_ticks": 0}, {"name": "The ferry", "start_ticks": 3_790_000_000}]
    read = next(c for c in jf.calls if c["path"] == ITEM_PATH)
    assert read["params"] == {"Fields": "Chapters"} and read["timeout"] == (player_api.CONNECT_S, 2.0)
    assert read["headers"]["Authorization"].endswith(f'Token="{TOKENS["you"]}"')
    info = jf.calls[-1]
    assert info["path"].endswith("/PlaybackInfo") and info["json"]["StartTimeTicks"] == 14_210_000_000


def test_her_resume_reads_with_her_own_token_and_user(client, jf):
    with_item(jf, ITEM_BODY)
    start(client, headers=HER, resume=True)
    read = next(c for c in jf.calls if "/Items/" in c["path"] and not c["path"].endswith("PlaybackInfo"))
    assert read["path"] == f"/Users/{UIDS[TOKENS['her']]}/Items/{ITEM}"
    assert read["headers"]["Authorization"].endswith(f'Token="{TOKENS["her"]}"')


def test_resume_never_overrides_the_players_start_and_skips_a_played_item(client, jf):
    with_item(jf, ITEM_BODY)
    body = start(client, resume=True, start_ticks=50_000_000)
    assert (body["resumed"], body["start_ticks"]) == (False, 50_000_000) and len(body["chapters"]) == 2
    assert jf.calls[-1]["json"]["StartTimeTicks"] == 50_000_000
    with_item(jf, {**ITEM_BODY, "UserData": {"PlaybackPositionTicks": 14_210_000_000, "Played": True}})
    body = start(client, resume=True)
    assert body["resumed"] is False and body["start_ticks"] == 0 and "StartTimeTicks" not in jf.calls[-1]["json"]


@pytest.mark.parametrize("kind", ["status", "timeout", "junk"])
def test_a_failed_item_read_never_fails_the_start(client, jf, kind):
    import requests
    if kind == "status":
        with_item(jf, {"x": 1}, status=500)
    elif kind == "timeout":
        with_item(jf, fail=requests.Timeout)
    else:
        with_item(jf, ["not", "an", "object"])
    body = start(client, resume=True)
    assert body["resumed"] is False and body["chapters"] == [] and body["start_ticks"] == 0


def test_without_resume_the_start_is_jy053s_exactly(client, jf):
    with_item(jf, ITEM_BODY)
    body = start(client)
    assert body["resumed"] is False and body["chapters"] == []
    assert not any("/Items/" in c["path"] and not c["path"].endswith("PlaybackInfo") for c in jf.calls)


@pytest.mark.parametrize("value", ["yes", 1, None, {}])
def test_resume_must_be_a_boolean(client, jf, value):
    r = client.post("/api/play/sessions", headers=YOU, json={**START, "resume": value})
    if value is None:   # null is "left out"
        assert r.status_code == 201
        return
    assert r.status_code == 400 and err(r) == "bad_request" and jf.calls == []


def test_the_page_sends_no_referrer(client, jf):
    """Review should-fix 1 (2026-10-27): nothing the page loads tells another host which item is playing."""
    seed(ITEM, {"kind": "movie", "id": ITEM, "title": "Harbour Lights"})
    r = client.get(f"/media/watch/{ITEM}", headers=YOU)
    assert r.headers["referrer-policy"] == "no-referrer"
    assert '<meta name="referrer" content="no-referrer">' in r.text
    assert r.text.index('name="referrer"') < r.text.index("<script")
    cold = client.get(f"/media/watch/{'ab' * 16}", headers=YOU)
    assert cold.headers["referrer-policy"] == "no-referrer"
