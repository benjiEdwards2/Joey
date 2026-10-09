"""Uptime Kuma monitor states from its Prometheus /metrics (Server area)."""

from __future__ import annotations

import os
import re

from connectors.base import Connector
from connectors.feeds._http import http_json


# Uptime Kuma 1.23 (2026-10-06, WP-S4). Raw shape (fixture and live) IS the Prometheus
# text exposition of GET {UPTIME_KUMA_URL}/metrics — HTTP Basic with an EMPTY username
# and the API key as password. Only `monitor_status` (1 up, 0 down, 2 pending,
# 3 maintenance) and `monitor_response_time` (ms; -1 = no ping) are read. The
# monitor_url / monitor_hostname / monitor_port labels are never copied out — they can
# carry LAN addresses and tokens.

KUMA_STATUS = {1: "up", 0: "down", 2: "pending", 3: "maintenance"}
KUMA_ORDER = {"down": 0, "pending": 1, "maintenance": 2, "up": 3}
_KUMA_LINE = re.compile(r"^(monitor_status|monitor_response_time)\{(.*)\}\s+(\S+)\s*$")
_KUMA_LABEL = re.compile(r'(\w+)="((?:[^"\\]|\\.)*)"')


def _kuma_parse(text) -> dict[str, dict]:
    """Exposition text -> {label-string: {labels, status, response}}. Anything that does
    not look like Uptime Kuma metrics raises a reason-free error (no label echo)."""
    bad = RuntimeError("Uptime Kuma metrics failed (unexpected payload)")
    if not isinstance(text, str) or "monitor_status" not in text:
        raise bad
    monitors: dict[str, dict] = {}
    for line in text.splitlines():
        if not line.startswith(("monitor_status", "monitor_response_time")):
            continue
        m = _KUMA_LINE.match(line.strip())
        if not m:
            raise bad
        metric, label_text, value = m.groups()
        labels = dict(_KUMA_LABEL.findall(label_text))
        if "monitor_name" not in labels:
            raise bad
        try:
            number = float(value)
        except ValueError:
            raise bad from None
        row = monitors.setdefault(label_text, {"labels": labels, "status": None, "response": None})
        if metric == "monitor_status":
            if number not in KUMA_STATUS:
                raise bad
            row["status"] = KUMA_STATUS[int(number)]
        else:
            row["response"] = int(round(number)) if number >= 0 else None
    return monitors


class UptimeKuma(Connector):
    """Uptime Kuma monitor states (Server area)."""

    id = "uptime_kuma"
    requires_env = ("UPTIME_KUMA_URL", "UPTIME_KUMA_API_KEY")

    def fetch(self) -> str:
        # One call, so no session.
        return http_json("Uptime Kuma metrics", os.environ["UPTIME_KUMA_URL"].rstrip("/") + "/metrics",
                         auth=("", os.environ["UPTIME_KUMA_API_KEY"]), text=True)

    def transform(self, raw: str) -> dict:
        monitors = [
            {"name": str(row["labels"]["monitor_name"]),
             "type": str(row["labels"].get("monitor_type") or ""),
             "status": row["status"],
             "response_ms": row["response"] if row["status"] == "up" else None}
            for row in _kuma_parse(raw).values() if row["status"] is not None
        ]
        monitors.sort(key=lambda m: (KUMA_ORDER[m["status"]], m["name"].lower()))
        up = sum(m["status"] == "up" for m in monitors)
        down = [m["name"] for m in monitors if m["status"] == "down"]
        total = len(monitors)
        if down:
            secondary = f"{down[0]} down" + (f" (+{len(down) - 1} more)" if len(down) > 1 else "")
        else:
            secondary = f"{total} monitor{'' if total == 1 else 's'}"
        return {
            "summary": f"{up} of {total} up" if total else "No monitors",
            "secondary": secondary,
            "up": up,
            "down": len(down),
            "total": total,
            "monitors": monitors,
        }
