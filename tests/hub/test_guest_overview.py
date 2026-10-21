"""Joey TV WP-B3 steps 2 and 7 (2026-10-21): the guest Overview and the one-time "Set up Jellyfin" card.

Overview = exactly [Continue watching, Recently added, Recently watched] (DECISIONS C; WP-M call 4: no hero). The first
and last are live reads of the signed-in user's own Jellyfin state WITH THEIR OWN TOKEN (`/UserItems/Resume`,
`/Items?userId=…&SortBy=DatePlayed&IsPlayed=true`), cached 60 s per user, 3 s timeout, the shelf omitted when the read
fails (logs carry the exception type only). For a `you` session they are the alias user's items (P3, 2026-10-19): the
admin's lounge-room state never appears. Recently added comes from the scrubbed snapshot `latest`. No hero, no
Downloading, Arrived, Requests, backup warning or household Up next.

The Set up Jellyfin card (Q39): shown on the Overview until dismissed (a cookie), with the server address rendered from
JELLYFIN_PUBLIC_URL, port included (the official app does not find the server without `:8443`)."""
import logging

import pytest

from hub import guest, media_guest_home
from tests.hub.fake_jellyfin import ADMIN_ID, ALIAS_ID, FRIEND_ID, KEY, PUBLIC_URL
from tests.hub.guest_pages import episode, guest_client, movie, shelf_titles, sign_in

HOUSE = {"summary": "SENTINEL_HOUSE_SUMMARY", "server_id": "srv-1",
         "now_playing": [{"title": "SENTINEL_HOUSE_NOW", "user": "SENTINEL_HOUSE_USER", "jf_id": "n1",
                          "progress_pct": 40, "play_method": "DirectPlay"}],
         "up_next": [{"title": "SENTINEL_HOUSE_UPNEXT", "jf_id": "u1", "item_key": "tmdb:11", "kind": "movie",
                      "remaining_text": "31 min left", "poster": "jf:u1"}],
         "history": {"recent": [{"title": "SENTINEL_HOUSE_HIST", "jf_id": "h1", "kind": "movie", "item_key": "tmdb:12",
                                 "when": "today", "watched_at": "2026-10-20T10:00:00Z"}]},
         "latest": [{"title": "Shared Arrival", "jf_id": "d0d0" * 8, "item_key": "tmdb:13", "type": "Movie",
                     "poster": "jf:" + "d0d0" * 8, "added_at": "2026-10-19T10:00:00Z", "played": True,
                     "last_played_at": "1999-01-01"}],
         "library": {"movies": 1, "episodes": 0}, "movies": [], "shows": []}
ARR = {"arrived": [{"title": "SENTINEL_HOUSE_ARRIVED", "when": "today"}],
       "downloading": [{"title": "SENTINEL_HOUSE_DL", "caption": "40%"}]}
QBIT = {"active": [{"name": "SENTINEL_HOUSE_TORRENT"}]}
SEERR = {"requests": [{"id": 1, "title": "SENTINEL_HOUSE_REQUEST", "requested_by": "SENTINEL_HOUSE_REQUESTER"}]}

RESUME_FILM = movie("aaaa" * 8, "Friend Resume Film", "603", minutes=120, at_min=72)
RESUME_EP = episode("bbbb" * 8, "Friend Show", "cccc" * 8, 1, 4, "The Fourth", minutes=45, at_min=24)
WATCHED = movie("eeee" * 8, "Friend Watched Film", "604", played_at="2026-10-19T20:00:00.0000000Z")


@pytest.fixture()
def gc(monkeypatch, tmp_path):
    client, fake = guest_client(monkeypatch, tmp_path, {"jellyfin": HOUSE, "arr": ARR, "qbittorrent": QBIT,
                                                         "jellyseerr": SEERR})
    fake.resume[FRIEND_ID] = [RESUME_FILM, RESUME_EP]
    fake.history[FRIEND_ID] = [WATCHED]
    with client as c:
        c.fake = fake
        yield c


def home(c):
    r = c.get(guest.home_path())
    assert r.status_code == 200
    return r.text


def main(html: str) -> str:
    return html.split("<main", 1)[1]


def test_overview_three_shelves_with_the_friends_own_items(gc):
    token = sign_in(gc, gc.fake, FRIEND_ID)
    html = home(gc)
    assert shelf_titles(html) == ["Continue watching", "Recently added", "Recently watched"]
    body = main(html)
    for words in ("Friend Resume Film", "Friend Show", "Shared Arrival", "Friend Watched Film"):
        assert words in body, words
    assert body.index("Friend Resume Film") < body.index("Shared Arrival") < body.index("Friend Watched Film")
    assert "/media/item/" + "aaaa" * 8 in body and "/media/item/" + "eeee" * 8 in body
    assert "jf:" + "cccc" * 8 in body or "cccc" * 8 in body          # an episode shows its series' poster
    reads = [c for c in gc.fake.calls if c[1] in ("/UserItems/Resume", "/Items")]
    assert {c[1] for c in reads} == {"/UserItems/Resume", "/Items"}
    assert {c[2].get("Token") for c in reads} == {token}              # the friend's own token, never the admin key
    assert {str(c[4].get("userId")) for c in reads} == {FRIEND_ID}
    items = next(c for c in reads if c[1] == "/Items")[4]
    assert (items.get("SortBy"), str(items.get("IsPlayed")).lower()) == ("DatePlayed", "true")


def test_household_rows_never_reach_the_guest_overview(gc):
    sign_in(gc, gc.fake, FRIEND_ID)
    html = home(gc)
    assert "SENTINEL_" not in html and "1999-01-01" not in html
    assert "Open in Jellyfin" not in html and "Downloading" not in html and "Most played" not in html
    assert "Nothing playing" not in html and "Up next" not in main(html)


def test_bs_alias_session_reads_the_alias_users_items_not_the_admins(gc):
    gc.fake.resume[ALIAS_ID] = [movie("ab12" * 8, "Alias Resume Film", "605", at_min=10)]
    gc.fake.resume[ADMIN_ID] = [movie("ad00" * 8, "Admin Lounge Film", "606", at_min=10)]
    sign_in(gc, gc.fake, ALIAS_ID)
    html = home(gc)
    assert "Alias Resume Film" in html and "Admin Lounge Film" not in html and "SENTINEL_" not in html
    reads = [c for c in gc.fake.calls if c[1] in ("/UserItems/Resume", "/Items")]
    assert {str(c[4].get("userId")) for c in reads} == {ALIAS_ID} and KEY not in {c[2].get("Token") for c in reads}


def test_jellyfin_down_leaves_only_recently_added(gc, caplog):
    sign_in(gc, gc.fake, FRIEND_ID)
    gc.fake.shelf_raises = TimeoutError
    with caplog.at_level(logging.WARNING):
        html = home(gc)
    assert shelf_titles(html) == ["Recently added"]
    assert "Shared Arrival" in html
    logged = " ".join(r.getMessage() for r in caplog.records)
    assert "TimeoutError" in logged and "jellyfin.test" not in logged and "Read timed out" not in logged


def test_shelf_reads_use_a_3s_timeout_and_are_cached_60s_per_user(gc, monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(media_guest_home, "clock", lambda: now[0])
    seen = []
    real_get = gc.fake.get

    def spy(url, params=None, headers=None, timeout=None, **kw):
        if url.endswith(("/UserItems/Resume", "/Items")):
            seen.append(timeout)
        return real_get(url, params=params, headers=headers, timeout=timeout, **kw)

    import requests
    monkeypatch.setattr(requests, "get", spy)
    sign_in(gc, gc.fake, FRIEND_ID)
    home(gc)
    home(gc)
    assert seen == [media_guest_home.TIMEOUT] * 2 and media_guest_home.TIMEOUT == 3
    now[0] += media_guest_home.TTL + 1
    home(gc)
    assert len(seen) == 4 and media_guest_home.TTL == 60


def test_an_empty_resume_list_keeps_the_heading_with_quiet_words(gc):
    gc.fake.resume[FRIEND_ID] = []
    sign_in(gc, gc.fake, FRIEND_ID)
    assert shelf_titles(home(gc)) == ["Continue watching", "Recently added", "Recently watched"]


def test_private_front_overview_is_unchanged(monkeypatch, tmp_path):
    client, fake = guest_client(monkeypatch, tmp_path, {"jellyfin": HOUSE})
    monkeypatch.setenv("JOEY_FRONT", "private")
    with client as c:
        html = c.get("/a/media").text
    assert "SENTINEL_HOUSE_UPNEXT" in html                    # the household's own Up next, as ever
    assert not [x for x in fake.calls if x[1] == "/UserItems/Resume"]


# ---- the Set up Jellyfin card (Q39, step 7) ----

def test_setup_card_shows_on_the_first_visit_and_not_after_dismissal(gc):
    sign_in(gc, gc.fake, FRIEND_ID)
    first = home(gc)
    assert "Set up Jellyfin" in first and PUBLIC_URL in first and ":8443" in first
    done = gc.get(guest.home_path() + "?setup=done")
    assert done.status_code == 200 and "Set up Jellyfin" not in done.text
    assert any(h.startswith("jm_setup=1;") and "Max-Age=31536000" in h and "SameSite=Lax" in h
               for h in done.headers.get_list("set-cookie"))
    assert "Set up Jellyfin" not in home(gc)                  # the cookie keeps it dismissed


def test_setup_card_needs_the_public_url(gc, monkeypatch):
    monkeypatch.delenv("JELLYFIN_PUBLIC_URL")
    sign_in(gc, gc.fake, FRIEND_ID)
    assert "Set up Jellyfin" not in home(gc)
