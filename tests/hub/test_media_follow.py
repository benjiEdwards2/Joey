"""Follow (2026-10-07): follow a person or a film series; their NEW films are requested through Jellyseerr.
Jellyfin / Jellyseerr / Discord are faked at `requests.get` / `requests.post` via the film page's fixtures."""
import re
from datetime import date, timedelta

from hub import media_follow
from tests.hub.film_page import whole
from tests.hub.helpers import env, SEERR_URL as SEERR, SKEY  # noqa: F401  (re-export: defined in tests/hub/helpers.py)
from tests.hub.conftest import main_of  # noqa: F401

TODAY = date.today()
PAST = (TODAY - timedelta(days=400)).isoformat()
SOON = (TODAY + timedelta(days=90)).isoformat()
HOOK = "https://discord.invalid/api/webhooks/1/secret-token"
ORIGIN_BAD = {"Origin": "https://evil.invalid"}


def film(i, title, when=SOON, **extra):
    return {"id": i, "mediaType": "movie", "title": title, "releaseDate": when, "posterPath": f"/f{i}.jpg", **extra}


# Jellyseerr's person credits carry no `order` (verified against server/models/Person.ts): billing comes from
# each film's own /movie/{id} credits.cast, faked in BILLING (film id -> Ada's order there).
BILLING = {1: 0, 2: 4, 3: 5, 4: 0, 5: 1, 6: 0, 7: 0, 10: 9}
CREDITS = {
    "cast": [
        film(1, "Lead Role"),
        film(2, "Fifth Billed"),
        film(3, "Sixth Billed"),
        film(4, "Old Lead", when=PAST),
        film(5, "Undated Lead", when=""),
        film(6, "Already Requested", mediaInfo={"status": 2}),
        film(7, "Already Available", mediaInfo={"status": 5}),
        film(10, "Cameo"),
        film(11, "Not In Cast List"),
        {"id": 50, "mediaType": "tv", "name": "Some Show", "firstAirDate": SOON},
    ],
    "crew": [
        film(8, "Directed It", job="Director"),
        film(3, "Sixth Billed", job="Director"),          # both roles: the director rule adds it
        film(9, "Produced It", job="Producer"),
        {"id": 51, "mediaType": "tv", "name": "Directed Show", "firstAirDate": SOON, "job": "Director"},
    ],
}
PERSON = {"id": 55, "name": "Ada Actor", "knownForDepartment": "Acting", "profilePath": "/ada.jpg"}


def seed(both, credits=CREDITS, billing=BILLING):
    both.seerr.table["/api/v1/person/55"] = PERSON
    both.seerr.table["/api/v1/person/55/combined_credits"] = credits
    for i, order in billing.items():
        both.seerr.table[f"/api/v1/movie/{i}"] = {"id": i, "credits": {"cast": [
            {"id": 99, "name": "Someone", "order": 0 if order else 1}, {"id": 55, "name": "Ada Actor", "order": order}]}}


def seerr_posts(both):
    return [j for u, j in both.seerr.posts if u.startswith(SEERR)]


def discord_posts(both):
    return [j for u, j in both.seerr.posts if u == HOOK]


def follow_person(client):
    return client.post("/media/follow/person/55", data={"back": "/media/person/55"}, follow_redirects=False)


# ---- follow / unfollow ----

def test_follow_and_unfollow_require_same_origin(env):
    client, both = env()
    seed(both)
    with client:
        assert client.post("/media/follow/person/55", headers=ORIGIN_BAD).status_code == 403
        assert client.post("/media/follow/collection/9/unfollow", headers=ORIGIN_BAD).status_code == 403
        assert client.post("/media/follow/tv/9", data={}).status_code == 404
    assert media_follow.follows() == []


def test_follow_is_instant_redirects_with_flash_and_unfollow_reverses(env):
    client, both = env()
    seed(both)
    with client:
        r = follow_person(client)
        assert r.status_code == 303 and r.headers["location"] == "/media/person/55?follow=on"
        f = media_follow.get("person", 55)
        assert f["name"] == "Ada Actor" and f["followed_at"] == TODAY.isoformat() and f["poster"] == "tmdb:/ada.jpg"
        b = main_of(client.get("/media/person/55?follow=on").text)
        assert "Following ✓" in b and 'action="/media/follow/person/55/unfollow"' in b and "Following — new films" in b
        r = client.post("/media/follow/person/55/unfollow", data={"back": "/media/person/55"}, follow_redirects=False)
        assert r.headers["location"] == "/media/person/55?follow=off"
        b = main_of(client.get("/media/person/55").text)
        assert '<button class="btn btn-secondary btn-sm" type="submit">Follow</button>' in b
    assert media_follow.get("person", 55) is None


def test_follow_runs_the_check_straight_away_and_back_is_local_only(env):
    client, both = env()
    seed(both)
    with client:
        r = client.post("/media/follow/person/55", data={"back": "https://evil.invalid/x"}, follow_redirects=False)
    assert r.headers["location"] == "/media/person/55?follow=on"
    assert {j["mediaId"] for j in seerr_posts(both)} == {1, 2, 3, 8}


# ---- the rules ----

def test_rules_date_billing_director_both_roles_tv_and_status(env):
    client, both = env()
    seed(both)
    with client:
        media_follow.follow("person", 55, "Ada Actor")
        got = media_follow.run_once()
    posts = seerr_posts(both)
    assert all(j == {"mediaType": "movie", "mediaId": j["mediaId"]} for j in posts)      # films only, Discover's payload
    assert {j["mediaId"] for j in posts} == {1, 2, 3, 8}
    # 3: order 5 but directed; 4: already released; 5: no date (never qualifies since 2026-10-08); 6/7 in Jellyseerr; 9 producer; 10 billed 9th;
    # 11: not in the film's cast list; TV never
    assert got["requested"] == 4 and got["already"] == 2   # undated film 5 no longer qualifies (2026-10-08)
    adds = {a["tmdb_id"]: a for a in media_follow.recent_adds(50)}
    assert adds[1]["reason"] == "top-5 cast" and adds[3]["reason"] == "director" and adds[8]["reason"] == "director"
    assert adds[6]["outcome"] == "already" and adds[7]["outcome"] == "already" and 4 not in adds and 50 not in adds
    assert not [c for c in both.calls if "/tv/" in c]
    assert not [c for c in both.calls if c.endswith("/api/v1/movie/4")]        # past films are never even read


def test_actor_order_five_excluded_without_director_credit(env):
    client, both = env()
    seed(both, {"cast": [film(3, "Sixth Billed"), film(2, "Fifth")], "crew": []}, {3: 5, 2: 4})
    with client:
        media_follow.follow("person", 55, "Ada")
        media_follow.run_once()
    assert [j["mediaId"] for j in seerr_posts(both)] == [2]


def test_order_on_the_credit_itself_is_used_when_present(env):
    client, both = env()
    seed(both, {"cast": [film(3, "Sixth Billed", order=5), film(2, "Fifth", order=4)], "crew": []}, {})
    with client:
        media_follow.follow("person", 55, "Ada")
        media_follow.run_once()
    assert [j["mediaId"] for j in seerr_posts(both)] == [2]


def test_follow_date_rule_uses_the_follow_day():
    # Tightened 2026-10-08 (B.: "only add things that are releasing in the future of the date currently"):
    # a known date strictly after today; today itself, the past, and unknown / TBA dates never qualify.
    today = date(2026, 10, 8)
    assert media_follow.qualifies("2026-10-09", today)
    assert not media_follow.qualifies("2026-10-08", today)
    assert not media_follow.qualifies("2026-10-06", today)
    assert not media_follow.qualifies("", today) and not media_follow.qualifies("TBA", today)


def test_collection_parts_are_requested(env):
    client, both = env()
    both.seerr.table["/api/v1/collection/9"] = {"name": "Harbour Collection", "parts": [
        film(603, "Harbour Lights", when=PAST, mediaInfo={"status": 5}), film(605, "Harbour Lights 3"),
        {**film(606, "Harbour Lights 4", when=""), "mediaType": None}]}
    with client:
        r = client.post("/media/follow/collection/9", data={"back": "/media/title/movie/603"}, follow_redirects=False)
        assert r.headers["location"] == "/media/title/movie/603?follow=on"
    assert sorted(j["mediaId"] for j in seerr_posts(both)) == [605]
    f = media_follow.get("collection", 9)
    assert f["name"] == "Harbour Collection" and f["link"] == "/media/title/movie/603"


def test_never_re_request_a_recorded_title(env):
    client, both = env()
    seed(both)
    with client:
        media_follow.follow("person", 55, "Ada")
        media_follow.run_once()
        n = len(seerr_posts(both))
        again = media_follow.run_once()
    assert len(seerr_posts(both)) == n and again["requested"] == 0


def test_failed_request_recorded_and_retried(env):
    client, both = env()
    seed(both, {"cast": [film(1, "Lead", order=0)], "crew": []})
    both.seerr.post_status = 500
    with client:
        media_follow.follow("person", 55, "Ada")
        assert media_follow.run_once()["failed"] == 1
        assert media_follow.recent_adds()[0]["outcome"] == "failed"
        both.seerr.post_status = 201
        assert media_follow.run_once()["requested"] == 1
    assert media_follow.recent_adds()[0]["outcome"] == "requested"


def test_409_from_jellyseerr_is_already(env):
    client, both = env()
    seed(both, {"cast": [film(1, "Lead", order=0)], "crew": []})
    both.seerr.post_status = 409
    with client:
        media_follow.follow("person", 55, "Ada")
        media_follow.run_once()
    assert media_follow.recent_adds()[0]["outcome"] == "already"


def test_cap_ten_then_deferred_go_next_run(env):
    client, both = env()
    seed(both, {"cast": [film(100 + i, f"Film {i}", order=0) for i in range(13)], "crew": []})
    with client:
        media_follow.follow("person", 55, "Ada")
        first = media_follow.run_once()
        second = media_follow.run_once()
    assert first["requested"] == 10 and first["deferred"] == 3
    assert second["requested"] == 3 and second["deferred"] == 0 and len(seerr_posts(both)) == 13


def test_no_keys_means_no_calls_and_the_page_says_so(env, monkeypatch):
    client, both = env()
    monkeypatch.delenv("JELLYSEERR_URL")
    with client:
        media_follow.follow("person", 55, "Ada")
        assert media_follow.run_once().get("skipped_no_keys")
        b = main_of(client.get("/media/following").text)
    assert "Follow needs Seerr" in b
    assert not [c for c in both.calls if c.startswith(SEERR)] and not both.seerr.posts


# ---- Discord ----

def test_discord_one_post_per_add(env, monkeypatch):
    monkeypatch.setenv("SERVER_DISCORD_WEBHOOK", HOOK)
    monkeypatch.delenv("MEDIA_DISCORD_WEBHOOK", raising=False)
    client, both = env()
    seed(both, {"cast": [film(1, "Lead Role", when="2099-03-01", order=0), film(7, "Have It", order=0, mediaInfo={"status": 5})],
                "crew": [film(8, "Directed It", when="2099-05-01", job="Director")]})
    with client:
        media_follow.follow("person", 55, "Ada Actor")
        media_follow.run_once()
    msgs = sorted(j["content"] for j in discord_posts(both))
    assert msgs == ["Joey Media: added Directed It (2099) — director · following Ada Actor",
                    "Joey Media: added Lead Role (2099) — top-5 cast · following Ada Actor"]


def test_media_webhook_overrides_and_silent_when_unset(env, monkeypatch):
    monkeypatch.delenv("SERVER_DISCORD_WEBHOOK", raising=False)
    monkeypatch.delenv("MEDIA_DISCORD_WEBHOOK", raising=False)
    client, both = env()
    seed(both, {"cast": [film(1, "Lead", order=0)], "crew": []})
    with client:
        media_follow.follow("person", 55, "Ada")
        media_follow.run_once()
    assert len(seerr_posts(both)) == 1 and len(both.seerr.posts) == 1          # no Discord call
    monkeypatch.setenv("SERVER_DISCORD_WEBHOOK", "https://other.invalid/hook")
    monkeypatch.setenv("MEDIA_DISCORD_WEBHOOK", HOOK)
    assert media_follow.webhook() == HOOK


# ---- pages ----

def test_following_page_rows_and_recent_adds(env):
    client, both = env()
    seed(both, {"cast": [film(1, "Lead Role", when="2099-03-01", order=0)], "crew": []})
    both.seerr.table["/api/v1/collection/9"] = {"name": "Harbour Collection", "posterPath": "/hc.jpg",
                                                "parts": [film(603, "Harbour Lights", when=PAST)]}
    with client:
        follow_person(client)
        client.post("/media/follow/collection/9", data={"back": "/media/title/movie/603"})
        b = main_of(client.get("/media/following").text)
    assert '<a href="/media/following" aria-current="page">Following</a>' in b
    assert '<a class="row" href="/media/person/55">' in b and "Ada Actor" in b and "Actor · top-5 billed" in b
    assert '<a class="row" href="/media/title/movie/603">' in b and "Film series" in b and "Harbour Collection" in b
    assert "1 added" in b and "0 added" in b
    recent = b.split("Recently added by follows", 1)[1]
    assert '<a class="row" href="/media/title/movie/1">' in recent and "Lead Role (2099)" in recent
    assert "Requested" in recent and "top-5 cast" in recent
    assert "secret-token" not in b and SKEY not in b


def test_following_empty_state_and_director_word(env):
    client, both = env()
    with client:
        b = main_of(client.get("/media/following").text)
        assert "Follow an actor, director, creator, film series or show from their page." in b   # F5: shows too
        media_follow.follow("person", 77, "Dee Director", dept="Directing")
        b = main_of(client.get("/media/following").text)
    assert "Dee Director" in b and "Director" in b and "top-5" not in b


def test_home_shelf_only_with_a_follow(env):
    client, both = env()
    seed(both, {"cast": [film(1, "Lead Role", when="2099-03-01", order=0)], "crew": []})
    with client:
        assert "New from people you follow" not in client.get("/a/alpha").text
        follow_person(client)
        b = main_of(client.get("/a/alpha").text)
    shelf = b.split("New from people you follow", 1)[1].split("</section>", 1)[0]
    assert 'href="/media/following"' in shelf and '<a class="card-poster" href="/media/title/movie/1">' in shelf
    assert "Lead Role" in shelf and "2099 · Ada Actor" in shelf


def test_film_page_follow_series_button(env):
    client, both = env()
    with client:
        b = main_of(whole(client, "/media/title/movie/603"))
        assert 'action="/media/follow/collection/9"' in b and "Follow series" in b
        assert b.count("Follow series") == 1                                   # only the collection shelf
        client.post("/media/follow/collection/9", data={"back": "/media/title/movie/603"})
        b = main_of(whole(client, "/media/title/movie/603?follow=on"))
    assert 'action="/media/follow/collection/9/unfollow"' in b and "Following series ✓" in b


def test_person_page_show_more_after_24(env):
    client, both = env()
    seed(both, {"cast": [film(1000 + i, f"Film {i:02d}", when=f"{2000 + i}-01-01", order=9) for i in range(30)], "crew": []})
    with client:
        b = main_of(client.get("/media/person/55").text)
    grid, more = b.split('<details class="showmore">', 1)
    assert len(re.findall(r'class="card-poster"', grid)) == 24 and "Show more · 6" in more
    assert len(re.findall(r'class="card-poster"', more)) == 6
    assert "Film 29" in grid and "Film 00" in more                           # newest first, oldest folded


def test_person_page_short_list_has_no_show_more(env):
    client, both = env()
    seed(both)
    with client:
        b = main_of(client.get("/media/person/55").text)
    assert "showmore" not in b


def test_media_follow_off_disables_the_loop(monkeypatch):
    monkeypatch.setenv("MEDIA_FOLLOW", "off")
    assert media_follow.disabled()
    monkeypatch.delenv("MEDIA_FOLLOW")
    assert not media_follow.disabled() and media_follow.FIRST_DELAY_S == 120 and media_follow.EVERY_S == 6 * 3600
