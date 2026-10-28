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
By hand: `python -m hub.library_reattach --dry-run | --apply | --undo <run_id>` (PASS / FAIL lines + a log file).

Safety: an SQLite backup of media.db first (MEDIA_BACKUP_DIR/media-pre-reattach-<run_id>.db); one transaction;
never deletes a row; a cell whose new value would break a key is left as it is and listed as a conflict; every
changed cell is logged in `reattach_change`; poster store folders (JY-260) and poster rows are copied to the new
id, never moved; undo puts back only cells that still hold the value the run wrote, and removes only the copies.
An undone run's ids are not re-applied by `auto()`.
"""
from __future__ import annotations

import argparse
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
    if len(cands) == 1:
        return "strong", "path", cands
    if cands:
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
        mapping = {}
        for old in sorted(olds, key=lambda r: (r["kind"], r["title"] or "", r["jf_id"])):
            strength, tier, cands = _match(old, live[old["kind"]], prefixes)
            entry = {"old": old["jf_id"], "kind": old["kind"], "title": _label(old), "tier": tier}
            if strength in ("strong", "weak"):
                entry["new"] = cands[0]["jf_id"]
                out[strength].append(entry)
                if strength == "strong":
                    mapping[old["jf_id"]] = cands[0]["jf_id"]
                    _children(old, cands[0], kids, refs, undone, prefixes, episodes_fn, out, mapping)
            elif strength == "ambiguous":
                out["ambiguous"].append({**entry, "candidates": sorted(c["jf_id"] for c in cands)})
            else:
                out["unmatched"].append(entry)
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


def _children(old_series, new_series, kids, refs, undone, prefixes, episodes_fn, out, mapping) -> None:
    """Seasons and episodes of a strongly matched series that Joey's rows point at: by number, else by file path."""
    mine = [k for k in kids[old_series["jf_id"]] if k["jf_id"] in refs and not k["superseded_by"]
            and k["jf_id"] not in undone]
    if not mine:
        return
    eps = episodes_fn(new_series["jf_id"])
    if eps is None:
        out["unmatched"] += [{"old": k["jf_id"], "kind": k["kind"], "title": _label(k, old_series),
                              "tier": "episodes read failed"} for k in mine]
        return
    by_num, seasons, by_path = {}, {}, {}
    ok = library_index.ID_RE.match
    for e in eps:
        if not ok(str(e.get("Id") or "")) or (e.get("SeasonId") and not ok(str(e["SeasonId"]))):
            continue   # an id that is not a plain Jellyfin id never names a row or a poster folder
        for row in library_index.row_from_item({**e, "Type": e.get("Type") or "Episode",
                                                "SeriesId": e.get("SeriesId") or new_series["jf_id"]}):
            out["new_rows"].append(row)
        s, n = e.get("ParentIndexNumber"), e.get("IndexNumber")
        if isinstance(s, int) and isinstance(n, int) and e.get("Id"):
            by_num[(s, n)] = e["Id"]
        if isinstance(s, int) and e.get("SeasonId"):
            seasons.setdefault(s, e["SeasonId"])
        p = _npath(e.get("Path"), prefixes)
        if p and e.get("Id"):
            by_path[p] = e["Id"]
    for k in sorted(mine, key=lambda k: (k["kind"], k["season"] or 0, k["episode"] or 0)):
        new, tier = None, None
        if k["kind"] == "episode":
            if isinstance(k["season"], int) and isinstance(k["episode"], int):
                new, tier = by_num.get((k["season"], k["episode"])), "series+number"
            if new is None and _npath(k["path"], prefixes) in by_path:
                new, tier = by_path[_npath(k["path"], prefixes)], "path"
        elif isinstance(k["season"], int):
            new, tier = seasons.get(k["season"]), "series+number"
        entry = {"old": k["jf_id"], "kind": k["kind"], "title": _label(k, old_series), "tier": tier}
        if new and new != k["jf_id"]:
            out["strong"].append({**entry, "new": new})
            mapping[k["jf_id"]] = new
        else:
            out["unmatched"].append({**entry, "tier": None})


def _summary(p: dict) -> dict:
    return {k: p[k] for k in ("strong", "weak", "ambiguous", "unmatched", "counts")}


def _backup(run_id: int) -> Path:
    from hub import media_backup
    dest = Path(media_backup.backup_dir())
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / f"media-pre-reattach-{run_id}.db"
    with closing(sqlite3.connect(media_store.db_path())) as src, closing(sqlite3.connect(path)) as dst:
        src.backup(dst)
    return path


def _posters_dir() -> Path:
    from hub import media_posters_store
    return media_posters_store.out_dir()


def apply(trigger: str = "manual", plan_: dict | None = None, episodes_fn=None) -> dict | None:
    """Re-attach the strong matches. None when there is nothing to do (nothing is written then)."""
    p = plan_ if plan_ is not None else plan(episodes_fn=episodes_fn)
    mapping = {x["old"]: x["new"] for x in p["strong"]}
    if not mapping:
        return None
    now = _now()
    with closing(media_store.connect()) as db, db:
        run_id = db.execute("INSERT INTO reattach_run(started_at, mode, trigger) VALUES(?, 'apply', ?)",
                            (now, trigger)).lastrowid
    try:
        backup = _backup(run_id)
    except (sqlite3.Error, OSError) as exc:
        with closing(media_store.connect()) as db, db:
            db.execute("UPDATE reattach_run SET mode = 'apply-failed', summary_json = ? WHERE id = ?",
                       (json.dumps({"error": f"backup failed: {type(exc).__name__}"}), run_id))
        raise
    conflicts, changes = [], []
    # poster store folders: copied (never moved) before the transaction; removed again if it fails
    copied = []
    root = _posters_dir()
    for old, new in mapping.items():
        if not (library_index.ID_RE.match(old) and library_index.ID_RE.match(new)):
            continue
        src, dst = root / old, root / new
        if not src.is_dir():
            continue
        if dst.exists():
            conflicts.append({"table": "poster_dir", "column": "folder", "row": new, "old": old, "new": new})
            continue
        shutil.copytree(src, dst)
        copied.append((old, new))
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
                changes.append((table, rowid, col, val, new_val))
        if "poster" in tables:
            cols = [r[1] for r in db.execute("PRAGMA table_info(poster)")]
            sel = ", ".join("?" if c == "jf_id" else c for c in cols)
            for old, new in mapping.items():
                if not db.execute("SELECT 1 FROM poster WHERE jf_id = ?", (old,)).fetchone():
                    continue
                if db.execute("SELECT 1 FROM poster WHERE jf_id = ?", (new,)).fetchone():
                    conflicts.append({"table": "poster", "column": "jf_id", "row": new, "old": old, "new": new})
                    continue
                db.execute(f"INSERT INTO poster({', '.join(cols)}) SELECT {sel} FROM poster WHERE jf_id = ?",
                           (new, old))
                changes.append(("poster", new, "jf_id", old, new))
        for old, new in copied:
            changes.append(("poster_dir", new, "folder", old, new))
        for old, new in mapping.items():
            db.execute("UPDATE library_index SET superseded_by = ? WHERE jf_id = ?", (new, old))
            changes.append(("library_index", old, "superseded_by", None, new))
        db.executemany("INSERT INTO reattach_change(run_id, table_name, row_ref, column_name, old_value, new_value) "
                       "VALUES(?, ?, ?, ?, ?, ?)", [(run_id, *c) for c in changes])
        summary = {**_summary(p), "conflicts": conflicts, "backup": backup.name,
                   "changed": sum(1 for c in changes if c[0] not in ("library_index", "poster", "poster_dir"))}
        db.execute("UPDATE reattach_run SET summary_json = ?, applied_at = ? WHERE id = ?",
                   (json.dumps(summary), _now(), run_id))
        db.commit()
    except BaseException:
        db.rollback()
        for _old, new in copied:
            shutil.rmtree(root / new, ignore_errors=True)
        raise
    finally:
        db.close()
    log.info("re-attach run %s applied: %s cells, %s conflicts", run_id, summary["changed"], len(conflicts))
    return {"run_id": run_id, "mode": "apply", "trigger": trigger, **summary}


def undo(run_id: int) -> dict:
    """Undo one applied run: each cell back to its old value where it still holds the value the run wrote (anything
    since changed is skipped and listed); the copied poster rows and folders removed. Logged as its own run."""
    removed_dirs = []
    with closing(media_store.connect()) as db, db:
        run = db.execute("SELECT mode, undone_at FROM reattach_run WHERE id = ?", (run_id,)).fetchone()
        if run is None or run[0] != "apply" or run[1]:
            raise ValueError("not an applied run that can be undone")
        restored, skipped = 0, []
        changes = db.execute("SELECT table_name, row_ref, column_name, old_value, new_value FROM reattach_change "
                             "WHERE run_id = ? ORDER BY id DESC", (run_id,)).fetchall()
        for table, ref, col, old, new in changes:
            if table == "poster_dir":
                removed_dirs.append(new)
                continue
            if table == "poster":
                cur = db.execute("DELETE FROM poster WHERE jf_id = ?", (new,))   # the copy this run created
            elif table == "library_index":
                cur = db.execute("UPDATE library_index SET superseded_by = ? WHERE jf_id = ? AND superseded_by IS ?",
                                 (old, ref, new))
            else:
                try:
                    cur = db.execute(f"UPDATE {table} SET {col} = ? WHERE rowid = ? AND {col} IS ?", (old, ref, new))
                except sqlite3.IntegrityError:
                    cur = None
            if cur is not None and cur.rowcount:
                restored += table not in ("library_index",)
            elif table not in ("library_index", "poster"):
                skipped.append({"table": table, "column": col, "row": ref, "old": old, "new": new})
        now = _now()
        summary = {"undo_of": run_id, "restored": restored, "skipped": skipped}
        undo_id = db.execute("INSERT INTO reattach_run(started_at, mode, trigger, summary_json, applied_at, undo_of) "
                             "VALUES(?, 'undo', 'manual', ?, ?, ?)", (now, json.dumps(summary), now, run_id)).lastrowid
        db.execute("UPDATE reattach_run SET undone_at = ? WHERE id = ?", (now, run_id))
    root = _posters_dir()
    for new in removed_dirs:
        if library_index.ID_RE.match(new or ""):
            shutil.rmtree(root / new, ignore_errors=True)
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
    if p["strong"]:
        return apply(trigger="auto", plan_=p)
    if not (p["weak"] or p["ambiguous"]):
        return None
    summary = json.dumps(_summary(p), sort_keys=True)
    with closing(media_store.connect()) as db, db:
        last = db.execute("SELECT summary_json FROM reattach_run WHERE mode = 'report' ORDER BY id DESC LIMIT 1"
                          ).fetchone()
        if last and last[0] == summary:
            return None
        run_id = db.execute("INSERT INTO reattach_run(started_at, mode, trigger, summary_json) "
                            "VALUES(?, 'report', 'auto', ?)", (_now(), summary)).lastrowid
    log.info("re-attach run %s: report only (%s weak, %s ambiguous)", run_id, len(p["weak"]), len(p["ambiguous"]))
    return {"run_id": run_id, "mode": "report", "trigger": "auto", **_summary(p)}


# ---- CLI ----

def _report_lines(p: dict) -> list[str]:
    lines = [f"      strong {len(p['strong'])}, weak {len(p['weak'])}, ambiguous {len(p['ambiguous'])}, "
             f"unmatched {len(p['unmatched'])}"]
    for word in ("strong", "weak", "ambiguous", "unmatched"):
        for x in p[word]:
            lines.append(f"      {word:<9} {x['kind']:<7} {x['title']}  {x['old']} -> "
                         f"{x.get('new') or ','.join(x.get('candidates', [])) or '-'}  ({x.get('tier') or 'no match'})")
    lines += [f"      rows {k}: {n}" for k, n in sorted(p["counts"].items())]
    return lines


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m hub.library_reattach",
                                 description="JY-264: re-attach media.db rows after a Jellyfin library rebuild")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true", help="report what would change; writes nothing")
    g.add_argument("--apply", action="store_true", help="re-attach the strong matches (backup first)")
    g.add_argument("--undo", type=int, metavar="RUN_ID", help="undo one applied run")
    args = ap.parse_args(argv)
    lines, code = [], 0
    try:
        if args.dry_run:
            p = plan()
            lines += ["PASS  dry run - nothing written", *_report_lines(p)]
        elif args.apply:
            r = apply(trigger="cli")
            if r is None:
                lines.append("PASS  apply - nothing to re-attach")
            else:
                lines += [f"PASS  apply - run {r['run_id']}: {r['changed']} cells changed, "
                          f"{len(r['conflicts'])} conflicts, backup {r['backup']}", *_report_lines(r)]
                lines += [f"      conflict {c['table']}.{c['column']} row {c['row']}: {c['old']} -> {c['new']}"
                          for c in r["conflicts"]]
        else:
            r = undo(args.undo)
            lines.append(f"PASS  undo - run {args.undo}: {r['restored']} restored, {len(r['skipped'])} skipped")
            lines += [f"      skipped {s['table']}.{s['column']} row {s['row']} (changed since)" for s in r["skipped"]]
    except Exception as exc:
        lines.append(f"FAIL  {'dry run' if args.dry_run else 'apply' if args.apply else 'undo'} - "
                     f"{type(exc).__name__}: {exc}")
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
