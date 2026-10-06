"""WP-S2 (2026-10-06): the live `system` fetch — /proc + statvfs, no secrets.
Every read is monkeypatched with fixture text, so this runs anywhere (incl. Windows)."""

import json
from pathlib import Path
from types import SimpleNamespace

import jsonschema
import pytest

from connectors import stubs
from connectors.stubs import System

SCHEMA = json.loads((Path(__file__).resolve().parents[2] / "connectors" / "schema" / "data"
                     / "system.schema.json").read_text(encoding="utf-8"))

# user nice system idle iowait irq softirq steal guest guest_nice
STAT_1 = "cpu  1000 0 500 8000 500 0 0 0 0 0\ncpu0 1000 0 500 8000 500 0 0 0 0 0\nintr 1\n"
STAT_2 = "cpu  1300 0 600 8500 600 0 0 0 0 0\ncpu0 1300 0 600 8500 600 0 0 0 0 0\nintr 2\n"
MEMINFO = "MemTotal:        8073296 kB\nMemFree:          512000 kB\nMemAvailable:    1992294 kB\n"
UPTIME = "1052400.57 4100000.00\n"
LOADAVG = "0.42 0.38 0.30 1/412 12345\n"
GIB = 1024 ** 3


@pytest.fixture()
def proc(monkeypatch):
    """Fake /proc: stat answers STAT_1 then STAT_2; statvfs 1 TiB with 256 GiB available."""
    stats = iter([STAT_1, STAT_2])
    files = {"meminfo": MEMINFO, "uptime": UPTIME, "loadavg": LOADAVG}
    monkeypatch.setattr(stubs, "_read_proc", lambda name: next(stats) if name == "stat" else files[name])
    monkeypatch.setattr(stubs, "CPU_SAMPLE_S", 0)
    statted = []

    def statvfs(path):
        statted.append(path)
        return SimpleNamespace(f_frsize=4096, f_blocks=1024 * GIB // 4096, f_bavail=256 * GIB // 4096)

    monkeypatch.setattr(stubs.os, "statvfs", statvfs, raising=False)
    monkeypatch.delenv("SYSTEM_VOLUMES", raising=False)
    return statted


def test_needs_no_env():
    assert System.requires_env == ()


def test_cpu_is_the_delta_between_two_samples(proc):
    # deltas: user +300, system +100, idle +500, iowait +100 -> total 1000, idle 600 -> 40 % busy
    assert System().fetch()["cpu_pct"] == 40.0


def test_cpu_math_ignores_cumulative_totals():
    assert stubs._cpu_times(STAT_1) == (8500, 10000)
    assert stubs._cpu_times(STAT_2) == (9100, 11000)


def test_raw_shape_matches_the_fixture_contract(proc):
    raw = System().fetch()
    fixture = json.loads((System().fixture_dir / "raw.json").read_text(encoding="utf-8"))
    assert set(raw) == set(fixture)
    assert raw["mem_total_bytes"] == 8073296 * 1024 and raw["mem_available_bytes"] == 1992294 * 1024
    assert raw["uptime_s"] == 1052400 and raw["load_1m"] == 0.42
    assert raw["volumes"] == [{"path": "/volume1", "total_bytes": 1024 * GIB, "free_bytes": 256 * GIB}]
    assert proc == ["/host/volume1"]  # the default SYSTEM_VOLUMES
    data = System().transform(raw)
    jsonschema.validate(data, SCHEMA)
    assert data["summary"] == "CPU 40% · 1.9 GB RAM free"
    assert data["secondary"] == "Up 12 days · /volume1 75% used"


def test_volume_paths_strip_the_host_prefix(proc, monkeypatch):
    monkeypatch.setenv("SYSTEM_VOLUMES", "/host/volume1, /host/volume2/Docker ,/data/snapshots,/host")
    raw = System().fetch()
    assert proc == ["/host/volume1", "/host/volume2/Docker", "/data/snapshots", "/host"]
    assert [v["path"] for v in raw["volumes"]] == ["/volume1", "/volume2/Docker", "/data/snapshots", "/"]
    assert stubs._volume_label("/hostile/x") == "/hostile/x"  # only a whole /host segment is stripped


def test_missing_loadavg_is_null_not_a_failure(proc, monkeypatch):
    real = stubs._read_proc

    def no_load(name):
        if name == "loadavg":
            raise RuntimeError("cannot read /proc/loadavg (FileNotFoundError)")
        return real(name)

    monkeypatch.setattr(stubs, "_read_proc", no_load)
    assert System().fetch()["load_1m"] is None


def test_unreadable_proc_is_an_error_envelope_never_numbers(snapshots, monkeypatch, tmp_path):
    monkeypatch.setenv("CONNECTOR_MODE", "live")
    monkeypatch.setattr(stubs, "PROC_ROOT", tmp_path / "no-proc")
    env = System().run()
    assert env["status"] == "error" and env["data"] == {}
    assert env["error"] == "RuntimeError: cannot read /proc/stat (FileNotFoundError)"


def test_unstattable_volume_is_an_error_naming_the_path(proc, monkeypatch):
    def boom(path):
        raise FileNotFoundError(path)

    monkeypatch.setattr(stubs.os, "statvfs", boom, raising=False)
    with pytest.raises(RuntimeError, match=r"cannot stat volume /host/volume1 \(FileNotFoundError\)"):
        System().fetch()
