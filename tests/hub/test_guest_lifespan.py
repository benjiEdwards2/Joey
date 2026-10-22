"""Joey TV WP-B1 (2026-10-21, Q24): the media front starts zero background loops - joey-hub stays the single
background writer against the shared media.db. _server_alerts_loop has no env switch, so the guard is in code."""
import asyncio
import importlib

import pytest
from fastapi.testclient import TestClient

from hub import media_plays, tasks

LOOP_ENVS = ("MEDIA_BACKUP", "PLAY_RECORDER", "MEDIA_WARMUP", "MEDIA_FOLLOW", "MEDIA_AWARDS")
STARTERS = ("_backup_loop", "_server_alerts_loop", "_media_warmup_loop", "_media_follow_loop", "_media_awards_loop")


@pytest.fixture()
def starts(monkeypatch):
    for key in LOOP_ENVS:
        monkeypatch.setenv(key, "on")
    calls = []

    async def idle():
        await asyncio.sleep(3600)

    def fake(name):
        def start():
            calls.append(name)
            return idle()
        return start

    for name in STARTERS:
        monkeypatch.setattr(tasks, name, fake(name))

    def recorder():
        calls.append("start_recorder")
        return None
    monkeypatch.setattr(media_plays, "start_recorder", recorder)
    import hub.main
    importlib.reload(hub.main)
    return calls


def test_no_background_loops_in_media_mode(starts, monkeypatch):
    monkeypatch.setenv("JOEY_FRONT", "media")
    import hub.main
    with TestClient(hub.main.app) as c:
        assert c.get("/healthz").json()["front"] == "media"
    assert starts == []


def test_private_front_starts_every_loop(starts):
    """Control: the same patches see all six starters on the private front, so the zero above is real."""
    import hub.main
    with TestClient(hub.main.app):
        pass
    assert sorted(starts) == sorted([*STARTERS, "start_recorder"])
