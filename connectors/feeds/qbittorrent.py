"""qBittorrent Web API, read only: downloading, finished in 24 h, seeding, transfer speeds, the global download cap."""

from __future__ import annotations

import os
from datetime import datetime, timezone

from connectors.base import Connector
from connectors.feeds._common import _duration_words, _now
from connectors.feeds._http import http_json, session


QBIT_ROW_LIMIT = 20
QBIT_FINISHED_WINDOW = 86400  # seconds: "finished today" = completed in the last 24 h
QBIT_ETA_INFINITE = 8640000   # qBittorrent's "no ETA" sentinel
# Download-side states -> a word, never a colour.
QBIT_ACTIVE_STATES = {
    "downloading": "Downloading", "forcedDL": "Downloading", "stalledDL": "Stalled",
    "metaDL": "Fetching metadata", "forcedMetaDL": "Fetching metadata",
    "pausedDL": "Paused", "stoppedDL": "Paused", "queuedDL": "Queued",
    "checkingDL": "Checking", "allocating": "Allocating",
}
QBIT_PAUSED_STATES = {"pausedDL", "stoppedDL"}
QBIT_SEEDING_STATES = {"uploading", "stalledUP", "forcedUP", "queuedUP", "pausedUP", "stoppedUP"}


def _bytes_text(n) -> str:
    """Decimal units, as a person reads them: '230 kB', '1.4 MB', '900 MB', '4.2 GB'.
    kB and anything >= 100 are whole numbers; smaller MB/GB/TB keep one decimal."""
    value = float(n or 0)
    if value < 1000:
        return f"{int(value)} B"
    for unit in ("kB", "MB", "GB", "TB"):
        value /= 1000
        if value < 999.5 or unit == "TB":
            break
    return f"{value:.0f} {unit}" if unit == "kB" or value >= 99.95 else f"{value:.1f} {unit}"


def _limit_text(bps) -> str | None:
    """P4 (2026-10-22): the global download cap in bits, as qBittorrent's users say it: 0 -> 'Unlimited',
    625000 B/s -> '5 Mbps' (one decimal under 10 Mbps, trailing .0 dropped), under 0.1 Mbps in kbps. None stays None."""
    if bps is None:
        return None
    if bps <= 0:
        return "Unlimited"
    mbps = bps * 8 / 1e6
    if mbps < 0.1:
        return f"{round(bps * 8 / 1000)} kbps"
    return f"{mbps:.0f} Mbps" if mbps >= 9.95 else f"{mbps:.1f}".rstrip("0").rstrip(".") + " Mbps"


def _eta_text(seconds) -> str:
    """qBittorrent eta seconds -> '12m' / '2h 05m' (blank when unknown or infinite)."""
    try:
        seconds = int(seconds)
    except (TypeError, ValueError):
        return ""
    if seconds <= 0 or seconds >= QBIT_ETA_INFINITE:
        return ""
    return _duration_words(max(1, round(seconds / 60)))


def _qbit_kind(category) -> str:
    cat = str(category or "").lower()
    if "radarr" in cat or "movie" in cat:
        return "movie"
    if "sonarr" in cat or "tv" in cat:
        return "tv"
    return "other"


def _epoch_iso(ts) -> str:
    return datetime.fromtimestamp(int(ts or 0), timezone.utc).isoformat(timespec="seconds")


class QBittorrent(Connector):
    """qBittorrent Web API, read only: what is downloading, what finished in the
    last 24 h, how much is seeding, and the global transfer speeds."""

    id = "qbittorrent"
    requires_env = ("QBIT_URL", "QBIT_USER", "QBIT_PASS")

    def fetch(self) -> dict:
        base = os.environ["QBIT_URL"].rstrip("/")
        client = session()  # the login cookie lives on it, then both reads reuse it
        try:
            try:
                http_json("qBittorrent login", f"{base}/api/v2/auth/login", method="POST",
                          data={"username": os.environ["QBIT_USER"], "password": os.environ["QBIT_PASS"]},
                          headers={"Referer": base}, session=client, text=True)
            except RuntimeError as exc:
                if exc.reason.startswith("HTTP 4"):  # 401/403: the credentials, not the server
                    raise RuntimeError("login refused") from None
                raise
            # 5.x answers 204 + empty body; older builds 200 "Ok." / "Fails.". Either
            # way the session cookie (SID / QBT_SID / QBT_SID_<port>) is the proof.
            if not any(c.name == "SID" or c.name.startswith("QBT_SID") for c in client.cookies):
                raise RuntimeError("login refused")
            return {key: http_json(f"qBittorrent {step}", base + path, session=client)
                    for step, key, path in (("torrents", "raw_torrents", "/api/v2/torrents/info"),
                                            ("transfer", "raw_transfer", "/api/v2/transfer/info"))}
        finally:
            client.close()

    def transform(self, raw: dict) -> dict:
        now = _now().timestamp()
        torrents = raw.get("raw_torrents") or []
        transfer = raw.get("raw_transfer") or {}

        def size_text(t: dict) -> str:
            return _bytes_text(t.get("size") or t.get("total_size"))

        active = [t for t in torrents if t.get("state") in QBIT_ACTIVE_STATES]
        # downloading-with-speed first, then by progress (desc); stable for ties
        active.sort(key=lambda t: (int(t.get("dlspeed") or 0) > 0, float(t.get("progress") or 0)),
                    reverse=True)
        active_rows = []
        for t in active[:QBIT_ROW_LIMIT]:
            state, speed = t["state"], int(t.get("dlspeed") or 0)
            active_rows.append({
                "hash": str(t.get("hash") or "").lower(),
                "name": str(t.get("name") or "Unknown"),
                "kind": _qbit_kind(t.get("category")),
                "category": str(t.get("category") or ""),
                "pct": min(100, max(0, int(float(t.get("progress") or 0) * 100))),
                "state_text": QBIT_ACTIVE_STATES[state],
                "speed_text": f"{_bytes_text(speed)}/s" if speed > 0 else "",
                "eta_text": "" if state in QBIT_PAUSED_STATES else _eta_text(t.get("eta")),
                "size_text": size_text(t),
                "added": _epoch_iso(t.get("added_on")),
            })

        done = [t for t in torrents
                if int(t.get("completion_on") or 0) > 0
                and now - int(t["completion_on"]) <= QBIT_FINISHED_WINDOW]
        done.sort(key=lambda t: int(t["completion_on"]), reverse=True)
        finished = [{
            "hash": str(t.get("hash") or "").lower(),
            "name": str(t.get("name") or "Unknown"),
            "kind": _qbit_kind(t.get("category")),
            "size_text": size_text(t),
            "when": _epoch_iso(t["completion_on"]),
        } for t in done[:QBIT_ROW_LIMIT]]

        seeding = sum(1 for t in torrents if t.get("state") in QBIT_SEEDING_STATES)
        dl, up = int(transfer.get("dl_info_speed") or 0), int(transfer.get("up_info_speed") or 0)
        totals = {"dl_bps": dl, "up_bps": up,
                  "dl_text": f"{_bytes_text(dl)}/s", "up_text": f"{_bytes_text(up)}/s"}
        try:   # P4 (2026-10-22): transfer/info's dl_rate_limit (bytes/s, 0 = no cap); null when the answer lacks it
            dl_limit = max(0, int(transfer["dl_rate_limit"]))
        except (KeyError, TypeError, ValueError):
            dl_limit = None

        if active:
            summary = f"{len(active)} downloading" + (f" · {totals['dl_text']}" if dl > 0 else "")
        else:
            summary = "Nothing downloading"
        finished_text = f"{len(done)} finished today" if done else "Nothing finished today"
        return {
            "summary": summary,
            "secondary": f"{seeding} seeding · {finished_text}" if seeding else finished_text,
            "active": active_rows,
            "finished": finished,
            "seeding": seeding,
            "totals": totals,
            "dl_limit_bps": dl_limit,
            "dl_limit_text": _limit_text(dl_limit),
        }
