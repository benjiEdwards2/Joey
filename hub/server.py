"""Server area page (WP-S1, 2026-10-06): the NAS "Homepage" dashboard, natively (Homepage retired 2026-10-09).

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
WP-T3 (2026-10-19, Server clean-up): no tile row and no Counts band; `library_health` (one line under Downloads),
`sweep_summary` (System's sweeps line), `disk_days` (the forecast that joins the page's Attention under 30 days) and
`attention_action` (each page Attention item with its action). `attention_items` and `hub_card` are unchanged.
JY-031 (2026-10-23): the disk forecast reaches the hub card and Discord. `forecast_step` runs once per hub loop tick
(hub/server_history.py keeps its state in memory) with hysteresis: an episode starts under FORECAST_ATTENTION_DAYS (30)
and ends only over FORECAST_END_DAYS (45) or when the disk is flat or shrinking. Its item goes into `attention_items`
(`forecast=`) on all three paths (hub card, /server, the loop's check), so they build the same key set.
"""

from __future__ import annotations

import ipaddress
import math
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit

from hub.ids import (ARR_SNAPSHOT_ID, JELLYSEERR_SNAPSHOT_ID, MEDIA_STATUS_SNAPSHOT_ID, QBIT_SNAPSHOT_ID,  # noqa: F401
                     SYSTEM_SNAPSHOT_ID, UPTIME_KUMA_SNAPSHOT_ID, WUD_SNAPSHOT_ID)
from hub.store import ago_text, connected, data_of, parse_utc, tile_state

SERVER_LAYOUT = "server"

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
}
NO_LOGO: set[str] = set()
SERVICE_SUBTITLES = {
    "jellyfin": "Media server", "jellyseerr": "Requests", "radarr": "Movies", "sonarr": "TV",
    "prowlarr": "Indexers", "qbittorrent": "Torrents (via VPN)", "gluetun": "VPN tunnel",
    "portainer": "Docker management", "uptime_kuma": "Service monitoring",
    "wud": "Container updates", "adm": "NAS admin",
}
# Apps with a Cloudflare-gated hostname come from areas.yaml `gated_hrefs` (registry.gated_hrefs, 2026-10-09):
# no hostname lives in this file. A card / link tile whose href is still a LAN address has no link and says "LAN".
LAN_WORD = "LAN"


def is_lan(href) -> bool:
    """True for a link only the home network can open (dead through the tunnel): a private / loopback / link-local
    IP, or a dot-less, .local, .lan or .home.arpa host name."""
    try:
        host = urlsplit(str(href or "")).hostname
    except ValueError:
        return False
    if not host:
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return "." not in host or host.endswith((".local", ".lan", ".home.arpa"))
    return ip.is_private or ip.is_loopback or ip.is_link_local


def uptime_text(seconds) -> str:
    """'12d 4h' / '5h 20m' / '40m' (E3, 2026-10-13: the guide's '2h 47m' lengths; was '5 h 20 min')."""
    try:
        seconds = max(0, int(seconds))
    except (TypeError, ValueError):
        return "—"
    days, rest = divmod(seconds, 86400)
    hours, minutes = rest // 3600, (rest % 3600) // 60
    if days:
        return f"{days}d {hours}h"
    return f"{hours}h {minutes}m" if hours else f"{minutes}m"


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


def last_sweep(runner, now: datetime | None = None) -> dict | None:
    """{text, stale} from `_runner.json` `ran_at`; None when absent or unreadable."""
    ran = parse_utc(runner.get("ran_at")) if isinstance(runner, dict) else None
    if ran is None:
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


# WP-U3 (B., 2026-10-07: "silence parked alerts"): a connector is NOT CONFIGURED — a setup
# task, not a failure — when (a) its latest error is a MissingCredential (connectors/base.py
# records "MissingCredential: <id>: missing environment variable …"), or (b) no visible area
# reads its snapshot (every area whose tiles reference it is `hidden`, or none does).
# Not-configured connectors never reach Attention, Discord or the hub card's warn state; the
# Sweeps · 24 h table still lists them, saying "Not configured" instead of "Failing".
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
        at = parse_utc(line.get("ran_at"))
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


def sweep_summary(rows, last) -> dict | None:
    """WP-T3 (2026-10-19, S5): System's ONE sweeps line in place of the Sweeps · 24 h band (its rows fold under it):
    {parts ["7 connectors", "all sweeps OK"], failing "1 failing: gcal" | None, not_configured "2 not configured" | None,
    last "Last sweep 12m ago" | None, stale, open (the fold opens itself on a failing or not-configured row)}. `rows`
    are `sweep_rows`, `last` is `last_sweep`; None when there is neither."""
    rows = rows or []
    if not rows and not last:
        return None
    failing = [r["id"] for r in rows if r["failing"] and not r["not_configured"]]
    n_nc = sum(1 for r in rows if r["not_configured"])
    parts = [f"{len(rows)} connector{'' if len(rows) == 1 else 's'}"] if rows else []
    if rows and not failing and not n_nc:
        parts.append("all sweeps OK")
    return {"parts": parts, "failing": f"{len(failing)} failing: {', '.join(failing)}" if failing else None,
            "not_configured": f"{n_nc} not configured" if n_nc else None,
            "last": f"Last sweep {last['text']}" if last else None, "stale": bool(last and last["stale"]),
            "open": bool(failing or n_nc)}


def _tile(area, snapshot_id):
    return next((t for t in area.tiles if t.snapshot == snapshot_id), None)


def _band(area, snaps, snapshot_id) -> dict:
    """{tile, st, data} for the area tile reading `snapshot_id`; data is {} when off."""
    tile = _tile(area, snapshot_id)
    st = tile_state(tile, snaps) if tile else {"state": "off", "note": None}
    return {"tile": tile, "st": st, "data": data_of(snaps.get(snapshot_id)) if st["state"] != "off" else {}}


def group_services(apps: list[dict]) -> list[dict]:
    groups = [{"label": label, "apps": [a for a in apps if a.get("id") in ids]}
              for label, ids in SERVICE_GROUPS]
    known = set().union(*(ids for _, ids in SERVICE_GROUPS))
    groups.append({"label": OTHER_GROUP, "apps": [a for a in apps if a.get("id") not in known]})
    return [g for g in groups if g["apps"]]


def service_card(app: dict, monitors: list[dict], gated: dict | None = None) -> dict:
    """One Services card: the app plus logo (file name or None), subtitle (or None), href (the gated hostname from
    `gated` when one exists, else the snapshot's — kept even when it is a LAN address, with `lan` True so the card
    says "LAN": it opens at home and is dead off the home network, 2026-10-10, reverses H-71) and the
    Uptime Kuma response ms of the monitor whose name IS the app's name or id (case-insensitive, H-72; the id too since
    the Jellyseerr -> Seerr rename, 2026-10-12, so a Kuma monitor still called "Jellyseerr" keeps matching), else None."""
    aid, name = app.get("id"), str(app.get("name") or app.get("id") or "?")
    keys = {name.strip().lower(), str(aid or "").strip().lower()}
    ms = next((m.get("response_ms") for m in monitors
               if str(m.get("name") or "").strip().lower() in keys and m.get("response_ms") is not None), None)
    href = (gated or {}).get(aid) or app.get("href")
    lan = bool(href) and is_lan(href)
    return {**app, "name": name, "initial": name[:1].upper(), "logo": SERVICE_LOGOS.get(aid),
            "subtitle": SERVICE_SUBTITLES.get(aid), "href": href, "lan": lan,
            "response_ms": ms}


# WP-T3 (2026-10-19, S1 + S2): the Counts band is gone — Requests / Torrents / arr downloading repeated Activity, and
# the arr disk bars repeated System's volumes. Its unique figures (Radarr / Sonarr wanted + missing, Prowlarr failed
# grabs) are ONE "Library health" line under Services › Downloads (or at the end of Services without that group).
HEALTH_GROUP = "Downloads"
SEARCH_MISSING_HREF = "/media/requests?sweep_ask=missing"   # media_arr_search: the page draws the confirm card


def library_health(snaps) -> dict | None:
    """{parts, failed, search} from the arr snapshot's `radarr` / `sonarr` / `prowlarr` objects (WP-S3), or None when
    the snapshot carries none of them. parts: the non-zero counts in words ("Radarr 2 wanted", "3 missing",
    "Sonarr 7 wanted"); failed: "Prowlarr 3 failed grabs" when that count is non-zero (amber: something to look at);
    search: the Search missing href when anything is wanted or missing, else None. No parts and no failed ⇒
    the template says "all clear"."""
    arr = _data(snaps, ARR_SNAPSHOT_ID)
    radarr, sonarr, prowlarr = (arr.get(k) if isinstance(arr.get(k), dict) else None
                                for k in ("radarr", "sonarr", "prowlarr"))
    if not (radarr or sonarr or prowlarr):
        return None

    def n(d, key) -> int:
        v = _num((d or {}).get(key))
        return max(0, int(v)) if v is not None else 0

    parts = []
    for name, d, keys in (("Radarr", radarr, ("wanted", "missing")), ("Sonarr", sonarr, ("wanted",))):
        words = [f"{n(d, k)} {k}" for k in keys if n(d, k)]
        if words:
            parts += [f"{name} {words[0]}", *words[1:]]
    failed = n(prowlarr, "failed_grabs")
    return {"parts": parts, "failed": f"Prowlarr {failed} failed grab{'' if failed == 1 else 's'}" if failed else None,
            "search": SEARCH_MISSING_HREF if parts else None}


# Pending rows the hub never sends to WUD (one definition; server_updates imports these): WUD itself (B. updates it by
# hand) and Joey's own containers (joey-cloudflared, joey-macromates, any `joey-*`: not in the media-server compose
# that WUD's dockercompose triggers manage, so they update on the next Joey deploy, 2026-10-12).
WUD_SELF = "wud"
JOEY_PREFIX = "joey-"
HOLD_TEXT = {"wud": "Update WUD by hand", "joey": "Updates on next Joey deploy"}


def update_hold(name) -> str | None:
    """Why a pending row has no Update now: "wud" | "joey" | None (it may run)."""
    name = str(name or "")
    if name == WUD_SELF:
        return "wud"
    return "joey" if name.startswith(JOEY_PREFIX) else None


def key_tag(row: dict) -> str:
    """The tag an ignore/run is keyed on: the new tag, or the current tag for a digest update (server_updates
    imports it from here)."""
    return str(row.get("new_tag") or row.get("current_tag") or "")


def _requested_text(run, row, now: datetime) -> str | None:
    if not run or run.get("tag") != key_tag(row):
        return None
    at = parse_utc(run.get("requested_at"))
    if at is None:
        return None
    return "Requested " + ago_text((now - at).total_seconds() / 60.0)


def split_updates(rows, ignores=None, requested=None, now: datetime | None = None) -> tuple[list, list]:
    """(shown, ignored) pending update rows; shown rows gain `requested_text` and `hold` / `hold_text`
    (`update_hold`: no Update now when set)."""
    ignores, requested = ignores or set(), requested or {}
    now = now or datetime.now(timezone.utc)
    shown, ignored = [], []
    for c in rows:
        if (c.get("name"), key_tag(c)) in ignores:
            ignored.append(c)
        else:
            hold = update_hold(c.get("name"))
            shown.append({**c, "requested_text": _requested_text(requested.get(c.get("name")), c, now),
                          "hold": hold, "hold_text": HOLD_TEXT.get(hold)})
    return shown, ignored


def _data(snaps, cid) -> dict:
    return data_of(snaps.get(cid))


def _volumes(snaps) -> list[dict]:
    return [{**v, "free_text": _gb(v.get("free_gb")), "total_text": _gb(v.get("total_gb"))}
            for v in _data(snaps, SYSTEM_SNAPSHOT_ID).get("volumes") or [] if isinstance(v, dict)]


def _apps(snaps) -> list[dict]:
    return [a for a in _data(snaps, MEDIA_STATUS_SNAPSHOT_ID).get("apps") or [] if isinstance(a, dict)]


def _monitors(snaps) -> list[dict]:
    return [m for m in _data(snaps, UPTIME_KUMA_SNAPSHOT_ID).get("monitors") or [] if isinstance(m, dict)]


def attention_items(snaps, backup: dict, runner: dict | None = None, stats=None,
                    live: set[str] | None = None, forecast: dict | None = None) -> list[dict]:
    """[{key, text}] — what needs B.'s attention. Keys are stable (`down:<app id>`,
    `disk:<path>`, `kuma:<monitor>`, `backup`, `sweep:<connector>`) so hub/server_alerts.py
    can tell a NEW item from one already pushed. Sweep items come from the 24 h history
    (`stats`, failing now) and fall back to `_runner.json` when there is no history.
    Not-configured connectors (`not_configured`, WP-U3) never become sweep items; `live`
    is `live_snapshot_ids(registry)`. `forecast` (JY-031): the cached disk forecast item
    (`forecast_step`'s "item", key `forecast:<path>`), placed after the disk items."""
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
    if forecast:
        items.append(forecast)
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


def attention_action(item: dict, cards: dict) -> dict:
    """WP-T3 (2026-10-19, S7): a page Attention item with its action — {text, href, action, new_tab}. A down service
    opens its card's link ("Open", new tab; the gated hostname or the LAN address, as on the card) or, with no link,
    jumps to Services; an Uptime Kuma monitor jumps to Services; a failing sweep to System (its sweeps line + fold).
    Disk and backup carry no action (none exists on this page); the disk forecast opens Free space (P1a, 2026-10-22:
    `/server/space`, hub/server_space.py, a list only). `cards`: Services cards by app id."""
    kind, _, ident = str(item.get("key") or "").partition(":")
    href = action = None
    new_tab = False
    if kind == "down":
        href = (cards.get(ident) or {}).get("href")
        href, action, new_tab = (href, "Open", True) if href else ("#services", "Services", False)
    elif kind == "kuma":
        href, action = "#services", "Services"
    elif kind == "sweep":
        href, action = "#system", "Sweeps"
    elif kind == "forecast":   # P1a free space (2026-10-22)
        href, action = "/server/space", "Free space"
    return {"text": item["text"], "href": href, "action": action, "new_tab": new_tab}


def services_words(snaps) -> str:
    """"All up" / "2 down · Prowlarr · Sonarr" / "Not connected" — the Services words of the hub card (H-73: one
    vocabulary, guide §9 " · " joins; the Server page's Services tile went with the tile row, WP-T3 2026-10-19)."""
    if not connected(snaps.get(MEDIA_STATUS_SNAPSHOT_ID)) or not _data(snaps, MEDIA_STATUS_SNAPSHOT_ID):
        return "Not connected"
    down = [str(a.get("name", a.get("id", "?"))) for a in _apps(snaps) if not a.get("up")]
    return " · ".join([f"{len(down)} down", *down]) if down else "All up"


def hub_card(snaps, ignores, backup: dict, runner: dict | None = None, history=None,
             now: datetime | None = None, live: set[str] | None = None, forecast: dict | None = None) -> dict:
    """The Server area's hub card in words: {summary, secondary, state: ok|warn}.
    summary: "All up" / "2 down · Prowlarr · Sonarr"; secondary: "N updates" (ignored ones
    excluded) · "disk N%" (fullest volume) · "reaches 85% in about N days" (JY-031: while the cached
    `forecast` item is open) · "N monitors down". `warn` whenever Attention is non-empty (the forecast
    included). "Not connected" when the services snapshot is missing."""
    summary = services_words(snaps)
    parts = []
    rows = [c for c in _data(snaps, WUD_SNAPSHOT_ID).get("containers") or []
            if isinstance(c, dict) and c.get("update_available")]
    n_up = len(split_updates(rows, ignores, None, now)[0])
    if n_up:
        parts.append(f"{n_up} update{'' if n_up == 1 else 's'}")
    pcts = [int(p) for v in _volumes(snaps) if (p := _num(v.get("pct_used"))) is not None]
    if pcts:
        parts.append(f"disk {max(pcts)}%")
    if forecast:
        parts.append(forecast["words"])
    n_down = sum(1 for m in _monitors(snaps) if m.get("status") == "down")
    if n_down:
        parts.append(f"{n_down} monitor{'' if n_down == 1 else 's'} down")
    attention = attention_items(snaps, backup, runner, sweep_stats(history, now), live, forecast)
    return {"summary": summary, "secondary": " · ".join(parts) or None,
            "state": "warn" if attention else "ok"}


SPARK_W, SPARK_H, SPARK_PAD = 240, 40, 3
SPARK_MIN_SPAN = 1.0  # % — a flat series draws as a flat line, not amplified noise
DISK_TARGET_PCT = DISK_ATTENTION_PCT
PROJECTION_MAX_DAYS = 3650  # 10 years: beyond that the trend reads "flat"
COLLECTING = "Collecting history · first chart after a few sweeps"
FORECAST_ATTENTION_DAYS = 30   # WP-T3 (2026-10-19, S6): a projection under this joins the page's Attention
FORECAST_END_DAYS = 45   # JY-031 (2026-10-23, B. 3a): an open forecast episode ends only over this (or flat/shrinking)
_VOLUME_RE = re.compile(r"/volume(\d+)(?:/|$)")


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


def disk_days(points: list) -> float | None:
    """Days until the volume reaches DISK_TARGET_PCT at the least-squares rate over `points` [(at, pct)], or None:
    under 24 h of history, already at or over the target, flat or falling, or PROJECTION_MAX_DAYS and beyond
    (WP-T3, 2026-10-19: lifted out of `disk_trend` so the projection can also reach Attention)."""
    if len(points) < 2:
        return None
    if (points[-1][0] - points[0][0]).total_seconds() < 86400 or points[-1][1] >= DISK_TARGET_PCT:
        return None
    slope = _slope(points)
    if slope <= 0:
        return None
    days = (DISK_TARGET_PCT - points[-1][1]) / slope
    return days if days < PROJECTION_MAX_DAYS else None


def _slope(points: list) -> float:
    """The least-squares rate of `points` [(at, pct)], in % per day (0.0 when it cannot be worked out)."""
    if len(points) < 2:
        return 0.0
    t0 = points[0][0]
    xs = [(at - t0).total_seconds() / 86400 for at, _ in points]
    ys = [v for _, v in points]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    var = sum((x - mx) ** 2 for x in xs)
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / var if var else 0.0


def _days_text(days: float) -> str:
    """Whole days rounded DOWN, at least 1 (JY-031, 2026-10-23: the one rounding for every projected number - the
    Attention item, the hub card, Discord, the trend line and Free space - so an item opened under 30 never reads 30
    and two places never differ by a day; was round())."""
    n = max(1, math.floor(days))
    return f"{n:,} day{'' if n == 1 else 's'}"


def disk_trend(points: list, days: float | None = None) -> str | None:
    """'Disk: 8.0 % → 8.4 % over 7 days · ~N days to 85 % at this rate' (least-squares slope,
    positive and < 10 years) else '… · flat'; under 24 h of history the projection waits. `days` (JY-031): the cached
    forecast item's projection, shown instead of this line's own so the trend and Attention say the same number."""
    if len(points) < 2:
        return None
    ys = [v for _, v in points]
    span_s = (points[-1][0] - points[0][0]).total_seconds()
    head = f"Disk: {ys[0]:.1f} % → {ys[-1]:.1f} % over {_span_text(span_s)}"
    if span_s < 86400:
        return head + " · projection after 24 h of history"
    if days is None and ys[-1] >= DISK_TARGET_PCT:
        return head + f" · at or over {DISK_TARGET_PCT} %"
    if days is None:
        days = disk_days(points)
    if days is not None:
        return head + f" · ~{_days_text(days)} to {DISK_TARGET_PCT} % at this rate"
    return head + " · flat"


def history_band(samples, now: datetime | None = None, forecast: dict | None = None) -> dict:
    """The "Last 24 h" band from server_history.recent() rows (oldest first): {collecting,
    sparks [CPU, RAM, fullest volume], trend}. Fewer than 2 samples in 24 h ⇒ collecting.
    `forecast` (JY-031): the cached forecast item; while it carries a projection for the trend's volume, the trend line
    says its days. (Its own "forecast" field, WP-T3's page-only item, went in JY-031: the cached item replaced it.)"""
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
        week = [(s["at"], p) for s in rows if (p := _vol_pct(s, path)) is not None]
        cached = forecast.get("days") if forecast and forecast.get("key") == f"forecast:{path}" else None
        trend = disk_trend(week, cached)
    return {"collecting": False, "text": None, "sparks": [s for s in sparks if s], "trend": trend}


def volume_name(path) -> str:
    """'/volume1' or anything under it ('/volume1/Docker') -> 'Volume 1', the NAS's own name for the volume (JY-031);
    any other path as it is."""
    m = _VOLUME_RE.match(str(path))
    return f"Volume {m.group(1)}" if m else str(path)


def forecast_item(path: str, days: float | None, free_gb=None, full: bool = False) -> dict:
    """The disk forecast's Attention item (JY-031): {key `forecast:<path>`, text, words (the hub card's meta)}.
    text "Disk: reaches 85% in about 23 days (Volume 1, 412 GB free)" (Discord adds "Joey Server: "); N days is
    `_days_text` (floor, at least 1); `days` is carried for the trend line. Two words without a number, for an episode kept open with no projection: `full` (at or over
    the target, the "is 85% full" item speaks) "at or over 85%"; no projection yet (a restart while collecting)
    "filling fast"."""
    if full:
        words = f"at or over {DISK_TARGET_PCT}%"
    elif days is None:
        words = "filling fast"
    else:
        words = f"reaches {DISK_TARGET_PCT}% in about {_days_text(days)}"
    free = _num(free_gb)
    where = volume_name(path) + (f", {free:,.0f} GB free" if free is not None else "")
    return {"key": f"forecast:{path}", "text": f"Disk: {words} ({where})", "words": words, "days": days}


def _week(rows: list, path) -> list:
    return [(s["at"], p) for s in rows if (p := _vol_pct(s, path)) is not None]


def _vol_free(rows: list, path):
    """The newest sample's free GB for `path`, else None."""
    for s in reversed(rows):
        for v in s.get("volumes") or []:
            if isinstance(v, dict) and v.get("path") == path:
                return v.get("free_gb")
    return None


def _closed(path=None, days=None, collecting=False) -> dict:
    return {"open": False, "path": path, "days": days, "collecting": collecting, "item": None}


def _forecast_keep(prev: dict, rows: list) -> dict:
    """Collecting, or under 24 h of history: nothing new to judge, so the episode keeps its state (rule 5). An open
    episode keeps its item; one restored from the seen-row (open, no item yet) gets one from what the 7-day history
    can say (a projection, at or over the target, else "filling fast") and stays open either way: only a real
    computed projection over 45 days, or a flat or shrinking disk, ends it."""
    if not prev.get("open"):
        return _closed(prev.get("path"), prev.get("days"), collecting=True)
    if prev.get("item"):
        return {**prev, "collecting": True}
    path = prev.get("path")
    week = _week(rows, path)
    days = disk_days(week)
    full = bool(week) and week[-1][1] >= DISK_TARGET_PCT
    return {"open": True, "path": path, "days": days, "collecting": True,
            "item": forecast_item(path, days, _vol_free(rows, path), full=full and days is None)}


def forecast_step(prev: dict | None, samples, now: datetime | None = None) -> dict:
    """One hub-loop tick of the disk forecast episode (JY-031, B.'s pick 2026-10-23: 1A 2a 3a 4a; fix round the same
    day). prev: the last state, or None; samples: server_history.recent() rows (7 days, oldest first).
    -> {open, path, days, collecting, item}; item (`forecast_item`) only while the episode is open.
    - Collecting (fewer than 2 samples in the last 24 h, history_band's rule) or under 24 h of history: the state is
      kept (`_forecast_keep`), so an open episode stays open and a return after an outage does not post again.
    - At or over the target (85 %) while open: the episode stays open and silent (same key, words "at or over 85%")
      while the disk still grows, so 84.9 -> 85.1 -> 84.9 posts once; a closed one does not open (the "is 85% full"
      item speaks). Flat or shrinking ends it.
    - Below the target, the fullest volume's 7-day projection (`disk_days`): a closed episode opens under
      FORECAST_ATTENTION_DAYS (30); an open one ends only over FORECAST_END_DAYS (45), or when it is flat or shrinking
      (or 10 years and more). A projection between 30 and 45 days keeps whatever state it had."""
    now = now or datetime.now(timezone.utc)
    prev = prev or {}
    rows = [s for s in samples or [] if isinstance(s, dict) and isinstance(s.get("at"), datetime)]
    start = now.timestamp() - 86400
    day = [s for s in rows if s["at"].timestamp() >= start]
    vols = [v for v in (day[-1].get("volumes") or [] if day else [])
            if isinstance(v, dict) and isinstance(v.get("pct_used"), (int, float))]
    if len(day) < 2 or not vols:
        return _forecast_keep(prev, rows)
    path = max(vols, key=lambda v: v["pct_used"])["path"]
    week = _week(rows, path)
    if len(week) < 2 or (week[-1][0] - week[0][0]).total_seconds() < 86400:
        return _forecast_keep(prev, rows)
    same = bool(prev.get("open")) and prev.get("path") == path
    if week[-1][1] >= DISK_TARGET_PCT:
        if same and _slope(week) > 0:
            return {"open": True, "path": path, "days": None, "collecting": False,
                    "item": forecast_item(path, None, _vol_free(rows, path), full=True)}
        return _closed(path)
    days = disk_days(week)
    if same:
        is_open = days is not None and days <= FORECAST_END_DAYS
    else:
        is_open = days is not None and days < FORECAST_ATTENTION_DAYS
    return {"open": is_open, "path": path, "days": days, "collecting": False,
            "item": forecast_item(path, days, _vol_free(rows, path)) if is_open else None}


def build_server(area, snaps, backup: dict, runner: dict | None = None,
                 ignores=None, requested=None, history=None, samples=None,
                 live: set[str] | None = None, gated: dict | None = None, forecast: dict | None = None,
                 now: datetime | None = None) -> dict:
    system = _band(area, snaps, SYSTEM_SNAPSHOT_ID)
    services = _band(area, snaps, MEDIA_STATUS_SNAPSHOT_ID)
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

    # 2026-10-12: no Monitors band any more (it repeated Services); the Kuma rows still give each card its ms.
    apps = [a for a in services["data"].get("apps") or [] if isinstance(a, dict)]
    services["groups"] = group_services([service_card(a, _monitors(snaps), gated) for a in apps])
    services["health"] = library_health(snaps)   # WP-T3 (S1 + S2)
    services["health_in"] = next((g["label"] for g in services["groups"] if g["label"] == HEALTH_GROUP), None)

    ud = updates["data"]
    updates["pending"], updates["ignored"] = split_updates(
        [c for c in ud.get("containers") or [] if isinstance(c, dict) and c.get("update_available")],
        ignores, requested)
    updates["n_eligible"] = sum(1 for c in updates["pending"] if not c["hold"])   # Update all is shown from 1
    # WP-T3 (2026-10-19, S9): "checked 2h ago" — the age of the WUD snapshot; "Stale" only past the Updates tile's own
    # stale_after_minutes (tile_state's rule, the one every band uses), never on a fresh one.
    snap = snaps.get(WUD_SNAPSHOT_ID)
    updates["checked"] = ({"text": "checked " + ago_text(snap.age_minutes), "stale": updates["st"]["state"] == "stale"}
                          if updates["st"]["state"] in ("fresh", "stale") and snap is not None else None)

    stats = sweep_stats(history)
    # JY-031 (2026-10-23): the disk forecast is the hub loop's cached item (`forecast`, hub/server_history.py), the same
    # one the hub card, the loop's Discord check and Free space use, so all build one key set; the trend line in the
    # Last 24 h band says its days. (WP-T3's page-only forecast from history_band is gone.)
    items = attention_items(snaps, backup, runner, stats, live, forecast)
    rows = sweep_rows(stats, live=live)
    history = history_band(samples, now, forecast)
    cards = {a.get("id"): a for g in services["groups"] for a in g["apps"]}

    return {"system": system, "services": services, "updates": updates,
            "attention": [attention_action(i, cards) for i in items], "attention_items": items,
            "sweeps": rows, "sweep_line": sweep_summary(rows, system["last_sweep"]),
            "history": history}
