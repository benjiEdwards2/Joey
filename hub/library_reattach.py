"""JY-264 phases 2-3: re-attach Joey's rows after a Jellyfin library rebuild (spec docs/specs/JY-264-engine-seam.md,
sections 2.3-3.3).

A rebuild (library removed and re-added, a fresh install, a move without /config) gives every item a new Jellyfin
id. hub/library_index.py keeps every id Joey has seen, with its provider ids and path, and marks one gone when a
complete library fetch no longer lists it. This module maps each gone id Joey's rows still point at to its new id
and rewrites those cells (B. 2026-10-28, Q1 A: old `jf:` keys become the new `jf:` ids).

Matching, same kind only, first hit wins:
  movie   tmdb, then imdb  -> exact path  -> title + year (weak)
  series  tvdb, tmdb, imdb -> exact path  -> title + year (weak)
  season / episode: through a strongly matched series, by season (+ episode) number, else the episode's file path;
  one GET /Shows/{new series id}/Episodes per affected series, during a run only.
Two candidates on a tier: the path, then title + year, break the tie; still two = ambiguous (never applied).
Paths are compared after stripping LIBRARY_PATH_PREFIXES (comma-separated), so a move between mounts still matches.

When it runs (Q2 A): `auto()` after each index sync. A rebuild is suspected when a referenced movie or series has
been missing from two complete fetches in a row and both fetches' counts are within 5 % of the library's baseline
count (a half-scanned library holds the run). Strong matches (provider id, path) then apply on their own; weak
(title + year) and ambiguous ones only go into the report (a `reattach_run` row with mode `report`).
By hand: `python -m hub.library_reattach --dry-run | --latest | --apply | --apply-report <run_id> | --undo <run_id>`
(PASS / FAIL lines + a log file; no Jellyfin ids or paths in the output). From B.'s computer: scripts/joey_reattach.py.

Safety: an SQLite backup of media.db first (MEDIA_BACKUP_DIR/media-pre-reattach-<run_id>.db); one transaction;
never deletes a row; a cell whose new value would break a key is left as it is and listed as a conflict; every
changed cell is logged in `reattach_change`; poster store folders (JY-260) and poster rows are copied to the new
id, never moved; undo puts back only cells that still hold the value the run wrote, and removes only the copies.
An undone run's ids are not re-applied by `auto()`.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import shutil
import sqlite3
import sys
from collections import defaultdict
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from hub import library_index, media_store

log = logging.getLogger("hub.library_reattach")

GUARD_PCT = 5
MIN_FETCHES_AUTO = 2
AUTO_MAX_PCT = 25     # auto moves at most this share of the indexed items in one run, unless the whole run is
                      # provider-id matches on a steady library count (a full rebuild); otherwise a report only
PROVIDER_TIERS = {"tmdb", "tvdb", "imdb"}
KEEP_BACKUPS = 5      # pre-reattach backups kept (newest first)
BACKUP_RE = re.compile(r"^media-pre-reattach-(\d+)\.db$")
# a copied poster row starts with no Jellyfin write-back state: that state (what Joey wrote, the original it saved,
# its locks) belongs to the OLD item id (review 2026-10-28)
POSTER_RESET = {"orig_ext": None, "orig_tag": None, "wrote": 0, "pending_ver": None, "live_ver": None,
                "live_tag": None, "locked_by_us": 0, "manual": 0, "fails": 0, "retry_at": None, "lock_owner": None,
                "lock_until": None, "written_at": None, "checked_at": None, "last_error": None}
# every column that holds a Jellyfin item id: "key" = `jf:<id>`, "bare" = the id itself (spec section 1). The
# `poster` columns hold the `jf:<id>` image ref of the row's art: moved too, or the row's picture breaks.
COLUMNS = (
    ("rating", "item_key", "key"), ("rating", "poster", "key"),
    ("diary", "item_key", "key"), ("diary", "show_key", "key"), ("diary", "season_key", "key"),
    ("diary", "poster", "key"),
    ("ranking", "item_key", "key"), ("ranking", "poster", "key"),
    ("nextup_hidden", "series_key", "key"), ("nextup_hidden", "episode_id", "bare"),
    ("rating_skip", "key", "key"), ("rating_skip", "poster", "key"),
    ("watchlist", "item_key", "key"), ("watchlist", "poster", "key"),
    ("play", "jf_id", "bare"), ("play", "item_key", "key"), ("play", "show_key", "key"),
    ("play", "season_key", "key"), ("play", "episode_key", "key"), ("play", "poster", "key"),
)
TIERS = {"movie": (("tmdb", "tmdb_id"), ("imdb", "imdb_id")),
         "series": (("tvdb", "tvdb_id"), ("tmdb", "tmdb_id"), ("imdb", "imdb_id"))}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _tables(db) -> set[str]:
    return {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def _bare(value, form: str) -> str | None:
    if not isinstance(value, str):
        return None
    if form == "key":
        return value[3:] if value.startswith("jf:") else None
    return value


def _cell(new_id: str, form: str) -> str:
    return f"jf:{new_id}" if form == "key" else new_id


def _prefixes() -> list[str]:
    raw = os.environ.get("LIBRARY_PATH_PREFIXES", "")
    return sorted({p.strip().replace("\\", "/").rstrip("/") for p in raw.split(",") if p.strip()}, key=len,
                  reverse=True)


def _npath(path, prefixes) -> str | None:
    if not path:
        return None
    p = str(path).replace("\\", "/")
    for pre in prefixes:
        if p == pre or p.startswith(pre + "/"):
            return p[len(pre):]
    return p


def _ntitle(title) -> str:
    return re.sub(r"[^0-9a-z]+", "", str(title or "").casefold())


def _referenced(db, tables: set[str]) -> set[str]:
    out = set()
    for table, col, form in COLUMNS:
        if table not in tables:
            continue
        cond = f"{col} LIKE 'jf:%'" if form == "key" else f"{col} IS NOT NULL"
        out |= {_bare(r[0], form) for r in db.execute(f"SELECT DISTINCT {col} FROM {table} WHERE {cond}")}
    if "poster" in tables:
        out |= {r[0] for r in db.execute("SELECT jf_id FROM poster")}
    out.discard(None)
    return out


def _undone_ids(db) -> set[str]:
    return {r[0] for r in db.execute(
        "SELECT c.row_ref FROM reattach_change c JOIN reattach_run r ON r.id = c.run_id "
        "WHERE r.undone_at IS NOT NULL AND c.table_name = 'library_index'")}


def _episodes(series_id: str) -> list[dict] | None:
    """One GET /Shows/{id}/Episodes (the new series' episodes, with their paths); None when it can't be read."""
    from hub import media_jellyfin
    creds = media_jellyfin.creds()
    if creds is None:
        return None
    base, headers = creds
    params = {"Fields": "Path,ProviderIds"}
    try:
        uid = media_jellyfin.user_id("you", base, headers)
        if uid:
            params["userId"] = uid
        body = media_jellyfin.get(base, headers, f"/Shows/{series_id}/Episodes", params)
    except Exception as exc:
        log.warning("re-attach episodes read failed: %s", type(exc).__name__)
        return None
    items = body.get("Items") if isinstance(body, dict) else None
    return [i for i in items if isinstance(i, dict)] if isinstance(items, list) else None


def _label(row: dict, series: dict | None = None) -> str:
    if row["kind"] in ("movie", "series"):
        return row.get("title") or row["jf_id"]
    show = (series or {}).get("title") or "Series"
    if row["kind"] == "season":
        return f"{show} season {row.get('season')}"
    return f"{show} S{row.get('season') or 0:02d}E{row.get('episode') or 0:02d}"


def _ids_agree(a: dict, b: dict) -> bool:
    """No provider id known on both sides differs (a path match with a different TMDB id is another title)."""
    return not any(a.get(c) and b.get(c) and a[c] != b[c] for c in ("tmdb_id", "tvdb_id", "imdb_id"))


def _match(old: dict, live: list[dict], prefixes) -> tuple[str, str | None, list[dict]]:
    """-> (strength, tier, candidates): strong / weak with one candidate, ambiguous with several, none."""
    def by_path(cands):
        p = _npath(old.get("path"), prefixes)
        return [c for c in cands if p and _npath(c.get("path"), prefixes) == p]

    def by_title(cands):
        t = _ntitle(old.get("title"))
        return [c for c in cands if t and _ntitle(c.get("title")) == t and c.get("year") == old.get("year")]

    for tier, col in TIERS[old["kind"]]:
        if not old.get(col):
            continue
        cands = [c for c in live if c.get(col) == old[col]]
        if len(cands) == 1:
            return "strong", tier, cands
        if cands:
            narrowed = by_path(cands) or by_title(cands)
            if len(narrowed) == 1:
                return "strong", tier, narrowed
            return "ambiguous", tier, cands
    cands = by_path(live)
    if len(cands) == 1 and _ids_agree(old, cands[0]):
        return "strong", "path", cands
    if cands:   # two items at one path, or a file replaced by a different title: never applied
        return "ambiguous", "path", cands
    cands = by_title(live)
    if len(cands) == 1:
        return "weak", "title+year", cands
    if cands:
        return "ambiguous", "title+year", cands
    return "none", None, []


def plan(min_fetches: int = 1, exclude_undone: bool = False, episodes_fn=None) -> dict:
    """The dry run: what a re-attach would change. Reads media.db only (plus one Jellyfin episode list per affected
    series); writes nothing."""
    out = {"strong": [], "weak": [], "ambiguous": [], "unmatched": [], "counts": {}, "new_rows": []}
    db = media_store.reader()
    if db is None:
        return out
    episodes_fn = episodes_fn or _episodes
    prefixes = _prefixes()
    with closing(db):
        tables = _tables(db)
        idx = {r["jf_id"]: dict(r) for r in db.execute("SELECT * FROM library_index")}
        refs = _referenced(db, tables)
        undone = _undone_ids(db) if exclude_undone else set()
        kids = defaultdict(list)
        for r in idx.values():
            if r["kind"] in ("season", "episode") and r["series_jf_id"]:
                kids[r["series_jf_id"]].append(r)

        def pending(r):
            return r["gone_since"] and not r["superseded_by"] and r["jf_id"] not in undone

        olds = [r for r in idx.values() if r["kind"] in TIERS and pending(r) and r["gone_fetches"] >= min_fetches
                and (r["jf_id"] in refs or any(k["jf_id"] in refs for k in kids[r["jf_id"]]))]
        old_ids = {r["jf_id"] for r in olds}
        live = defaultdict(list)
        for r in idx.values():
            if (r["kind"] in TIERS and not r["gone_since"] and not r["superseded_by"] and r["last_seen_at"]
                    and not r["version_of"] and r["jf_id"] not in old_ids):
                live[r["kind"]].append(r)
        for old in sorted(olds, key=lambda r: (r["kind"], r["title"] or "", r["jf_id"])):
            strength, tier, cands = _match(old, live[old["kind"]], prefixes)
            entry = {"old": old["jf_id"], "kind": old["kind"], "title": _label(old), "tier": tier}
            if strength in ("strong", "weak"):
                entry["new"] = cands[0]["jf_id"]
                out[strength].append(entry)
                if strength == "strong":
                    _children(old, cands[0], kids, refs, undone, prefixes, episodes_fn, out)
            elif strength == "ambiguous":
                out["ambiguous"].append({**entry, "candidates": sorted(c["jf_id"] for c in cands)})
            else:
                out["unmatched"].append(entry)
        _many_to_one(out)
        mapping = {x["old"]: x["new"] for x in out["strong"]}
        for table, col, form in COLUMNS:
            if table not in tables:
                continue
            n = sum(cnt for val, cnt in db.execute(f"SELECT {col}, COUNT(*) FROM {table} GROUP BY {col}")
                    if _bare(val, form) in mapping)
            if n:
                out["counts"][f"{table}.{col}"] = n
        if "poster" in tables:
            n = sum(1 for (jf_id,) in db.execute("SELECT jf_id FROM poster") if jf_id in mapping)
            if n:
                out["counts"]["poster.copy"] = n
    return out


def _children(old_series, new_series, kids, refs, undone, prefixes, episodes_fn, out) -> None:
    """Seasons and episodes of a strongly matched series that Joey's rows point at: by number, else by file path.
    A number (or path) that two new episodes share, or a season number with two season ids, is ambiguous."""
    mine = [k for k in kids[old_series["jf_id"]] if k["jf_id"] in refs and not k["superseded_by"]
            and k["jf_id"] not in undone]
    if not mine:
        return
    parent = old_series["jf_id"]
    eps = episodes_fn(new_series["jf_id"])
    if eps is None:
        out["unmatched"] += [{"old": k["jf_id"], "kind": k["kind"], "title": _label(k, old_series),
                              "tier": "episodes read failed", "parent": parent} for k in mine]
        return
    by_num, seasons, by_path = defaultdict(set), defaultdict(set), defaultdict(set)
    ok = library_index.ID_RE.match
    for e in eps:
        if not ok(str(e.get("Id") or "")) or (e.get("SeasonId") and not ok(str(e["SeasonId"]))):
            continue   # an id that is not a plain Jellyfin id never names a row or a poster folder
        for row in library_index.row_from_item({**e, "Type": e.get("Type") or "Episode",
                                                "SeriesId": e.get("SeriesId") or new_series["jf_id"]}):
            out["new_rows"].append(row)
        s, n = e.get("ParentIndexNumber"), e.get("IndexNumber")
        if isinstance(s, int) and isinstance(n, int):
            by_num[(s, n)].add(e["Id"])
        if isinstance(s, int) and e.get("SeasonId"):
            seasons[s].add(e["SeasonId"])
        p = _npath(e.get("Path"), prefixes)
        if p:
            by_path[p].add(e["Id"])
    for k in sorted(mine, key=lambda k: (k["kind"], k["season"] or 0, k["episode"] or 0)):
        found, tier = set(), None
        if k["kind"] == "episode":
            if isinstance(k["season"], int) and isinstance(k["episode"], int):
                found, tier = by_num.get((k["season"], k["episode"]), set()), "series+number"
            if not found and _npath(k["path"], prefixes) in by_path:
                found, tier = by_path[_npath(k["path"], prefixes)], "path"
        elif isinstance(k["season"], int):
            found, tier = seasons.get(k["season"], set()), "series+number"
        entry = {"old": k["jf_id"], "kind": k["kind"], "title": _label(k, old_series), "tier": tier, "parent": parent}
        found = found - {k["jf_id"]}
        if len(found) == 1:
            out["strong"].append({**entry, "new": next(iter(found))})
        elif found:
            out["ambiguous"].append({**entry, "candidates": sorted(found)})
        else:
            out["unmatched"].append({**entry, "tier": None})


def _many_to_one(out: dict) -> None:
    """Two old ids that would land on one new id: all of them become ambiguous (never applied), and so do the
    seasons and episodes matched through a series that was demoted."""
    targets = defaultdict(list)
    for word in ("strong", "weak"):
        for x in out[word]:
            targets[x["new"]].append(x["old"])
    clash = {old for olds in targets.values() if len(olds) > 1 for old in olds}
    if not clash:
        return
    for word in ("strong", "weak"):
        keep = []
        for x in out[word]:
            if x["old"] in clash or x.get("parent") in clash:
                why = "many-to-one" if x["old"] in clash else "series ambiguous"
                out["ambiguous"].append({**{k: v for k, v in x.items() if k != "new"}, "tier": why,
                                         "candidates": [x["new"]]})
            else:
                keep.append(x)
        out[word] = keep


def _summary(p: dict) -> dict:
    return {k: p[k] for k in ("strong", "weak", "ambiguous", "unmatched", "counts")}


def _backup(run_id: int) -> Path:
    """An SQLite online backup of media.db before the run; only the newest KEEP_BACKUPS pre-reattach copies are kept."""
    from hub import media_backup
    dest = Path(media_backup.backup_dir())
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / f"media-pre-reattach-{run_id}.db"
    with closing(sqlite3.connect(media_store.db_path())) as src, closing(sqlite3.connect(path)) as dst:
        src.backup(dst)
    others = sorted((f.stat().st_mtime_ns, f.name, f) for f in dest.iterdir()
                    if BACKUP_RE.match(f.name) and f.is_file() and f != path)
    for *_key, f in others[:max(0, len(others) - (KEEP_BACKUPS - 1))]:   # this run's copy is always kept
        try:
            f.unlink()
        except OSError:
            pass
    return path


def _posters_dir() -> Path:
    from hub import media_posters_store
    return media_posters_store.out_dir()


def _fingerprint(folder: Path) -> str:
    """Every file under a folder as (relative path, size, sha256): what undo checks before removing a copy."""
    files = []
    for f in sorted(folder.rglob("*")):
        if f.is_file():
            files.append([f.relative_to(folder).as_posix(), f.stat().st_size,
                          hashlib.sha256(f.read_bytes()).hexdigest()])
    return json.dumps(files)


def _row_json(db, jf_id: str) -> str | None:
    cur = db.execute("SELECT * FROM poster WHERE jf_id = ?", (jf_id,))
    row = cur.fetchone()
    if row is None:
        return None
    return json.dumps(dict(zip([d[0] for d in cur.description], tuple(row))), sort_keys=True)


def _mark_failed(run_id: int, why: str) -> None:
    try:
        with closing(media_store.connect()) as db, db:
            db.execute("UPDATE reattach_run SET mode = 'apply-failed', summary_json = ? WHERE id = ?",
                       (json.dumps({"error": why}), run_id))
    except sqlite3.Error:
        pass


def _copy_folder(root: Path, old: str, new: str) -> str | None:
    """Copy <old>/ to <new>/ without the old item's Jellyfin original (orig.*: it belongs to the old id's
    write-back). Through a temp folder renamed into place, so a half copy never sits at <new>/. -> the copy's
    fingerprint, or None when there is nothing to copy."""
    src, dst = root / old, root / new
    if not src.is_dir():
        return None
    tmp = root / f".{new}.reattach-tmp"
    shutil.rmtree(tmp, ignore_errors=True)   # a crashed run's leftover
    shutil.copytree(src, tmp, ignore=shutil.ignore_patterns("orig.*"))
    os.replace(tmp, dst)
    return _fingerprint(dst)


def apply(trigger: str = "manual", plan_: dict | None = None, episodes_fn=None) -> dict | None:
    """Re-attach the strong matches. None when there is nothing to do (nothing is written then)."""
    p = plan_ if plan_ is not None else plan(episodes_fn=episodes_fn)
    mapping = {x["old"]: x["new"] for x in p["strong"]
               if library_index.ID_RE.match(x["old"]) and library_index.ID_RE.match(x["new"])}
    if not mapping:
        return None
    now = _now()
    with closing(media_store.connect()) as db, db:
        run_id = db.execute("INSERT INTO reattach_run(started_at, mode, trigger) VALUES(?, 'apply', ?)",
                            (now, trigger)).lastrowid
    try:
        backup = _backup(run_id)
    except (sqlite3.Error, OSError) as exc:
        _mark_failed(run_id, f"backup failed: {type(exc).__name__}")
        raise
    conflicts, changes, copied = [], [], []
    root = _posters_dir()
    db = media_store.connect()
    try:
        db.execute("BEGIN IMMEDIATE")
        tables = _tables(db)
        for row in p.get("new_rows", []):
            library_index._upsert(db, row, now)
        for table, col, form in COLUMNS:
            if table not in tables:
                continue
            for rowid, val in db.execute(f"SELECT rowid, {col} FROM {table} WHERE {col} IS NOT NULL").fetchall():
                new = mapping.get(_bare(val, form))
                if not new:
                    continue
                new_val = _cell(new, form)
                try:
                    db.execute(f"UPDATE {table} SET {col} = ? WHERE rowid = ?", (new_val, rowid))
                except sqlite3.IntegrityError:
                    conflicts.append({"table": table, "column": col, "row": rowid, "old": val, "new": new_val})
                    continue
                changes.append((table, rowid, col, val, new_val, None))
        if "poster" in tables:
            cols = [r[1] for r in db.execute("PRAGMA table_info(poster)")]
            for old, new in mapping.items():
                row = db.execute(f"SELECT {', '.join(cols)} FROM poster WHERE jf_id = ?", (old,)).fetchone()
                if row is None:
                    continue
                if db.execute("SELECT 1 FROM poster WHERE jf_id = ?", (new,)).fetchone():
                    conflicts.append({"table": "poster", "column": "jf_id", "row": new, "old": old, "new": new})
                    continue
                vals = {**dict(zip(cols, tuple(row))), "jf_id": new}
                vals.update({k: v for k, v in POSTER_RESET.items() if k in vals})   # the write-back is the old id's
                db.execute(f"INSERT INTO poster({', '.join(vals)}) VALUES({', '.join('?' * len(vals))})",
                           tuple(vals.values()))
                changes.append(("poster", new, "jf_id", old, new, _row_json(db, new)))
        # poster store folders, inside the transaction: any failure below removes every copy again
        for old, new in mapping.items():
            if (root / new).exists():
                if (root / old).is_dir():
                    conflicts.append({"table": "poster_dir", "column": "folder", "row": new, "old": old, "new": new})
                continue
            fp = _copy_folder(root, old, new)
            if fp is not None:
                copied.append(new)
                changes.append(("poster_dir", new, "folder", old, new, fp))
        for old, new in mapping.items():
            db.execute("UPDATE library_index SET superseded_by = ? WHERE jf_id = ?", (new, old))
            changes.append(("library_index", old, "superseded_by", None, new, None))
        db.executemany("INSERT INTO reattach_change(run_id, table_name, row_ref, column_name, old_value, new_value, "
                       "detail) VALUES(?, ?, ?, ?, ?, ?, ?)", [(run_id, *c) for c in changes])
        summary = {**_summary(p), "conflicts": conflicts, "backup": backup.name,
                   "changed": sum(1 for c in changes if c[0] not in ("library_index", "poster", "poster_dir"))}
        db.execute("UPDATE reattach_run SET summary_json = ?, applied_at = ? WHERE id = ?",
                   (json.dumps(summary), _now(), run_id))
        db.commit()
    except BaseException as exc:
        db.rollback()
        for new in copied:
            shutil.rmtree(root / new, ignore_errors=True)
        _mark_failed(run_id, f"apply failed: {type(exc).__name__}")
        raise
    finally:
        db.close()
    log.info("re-attach run %s applied: %s cells, %s conflicts", run_id, summary["changed"], len(conflicts))
    return {"run_id": run_id, "mode": "apply", "trigger": trigger, **summary}


def undo(run_id: int) -> dict:
    """Undo one applied run: each cell back to its old value where it still holds the value the run wrote; a copied
    poster row or folder removed only while it is exactly what the run created. Anything changed since is skipped
    and listed. Logged as its own run."""
    remove_dirs = []
    root = _posters_dir()
    with closing(media_store.connect()) as db, db:
        run = db.execute("SELECT mode, undone_at FROM reattach_run WHERE id = ?", (run_id,)).fetchone()
        if run is None or run[0] != "apply" or run[1]:
            raise ValueError("not an applied run that can be undone")
        restored, skipped = 0, []
        changes = db.execute("SELECT table_name, row_ref, column_name, old_value, new_value, detail "
                             "FROM reattach_change WHERE run_id = ? ORDER BY id DESC", (run_id,)).fetchall()
        for table, ref, col, old, new, detail in changes:
            done = False
            if table == "poster_dir":
                folder = root / str(new)
                if not folder.exists():
                    continue
                done = bool(library_index.ID_RE.match(str(new))) and _fingerprint(folder) == detail
                if done:
                    remove_dirs.append(folder)
            elif table == "poster":
                if _row_json(db, new) == detail:   # still the copy this run made: the poster job has not touched it
                    db.execute("DELETE FROM poster WHERE jf_id = ?", (new,))
                    done = True
            elif table == "library_index":
                db.execute("UPDATE library_index SET superseded_by = ? WHERE jf_id = ? AND superseded_by IS ?",
                           (old, ref, new))
                continue
            else:
                try:
                    done = db.execute(f"UPDATE {table} SET {col} = ? WHERE rowid = ? AND {col} IS ?",
                                      (old, ref, new)).rowcount > 0
                except sqlite3.IntegrityError:
                    done = False
            if done:
                restored += 1
            else:
                skipped.append({"table": table, "column": col, "row": ref, "old": old, "new": new})
        now = _now()
        summary = {"undo_of": run_id, "restored": restored, "skipped": skipped}
        undo_id = db.execute("INSERT INTO reattach_run(started_at, mode, trigger, summary_json, applied_at, undo_of) "
                             "VALUES(?, 'undo', 'manual', ?, ?, ?)", (now, json.dumps(summary), now, run_id)).lastrowid
        db.execute("UPDATE reattach_run SET undone_at = ? WHERE id = ?", (now, run_id))
    for folder in remove_dirs:
        shutil.rmtree(folder, ignore_errors=True)
    return {"run_id": undo_id, **summary}


def suspected() -> bool:
    """The rebuild guard: the last fetch was complete and it and the one before are within GUARD_PCT of the
    baseline count (a half-scanned library holds)."""
    db = media_store.reader()
    if db is None:
        return False
    with closing(db):
        state = dict(db.execute("SELECT key, value FROM library_index_state").fetchall())
    try:
        base, last, prev = (int(state[k]) for k in ("guard_baseline", "count_last", "count_prev"))
    except (KeyError, TypeError, ValueError):
        return False
    if state.get("last_complete") != "1" or base <= 0:
        return False
    return all(abs(n - base) * 100 <= GUARD_PCT * base for n in (last, prev))


def auto(episodes_fn=None) -> dict | None:
    """After an index sync: apply the strong matches of a suspected rebuild (Q2 A), or store a new report when only
    weak / ambiguous matches are left. None when nothing was written."""
    if not suspected():
        return None
    p = plan(min_fetches=MIN_FETCHES_AUTO, exclude_undone=True, episodes_fn=episodes_fn)
    capped = bool(p["strong"]) and _over_cap(len(p["strong"])) and not (_all_provider(p) and _count_steady())
    if p["strong"] and not capped:
        return apply(trigger="auto", plan_=p)
    if not (p["weak"] or p["ambiguous"] or capped):
        return None
    report = {**_summary(p), **({"capped": AUTO_MAX_PCT} if capped else {})}
    summary = json.dumps(report, sort_keys=True)
    with closing(media_store.connect()) as db, db:
        last = db.execute("SELECT summary_json FROM reattach_run WHERE mode = 'report' ORDER BY id DESC LIMIT 1"
                          ).fetchone()
        if last and last[0] == summary:
            return None
        run_id = db.execute("INSERT INTO reattach_run(started_at, mode, trigger, summary_json) "
                            "VALUES(?, 'report', 'auto', ?)", (_now(), summary)).lastrowid
    log.info("re-attach run %s: report only (%s strong%s, %s weak, %s ambiguous)", run_id, len(p["strong"]),
             " over the auto cap" if capped else "", len(p["weak"]), len(p["ambiguous"]))
    return {"run_id": run_id, "mode": "report", "trigger": "auto", **report}


def _all_provider(p: dict) -> bool:
    """Every change is a provider-id match (a film or series on tmdb / tvdb / imdb, or a season or episode by number
    under a series matched that way), with no tie and no many-to-one anywhere in the run."""
    if p["ambiguous"]:
        return False
    series = {x["old"]: x["tier"] for x in p["strong"] if x["kind"] in TIERS}
    return all(x["tier"] in PROVIDER_TIERS if x["kind"] in TIERS
               else x["tier"] == "series+number" and series.get(x.get("parent")) in PROVIDER_TIERS
               for x in p["strong"])


def _count_steady() -> bool:
    """The library count is the same on the two complete fetches the run rests on."""
    db = media_store.reader()
    if db is None:
        return False
    with closing(db):
        state = dict(db.execute("SELECT key, value FROM library_index_state").fetchall())
    return state.get("count_last") is not None and state.get("count_last") == state.get("count_prev")


def _over_cap(n: int) -> bool:
    """More than AUTO_MAX_PCT of the indexed items would move: too big to apply unattended (the CLI still can)."""
    db = media_store.reader()
    if db is None:
        return True
    with closing(db):
        indexed = db.execute("SELECT COUNT(*) FROM library_index").fetchone()[0]
    return n * 100 > AUTO_MAX_PCT * max(indexed, 1)


# ---- CLI ----
# Output carries run ids, counts, kinds, titles and tiers only: no Jellyfin ids and no paths (scripts/joey_reattach.py
# prints it on B.'s computer).

def _report_lines(p: dict) -> list[str]:
    lines = [f"      strong {len(p['strong'])}, weak {len(p['weak'])}, ambiguous {len(p['ambiguous'])}, "
             f"unmatched {len(p['unmatched'])}" + (f", over the {p['capped']} % auto cap" if p.get("capped") else "")]
    for word in ("strong", "weak", "ambiguous", "unmatched"):
        for x in p[word]:
            lines.append(f"      {word:<9} {x['kind']:<7} {x['title']}  ({x.get('tier') or 'no match'})")
    lines += [f"      rows {k}: {n}" for k, n in sorted(p["counts"].items())]
    return lines


def _pairs(p: dict) -> set:
    return {(x["old"], x["new"]) for x in p["strong"]}


def latest() -> dict | None:
    """The newest report / apply / undo run, with its summary."""
    db = media_store.reader()
    if db is None:
        return None
    with closing(db):
        row = db.execute("SELECT id, started_at, mode, trigger, summary_json, undone_at FROM reattach_run "
                         "ORDER BY id DESC LIMIT 1").fetchone()
    if row is None:
        return None
    return {"run_id": row[0], "started_at": row[1], "mode": row[2], "trigger": row[3], "undone_at": row[5],
            "summary": json.loads(row[4] or "{}")}


def apply_report(run_id: int) -> dict | None:
    """Apply a stored report by hand: only when a fresh plan still makes exactly the report's strong matches."""
    db = media_store.reader()
    row = None
    if db is not None:
        with closing(db):
            row = db.execute("SELECT mode, summary_json FROM reattach_run WHERE id = ?", (run_id,)).fetchone()
    if row is None or row[0] != "report":
        raise ValueError("not a report run")
    p = plan()
    if _pairs(p) != _pairs({"strong": json.loads(row[1] or "{}").get("strong", [])}):
        raise ValueError("the library changed since this report: run --latest again")
    return apply(trigger=f"report {run_id}", plan_=p)


def _apply_lines(r: dict | None) -> list[str]:
    if r is None:
        return ["PASS  apply - nothing to re-attach"]
    lines = [f"PASS  apply - run {r['run_id']}: {r['changed']} cells changed, {len(r['conflicts'])} conflicts, "
             f"backup taken", *_report_lines(r)]
    by = defaultdict(int)
    for c in r["conflicts"]:
        by[f"{c['table']}.{c['column']}"] += 1
    return lines + [f"      conflicts {k}: {n} (left as they were)" for k, n in sorted(by.items())]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m hub.library_reattach",
                                 description="JY-264: re-attach media.db rows after a Jellyfin library rebuild")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true", help="report what would change; writes nothing")
    g.add_argument("--latest", action="store_true", help="show the newest run (report, apply or undo)")
    g.add_argument("--apply", action="store_true", help="re-attach the strong matches (backup first)")
    g.add_argument("--apply-report", type=int, metavar="RUN_ID", help="apply a stored report, if still current")
    g.add_argument("--undo", type=int, metavar="RUN_ID", help="undo one applied run")
    args = ap.parse_args(argv)
    step = ("dry run" if args.dry_run else "latest" if args.latest else "apply" if args.apply
            else "apply report" if args.apply_report is not None else "undo")
    lines, code = [], 0
    try:
        if args.dry_run:
            lines += ["PASS  dry run - nothing written", *_report_lines(plan())]
        elif args.latest:
            r = latest()
            if r is None:
                lines.append("PASS  latest - no re-attach run yet")
            else:
                sm = r["summary"]
                lines.append(f"PASS  latest - run {r['run_id']} {r['mode']} ({r['trigger']}) {r['started_at']}"
                             + (f", undone {r['undone_at']}" if r["undone_at"] else ""))
                if "strong" in sm:
                    lines += _report_lines({**{k: sm.get(k, []) for k in ("strong", "weak", "ambiguous", "unmatched")},
                                            "counts": sm.get("counts", {}), "capped": sm.get("capped")})
                if "restored" in sm:
                    lines.append(f"      undo of run {sm.get('undo_of')}: {sm['restored']} restored, "
                                 f"{len(sm.get('skipped', []))} skipped")
        elif args.apply:
            lines += _apply_lines(apply(trigger="cli"))
        elif args.apply_report is not None:
            lines += _apply_lines(apply_report(args.apply_report))
        else:
            r = undo(args.undo)
            lines.append(f"PASS  undo - run {args.undo}: {r['restored']} restored, {len(r['skipped'])} skipped")
            by = defaultdict(int)
            for x in r["skipped"]:
                by[f"{x['table']}.{x['column']}"] += 1
            lines += [f"      skipped {k}: {n} (changed since)" for k, n in sorted(by.items())]
    except Exception as exc:
        lines.append(f"FAIL  {step} - {type(exc).__name__}: {exc if isinstance(exc, ValueError) else 'see the hub log'}")
        code = 1
    text = "\n".join(lines)
    print(text)
    try:
        logfile = media_store.db_path().parent / "library_reattach.log"
        with open(logfile, "a", encoding="utf-8") as fh:
            fh.write(f"=== {_now()} {' '.join(argv if argv is not None else sys.argv[1:])}\n{text}\n")
    except OSError:
        pass
    return code


if __name__ == "__main__":
    sys.exit(main())
