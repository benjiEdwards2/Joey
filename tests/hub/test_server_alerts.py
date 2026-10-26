"""Server → Discord push of NEW Attention items (WP-U2, 2026-10-06). requests.post is mocked;
media.db is the conftest's isolated tmp file."""
import importlib
import sqlite3

import pytest
import requests
from fastapi.testclient import TestClient

from hub import media_db, server_alerts
from tests.hub.helpers import write_envelope

HOOK = "https://discord.invalid/api/webhooks/1/SECRET"


class Resp:
    def __init__(self, code):
        self.status_code = code


class Calls(list):
    state: dict


@pytest.fixture()
def posts(monkeypatch):
    calls = Calls()
    state = {"code": 204, "raise": None}

    def fake_post(url, json=None, timeout=None):
        calls.append({"url": url, "text": json["content"], "timeout": timeout})
        if state["raise"]:
            raise state["raise"]
        return Resp(state["code"])
    monkeypatch.setattr(server_alerts.requests, "post", fake_post)
    monkeypatch.setenv("SERVER_DISCORD_WEBHOOK", HOOK)
    calls.state = state
    return calls


DOWN = {"key": "down:prowlarr", "text": "Prowlarr is Down (timeout)"}
DISK = {"key": "disk:/volume1", "text": "/volume1 is 90% full (10.0 GB free)"}


def test_new_item_posts_once_then_not_again(posts):
    assert server_alerts.sync([DOWN]) == 1
    assert posts == [{"url": HOOK, "text": "Joey Server: Prowlarr is Down (timeout)", "timeout": 10}]
    assert server_alerts.sync([DOWN]) == 0 and len(posts) == 1


def test_gone_then_back_notifies_again(posts):
    server_alerts.sync([DOWN, DISK])
    server_alerts.sync([DISK])                         # prowlarr recovered: row deleted
    with sqlite3.connect(media_db.db_path()) as db:
        assert [r[0] for r in db.execute("SELECT key FROM server_attention_seen")] == ["disk:/volume1"]
    assert server_alerts.sync([DOWN, DISK]) == 1
    assert [p["text"] for p in posts].count("Joey Server: Prowlarr is Down (timeout)") == 2


def test_webhook_unset_does_nothing(posts, monkeypatch):
    monkeypatch.delenv("SERVER_DISCORD_WEBHOOK")
    assert server_alerts.sync([DOWN]) == 0 and posts == []
    assert not media_db.db_path().exists() and server_alerts.check_once() == 0


def test_webhook_4xx_or_exception_never_raises_and_retries_next_cycle(posts, caplog):
    posts.state["code"] = 404
    assert server_alerts.sync([DOWN]) == 0
    posts.state["code"], posts.state["raise"] = 204, requests.ConnectionError(HOOK)
    assert server_alerts.sync([DOWN]) == 0
    assert "SECRET" not in caplog.text and "ConnectionError" in caplog.text
    posts.state["raise"] = None
    assert server_alerts.sync([DOWN]) == 1 and len(posts) == 3


def test_at_most_five_per_cycle(posts):
    items = [{"key": f"kuma:m{i}", "text": f"Uptime Kuma: m{i} is Down"} for i in range(7)]
    assert server_alerts.sync(items) == 5
    assert server_alerts.sync(items) == 2 and len(posts) == 7


def test_check_once_and_server_render_push_from_snapshots(posts, tmp_path, monkeypatch):
    snaps = tmp_path / "snaps"
    monkeypatch.setenv("SNAPSHOT_DIR", str(snaps))
    monkeypatch.delenv("AREAS_PATH", raising=False)
    write_envelope(snaps, "media_status", age_minutes=1, data={"summary": "0 of 1 up", "apps": [
        {"id": "prowlarr", "name": "Prowlarr", "up": False, "note": "timeout"}]})
    assert server_alerts.check_once() == 1
    write_envelope(snaps, "uptime_kuma", age_minutes=1, data={"monitors": [
        {"name": "Radarr", "status": "down"}]})
    import hub.main
    importlib.reload(hub.main)
    with TestClient(hub.main.app) as client:
        assert client.get("/server").status_code == 200
    assert [p["text"] for p in posts] == ["Joey Server: Prowlarr is Down (timeout)",
                                         "Joey Server: Uptime Kuma: Radarr is Down"]


def test_a_refused_push_backs_off_after_three_failures(posts, caplog):
    """H-67: a permanently refused webhook is tried 3 times per item, then left alone while the item stays current;
    once the item clears and returns it is tried again."""
    import logging
    posts.state["code"] = 404
    with caplog.at_level(logging.WARNING, logger="hub.server_alerts"):
        for _ in range(6):
            assert server_alerts.sync([DOWN]) == 0
    assert len(posts) == 3 and "giving up on one item after 3 failures" in caplog.text
    assert HOOK not in caplog.text and "SECRET" not in caplog.text
    server_alerts.sync([])                               # cleared: row deleted
    posts.state["code"] = 204
    assert server_alerts.sync([DOWN]) == 1 and len(posts) == 4


def test_fails_column_is_added_to_an_older_table(posts):
    with sqlite3.connect(media_db.db_path()) as db:
        db.execute("CREATE TABLE server_attention_seen(key TEXT PRIMARY KEY, first_seen TEXT, last_seen TEXT, "
                   "notified_at TEXT)")
        db.execute("INSERT INTO server_attention_seen VALUES('down:prowlarr', 'a', 'a', NULL)")
    assert server_alerts.sync([DOWN]) == 1
    with sqlite3.connect(media_db.db_path()) as db:
        assert [r[1] for r in db.execute("PRAGMA table_info(server_attention_seen)")][-1] == "fails"


# ---- JY-254: the boot grace -------------------------------------------------------------------------------------

def _status(d, updated, apps):
    """A media_status envelope whose last success is `updated` (aware)."""
    import json
    d.mkdir(parents=True, exist_ok=True)
    ts = updated.isoformat()
    (d / "media_status.json").write_text(json.dumps({
        "connector": "media_status", "schema_version": 1, "fetched_at": ts, "updated_at": ts, "status": "ok",
        "consecutive_failures": 0, "error": None, "data": {"apps": apps}}), encoding="utf-8")
    from hub import store
    return store.get_snapshots(d)


def _boot():
    from datetime import datetime, timezone
    return datetime(2026, 1, 1, 7, 0, tzinfo=timezone.utc)


PROWLARR_DOWN = [{"id": "prowlarr", "name": "Prowlarr", "up": False, "note": "timeout"},
                 {"id": "radarr", "name": "Radarr", "up": True}]


def _downs(posts):
    return [p["text"] for p in posts if " is Down" in p["text"]]


def test_no_down_alert_at_boot_plus_2_min_without_a_fresh_sample(posts, tmp_path):
    from datetime import timedelta
    b = _boot()
    snaps = _status(tmp_path / "snaps", b - timedelta(hours=9), PROWLARR_DOWN)
    server_alerts.check_once(set(), snaps, now=b + timedelta(minutes=2), booted=b)
    assert _downs(posts) == []
    assert "down:prowlarr" not in server_alerts.seen_keys("down:")


def test_a_dead_service_alerts_at_boot_plus_20_min(posts, tmp_path):
    from datetime import timedelta
    b = _boot()
    snaps = _status(tmp_path / "snaps", b + timedelta(minutes=19), PROWLARR_DOWN)
    assert server_alerts.check_once(set(), snaps, now=b + timedelta(minutes=20), booted=b) >= 1
    assert _downs(posts) == ["Joey Server: Prowlarr is Down (timeout)"]


def test_an_already_running_hub_alerts_a_real_outage_at_once(posts, tmp_path):
    from datetime import timedelta
    b = _boot()
    snaps = _status(tmp_path / "snaps", b + timedelta(hours=5, minutes=-1), PROWLARR_DOWN)
    server_alerts.check_once(set(), snaps, now=b + timedelta(hours=5), booted=b)
    assert _downs(posts) == ["Joey Server: Prowlarr is Down (timeout)"]


def test_an_outage_pushed_before_a_restart_is_kept_through_the_grace_and_not_pushed_again(posts, tmp_path):
    from datetime import timedelta
    b = _boot()
    assert server_alerts.sync([DOWN]) == 1                                   # pushed before the restart
    snaps = _status(tmp_path / "snaps", b - timedelta(minutes=30), PROWLARR_DOWN)
    server_alerts.check_once(set(), snaps, now=b + timedelta(minutes=2), booted=b)
    assert "down:prowlarr" in server_alerts.seen_keys("down:")              # held, not deleted
    snaps = _status(tmp_path / "snaps", b + timedelta(minutes=19), PROWLARR_DOWN)
    server_alerts.check_once(set(), snaps, now=b + timedelta(minutes=20), booted=b)
    assert _downs(posts) == ["Joey Server: Prowlarr is Down (timeout)"]   # still the one push
