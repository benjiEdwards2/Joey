"""T3 hub core (2026-10-09): per-request work the hub does once, not per consumer (H-50, H-08, H-29, H-53)."""
import importlib

from fastapi.testclient import TestClient
from starlette.requests import Request

from tests.hub.test_registry import make_area, make_tile, write_registry
from tests.hub.test_store import write_envelope


def _shelf_area():
    area = make_area("alpha", "play-t", snapshot="jellyfin", stale_after_minutes=10, detail="/media/playing")
    area["layout"] = "shelves"
    area["tiles"].append(make_tile("hist-t", snapshot="jellyfin", stale_after_minutes=10, detail="/media/history"))
    return area


def _reload(tmp_path, monkeypatch, *areas):
    monkeypatch.setenv("SNAPSHOT_DIR", str(tmp_path / "snaps"))
    monkeypatch.setenv("MEDIA_DB_PATH", str(tmp_path / "media.db"))
    monkeypatch.setenv("AREAS_PATH", str(write_registry(tmp_path, *areas)))
    write_envelope(tmp_path / "snaps", "jellyfin", age_minutes=1, data={"summary": "x", "history": {"recent": [
        {"title": "Film", "kind": "movie", "item_key": "tmdb:1", "watched_at": "2099-01-01T00:00:00Z"}]}})
    import hub.main
    importlib.reload(hub.main)
    return hub.main


def test_status_is_built_for_the_hub_page_only(tmp_path, monkeypatch):
    """H-50: only hub.html reads `status`; no other page pays for build_status. H-08: only media_playing.html
    reads `owner_view`."""
    main = _reload(tmp_path, monkeypatch, _shelf_area(), make_area("beta"))
    ctx, real = {}, main.templates.TemplateResponse

    def spy(request, name, context=None, *a, **kw):
        ctx[name] = set(context or {})
        return real(request, name, context, *a, **kw)

    monkeypatch.setattr(main.templates, "TemplateResponse", spy)
    with TestClient(main.app) as c:
        for path in ("/", "/weather", "/a/beta", "/a/alpha", "/media/playing", "/a/nope"):
            c.get(path)
    assert set(ctx) == {"hub.html", "weather.html", "area.html", "area_shelves.html", "media_playing.html", "404.html"}
    assert [n for n, keys in ctx.items() if "status" in keys] == ["hub.html"]
    assert [n for n, keys in ctx.items() if "owner_view" in keys] == ["media_playing.html"]


def test_media_frame_reads_ratings_once(tmp_path, monkeypatch):
    """H-29: the Media frame's waiting counts and To rate tab counts share one recent + ratings read."""
    main = _reload(tmp_path, monkeypatch, _shelf_area())
    calls = []
    real = main._ratings
    monkeypatch.setattr(main, "_ratings", lambda *a: calls.append(a) or real(*a))
    with TestClient(main.app):
        req = Request({"type": "http", "method": "GET", "path": "/media/movies", "headers": [], "query_string": b"",
                       "scheme": "http", "server": ("t", 80), "root_path": ""})
        nav = main.media_frame(req)
    assert len(calls) == 1 and nav


def test_server_loop_reads_snapshots_once(tmp_path, monkeypatch):
    """H-53: one snapshot read feeds both the history sample and the alert check."""
    main = _reload(tmp_path, monkeypatch, _shelf_area())
    reads, seen = [], {}
    monkeypatch.setattr(main, "_read_snapshots", lambda *a: reads.append(1) or {"marker": True})
    monkeypatch.setattr(main.server_history, "sample", lambda snaps=None: seen.setdefault("sample", snaps))
    monkeypatch.setattr(main.server_alerts, "check_once", lambda live=None, snaps=None: seen.setdefault("check", snaps))
    main._server_tick()
    assert reads == [1] and seen["sample"] == seen["check"] == {"marker": True}


def test_check_once_uses_the_callers_snapshots(tmp_path, monkeypatch):
    from hub import server_alerts, store
    monkeypatch.setenv("SERVER_DISCORD_WEBHOOK", "https://discord.invalid/hook")
    monkeypatch.setenv("MEDIA_DB_PATH", str(tmp_path / "media.db"))
    monkeypatch.setattr(store, "get_snapshots", lambda *a: (_ for _ in ()).throw(AssertionError("re-read")))
    monkeypatch.setattr(server_alerts, "sync", lambda items: len(items))
    assert server_alerts.check_once(set(), {}) >= 0
