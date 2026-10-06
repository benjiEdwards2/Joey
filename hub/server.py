"""Server area page (WP-S1, 2026-10-06): the NAS "Homepage" dashboard, natively.

Pure: registry area + snapshots + backup status in, one dict of bands out. Every band
degrades on its own — a missing snapshot is that band's "Not connected", never a 500.
Keyed by connector ids and the area's `layout: server`, never by area name.
Thresholds (B., 2026-10-06): disk >= 85 % used, media.db backup older than 36 h
(hub/media_backup.py's own STALE_AFTER), any service Down.
WP-S4 (2026-10-06): Uptime Kuma monitors down/pending, connectors whose last sweep
errored (`_runner.json`), and a "Last sweep" line (stale past 90 min) in System.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from hub.store import tile_state

SERVER_LAYOUT = "server"

SYSTEM_SNAPSHOT_ID = "system"
WUD_SNAPSHOT_ID = "wud"
MEDIA_STATUS_SNAPSHOT_ID = "media_status"
JELLYSEERR_SNAPSHOT_ID = "jellyseerr"
QBIT_SNAPSHOT_ID = "qbittorrent"
ARR_SNAPSHOT_ID = "arr"
UPTIME_KUMA_SNAPSHOT_ID = "uptime_kuma"

SWEEP_STALE_MINUTES = 90
_URL_RE = re.compile(r"https?://\S+")

DISK_ATTENTION_PCT = 85

# Services grouping by app id; anything not listed (incl. unknown ids) lands in System.
SERVICE_GROUPS = (
    ("Media", {"jellyfin", "jellyseerr"}),
    ("Downloads", {"radarr", "sonarr", "prowlarr", "qbittorrent", "gluetun"}),
)
OTHER_GROUP = "System"


def uptime_text(seconds) -> str:
    """'12 days 4 h' / '5 h 20 min' / '40 min'."""
    try:
        seconds = max(0, int(seconds))
    except (TypeError, ValueError):
        return "—"
    days, rest = divmod(seconds, 86400)
    hours, minutes = rest // 3600, (rest % 3600) // 60
    if days:
        return f"{days} day{'' if days == 1 else 's'} {hours} h"
    return f"{hours} h {minutes:02d} min" if hours else f"{minutes} min"


def _gb(n) -> str:
    try:
        return f"{float(n):,.1f} GB"
    except (TypeError, ValueError):
        return "—"


def ago_text(minutes: float) -> str:
    """'just now' / '4 min ago' / '2 h ago' / '3 days ago'."""
    minutes = max(0, int(minutes))
    if minutes < 1:
        return "just now"
    if minutes < 60:
        return f"{minutes} min ago"
    if minutes < 48 * 60:
        return f"{minutes // 60} h ago"
    return f"{minutes // 1440} days ago"


def last_sweep(runner, now: datetime | None = None) -> dict | None:
    """{text, stale} from `_runner.json` `ran_at`; None when absent or unreadable."""
    try:
        ran = datetime.fromisoformat(str(runner["ran_at"]).replace("Z", "+00:00"))
        if ran.tzinfo is None:
            ran = ran.replace(tzinfo=timezone.utc)
    except Exception:
        return None
    minutes = ((now or datetime.now(timezone.utc)) - ran).total_seconds() / 60.0
    return {"text": ago_text(minutes), "stale": minutes > SWEEP_STALE_MINUTES}


def runner_errors(runner) -> list[str]:
    """'<id> sweep failed: <reason>' per connector whose last result errored. Connector
    errors are sanitised at source; runner-level ones keep the exception type only and
    any URL is masked as a last guard."""
    results = (runner or {}).get("results") if isinstance(runner, dict) else None
    if not isinstance(results, dict):
        return []
    out = []
    for cid, res in sorted(results.items()):
        if not isinstance(res, dict) or res.get("status") != "error":
            continue
        reason = str(res.get("error") or "unknown error")
        if reason.startswith("runner-level "):
            reason = reason.split(":", 1)[0]
        reason = _URL_RE.sub("[url]", reason.removeprefix("RuntimeError: "))
        out.append(f"{cid} sweep failed: {reason}")
    return out


def _tile(area, snapshot_id):
    return next((t for t in area.tiles if t.snapshot == snapshot_id), None)


def _band(area, snaps, snapshot_id) -> dict:
    """{tile, st, data} for the area tile reading `snapshot_id`; data is {} when off."""
    tile = _tile(area, snapshot_id)
    st = tile_state(tile, snaps) if tile else {"state": "off", "note": None}
    snap = snaps.get(snapshot_id)
    return {"tile": tile, "st": st, "data": (snap.data or {}) if snap and st["state"] != "off" else {}}


def group_services(apps: list[dict]) -> list[dict]:
    groups = [{"label": label, "apps": [a for a in apps if a.get("id") in ids]}
              for label, ids in SERVICE_GROUPS]
    known = set().union(*(ids for _, ids in SERVICE_GROUPS))
    groups.append({"label": OTHER_GROUP, "apps": [a for a in apps if a.get("id") not in known]})
    return [g for g in groups if g["apps"]]


def _counts(snaps) -> dict:
    """Jellyseerr / qBittorrent / arr counts. None per source when absent; the arr
    library/indexer objects (`radarr`, `sonarr`, `prowlarr`, WP-S3) are None when the
    snapshot predates them or the connector nulled them (partial-ok)."""
    def data(cid):
        snap = snaps.get(cid)
        return snap.data if snap and snap.data else None

    seerr, qb, arr = data(JELLYSEERR_SNAPSHOT_ID), data(QBIT_SNAPSHOT_ID), data(ARR_SNAPSHOT_ID)
    totals = (qb or {}).get("totals") or {}
    return {
        "requests": (seerr or {}).get("counts") if seerr else None,
        "torrents": {
            "downloading": len(qb.get("active") or []),
            "seeding": qb.get("seeding", 0),
            "dl_text": totals.get("dl_text", "0 B/s"),
            "up_text": totals.get("up_text", "0 B/s"),
        } if qb else None,
        "arr": {
            "downloading": len(arr.get("downloading") or []),
            "this_week": len(arr.get("this_week") or []),
            "disk": [{**d, "free_text": _gb(d.get("free_gb")), "total_text": _gb(d.get("total_gb"))}
                     for d in arr.get("disk") or []],
        } if arr else None,
        "radarr": (arr or {}).get("radarr") or None,
        "sonarr": (arr or {}).get("sonarr") or None,
        "prowlarr": (arr or {}).get("prowlarr") or None,
    }


def build_server(area, snaps, backup: dict, runner: dict | None = None) -> dict:
    system = _band(area, snaps, SYSTEM_SNAPSHOT_ID)
    services = _band(area, snaps, MEDIA_STATUS_SNAPSHOT_ID)
    monitors = _band(area, snaps, UPTIME_KUMA_SNAPSHOT_ID)
    updates = _band(area, snaps, WUD_SNAPSHOT_ID)

    sd = system["data"]
    volumes = [{**v, "free_text": _gb(v.get("free_gb")), "total_text": _gb(v.get("total_gb"))}
               for v in sd.get("volumes") or []]
    system.update(
        cpu_text=f"{float(sd['cpu_pct']):.0f}%" if sd.get("cpu_pct") is not None else "—",
        load_text=f"Load {sd['load_1m']:.2f}" if sd.get("load_1m") is not None else "",
        ram_text=_gb(sd.get("ram_free_gb")) + " free" if sd.get("ram_free_gb") is not None else "—",
        ram_sub=(f"of {_gb(sd.get('ram_total_gb'))} · {sd.get('ram_pct_used', 0)}% used"
                 if sd.get("ram_total_gb") is not None else ""),
        uptime_text=uptime_text(sd.get("uptime_s")) if sd.get("uptime_s") is not None else "—",
        volumes=volumes,
        last_sweep=last_sweep(runner) if runner else None,
    )

    apps = services["data"].get("apps") or []
    services["groups"] = group_services(apps)

    monitors["rows"] = [m for m in monitors["data"].get("monitors") or [] if isinstance(m, dict)]

    ud = updates["data"]
    updates["pending"] = [c for c in ud.get("containers") or [] if c.get("update_available")]

    attention: list[str] = []
    for a in apps:
        if not a.get("up"):
            attention.append(f"{a.get('name', a.get('id', '?'))} is Down"
                             + (f" ({a['note']})" if a.get("note") else ""))
    for v in volumes:
        if int(v.get("pct_used") or 0) >= DISK_ATTENTION_PCT:
            attention.append(f"{v.get('path', '?')} is {v['pct_used']}% full ({v['free_text']} free)")
    for m in monitors["rows"]:
        if m.get("status") in ("down", "pending"):
            attention.append(f"Uptime Kuma: {m.get('name', '?')} is {m['status'].title()}")
    if backup.get("warning"):  # media_backup: stale (> 36 h) or none yet
        attention.append(backup["warning"])
    attention.extend(runner_errors(runner))

    return {"tiles": [{"tile": t, "st": tile_state(t, snaps)} for t in area.tiles],
            "system": system, "services": services, "monitors": monitors, "updates": updates,
            "attention": attention, "counts": _counts(snaps)}
