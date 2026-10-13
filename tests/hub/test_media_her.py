"""Georgina's view (2026-10-05): owner_view=her reads the snapshot's `her` block (up next +
history) and her own ratings/diary rows (owner 'her'); B.'s data never leaks into it.
Placement is asserted inside <main>."""
import importlib
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from hub import media_db
from tests.hub.helpers import ARR, JELLY, make_area, SEERR_REQUESTS as SEERR, shelf_area, write_envelope, write_registry

NOW = datetime.now(timezone.utc)
HX = {"HX-Request": "true"}
HER_RECENT = [
    {"title": "Garden Lane · S01E01 · First Frost", "item_key": "jf:her-1", "kind": "episode",
     "poster": "jf:her-1", "when": "yesterday", "watched_at": (NOW - timedelta(days=1)).isoformat()},
    {"title": "Paper Lanterns", "item_key": "tmdb:202", "kind": "movie", "poster": None,
     "when": "2 days ago", "watched_at": (NOW - timedelta(days=2)).isoformat()},
]
HER = {"user": "georgina",
       "up_next": [{"title": "Cold Harbour", "remaining_text": "60 min left", "poster": None,
                    "item_key": "tmdb:201", "kind": "movie", "jf_id": "her-id"}],
       "history": {"recent": HER_RECENT, "week_count": 2, "month_count": 2, "hours_total": 2.4,
                   "hours_month": 2.4, "most_played_shows": [], "most_played_movies": [],
                   "on_this_day": []}}
B_ONLY = ("Dust and Daylight", "Harbour Lights", "Rated One")


def shared_area():
    area = shelf_area()
    for t in area["tiles"]:
        if t.get("detail") in ("/media/history", "/media/diary"):
            t["owner"] = "shared"
    return area


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("AREAS_PATH", str(write_registry(tmp_path, shared_area(), make_area("beta"))))
    monkeypatch.setenv("MEDIA_DB_PATH", str(tmp_path / "media.db"))
    snaps = tmp_path / "snaps"
    monkeypatch.setenv("SNAPSHOT_DIR", str(snaps))

    def build(her=HER, now_playing=None):
        data = {**JELLY, "her": her, "server_id": "srv"}
        if now_playing is not None:
            data["now_playing"] = now_playing
        write_envelope(snaps, "jellyfin", age_minutes=1, data=data)
        write_envelope(snaps, "arr", age_minutes=1, data=ARR)
        write_envelope(snaps, "jellyseerr", age_minutes=1, data=SEERR)
        import hub.main
        importlib.reload(hub.main)
        return TestClient(hub.main.app)
    return build


def main_html(html):
    return html.split("<main", 1)[1]


def test_her_view_shelves_show_hers_not_b(env):
    with env(now_playing=[]) as client:
        html = main_html(client.get("/a/alpha?owner_view=her").text)
    assert "Cold Harbour" in html and "Up next" in html
    assert "Continue watching" in html and "Recently watched" not in html   # media-ux2: no Recently watched on home
    for title in B_ONLY:
        assert title not in html, title


def test_you_and_both_views_still_show_b(env):
    with env() as client:
        for view in ("you", "both"):
            html = main_html(client.get(f"/a/alpha?owner_view={view}").text)
            assert "Dust and Daylight" in html, view   # media-ux2: Harbour Lights was a Recently watched row
            assert "Cold Harbour" not in html and "First Frost" not in html, view


def test_her_view_with_null_her_shows_quiet_words(env):
    with env(her=None, now_playing=[]) as client:
        html = main_html(client.get("/a/alpha?owner_view=her").text)
    assert html.count("Her Jellyfin account isn&#39;t set up yet") == 1   # media-ux2: Continue watching only
    assert "Nothing playing" in html
    for title in B_ONLY:
        assert title not in html, title


def test_her_view_ratings_come_from_her_rows_only(env):
    media_db.set_rating("tmdb:202", 9, "movie", "Paper Lanterns", owner="her")
    media_db.set_rating("m2", 4, "movie", "Rated One")  # B.'s
    with env() as client:
        # media-ux2: Media home lost Recently watched; History's Recently watched carries the scores now
        her = main_html(client.get("/media/history?owner_view=her").text)
        you = main_html(client.get("/media/history?owner_view=you").text)
    assert "Your rating: 9 out of 10" in her and "Your rating: 4 out of 10" not in her
    assert "Your rating: 4 out of 10" in you and "Your rating: 9 out of 10" not in you


def test_playing_page_in_her_view_uses_her_up_next_but_shared_sessions(env):
    with env() as client:
        html = main_html(client.get("/media/playing?owner_view=her").text)
    assert "Cold Harbour" in html and "Dust and Daylight" not in html
    assert "Playing Now Title" in html  # sessions are server-wide


def test_history_page_in_her_view_and_to_rate(env):
    with env() as client:
        html = main_html(client.get("/media/history?owner_view=her").text)
        b = main_html(client.get("/media/history?owner_view=you").text)
    assert "Paper Lanterns" in html and "Harbour Lights" not in html
    assert "Harbour Lights" in b and "Paper Lanterns" not in b


def test_rating_post_in_her_view_stores_owner_her_and_never_collides(env):
    media_db.set_rating("tmdb:202", 7, "movie", "Paper Lanterns")  # B. rated the same key
    body = "item_key=tmdb:202&kind=movie&title=Paper+Lanterns&score=3"
    with env() as client:
        client.get("/media/history?owner_view=her")  # sets the owner_view cookie, as the browser would
        assert client.post("/media/rate", content=body, headers=HX).status_code == 200
        assert media_db.get_rating("tmdb:202", "her")["score"] == 3
        assert media_db.get_rating("tmdb:202")["score"] == 7
        client.delete("/media/rate/tmdb:202", headers=HX)  # her cookie -> removes hers only
    assert media_db.get_rating("tmdb:202", "her") is None and media_db.get_rating("tmdb:202")["score"] == 7


def test_rating_post_without_her_view_is_b(env):
    with env() as client:
        client.post("/media/rate", content="item_key=tmdb:202&kind=movie&title=X&score=5", headers=HX)
    assert media_db.get_rating("tmdb:202")["score"] == 5 and media_db.get_rating("tmdb:202", "her") is None


def test_diary_in_her_view_syncs_her_history_and_logs_as_her(env):
    pick = "%7B%22item_key%22%3A%22tmdb%3A5%22%2C%22kind%22%3A%22movie%22%2C%22title%22%3A%22Manual%22%7D"
    with env() as client:
        html = main_html(client.get("/media/diary?owner_view=her").text)
        assert "Paper Lanterns" in html and "Harbour Lights" not in html
        assert client.post("/media/log", headers=HX, content="pick=" + pick).status_code == 200
    assert {r["title"] for r in media_db.list_diary(owner="her")} == {"Garden Lane", "Paper Lanterns", "Manual"}
    assert media_db.list_diary() == []  # B.'s diary untouched (his page was never opened)


def test_hub_card_hero_in_her_view_uses_her_up_next(env):
    with env(now_playing=[]) as client:
        her = main_html(client.get("/?owner_view=her").text)
        you = main_html(client.get("/?owner_view=you").text)
    assert "Cold Harbour" in her and "Dust and Daylight" not in her
    assert "Dust and Daylight" in you and "Cold Harbour" not in you


def test_real_registry_history_and_diary_are_shared():
    from hub.registry import load_registry
    media = next(a for a in load_registry("config/areas.yaml").areas if a.id == "media")
    owners = {t.id: t.owner.value for t in media.tiles}
    assert owners["history"] == owners["diary"] == "shared" and "years" not in owners   # decision 1


def test_rating_level_setting_is_per_owner(env):
    with env() as client:
        client.get("/media/history?owner_view=her")  # her cookie
        assert client.post("/media/settings/rating_level", data={"value": "episode"},
                           follow_redirects=False).status_code == 303
    assert media_db.rating_level("her") == "episode" and media_db.rating_level("you") == "show"


def test_signed_in_her_never_sees_diary_scope_and_her_post_is_refused(env, monkeypatch):
    """Diary scope (2026-10-13): only owner 'you' may show everyone's diary. Signed-in her: no toggle, POST 403,
    nothing stored, and her page stays hers even with B.'s scope set to everyone."""
    from hub.identity import IDENTITY_HEADER
    monkeypatch.setenv("OWNER_EMAIL_YOU", "you@example.invalid")
    as_her = {IDENTITY_HEADER: "her@example.invalid"}
    media_db.add_manual_watch("tmdb:9", "movie", "B Only Film", watched_on=NOW.date().isoformat(), owner="you")
    media_db.set_setting("you", "diary_scope", "everyone")
    with env() as client:
        html = main_html(client.get("/media/diary", headers=as_her).text)
        assert "/media/settings/diary_scope" not in html and ">Everyone<" not in html
        assert "Paper Lanterns" in html and "B Only Film" not in html
        for value in ("everyone", "mine"):
            assert client.post("/media/settings/diary_scope", data={"value": value}, headers=as_her,
                               follow_redirects=False).status_code == 403
    assert media_db.get_setting("her", "diary_scope") is None and media_db.diary_scope("her") == "mine"
    assert media_db.diary_scope("you") == "everyone"   # her refused POST changed nothing of his either


def test_her_view_not_signed_in_is_not_eligible_for_diary_scope(env):
    with env() as client:
        html = main_html(client.get("/media/diary?owner_view=her").text)
        assert "/media/settings/diary_scope" not in html
        assert client.post("/media/settings/diary_scope", data={"value": "everyone"},
                           follow_redirects=False).status_code == 403   # her cookie
    assert media_db.get_setting("her", "diary_scope") is None
