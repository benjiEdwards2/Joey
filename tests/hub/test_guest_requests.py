"""Joey TV WP-B4 (2026-10-21): friend requests through Seerr on the media front.

DECISIONS B #19: friends request via Discover and EVERY friend request waits for B.'s approval. The W3 probe (2026-10-21,
fixtures tests/hub/fixtures/seerr_*.json, fake tests/hub/fake_seerr.py) proved the mechanism:

* a friend's request is sent with the admin `X-Api-Key` AND `X-Api-User: <the friend's Seerr id>` - never the bare key
  (that would be the admin's, auto-approved);
* the Seerr id is looked up in `GET /api/v1/user?take=500` by `jellyfinUserId` (dash-less, lower case), cached 1 h;
  a friend with no Seerr user is imported on their first request (`POST /api/v1/user/import-from-jellyfin`, that
  friend only, Q29), then looked up once more; still none -> "Requests aren't set up for you yet" and no request;
* pending only: a friend whose Seerr user could approve (ADMIN / MANAGE_REQUESTS / AUTO_APPROVE*) is refused before
  anything is sent; the quality safety net and Sonarr's follow (admin side effects, Q19) never run on the media front
  (WP-RQ2, 2026-10-22: the friend's quality pick rides their own pending request - tests/hub/test_guest_request_picks.py);
* decline is B.'s, in Seerr: no guest page carries a decline / approve / remove control and the hub never calls
  `/decline`; once B. declines, the friend's title page and Discover chip say Declined;
* the request route is GUEST (moved from RESERVED); every admin path stays PRIVATE; B.'s own request (private front,
  or the household alias on the media front) is byte-identical to before: no `X-Api-User`.

The Discover screen is WP-M screen 10 (mockups/tv-mode.html): a poster grid with In library / Requested / Request
chips; a poster opens the request panel; Request -> "Requested — waiting for approval" and the grid chip updates.
Names are invented ("Sample Friend")."""
from __future__ import annotations

import re

import pytest

from hub import guest, media_arr_search, media_guest_requests, media_quality
from tests.hub.fake_jellyfin import ALIAS_ID, FRIEND_ID, OTHER_ID
from tests.hub.fake_seerr import (ADMIN, AUTO_APPROVE, AUTO_APPROVE_MOVIE, KEY, MANAGE_REQUESTS, REQUEST, FakeSeerr,
                                  res)
from tests.hub.guest_pages import TV_UA, guest_client, links_of, sign_in
from tests.hub.test_media_discover import env  # noqa: F401 - the private-front fixture (B.'s request, unchanged)

HX = {"HX-Request": "true"}
FORM = {"content-type": "application/x-www-form-urlencoded"}
SEERR_SNAP = {"jellyseerr": {"summary": "x", "requests": []}}
FRIEND_SEERR = 7
WAITING = "Requested — waiting for approval"
NOT_SET_UP = "set up for you yet"


def seed(seerr: FakeSeerr) -> FakeSeerr:
    seerr.titles[("movie", 701)] = {**res(701, "Harvest Moon Rising"), "tagline": "", "genres": []}
    seerr.titles[("movie", 603)] = {**res(603, "Salt and Static", status=5), "genres": []}
    seerr.titles[("movie", 702)] = {**res(702, "Pale Horizon"), "mediaInfo": {"status": 2, "requests": [
        {"id": 5, "status": 1, "requestedBy": {"id": 1, "displayName": "SENTINEL_SEERR_REQUESTER",
                                               "email": "SENTINEL_SEERR_EMAIL"}}]}}
    seerr.titles[("tv", 100)] = {**res(100, "Tangle of Wires", "tv", status=1), "numberOfSeasons": 2,
                                 "seasons": [{"seasonNumber": 1, "name": "Season 1", "episodeCount": 8},
                                             {"seasonNumber": 2, "name": "Season 2", "episodeCount": 8}]}
    seerr.shelves = {
        "/api/v1/discover/trending": [res(701, "Harvest Moon Rising"), res(603, "Salt and Static", status=5),
                                      res(702, "Pale Horizon", status=2)],
        "/api/v1/discover/movies": [res(701, "Harvest Moon Rising"), res(703, "Marigold Lane")],
        "/api/v1/discover/tv": [res(100, "Tangle of Wires", "tv", status=1)],
        "/api/v1/discover/movies/upcoming": [], "/api/v1/discover/tv/upcoming": [],
    }
    seerr.search = [res(704, "Searchable Film"), res(603, "Salt and Static", status=5)]
    return seerr


def start(monkeypatch, tmp_path, uid: str = FRIEND_ID):
    client, fake = guest_client(monkeypatch, tmp_path, SEERR_SNAP)
    seerr = seed(FakeSeerr().install(monkeypatch))
    return client, fake, seerr, uid


@pytest.fixture()
def friend(monkeypatch, tmp_path):
    client, fake, seerr, uid = start(monkeypatch, tmp_path)
    with client as c:
        c.fake, c.seerr = fake, seerr
        sign_in(c, fake, uid)
        yield c


@pytest.fixture()
def follows(monkeypatch):
    """Records every admin side effect a request could trigger (Sonarr follow, the quality safety net)."""
    got = []
    monkeypatch.setattr(media_arr_search, "follow_all", lambda *a, **k: got.append(("follow_all", a)) or "ok")
    monkeypatch.setattr(media_quality, "ensure", lambda *a, **k: got.append(("ensure", a)) or "ok")
    monkeypatch.setattr(media_quality, "profiles", lambda kind: [{"id": 4, "name": "HD-1080p", "default": True},
                                                                 {"id": 5, "name": "Ultra-HD", "default": False}])
    return got


def request_posts(seerr) -> list[tuple]:
    return seerr.posts_to("/api/v1/request")


def post(c, path: str, body: str = "", htmx: bool = True):
    return c.post(path, content=body, headers={**(HX if htmx else {}), **FORM}, follow_redirects=False)


# ---- the request is the friend's own (X-Api-User), imported on the first request (Q29) ----

def test_first_request_imports_the_friend_then_sends_as_them(friend):
    seerr = friend.seerr
    assert seerr.user_for(FRIEND_ID) is None
    r = post(friend, "/media/title/movie/701/request")
    assert r.status_code == 200 and WAITING in r.text
    imports = seerr.posts_to("/api/v1/user/import-from-jellyfin")
    assert len(imports) == 1 and imports[0][3] == {"jellyfinUserIds": [FRIEND_ID]}   # that friend only
    new_id = seerr.user_for(FRIEND_ID)["id"]
    [sent] = request_posts(seerr)
    assert sent[3] == {"mediaType": "movie", "mediaId": 701}
    assert sent[4]["X-Api-Key"] == KEY and sent[4]["X-Api-User"] == str(new_id)
    assert seerr.requests[-1]["status"] == 1 and seerr.requests[-1]["requestedBy"]["id"] == new_id   # pending, theirs
    order = [(m, p) for m, p, *_ in seerr.calls if m == "POST" or p == "/api/v1/user"]
    assert order == [("GET", "/api/v1/user"), ("POST", "/api/v1/user/import-from-jellyfin"), ("GET", "/api/v1/user"),
                     ("POST", "/api/v1/request")]
    assert KEY not in r.text


def test_an_imported_friend_is_not_imported_again(friend):
    friend.seerr.add_user(FRIEND_SEERR, FRIEND_ID)
    assert WAITING in post(friend, "/media/title/movie/701/request").text
    assert friend.seerr.count("POST", "/api/v1/user/import-from-jellyfin") == 0
    assert request_posts(friend.seerr)[0][4]["X-Api-User"] == str(FRIEND_SEERR)


def test_the_lookup_matches_a_dashed_upper_case_jellyfin_id(friend):
    dashed = "-".join([FRIEND_ID[:8], FRIEND_ID[8:12], FRIEND_ID[12:16], FRIEND_ID[16:20], FRIEND_ID[20:]]).upper()
    friend.seerr.add_user(FRIEND_SEERR, dashed)
    assert WAITING in post(friend, "/media/title/movie/701/request").text
    assert request_posts(friend.seerr)[0][4]["X-Api-User"] == str(FRIEND_SEERR)


def test_import_that_creates_nobody_is_norequests_and_no_request(friend):
    friend.seerr.import_creates = False
    r = post(friend, "/media/title/movie/701/request")
    assert r.status_code == 200 and NOT_SET_UP in r.text
    assert friend.seerr.count("POST", "/api/v1/user/import-from-jellyfin") == 1   # exactly one import, one re-lookup
    assert friend.seerr.count("GET", "/api/v1/user") == 2
    assert request_posts(friend.seerr) == []


def test_a_failed_import_is_norequests_and_no_request(friend):
    friend.seerr.import_status = 500
    assert NOT_SET_UP in post(friend, "/media/title/movie/701/request").text
    assert request_posts(friend.seerr) == []


@pytest.mark.parametrize("how", ["status", "raises"])
def test_a_lookup_failure_sends_nothing(friend, how):
    """Never a fall back to the bare key: no user list -> no import, no request."""
    if how == "status":
        friend.seerr.users_status = 500
    else:
        import requests
        friend.seerr.users_raises = requests.ConnectionError
    r = post(friend, "/media/title/movie/701/request")
    assert r.status_code == 200 and "send the request" in r.text
    assert [c for c in friend.seerr.calls if c[0] == "POST"] == []


def test_the_user_lookup_is_cached_for_an_hour(friend, monkeypatch):
    friend.seerr.add_user(FRIEND_SEERR, FRIEND_ID)
    now = [1000.0]
    monkeypatch.setattr(media_guest_requests, "_clock", lambda: now[0])
    post(friend, "/media/title/movie/701/request")
    post(friend, "/media/title/movie/703/request")
    assert friend.seerr.count("GET", "/api/v1/user") == 1
    now[0] += 3601
    post(friend, "/media/title/tv/100/request", "seasons=1")
    assert friend.seerr.count("GET", "/api/v1/user") == 2
    assert [p[4]["X-Api-User"] for p in request_posts(friend.seerr)] == [str(FRIEND_SEERR)] * 3


# ---- pending only ----

@pytest.mark.parametrize("perms", [ADMIN, MANAGE_REQUESTS | REQUEST, AUTO_APPROVE | REQUEST,
                                   AUTO_APPROVE_MOVIE | REQUEST])
def test_a_friend_who_could_approve_is_refused_before_sending(friend, perms):
    friend.seerr.add_user(FRIEND_SEERR, FRIEND_ID, perms)
    r = post(friend, "/media/title/movie/701/request")
    assert NOT_SET_UP in r.text and request_posts(friend.seerr) == []


def test_a_friend_request_is_pending_and_says_so(friend):
    friend.seerr.add_user(FRIEND_SEERR, FRIEND_ID)
    r = post(friend, "/media/title/movie/701/request")
    assert WAITING in r.text and "shows in Requests" not in r.text and "✓" not in r.text
    assert friend.seerr.requests[-1]["status"] == 1


def test_no_admin_side_effects_for_a_friend(friend, follows):
    """'All seasons' by a friend: Seerr's seasons "all", but no Sonarr follow and no quality safety net (Q19).
    WP-RQ2 (2026-10-22): the confirm step now offers the Quality chips and the pick rides the friend's own request."""
    friend.seerr.add_user(FRIEND_SEERR, FRIEND_ID)
    confirm = friend.get("/media/title/tv/100/request?step=confirm", headers=HX).text
    assert "Confirm request" in confirm and 'name="profile"' in confirm and "+ future" not in confirm
    post(friend, "/media/title/tv/100/request", "seasons=all&profile=5")
    post(friend, "/media/title/movie/701/request", "profile=5")
    assert [p[3] for p in request_posts(friend.seerr)] == [
        {"mediaType": "tv", "mediaId": 100, "seasons": "all", "profileId": 5},
        {"mediaType": "movie", "mediaId": 701, "profileId": 5}]
    assert follows == []


def test_the_households_alias_on_the_media_front_sends_the_bare_key(monkeypatch, tmp_path, follows):
    """B. (the household's outside Jellyfin user, `you`) on the media front: his request is the admin's as today - no
    X-Api-User, no import - and still no Sonarr follow or quality enforcement there (Q19 keys on the front)."""
    client, fake, seerr, _ = start(monkeypatch, tmp_path)
    with client as c:
        sign_in(c, fake, ALIAS_ID)
        r = post(c, "/media/title/tv/100/request", "seasons=all")
    assert r.status_code == 200 and "Requested" in r.text
    [sent] = request_posts(seerr)
    assert sent[4] == {"X-Api-Key": KEY}
    assert seerr.count("GET", "/api/v1/user") == 0 and seerr.count("POST", "/api/v1/user/import-from-jellyfin") == 0
    assert follows == []


def test_private_front_request_is_byte_identical(env):
    """B.'s request on private Joey: exactly the admin key, no X-Api-User (unchanged since 2026-10-05)."""
    client, fake = env()
    with client:
        client.post("/media/title/movie/603/request", headers=HX)
    url, payload, headers = fake.posts[0]
    assert headers == {"X-Api-Key": "k-SECRET-0123456789"} and payload == {"mediaType": "movie", "mediaId": 603}


# ---- decline is B.'s, in Seerr ----

def test_decline_is_hidden_and_a_declined_request_shows_declined(friend):
    seerr = friend.seerr
    seerr.add_user(FRIEND_SEERR, FRIEND_ID)
    post(friend, "/media/title/movie/701/request")
    rid = seerr.requests[-1]["id"]
    pages = [friend.get(p, headers=h).text for p, h in (
        ("/media/discover", {}), ("/media/title/movie/701", {}), ("/media/title/movie/701/request?panel=1", HX),
        ("/media/title/movie/701/request", HX), ("/media/title/movie/701/part/all?p=actions", {}))]
    for html in pages:
        assert not [u for m, u, a in links_of(html) if re.search(r"decline|approve|/media/requests", u, re.I)]
        assert not re.search(r">\s*(Decline|Approve|Remove)( request)?\s*<", html)
    assert seerr.count("POST", f"/api/v1/request/{rid}/decline") == 0
    media_guest_requests.clear()
    seerr.decline(rid)            # B., in Seerr's own UI
    block = friend.get("/media/title/movie/701/request", headers=HX).text
    part = friend.get("/media/title/movie/701/part/all?p=actions").text
    panel = friend.get("/media/title/movie/701/request?panel=1", headers=HX).text
    grid = friend.get("/media/discover").text
    assert "Declined" in block and "Declined" in part and "Declined" in panel
    assert re.search(r'id="chip-movie-701"[^>]*>Declined<', grid)
    assert [c for c in seerr.calls if c[1].endswith("/decline")] == []


def test_a_friends_pending_request_shows_on_the_title_page(friend):
    friend.seerr.add_user(FRIEND_SEERR, FRIEND_ID)
    post(friend, "/media/title/movie/701/request")
    assert WAITING in friend.get("/media/title/movie/701/part/all?p=actions").text


def test_another_friends_request_is_not_mine(monkeypatch, tmp_path):
    client, fake, seerr, _ = start(monkeypatch, tmp_path)
    seerr.add_user(FRIEND_SEERR, FRIEND_ID)
    seerr.add_user(8, OTHER_ID, name="Other Friend")
    with client as c:
        sign_in(c, fake, OTHER_ID)
        post(c, "/media/title/movie/701/request")
        media_guest_requests.clear()
        sign_in(c, fake, FRIEND_ID)
        panel = c.get("/media/title/movie/701/request?panel=1", headers=HX).text
        grid = c.get("/media/discover").text
    assert WAITING not in panel and "Already requested" in panel   # the media is requested, just not by them
    assert re.search(r'id="chip-movie-701"[^>]*>Requested<', grid)
    assert "Other Friend" not in panel + grid


# ---- routes: request GUEST, every admin path PRIVATE ----

def test_the_request_route_moved_from_reserved_to_guest():
    assert guest.RESERVED == ()
    assert ("GET", "/media/title/{kind}/{tmdb_id}/request") in guest.GUEST
    assert ("POST", "/media/title/{kind}/{tmdb_id}/request") in guest.GUEST
    assert guest.allows("GET", "/media/title/movie/603/request")
    assert guest.allows("POST", "/media/title/tv/100/request")


ADMIN_PATHS = [("GET", "/media/requests"), ("POST", "/media/requests/129/remove"),
               ("POST", "/media/follow/movie/701"), ("POST", "/media/follow/movie/701/unfollow"),
               ("GET", "/media/following"), ("POST", "/media/title/movie/701/search"),
               ("GET", "/media/title/movie/701/arr"), ("GET", "/media/title/movie/701/quality"),
               ("POST", "/media/title/movie/701/quality"), ("POST", "/media/title/movie/701/upgrade"),
               ("GET", "/media/arr/sweep"), ("POST", "/media/arr/sweep")]


@pytest.mark.parametrize("method, path", ADMIN_PATHS)
def test_admin_paths_stay_private(friend, method, path):
    assert not guest.allows(method, path)
    r = friend.request(method, path, headers=FORM, follow_redirects=False)
    assert r.status_code == 404
    assert [c for c in friend.seerr.calls if c[0] == "POST"] == []


# ---- the Discover screen (WP-M screen 10) ----

def test_discover_grid_has_the_three_chips_and_opens_the_panel(friend):
    friend.seerr.add_user(FRIEND_SEERR, FRIEND_ID)
    html = friend.get("/media/discover").text
    assert re.search(r"Discover · 5\b", html)                       # 701, 603, 702, 703, tv 100 - de-duplicated
    assert re.search(r'id="chip-movie-701"[^>]*>Request<', html)
    assert re.search(r'id="chip-movie-603"[^>]*>In library<', html)
    assert re.search(r'id="chip-movie-702"[^>]*>Requested<', html)
    assert re.search(r'id="chip-tv-100"[^>]*>Request<', html)
    assert 'hx-get="/media/title/movie/701/request?panel=1"' in html and 'href="/media/title/movie/701"' in html
    assert '<dialog id="req-dialog"' in html
    assert "/media/discover/service/" not in html                   # screen 10: the grid, no service tiles


def test_panel_request_says_waiting_and_updates_the_chip(friend):
    friend.seerr.add_user(FRIEND_SEERR, FRIEND_ID)
    panel = friend.get("/media/title/movie/701/request?panel=1", headers=HX).text
    assert "Harvest Moon Rising" in panel and "2024" in panel and "Overview of Harvest Moon Rising." in panel
    assert re.search(r'<button[^>]*data-first[^>]*>Request</button>', panel)
    assert 'hx-post="/media/title/movie/701/request"' in panel and 'name="panel" value="1"' in panel
    done = post(friend, "/media/title/movie/701/request", "panel=1").text
    assert WAITING in done and "data-close" in done
    assert re.search(r'<span id="chip-movie-701"[^>]*hx-swap-oob="true"[^>]*>Requested</span>', done)
    assert re.search(r'id="chip-movie-701"[^>]*>Requested<', friend.get("/media/discover").text)


def test_panel_for_a_show_requests_every_season(friend, follows):
    friend.seerr.add_user(FRIEND_SEERR, FRIEND_ID)
    panel = friend.get("/media/title/tv/100/request?panel=1", headers=HX).text
    assert 'name="seasons" value="all"' in panel
    post(friend, "/media/title/tv/100/request", "panel=1&seasons=all")
    assert request_posts(friend.seerr)[0][3] == {"mediaType": "tv", "mediaId": 100, "seasons": "all", "profileId": 4}
    assert follows == []


@pytest.mark.parametrize("tmdb, word", [(603, "Already in the library"), (702, "Already requested")])
def test_panel_for_a_title_that_needs_no_request_shows_its_status_and_done(friend, tmdb, word):
    panel = friend.get(f"/media/title/movie/{tmdb}/request?panel=1", headers=HX).text
    assert word in panel and "data-close" in panel and ">Request</button>" not in panel


def test_panel_norequests_reads_as_words(friend):
    friend.seerr.import_creates = False
    done = post(friend, "/media/title/movie/701/request", "panel=1").text
    assert NOT_SET_UP in done and "data-close" in done


def test_guest_search_results_are_grid_cards_with_chips(friend):
    html = friend.get("/media/discover/search?q=searchable", headers=HX).text
    assert re.search(r'id="chip-movie-704"[^>]*>Request<', html)
    assert re.search(r'id="chip-movie-603"[^>]*>In library<', html)
    assert "/media/watchlist/add" not in html or guest.allows("POST", "/media/watchlist/add")
    full = friend.get("/media/discover?q=searchable").text
    assert re.search(r'id="chip-movie-704"[^>]*>Request<', full)


def test_page_views_never_import(friend):
    """Only a request imports the friend; Discover, panels and title pages read, never write."""
    for path, h in (("/media/discover", {}), ("/media/title/movie/701/request?panel=1", HX),
                    ("/media/title/movie/701", {}), ("/media/title/movie/701/part/all?p=actions", {})):
        friend.get(path, headers=h)
    assert [c for c in friend.seerr.calls if c[0] == "POST"] == []


def test_tv_mode_discover_keeps_the_panel_and_back_restores_the_poster(friend):
    html = friend.get("/media/discover", headers={"User-Agent": TV_UA}).text
    assert '<dialog id="req-dialog"' in html and "data-req-open" in html
    tvjs = friend.get("/static/tv.js").text
    assert "_opener" in tvjs   # window.joeyTV.back() returns focus to the poster that opened the panel


# ---- the exposure crawl, with Seerr connected ----

def test_crawl_of_the_discover_and_request_pages(friend):
    from tests.hub.test_guest_exposure import problems_of
    friend.seerr.add_user(FRIEND_SEERR, FRIEND_ID)
    post(friend, "/media/title/movie/701/request")
    paths = ["/media/discover", "/media/discover?q=searchable", "/media/discover/search?q=searchable",
             "/media/title/movie/701", "/media/title/movie/702", "/media/title/movie/703", "/media/title/tv/100",
             "/media/title/movie/701/part/all?p=actions", "/media/title/movie/702/part/all?p=actions"]
    for kind, tmdb in (("movie", 701), ("movie", 603), ("movie", 702), ("movie", 703), ("tv", 100)):
        base = f"/media/title/{kind}/{tmdb}/request"
        paths += [base, base + "?panel=1", base + "?step=confirm"]
    problems, rendered = [], 0
    for ua in ({}, {"User-Agent": TV_UA}):
        for path in paths:
            r = friend.get(path, headers=ua)
            rendered += r.status_code == 200
            problems += problems_of(path, r.status_code, r.text)
            for word in ("SENTINEL_SEERR", "seerr.test", KEY, "Sample Admin", "example.test/avatar"):
                if word in r.text:
                    problems.append(f"{path}: {word}")
    assert not problems, "\n".join(problems[:40])
    assert rendered == 2 * len(paths)
