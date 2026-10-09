"""Server → Last 24 h history (WP-U4, 2026-10-06): sampler into media.db and the sparkline band."""
import importlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from hub import media_db, server, server_history
from hub.store import get_snapshots
from tests.hub.helpers import write_envelope

SYS = {"summary": "CPU 16%", "cpu_pct": 16.2, "load_1m": 0.42, "ram_free_gb": 1.9, "ram_pct_used": 75,
       "ram_total_gb": 7.7, "uptime_s": 100,
       "volumes": [{"path": "/volume1", "total_gb": 1000.0, "free_gb": 900.0, "pct_used": 10},
                   {"path": "/volume1/Docker", "total_gb": 400.0, "free_gb": 100.0, "pct_used": 75}]}


def _rows():
    with sqlite3.connect(media_db.db_path()) as db:
        return db.execute("SELECT ts, cpu_pct, ram_pct_used, volumes FROM server_system_samples "
                          "ORDER BY ts").fetchall()


def _write(snaps, age_minutes=1, status="ok", data=SYS):
    write_envelope(snaps, "system", age_minutes=age_minutes, data=data, status=status)


def test_sampler_inserts_once_per_new_updated_at(tmp_path):
    snaps = tmp_path / "snaps"
    _write(snaps, age_minutes=4)
    assert server_history.sample(get_snapshots(snaps)) is True
    assert server_history.sample(get_snapshots(snaps)) is False  # same updated_at: no duplicate
    rows = _rows()
    assert len(rows) == 1 and rows[0][1] == 16.2 and rows[0][2] == 75 and rows[0][0].endswith("Z")
    vols = json.loads(rows[0][3])
    assert vols[1] == {"path": "/volume1/Docker", "pct_used": 75.0, "free_gb": 100.0}
    _write(snaps, age_minutes=2)  # the next 2-min snapshot
    assert server_history.sample(get_snapshots(snaps)) is True
    assert len(_rows()) == 2


def test_sampler_skips_error_and_missing_snapshots(tmp_path):
    snaps = tmp_path / "snaps"
    assert server_history.sample(get_snapshots(snaps)) is False
    _write(snaps, status="error")
    assert server_history.sample(get_snapshots(snaps)) is False
    assert not media_db.db_path().exists()


def test_sampler_prunes_rows_older_than_8_days(tmp_path):
    snaps = tmp_path / "snaps"
    _write(snaps, age_minutes=9 * 1440)
    assert server_history.sample(get_snapshots(snaps)) is True
    _write(snaps, age_minutes=7 * 1440)
    assert server_history.sample(get_snapshots(snaps)) is True
    assert len(_rows()) == 2  # 9 d is only 2 d older than the newest
    _write(snaps, age_minutes=1)
    assert server_history.sample(get_snapshots(snaps)) is True
    assert len(_rows()) == 2  # the 9-day row went


def test_recent_without_media_db_is_empty_and_creates_nothing():
    assert server_history.recent() == [] and not media_db.db_path().exists()


NOW = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)


def _samples(disk, hours_back, cpu=(4, 38, 15), ram=(70, 75, 72)):
    """One sample per entry of `hours_back`; disk(i) gives /volume1 pct for sample i."""
    out = []
    n = len(hours_back)
    for i, h in enumerate(hours_back):
        out.append({"at": NOW - timedelta(hours=h), "cpu_pct": cpu[i % len(cpu)] if i < n - 1 else cpu[-1],
                    "ram_pct_used": ram[i % len(ram)] if i < n - 1 else ram[-1], "ram_free_gb": 2.0,
                    "load_1m": 0.5, "volumes": [{"path": "/volume1", "pct_used": disk(i), "free_gb": 1.0},
                                                {"path": "/volume2", "pct_used": 1.0, "free_gb": 9.0}]})
    return out


def test_history_band_rising_disk_projects_days_to_85():
    hours = [168, 120, 72, 23, 12, 0]
    band = server.history_band(_samples(lambda i: [8.0, 8.1, 8.2, 8.3, 8.35, 8.4][i], hours), NOW)
    assert not band["collecting"]
    texts = [s["text"] for s in band["sparks"]]
    assert texts == ["CPU 4–38 %, now 15 %", "RAM 70–75 %, now 72 %", "Disk /volume1 8.3–8.4 %, now 8.4 %"]
    assert band["trend"].startswith("Disk: 8.0 % → 8.4 % over 7 days · ~")
    assert band["trend"].endswith("days to 85 % at this rate")


def test_history_band_flat_disk_reads_flat():
    band = server.history_band(_samples(lambda i: 8.0, [168, 72, 10, 0]), NOW)
    assert band["trend"] == "Disk: 8.0 % → 8.0 % over 7 days · flat"


def test_history_band_under_two_samples_is_collecting():
    band = server.history_band(_samples(lambda i: 8.0, [48, 1]), NOW)  # only one inside 24 h
    assert band["collecting"] and band["text"] == server.COLLECTING
    assert server.history_band([], NOW)["collecting"]


@pytest.fixture()
def client_for(tmp_path, monkeypatch):
    monkeypatch.delenv("AREAS_PATH", raising=False)
    snaps = tmp_path / "snaps"
    snaps.mkdir()
    monkeypatch.setenv("SNAPSHOT_DIR", str(snaps))

    def build():
        import hub.main
        importlib.reload(hub.main)
        return TestClient(hub.main.app)
    return snaps, build


def _seed(rows):
    with sqlite3.connect(media_db.db_path()) as db:
        db.execute(server_history.DDL)
        db.executemany("INSERT INTO server_system_samples VALUES(?,?,?,?,?,?)", rows)


def _ts(minutes_ago):
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_page_renders_three_sparklines_with_text(client_for):
    snaps, build = client_for
    _write(snaps)
    vols = lambda p: json.dumps([{"path": "/volume1", "pct_used": p, "free_gb": 1.0}])
    _seed([(_ts(20 * 60), 4.0, 70, 2.0, 0.1, vols(8.0)),
           (_ts(10 * 60), 38.0, 75, 2.0, 0.1, vols(8.2)),
           (_ts(30), 15.0, 72, 2.0, 0.1, vols(8.4))])
    with build() as client:
        r = client.get("/server")
    assert r.status_code == 200
    body = r.text.split("<main", 1)[1]
    band = body.split('id="history"', 1)[1].split("</section>", 1)[0]
    assert band.count('<svg class="spark-svg"') == 3 and band.count("<polyline") == 3
    assert "<script" not in band
    assert "CPU 4–38 %, now 15 %" in band and "RAM 70–75 %, now 72 %" in band
    assert "Disk /volume1 8.0–8.4 %, now 8.4 %" in band
    assert "projection after 24 h of history" in band  # 20 h of history only
    # the band sits right after System
    assert body.index('id="system"') < body.index('id="history"') < body.index('id="services"')


def test_page_collecting_with_fewer_than_two_samples(client_for):
    snaps, build = client_for
    _write(snaps)
    with build() as client:
        r = client.get("/server")
        assert r.status_code == 200
        assert "Collecting history · first chart after a few sweeps" in r.text.split("<main", 1)[1]
    assert len(_rows()) == 1  # the render's background task sampled the snapshot


def test_page_without_media_db_or_system_snapshot_never_500s(client_for):
    _, build = client_for
    with build() as client:
        r = client.get("/server")
    assert r.status_code == 200
    assert "Collecting history" in r.text.split("<main", 1)[1]
    assert not media_db.db_path().exists()  # no system snapshot: nothing sampled, nothing created
