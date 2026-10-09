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
    """H-50: only hub.html reads `status`; no other page pays for build_status. H-08 / M-16: the detail pages get the
    data `owner` (media_playing.html's Move on acts), never the raw `owner_view`."""
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
    assert [n for n, keys in ctx.items() if "owner_view" in keys] == []
    assert "owner" in ctx["media_playing.html"]


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


def test_unranked_count_matches_years_overview(tmp_path, monkeypatch):
    """H-49: the hub's "to place" is one COUNT, equal to the per-year sum it replaces."""
    from hub import media_db
    monkeypatch.setenv("MEDIA_DB_PATH", str(tmp_path / "media.db"))
    assert media_db.unranked_count() == 0                       # no media.db yet
    for i, year in enumerate((2020, 2020, 2021, None, 2021)):
        media_db.set_rating(f"tmdb:{i}", 7, "movie", f"Film {i}", year=year)
    media_db.set_rating("tmdb:99", 8, "movie", "Hers", year=2020, owner="her")
    media_db.place(2020, "tmdb:0")
    media_db.place(2021, "tmdb:2")
    expected = sum(y["unranked_count"] for y in media_db.years_overview())
    assert media_db.unranked_count() == expected == 3


def test_hub_server_card_is_cached_while_snapshots_are_unchanged(tmp_path, monkeypatch):
    """H-49: the hub page reuses the Server card for 60 s; a new snapshot (or the TTL) rebuilds it."""
    server_area = make_area("srv", "svc-t", snapshot="media_status", stale_after_minutes=10)
    server_area["layout"] = "server"
    main = _reload(tmp_path, monkeypatch, server_area)
    write_envelope(tmp_path / "snaps", "media_status", age_minutes=1, data={"summary": "1 of 1 up", "apps": [
        {"id": "j", "name": "Jellyfin", "up": True}]})
    builds, backups = [], []
    real_card, real_status = main.server_area.hub_card, main.media_backup.current_status
    monkeypatch.setattr(main.server_area, "hub_card", lambda *a, **k: builds.append(1) or real_card(*a, **k))
    monkeypatch.setattr(main.media_backup, "current_status", lambda: backups.append(1) or real_status())
    with TestClient(main.app) as c:
        assert "All up" in c.get("/").text and "All up" in c.get("/").text
        assert len(builds) == 1 and len(backups) == 2          # one backup read per request, one card build
        write_envelope(tmp_path / "snaps", "media_status", age_minutes=0, data={"summary": "0 of 1 up", "apps": [
            {"id": "j", "name": "Jellyfin", "up": False}]})
        assert "1 down · Jellyfin" in c.get("/").text and len(builds) == 2
        monkeypatch.setattr(main, "HUB_CARD_TTL_S", 0)
        c.get("/")
        assert len(builds) == 3


def test_a_media_page_reads_the_snapshot_dir_once(tmp_path, monkeypatch):
    """H-48: _detail_page, its builders (_qb_data, _arr_linker) and media_frame share request.state.snaps."""
    area = _shelf_area()
    area["tiles"] += [make_tile("lib-t", snapshot="arr", stale_after_minutes=60, detail="/media/library"),
                      make_tile("dl-t", snapshot="qbittorrent", stale_after_minutes=60, detail="/media/downloads")]
    main = _reload(tmp_path, monkeypatch, area)
    write_envelope(tmp_path / "snaps", "arr", age_minutes=1, data={"summary": "x", "arrived": [], "this_week": []})
    write_envelope(tmp_path / "snaps", "qbittorrent", age_minutes=1, data={"summary": "x", "active": []})
    reads, real = [], main.shell._read_snapshots
    monkeypatch.setattr(main.shell, "_read_snapshots", lambda *a: reads.append(1) or real(*a))
    with TestClient(main.app) as c:
        for path in ("/media/library", "/media/downloads", "/media/movies", "/"):
            reads.clear()
            assert c.get(path).status_code == 200
            assert reads == [1], path


def test_ids_are_defined_once_for_the_hub_core():
    """H-19 / H-26 / H-21 / H-24: snapshot ids, the home clock, the areas path and the timestamp parser live in one
    place each; main.py and the server modules import them."""
    import re
    from pathlib import Path

    from hub import ids, main, server, server_history, server_updates
    hub_dir = Path(__file__).resolve().parents[2] / "hub"
    for name in ("main.py", "server.py", "server_history.py", "server_alerts.py", "server_updates.py"):
        text = (hub_dir / name).read_text(encoding="utf-8")
        assert not re.search(r'(?m)^[A-Z_]*SNAPSHOT_ID = "', text), name
        assert 'HOME_TZ_NAME = "' not in text and 'replace("Z", "+00:00")' not in text, name
    assert main.JELLYFIN_SNAPSHOT_ID == ids.JELLYFIN_SNAPSHOT_ID and server.SYSTEM_SNAPSHOT_ID == ids.SYSTEM_SNAPSHOT_ID
    assert server_history.SYSTEM_SNAPSHOT_ID == "system" and server_updates.key_tag is server.key_tag
    assert main._now_home is ids.home_now


def test_home_clock_and_areas_path(monkeypatch):
    from hub import ids
    now = ids.home_now()
    assert now.tzinfo is not None and str(now.tzinfo) in ("Australia/Melbourne", str(now.astimezone().tzinfo))
    monkeypatch.setenv("AREAS_PATH", "/x/areas.yaml")
    assert ids.areas_path() == "/x/areas.yaml"
    monkeypatch.setenv("AREAS_PATH", "")
    assert ids.areas_path().endswith("areas.yaml") and ids.DEFAULT_AREAS_PATH.is_file()


def test_feeds_line_counts_visible_live_feeds_only(tmp_path, monkeypatch):
    """H-32: parked areas' feeds are not in the denominator; an error envelope without data is not live."""
    parked = {**make_area("parked", "p-t", snapshot="money"), "hidden": True}
    main = _reload(tmp_path, monkeypatch, _shelf_area(), make_area("cal", "c-t", snapshot="gcal"),
                   make_area("wx", "w-t", snapshot="open_meteo", stale_after_minutes=60), parked)
    write_envelope(tmp_path / "snaps", "gcal", age_minutes=1, data={}, status="error")      # failing, nothing kept
    write_envelope(tmp_path / "snaps", "open_meteo", age_minutes=120, data={"summary": "x"})  # stale
    write_envelope(tmp_path / "snaps", "money", age_minutes=1, data={"summary": "x"})         # parked
    with TestClient(main.app):
        status = main.build_status(main.get_snapshots())
    assert status == {"feeds_total": 3, "feeds_ok": 2, "stale": ["Wx"]}


def test_connected_is_the_one_rule():
    from hub.store import Snapshot, connected, data_of

    def snap(status, data):
        return Snapshot("c", status, "", "", 0, None, data, 1.0)
    assert not connected(None) and not connected(snap("error", {}))
    assert connected(snap("error", {"summary": "old"})) and connected(snap("ok", {}))
    assert data_of(snap("error", {})) == {} and data_of(snap("ok", {"a": 1})) == {"a": 1} and data_of(None) == {}


def test_server_card_needs_attention_is_its_own_warn_state(tmp_path, monkeypatch):
    """H-34: the hub Server card's "Needs attention" is state `warn` (amber like stale), not a borrowed "stale"."""
    main = _reload(tmp_path, monkeypatch, _shelf_area())
    monkeypatch.setattr(main, "_server_hub_card", lambda snaps, backup: {"summary": "1 down · X", "secondary": None,
                                                                        "state": "warn"})
    fresh = {"state": "fresh", "age_text": "2m ago", "value": "v", "secondary": None, "href": None, "note": None}
    out = main.server_card_state(fresh, {}, {"warning": None})
    assert (out["state"], out["age_text"]) == ("warn", "Needs attention")
    stale = {**fresh, "state": "stale", "age_text": "Stale · 3h ago"}
    assert main.server_card_state(stale, {}, {"warning": None})["age_text"] == "Needs attention · Stale · 3h ago"
    html = main.templates.env.from_string('{% from "_kpi.html" import kpi %}{{ kpi("/a/x", "X", "L", "server", st, "shared") }}'
                                          ).render(st=out)
    assert '<span class="badge badge-wait">Needs attention</span>' in html
