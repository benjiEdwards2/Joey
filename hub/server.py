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
WP-U4 (2026-10-06): "Last 24 h" band (`history_band`) from media.db `server_system_samples`
(hub/server_history.py) — CPU / RAM / fullest-volume sparklines and a 7-day disk trend line.
WP-U3 (2026-10-07): not-configured connectors (`not_configured`) stay out of Attention, and
Services is a card grid (`service_card`: logo, subtitle, gated href, Uptime Kuma ms).
"""

from __future__ import annotations

import math
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

# WP-U3 (2026-10-07): the Services band is a card grid (Homepage-style). Logos are vendored
# in hub/static/svc/ (sources + licence in its README.md); an id with no entry renders a
# neutral initial-letter tile. NO_LOGO lists media_status apps knowingly shipped without one
# (tests/hub/test_server_cards.py fails on any other app missing a logo).
SERVICE_LOGOS = {
    "jellyfin": "jellyfin.svg", "jellyseerr": "jellyseerr.svg", "radarr": "radarr.svg",
    "sonarr": "sonarr.svg", "prowlarr": "prowlarr.svg", "qbittorrent": "qbittorrent.svg",
    "gluetun": "gluetun.svg", "portainer": "portainer.svg", "uptime_kuma": "uptime-kuma.svg",
    "wud": "wud.svg", "adm": "adm.svg",
    "homepage": "homepage.png",  # dashboard-icons has no Homepage SVG, only this PNG
}
NO_LOGO: set[str] = set()
SERVICE_SUBTITLES = {
    "jellyfin": "Media server", "jellyseerr": "Requests", "radarr": "Movies", "sonarr": "TV",
    "prowlarr": "Indexers", "qbittorrent": "Torrents (via VPN)", "gluetun": "VPN tunnel",
    "portainer": "Docker management", "uptime_kuma": "Service monitoring",
    "wud": "Container updates", "adm": "NAS admin", "homepage": "NAS dashboard",
}
# Apps that have a Cloudflare-gated hostname: the card links there instead of the LAN
# href from the snapshot (only Homepage today; the KPI-row link tiles are separate).
GATED_HREFS = {"homepage": "https://homepage.joeyhome.net"}


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


def _num(v) -> float | None:
    """A finite number from an envelope value (int, float or numeric string), else None — a malformed
    `system` value degrades to "—", never a 500 (H-63)."""
    if isinstance(v, bool):
        return None
    try:
        n = float(v)
    except (TypeError, ValueError):
        return None
    return n if math.isfinite(n) else None


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


# WP-U3 (B., 2026-10-07: "silence parked alerts"): a connector is NOT CONFIGURED — a setup
# task, not a failure — when (a) its latest error is a MissingCredential (connectors/base.py
# records "MissingCredential: <id>: missing environment variable …"), or (b) no visible area
# reads its snapshot (every area whose tiles reference it is `hidden`, or none does).
# Not-configured connectors never reach Attention, Discord or the hub card's warn state; the
# Sweeps (24 h) table still lists them, saying "Not configured" instead of "Failing".
MISSING_CREDENTIAL = "MissingCredential"


def live_snapshot_ids(registry) -> set[str] | None:
    """Snapshot ids read by at least one visible (not `hidden`) area; None without a registry
    (rule (b) then stays off and only rule (a) applies)."""
    if registry is None:
        return None
    return {t.snapshot for a in registry.areas if not a.hidden for t in a.tiles if t.snapshot}


def not_configured(cid: str, reason, live: set[str] | None = None) -> bool:
    """Rule (a): the latest error is a MissingCredential; rule (b): not read by a visible area."""
    if str(reason or "").removeprefix("runner-level ").startswith(MISSING_CREDENTIAL):
        return True
    return live is not None and cid not in live


def _runner_error_items(runner, live: set[str] | None = None) -> list[dict]:
    results = (runner or {}).get("results") if isinstance(runner, dict) else None
    if not isinstance(results, dict):
        return []
    return [{"key": f"sweep:{cid}", "text": f"{cid} sweep failed: {_reason(res)}"}
            for cid, res in sorted(results.items())
            if isinstance(res, dict) and res.get("status") == "error"
            and not not_configured(cid, res.get("error"), live)]


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


def sweep_rows(stats, now: datetime | None = None, live: set[str] | None = None) -> list[dict]:
    """The page's "Sweeps (24 h)" rows: {id, runs, failures, last_ok_text, failing,
    not_configured (failing, but a setup task — WP-U3)}."""
    now = now or datetime.now(timezone.utc)
    return [{"id": cid, "runs": st["runs"], "failures": st["failures"], "failing": st["failing"],
             "not_configured": st["failing"] and not_configured(cid, st["reason"], live),
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


def service_card(app: dict, monitors: list[dict]) -> dict:
    """One Services card: the app plus logo (file name or None), subtitle (or None), href
    (gated hostname when one exists) and the Uptime Kuma response ms of the first monitor
    whose name contains the app's name (case-insensitive), else None."""
    aid, name = app.get("id"), str(app.get("name") or app.get("id") or "?")
    ms = next((m.get("response_ms") for m in monitors
               if name.lower() in str(m.get("name") or "").lower()
               and m.get("response_ms") is not None), None)
    return {**app, "name": name, "initial": name[:1].upper(), "logo": SERVICE_LOGOS.get(aid),
            "subtitle": SERVICE_SUBTITLES.get(aid), "href": GATED_HREFS.get(aid, app.get("href")),
            "response_ms": ms}


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


def attention_items(snaps, backup: dict, runner: dict | None = None, stats=None,
                    live: set[str] | None = None) -> list[dict]:
    """[{key, text}] — what needs B.'s attention. Keys are stable (`down:<app id>`,
    `disk:<path>`, `kuma:<monitor>`, `backup`, `sweep:<connector>`) so hub/server_alerts.py
    can tell a NEW item from one already pushed. Sweep items come from the 24 h history
    (`stats`, failing now) and fall back to `_runner.json` when there is no history.
    Not-configured connectors (`not_configured`, WP-U3) never become sweep items; `live`
    is `live_snapshot_ids(registry)`."""
    items: list[dict] = []
    for a in _apps(snaps):
        if not a.get("up"):
            items.append({"key": f"down:{a.get('id', a.get('name', '?'))}",
                          "text": f"{a.get('name', a.get('id', '?'))} is Down"
                                  + (f" ({a['note']})" if a.get("note") else "")})
    for v in _volumes(snaps):
        pct = _num(v.get("pct_used"))
        if pct is not None and int(pct) >= DISK_ATTENTION_PCT:
            items.append({"key": f"disk:{v.get('path', '?')}",
                          "text": f"{v.get('path', '?')} is {pct:g}% full ({v['free_text']} free)"})
    for m in _monitors(snaps):
        if m.get("status") in ("down", "pending"):
            items.append({"key": f"kuma:{m.get('name', '?')}",
                          "text": f"Uptime Kuma: {m.get('name', '?')} is {m['status'].title()}"})
    if (backup or {}).get("warning"):  # media_backup: stale (> 36 h) or none yet
        items.append({"key": "backup", "text": backup["warning"]})
    if stats is None:
        items.extend(_runner_error_items(runner, live))
    else:
        for cid, st in sorted(stats.items()):
            if st["failing"] and st["failures"] and not not_configured(cid, st["reason"], live):
                items.append({"key": f"sweep:{cid}",
                              "text": f"{cid} failed {st['failures']} of the last {st['runs']} "
                                      f"sweep{'' if st['runs'] == 1 else 's'} · {st['reason']}"})
    return items


def hub_card(snaps, ignores, backup: dict, runner: dict | None = None, history=None,
             now: datetime | None = None, live: set[str] | None = None) -> dict:
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
    pcts = [int(p) for v in _volumes(snaps) if (p := _num(v.get("pct_used"))) is not None]
    if pcts:
        parts.append(f"disk {max(pcts)}%")
    n_down = sum(1 for m in _monitors(snaps) if m.get("status") == "down")
    if n_down:
        parts.append(f"{n_down} monitor{'' if n_down == 1 else 's'} down")
    attention = attention_items(snaps, backup, runner, sweep_stats(history, now), live)
    return {"summary": summary, "secondary": " · ".join(parts) or None,
            "state": "warn" if attention else "ok"}


SPARK_W, SPARK_H, SPARK_PAD = 240, 40, 3
SPARK_MIN_SPAN = 1.0  # % — a flat series draws as a flat line, not amplified noise
DISK_TARGET_PCT = DISK_ATTENTION_PCT
PROJECTION_MAX_DAYS = 3650  # 10 years: beyond that the trend reads "flat"
COLLECTING = "Collecting history — first chart after a few sweeps"


def _spark(label: str, points: list, start: datetime, digits: int = 0) -> dict | None:
    """Inline-SVG sparkline geometry over the 24 h window + its words; None under 2 points."""
    if len(points) < 2:
        return None
    vals = [v for _, v in points]
    lo, hi, last = min(vals), max(vals), vals[-1]
    span = max(hi - lo, SPARK_MIN_SPAN)
    inner_w, inner_h = SPARK_W - 2 * SPARK_PAD, SPARK_H - 2 * SPARK_PAD
    line = " ".join(
        f"{round(SPARK_PAD + min(1.0, max(0.0, (at - start).total_seconds() / 86400)) * inner_w, 1)},"
        f"{round(SPARK_H - SPARK_PAD - (v - lo) / span * inner_h, 1)}" for at, v in points)
    f = (lambda v: f"{v:.{digits}f}")
    return {"label": label, "line": line, "w": SPARK_W, "h": SPARK_H, "base": SPARK_H - SPARK_PAD,
            "pad": SPARK_PAD, "text": f"{label} {f(lo)}–{f(hi)} %, now {f(last)} %"}


def _vol_pct(sample: dict, path: str):
    for v in sample.get("volumes") or []:
        if v.get("path") == path and isinstance(v.get("pct_used"), (int, float)):
            return float(v["pct_used"])
    return None


def _span_text(seconds: float) -> str:
    days = seconds / 86400
    if days >= 1:
        n = round(days)
        return f"{n} day{'' if n == 1 else 's'}"
    return f"{max(1, round(seconds / 3600))} h"


def disk_trend(points: list) -> str | None:
    """'Disk: 8.0 % → 8.4 % over 7 days · ~N days to 85 % at this rate' (least-squares slope,
    positive and < 10 years) else '… · flat'; under 24 h of history the projection waits."""
    if len(points) < 2:
        return None
    t0 = points[0][0]
    xs = [(at - t0).total_seconds() / 86400 for at, _ in points]
    ys = [v for _, v in points]
    span_s = (points[-1][0] - t0).total_seconds()
    head = f"Disk: {ys[0]:.1f} % → {ys[-1]:.1f} % over {_span_text(span_s)}"
    if span_s < 86400:
        return head + " · projection after 24 h of history"
    if ys[-1] >= DISK_TARGET_PCT:
        return head + f" · at or over {DISK_TARGET_PCT} %"
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    var = sum((x - mx) ** 2 for x in xs)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / var if var else 0.0
    if slope > 0:
        days = (DISK_TARGET_PCT - ys[-1]) / slope
        if days < PROJECTION_MAX_DAYS:
            n = max(1, round(days))
            return head + f" · ~{n:,} day{'' if n == 1 else 's'} to {DISK_TARGET_PCT} % at this rate"
    return head + " · flat"


def history_band(samples, now: datetime | None = None) -> dict:
    """The "Last 24 h" band from server_history.recent() rows (oldest first): {collecting,
    sparks [CPU, RAM, fullest volume], trend}. Fewer than 2 samples in 24 h ⇒ collecting."""
    now = now or datetime.now(timezone.utc)
    start = now.timestamp() - 86400
    rows = [s for s in samples or [] if isinstance(s, dict) and s.get("at") is not None]
    day = [s for s in rows if s["at"].timestamp() >= start]
    if len(day) < 2:
        return {"collecting": True, "text": COLLECTING, "sparks": [], "trend": None}
    t_start = datetime.fromtimestamp(start, timezone.utc)

    def series(key, among):
        return [(s["at"], float(s[key])) for s in among if isinstance(s.get(key), (int, float))]

    sparks = [_spark("CPU", series("cpu_pct", day), t_start),
              _spark("RAM", series("ram_pct_used", day), t_start)]
    vols = [v for v in day[-1].get("volumes") or [] if isinstance(v.get("pct_used"), (int, float))]
    trend = None
    if vols:
        path = max(vols, key=lambda v: v["pct_used"])["path"]
        pts = [(s["at"], p) for s in day if (p := _vol_pct(s, path)) is not None]
        sparks.append(_spark(f"Disk {path}", pts, t_start, digits=1))
        trend = disk_trend([(s["at"], p) for s in rows if (p := _vol_pct(s, path)) is not None])
    return {"collecting": False, "text": None, "sparks": [s for s in sparks if s], "trend": trend}


def build_server(area, snaps, backup: dict, runner: dict | None = None,
                 ignores=None, requested=None, history=None, samples=None,
                 live: set[str] | None = None) -> dict:
    system = _band(area, snaps, SYSTEM_SNAPSHOT_ID)
    services = _band(area, snaps, MEDIA_STATUS_SNAPSHOT_ID)
    monitors = _band(area, snaps, UPTIME_KUMA_SNAPSHOT_ID)
    updates = _band(area, snaps, WUD_SNAPSHOT_ID)

    sd = system["data"]
    cpu, load = _num(sd.get("cpu_pct")), _num(sd.get("load_1m"))
    system.update(
        cpu_text=f"{cpu:.0f}%" if cpu is not None else "—",
        load_text=f"Load {load:.2f}" if load is not None else "",
        ram_text=_gb(sd.get("ram_free_gb")) + " free" if sd.get("ram_free_gb") is not None else "—",
        ram_sub=(f"of {_gb(sd.get('ram_total_gb'))} · {sd.get('ram_pct_used', 0)}% used"
                 if sd.get("ram_total_gb") is not None else ""),
        uptime_text=uptime_text(sd.get("uptime_s")) if sd.get("uptime_s") is not None else "—",
        volumes=_volumes(snaps) if sd else [],
        last_sweep=last_sweep(runner) if runner else None,
    )

    monitors["rows"] = [m for m in monitors["data"].get("monitors") or [] if isinstance(m, dict)]

    apps = [a for a in services["data"].get("apps") or [] if isinstance(a, dict)]
    services["groups"] = group_services([service_card(a, monitors["rows"]) for a in apps])

    ud = updates["data"]
    updates["pending"], updates["ignored"] = split_updates(
        [c for c in ud.get("containers") or [] if isinstance(c, dict) and c.get("update_available")],
        ignores, requested)

    stats = sweep_stats(history)
    items = attention_items(snaps, backup, runner, stats, live)

    return {"tiles": [{"tile": t, "st": tile_state(t, snaps)} for t in area.tiles],
            "system": system, "services": services, "monitors": monitors, "updates": updates,
            "attention": [i["text"] for i in items], "attention_items": items,
            "sweeps": sweep_rows(stats, live=live), "counts": _counts(snaps),
            "history": history_band(samples)}
