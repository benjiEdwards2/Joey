"""Watched / unwatched for films, episodes and seasons (media-ux3, 2026-10-08). The routes extend media_resume's
Move-on pair: POST /media/resume/{id}/watched (a season with scope=season) and POST /media/resume/{id}/unwatched
(Jellyfin DELETE /UserPlayedItems/{id}, legacy DELETE /Users/{uid}/PlayedItems/{id}). Jellyfin is faked at
`requests.get` / `post` / `delete`; no network. Both users: "you" = JELLYFIN_USER (else the admin), "her" =
JELLYFIN_USER_HER exactly. Fixtures from test_media_resume / test_media_item."""
import pytest
import requests

from hub import media_db, media_hidden, media_item
from tests.hub.helpers import ep, EPISODES, ITEMS, TOMORROW
from tests.hub.conftest import main_of  # noqa: F401
from tests.hub.test_media_resume import KEY, ORIGIN_BAD, URL, R, env  # noqa: F401  (env is a fixture)


@pytest.fixture()
def wenv(env, monkeypatch):  # noqa: F811
    def build(**kw):
        client, fake, snaps = env(**kw)
        fake.deletes, fake.delete_status = [], 204

        def delete(url, params=None, headers=None, timeout=None, **k):
            assert url.startswith(URL) and headers == {"Authorization": f"MediaBrowser Token={KEY}"}
            path = url[len(URL):]
            fake.deletes.append((path, params))
            if fake.legacy and path.startswith("/UserPlayedItems/"):
                return R({}, 405)
            return R(None, fake.delete_status)

        monkeypatch.setattr(requests, "delete", delete)
        return client, fake, snaps

    return build


def post(client, jf, action, back, **extra):
    return client.post(f"/media/resume/{jf}/{action}", data={"back": back, **extra}, follow_redirects=False)


def hero_btns(b):
    return b.split('class="hero-detail-btns"', 1)[1].split("</header>", 1)[0]


def page(client, path):
    return client.get(path).text.replace('<span class="sep"> · </span>', " · ")


# ---- the Jellyfin calls ----

def test_episode_unwatched_uses_the_10_9_delete_and_keeps_its_season(wenv):
    client, fake, _ = wenv()
    with client:
        r = post(client, "ep3", "unwatched", "/media/item/ep3", season="4")
    assert r.status_code == 303 and r.headers["location"] == "/media/item/ep3?done=unwatched&season=4"
    assert fake.deletes == [("/UserPlayedItems/ep3", {"userId": "u-ben"})] and fake.posts == []


def test_unwatched_falls_back_to_the_legacy_route(wenv):
    client, fake, _ = wenv()
    fake.legacy = True
    with client:
        r = post(client, "mov1", "unwatched", "/media/item/mov1")
    assert r.headers["location"] == "/media/item/mov1?done=unwatched"
    assert fake.deletes == [("/UserPlayedItems/mov1", {"userId": "u-ben"}), ("/Users/u-ben/PlayedItems/mov1", None)]


def test_season_watched_posts_the_season_id(wenv):
    client, fake, _ = wenv()
    with client:
        r = post(client, "sea1", "watched", "/media/item/ser1", scope="season", show="ser1", season="4")
    assert r.headers["location"] == "/media/item/ser1?done=season-watched&season=4"
    assert fake.posts == [("/UserPlayedItems/sea1", {"userId": "u-ben"}, None)]


def test_season_unwatched_deletes_the_season_id_with_legacy_fallback(wenv):
    client, fake, _ = wenv()
    fake.legacy = True
    with client:
        r = post(client, "sea1", "unwatched", "/media/item/ser1", scope="season", show="ser1", season="4")
    assert r.headers["location"] == "/media/item/ser1?done=season-unwatched&season=4"
    assert [d[0] for d in fake.deletes] == ["/UserPlayedItems/sea1", "/Users/u-ben/PlayedItems/sea1"]


def test_her_view_acts_as_her_user_for_watched_unwatched_and_seasons(wenv):
    client, fake, _ = wenv()
    client.cookies.set("owner_view", "her")
    with client:
        post(client, "her-ep2", "unwatched", "/", owner="you")            # the form can't override her view
        post(client, "sea1", "watched", "/", scope="season", show="ser1")
    assert fake.deletes == [("/UserPlayedItems/her-ep2", {"userId": "u-geo"})]
    assert fake.posts == [("/UserPlayedItems/sea1", {"userId": "u-geo"}, None)]


def test_her_without_a_her_user_is_a_word(wenv, monkeypatch):
    monkeypatch.setenv("JELLYFIN_USER_HER", "Nobody")
    client, fake, _ = wenv()
    client.cookies.set("owner_view", "her")
    with client:
        r = post(client, "mov1", "unwatched", "/media/item/mov1")
    assert r.headers["location"] == "/media/item/mov1?error=jfuser" and fake.deletes == []


def test_routes_require_same_origin(wenv):
    client, fake, _ = wenv()
    with client:
        assert client.post("/media/resume/mov1/unwatched", headers=ORIGIN_BAD).status_code == 403
        assert client.post("/media/resume/sea1/watched", data={"scope": "season"}, headers=ORIGIN_BAD).status_code == 403
        assert client.get("/media/resume/mov1/unwatched").status_code in (404, 405)
        assert client.post("/media/resume/bad..id/unwatched").status_code == 404
    assert fake.deletes == [] and fake.posts == []


def test_refusal_is_status_only_and_keeps_the_season(wenv):
    client, fake, _ = wenv()
    fake.delete_status = 403
    with client:
        r = post(client, "ep3", "unwatched", "/media/item/ser1", season="4")
        b = main_of(client.get(r.headers["location"]).text)
    assert r.headers["location"] == "/media/item/ser1?error=jfrefused&code=403&season=4"
    assert "Jellyfin refused (HTTP 403)" in b and "secret-host" not in b and "SECRET" not in b


def test_junk_season_and_scope_are_ignored(wenv):
    client, fake, _ = wenv()
    with client:
        r = post(client, "ep3", "unwatched", "/media/item/ser1", season="4; x", scope="everything")
    assert r.headers["location"] == "/media/item/ser1?done=unwatched"


# ---- flashes ----

@pytest.mark.parametrize("jf,action,extra,word", [
    ("mov1", "unwatched", {}, "Marked unwatched"),
    ("mov1", "watched", {}, "Marked watched"),
    ("sea1", "watched", {"scope": "season", "show": "ser1"}, "Season marked watched"),
    ("sea1", "unwatched", {"scope": "season", "show": "ser1"}, "Season marked unwatched"),
])
def test_flash_words(wenv, jf, action, extra, word):
    client, _, _ = wenv()
    with client:
        r = post(client, jf, action, "/media/playing", **extra)
        b = main_of(client.get(r.headers["location"]).text)
    assert f'<p class="metaline st-good" role="status">{word}</p>' in b


# ---- the page shows the new state at once ----

def test_success_clears_the_item_cache_so_the_page_rereads(wenv, monkeypatch):
    monkeypatch.setitem(ITEMS["mov1"], "UserData", {"Played": False, "PlaybackPositionTicks": 0})
    client, fake, _ = wenv()
    with client:
        before = hero_btns(main_of(client.get("/media/item/mov1").text))
        assert "mov1" in media_item._cache
        monkeypatch.setitem(ITEMS["mov1"], "UserData", {"Played": True, "PlaybackPositionTicks": 0})  # Jellyfin now
        r = post(client, "mov1", "watched", "/media/item/mov1")
        assert media_item._cache == {}
        after = main_of(client.get(r.headers["location"]).text)
    assert 'action="/media/resume/mov1/watched"' in before and ">Mark watched</button>" in before
    btns = hero_btns(after)
    assert 'action="/media/resume/mov1/unwatched"' in btns and ">Mark unwatched</button>" in btns
    assert "Play again ▶" in btns and "Marked watched" in after


def test_failure_keeps_the_cache(wenv):
    client, fake, _ = wenv()
    fake.delete_status = 500
    with client:
        client.get("/media/item/mov1")
        post(client, "mov1", "unwatched", "/media/item/mov1")
        assert "mov1" in media_item._cache


def test_episode_row_state_words_flip_after_marking(wenv, monkeypatch):
    client, fake, _ = wenv()
    with client:
        b = page(client, "/media/item/ser1")
        row5 = b.split('id="ep-ep5"', 1)[1].split('<div class="row has-form', 1)[0]
        assert "Not watched" in row5 and 'action="/media/resume/ep5/watched"' in row5
        import tests.hub.test_media_resume as tmr                                           # Jellyfin now:
        monkeypatch.setattr(tmr, "EPISODES", EPISODES[:4] + [ep(5, "Five", True)] + EPISODES[5:])
        r = post(client, "ep5", "watched", "/media/item/ser1", season="4")
        b = page(client, r.headers["location"])
    row5 = b.split('id="ep-ep5"', 1)[1].split('<div class="row has-form', 1)[0]
    assert ">Watched<" in row5 and 'action="/media/resume/ep5/unwatched"' in row5 and ">Mark unwatched</button>" in row5


# ---- Continue watching hiding ----

def test_watched_hides_from_continue_watching_unwatched_does_not(wenv):
    client, fake, _ = wenv()
    with client:
        post(client, "mov1", "unwatched", "/media/playing")
        assert "Dust and Daylight" in main_of(client.get("/media/playing").text)
        post(client, "mov1", "watched", "/media/playing")
        assert "Dust and Daylight" not in main_of(client.get("/media/playing").text)


def test_season_watched_hides_every_episode_of_the_season(wenv):
    client, fake, _ = wenv()
    with client:
        assert "Quiet Show" in main_of(client.get("/media/playing").text)     # ep5, a Next episode row
        post(client, "sea1", "watched", "/media/playing", scope="season", show="ser1")
        b = main_of(client.get("/media/playing").text)
    assert "Quiet Show" not in b and "Dust and Daylight" in b
    for jf in ("ep1", "ep4", "ep5", "sea1"):
        assert media_hidden.is_hidden("resume", f"you:{jf}")


def test_season_unwatched_hides_only_in_progress_episodes(wenv):
    client, fake, _ = wenv()
    with client:
        post(client, "sea1", "unwatched", "/media/playing", scope="season", show="ser1")
    assert media_hidden.is_hidden("resume", "you:ep4")                      # its saved position is gone
    assert not media_hidden.is_hidden("resume", "you:ep5") and not media_hidden.is_hidden("resume", "you:sea1")


def test_season_hiding_is_per_owner(wenv):
    client, fake, _ = wenv()
    client.cookies.set("owner_view", "her")
    with client:
        post(client, "sea1", "watched", "/", scope="season", show="ser1")
    assert media_hidden.is_hidden("resume", "her:ep5") and not media_hidden.is_hidden("resume", "you:ep5")


# ---- the diary ----

def test_unwatched_never_deletes_a_diary_entry(wenv):
    client, fake, _ = wenv()
    with client:
        media_db.add_manual_watch(item_key="tmdb:603", kind="movie", title="Harbour Lights", year=2019)
        post(client, "mov1", "unwatched", "/media/item/mov1")
        post(client, "sea1", "unwatched", "/media/item/ser1", scope="season", show="ser1")
        rows = media_db.list_diary(50, 0, None, "you")
    assert [r["item_key"] for r in rows] == ["tmdb:603"]


# ---- where the buttons are ----

def test_series_page_season_header_and_row_toggles(wenv):
    client, _, _ = wenv()
    with client:
        b = page(client, "/media/item/ser1")
    season = b.split('<details class="seasonbox epseason"', 1)[1].split("</details>", 1)[0]
    acts = season.split('<div class="seasonacts">', 1)[1].split("</div>", 1)[0]
    assert 'action="/media/resume/sea1/watched"' in acts and ">Mark season watched</button>" in acts
    assert 'name="scope" value="season"' in acts and 'name="show" value="ser1"' in acts
    assert 'name="season" value="4"' in acts and 'name="back" value="/media/item/ser1"' in acts
    for jf, action in (("ep1", "unwatched"), ("ep4", "watched"), ("ep5", "watched")):
        row = season.split(f'id="ep-{jf}"', 1)[1].split('<div class="row has-form', 1)[0]
        link = row.split("</a>", 1)[0]
        assert "<form" not in link                                            # the row stays one whole link
        side = row.split("</a>", 1)[1]
        assert f'action="/media/resume/{jf}/{action}"' in side and 'name="season" value="4"' in side
    row6 = season.split('id="ep-ep6"', 1)[1]
    assert "/media/resume/ep6/" not in row6                                   # not aired: nothing to mark


def test_season_header_flips_once_every_aired_episode_is_watched(wenv, monkeypatch):
    import tests.hub.test_media_resume as tmr
    monkeypatch.setattr(tmr, "EPISODES", [ep(1, "One", True), ep(2, "Two", True), ep(3, "Three", premiere=TOMORROW)])
    client, _, _ = wenv()
    with client:
        b = page(client, "/media/item/ser1")
    acts = b.split('<div class="seasonacts">', 1)[1].split("</div>", 1)[0]
    assert 'action="/media/resume/sea1/unwatched"' in acts and ">Mark season unwatched</button>" in acts


def test_episode_page_toggle_sits_in_the_hero_buttons(wenv):
    client, _, _ = wenv()
    with client:
        b = main_of(client.get("/media/item/ep3").text)                      # ep3 is watched
    btns = hero_btns(b)
    assert 'action="/media/resume/ep3/unwatched"' in btns and ">Mark unwatched</button>" in btns
    assert 'name="season" value="4"' in btns and 'name="back" value="/media/item/ep3"' in btns


def test_in_progress_pages_keep_the_move_on_pair_and_no_second_mark_watched(wenv):
    client, _, _ = wenv()
    with client:
        b = main_of(client.get("/media/item/mov1").text)                     # mov1 is 80 min in
    btns = hero_btns(b)
    assert btns.count(">Mark watched</button>") == 1 and "/media/resume/mov1/reset" in btns
    assert "/media/resume/mov1/unwatched" not in btns


def test_her_view_pages_carry_no_watch_buttons(wenv):
    client, _, _ = wenv()
    client.cookies.set("owner_view", "her")
    with client:
        for path in ("/media/item/ser1", "/media/item/ep3", "/media/item/mov1"):
            assert "/media/resume/" not in main_of(client.get(path).text), path


def test_both_view_pages_act_as_you(wenv):
    client, _, _ = wenv()
    client.cookies.set("owner_view", "both")
    with client:
        b = main_of(client.get("/media/item/ep3").text)
    assert 'action="/media/resume/ep3/unwatched"' in b and 'name="owner" value="you"' in b


def test_buttons_carry_words_beside_their_icons(wenv):
    client, _, _ = wenv()
    with client:
        b = main_of(client.get("/media/item/ser1").text)
    for word in ("Mark season watched", "Mark watched", "Mark unwatched"):
        assert f'</svg>{word}</button>' in b, word


def test_jellyfin_down_page_has_no_watch_buttons(wenv, monkeypatch):
    client, fake, _ = wenv()

    def boom(*a, **k):
        raise requests.ConnectionError("x")

    monkeypatch.setattr(requests, "get", boom)
    with client:
        b = main_of(client.get("/media/item/mov1").text)
    assert "/media/resume/" not in b
