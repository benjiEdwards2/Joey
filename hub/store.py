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


def parse_utc(value) -> Optional[datetime]:
    """An ISO timestamp as an aware datetime (naive = UTC; 'Z' and Jellyfin's 7-digit fractions accepted by
    Python 3.12's fromisoformat); None when it is not one. The one parser for the hub core (H-21)."""
    try:
        at = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return at if at.tzinfo else at.replace(tzinfo=timezone.utc)


def _parse(path: Path) -> Optional[tuple[dict[str, Any], datetime]]:
    """(Snapshot fields without age, updated_at as a datetime); None for a malformed file."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        updated = parse_utc(raw["updated_at"])
        if updated is None:
            raise ValueError("updated_at is not a timestamp")
        return {
            "connector": raw["connector"],
            "status": raw["status"],
            "fetched_at": raw["fetched_at"],
            "updated_at": raw["updated_at"],
            "consecutive_failures": raw["consecutive_failures"],
            "error": raw.get("error"),
            "data": raw["data"],
        }, updated
    except Exception as exc:  # malformed file == absent, never a crash
        log.warning("snapshot %s unreadable, treating as absent: %s", path.name, type(exc).__name__)
        return None


def _snapshot_dir(snapshot_dir: str | Path | None = None) -> Path:
    return Path(snapshot_dir or os.environ.get("SNAPSHOT_DIR", DEFAULT_SNAPSHOT_DIR))


# H-48 (2026-10-09): every request used to re-parse every envelope (the jellyfin one carries whole libraries) up
# to four times. Each file is now parsed once per (st_mtime_ns, st_size); a file changed in the last
# FRESH_GUARD_S is always re-read (filesystems with coarse mtimes), and age_minutes is recomputed on every call.
# The parsed `data` is shared between calls: treat Snapshot.data as read-only.
FRESH_GUARD_S = 1.0
_PARSED: dict[str, dict[str, tuple]] = {}   # dir -> {file name: ((mtime_ns, size), parsed or None)}
_PARSED_DIRS_MAX = 8


def _cached_parse(path: Path, seen: dict[str, tuple], prev: dict[str, tuple], now: datetime):
    try:
        st = path.stat()
    except OSError:
        return None
    sig = (st.st_mtime_ns, st.st_size)
    hit = prev.get(path.name)
    if hit is not None and hit[0] == sig and now.timestamp() - st.st_mtime >= FRESH_GUARD_S:
        parsed = hit[1]
    else:
        parsed = _parse(path)
    seen[path.name] = (sig, parsed)
    return parsed


def get_snapshots(snapshot_dir: str | Path | None = None) -> dict[str, Snapshot]:
    """Read every envelope in the snapshot dir. Missing dir → {}."""
    directory = _snapshot_dir(snapshot_dir)
    if not directory.is_dir():
        return {}
    now = datetime.now(timezone.utc)
    key = str(directory)
    prev, seen = _PARSED.get(key, {}), {}
    out: dict[str, Snapshot] = {}
    for path in sorted(directory.glob("*.json")):
        if path.name.startswith("_"):  # _runner.json etc. are heartbeats, not envelopes
            continue
        parsed = _cached_parse(path, seen, prev, now)
        if parsed is not None:
            fields, updated = parsed
            out[fields["connector"]] = Snapshot(**fields, age_minutes=(now - updated).total_seconds() / 60.0)
    if key not in _PARSED and len(_PARSED) >= _PARSED_DIRS_MAX:
        _PARSED.clear()  # tests use many temp dirs; production has one
    _PARSED[key] = seen   # only the files still there
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


HISTORY_NAME = "_runner_history.jsonl"  # run_all.py: one JSON line per sweep, append-only
# 24 h is ~720 fast (120 s) sweeps + 24 hourly ones; read only the file's tail.
HISTORY_MAX_LINES = 1000
HISTORY_MAX_BYTES = 2 * 1024 * 1024


def get_runner_history(snapshot_dir: str | Path | None = None,
                       max_lines: int = HISTORY_MAX_LINES,
                       max_bytes: int = HISTORY_MAX_BYTES) -> Optional[list[dict[str, Any]]]:
    """The tail of `_runner_history.jsonl` (WP-U2, 2026-10-06), oldest first: at most
    `max_lines` parsed sweep lines from the last `max_bytes`. Malformed lines are skipped;
    a missing or unreadable file → None (callers fall back to `_runner.json`)."""
    path = _snapshot_dir(snapshot_dir) / HISTORY_NAME
    try:
        with path.open("rb") as fh:
            size = fh.seek(0, os.SEEK_END)
            start = max(0, size - max_bytes)
            fh.seek(start)
            raw = fh.read()
    except Exception:
        return None
    lines = raw.split(b"\n")
    if start > 0:
        lines = lines[1:]  # the first line is cut mid-way
    out: list[dict[str, Any]] = []
    for line in lines:  # bounded by max_bytes
        try:
            item = json.loads(line)
        except Exception:
            continue
        if isinstance(item, dict):
            out.append(item)
    return out[-max_lines:]


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

    age_text = ago_text(snap.age_minutes)
    common = {
        "value": str(snap.data.get("summary", "—")),
        "secondary": snap.data.get("secondary"),
        "href": None, "note": None,
    }
    if snap.age_minutes > tile.stale_after_minutes:
        return {"state": "stale", "age_text": f"Stale · {age_text}", **common}
    return {"state": "fresh", "age_text": age_text, **common}


def ago_text(minutes: float) -> str:
    """'just now' / '12m ago' / '3h ago' / '2d ago' — the ONE relative-time format of the hub core (H-20): tile ages,
    the Server page and Media's added / watched words all use it."""
    minutes = max(0, int(minutes))
    if minutes < 1:
        return "just now"
    if minutes < 60:
        return f"{minutes}m ago"
    if minutes < 48 * 60:
        return f"{minutes // 60}h ago"
    return f"{minutes // 1440}d ago"
