"""M-40 (W2 media, 2026-10-09): the Media write routes read their form on the event loop but run the slow part —
Jellyseerr / Sonarr / Jellyfin calls, SQLite writes — in a worker thread. A stuck upstream must never stall the
rest of the hub: /healthz answers while one of these routes is still waiting on its upstream."""
import importlib
import threading
import time

import pytest
from fastapi.testclient import TestClient

from tests.hub.helpers import make_area, write_registry

WAIT_S = 5.0


@pytest.fixture
def client(tmp_path, monkeypatch):
    area = make_area("alpha", "play-t", snapshot="jellyfin", stale_after_minutes=10, detail="/media/playing")
    area["layout"] = "shelves"
    monkeypatch.setenv("SNAPSHOT_DIR", str(tmp_path / "snaps"))
    monkeypatch.setenv("MEDIA_DB_PATH", str(tmp_path / "media.db"))
    monkeypatch.setenv("AREAS_PATH", str(write_registry(tmp_path, area)))
    import hub.main
    importlib.reload(hub.main)
    with TestClient(hub.main.app) as c:
        yield c


def _stuck(started: threading.Event, release: threading.Event, result):
    def fake(*_a, **_k):
        started.set()
        release.wait(WAIT_S)
        return result
    return fake


# (patch target module, attribute, what the fake returns, method, path, form body)
CASES = {
    "request": ("hub.media_discover", "_send", None, "/media/title/movie/603/request", {}),
    "search_now": ("hub.media_arr_search", "start_search", ("started", None), "/media/title/movie/603/search", {}),
    "mark_watched": ("hub.media_resume", "act", (None, None), "/media/resume/abc123/watched", {"back": "/media/tv"}),
    "follow": ("hub.media_follow", "_describe", {}, "/media/follow/person/31", {"name": "Tom Hanks"}),
    "rate": ("hub.media_db", "set_rating", None, "/media/rate",
             {"item_key": "tmdb:603", "kind": "movie", "title": "The Matrix", "score": "8"}),
    "watchlist": ("hub.media_watchlist_db", "add", None, "/media/watchlist/add",
                  {"tmdb_id": "603", "kind": "movie", "title": "The Matrix"}),
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_a_stuck_upstream_does_not_block_healthz(client, monkeypatch, name):
    module, attr, result, path, form = CASES[name]
    started, release = threading.Event(), threading.Event()
    monkeypatch.setattr(importlib.import_module(module), attr, _stuck(started, release, result))
    out = {}

    def write():
        out["resp"] = client.post(path, data=form, follow_redirects=False)

    worker = threading.Thread(target=write)
    worker.start()
    try:
        assert started.wait(WAIT_S), "the route never reached its upstream"
        t0 = time.monotonic()
        health = client.get("/healthz")
        elapsed = time.monotonic() - t0
    finally:
        release.set()
        worker.join(WAIT_S * 2)
    assert health.status_code == 200
    assert elapsed < 1.5, f"/healthz waited {elapsed:.1f}s behind {name}"
    assert out["resp"].status_code in (200, 303)
