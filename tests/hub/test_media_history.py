"""Media Phase 4a — the /media/history page, rendered from the history block of the jellyfin snapshot (the area
"Recently watched" strip was removed 2026-10-09, decision 2). Placement is asserted inside <main>.

JY-298 (B., 2026-11-02; tests rewritten 2026-11-03): the To rate page is gone. /media/history redirects to History
(the diary), which carries the To rate inbox (count, Rate TV by, folded rows with Skip) and "Clear all rating
requests" (POST /media/rate/clear: skips every open request of the viewer's own, rates nothing). The old page's
tests (numbers line, Recently watched order, you chip, its empty words and 120 px posters) went with the page.
"""
import importlib
import json
import re
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from tests.hub.helpers import make_area, make_tile, write_envelope
from tests.hub.conftest import app_with, main_of  # noqa: F401  (shared helper; other test modules import it from here)

SAMPLE = json.loads((Path(__file__).resolve().parents[2] / "config" / "sample_snapshots" / "jellyfin.json")
                    .read_text(encoding="utf-8"))["data"]


@pytest.fixture()
def app_factory(tmp_path, monkeypatch):
    area = make_area("alpha", "play-t", snapshot="jellyfin", stale_after_minutes=10,
                     detail="/media/playing")
    area["tiles"].append(make_tile("hist-t", snapshot="jellyfin", stale_after_minutes=10,
                                   detail="/media/history", owner="you"))
    return app_with(tmp_path, monkeypatch, area), tmp_path


def test_404_when_no_tile_has_the_history_route(tmp_path, monkeypatch):
    # a tile reading jellyfin is not enough — the history page needs the history tile
    path = tmp_path / "areas.yaml"
    path.write_text(yaml.safe_dump({"areas": [make_area("alpha", snapshot="jellyfin",
                                                         detail="/media/playing")]}), encoding="utf-8")
    monkeypatch.setenv("AREAS_PATH", str(path))
    monkeypatch.setenv("SNAPSHOT_DIR", str(tmp_path / "snaps"))
    import hub.main
    importlib.reload(hub.main)
    with TestClient(hub.main.app) as client:
        resp = client.get("/media/history")
    assert resp.status_code == 404 and "No page here" in resp.text


# ---- JY-298: To rate folded into History ----
from hub import media_db, media_nav  # noqa: E402
from tests.hub.test_media_rate import TV, env, jelly_data  # noqa: E402,F401

INBOX = ">To rate</h2>"


def to_rate(html):
    body = main_of(html)
    return body.split(INBOX, 1)[1].split("</section>", 1)[0] if INBOX in body else None


def clear(client, **extra):
    return client.post("/media/rate/clear", data={"back": "/media/diary"}, follow_redirects=False, **extra)


def test_activity_tabs_have_no_to_rate_anywhere():
    for table in (media_nav.SECTIONS, [media_nav.GUEST_DIARY]):
        assert not [h for s in table for label, h in s["tabs"] if h == "/media/history" or
                    (label == "To rate" and s["id"] in ("server", "diary"))]


def test_old_history_link_redirects_to_history_keeping_the_query(env):
    build, _ = env
    with build() as client:
        r = client.get("/media/history", follow_redirects=False)
        assert r.status_code == 307 and r.headers["location"] == "/media/diary"
        r = client.get("/media/history?owner_view=her", follow_redirects=False)
        assert r.headers["location"] == "/media/diary?owner_view=her"
        assert "<title>History · Joey</title>" in client.get("/media/history").text


def test_history_carries_the_inbox_count_and_the_clear_button(env):
    build, _ = env
    with build() as client:
        html = client.get("/media/diary").text
    inbox = to_rate(html)
    assert "3 waiting for your rating" in inbox and inbox.count('class="ratepick"') == 3   # Heat, Quiet Show, Already Rated
    assert 'action="/media/rate/clear"' in inbox and "Clear all rating requests (3)" in inbox and "Yes, clear 3" in inbox
    assert 'aria-label="Rate TV by"' in inbox and ">Skip" in inbox


def test_clear_skips_every_open_request_rates_nothing_and_zeroes_the_counts(env):
    build, db_file = env
    with build() as client:
        r = clear(client)
        assert r.status_code == 303 and r.headers["location"] == "/media/diary?skip=cleared"
        html = client.get(r.headers["location"]).text
        assert to_rate(html) is None and "Rating requests cleared" in html
        assert 'class="waitcount"' not in html.split("<main", 1)[0].split('class="sectabs sub"', 1)[-1].split("</nav>", 1)[0]
        assert '<section class="sec skipped">' in html and ">Unskip</button>" in html
        hub_html = client.get("/a/alpha").text
    assert sorted(s["key"] for s in media_db.skips("you")) == ["jf:s1", "tmdb:1", "tmdb:4"]
    assert all(not s["forever"] for s in media_db.skips("you"))
    assert media_db.get_ratings(["jf:s1", "tmdb:1", "tmdb:4"]) == {}            # nothing got a score
    assert 'class="waitcount"' not in hub_html


def test_clear_is_owner_scoped_and_unskip_restores_one(env):
    build, _ = env
    with build() as client:
        client.get("/media/diary?owner_view=her")   # her view cookie
        client.get("/media/diary?owner_view=you")
        assert clear(client).status_code == 303
        assert media_db.skips("her") == []          # her inbox untouched
        r = client.post("/media/rate/unskip", data={"key": "tmdb:1", "back": "/media/diary"}, follow_redirects=False)
        assert r.headers["location"] == "/media/diary?skip=unskip"
        inbox = to_rate(client.get("/media/diary").text)
    assert "Heat" in inbox and "Quiet Show" not in inbox and "1 waiting" in inbox and "Already Rated" not in inbox


def test_clear_follows_the_rating_level(env):
    build, _ = env
    media_db.set_setting("you", "rating_level", "episode")
    with build(jelly_data(TV)) as client:
        assert to_rate(client.get("/media/diary").text).count('class="ratepick"') == 4
        clear(client)
        assert to_rate(client.get("/media/diary").text) is None
    assert sorted(s["key"] for s in media_db.skips("you")) == ["jf:cfae7", "jf:cfae8", "jf:cfae9", "tmdb:1"]


def test_clear_refuses_a_foreign_origin_and_is_a_no_op_with_nothing_waiting(env):
    build, _ = env
    with build(jelly_data([])) as client:
        r = client.post("/media/rate/clear", data={}, headers={"Origin": "https://evil.example"})
        assert r.status_code == 403
        assert clear(client).status_code == 303
    assert media_db.skips("you") == []


def test_skip_many_is_one_write_and_never_forever(tmp_path, monkeypatch):
    monkeypatch.setenv("MEDIA_DB_PATH", str(tmp_path / "media.db"))
    assert media_db.skip_many("you", []) == 0
    media_db.skip("you", "jf:a", "tv", "A", forever=True)
    n = media_db.skip_many("you", [{"item_key": "jf:b", "kind": "movie", "title": "B"}, {"item_key": None}])
    assert n == 1 and {s["key"]: s["forever"] for s in media_db.skips("you")} == {"jf:a": 1, "jf:b": 0}
