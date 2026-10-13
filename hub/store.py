"""Snapshot store — the hub's read side of the frozen envelope contract (D13).

Connectors write /data/snapshots/{id}.json envelopes; the hub reads them here.
The hub NEVER errors because a connector didn't run: a missing directory,
missing file, or malformed file simply means "not connected".
"""

from __future__ import annotations

import json
import logging
import os
import threading
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


# E1 (2026-10-13): the history file is append-only between rotations, and the hub read its 2 MB tail on every Server
# page and every hub-card refresh (~110 ms on the NAS). The parsed lines are now kept per (file, max_bytes) with the
# file's identity (device, inode), size and mtime: unchanged → the same list back (callers treat it as read-only);
# grown → only the new bytes are parsed; shrunk, replaced (run_all's rotation is tmp + os.replace) or rewritten in
# place → read afresh. The answer is exactly what a full re-read would give.
_HISTORY: dict[tuple[str, int], dict] = {}
_HISTORY_LOCK = threading.Lock()
_HISTORY_MAX = 8   # tests use many temp dirs; production has one


def _parse_line(raw: bytes):
    try:
        item = json.loads(raw)
    except Exception:
        return None
    return item if isinstance(item, dict) else None


def _history_lines(fh, begin: int, end: int) -> tuple[list[tuple[int, Any]], int]:
    """Parse file[begin:end] -> ([(line start offset, dict or None)] for every newline-terminated line, the offset
    where the unterminated remainder starts)."""
    fh.seek(begin)
    raw = fh.read(end - begin)
    recs, pos = [], 0
    while True:
        nl = raw.find(b"\n", pos)
        if nl < 0:
            break
        recs.append((begin + pos, _parse_line(raw[pos:nl])))
        pos = nl + 1
    return recs, begin + pos


def get_runner_history(snapshot_dir: str | Path | None = None,
                       max_lines: int = HISTORY_MAX_LINES,
                       max_bytes: int = HISTORY_MAX_BYTES) -> Optional[list[dict[str, Any]]]:
    """The tail of `_runner_history.jsonl` (WP-U2, 2026-10-06), oldest first: at most
    `max_lines` parsed sweep lines from the last `max_bytes`. Malformed lines are skipped;
    a missing or unreadable file → None (callers fall back to `_runner.json`). Kept in memory between calls and
    extended by the appended bytes only (E1); the list returned is shared — read-only."""
    path = _snapshot_dir(snapshot_dir) / HISTORY_NAME
    key = (str(path), max_bytes)
    try:
        with path.open("rb") as fh:
            st = os.fstat(fh.fileno())
            sig = (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns)
            with _HISTORY_LOCK:
                kept = _HISTORY.get(key)
            if kept is not None and kept["sig"] == sig and kept["max_lines"] == max_lines:
                return kept["out"]
            size = st.st_size
            start = max(0, size - max_bytes)
            grown = (kept is not None and kept["sig"][:2] == sig[:2] and kept["sig"][2] <= size
                     and kept["rest"] >= start and (kept["sig"][2] < size or kept["sig"][3] == sig[3]))
            if grown:
                new, rest = _history_lines(fh, kept["rest"], size)
                recs = kept["recs"] + new
            else:
                recs, rest = _history_lines(fh, start, size)
            tail = None
            if rest < size:   # a last line not yet newline-terminated: read now, re-read when the file grows
                fh.seek(rest)
                tail = _parse_line(fh.read(size - rest))
    except Exception:
        return None
    # the first line of the window is cut mid-way unless the window starts at the file's beginning (a line starting
    # exactly at `start` is dropped too - as the full read always did)
    recs = [r for r in recs if r[0] > start or start == 0]
    out = [item for _, item in recs if item is not None]
    if tail is not None and (rest > start or start == 0):
        out.append(tail)
    out = out[-max_lines:]
    with _HISTORY_LOCK:
        if key not in _HISTORY and len(_HISTORY) >= _HISTORY_MAX:
            _HISTORY.clear()
        _HISTORY[key] = {"sig": sig, "recs": recs, "rest": rest, "out": out, "max_lines": max_lines}
    return out


def connected(snap: Optional[Snapshot]) -> bool:
    """THE "is there something to show" rule (H-33): an envelope exists and is not an error with no data. An error
    envelope that still carries the last good data IS connected — it shows that data and ages into "stale" (the
    connector keeps `updated_at` at its last success)."""
    return snap is not None and not (snap.status == "error" and not snap.data)


def data_of(snap: Optional[Snapshot]) -> dict[str, Any]:
    """A connected envelope's data as a dict; {} otherwise."""
    return snap.data if connected(snap) and isinstance(snap.data, dict) else {}


def tile_state(tile, snapshots: dict[str, Snapshot]) -> dict[str, Any]:
    """Resolve one areas.yaml tile against the snapshots: the four states.

    Returns {state: link|fresh|stale|off, value, secondary, age_text, href, note}. (The hub Server card adds a
    fifth, `warn` — "Needs attention" — styled like stale; hub/main.py server_card_state.)
    Display convention (WP18): a tile shows envelope.data["summary"] and the
    optional envelope.data["secondary"] (D17's one secondary line).
    """
    if tile.tier.value == "link":
        return {"state": "link", "href": tile.href, "value": tile.label,
                "secondary": None, "age_text": None, "note": None}

    snap = snapshots.get(tile.snapshot)
    if not connected(snap):
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
