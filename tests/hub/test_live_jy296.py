"""JY-296/297 (2026-11-04, Option A): the Live page = now-playing wall + Health rail, its two 30 s poll fragments,
the empty state, the owner-only gate and the no-overflow CSS rules (B.: "going off the page to the right")."""
import re
import time
from pathlib import Path

import pytest

from hub import media_backup, server_history
from tests.hub.conftest import main_raw as main_of
from tests.hub.fake_jellyfin import FRIEND_ID
from tests.hub.guest_pages import guest_client, sign_in
from tests.hub.helpers import write_envelope
from tests.hub.test_media_detail import APPS, PLAY, app_factory  # noqa: F401  (fixture)

CSS = Path(__file__).resolve().parents[2] / "hub" / "static" / "control-surface.css"
SYSTEM = {"cpu_pct": 12.4, "ram_pct_used": 57, "volumes": [{"path": "/volume1", "total_gb": 1000, "free_gb": 250,
                                                             "pct_used": 75}]}
QBIT = {"active": [{"name": "Sample.Torrent", "pct": 40, "state_text": "Downloading", "speed_text": "2 MB/s",
                    "eta_text": "5m"}]}


@pytest.fixture()
def snaps(app_factory, monkeypatch):  # noqa: F811
    monkeypatch.setattr(media_backup, "current_status", lambda: {"state": "ok", "age_text": "2h ago", "size_text": "1 MB",
                                                                 "note": None})
    monkeypatch.setattr(server_history, "forecast_peek", lambda: {"key": "forecast:/volume1",
                                                                  "words": "reaches 85% in about 23 days"})
    build, tmp_path = app_factory
    d = tmp_path / "snaps"
    write_envelope(d, "media_status", age_minutes=1, data={"summary": "x", "apps": APPS})
    write_envelope(d, "system", age_minutes=1, data=SYSTEM)
    write_envelope(d, "qbittorrent", age_minutes=1, data=QBIT)
    return build, d


def test_live_page_has_wall_and_health_rail(snaps):
    build, d = snaps
    write_envelope(d, "jellyfin", age_minutes=1, data=PLAY)
    with build(d) as client:
        body = main_of(client.get("/media/playing").text)
    assert '<div class="live">' in body
    now, rail = body.index('id="live-now"'), body.index('id="live-health"')
    assert now < rail                                                     # rail on the right (source order)
    assert 'class="live-card"' in body and "Harbour Lights" in body and "width: 42%" in body
    assert "Sample.Torrent" in body and ">Downloading</h2>" in body
    rail_html = body[rail:]
    assert "1 down · Prowlarr" in rail_html
    assert "CPU" in rail_html and "12%" in rail_html and "RAM" in rail_html and "57%" in rail_html
    assert "Volume 1" in rail_html and "75%" in rail_html and "reaches 85% in about 23 days" in rail_html
    assert '<span class="st-up">Up</span>' in rail_html and '<span class="st-down">Down</span>' in rail_html
    assert "Backup: Backed up · 2h ago" in rail_html


def test_fragments_render_alone_with_polls(snaps):
    build, d = snaps
    write_envelope(d, "jellyfin", age_minutes=1, data=PLAY)
    with build(d) as client:
        now = client.get("/media/playing/part/now")
        health = client.get("/media/playing/part/health")
        for path in ("/media/playing/part/now", "/media/playing/part/health"):   # poll budget: warm render < 50 ms
            took = []
            for _ in range(6):
                t = time.perf_counter()
                client.get(path)
                took.append(time.perf_counter() - t)
            assert min(took[1:]) < 0.05, (path, took)   # best warm request, test client included
    assert now.status_code == 200 and health.status_code == 200
    for resp, part in ((now, "now"), (health, "health")):
        assert "<html" not in resp.text and "<main" not in resp.text
        assert f'hx-get="/media/playing/part/{part}"' in resp.text
        assert 'hx-trigger="every 30s [!document.hidden]"' in resp.text and 'hx-swap="outerHTML"' in resp.text
    assert "Harbour Lights" in now.text and "Volume 1" in health.text


def test_empty_state_shows_last_watched(snaps):
    build, d = snaps
    data = {**PLAY, "now_playing": [],
            "history": {"recent": [{"title": "Old Lighthouse", "when": "2h ago", "poster": None}]}}
    write_envelope(d, "jellyfin", age_minutes=1, data=data)
    with build(d) as client:
        body = main_of(client.get("/media/playing").text)
    assert "Nothing playing" in body and "Old Lighthouse" in body and "Last watched" in body
    assert "Dust and Daylight" in body                                    # Up next still there


def test_live_css_cannot_push_the_page_sideways():
    css = CSS.read_text(encoding="utf-8")
    live = re.search(r"\.live \{[^}]*\}", css).group(0)
    assert "minmax(0, 1fr)" in live and re.search(r"(?<!minmax\(0, )\b1fr\b", live) is None
    assert re.search(r"\.live > \*[^{]*\{[^}]*min-width: 0", css)
    tiles = re.search(r"\.live-tiles \{[^}]*\}", css).group(0)
    assert "overflow-x: auto" in tiles
    narrow = css.split("@media (max-width: 1100px)", 1)[1].split("}\n}", 1)[0]
    assert "grid-template-columns: minmax(0, 1fr)" in narrow and "order: -1" in narrow


@pytest.fixture()
def friend(monkeypatch, tmp_path):
    client, fake = guest_client(monkeypatch, tmp_path)
    with client as c:
        sign_in(c, fake, FRIEND_ID)
        yield c


def test_friends_never_reach_live_or_health(friend):
    for path in ("/media/playing", "/media/apps", "/media/playing/part/now", "/media/playing/part/health"):
        assert friend.get(path).status_code == 404, path
    page = friend.get("/media/movies").text
    assert ">Live<" not in page and "/media/playing" not in page and ">Health<" not in page


def test_health_tab_is_gone_and_apps_redirects_to_live(snaps):
    """JY-319: no Health tab; /media/apps sends the owner to Live (302), where the rail carries Health."""
    from hub import media_nav
    assert not [h for s in media_nav.SECTIONS for _, h in s["tabs"] if h == "/media/apps"]
    assert "/media/apps" not in [p for s in media_nav.SECTIONS for p in s["prefixes"]]
    build, d = snaps
    with build(d) as client:
        r = client.get("/media/apps", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/media/playing"
