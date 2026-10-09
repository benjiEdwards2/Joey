"""Watchlist storage (F6, 2026-10-06): titles B. or Georgina want to see, one row per owner
and `tmdb:<id>` key, in the same media.db. Own table (DDL below; media_store creates it with
the rest of media.db). Pure helpers (statuses, sorts, shuffle) live here too."""
from __future__ import annotations

import random
import sqlite3
from contextlib import closing
from datetime import date

from hub import media_db, media_store

DDL = """CREATE TABLE IF NOT EXISTS watchlist(
  owner TEXT, item_key TEXT, kind TEXT, title TEXT, year INT, poster TEXT, tmdb_id INT, added_at TEXT,
  PRIMARY KEY(owner, item_key))"""
SORTS = ("newest", "oldest", "title", "added", "shuffle")
SORT_LABELS = {"added": "Recently added", "newest": "Newest release", "oldest": "Oldest release",
               "title": "A-Z", "shuffle": "Shuffle"}
REQUEST_WORDS = {"pending": "Requested", "approved": "Processing", "processing": "Processing",
                 "requested": "Requested", "partly available": "Partly available"}
ON_DISK = "On disk"
NOT_ON = "Not on server"


def ensure() -> sqlite3.Connection:
    """A connection for a write (media_store)."""
    return media_store.connect()


def _reader():
    """Connection for reads, or None when there is no DB file yet (reads never create it) or it can't be opened."""
    return media_store.reader()


def key_of(tmdb_id) -> str:
    return f"tmdb:{int(tmdb_id)}"


def add(owner: str, row: dict) -> None:
    key = key_of(row["tmdb_id"])
    with closing(ensure()) as db:
        db.execute("""INSERT OR IGNORE INTO watchlist(owner, item_key, kind, title, year, poster, tmdb_id, added_at)
                      VALUES(?,?,?,?,?,?,?,?)""",
                   (owner, key, media_db.norm_kind(row.get("kind")), row["title"], row.get("year"),
                    row.get("poster"), int(row["tmdb_id"]), media_db._now().isoformat()))
        db.commit()


def remove(owner: str, item_key: str) -> None:
    with closing(ensure()) as db:
        db.execute("DELETE FROM watchlist WHERE owner = ? AND item_key = ?", (owner, item_key))
        db.commit()


def rows(owner: str, kind: str | None = None) -> list[dict]:
    sql, args = "SELECT * FROM watchlist WHERE owner = ?", [owner]
    if kind:
        sql, args = sql + " AND kind = ?", args + [media_db.norm_kind(kind)]
    db = _reader()
    if db is None:
        return []
    with closing(db):
        return [dict(r) for r in db.execute(sql + " ORDER BY added_at DESC, item_key", args)]


def contains(owner: str, keys) -> set:
    keys = sorted({k for k in keys if k})
    if not keys:
        return set()
    db = _reader()
    if db is None:
        return set()
    with closing(db):
        marks = ",".join("?" * len(keys))
        return {r["item_key"] for r in db.execute(
            f"SELECT item_key FROM watchlist WHERE owner = ? AND item_key IN ({marks})", [owner, *keys])}


def count_not_on_server(owner: str, kind: str | None, on_server_keys) -> int:
    have = set(on_server_keys or [])
    return sum(1 for r in rows(owner, kind) if r["item_key"] not in have)


def prune_played(owner: str, played_keys, kind: str | None = None) -> int:
    """Drop watched titles from the list in ONE delete (M-38); returns how many left."""
    played = set(played_keys or [])
    gone = sorted(r["item_key"] for r in rows(owner, kind) if r["item_key"] in played)
    if gone:
        with closing(ensure()) as db:
            db.execute(f"DELETE FROM watchlist WHERE owner = ? AND item_key IN ({','.join('?' * len(gone))})",
                       [owner, *gone])
            db.commit()
    return len(gone)


def request_words(requests_rows) -> dict:
    """{(kind, tmdb_id): word} from jellyseerr snapshot `requests` rows; Declined/Available are skipped."""
    out = {}
    for r in requests_rows or []:
        word = REQUEST_WORDS.get(str(r.get("status_text") or "").strip().lower())
        try:
            out[(media_db.norm_kind(r.get("kind")), int(r.get("tmdb_id")))] = word
        except (TypeError, ValueError):
            continue
    return {k: v for k, v in out.items() if v}


def status_word(row: dict, on_server_keys, words: dict) -> str:
    if row["item_key"] in on_server_keys:
        return ON_DISK
    return words.get((row["kind"], row["tmdb_id"])) or NOT_ON


def sort_rows(rows, sort: str, owner: str = "", kind: str = "", today: date | None = None):
    title = lambda r: (r["title"] or "").lower()
    if sort == "newest":
        return sorted(rows, key=lambda r: (-(r["year"] or 0), title(r)))
    if sort == "oldest":
        return sorted(rows, key=lambda r: (r["year"] is None, r["year"] or 0, title(r)))
    if sort == "title":
        return sorted(rows, key=title)
    if sort == "shuffle":  # holds still for a day
        out = sorted(rows, key=lambda r: r["item_key"])
        random.Random(f"{today or date.today()}:{owner}:{kind}").shuffle(out)
        return out
    return sorted(rows, key=lambda r: (r["added_at"] or "", r["item_key"]), reverse=True)

