"""Server → Discord push of NEW Attention items (WP-U2, 2026-10-06). requests.post is mocked;
media.db is the conftest's isolated tmp file."""
import importlib
import sqlite3

import pytest
import requests
from fastapi.testclient import TestClient

from hub import media_db, server_alerts
from tests.hub.test_store import write_envelope

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
