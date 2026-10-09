"""Backups of media.db (2026-10-05) — the hub's only write path, kept as gzip dumps
in `MEDIA_BACKUP_DIR` (default /data/backups/media). Runs inside the hub process
(see `lifespan` in hub/main.py); the NAS is off overnight, so the startup check is
what gives one backup per day.

Every file named media-YYYY-MM-DD_HHMM.db.gz (UTC) is a whole, integrity-checked
backup: work happens in dot-prefixed temp files and only an atomic rename makes a
dump visible. Pure functions take `now` and paths; the env readers sit at the end.
"""

from __future__ import annotations

import gzip
import logging
import os
import re
import shutil
import sqlite3
import tempfile
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

from hub import media_db
from hub.store import ago_text

log = logging.getLogger("hub.media_backup")

DEFAULT_BACKUP_DIR = "/data/backups/media"
NAME_RE = re.compile(r"^media-(\d{4}-\d{2}-\d{2}_\d{4})\.db\.gz$")
NAME_FMT = "%Y-%m-%d_%H%M"
STALE_AFTER = timedelta(hours=36)
FRESH_ENOUGH = timedelta(hours=20)   # maybe_backup skips while the newest is younger
KEEP_ALL_DAYS = 30
KEEP_MONTHLY_MONTHS = 24


def _integrity(db: sqlite3.Connection) -> str:
    return db.execute("PRAGMA integrity_check").fetchone()[0]


def _unlink(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def backup_now(db_path, dest_dir, now: datetime) -> Path:
    """Copy, check, gzip, rename. Raises on any failure and leaves nothing partial."""
    db_path, dest_dir = Path(db_path), Path(dest_dir)
    if not db_path.is_file():
        raise FileNotFoundError(f"no database at {db_path}")
    if not dest_dir.is_dir():
        raise FileNotFoundError(f"no backup folder at {dest_dir}")
    final = dest_dir / f"media-{now.strftime(NAME_FMT)}.db.gz"
    fd, raw = tempfile.mkstemp(dir=dest_dir, prefix=".media-", suffix=".db.tmp")
    os.close(fd)
    raw = Path(raw)
    packed = raw.with_suffix(".gz.tmp")
    try:
        with closing(sqlite3.connect(db_path, timeout=5)) as src, \
                closing(sqlite3.connect(raw)) as dst:
            src.backup(dst)
            dst.execute("PRAGMA journal_mode=DELETE")  # a plain single-file copy, no -wal
            result = _integrity(dst)
        if result != "ok":
            raise ValueError(f"integrity_check said {result!r}")
        if raw.stat().st_size <= 0:
            raise ValueError("backup copy is empty")
        with open(raw, "rb") as fin, gzip.open(packed, "wb") as fout:
            shutil.copyfileobj(fin, fout)
        os.replace(packed, final)
    finally:
        _unlink(raw)
        _unlink(packed)
    return final


def _dumps(dest_dir) -> list[tuple[datetime, Path]]:
    """(taken_at, path) for every well-named dump, oldest first. Temp files are ignored."""
    out = []
    try:
        entries = list(Path(dest_dir).iterdir())
    except OSError:
        return []
    for p in entries:
        m = NAME_RE.match(p.name)
        if m and p.is_file():
            try:
                taken = datetime.strptime(m.group(1), NAME_FMT).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            out.append((taken, p))
    return sorted(out)


def _months_back(now: datetime, months: int) -> datetime:
    index = now.year * 12 + (now.month - 1) - months
    year, month = divmod(index, 12)
    day = min(now.day, 28)
    return now.replace(year=year, month=month + 1, day=day)


def prune(dest_dir, now: datetime) -> list[Path]:
    """Keep every dump from the last 30 days, then the first dump of each month for
    24 months; delete the rest. Callers prune only after a successful new backup."""
    recent = now - timedelta(days=KEEP_ALL_DAYS)
    monthly = _months_back(now, KEEP_MONTHLY_MONTHS)
    seen_months = set()
    removed = []
    for taken, path in _dumps(dest_dir):  # oldest first, so the first per month wins
        month = (taken.year, taken.month)
        first_of_month = month not in seen_months
        seen_months.add(month)
        if taken >= recent or (first_of_month and taken >= monthly):
            continue
        _unlink(path)
        removed.append(path)
    return removed


def newest(dest_dir, now: datetime | None = None) -> dict | None:
    dumps = _dumps(dest_dir)
    if not dumps:
        return None
    taken, path = dumps[-1]
    now = now or datetime.now(timezone.utc)
    return {"path": path, "taken_at": taken, "age_seconds": (now - taken).total_seconds(),
            "size_bytes": path.stat().st_size}


def _ago(seconds: float) -> str:
    """The hub's one relative-time format (store.ago_text: 'just now' / '12m ago' / '3h ago' / '2d ago')."""
    return ago_text(seconds / 60)


def _gap(seconds: float) -> str:
    """'40 hours' / '2 days' — how long since the last backup, for the warning line."""
    if seconds < 2 * 86400:
        return f"{int(seconds // 3600)} hours"
    return f"{int(seconds // 86400)} days"


def _size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{round(n / 1024)} KB"
    return f"{n / (1024 * 1024):.1f} MB"


def _dir_problem(dest_dir) -> str | None:
    if not dest_dir:
        return "no backup folder set"
    p = Path(dest_dir)
    if not p.is_dir():
        return "backup folder missing"
    if not os.access(p, os.W_OK):
        return "backup folder not writable"
    return None


def status(db_path, dest_dir, now: datetime) -> dict:
    """state: ok | stale | none | nodb | off — plus words for the pages."""
    out = {"state": "ok", "note": None, "age_text": "", "size_text": "", "warning": None}
    if not Path(db_path).is_file():
        return {**out, "state": "nodb"}
    problem = _dir_problem(dest_dir)
    if problem:
        return {**out, "state": "off", "note": problem}
    top = newest(dest_dir, now)
    if top is None:
        return {**out, "state": "none", "warning": "Media backup: none yet"}
    age = top["age_seconds"]
    out.update(age_text=_ago(age), size_text=_size(top["size_bytes"]))
    if age > STALE_AFTER.total_seconds():
        out.update(state="stale", warning=f"Media backup: none in {_gap(age)}")
    return out


# --- env readers (the hub's entry points) -------------------------------------

def backup_dir() -> str:
    return os.environ.get("MEDIA_BACKUP_DIR", DEFAULT_BACKUP_DIR)


def disabled() -> bool:
    return os.environ.get("MEDIA_BACKUP", "").strip().lower() == "off"


def current_status(now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    st = status(media_db.db_path(), backup_dir(), now)
    if disabled() and st["state"] != "nodb":
        st = {**st, "state": "off", "note": "turned off", "warning": None}
    return st


def run_backup(now: datetime | None = None) -> bool:
    """Backup then prune. Never raises; one log line; False when skipped or failed."""
    now = now or datetime.now(timezone.utc)
    db, dest = media_db.db_path(), backup_dir()
    if not db.is_file():
        return False
    problem = _dir_problem(dest)
    if problem:
        log.info("media backup skipped: %s", problem)
        return False
    try:
        made = backup_now(db, dest, now)
        removed = prune(dest, now)
    except Exception as exc:
        log.warning("media backup failed: %s: %s", type(exc).__name__, exc)
        return False
    log.info("media backup ok: %s (%s), pruned %d", made.name, _size(made.stat().st_size), len(removed))
    return True


def maybe_backup(now: datetime | None = None) -> bool:
    """run_backup only when no backup is newer than 20 hours."""
    now = now or datetime.now(timezone.utc)
    top = newest(backup_dir(), now)
    if top is not None and top["age_seconds"] < FRESH_ENOUGH.total_seconds():
        return False
    return run_backup(now)
