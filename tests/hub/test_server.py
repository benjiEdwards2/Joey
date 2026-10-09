"""Server area page (WP-S1, 2026-10-06). Real registry, sample snapshots copied into a
tmp dir; every assertion is made inside <main> (sections once rendered into <title>)."""
import importlib
import json
import re
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


def txt(html):
    """The visible text of a fragment: tags stripped, whitespace collapsed (the " · " joins sit in .sep spans)."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html))


def services_of(body):
    return body.split('id="services"', 1)[1].split('id="updates"', 1)[0]


def test_registry_server_area_is_last_with_the_agreed_tiles():
    area = load_registry(AREAS_YAML).areas[-1]
    assert (area.id, area.name, area.icon, area.layout) == ("server", "Server", "server", "server")
    assert area.rail_section == "areas" and not area.hidden and area.summary_tile == "services"
    tiles = {t.id: t for t in area.tiles}
    assert list(tiles) == ["services", "system", "monitors", "updates", "homepage", "portainer"]  # monitors: WP-S4
    assert (tiles["services"].snapshot, tiles["services"].stale_after_minutes) == ("media_status", 10)
    assert (tiles["system"].snapshot, tiles["system"].stale_after_minutes) == ("system", 10)
    assert (tiles["updates"].snapshot, tiles["updates"].stale_after_minutes) == ("wud", 180)
    assert (tiles["monitors"].snapshot, tiles["monitors"].stale_after_minutes,
            tiles["monitors"].detail, tiles["monitors"].label) == (
        "uptime_kuma", 10, "/server#monitors", "Monitors")
    assert tiles["monitors"].setup_note == "Set UPTIME_KUMA_URL/UPTIME_KUMA_API_KEY in deploy/.env."
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
    assert "/volume1/Docker" in body and "120.0 GB free" in body and "of 465.6 GB" in body and "74% used" in body
    assert "width: 71%" in body
    # 2 Services, grouped, Up/Down as words, whole row links to the app
    svc = services_of(body)
    order = [svc.index(f'<h2 class="seclabel">{h}</h2>') for h in ("Media", "Downloads", "System")]
    assert order == sorted(order)
    assert ">Down</span>" in body and ">Up</span>" in body
    assert 'href="http://nas.local:8096"' in body
    # 3 Updates
    assert "17 monitored · 2 updates" in txt(body) and "uptime-kuma" in body and "1.23.16 → 2.0.2" in body
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
    kuma = {"summary": "1 of 1 up", "up": 1, "down": 0, "total": 1, "monitors": [  # WP-S4: all up
        {"name": "Jellyfin", "type": "http", "status": "up", "response_ms": 30}]}
    with env(system=system, media_status=apps, uptime_kuma=kuma) as client:
        body = main_of(client.get("/server").text)
    assert "/volume1 is 85% full" in body and "/volume2 is 84% full" not in body
    svc = services_of(body)
    sys_group = svc.split('<h2 class="seclabel">System</h2>', 1)[1].split("</section>", 1)[0]
    assert "Mystery App" in sys_group
    assert '<h2 class="seclabel">Downloads</h2>' not in svc   # empty groups are omitted
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


def test_hub_and_shell_show_the_server_area(env):
    with env() as client:
        html = client.get("/").text
    top = html.split('aria-label="Sections"', 1)[1].split("</nav>", 1)[0]
    assert '<a href="/a/server">Server</a>' in top
    tabs = html.split('aria-label="Sections (phone)"', 1)[1]
    assert 'href="/a/server"' in tabs and '<rect x="3.5" y="4" width="17" height="7"' in tabs   # server-rack icon
    assert 'href="/a/server"' in main_of(html)                   # hub KPI card


def test_server_route_404s_without_a_server_layout_area(tmp_path, monkeypatch):
    monkeypatch.setenv("AREAS_PATH", str(write_registry(tmp_path, make_area("alpha"))))
    import hub.main
    importlib.reload(hub.main)
    with TestClient(hub.main.app) as client:
        assert client.get("/server").status_code == 404


# ---- WP-S4 (2026-10-06): Monitors band, monitor + runner attention, Last sweep ------

def write_runner(snaps_dir, ran_at, results=None):
    (snaps_dir / "_runner.json").write_text(json.dumps(
        {"ran_at": ran_at, "results": results or {}}), encoding="utf-8")


def test_monitors_band_sits_between_services_and_updates_and_flags_down(env):
    with env() as client:
        body = main_of(client.get("/server").text)
    marks = [body.index(m) for m in ('id="services"', 'id="monitors"', 'id="updates"')]
    assert marks == sorted(marks)
    band = body.split('id="monitors"', 1)[1].split('id="updates"', 1)[0]
    assert "5 of 6 up" in band
    assert ">Down</span>" in band and ">Prowlarr</div>" in band and "38 ms" in band
    assert 'class="row is-down"' in band                     # a down monitor is a tinted row
    assert band.index("Prowlarr") < band.index("Jellyfin")   # down sorts first
    assert "Uptime Kuma: Prowlarr is Down" in body
    assert 'href="/server#monitors"' in body                 # the KPI tile
    assert "Last sweep" not in body                          # no _runner.json -> omitted


def test_pending_monitor_and_runner_errors_reach_attention_and_last_sweep_shows(env, tmp_path):
    from datetime import datetime, timedelta, timezone
    kuma = {"summary": "0 of 1 up", "up": 0, "down": 0, "total": 1, "monitors": [
        {"name": "Backup", "type": "push", "status": "pending", "response_ms": None}]}
    client = env(uptime_kuma=kuma)
    ran = (datetime.now(timezone.utc) - timedelta(minutes=4)).isoformat()
    write_runner(tmp_path / "snaps", ran, {
        "wud": {"status": "error", "consecutive_failures": 2,
                "error": "RuntimeError: WUD containers failed (HTTP 401)"},
        "gcal": {"status": "error", "consecutive_failures": -1,
                 "error": "runner-level ValueError: http://secret.invalid/x?k=SECRETKEY"},
        "system": {"status": "ok", "consecutive_failures": 0, "error": None}})
    with client:
        body = main_of(client.get("/server").text)
    assert "Uptime Kuma: Backup is Pending" in body and ">Pending</span>" in body
    assert "wud sweep failed: WUD containers failed (HTTP 401)" in body
    assert "gcal sweep failed: runner-level ValueError" in body and "SECRETKEY" not in body
    assert "system sweep failed" not in body
    sweep = body.split("Last sweep", 1)[1].split("</div></div>", 1)[0]
    assert "4 min ago" in sweep and "Stale" not in sweep


def test_old_sweep_reads_stale_and_bad_runner_files_never_500(env, tmp_path):
    client = env()
    write_runner(tmp_path / "snaps", "2026-01-01T00:00:00+00:00")
    with client:
        sweep = main_of(client.get("/server").text).split("Last sweep", 1)[1].split("</div></div>", 1)[0]
        assert "days ago" in sweep and "Stale" in sweep
        for junk in ("{not json", "[]", '{"ran_at": "yesterday", "results": "nope"}'):
            (tmp_path / "snaps" / "_runner.json").write_text(junk, encoding="utf-8")
            r = client.get("/server")
            assert r.status_code == 200 and "Last sweep" not in main_of(r.text)


def test_sweep_and_ago_helpers():
    from datetime import datetime, timezone
    now = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)
    assert server.last_sweep({"ran_at": "2026-10-06T11:56:00+00:00"}, now) == {
        "text": "4 min ago", "stale": False}
    assert server.last_sweep({"ran_at": "2026-10-06T10:30:00Z"}, now) == {"text": "1 h ago", "stale": False}
    assert server.last_sweep({"ran_at": "2026-10-06T10:29:00Z"}, now)["stale"] is True
    assert server.last_sweep({}, now) is None
    assert server.ago_text(0.5) == "just now" and server.ago_text(60 * 50) == "2 days ago"
    assert server.runner_errors(None) == [] and server.runner_errors({"results": []}) == []


def test_monitors_band_degrades_to_not_connected(env):
    with env(samples=False) as client:
        body = main_of(client.get("/server").text)
    band = body.split('id="monitors"', 1)[1].split('id="updates"', 1)[0]
    assert "Not connected" in band and "UPTIME_KUMA_URL" in band


# ---- WP-U2 (2026-10-06): hub card words, durable sweep errors, Sweeps (24 h) -------

from datetime import datetime, timedelta, timezone  # noqa: E402

from hub.store import get_snapshots  # noqa: E402
from tests.hub.test_store import write_history  # noqa: E402

ALL_UP = {"summary": "2 of 2 up", "apps": [
    {"id": "jellyfin", "name": "Jellyfin", "up": True}, {"id": "radarr", "name": "Radarr", "up": True}]}
TWO_DOWN = {"summary": "1 of 3 up", "apps": [
    {"id": "jellyfin", "name": "Jellyfin", "up": True}, {"id": "prowlarr", "name": "Prowlarr", "up": False},
    {"id": "sonarr", "name": "Sonarr", "up": False}]}
WUD = {"summary": "2 updates", "containers": [
    {"name": "a", "update_available": True, "current_tag": "1", "new_tag": "2"},
    {"name": "b", "update_available": True, "current_tag": "3", "new_tag": "4"},
    {"name": "c", "update_available": False, "current_tag": "5"}]}
SYSTEM = {"volumes": [{"path": "/volume1", "pct_used": 71, "free_gb": 10, "total_gb": 40},
                      {"path": "/volume2", "pct_used": 74, "free_gb": 10, "total_gb": 40}]}
KUMA = {"monitors": [{"name": "Prowlarr", "status": "down"}, {"name": "Radarr", "status": "down"},
                     {"name": "Jellyfin", "status": "up"}]}


def _snaps(tmp_path, **data):
    d = tmp_path / "card"
    for cid, payload in data.items():
        write_envelope(d, cid, age_minutes=1, data=payload)
    return get_snapshots(d)


def test_hub_card_all_up_is_ok_with_disk(tmp_path):
    card = server.hub_card(_snaps(tmp_path, media_status=ALL_UP, system=SYSTEM), set(), {"warning": None})
    assert card == {"summary": "All up", "secondary": "disk 74%", "state": "ok"}


def test_hub_card_down_updates_excluding_ignored_monitors_and_warn(tmp_path):
    snaps = _snaps(tmp_path, media_status=TWO_DOWN, wud=WUD, system=SYSTEM, uptime_kuma=KUMA)
    card = server.hub_card(snaps, {("a", "2")}, {"warning": None})
    assert card["summary"] == "2 down: Prowlarr, Sonarr"
    assert card["secondary"] == "1 update · disk 74% · 2 monitors down"
    assert card["state"] == "warn"
    assert server.hub_card(snaps, set(), {"warning": None})["secondary"].startswith("2 updates · ")


def test_hub_card_warns_on_any_attention_and_degrades(tmp_path):
    snaps = _snaps(tmp_path, media_status=ALL_UP)
    assert server.hub_card(snaps, set(), {"warning": "Media backup: none yet"})["state"] == "warn"
    assert server.hub_card(snaps, set(), {"warning": None}) == {
        "summary": "All up", "secondary": None, "state": "ok"}
    assert server.hub_card({}, set(), {"warning": None})["summary"] == "Not connected"


def test_hub_server_card_shows_the_words_and_needs_attention(env):
    with env() as client:
        body = main_of(client.get("/").text)
    card = body.split('href="/a/server"', 1)[1].split("</a>", 1)[0]
    assert "1 down: Prowlarr" in card and "2 updates · disk 74% · 1 monitor down" in card
    assert '<span class="badge badge-wait">Needs attention</span>' in card   # amber: something to do
    assert "12 of 12 up" not in card and "11 of 12 up" not in card


def test_hub_server_card_is_ok_when_nothing_needs_attention(env):
    with env(samples=False, media_status=ALL_UP, system=SYSTEM) as client:
        card = main_of(client.get("/").text).split('href="/a/server"', 1)[1].split("</a>", 1)[0]
    assert "All up" in card and "disk 74%" in card and "Needs attention" not in card


BAD_SYSTEM = {"summary": "x", "cpu_pct": "busy", "load_1m": "high", "ram_pct_used": "most", "uptime_s": "long",
              "volumes": [{"path": "/volume1", "pct_used": "full", "free_gb": "?", "total_gb": None},
                          {"path": "/volume2", "pct_used": float("nan")}, "not a volume"]}


def test_malformed_system_envelope_never_500s_hub_or_server(env):
    """H-63: non-numeric values degrade to words; the hub's Server card never takes `/` down."""
    with env(samples=False, media_status=ALL_UP, system=BAD_SYSTEM) as client:
        hub, page = client.get("/"), client.get("/server")
    assert hub.status_code == 200 and page.status_code == 200
    assert "All up" in main_of(hub.text).split('href="/a/server"', 1)[1].split("</a>", 1)[0]
    assert "Load " not in txt(main_of(page.text)).split("Last 24 h")[0]


def test_hub_page_survives_a_hub_card_crash(env, monkeypatch):
    with env(samples=False, media_status=ALL_UP, system=SYSTEM) as client:
        import hub.main
        monkeypatch.setattr(hub.main.server_area, "hub_card", lambda *a, **k: 1 / 0)
        r = client.get("/")
    assert r.status_code == 200 and 'href="/a/server"' in r.text


def test_num_coerces_envelope_values():
    assert [server._num(v) for v in (3, 2.5, "4.5", True, None, "x", float("inf"))] == [3.0, 2.5, 4.5, None, None,
                                                                                         None, None]


NOW = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)


def _line(minutes_ago, results):
    return {"ran_at": (NOW - timedelta(minutes=minutes_ago)).isoformat(), "results": {
        cid: {"status": s, "error": e} for cid, (s, e) in results.items()}}


def test_sweep_stats_window_recovered_and_still_failing():
    err = ("error", "RuntimeError: WUD containers failed (HTTP 401)")
    ok = ("ok", None)
    history = [_line(25 * 60, {"wud": err, "arr": err}),            # outside the 24 h window
               _line(180, {"wud": err, "arr": err}), _line(120, {"wud": ok, "arr": err}),
               _line(60, {"wud": err, "arr": ok}), "junk", {"ran_at": "nope", "results": {}},
               {"ran_at": NOW.isoformat(), "results": "bad"}]
    stats = server.sweep_stats(history, NOW)
    assert stats["wud"] == {"runs": 3, "failures": 2, "failing": True,
                            "reason": "WUD containers failed (HTTP 401)",
                            "last_ok": NOW - timedelta(minutes=120)}
    assert stats["arr"]["failing"] is False and stats["arr"]["failures"] == 2
    items = server.attention_items({}, {"warning": None}, None, stats)
    assert items == [{"key": "sweep:wud",
                      "text": "wud failed 2 of the last 3 sweeps · WUD containers failed (HTTP 401)"}]
    rows = server.sweep_rows(stats, NOW)
    assert [(r["id"], r["runs"], r["failures"], r["last_ok_text"]) for r in rows] == [
        ("arr", 3, 2, "1 h ago"), ("wud", 3, 2, "2 h ago")]
    assert server.sweep_stats(None) is None and server.sweep_stats(["junk"]) is None


def test_history_drives_attention_and_sweeps_table_with_runner_fallback(env, tmp_path):
    client = env()
    snaps = tmp_path / "snaps"
    write_runner(snaps, datetime.now(timezone.utc).isoformat(), {
        "wud": {"status": "ok", "consecutive_failures": 0, "error": None}})   # fast sweep overwrote it
    write_history(snaps, [(90, {"wud": ("error", "RuntimeError: WUD containers failed (HTTP 401)"),
                                "system": "ok"}),
                          (30, {"wud": ("error", "RuntimeError: WUD containers failed (HTTP 401)"),
                                "gcal": ("error", "runner-level ValueError: http://x.invalid/?k=SECRETKEY")}),
                          (2, {"system": "ok", "gcal": "ok"})], junk=["{broken"])
    with client:
        body = main_of(client.get("/server").text)
    att = body.split('id="attention"', 1)[1].split('id="sweeps"', 1)[0]
    assert "wud failed 2 of the last 2 sweeps · WUD containers failed (HTTP 401)" in att
    assert "gcal" not in att and "SECRETKEY" not in body                     # recovered -> table only
    sweeps = body.split('id="sweeps"', 1)[1].split("</section>", 1)[0]
    assert "Sweeps · 24 h" in body and ">gcal</div>" in sweeps and "2 runs · 1 failed" in txt(sweeps)
    assert ">system</div>" in sweeps and ">wud</div>" in sweeps and "last ok none in 24 h" in txt(sweeps)
    (snaps / "_runner_history.jsonl").write_text("{junk\n[]\n", encoding="utf-8")
    with client:
        r = client.get("/server")
    assert r.status_code == 200 and 'id="sweeps"' not in main_of(r.text)   # no usable history
