"""Server area page (WP-S1, 2026-10-06). Real registry, sample snapshots copied into a
tmp dir; every assertion is made inside <main> (sections once rendered into <title>)."""
import importlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hub import server
from hub.registry import load_registry
from tests.hub.test_registry import AREAS_YAML, make_area, write_registry
from tests.hub.test_store import write_envelope

SAMPLES = Path(__file__).resolve().parents[2] / "config" / "sample_snapshots"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.delenv("AREAS_PATH", raising=False)
    snaps = tmp_path / "snaps"
    snaps.mkdir()
    monkeypatch.setenv("SNAPSHOT_DIR", str(snaps))

    def build(samples=True, **data):
        if samples:
            for p in SAMPLES.glob("*.json"):
                if not p.stem.startswith("_"):
                    write_envelope(snaps, p.stem, age_minutes=1,
                                   data=json.loads(p.read_text(encoding="utf-8"))["data"])
        for cid, d in data.items():
            write_envelope(snaps, cid, age_minutes=1, data=d)
        import hub.main
        importlib.reload(hub.main)
        return TestClient(hub.main.app)
    return build


def main_of(html):
    return html.split("<main", 1)[1]


def services_of(body):
    return body.split('id="services"', 1)[1].split('id="updates"', 1)[0]


def test_registry_server_area_is_last_with_the_agreed_tiles():
    area = load_registry(AREAS_YAML).areas[-1]
    assert (area.id, area.name, area.accent, area.icon, area.layout) == (
        "server", "Server", "#9AA4B2", "server", "server")
    assert area.rail_section == "areas" and not area.hidden and area.summary_tile == "services"
    tiles = {t.id: t for t in area.tiles}
    assert list(tiles) == ["services", "system", "updates", "homepage", "portainer"]
    assert (tiles["services"].snapshot, tiles["services"].stale_after_minutes) == ("media_status", 10)
    assert (tiles["system"].snapshot, tiles["system"].stale_after_minutes) == ("system", 10)
    assert (tiles["updates"].snapshot, tiles["updates"].stale_after_minutes) == ("wud", 180)
    assert tiles["homepage"].href == "https://homepage.joeyhome.net"
    assert tiles["portainer"].href == "http://192.168.68.59:9000"
    assert all(t.owner.value == "shared" for t in area.tiles)


@pytest.mark.parametrize("route", ["/server", "/a/server"])
def test_server_page_renders_every_band_from_the_samples(env, route):
    with env() as client:
        r = client.get(route)
    assert r.status_code == 200
    body = main_of(r.text)
    assert r.text.split("<title>", 1)[1].split("</title>", 1)[0] == "Server · Joey"
    # 1 System
    assert "16%" in body and "Load 0.42" in body and "1.9 GB free" in body
    assert "of 7.7 GB · 75% used" in body and "12 days 4 h" in body
    assert "/volume1/Docker" in body and "120.0 GB free of 465.6 GB · 74% used" in body
    assert "width: 71%" in body
    # 2 Services, grouped, Up/Down as words, whole row links to the app
    svc = services_of(body)
    order = [svc.index(f'<div class="head">{h}</div>') for h in ("Media", "Downloads", "System")]
    assert order == sorted(order)
    assert ">Down</span>" in body and ">Up</span>" in body
    assert 'href="http://nas.local:8096"' in body
    # 3 Updates
    assert "16 monitored · 1 update" in body and "uptime-kuma" in body and "1.23.16 → 2.0.2" in body
    # 4 Attention: prowlarr is Down in the media_status fixture
    assert "Prowlarr is Down (timeout)" in body and "All clear" not in body
    # 5 Counts
    assert ">Pending<" in body and ">Seeding<" in body and ">This week<" in body
    # link tiles
    assert 'href="https://homepage.joeyhome.net"' in body and 'href="http://192.168.68.59:9000"' in body
    # band order, top to bottom
    marks = [body.index(m) for m in
             ('id="system"', 'id="services"', 'id="updates"', 'id="attention"', 'id="counts"')]
    assert marks == sorted(marks)


def test_server_page_with_no_snapshots_degrades_band_by_band(env):
    with env(samples=False) as client:
        r = client.get("/server")
    assert r.status_code == 200
    body = main_of(r.text)
    assert body.count("Not connected") >= 6   # system, services, updates, 3 count sources
    assert "All clear" in body


def test_attention_lists_full_volumes_and_unknown_apps_land_in_system(env):
    system = json.loads((SAMPLES / "system.json").read_text(encoding="utf-8"))["data"]
    system["volumes"][0]["pct_used"] = 85
    system["volumes"][1]["pct_used"] = 84
    apps = {"summary": "2 of 2 up", "apps": [
        {"id": "jellyfin", "name": "Jellyfin", "href": "http://h:8096", "up": True,
         "status_text": "Up", "note": None},
        {"id": "mystery", "name": "Mystery App", "href": "http://h:1", "up": True,
         "status_text": "Up", "note": None},
    ]}
    with env(system=system, media_status=apps) as client:
        body = main_of(client.get("/server").text)
    assert "/volume1 is 85% full" in body and "/volume2 is 84% full" not in body
    svc = services_of(body)
    sys_group = svc.split('<div class="head">System</div>', 1)[1].split("</section>", 1)[0]
    assert "Mystery App" in sys_group
    assert '<div class="head">Downloads</div>' not in svc   # empty groups are omitted
    assert "1 needs attention" in body                      # the 85 % volume, nothing else


def test_build_server_adds_the_backup_warning():
    area = load_registry(AREAS_YAML).areas[-1]
    out = server.build_server(area, {}, {"warning": "Media backup: none in 40 hours"})
    assert out["attention"] == ["Media backup: none in 40 hours"]
    assert server.build_server(area, {}, {"warning": None})["attention"] == []


def test_uptime_text_and_grouping_helpers():
    assert server.uptime_text(1052400) == "12 days 4 h"
    assert server.uptime_text(86400) == "1 day 0 h"
    assert server.uptime_text(5 * 3600 + 20 * 60) == "5 h 20 min"
    assert server.uptime_text(40 * 60) == "40 min"
    assert server.uptime_text(None) == "—"
    groups = server.group_services([{"id": "gluetun"}, {"id": "portainer"}, {"id": "jellyseerr"}])
    assert [(g["label"], [a["id"] for a in g["apps"]]) for g in groups] == [
        ("Media", ["jellyseerr"]), ("Downloads", ["gluetun"]), ("System", ["portainer"])]


def test_hub_and_rail_show_the_server_area(env):
    with env() as client:
        html = client.get("/").text
    rail = html.split('aria-label="Areas list"', 1)[1].split("</nav>", 1)[0]
    assert 'href="/a/server"' in rail and "Server</a>" in rail
    assert '<rect x="3.5" y="4" width="17" height="7"' in rail   # server-rack icon
    assert 'href="/a/server"' in main_of(html)                   # hub KPI card


def test_server_route_404s_without_a_server_layout_area(tmp_path, monkeypatch):
    monkeypatch.setenv("AREAS_PATH", str(write_registry(tmp_path, make_area("alpha"))))
    import hub.main
    importlib.reload(hub.main)
    with TestClient(hub.main.app) as client:
        assert client.get("/server").status_code == 404
