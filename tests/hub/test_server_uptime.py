"""JY-133 (P7, 2026-10-26, built as option A for B.'s pick): 7-day uptime per service on the Server cards.

Joey samples the cached `uptime_kuma` snapshot into media.db (`server_kuma_samples`), sums 7 days after the page and on
the 5-minute loop, and the render reads only the in-memory result (`server_uptime.peek()`): no live call, no DB read."""
import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from hub import media_db, server, server_uptime
from hub.store import get_snapshots
from tests.hub.helpers import write_envelope
from tests.hub.test_server import env, main_of  # noqa: F401 (fixture)
from tests.hub.test_server_cards import card

NOW = datetime(2026, 10, 26, 10, 0, tzinfo=timezone.utc)
KUMA = {"summary": "2 of 3 up", "up": 2, "down": 1, "total": 3, "monitors": [
    {"name": "Jellyfin", "type": "http", "status": "up", "response_ms": 38},
    {"name": "Prowlarr", "type": "http", "status": "down", "response_ms": None},
    {"name": "NAS", "type": "ping", "status": "up", "response_ms": 2}]}


@pytest.fixture(autouse=True)
def _fresh():
    server_uptime.clear()
    yield
    server_uptime.clear()


def _rows():
    with sqlite3.connect(media_db.db_path()) as db:
        return db.execute("SELECT ts, states FROM server_kuma_samples ORDER BY ts").fetchall()


def _write(snaps, age_minutes=1, status="ok", data=KUMA):
    write_envelope(snaps, "uptime_kuma", age_minutes=age_minutes, data=data, status=status)


def rows(*spec):
    """(minutes before NOW, {name: state}) -> the summary's row shape, oldest first."""
    return sorted(((NOW - timedelta(minutes=m)), states) for m, states in spec)


# ---- sampling ---------------------------------------------------------------------------------------------------

def test_sample_stores_names_and_states_once_per_snapshot(tmp_path):
    snaps = tmp_path / "snaps"
    _write(snaps, age_minutes=4)
    assert server_uptime.sample(get_snapshots(snaps)) is True
    assert server_uptime.sample(get_snapshots(snaps)) is False          # same updated_at: no duplicate
    (ts, states), = _rows()
    assert ts.endswith("Z") and json.loads(states) == {"Jellyfin": "up", "Prowlarr": "down", "NAS": "up"}
    _write(snaps, age_minutes=2)
    assert server_uptime.sample(get_snapshots(snaps)) is True
    assert len(_rows()) == 2


def test_sample_skips_missing_error_and_empty_snapshots(tmp_path):
    snaps = tmp_path / "snaps"
    assert server_uptime.sample(get_snapshots(snaps)) is False
    _write(snaps, status="error")
    assert server_uptime.sample(get_snapshots(snaps)) is False
    _write(snaps, data={"summary": "No monitors", "monitors": []})
    assert server_uptime.sample(get_snapshots(snaps)) is False
    assert not media_db.db_path().exists()


def test_sample_prunes_rows_older_than_8_days(tmp_path):
    snaps = tmp_path / "snaps"
    _write(snaps, age_minutes=9 * 1440)
    assert server_uptime.sample(get_snapshots(snaps)) is True
    _write(snaps, age_minutes=1)
    assert server_uptime.sample(get_snapshots(snaps)) is True
    assert len(_rows()) == 1


def test_sample_never_stores_a_url_or_host(tmp_path):
    snaps = tmp_path / "snaps"
    leaky = {**KUMA, "monitors": [{**KUMA["monitors"][0], "url": "http://nas.local:8096", "hostname": "nas.local"}]}
    _write(snaps, data=leaky)
    server_uptime.sample(get_snapshots(snaps))
    assert "nas.local" not in _rows()[0][1]


# ---- the 7-day sum and its words ---------------------------------------------------------------------------------

def test_summary_counts_up_over_up_plus_down_in_the_last_7_days():
    spec = [(m, {"Jellyfin": "up", "Prowlarr": "up"}) for m in range(5, 7 * 1440, 60)]
    spec += [(8 * 1440, {"Prowlarr": "down"})]                          # older than 7 days: ignored
    spec += [(300, {"Prowlarr": "down"}), (310, {"Prowlarr": "pending"}), (320, {"Prowlarr": "maintenance"})]
    s = server_uptime.summary(rows(*spec), NOW)
    assert s["jellyfin"]["pct"] == 100.0 and s["jellyfin"]["last_down"] is None
    up = len(range(5, 7 * 1440, 60))
    assert s["prowlarr"]["pct"] == pytest.approx(100 * up / (up + 1))
    assert s["prowlarr"]["last_down"] == NOW - timedelta(minutes=300)
    assert 6.9 < s["jellyfin"]["days"] <= 7


def test_words():
    w = server_uptime.words
    assert w({"pct": 100.0, "days": 7.0, "last_down": None}, NOW) == "100% up · 7 days"
    assert w({"pct": 99.46, "days": 3.2, "last_down": NOW - timedelta(hours=5)}, NOW) == "99.4% up · 3 days · down 5h ago"
    assert w({"pct": 99.99, "days": 6.6, "last_down": NOW - timedelta(days=2)}, NOW) == "99.9% up · 7 days · down 2d ago"
    assert w({"pct": 100.0, "days": 0.2, "last_down": None}, NOW) == "100% up · today"
    assert w({"pct": 100.0, "days": 1.1, "last_down": None}, NOW) == "100% up · 1 day"
    assert w(None, NOW) is None


def test_a_monitor_with_only_pending_samples_has_no_line():
    s = server_uptime.summary(rows((10, {"NAS": "pending"}), (20, {"NAS": "maintenance"})), NOW)
    assert "nas" not in s


# ---- the card ----------------------------------------------------------------------------------------------------

def test_service_card_takes_the_line_by_name_or_id():
    up = {"jellyfin": {"pct": 100.0, "days": 7.0, "last_down": None},
          "jellyseerr": {"pct": 98.0, "days": 7.0, "last_down": None}}
    jf = server.service_card({"id": "jellyfin", "name": "Jellyfin", "up": True}, [], uptime=up, now=NOW)
    assert jf["uptime_text"] == "100% up · 7 days"
    seerr = server.service_card({"id": "jellyseerr", "name": "Seerr", "up": True}, [], uptime=up, now=NOW)
    assert seerr["uptime_text"] == "98% up · 7 days"
    assert server.service_card({"id": "portainer", "name": "Portainer", "up": True}, [], uptime=up)["uptime_text"] is None
    assert server.service_card({"id": "jellyfin", "name": "Jellyfin", "up": True}, [])["uptime_text"] is None


def test_the_page_shows_the_line_from_the_cache_only(env, monkeypatch):
    with env() as client:
        body = main_of(client.get("/server").text)
        assert 'class="svc-sub svc-uptime"' not in body                  # nothing cached yet: no line, no DB read
        monkeypatch.setattr(server_uptime, "_summary", {"jellyfin": {"pct": 99.46, "days": 7.0,
                                                                     "last_down": datetime.now(timezone.utc) - timedelta(hours=3)}})
        body = main_of(client.get("/server").text)
    jf = card(body, "Jellyfin")
    assert '<span class="svc-sub svc-uptime">99.4% up · 7 days · down 3h ago</span>' in jf
    assert "svc-uptime" not in card(body, "Portainer")


def test_the_render_never_reads_the_samples_table(env, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("the render read media.db")
    with env() as client:
        monkeypatch.setattr(server_uptime, "refresh", boom)
        monkeypatch.setattr(server_uptime, "_read_rows", boom)
        monkeypatch.setattr(server_uptime, "sample", lambda *a, **k: False)   # the after-page task, not the render
        assert client.get("/server").status_code == 200


def test_tick_samples_then_refreshes(tmp_path):
    snaps = tmp_path / "snaps"
    _write(snaps, age_minutes=1)
    server_uptime.tick(get_snapshots(snaps))
    got = server_uptime.peek()
    assert got["jellyfin"]["pct"] == 100.0 and got["prowlarr"]["pct"] == 0.0


# ---- review should-fixes (2026-10-26) ----------------------------------------------------------------------------

def test_the_overnight_gap_is_not_down():
    """The NAS is off 22:00-07:00 Melbourne (11:00-20:00 UTC in October): no samples, so nothing counts either way."""
    mel_day = [(m, {"Jellyfin": "up"}) for d in range(7) for m in range(d * 1440 + 30, d * 1440 + 15 * 60, 5)]
    s = server_uptime.summary(rows(*mel_day), NOW)
    assert s["jellyfin"]["pct"] == 100.0 and s["jellyfin"]["last_down"] is None
    assert server_uptime.words(s["jellyfin"], NOW).startswith("100% up · ")


def test_the_render_never_samples(env):
    with env() as client:
        assert client.get("/server").status_code == 200
        client.get("/server")
    if media_db.db_path().exists():
        with sqlite3.connect(media_db.db_path()) as db:
            names = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "server_kuma_samples" not in names                       # the 5-minute loop is the one writer


def test_refresh_reads_without_creating_anything(tmp_path):
    assert server_uptime.refresh(NOW) == {}
    assert not media_db.db_path().exists()
    media_db.connect().close()                                          # a media.db without the table
    assert server_uptime.refresh(NOW) == {}
    with sqlite3.connect(media_db.db_path()) as db:
        names = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "server_kuma_samples" not in names


def test_the_loop_tick_samples_at_most_once_per_snapshot(tmp_path):
    snaps = tmp_path / "snaps"
    _write(snaps, age_minutes=3)
    for _ in range(3):
        server_uptime.tick(get_snapshots(snaps))
    assert len(_rows()) == 1
