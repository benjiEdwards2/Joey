"""WP-RQ3 (2026-10-22) - Everyone's watchlist: every owner's list grouped by person (You, Georgina, friends by their
Jellyfin name from a cache, "Friend" while cold), status words from the snapshots, the owner gate (her and the media
front get 404), per-row Request = the normal confirm block, and Request all (filtered, deduplicated, capped, words).
Nothing touches the network: Seerr is tests/hub/test_media_discover.Fake, Jellyfin /Users a stub."""
import re

import pytest
from fastapi.testclient import TestClient

from hub import media_discover, media_quality, media_watchlist_everyone as everyone, media_watchlist_db as wl
from tests.hub.conftest import main_of
from tests.hub.test_media_discover import FAKE_KEY, FAKE_URL, FORM, HX, MOVIE, TV, Fake
from tests.hub.test_media_frame import env  # noqa: F401  (frame env fixture)
from tests.hub.test_media_library_pages import jelly

FRIEND = "jf:" + "ab" * 16
FRIEND2 = "jf:" + "cd" * 16
REQS = {"summary": "x", "requests": [
    {"tmdb_id": 101, "kind": "movie", "status_text": "Pending", "item_key": "tmdb:101"},
    {"tmdb_id": 102, "kind": "movie", "status_text": "Approved", "item_key": "tmdb:102"},
]}
PAGE = "/media/watchlist/everyone"
ALL = PAGE + "/request-all"


def put(tmdb, kind="movie", title="T", year=2020, owner="you"):
    wl.add(owner, {"tmdb_id": tmdb, "kind": kind, "title": title, "year": year, "poster": None})


@pytest.fixture(autouse=True)
def _fresh():
    everyone.clear()
    yield
    everyone.clear()


@pytest.fixture()
def app(env, monkeypatch):
    """(client, Seerr fake): the private front with Jellyfin library + jellyseerr requests snapshots and Seerr faked."""
    def build(reqs=None):
        main = env(jellyfin=jelly(), jellyseerr=reqs or REQS)
        monkeypatch.setenv("JELLYSEERR_URL", FAKE_URL)
        monkeypatch.setenv("JELLYSEERR_API_KEY", FAKE_KEY)
        media_discover.clear_cache()
        fake = Fake()
        monkeypatch.setattr(media_discover.requests, "get", fake.get)
        monkeypatch.setattr(media_discover.requests, "post", fake.post)
        return TestClient(main.app), fake
    return build


def page(c, path=PAGE):
    r = c.get(path)
    assert r.status_code == 200, r.status_code
    return main_of(r.text)


def groups(b):
    return re.findall(r'<h2 class="seclabel">([^<]+)</h2>', b)


def titles(b):
    return [t.strip() for t in re.findall(r'class="row-title">([^<(]+)', b)]


def seed():
    put(12, title="Bravo Film", year=2022)              # on disk (library tmdb:12)
    put(999, title="Nowhere Film")                      # not on server
    put(101, title="Req Film", owner="her")             # Pending -> Requested
    put(999, title="Nowhere Film", owner="her")         # the same title on two lists
    put(102, title="Proc Film", owner=FRIEND)           # Approved -> Processing
    put(500, kind="tv", title="Wanted Show", owner=FRIEND)
    put(600, title="Other Film", owner=FRIEND2)


# ---- the page ----

def test_groups_names_status_words_and_head(app, monkeypatch):
    c, _ = app()
    seed()
    calls = []
    monkeypatch.setattr(everyone, "fill_names", lambda: calls.append(1))
    with c:
        b = page(c)
    assert groups(b) == ["You · 2", "Georgina · 2", "Friend · 2", "Friend · 1"]   # names cold: "Friend"
    assert calls == [1]                                    # the /Users read runs after the response
    assert "7 titles · 6 not on the server" in b
    for word in ("On disk", "Requested", "Processing", "Not on server"):
        assert f">{word}</span>" in b
    assert b.count("Nowhere Film") == 2                    # once per person
    assert "Added " in b and "Film" in b and " · TV · " in b
    assert "Everyone&#39;s watchlist" in c.get(PAGE).text   # the page names itself


def test_friend_names_come_from_the_cache(app, monkeypatch, caplog):
    c, _ = app()
    seed()
    monkeypatch.setenv("JELLYFIN_URL", "http://jf.secret-host.invalid:8096")
    monkeypatch.setenv("JELLYFIN_API_KEY", "jf-SECRET")
    from hub import media_jellyfin
    users = [{"Id": "ABABABAB-ABAB-ABAB-ABAB-ABABABABABAB", "Name": "Zed Mate"},
             {"Id": "cd" * 16, "Name": "Amy Pal"}, {"Id": "junk", "Name": "Nobody"}]
    monkeypatch.setattr(media_jellyfin, "get", lambda base, headers, path: users)
    with c:
        page(c)                                            # cold: fills after the response
        b = page(c)
    assert groups(b) == ["You · 2", "Georgina · 2", "Amy Pal · 1", "Zed Mate · 2"]   # friends by name
    assert "Zed Mate" not in caplog.text and "Amy Pal" not in caplog.text


def test_names_read_failure_is_logged_by_type_and_not_retried_at_once(monkeypatch, caplog):
    monkeypatch.setenv("JELLYFIN_URL", "http://jf.secret-host.invalid:8096")
    monkeypatch.setenv("JELLYFIN_API_KEY", "jf-SECRET")
    from hub import media_jellyfin

    def boom(*a):
        raise ConnectionError("http://jf.secret-host.invalid:8096/Users")
    monkeypatch.setattr(media_jellyfin, "get", boom)
    assert everyone.names_due()
    everyone.fill_names()
    assert everyone.names() == {} and not everyone.names_due()
    assert "ConnectionError" in caplog.text and "secret-host" not in caplog.text


def test_filters_person_and_kind(app):
    c, _ = app()
    seed()
    with c:
        assert groups(page(c, f"{PAGE}?who={FRIEND}")) == ["Friend · 2"]
        assert groups(page(c, f"{PAGE}?who=her&kind=movie")) == ["Georgina · 2"]
        b = page(c, f"{PAGE}?kind=tv")
        assert groups(b) == ["Friend · 1"] and titles(b) == ["Wanted Show"]
        assert len(groups(page(c, f"{PAGE}?who=jf:bogus"))) == 4   # unknown -> All
        chips = page(c, f"{PAGE}?who=her")
    assert 'class="chip on" href="/media/watchlist/everyone?who=her" aria-current="true">Georgina' in chips
    assert f'href="/media/watchlist/everyone?who={FRIEND.replace(":", "%3A")}"' in chips


def test_empty_state(app):
    c, _ = app()
    with c:
        b = page(c)
    assert "Nothing on anyone's watchlist." in b and "Request all" not in b


# ---- the gate ----

def test_her_gets_404_and_no_link(app):
    c, fake = app()
    seed()
    with c:
        assert c.get(f"{PAGE}?owner_view=her").status_code == 404
        assert c.get("/media/movies/watchlist?owner_view=her").status_code == 200   # sets the her-view cookie
        assert c.get(PAGE).status_code == 404               # the cookie keeps the her view
        assert c.get(ALL, headers=HX).status_code == 404
        assert c.post(ALL, content="who=", headers={**HX, **FORM}).status_code == 404
        assert "/media/watchlist/everyone" not in c.get("/media/movies/watchlist").text
        assert "/media/watchlist/everyone" not in c.get("/media/requests").text
        c.cookies.clear()
        assert c.get(f"{PAGE}?owner_view=you").status_code == 200
    assert fake.posts == []


def test_links_from_the_watchlist_and_requests_pages(app):
    c, _ = app()
    with c:
        for path in ("/media/movies/watchlist", "/media/requests"):
            assert """<a href="/media/watchlist/everyone">Everyone's watchlist</a>""" in c.get(path).text, path


def test_routes_are_private_never_guest():
    from hub import guest
    for method, path in (("GET", PAGE), ("GET", ALL), ("POST", ALL)):
        assert not guest.allows(method, path)


def test_media_front_404_for_a_signed_in_friend(monkeypatch, tmp_path):
    from tests.hub.fake_jellyfin import FRIEND_ID
    from tests.hub.guest_pages import guest_client, sign_in
    client, fake = guest_client(monkeypatch, tmp_path, {"jellyfin": jelly()})
    with client as c:
        sign_in(c, fake, FRIEND_ID)
        missing = c.get("/no-such-page").text
        for method, path in (("GET", PAGE), ("GET", ALL), ("POST", ALL)):
            r = c.request(method, path, headers=FORM if method == "POST" else {}, follow_redirects=False)
            assert r.status_code == 404 and r.text == missing, (method, path)
        assert "/media/watchlist/everyone" not in c.get("/media/movies/watchlist").text


def test_media_front_handler_refuses_even_owner_you(monkeypatch):
    """Defence in depth: the handler itself refuses on the media front (where B. can sign in as "you")."""
    from hub import guest
    monkeypatch.setattr(guest, "is_media", lambda: True)
    assert everyone._allowed(object()) is False


# ---- per-row Request: the normal confirm block ----

def test_row_request_opens_the_normal_confirm_block(app, monkeypatch):
    c, fake = app()
    put(603, title="The Matrix", owner=FRIEND)
    put(100, kind="tv", title="Big Show", owner="her")
    monkeypatch.setattr(media_quality, "profiles", lambda kind: [
        {"id": 1, "name": "HD-1080p", "is_4k": False, "default": True},
        {"id": 2, "name": "Ultra-HD", "is_4k": True, "default": False}])
    with c:
        b = page(c)
        assert 'hx-get="/media/title/movie/603/request?step=confirm" hx-target="next .wlreq-slot"' in b
        assert 'href="/media/title/movie/603?step=confirm"' in b                # no-JS: the title page's confirm
        assert fake.gets == []                                                   # the page made no upstream call
        film = c.get("/media/title/movie/603/request?step=confirm", headers=HX).text
        show = c.get("/media/title/tv/100/request?step=confirm", headers=HX).text
        sent = c.post("/media/title/movie/603/request", content="profile=2", headers={**HX, **FORM}).text
    assert 'id="request-block"' in film and "Request The Matrix (1999)?" in film and 'name="profile" value="2"' in film
    assert 'name="seasons" value="4"' in show and "All seasons + future" in show
    assert "Requested in Ultra-HD ✓" in sent
    assert fake.posts[0][1] == {"mediaType": "movie", "mediaId": 603, "profileId": 2}
    assert "X-Api-User" not in fake.posts[0][2]                                  # as B.: the admin key alone


def test_only_not_on_server_rows_offer_request(app):
    c, _ = app()
    seed()
    with c:
        b = page(c)
    assert b.count("wlreq-open") == 4   # Nowhere Film x2, Wanted Show, Other Film (not On disk / Requested / Processing)


# ---- Request all ----

def test_request_all_panel_lists_deduplicated_titles_and_quality_rows(app, monkeypatch):
    c, fake = app()
    seed()
    monkeypatch.setattr(media_quality, "profiles", lambda kind: [
        {"id": 10 if kind == "movie" else 20, "name": "HD", "is_4k": False, "default": True},
        {"id": 11 if kind == "movie" else 21, "name": "4K", "is_4k": True, "default": False}])
    with c:
        b = page(c)
        assert "Request all · 3</a>" in b                                    # Nowhere (once), Wanted Show, Other Film
        assert f'hx-get="{ALL}?who=&amp;kind="' in b
        panel = c.get(ALL, headers=HX).text
        plain = c.get(ALL, follow_redirects=False)
        drawn = page(c, f"{PAGE}?all=1")
        assert "Request all · 1</a>" in page(c, f"{PAGE}?who=her")          # one person's group
    assert panel.count("<li>") == 3 and panel.count("Nowhere Film") == 1
    assert 'name="profile_movie" value="11"' in panel and 'name="profile_tv" value="21"' in panel
    assert "Quality · Films" in panel and "Quality · TV" in panel
    # JY-232 (B., 2026-10-27, "go s1"): shows go as Season 1 only, and the panel says so (was "Shows: all seasons")
    assert "Request 2 films · 1 show (Season 1)?" in panel and "all seasons" not in panel
    assert "<dialog" not in panel and 'action="/media/watchlist/everyone/request-all"' in panel
    assert plain.status_code == 303 and plain.headers["location"] == f"{PAGE}?all=1"
    assert "Request 2 films · 1 show (Season 1)?" in drawn   # JY-232: was "Request 3 titles?"
    assert fake.posts == []


def test_request_all_sends_each_once_with_the_picked_quality(app, monkeypatch):
    c, fake = app()
    seed()
    monkeypatch.setattr(media_quality, "profiles", lambda kind: [
        {"id": 10, "name": "HD", "is_4k": False, "default": True},
        {"id": 11, "name": "4K", "is_4k": True, "default": False}])
    nets = []
    monkeypatch.setattr(media_quality, "ensure", lambda kind, tmdb, pid, tvdb=None: nets.append((kind, tmdb, pid)))
    with c:
        r = c.post(ALL, content="who=&kind=&profile_movie=11&profile_tv=10", headers=FORM, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == f"{PAGE}?rqn=3"
        b = page(c, r.headers["location"])
    payloads = [p[1] for p in fake.posts]
    assert payloads == [{"mediaType": "movie", "mediaId": 999, "profileId": 11},
                        {"mediaType": "tv", "mediaId": 500, "seasons": [1], "profileId": 10},   # JY-232: Season 1
                        {"mediaType": "movie", "mediaId": 600, "profileId": 11}]
    assert all(p[0] == f"{FAKE_URL}/api/v1/request" and "X-Api-User" not in p[2] for p in fake.posts)
    assert nets == [("movie", 999, 11), ("movie", 600, 11)]              # the safety net, after the answer
    assert 'class="metaline st-good" role="status">Requested 3</p>' in b
    assert "Request all" not in b and b.count(">Requested</span>") == 5     # sent titles read Requested


def test_request_all_follows_the_filter_and_skips_requested(app):
    c, fake = app()
    seed()
    with c:
        r = c.post(ALL, content=f"who={FRIEND}&kind=", headers=FORM, follow_redirects=False)
    assert [p[1]["mediaId"] for p in fake.posts] == [500]                # 102 is Processing: skipped
    assert r.headers["location"] == f"{PAGE}?who={FRIEND.replace(':', '%3A')}&rqn=1"


def test_request_all_caps_and_words(app, monkeypatch):
    c, fake = app()
    monkeypatch.setattr(everyone, "CAP", 3)
    for i in range(5):
        put(700 + i, title=f"Film {i}")
    calls = iter([201, 409, 201])
    real_post = fake.post

    def post(url, json=None, headers=None, timeout=None, **kw):
        fake.post_status = next(calls)
        return real_post(url, json=json, headers=headers, timeout=timeout)
    monkeypatch.setattr(media_discover.requests, "post", post)
    with c:
        r = c.post(ALL, content="who=&kind=", headers=FORM, follow_redirects=False)
        loc = r.headers["location"]
        b = page(c, loc)
    assert len(fake.posts) == 3 and loc == f"{PAGE}?rqn=2&rqf=exists-1&rql=2"
    assert "Requested 2 · 1 failed: Already requested · 2 left · Request all again" in b and "st-warn" in b


def test_request_all_network_failure_words_and_htmx_boosted(app):
    c, fake = app()
    put(999, title="Nowhere Film")
    fake.fail = True
    with c:
        r = c.post(ALL, content="who=&kind=", headers={**FORM, **HX})
        b = main_of(r.text)
    assert r.status_code == 200 and "1 failed: Couldn&#39;t send the request" in b
    assert FAKE_KEY not in r.text and "secret-host" not in b


def test_request_all_with_nothing_to_send_and_bad_profile(app, monkeypatch):
    c, fake = app()
    put(12, title="Bravo Film")                    # on disk
    with c:
        r = c.post(ALL, content="who=&kind=", headers=FORM, follow_redirects=False)
        assert "Nothing to request" in page(c, r.headers["location"])
        put(999, title="Nowhere Film")
        monkeypatch.setattr(media_quality, "profiles", lambda kind: [
            {"id": 10, "name": "HD", "is_4k": False, "default": True}, {"id": 11, "name": "4K", "is_4k": True,
                                                                         "default": False}])
        assert c.post(ALL, content="profile_movie=99", headers=FORM).status_code == 422
    assert fake.posts == []


def test_request_all_refuses_a_foreign_origin(app):
    c, fake = app()
    put(999)
    with c:
        assert c.post(ALL, content="who=", headers={**FORM, "Origin": "https://evil.example"}).status_code == 403
    assert fake.posts == []


def test_request_all_reuses_the_single_send(app, monkeypatch):
    """The one request function: Request all calls media_discover._send (as B.: user None), nothing of its own."""
    c, _ = app()
    put(999)
    put(500, kind="tv")
    seen = []
    monkeypatch.setattr(media_discover, "_send", lambda kind, tmdb, seasons, profile_id=None, user=None:
                        seen.append((kind, tmdb, seasons, profile_id, user)))
    with c:
        c.post(ALL, content="who=&kind=", headers=FORM)
    assert sorted(seen) == [("movie", 999, [], None, None), ("tv", 500, [1], None, None)]   # JY-232: Season 1 only


def test_flash_words():
    w = lambda **q: everyone.flash_words(q)
    assert w() == (None, None)
    assert w(rqn="7", rqf="network-1") == (None, "Requested 7 · 1 failed: Couldn't send the request")
    assert w(rqn="0") == ("Nothing to request", None)
    assert w(rqn="2", rqf="bogus-3.declined-x") == ("Requested 2", None)


# ---- JY-232 (B., 2026-10-27: "JY-232: go s1"): Request all sends shows as Season 1 only ----

def test_confirm_says_plainly_what_will_be_sent(app):
    c, _ = app()
    put(901, title="Film A")
    put(902, title="Film B", owner="her")
    put(501, kind="tv", title="Show A", owner=FRIEND)
    put(502, kind="tv", title="Show B", owner=FRIEND2)
    with c:
        mixed = c.get(ALL, headers=HX).text
        films = c.get(f"{ALL}?kind=movie", headers=HX).text
        shows = c.get(f"{ALL}?kind=tv", headers=HX).text
        one = c.get(f"{ALL}?who={FRIEND}", headers=HX).text
    assert "Request 2 films · 2 shows (Season 1)?" in mixed
    assert "Request 2 films?" in films and "Season 1" not in films
    assert "Request 2 shows (Season 1)?" in shows
    assert "Request 1 show (Season 1)?" in one
    assert mixed.count("TV · Season 1") == 2                    # each show in the list says it too
    assert "all seasons" not in mixed + films + shows + one


def test_request_all_shows_season_1_capped_deduplicated_and_skipping(app):
    """25 new shows (one on two lists), one requested, one on disk: 20 sent as Season 1, each once, the rest wait."""
    reqs = {"summary": "x", "requests": [{"tmdb_id": 799, "kind": "tv", "status_text": "Pending", "item_key": "tmdb:799"}]}
    c, fake = app(reqs)
    for i in range(25):
        put(800 + i, kind="tv", title=f"Show {i}", owner=FRIEND)
    put(800, kind="tv", title="Show 0", owner=FRIEND2)          # the same show on a second list
    put(799, kind="tv", title="Asked Show", owner="her")        # already requested
    put(21, kind="tv", title="Echo Show")                       # on the server (library tmdb:21)
    with c:
        r = c.post(ALL, content="who=&kind=", headers=FORM, follow_redirects=False)
    assert everyone.CAP == 20
    ids = [p[1]["mediaId"] for p in fake.posts]
    assert len(ids) == 20 and len(set(ids)) == 20 and 799 not in ids and 21 not in ids
    assert all(p[1]["seasons"] == [1] for p in fake.posts)
    assert r.headers["location"] == f"{PAGE}?rqn=20&rql=5"


# ---- JY-232 privacy pins ----

def test_a_friend_sees_only_their_own_watchlist_on_the_media_front(monkeypatch, tmp_path):
    """Friends never see each other's lists (or the household's): the friend's own Watchlist page holds their rows only."""
    from tests.hub.fake_jellyfin import FRIEND_ID
    from tests.hub.guest_pages import guest_client, sign_in
    client, fake = guest_client(monkeypatch, tmp_path, {"jellyfin": jelly()})
    put(901, title="Mine Film", owner="jf:" + FRIEND_ID)
    put(902, title="Other Friend Film", owner=FRIEND)
    put(903, title="Household Film")
    put(904, title="Her Film", owner="her")
    with client as c:
        sign_in(c, fake, FRIEND_ID)
        b = c.get("/media/movies/watchlist").text
        assert c.get(PAGE).status_code == 404
    assert "Mine Film" in b
    for other in ("Other Friend Film", "Household Film", "Her Film", "Everyone&#39;s watchlist"):
        assert other not in b, other


def test_page_render_makes_no_live_calls(app, monkeypatch):
    """With the names warm the page and its Request all panel make no upstream call at all; with them cold the one
    Jellyfin /Users read runs after the handler has built the response (a BackgroundTask), never during it."""
    import requests

    from hub import media_pages
    c, fake = app()
    seed()
    calls = []

    def no_network(*a, **kw):
        calls.append(a[:2])
        raise AssertionError("live call on render")
    monkeypatch.setattr(requests, "get", no_network)
    monkeypatch.setattr(requests, "post", no_network)
    monkeypatch.setattr(requests.Session, "request", no_network)
    with everyone._lock:
        everyone._names.update(at=everyone._clock(), map={"ab" * 16: "Zed Mate"}, failed_at=None)
    with c:
        assert "Zed Mate · 2" in page(c)
    assert calls == [] and fake.gets == [] and fake.posts == []

    everyone.clear()                                             # cold: the read is due
    order = []
    real = media_pages._detail_page
    monkeypatch.setattr(media_pages, "_detail_page", lambda *a, **kw: (r := real(*a, **kw), order.append("built"))[0])
    monkeypatch.setattr(everyone, "fill_names", lambda: order.append("users read"))
    with c:
        page(c)
    assert order == ["built", "users read"] and calls == []


# ---- JY-232 review fixes (2026-10-27) ----

def test_two_concurrent_request_alls_send_each_title_once(app, monkeypatch):
    """A double-click: the second POST arrives while the first is still sending. It answers "Already sending…" and
    sends nothing, so Seerr sees each title once."""
    import threading
    c, fake = app()
    put(999, title="Nowhere Film")
    put(500, kind="tv", title="Wanted Show", owner=FRIEND)
    first_in, second_done = threading.Event(), threading.Event()
    real_post = fake.post

    def slow_post(url, json=None, headers=None, timeout=None, **kw):
        first_in.set()
        assert second_done.wait(10), "the second POST never answered"
        return real_post(url, json=json, headers=headers, timeout=timeout)
    monkeypatch.setattr(media_discover.requests, "post", slow_post)
    answers = {}
    with c:
        first = threading.Thread(target=lambda: answers.update(
            first=c.post(ALL, content="who=&kind=", headers=FORM, follow_redirects=False)))
        first.start()
        assert first_in.wait(10)
        second = c.post(ALL, content="who=&kind=", headers=FORM, follow_redirects=False)
        second_done.set()
        first.join(10)
        busy = page(c, second.headers["location"])
    assert second.status_code == 303 and second.headers["location"] == f"{PAGE}?rqb=1"
    assert 'class="metaline st-warn" role="status">Already sending…</p>' in busy
    assert answers["first"].headers["location"] == f"{PAGE}?rqn=2"
    assert sorted(p[1]["mediaId"] for p in fake.posts) == [500, 999]      # each once
    assert not everyone._sending.locked()                                  # released after the send


def test_a_filter_that_matches_nothing_says_so(app):
    c, _ = app()
    put(999, title="Nowhere Film")
    with c:
        b = page(c, f"{PAGE}?kind=tv")
    assert "Nothing matches this filter." in b and "Nothing on anyone" not in b
