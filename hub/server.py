"""Server area page (WP-S1, 2026-10-06): the NAS "Homepage" dashboard, natively.

Pure: registry area + snapshots + backup status in, one dict of bands out. Every band
degrades on its own — a missing snapshot is that band's "Not connected", never a 500.
Keyed by connector ids and the area's `layout: server`, never by area name.
Thresholds (B., 2026-10-06): disk >= 85 % used, media.db backup older than 36 h
(hub/media_backup.py's own STALE_AFTER), any service Down.
WP-S4 (2026-10-06): Uptime Kuma monitors down/pending, connectors whose last sweep
errored (`_runner.json`), and a "Last sweep" line (stale past 90 min) in System.
WP-U1 (2026-10-06): pending updates split into shown and ignored (media.db ignores keyed
on container + new tag, or current tag for a digest update), each shown row carrying
"Requested N min ago" while its last requested run still matches the snapshot.
WP-U2 (2026-10-06): Attention as keyed items (`attention_items`, keys like `down:prowlarr`
— hub/server_alerts.py pushes NEW ones to Discord), durable sweep failures from
`_runner_history.jsonl` (last 24 h; `sweep_stats`), and the hub card's own words (`hub_card`).
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


def _reason(res: dict) -> str:
    """A result's error, sanitised: connector errors are sanitised at source; runner-level
    ones keep the exception type only and any URL is masked as a last guard."""
    reason = str(res.get("error") or "unknown error")
    if reason.startswith("runner-level "):
        reason = reason.split(":", 1)[0]
    return _URL_RE.sub("[url]", reason.removeprefix("RuntimeError: "))


def runner_errors(runner) -> list[str]:
    """'<id> sweep failed: <reason>' per connector whose last result errored."""
    return [i["text"] for i in _runner_error_items(runner)]


def _runner_error_items(runner) -> list[dict]:
    results = (runner or {}).get("results") if isinstance(runner, dict) else None
    if not isinstance(results, dict):
        return []
    return [{"key": f"sweep:{cid}", "text": f"{cid} sweep failed: {_reason(res)}"}
            for cid, res in sorted(results.items())
            if isinstance(res, dict) and res.get("status") == "error"]


SWEEP_WINDOW_HOURS = 24


def _when(value) -> datetime | None:
    try:
        at = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return at if at.tzinfo else at.replace(tzinfo=timezone.utc)


def sweep_stats(history, now: datetime | None = None) -> dict[str, dict] | None:
    """Per connector over the last 24 h of `_runner_history.jsonl` lines (oldest first):
    {runs, failures, failing (latest run errored), reason (last error, sanitised),
    last_ok (datetime | None)}. None when there is no usable history (caller falls back to
    `_runner.json`); malformed lines are skipped."""
    if not history:
        return None
    now = now or datetime.now(timezone.utc)
    since = now.timestamp() - SWEEP_WINDOW_HOURS * 3600
    stats: dict[str, dict] = {}
    usable = False
    for line in history:
        if not isinstance(line, dict) or not isinstance(line.get("results"), dict):
            continue
        at = _when(line.get("ran_at"))
        if at is None:
            continue
        usable = True
        if at.timestamp() < since:
            continue
        for cid, res in line["results"].items():
            if not isinstance(res, dict):
                continue
            st = stats.setdefault(str(cid), {"runs": 0, "failures": 0, "failing": False,
                                             "reason": None, "last_ok": None, "_at": None})
            failed = res.get("status") == "error"
            st["runs"] += 1
            st["failures"] += failed
            if not failed and (st["last_ok"] is None or at > st["last_ok"]):
                st["last_ok"] = at
            if st["_at"] is None or at >= st["_at"]:  # the latest run decides `failing`
                st["_at"], st["failing"] = at, failed
                if failed:
                    st["reason"] = _reason(res)
    if not usable:
        return None
    for st in stats.values():
        st.pop("_at")
    return stats


def sweep_rows(stats, now: datetime | None = None) -> list[dict]:
    """The page's "Sweeps (24 h)" rows: {id, runs, failures, last_ok_text, failing}."""
    now = now or datetime.now(timezone.utc)
    return [{"id": cid, "runs": st["runs"], "failures": st["failures"], "failing": st["failing"],
             "last_ok_text": (ago_text((now - st["last_ok"]).total_seconds() / 60.0)
                              if st["last_ok"] else "none in 24 h")}
            for cid, st in sorted((stats or {}).items())]


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


def _key_tag(row: dict) -> str:
    """Same key as hub/server_updates.key_tag (kept here so this module stays pure)."""
    return str(row.get("new_tag") or row.get("current_tag") or "")


def _requested_text(run, row, now: datetime) -> str | None:
    if not run or run.get("tag") != _key_tag(row):
        return None
    try:
        at = datetime.fromisoformat(str(run["requested_at"]).replace("Z", "+00:00"))
        at = at if at.tzinfo else at.replace(tzinfo=timezone.utc)
    except (KeyError, ValueError):
        return None
    return "Requested " + ago_text((now - at).total_seconds() / 60.0)


def split_updates(rows, ignores=None, requested=None, now: datetime | None = None) -> tuple[list, list]:
    """(shown, ignored) pending update rows; shown rows gain `requested_text`."""
    ignores, requested = ignores or set(), requested or {}
    now = now or datetime.now(timezone.utc)
    shown, ignored = [], []
    for c in rows:
        if (c.get("name"), _key_tag(c)) in ignores:
            ignored.append(c)
        else:
            shown.append({**c, "requested_text": _requested_text(requested.get(c.get("name")), c, now)})
    return shown, ignored


def _data(snaps, cid) -> dict:
    snap = snaps.get(cid)
    return (snap.data or {}) if snap and isinstance(snap.data, dict) else {}


def _volumes(snaps) -> list[dict]:
    return [{**v, "free_text": _gb(v.get("free_gb")), "total_text": _gb(v.get("total_gb"))}
            for v in _data(snaps, SYSTEM_SNAPSHOT_ID).get("volumes") or [] if isinstance(v, dict)]


def _apps(snaps) -> list[dict]:
    return [a for a in _data(snaps, MEDIA_STATUS_SNAPSHOT_ID).get("apps") or [] if isinstance(a, dict)]


def _monitors(snaps) -> list[dict]:
    return [m for m in _data(snaps, UPTIME_KUMA_SNAPSHOT_ID).get("monitors") or [] if isinstance(m, dict)]


def attention_items(snaps, backup: dict, runner: dict | None = None, stats=None) -> list[dict]:
    """[{key, text}] — what needs B.'s attention. Keys are stable (`down:<app id>`,
    `disk:<path>`, `kuma:<monitor>`, `backup`, `sweep:<connector>`) so hub/server_alerts.py
    can tell a NEW item from one already pushed. Sweep items come from the 24 h history
    (`stats`, failing now) and fall back to `_runner.json` when there is no history."""
    items: list[dict] = []
    for a in _apps(snaps):
        if not a.get("up"):
            items.append({"key": f"down:{a.get('id', a.get('name', '?'))}",
                          "text": f"{a.get('name', a.get('id', '?'))} is Down"
                                  + (f" ({a['note']})" if a.get("note") else "")})
    for v in _volumes(snaps):
        if int(v.get("pct_used") or 0) >= DISK_ATTENTION_PCT:
            items.append({"key": f"disk:{v.get('path', '?')}",
                          "text": f"{v.get('path', '?')} is {v['pct_used']}% full ({v['free_text']} free)"})
    for m in _monitors(snaps):
        if m.get("status") in ("down", "pending"):
            items.append({"key": f"kuma:{m.get('name', '?')}",
                          "text": f"Uptime Kuma: {m.get('name', '?')} is {m['status'].title()}"})
    if (backup or {}).get("warning"):  # media_backup: stale (> 36 h) or none yet
        items.append({"key": "backup", "text": backup["warning"]})
    if stats is None:
        items.extend(_runner_error_items(runner))
    else:
        for cid, st in sorted(stats.items()):
            if st["failing"] and st["failures"]:
                items.append({"key": f"sweep:{cid}",
                              "text": f"{cid} failed {st['failures']} of the last {st['runs']} "
                                      f"sweep{'' if st['runs'] == 1 else 's'} · {st['reason']}"})
    return items


def hub_card(snaps, ignores, backup: dict, runner: dict | None = None, history=None,
             now: datetime | None = None) -> dict:
    """The Server area's hub card in words: {summary, secondary, state: ok|warn}.
    summary: "All up" / "2 down: Prowlarr, Sonarr"; secondary: "N updates" (ignored ones
    excluded) · "disk N%" (fullest volume) · "N monitors down". `warn` whenever Attention
    is non-empty. "Not connected" when the services snapshot is missing."""
    apps = _apps(snaps)
    if MEDIA_STATUS_SNAPSHOT_ID not in snaps or not _data(snaps, MEDIA_STATUS_SNAPSHOT_ID):
        summary = "Not connected"
    else:
        down = [str(a.get("name", a.get("id", "?"))) for a in apps if not a.get("up")]
        summary = f"{len(down)} down: {', '.join(down)}" if down else "All up"
    parts = []
    rows = [c for c in _data(snaps, WUD_SNAPSHOT_ID).get("containers") or []
            if isinstance(c, dict) and c.get("update_available")]
    n_up = len(split_updates(rows, ignores, None, now)[0])
    if n_up:
        parts.append(f"{n_up} update{'' if n_up == 1 else 's'}")
    pcts = [int(v.get("pct_used") or 0) for v in _volumes(snaps)]
    if pcts:
        parts.append(f"disk {max(pcts)}%")
    n_down = sum(1 for m in _monitors(snaps) if m.get("status") == "down")
    if n_down:
        parts.append(f"{n_down} monitor{'' if n_down == 1 else 's'} down")
    attention = attention_items(snaps, backup, runner, sweep_stats(history, now))
    return {"summary": summary, "secondary": " · ".join(parts) or None,
            "state": "warn" if attention else "ok"}


def build_server(area, snaps, backup: dict, runner: dict | None = None,
                 ignores=None, requested=None, history=None) -> dict:
    system = _band(area, snaps, SYSTEM_SNAPSHOT_ID)
    services = _band(area, snaps, MEDIA_STATUS_SNAPSHOT_ID)
    monitors = _band(area, snaps, UPTIME_KUMA_SNAPSHOT_ID)
    updates = _band(area, snaps, WUD_SNAPSHOT_ID)

    sd = system["data"]
    system.update(
        cpu_text=f"{float(sd['cpu_pct']):.0f}%" if sd.get("cpu_pct") is not None else "—",
        load_text=f"Load {sd['load_1m']:.2f}" if sd.get("load_1m") is not None else "",
        ram_text=_gb(sd.get("ram_free_gb")) + " free" if sd.get("ram_free_gb") is not None else "—",
        ram_sub=(f"of {_gb(sd.get('ram_total_gb'))} · {sd.get('ram_pct_used', 0)}% used"
                 if sd.get("ram_total_gb") is not None else ""),
        uptime_text=uptime_text(sd.get("uptime_s")) if sd.get("uptime_s") is not None else "—",
        volumes=_volumes(snaps) if sd else [],
        last_sweep=last_sweep(runner) if runner else None,
    )

    apps = services["data"].get("apps") or []
    services["groups"] = group_services(apps)

    monitors["rows"] = [m for m in monitors["data"].get("monitors") or [] if isinstance(m, dict)]

    ud = updates["data"]
    updates["pending"], updates["ignored"] = split_updates(
        [c for c in ud.get("containers") or [] if isinstance(c, dict) and c.get("update_available")],
        ignores, requested)

    stats = sweep_stats(history)
    items = attention_items(snaps, backup, runner, stats)

    return {"tiles": [{"tile": t, "st": tile_state(t, snaps)} for t in area.tiles],
            "system": system, "services": services, "monitors": monitors, "updates": updates,
            "attention": [i["text"] for i in items], "attention_items": items,
            "sweeps": sweep_rows(stats), "counts": _counts(snaps)}
