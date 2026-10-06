"""Snapshot store — the hub's read side of the frozen envelope contract (D13).

Connectors write /data/snapshots/{id}.json envelopes; the hub reads them here.
The hub NEVER errors because a connector didn't run: a missing directory,
missing file, or malformed file simply means "not connected".
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("hub.store")

DEFAULT_SNAPSHOT_DIR = "/data/snapshots"


@dataclass
class Snapshot:
    connector: str
    status: str
    fetched_at: str
    updated_at: str
    consecutive_failures: int
    error: Optional[str]
    data: dict[str, Any]
    age_minutes: float  # since updated_at (last SUCCESS — what stale badges read)


def _parse(path: Path, now: datetime) -> Optional[Snapshot]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        updated = datetime.fromisoformat(raw["updated_at"].replace("Z", "+00:00"))
        return Snapshot(
            connector=raw["connector"],
            status=raw["status"],
            fetched_at=raw["fetched_at"],
            updated_at=raw["updated_at"],
            consecutive_failures=raw["consecutive_failures"],
            error=raw.get("error"),
            data=raw["data"],
            age_minutes=(now - updated).total_seconds() / 60.0,
        )
    except Exception as exc:  # malformed file == absent, never a crash
        log.warning("snapshot %s unreadable, treating as absent: %s", path.name, exc)
        return None


def _snapshot_dir(snapshot_dir: str | Path | None = None) -> Path:
    return Path(snapshot_dir or os.environ.get("SNAPSHOT_DIR", DEFAULT_SNAPSHOT_DIR))


def get_snapshots(snapshot_dir: str | Path | None = None) -> dict[str, Snapshot]:
    """Read every envelope in the snapshot dir. Missing dir → {}."""
    directory = _snapshot_dir(snapshot_dir)
    if not directory.is_dir():
        return {}
    now = datetime.now(timezone.utc)
    out: dict[str, Snapshot] = {}
    for path in sorted(directory.glob("*.json")):
        snap = _parse(path, now)
        if snap is not None:
            out[snap.connector] = snap
    return out


RUNNER_NAME = "_runner.json"  # connectors/run_all.py's heartbeat (last sweep only)


def get_runner(snapshot_dir: str | Path | None = None) -> Optional[dict[str, Any]]:
    """The connector runner's last-sweep heartbeat (WP-S4, 2026-10-06), from the same dir
    as the envelopes. Missing or malformed → None, never a crash."""
    try:
        raw = json.loads((_snapshot_dir(snapshot_dir) / RUNNER_NAME).read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else None
    except Exception:
        return None


def tile_state(tile, snapshots: dict[str, Snapshot]) -> dict[str, Any]:
    """Resolve one areas.yaml tile against the snapshots: the four states.

    Returns {state: link|fresh|stale|off, value, secondary, age_text, href, note}.
    Display convention (WP18): a tile shows envelope.data["summary"] and the
    optional envelope.data["secondary"] (D17's one secondary line).
    """
    if tile.tier.value == "link":
        return {"state": "link", "href": tile.href, "value": tile.label,
                "secondary": None, "age_text": None, "note": None}

    snap = snapshots.get(tile.snapshot)
    if snap is None or snap.status == "error" and not snap.data:
        return {"state": "off", "value": "Not connected", "secondary": None,
                "age_text": None, "href": None, "note": tile.setup_note}

    age_text = _age_text(snap.age_minutes)
    common = {
        "value": str(snap.data.get("summary", "—")),
        "secondary": snap.data.get("secondary"),
        "href": None, "note": None,
    }
    if snap.age_minutes > tile.stale_after_minutes:
        return {"state": "stale", "age_text": f"stale {age_text}", **common}
    return {"state": "fresh", "age_text": f"{age_text} ago", **common}


def _age_text(minutes: float) -> str:
    if minutes < 60:
        return f"{max(0, int(minutes))}m"
    if minutes < 48 * 60:
        return f"{int(minutes // 60)}h"
    return f"{int(minutes // 1440)}d"
