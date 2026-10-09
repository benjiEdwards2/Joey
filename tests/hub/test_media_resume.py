"""Move on from Continue watching (2026-10-08): Mark watched / Reset progress on resume items (hub + Media home
shelves, Server → Playing's Up next, the film / episode page). Jellyfin is faked at `requests.get` / `requests.post`;
no network. Both users: "you" = JELLYFIN_USER (else the admin), "her" = JELLYFIN_USER_HER exactly."""
import importlib
import logging
from datetime import datetime, timedelta, timezone

import pytest
import requests
from fastapi.testclient import TestClient

from hub import media_files, media_hidden, media_item, media_resume
from tests.hub.test_media_item import EPISODES, ITEMS, SEASONS, TICKS
from tests.hub.test_media_shelves import shelf_area
from tests.hub.test_registry import make_area, write_registry
from tests.hub.test_store import write_envelope

URL = "http://jf.secret-host.invalid:8096"
KEY = "jf-SECRET-key-123"
ORIGIN_BAD = {"Origin": "https://evil.invalid"}
USERS = [{"Id": "u-ben", "Name": "Ben", "Policy": {"IsAdministrator": True}},
         {"Id": "u-geo", "Name": "Georgina", "Policy": {"IsAdministrator": False}}]
MINE = [{"title": "Dust and Daylight", "kind": "movie", "remaining_text": "31 min left", "poster": "jf:mov1",
         "item_key": "tmdb:603", "jf_id": "mov1"},
        {"title": "Quiet Show · S04E05 · Five", "kind": "episode", "remaining_text": "Next episode", "poster": "jf:ser1",
         "item_key": "jf:ser1", "jf_id": "ep5", "show_key": "jf:ser1"}]
HERS = [{"title": "Garden Lane · S01E02 · Thaw", "kind": "episode", "remaining_text": "12 min left",
         "poster": "jf:her-series-1", "item_key": "jf:her-series-1", "jf_id": "her-ep2"}]


class R:
    def __init__(self, body=None, status=200):
        self._b, self.status_code = body, status

    def json(self):
        return self._b


class Fake:
    def __init__(self):
        self.gets, self.posts = [], []
        self.legacy = False            # a pre-10.9 server: the new routes 404
        self.post_status = 200
        self.raise_post = None

    def get(self, url, params=None, headers=None, timeout=None, **kw):
        assert url.startswith(URL) and headers == {"Authorization": f"MediaBrowser Token={KEY}"}
        path = url[len(URL):]
        self.gets.append(path)
        if path == "/Users":
            return R(USERS)
        if path == "/System/Info/Public":
            return R({"Id": "pubsrv"})
        if path.startswith("/Users/u-ben/Items/"):
            it = ITEMS.get(path.rsplit("/", 1)[1])
            return R(it) if it else R({}, 404)
        if path == "/Shows/ser1/Seasons":
            return R({"Items": SEASONS})
        if path == "/Shows/ser1/Episodes":
            return R({"Items": EPISODES})
        return R({}, 404)

    def post(self, url, params=None, json=None, headers=None, timeout=None, **kw):
        assert url.startswith(URL) and headers == {"Authorization": f"MediaBrowser Token={KEY}"}
        path = url[len(URL):]
        self.posts.append((path, params, json))
        if self.raise_post:
            raise self.raise_post(f"Max retries exceeded with url: {url}?api_key={KEY}")
        if self.legacy and path.startswith(("/UserPlayedItems/", "/UserItems/")):
            return R({}, 404)
        return R({}, self.post_status)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("AREAS_PATH", str(write_registry(tmp_path, shelf_area(), make_area("beta"))))
    monkeypatch.setenv("MEDIA_DB_PATH", str(tmp_path / "media.db"))
    snaps = tmp_path / "snaps"
    monkeypatch.setenv("SNAPSHOT_DIR", str(snaps))
    monkeypatch.setenv("PLAY_RECORDER", "off")
    monkeypatch.setenv("JELLYFIN_URL", URL)
    monkeypatch.setenv("JELLYFIN_API_KEY", KEY)
    monkeypatch.setenv("JELLYFIN_USER_HER", "Georgina")
    monkeypatch.delenv("JELLYFIN_USER", raising=False)
    monkeypatch.delenv("OWNER_EMAIL_YOU", raising=False)
    media_hidden.clear()
    media_resume.clear_cache()

    def build(her=True):
        data = {"summary": "x", "server_id": "srv-1", "up_next": [dict(r) for r in MINE],
                "her": {"up_next": [dict(r) for r in HERS], "history": {}} if her else None}
        write_envelope(snaps, "jellyfin", age_minutes=1, data=data)
        import hub.main
        importlib.reload(hub.main)
        media_files.clear_cache()
        media_item.clear_cache()
        fake = Fake()
        monkeypatch.setattr(requests, "get", fake.get)
        monkeypatch.setattr(requests, "post", fake.post)
        return TestClient(hub.main.app), fake, snaps

    yield build
    media_hidden.clear()


def main_of(html):
    return html.split("<main", 1)[1].replace('<span class="sep"> · </span>', " · ")


def watched(client, jf, back="/media/playing", **extra):
    return client.post(f"/media/resume/{jf}/watched", data={"back": back, **extra}, follow_redirects=False)


def reset(client, jf, back="/media/playing", **extra):
    return client.post(f"/media/resume/{jf}/reset", data={"back": back, **extra}, follow_redirects=False)


# ---- the Jellyfin calls ----

def test_mark_watched_as_you_uses_the_10_9_route(env):
    client, fake, _ = env()
    with client:
        r = watched(client, "mov1")
    assert r.status_code == 303 and r.headers["location"] == "/media/playing?done=watched"
    assert fake.posts == [("/UserPlayedItems/mov1", {"userId": "u-ben"}, None)]


def test_reset_progress_as_you_posts_zero_ticks(env):
    client, fake, _ = env()
    with client:
        r = reset(client, "mov1")
    assert r.headers["location"] == "/media/playing?done=reset"
    assert fake.posts == [("/UserItems/mov1/UserData", {"userId": "u-ben"}, {"PlaybackPositionTicks": 0})]


def test_jellyfin_user_name_picks_you(env, monkeypatch):
    monkeypatch.setenv("JELLYFIN_USER", "Georgina")   # an odd setup, but the name wins over the admin
    client, fake, _ = env()
    with client:
        watched(client, "mov1")
    assert fake.posts[0][1] == {"userId": "u-geo"}


def test_her_view_acts_as_her_user_for_both_actions(env):
    client, fake, _ = env()
    client.cookies.set("owner_view", "her")
    with client:
        watched(client, "her-ep2", owner="you")              # the form can't override a her/you view
        reset(client, "her-ep2")
    assert fake.posts == [("/UserPlayedItems/her-ep2", {"userId": "u-geo"}, None),
                          ("/UserItems/her-ep2/UserData", {"userId": "u-geo"}, {"PlaybackPositionTicks": 0})]


def test_signed_in_viewer_always_acts_as_themselves(env, monkeypatch):
    monkeypatch.setenv("OWNER_EMAIL_YOU", "ben@example.invalid")
    client, fake, _ = env()
    with client:
        client.post("/media/resume/her-ep2/watched", data={"owner": "her", "back": "/"},
                    headers={"Cf-Access-Authenticated-User-Email": "ben@example.invalid"}, follow_redirects=False)
        client.post("/media/resume/mov1/watched", data={"owner": "you", "back": "/"},
                    headers={"Cf-Access-Authenticated-User-Email": "geo@example.invalid"}, follow_redirects=False)
    assert [p[1] for p in fake.posts] == [{"userId": "u-ben"}, {"userId": "u-geo"}]


def test_both_view_row_owner_comes_from_the_form(env):
    client, fake, _ = env()
    client.cookies.set("owner_view", "both")
    with client:
        watched(client, "her-ep2", owner="her")
        watched(client, "mov1", owner="nobody")              # junk -> you
    assert [p[1] for p in fake.posts] == [{"userId": "u-geo"}, {"userId": "u-ben"}]


def test_her_without_a_her_user_is_a_word_never_the_admin(env, monkeypatch):
    monkeypatch.setenv("JELLYFIN_USER_HER", "Nobody")
    client, fake, _ = env()
    client.cookies.set("owner_view", "her")
    with client:
        r = watched(client, "her-ep2", back="/")
        page = main_of(client.get(r.headers["location"]).text)
    assert r.headers["location"] == "/?error=jfuser" and fake.posts == []
    assert "No Jellyfin user for this profile" in page


def test_older_server_falls_back_to_the_legacy_routes(env):
    client, fake, _ = env()
    fake.legacy = True
    with client:
        assert watched(client, "mov1").headers["location"] == "/media/playing?done=watched"
        assert reset(client, "mov1").headers["location"] == "/media/playing?done=reset"
    assert [p[0] for p in fake.posts] == ["/UserPlayedItems/mov1", "/Users/u-ben/PlayedItems/mov1",
                                          "/UserItems/mov1/UserData", "/Users/u-ben/Items/mov1/UserData"]
    assert fake.posts[3][2] == {"PlaybackPositionTicks": 0}


# ---- the list drops the item at once ----

def test_marked_item_leaves_every_resume_list_immediately(env):
    client, fake, _ = env()
    with client:
        assert "Dust and Daylight" in main_of(client.get("/media/playing").text)
        r = watched(client, "mov1")
        playing = main_of(client.get(r.headers["location"]).text)
        home = main_of(client.get("/a/alpha").text)
        hub_page = main_of(client.get("/").text)
    assert '<p class="metaline st-good" role="status">Marked watched</p>' in playing
    for page in (playing, home, hub_page):
        assert "Dust and Daylight" not in page
    assert "Quiet Show" in playing                           # the rest stay


def test_hidden_only_for_that_owner(env):
    client, fake, _ = env()
    client.cookies.set("owner_view", "both")
    with client:
        reset(client, "her-ep2", owner="her", back="/")
        page = main_of(client.get("/").text)
    assert "Garden Lane" not in page and "Dust and Daylight" in page


def test_a_newer_jellyfin_sweep_is_the_truth_again(env):
    import json
    client, fake, snaps = env()
    with client:
        watched(client, "mov1")
        assert "Dust and Daylight" not in main_of(client.get("/media/playing").text)
        doc = json.loads((snaps / "jellyfin.json").read_text(encoding="utf-8"))
        ts = (datetime.now(timezone.utc) + timedelta(seconds=media_hidden.GRACE_S + 5)).isoformat()
        doc["updated_at"] = doc["fetched_at"] = ts
        (snaps / "jellyfin.json").write_text(json.dumps(doc), encoding="utf-8")
        assert "Dust and Daylight" in main_of(client.get("/media/playing").text)


# ---- where the buttons are ----

def test_playing_up_next_rows_carry_both_actions_outside_the_row_link(env):
    client, _, _ = env()
    with client:
        body = main_of(client.get("/media/playing").text)
    rows = body.split('<div class="rowwrap resumerow">')
    first, second = rows[1], rows[2]
    link = first.split('<a class="row" href="/media/item/mov1">', 1)[1].split("</a>", 1)[0]
    assert "<form" not in link and "Dust and Daylight" in link   # the row is still one whole link
    acts = first.split("</a>", 1)[1]
    assert 'action="/media/resume/mov1/watched"' in acts and 'action="/media/resume/mov1/reset"' in acts
    assert ">Mark watched</button>" in acts and ">Reset progress</button>" in acts
    assert 'name="back" value="/media/playing"' in acts and 'name="owner" value="you"' in acts
    # a next-up suggestion has nothing to reset
    assert 'action="/media/resume/ep5/watched"' in second and "/media/resume/ep5/reset" not in second


def test_hub_and_media_home_cards_fold_the_actions_under_move_on(env):
    client, _, _ = env()
    with client:
        hub_page = main_of(client.get("/").text)
        home = main_of(client.get("/a/alpha").text)
    assert "/media/resume/" not in hub_page                      # media-ux2: Continue watching left the hub
    for page, back in ((home, "/a/alpha"),):
        wrap = page.split('<div class="card-wrap">', 1)[1]
        card = wrap.split("</a>", 1)[0]
        assert "<form" not in card and "<details" not in card       # the card stays one whole link
        assert '<summary class="btn btn-ghost btn-sm">Move on</summary>' in wrap
        assert 'action="/media/resume/mov1/watched"' in wrap and f'name="back" value="{back}"' in wrap
    assert "confirm(" not in hub_page


def test_both_view_hub_cards_carry_each_rows_owner(env):
    """media-ux2: the hub has no Continue watching cards any more; Media home's carry the owner."""
    client, _, _ = env()
    client.cookies.set("owner_view", "both")
    with client:
        page = main_of(client.get("/").text)
        home = main_of(client.get("/a/alpha").text)
    assert 'action="/media/resume/' not in page
    acts = home.split('action="/media/resume/mov1/watched"', 1)[1].split("</form>", 1)[0]
    assert 'name="owner" value="you"' in home.split('action="/media/resume/mov1/watched"', 1)[0][-400:] + acts


def test_film_page_shows_both_beside_resume(env):
    client, _, _ = env()
    with client:
        b = main_of(client.get("/media/item/mov1").text)
    assert "Resume ▶ · 32m left" in b
    btns = b.split('class="hero-detail-btns"', 1)[1]
    assert 'action="/media/resume/mov1/watched"' in btns and 'action="/media/resume/mov1/reset"' in btns
    assert 'name="back" value="/media/item/mov1"' in btns


def test_film_page_without_progress_has_no_actions(env, monkeypatch):
    monkeypatch.setitem(ITEMS["mov1"], "UserData", {"Played": True, "PlaybackPositionTicks": 0})
    client, _, _ = env()
    with client:
        b = main_of(client.get("/media/item/mov1").text)
    # media-ux3: a watched film now offers "Mark unwatched" — but never the Move-on pair
    assert "/media/resume/mov1/reset" not in b and 'action="/media/resume/mov1/watched"' not in b


def test_film_page_in_her_view_has_no_actions(env):
    client, _, _ = env()
    client.cookies.set("owner_view", "her")
    with client:
        b = main_of(client.get("/media/item/mov1").text)
    assert "/media/resume/" not in b                          # the page's state is B.'s user's


def test_episode_page_in_progress_targets_the_episode(env, monkeypatch):
    monkeypatch.setitem(ITEMS["ep3"], "UserData", {"Played": False, "PlaybackPositionTicks": 10 * TICKS})
    # media-ux4: the hero reads the episode's state from the show's season list, so the list says in progress too
    monkeypatch.setitem(EPISODES[2], "UserData", {"Played": False, "PlaybackPositionTicks": 10 * TICKS})
    client, _, _ = env()
    with client:
        b = main_of(client.get("/media/item/ep3").text)
    assert 'action="/media/resume/ep3/watched"' in b and 'action="/media/resume/ep3/reset"' in b


# ---- guards and errors ----

def test_actions_require_same_origin(env):
    client, fake, _ = env()
    with client:
        assert client.post("/media/resume/mov1/watched", headers=ORIGIN_BAD).status_code == 403
        assert client.post("/media/resume/mov1/reset", headers=ORIGIN_BAD).status_code == 403
        assert client.get("/media/resume/mov1/watched").status_code in (404, 405)
    assert fake.posts == []


def test_bad_id_and_bad_back(env):
    client, fake, _ = env()
    with client:
        assert client.post("/media/resume/bad..id/watched").status_code == 404
        r = watched(client, "mov1", back="https://evil.invalid/x")
        r2 = watched(client, "mov1", back="//evil.invalid/x")
        r3 = watched(client, "mov1", back="/media/item/mov1?done=reset#x")
    assert r.headers["location"] == r2.headers["location"] == "/media/playing?done=watched"
    assert r3.headers["location"] == "/media/item/mov1?done=watched"   # an old flash never rides along


def test_jellyfin_down_is_a_word_and_never_leaks(env, caplog):
    client, fake, _ = env()
    fake.raise_post = requests.ConnectionError
    with caplog.at_level(logging.WARNING), client:
        r = watched(client, "mov1")
        page = client.get(r.headers["location"]).text
    assert r.headers["location"] == "/media/playing?error=jfdown"
    assert "Couldn&#39;t reach Jellyfin" in page or "Couldn't reach Jellyfin" in page
    assert "Dust and Daylight" in main_of(page)                # nothing hidden on failure
    assert "jellyfin watched failed: ConnectionError" in caplog.text
    for text in (page, caplog.text, r.headers["location"]):
        assert "secret-host" not in text and "SECRET" not in text


def test_jellyfin_refusal_is_status_only(env, caplog):
    client, fake, _ = env()
    fake.post_status = 403
    with caplog.at_level(logging.WARNING), client:
        r = reset(client, "mov1")
        page = main_of(client.get(r.headers["location"]).text)
    assert r.headers["location"] == "/media/playing?error=jfrefused&code=403"
    assert "Jellyfin refused (HTTP 403)" in page and "jellyfin reset refused: HTTP 403" in caplog.text


def test_not_connected(env, monkeypatch):
    client, fake, _ = env()
    monkeypatch.delenv("JELLYFIN_API_KEY")
    with client:
        r = watched(client, "mov1")
    assert r.headers["location"] == "/media/playing?error=jfunset" and fake.posts == []


def test_resume_acts_helper(env):
    import hub.main as main
    # media-ux2: a Next Up suggestion (no position) also carries Hide + its series key
    assert main.resume_acts(MINE[0], "you") == {"jf_id": "mov1", "owner": "you", "reset": True, "hide": False,
                                                "series": None}
    assert main.resume_acts(MINE[1], "her") == {"jf_id": "ep5", "owner": "her", "reset": False, "hide": True,
                                                "series": "jf:ser1"}
    assert main.resume_acts({"title": "x"}, "you") is None
