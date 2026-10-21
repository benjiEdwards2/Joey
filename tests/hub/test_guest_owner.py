"""Joey TV WP-B2 step 5 (2026-10-21): the owner helpers FAIL CLOSED for `jf:` owners - the gate for ever enabling the
`media` compose profile (WP-B1 flagged that `owner_of('jf:x')` was `you` and `owner_filter` None, so a friend would
have read and written B.'s rows).

* `media_db.owner_of` / `owner_filter`: a well-formed `jf:<32 hex>` (hub.identity.OWNER_KEY_RE) passes through; any
  other `jf:` value raises; on the media front nothing but you / her / jf: maps to an owner (never 'both' -> B.).
* `media_plays_db` reads, `media_home.view_jelly` / `_profile_rows`, `media_resume.owner_of`: the friend's own rows or
  nothing - never B.'s, never Georgina's, never everyone's.
* P3 (2026-10-19, B. accepted): on the media front every Jellyfin read / write is the SIGNED-IN user's - for a `you`
  session (the alias user, Q16) exactly as for a friend; JELLYFIN_USER (the admin) is never substituted.
* `shell.resolve_owner_view` on the media front: the identity's owner, query and cookie ignored, never a cookie set.
The private-front meaning of every helper is unchanged (tests/hub/test_owner_filter.py, test_media_her.py,
test_identity.py are untouched)."""
import pytest
from fastapi.testclient import TestClient

from hub import guest, media_db, media_home, media_item, media_jellyfin, media_plays_db, media_resume
from hub.identity import Identity
from tests.hub.fake_jellyfin import (ADMIN_ID, ALIAS_ID, FRIEND_ID, HTTPS, KEY, OTHER_ID, URL, FakeJellyfin,
                                     media_env, reload_app, session_cookie)
from tests.hub.helpers import write_envelope

FRIEND = f"jf:{FRIEND_ID}"
OTHER = f"jf:{OTHER_ID}"
SNAP = {"summary": "x", "server_id": "srv-1",
        "up_next": [{"title": "SENTINEL_YOU_UPNEXT", "jf_id": "u1", "item_key": "tmdb:11", "kind": "movie",
                     "remaining_text": "31 min left"}],
        "now_playing": [{"title": "SENTINEL_YOU_NOW", "user": "Sample Admin", "jf_id": "n1"}],
        "history": {"recent": [{"title": "SENTINEL_YOU_HIST", "jf_id": "h1", "kind": "movie", "item_key": "tmdb:12"}]},
        "her": {"up_next": [{"title": "SENTINEL_HER_UPNEXT", "jf_id": "u2"}],
                "history": {"recent": [{"title": "SENTINEL_HER_HIST", "jf_id": "h2"}]}},
        "latest": [{"title": "Shared New One", "jf_id": "l1", "item_key": "tmdb:13", "type": "Movie",
                    "played": True, "last_played_at": "1999-01-01"}],
        "movies": [{"title": "Library Film", "jf_id": "mov1", "item_key": "tmdb:603", "played": True,
                    "last_played_at": "1999-01-01"}],
        "shows": [{"title": "Library Show", "jf_id": "ser1", "item_key": "jf:ser1", "played": False, "unplayed": 3}]}


# ---- the helpers themselves ----

def test_owner_of_passes_a_friend_key_through():
    assert media_db.owner_of(FRIEND) == FRIEND
    assert media_db.owner_filter(FRIEND) == FRIEND


@pytest.mark.parametrize("bad", ["jf:x", "jf:f00d", "jf:" + "F" * 32, "jf:" + "0" * 33, "jf:"])
def test_a_malformed_friend_key_never_becomes_an_owner(bad):
    with pytest.raises(ValueError):
        media_db.owner_of(bad)
    with pytest.raises(ValueError):
        media_db.owner_filter(bad)


def test_private_front_meanings_are_unchanged():
    assert [media_db.owner_of(v) for v in ("her", "you", "both", "x")] == ["her", "you", "you", "you"]
    assert [media_db.owner_filter(v) for v in ("you", "her", "both", None)] == ["you", "her", None, None]


@pytest.mark.parametrize("view", ["both", None, "none", "x"])
def test_on_the_media_front_nothing_else_maps_to_b(monkeypatch, view):
    monkeypatch.setenv("JOEY_FRONT", "media")
    with pytest.raises(ValueError):
        media_db.owner_of(view)
    with pytest.raises(ValueError):
        media_db.owner_filter(view)
    assert media_db.owner_of("you") == "you" and media_db.owner_of(FRIEND) == FRIEND


def test_play_reads_are_the_friends_own(monkeypatch):
    from datetime import datetime, timezone
    now = datetime(2026, 10, 21, 10, tzinfo=timezone.utc)
    for owner, title in (("you", "B Film"), ("her", "G Film"), (FRIEND, "F Film"), (OTHER, "O Film")):
        media_plays_db.record_sighting({"user_name": "x", "owner": owner, "jf_id": "same", "kind": "movie",
                                        "title": title, "item_key": "tmdb:1", "position_pct": 95,
                                        "runtime_min": 100}, now)
    assert [r["title"] for r in media_plays_db._rows("all", FRIEND, now)] == ["F Film"]
    assert media_plays_db.watch_count("same", FRIEND) == 1
    assert media_plays_db.watch_count("same", "jf:bad") == 0
    assert media_plays_db._rows("all", "jf:bad", now) == []
    assert {r["title"] for r in media_plays_db._rows("all", None, now)} == {"B Film", "G Film"}   # private: household


def test_view_jelly_for_a_friend_has_nothing_of_bs():
    out = media_home.view_jelly(SNAP, FRIEND)
    assert out["up_next"] == [] and out["history"] == {} and not out.get("now_playing")
    assert "her" not in out
    assert all("played" not in r and "last_played_at" not in r for k in ("latest", "movies", "shows") for r in out[k])
    assert "SENTINEL" not in repr(out)
    assert media_home._profile_rows(SNAP, FRIEND, lambda p: (p.get("history") or {}).get("recent") or []) == []


def test_view_jelly_on_the_media_front_hides_bs_snapshot_from_you_too(monkeypatch):
    """P3: on the media front `you` is the alias user - the admin's snapshot rows are not theirs either."""
    monkeypatch.setenv("JOEY_FRONT", "media")
    assert "SENTINEL" not in repr(media_home.view_jelly(SNAP, "you"))
    assert media_home._profile_rows(SNAP, "you", lambda p: (p.get("history") or {}).get("recent") or []) == []


def test_view_jelly_private_views_are_unchanged():
    assert media_home.view_jelly(SNAP, "you") is SNAP
    assert media_home.view_jelly(SNAP, "her")["up_next"][0]["title"] == "SENTINEL_HER_UPNEXT"
    rows = media_home._profile_rows(SNAP, "both", lambda p: (p.get("history") or {}).get("recent") or [])
    assert [o for _, o in rows] == ["you", "her"]


def test_jellyfin_user_id_is_never_the_admin_on_the_media_front(monkeypatch):
    monkeypatch.setenv("JOEY_FRONT", "media")
    monkeypatch.setenv("JELLYFIN_USER", "Sample Admin")
    users = lambda b, h: [{"Id": ADMIN_ID, "Name": "Sample Admin", "Policy": {"IsAdministrator": True}}]
    assert media_jellyfin.user_id("you", URL, {}, users) is None
    token = media_jellyfin.bind_viewer(FRIEND_ID)
    try:
        assert media_jellyfin.user_id("you", URL, {}, users) == FRIEND_ID
        assert media_jellyfin.user_id("her", URL, {}, users) == FRIEND_ID
    finally:
        media_jellyfin.reset_viewer(token)
    monkeypatch.delenv("JOEY_FRONT")
    assert media_jellyfin.user_id("you", URL, {}, users) == ADMIN_ID   # private front unchanged


# ---- through the media front ----

@pytest.fixture()
def fake(monkeypatch, tmp_path):
    media_env(monkeypatch)
    snaps = tmp_path / "snaps"
    monkeypatch.setenv("SNAPSHOT_DIR", str(snaps))
    write_envelope(snaps, "jellyfin", age_minutes=1, data=SNAP)
    return FakeJellyfin().install(monkeypatch)


@pytest.fixture()
def client(fake):
    with TestClient(reload_app(), base_url=HTTPS) as c:
        yield c


def sign_in(c, fake, uid):
    token = fake.token_for(uid)
    c.cookies.clear()
    for k, v in session_cookie(token).items():
        c.cookies.set(k, v)
    return token


def test_a_friends_rating_is_keyed_to_the_friend(client, fake):
    media_db.set_rating("tmdb:603", 9, "movie", "Library Film", owner="you")
    sign_in(client, fake, FRIEND_ID)
    r = client.post("/media/rate", data={"item_key": "tmdb:603", "score": "3", "kind": "movie",
                                         "title": "Library Film", "year": "1999"}, follow_redirects=False)
    assert r.status_code in (200, 303)
    assert media_db.get_ratings(["tmdb:603"], owner=FRIEND) == {"tmdb:603": 3}
    assert media_db.get_ratings(["tmdb:603"], owner="you") == {"tmdb:603": 9}   # B.'s row untouched


def test_the_diary_shows_only_the_friends_rows_whatever_the_view(client, fake):
    for n, (owner, title) in enumerate((("you", "SENTINEL_YOU_DB"), ("her", "SENTINEL_HER_DB"),
                                         (FRIEND, "Friend Logged Film"), (OTHER, "SENTINEL_OTHER_DB")), 1):
        media_db.add_manual_watch(f"tmdb:{900 + n}", "movie", title, watched_on="2026-10-20", owner=owner)
    media_db.set_setting("you", "diary_scope", "everyone")   # B.'s private choice must not reach the media front
    sign_in(client, fake, FRIEND_ID)
    for query, cookies in (("", {}), ("?owner_view=both", {}), ("", {"owner_view": "both"})):
        for k, v in cookies.items():
            client.cookies.set(k, v)
        r = client.get("/media/diary" + query, follow_redirects=False)
        assert r.status_code == 200
        assert "Friend Logged Film" in r.text and "SENTINEL" not in r.text
        assert not [h for h in r.headers.get_list("set-cookie") if h.startswith("owner_view=")]
    sign_in(client, fake, ALIAS_ID)
    r = client.get("/media/diary")
    assert "SENTINEL_YOU_DB" in r.text and "SENTINEL_HER_DB" not in r.text and "Friend Logged Film" not in r.text


def test_resolve_owner_view_is_the_identity_on_the_media_front(monkeypatch):
    monkeypatch.setenv("JOEY_FRONT", "media")
    from starlette.requests import Request
    from hub import shell
    scope = {"type": "http", "method": "GET", "path": "/", "query_string": b"owner_view=both",
             "headers": [(b"cookie", b"owner_view=both")],
             "state": {"identity": Identity(owner=FRIEND, name="Sample Friend", jf_user_id=FRIEND_ID)}}
    assert shell.resolve_owner_view(Request(scope)) == (FRIEND, False)
    anon = {**scope, "state": {}}
    view, from_query = shell.resolve_owner_view(Request(anon))
    assert view not in ("both", "you", "her") and from_query is False


@pytest.mark.parametrize("uid", [FRIEND_ID, ALIAS_ID])
def test_resume_writes_go_to_the_signed_in_jellyfin_user(client, fake, uid):
    """P3: a friend AND a `you` session (the alias user) act as themselves, with their own token - never the admin."""
    token = sign_in(client, fake, uid)
    for action in ("watched", "unwatched", "reset"):
        r = client.post(f"/media/resume/mov1/{action}", data={"back": "/media/movies", "owner": "her"},
                        follow_redirects=False)
        assert r.status_code == 303 and "error" not in r.headers["location"], (action, r.headers["location"])
    writes = [c for c in fake.calls if c[1].startswith(("/UserPlayedItems/", "/UserItems/"))]
    assert len(writes) == 3
    assert {c[4].get("userId") for c in writes} == {uid}
    assert {c[2].get("Token") for c in writes} == {token}
    assert not [c for c in fake.calls if ADMIN_ID in c[1] or c[4].get("userId") == ADMIN_ID or c[2].get("Token") == KEY
                and c[1] != "/Users"]


def test_a_friends_next_up_hide_is_keyed_to_the_friend(client, fake):
    sign_in(client, fake, FRIEND_ID)
    r = client.post("/media/resume/ep5/hide", data={"series": "jf:ser1", "back": "/media/movies", "owner": "you"},
                    follow_redirects=False)
    assert r.status_code == 303
    assert media_db.next_up_hidden() == {(FRIEND, "jf:ser1"): "ep5"}


def test_item_reads_are_the_viewers_own_and_cached_per_viewer(client, fake):
    fake.items["mov1"] = {"Id": "mov1", "Type": "Movie", "Name": "Library Film", "ProductionYear": 1999}
    fake.played[FRIEND_ID] = {"mov1"}
    sign_in(client, fake, FRIEND_ID)
    assert client.get("/media/item/mov1").status_code == 200
    sign_in(client, fake, OTHER_ID)
    assert client.get("/media/item/mov1").status_code == 200
    reads = [c[1] for c in fake.calls if c[1].endswith("/Items/mov1")]
    assert f"/Users/{FRIEND_ID}/Items/mov1" in reads and f"/Users/{OTHER_ID}/Items/mov1" in reads
    assert not [p for p in reads if ADMIN_ID in p]
    assert media_item.peek("mov1") is None   # outside a viewer's request there is no entry to see


def test_resume_owner_of_ignores_the_form_on_the_media_front(monkeypatch):
    monkeypatch.setenv("JOEY_FRONT", "media")
    from starlette.requests import Request
    scope = {"type": "http", "method": "POST", "path": "/", "query_string": b"", "headers": [],
             "state": {"identity": Identity(owner=FRIEND, name="Sample Friend", jf_user_id=FRIEND_ID)}}
    assert media_resume.owner_of(Request(scope), {"owner": "her"}) == FRIEND
