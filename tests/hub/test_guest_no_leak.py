"""Joey TV WP-B2 step 6 (2026-10-21): the sentinel no-leak sweep. B.'s snapshot rows (`SENTINEL_YOU_*`), Georgina's
block (`SENTINEL_HER_*`) and the household's media.db rows (`SENTINEL_*_DB`) are seeded; then EVERY GUEST GET route
(imported from hub.guest, path parameters filled by tests/deploy/route_sweep.py's fixed table) is requested as a
signed-in friend four ways - plain, `?owner_view=both`, cookie `owner_view=both`, and B.'s spoofed Access header.
Every answer is 200 or 404 and no body carries `SENTINEL_`. A control run as B.'s own outside Jellyfin user (the alias,
`you` - Q16) proves the sweep can see data: `SENTINEL_YOU_DB` shows, `SENTINEL_HER_*` never does, and neither does B.'s
admin snapshot (P3)."""
import pytest
from fastapi.testclient import TestClient

from hub import guest, media_db
from hub.identity import IDENTITY_HEADER
from tests.deploy import route_sweep
from tests.hub.fake_jellyfin import ALIAS_ID, FRIEND_ID, HTTPS, FakeJellyfin, media_env, reload_app, session_cookie
from tests.hub.helpers import write_envelope

JELLY = {"summary": "SENTINEL_YOU_SUMMARY 2 playing now", "server_id": "srv-1",
         "up_next": [{"title": "SENTINEL_YOU_UPNEXT", "jf_id": "u1", "item_key": "tmdb:11", "kind": "movie",
                      "remaining_text": "31 min left", "poster": "jf:u1"}],
         "now_playing": [{"title": "SENTINEL_YOU_NOW", "user": "SENTINEL_YOU_USER", "jf_id": "n1"}],
         "secondary": "SENTINEL_YOU_SECONDARY",
         "history": {"recent": [{"title": "SENTINEL_YOU_HIST", "jf_id": "h1", "kind": "movie", "item_key": "tmdb:12",
                                 "when": "today", "watched_at": "2026-10-20T10:00:00Z"}],
                     "most_played_movies": [{"title": "SENTINEL_YOU_MOSTPLAYED"}], "on_this_day": [],
                     "month_count": 1, "week_count": 1, "hours_month": 1, "hours_total": 1},
         "her": {"user": "SENTINEL_HER_USER",
                 "up_next": [{"title": "SENTINEL_HER_UPNEXT", "jf_id": "u2", "item_key": "tmdb:21", "kind": "movie"}],
                 "history": {"recent": [{"title": "SENTINEL_HER_HIST", "jf_id": "h2", "item_key": "tmdb:22",
                                         "kind": "movie", "when": "today"}]},
                 "movies": [], "shows": []},
         "latest": [{"title": "Shared New One", "jf_id": "l1", "item_key": "tmdb:13", "type": "Movie",
                     "poster": "jf:l1", "added_at": "2026-10-19T10:00:00Z"}],
         "library": {"movies": 1, "episodes": 0},
         "movies": [{"title": "Library Film", "jf_id": "mov1", "item_key": "tmdb:603", "year": 1999,
                     "played": True, "last_played_at": "SENTINEL_YOU_PLAYED_AT", "poster": "jf:mov1"}],
         "shows": []}
SEERR = {"summary": "1 request", "counts": {},
         "requests": [{"id": 13, "item_key": "tmdb:1001", "kind": "movie", "title": "Midnight Harbour", "tmdb_id": 1001,
                       "requested_by": "SENTINEL_YOU_REQUESTER", "status_text": "Pending", "when": "1 hour ago",
                       "year": 2025, "poster": "tmdb:/x.jpg"}]}
QBIT = {"summary": "SENTINEL_YOU_QBIT", "active": [{"name": "SENTINEL_YOU_TORRENT"}]}


class Args:
    jf_id, ref, area_id = "mov1", "x", "media"


def guest_gets() -> list[str]:
    # WP-B3: plus the Overview in TV mode, its Set-up-card dismissal, the 404 page and /signin
    home = guest.home_path()
    return list(dict.fromkeys(route_sweep.fill(t, Args) for m, t in guest.GUEST if m == "GET")) + [
        home, home + "?tv=1", home + "?setup=done", "/no-such-page", "/signin"]


@pytest.fixture()
def client(monkeypatch, tmp_path):
    media_env(monkeypatch)
    monkeypatch.setenv("OWNER_EMAIL_YOU", "you@example.com")
    snaps = tmp_path / "snaps"
    monkeypatch.setenv("SNAPSHOT_DIR", str(snaps))
    write_envelope(snaps, "jellyfin", age_minutes=1, data=JELLY)
    write_envelope(snaps, "jellyseerr", age_minutes=1, data=SEERR)
    write_envelope(snaps, "qbittorrent", age_minutes=1, data=QBIT)
    for owner, word in (("you", "YOU"), ("her", "HER")):
        media_db.set_rating("tmdb:603", 7, "movie", f"SENTINEL_{word}_RATED_DB", owner=owner)
        media_db.add_manual_watch("tmdb:604", "movie", f"SENTINEL_{word}_DIARY_DB", watched_on="2026-10-20",
                                  owner=owner)
    fake = FakeJellyfin().install(monkeypatch)
    with TestClient(reload_app(), base_url=HTTPS) as c:
        c.fake = fake
        yield c


def sign_in(c, uid):
    c.cookies.clear()
    for k, v in session_cookie(c.fake.token_for(uid)).items():
        c.cookies.set(k, v)


def sweep(c, path):
    base = dict(c.cookies)
    out = []
    for query, extra_cookie, headers in (("", {}, {}), ("?owner_view=both", {}, {}),
                                         ("", {"owner_view": "both"}, {}),
                                         ("", {}, {IDENTITY_HEADER: "you@example.com"})):
        c.cookies.clear()
        for k, v in {**base, **extra_cookie}.items():
            c.cookies.set(k, v)
        sep = "&" if "?" in path and query else ""
        out.append(c.get(path + (query.replace("?", sep) if sep else query), headers=headers, follow_redirects=False))
    c.cookies.clear()
    for k, v in base.items():
        c.cookies.set(k, v)
    return out


def test_no_guest_route_leaks_household_data_to_a_friend(client):
    sign_in(client, FRIEND_ID)
    seen = 0
    for path in guest_gets():
        for r in sweep(client, path):
            assert r.status_code in (200, 404), (path, r.status_code)
            assert "SENTINEL_" not in r.text, (path, r.text[r.text.find("SENTINEL_") - 80:][:200])
            seen += r.status_code == 200
    assert seen > 20   # the sweep really rendered pages


def test_the_control_run_as_bs_outside_user_sees_only_his_own_rows(client):
    sign_in(client, ALIAS_ID)
    bodies = ""
    for path in guest_gets():
        for r in sweep(client, path):
            assert r.status_code in (200, 404), (path, r.status_code)
            bodies += r.text
    assert "SENTINEL_YOU_" in bodies and "_DB" in bodies          # the sweep can see data
    assert "SENTINEL_HER_" not in bodies
    for word in ("SUMMARY", "UPNEXT", "NOW", "HIST", "USER", "SECONDARY", "MOSTPLAYED", "PLAYED_AT", "REQUESTER", "QBIT",
                 "TORRENT"):
        assert f"SENTINEL_YOU_{word}" not in bodies, word   # the admin's snapshot never reaches the media front
