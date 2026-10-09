"""NAS host health from /proc and statvfs (Server area). No secrets, so no requires_env."""

from __future__ import annotations

import os
from pathlib import Path

from connectors.base import Connector
from connectors.feeds._common import GIB, _duration_words


# Server area (2026-10-06, WP-S1): host health of the NAS itself. Raw shape (fixture
# and live `fetch()`, WP-S2):
# {cpu_pct, mem_total_bytes, mem_available_bytes, uptime_s, load_1m|null,
#  volumes: [{path, total_bytes, free_bytes}]}. Sizes are binary GiB, shown as "GB".
# Live: runs inside joey-connectors on the NAS. /proc/{stat,meminfo,uptime,loadavg} are
# host-wide from a container by default; volumes are os.statvfs on each container path
# in SYSTEM_VOLUMES (set in deploy/docker-compose.yml, bind `/volume1:/host/volume1:ro`),
# reported with the `/host` prefix stripped — or under its SYSTEM_VOLUME_LABELS name
# (2026-10-09). No secrets, so no requires_env.

PROC_ROOT = Path("/proc")
CPU_SAMPLE_S = 1.0  # gap between the two /proc/stat reads
SYSTEM_VOLUMES_DEFAULT = "/host/volume1"
HOST_PREFIX = "/host"


def _read_proc(name: str) -> str:
    try:
        return (PROC_ROOT / name).read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"cannot read /proc/{name} ({type(exc).__name__})") from None


def _cpu_times(stat_text: str) -> tuple[int, int]:
    """(idle, total) jiffies from /proc/stat's aggregate `cpu` line. idle includes
    iowait; total is user..steal (guest time is already inside user/nice)."""
    for line in stat_text.splitlines():
        parts = line.split()
        if parts and parts[0] == "cpu":
            values = [int(v) for v in parts[1:9]]
            idle = values[3] + (values[4] if len(values) > 4 else 0)
            return idle, sum(values)
    raise RuntimeError("no cpu line in /proc/stat")


def _volume_label(path: str) -> str:
    """'/host/volume1' -> '/volume1' — the path as the NAS itself names it."""
    if path == HOST_PREFIX:
        return "/"
    return path[len(HOST_PREFIX):] if path.startswith(HOST_PREFIX + "/") else path


def _volume_labels() -> dict[str, str]:
    """SYSTEM_VOLUME_LABELS `path=label[,path=label]` -> {path: label} (C-19): the name a
    volume is shown under, e.g. `/data/snapshots=/volume1` (statvfs reports the whole
    filesystem, so a small bind on the volume replaces mounting the volume itself).
    Pairs without both a path and a label are ignored."""
    labels = {}
    for pair in (os.environ.get("SYSTEM_VOLUME_LABELS") or "").split(","):
        path, sep, label = pair.partition("=")
        if sep and path.strip() and label.strip():
            labels[path.strip()] = label.strip()
    return labels


def _gib(n) -> float:
    return round(float(n or 0) / GIB, 1)


def _uptime_words(seconds) -> str:
    """'12d 4h' / '5h 20m' / '40m' — the NAS uptime, in the one duration format."""
    return _duration_words(max(0, int(seconds or 0)) // 60)


class System(Connector):
    """NAS host health: CPU, RAM, uptime and per-volume space (Server area)."""

    id = "system"

    def fetch(self) -> dict:
        import time

        idle1, total1 = _cpu_times(_read_proc("stat"))
        time.sleep(CPU_SAMPLE_S)
        idle2, total2 = _cpu_times(_read_proc("stat"))
        dt = total2 - total1
        cpu = 0.0 if dt <= 0 else min(100.0, max(0.0, (dt - (idle2 - idle1)) / dt * 100))

        mem = {}
        for line in _read_proc("meminfo").splitlines():
            key, _, rest = line.partition(":")
            fields = rest.split()
            if fields:
                mem[key.strip()] = int(fields[0]) * (1024 if fields[1:] == ["kB"] else 1)
        if "MemTotal" not in mem or "MemAvailable" not in mem:
            raise RuntimeError("/proc/meminfo has no MemTotal/MemAvailable")

        uptime = float(_read_proc("uptime").split()[0])
        try:
            load = float(_read_proc("loadavg").split()[0])
        except (RuntimeError, IndexError, ValueError):
            load = None  # load is optional in the raw shape

        volumes = []
        spec = os.environ.get("SYSTEM_VOLUMES") or SYSTEM_VOLUMES_DEFAULT
        labels = _volume_labels()
        for path in (p.strip() for p in spec.split(",")):
            if not path:
                continue
            try:
                st = os.statvfs(path)
            except (OSError, AttributeError) as exc:  # AttributeError: no statvfs (Windows)
                raise RuntimeError(f"cannot stat volume {path} ({type(exc).__name__})") from None
            volumes.append({"path": labels.get(path) or _volume_label(path),
                            "total_bytes": st.f_blocks * st.f_frsize,
                            "free_bytes": st.f_bavail * st.f_frsize})

        return {"cpu_pct": round(cpu, 1), "mem_total_bytes": mem["MemTotal"],
                "mem_available_bytes": mem["MemAvailable"], "uptime_s": int(uptime),
                "load_1m": load, "volumes": volumes}

    def transform(self, raw: dict) -> dict:
        total, free = _gib(raw.get("mem_total_bytes")), _gib(raw.get("mem_available_bytes"))
        ram_pct = round((1 - free / total) * 100) if total else 0
        volumes = []
        for v in raw.get("volumes") or []:
            vt, vf = _gib(v.get("total_bytes")), _gib(v.get("free_bytes"))
            volumes.append({
                "path": str(v.get("path") or "?"),
                "total_gb": vt,
                "free_gb": vf,
                "pct_used": min(100, max(0, round((1 - vf / vt) * 100))) if vt else 0,
            })
        cpu = round(float(raw.get("cpu_pct") or 0), 1)
        load = raw.get("load_1m")
        fullest = max(volumes, key=lambda v: v["pct_used"], default=None)
        secondary = f"Up {_uptime_words(raw.get('uptime_s'))}"
        if fullest:
            secondary += f" · {fullest['path']} {fullest['pct_used']}% used"
        return {
            "summary": f"CPU {cpu:.0f}% · {free:.1f} GB RAM free",
            "secondary": secondary,
            "cpu_pct": cpu,
            "ram_total_gb": total,
            "ram_free_gb": free,
            "ram_pct_used": min(100, max(0, ram_pct)),
            "uptime_s": max(0, int(raw.get("uptime_s") or 0)),
            "volumes": volumes,
            "load_1m": None if load is None else round(float(load), 2),
        }
