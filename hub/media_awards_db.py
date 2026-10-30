"""Awards store (AWARDS_PLAN A1, 2026-10-08): the `award_*` tables in media.db, their writers (the sync's) and the
readers the pages use. media_store creates the tables (DDL below) and runs `apply_seed()` once per file per process; reads
never create the file.

Tables (plan §2.1, with three recorded additions):
  award_body / award_edition / award_category / award_nomination / award_entity / award_sync as planned;
  + `award_category.lead` ('work' | 'person': whose name heads a nominee line) and `award_entity.poster` (a lazily
    filled `tmdb:` ref) — both read by the pages;
  + `award_title(title, qid)`: the enwiki title -> QID cache (a title that resolves to nothing is remembered as '').
A missing side of a nomination is '' (never NULL); a side that is present but unresolved holds '~<slug of its label>'
(never a QID), so two unresolved nominees in one category never collide on the primary key and no row is dropped.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from contextlib import closing
from datetime import date
from pathlib import Path

import yaml

from hub import media_db, media_store
from hub import media_awards_seed as seed
from hub.media_awards_parse import ordinal, slug, wp_title

log = logging.getLogger("hub.media_awards_db")

DDL = (
    """CREATE TABLE IF NOT EXISTS award_body(
  id TEXT PRIMARY KEY, name TEXT, kinds TEXT, wd_series TEXT, wp_title_fmt TEXT, usual_month INT, sort INT)""",
    """CREATE TABLE IF NOT EXISTS award_edition(
  body_id TEXT, ordinal INT, year INT, held_on TEXT, wd_qid TEXT, wp_title TEXT, name TEXT,
  state TEXT NOT NULL DEFAULT 'pending', note TEXT, synced_at TEXT, PRIMARY KEY(body_id, ordinal))""",
    """CREATE TABLE IF NOT EXISTS award_category(
  body_id TEXT, cat_key TEXT, name TEXT, kind TEXT, grp TEXT, rank INT, lead TEXT, PRIMARY KEY(body_id, cat_key))""",
    """CREATE TABLE IF NOT EXISTS award_nomination(
  body_id TEXT, ordinal INT, cat_key TEXT, work_qid TEXT NOT NULL DEFAULT '', work_title TEXT,
  person_qid TEXT NOT NULL DEFAULT '', person_name TEXT, won INT, pos INT, source TEXT,
  PRIMARY KEY(body_id, ordinal, cat_key, work_qid, person_qid))""",
    """CREATE TABLE IF NOT EXISTS award_entity(
  qid TEXT PRIMARY KEY, kind TEXT, label TEXT, tmdb_movie INT, tmdb_tv INT, tmdb_person INT, imdb TEXT, tvdb INT,
  poster TEXT, resolved_at TEXT)""",
    "CREATE TABLE IF NOT EXISTS award_title(title TEXT PRIMARY KEY, qid TEXT NOT NULL DEFAULT '', resolved_at TEXT)",
    "CREATE TABLE IF NOT EXISTS award_sync(key TEXT PRIMARY KEY, value TEXT)",
    "CREATE INDEX IF NOT EXISTS award_nom_work ON award_nomination(work_qid)",
    "CREATE INDEX IF NOT EXISTS award_nom_person ON award_nomination(person_qid)",
    "CREATE INDEX IF NOT EXISTS award_ed_year ON award_edition(body_id, year)",
    "CREATE INDEX IF NOT EXISTS award_ent_tmdb_movie ON award_entity(tmdb_movie)",
    "CREATE INDEX IF NOT EXISTS award_ent_tmdb_tv ON award_entity(tmdb_tv)",
    "CREATE INDEX IF NOT EXISTS award_ent_tvdb ON award_entity(tvdb)",
    "CREATE INDEX IF NOT EXISTS award_ent_tmdb_person ON award_entity(tmdb_person)",
)
QID_RE = re.compile(r"^Q[1-9][0-9]*$")


def is_qid(value) -> bool:
    return bool(value) and bool(QID_RE.match(str(value)))


def local_key(label: str) -> str:
    """The key of a present-but-unresolved side: '~' + slug (never a QID)."""
    return "~" + (slug(label) or "untitled")


# ---- connection ----

def ensure() -> sqlite3.Connection:
    """A connection for a write (media_store)."""
    return media_store.connect()


def apply_seed(db) -> None:
    """The body rows from media_awards_seed, written when the stored seed version differs (one SELECT otherwise)."""
    row = db.execute("SELECT value FROM award_sync WHERE key = 'seed_v'").fetchone()
    if not row or row["value"] != str(seed.SEED_VERSION):
        with db:
            for b in seed.BODIES:
                db.execute("INSERT INTO award_body(id, name, kinds, wd_series, wp_title_fmt, usual_month, sort) "
                           "VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name = excluded.name, "
                           "kinds = excluded.kinds, wd_series = excluded.wd_series, wp_title_fmt = excluded.wp_title_fmt, "
                           "usual_month = excluded.usual_month, sort = excluded.sort",
                           (b["id"], b["name"], b["kinds"], b.get("wd_series"), b.get("wp_title_fmt"),
                            b["usual_month"], b["sort"]))
            db.execute("INSERT OR REPLACE INTO award_sync(key, value) VALUES('seed_v', ?)", (str(seed.SEED_VERSION),))


def _reader():
    """A connection for reading, or None when there is no media.db yet / it can't be opened (media_store)."""
    return media_store.reader()


def _now() -> str:
    return media_db._now().isoformat(timespec="seconds")


# ---- sync key/values ----

def get_sync(db, key: str, default=None):
    row = db.execute("SELECT value FROM award_sync WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_sync(db, key: str, value) -> None:
    with db:
        db.execute("INSERT OR REPLACE INTO award_sync(key, value) VALUES(?, ?)", (key, str(value)))


# ---- writers (the sync's) ----

def edition_name(body_id: str, n: int, year: int | None) -> str:
    b = seed.BY_ID.get(body_id) or {}
    if b.get("edition_fmt"):
        return b["edition_fmt"].format(year=year or n)
    return wp_title(b.get("wp_title_fmt"), n) or f"{ordinal(n)} {b.get('name', body_id)}"


def upsert_editions(db, body_id: str, rows: list[dict]) -> int:
    """rows: {ordinal, year?, held_on?, wd_qid?} -> new rows are 'pending'; known ones keep their state and gain any
    better facts (a day-precision date, the edition QID). -> rows written."""
    b = seed.BY_ID.get(body_id) or {}
    n = 0
    with db:
        for r in rows:
            o = int(r["ordinal"])
            year = r.get("year")
            db.execute(
                "INSERT INTO award_edition(body_id, ordinal, year, held_on, wd_qid, wp_title, name, state) "
                "VALUES(?,?,?,?,?,?,?, 'pending') ON CONFLICT(body_id, ordinal) DO UPDATE SET "
                "year = COALESCE(excluded.year, award_edition.year), "
                "held_on = COALESCE(excluded.held_on, award_edition.held_on), "
                "wd_qid = COALESCE(excluded.wd_qid, award_edition.wd_qid), "
                "wp_title = COALESCE(excluded.wp_title, award_edition.wp_title), name = excluded.name",
                (body_id, o, year, r.get("held_on"), r.get("wd_qid"), wp_title(b.get("wp_title_fmt"), o),
                 edition_name(body_id, o, year)))
            n += 1
    return n


def set_state(db, body_id: str, n: int, state: str, note: str | None = None, synced: bool = False) -> None:
    with db:
        if synced:
            db.execute("UPDATE award_edition SET state = ?, note = ?, synced_at = ? WHERE body_id = ? AND ordinal = ?",
                       (state, note, _now(), body_id, n))
        else:
            db.execute("UPDATE award_edition SET state = ?, note = ? WHERE body_id = ? AND ordinal = ?",
                       (state, note, body_id, n))


def upsert_entities(db, ents) -> None:
    now = _now()
    rows = [(e["qid"], e.get("kind") or "other", e.get("label"), e.get("tmdb_movie"), e.get("tmdb_tv"),
             e.get("tmdb_person"), e.get("imdb"), e.get("tvdb"), now) for e in ents if is_qid(e.get("qid"))]
    db.executemany(
        "INSERT INTO award_entity(qid, kind, label, tmdb_movie, tmdb_tv, tmdb_person, imdb, tvdb, resolved_at) "
        "VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(qid) DO UPDATE SET kind = excluded.kind, "
        "label = COALESCE(award_entity.label, excluded.label), tmdb_movie = excluded.tmdb_movie, "
        "tmdb_tv = excluded.tmdb_tv, tmdb_person = excluded.tmdb_person, imdb = excluded.imdb, "
        "tvdb = excluded.tvdb, resolved_at = excluded.resolved_at", rows)


def write_edition(db, body_id: str, n: int, categories: list[dict], nominations: list[dict], entities,
                  state: str, source: str, note: str | None = None) -> int:
    """Replace one edition's nominations (one transaction): categories upserted (first name kept — the backfill runs
    newest first), entities upserted, the edition's state + synced_at set. -> nominations written."""
    with db:
        for c in categories:
            rank, grp = c.get("rank"), c.get("grp")
            if rank is None:
                rank, grp = seed.rank_of(body_id, c["kind"], c["name"], slug(c["name"]), c.get("order", 0))
            db.execute("INSERT INTO award_category(body_id, cat_key, name, kind, grp, rank, lead) VALUES(?,?,?,?,?,?,?) "
                       "ON CONFLICT(body_id, cat_key) DO UPDATE SET lead = COALESCE(award_category.lead, excluded.lead)",
                       (body_id, c["cat_key"], c["name"], c["kind"], grp, rank, c.get("lead")))
        upsert_entities(db, list(entities.values()) if isinstance(entities, dict) else entities)
        db.execute("DELETE FROM award_nomination WHERE body_id = ? AND ordinal = ?", (body_id, n))
        rows = {}
        for m in nominations:
            key = (m["cat_key"], m.get("work_qid") or "", m.get("person_qid") or "")
            old = rows.get(key)
            if old:
                old["won"] = max(old["won"], int(m.get("won") or 0))
                continue
            rows[key] = {**m, "won": int(m.get("won") or 0)}
        db.executemany(
            "INSERT INTO award_nomination(body_id, ordinal, cat_key, work_qid, work_title, person_qid, person_name, won, "
            "pos, source) VALUES(?,?,?,?,?,?,?,?,?,?)",
            [(body_id, n, k[0], k[1], (m.get("work_title") or "")[:200], k[2], (m.get("person_name") or "")[:200],
              m["won"], int(m.get("pos") or 0), source) for k, m in rows.items()])
        db.execute("UPDATE award_edition SET state = ?, note = ?, synced_at = ? WHERE body_id = ? AND ordinal = ?",
                   (state, note, _now(), body_id, n))
    return len(rows)


def cached_titles(db, titles) -> dict[str, str]:
    titles = list(dict.fromkeys(t for t in titles if t))
    out: dict[str, str] = {}
    for i in range(0, len(titles), 500):
        chunk = titles[i:i + 500]
        for r in db.execute(f"SELECT title, qid FROM award_title WHERE title IN ({','.join('?' * len(chunk))})", chunk):
            out[r["title"]] = r["qid"]
    return out


def remember_titles(db, mapping: dict[str, str]) -> None:
    now = _now()
    with db:
        db.executemany("INSERT OR REPLACE INTO award_title(title, qid, resolved_at) VALUES(?,?,?)",
                       [(t, q or "", now) for t, q in mapping.items()])


def known_entities(db, qids) -> set[str]:
    qids = [q for q in dict.fromkeys(qids) if is_qid(q)]
    out: set[str] = set()
    for i in range(0, len(qids), 500):
        chunk = qids[i:i + 500]
        out |= {r["qid"] for r in db.execute(
            f"SELECT qid FROM award_entity WHERE qid IN ({','.join('?' * len(chunk))})", chunk)}
    return out


def set_poster(qid: str, ref: str) -> None:
    db = _reader()
    if db is None:
        return
    with closing(db):
        with db:
            db.execute("UPDATE award_entity SET poster = ? WHERE qid = ?", (ref, qid))


# ---- readers ----

SHOWN_PATH = Path(__file__).resolve().parents[1] / "config" / "awards.yaml"


def shown_ids(path: Path | None = None) -> set[str] | None:
    """JY-270 (B. 2026-10-30, majors only): the ceremony ids config/awards.yaml lets the Awards page offer; None = all
    (no file, no list, or an unreadable file)."""
    try:
        ids = (yaml.safe_load((path or SHOWN_PATH).read_text(encoding="utf-8")) or {}).get("ceremonies") or []
    except (OSError, yaml.YAMLError, AttributeError):
        return None
    return {str(i) for i in ids} or None


def _shown(b: dict) -> bool:
    ids = shown_ids()
    return ids is None or b["id"] in ids


def bodies(kind: str) -> list[dict]:
    """The bodies with categories of this kind ('film' | 'tv') that config/awards.yaml shows, in seed order (works
    without a DB)."""
    return [{"id": b["id"], "name": b["name"]} for b in sorted(seed.BODIES, key=lambda b: b["sort"])
            if kind in b["kinds"].split(",") and _shown(b)]


def years_of(body_id: str) -> list[int]:
    """Ceremony years of the editions known for a body, newest first (any state; an edition without a year is not
    placeable yet)."""
    db = _reader()
    if db is None:
        return []
    with closing(db):
        return [r["year"] for r in db.execute(
            "SELECT DISTINCT year FROM award_edition WHERE body_id = ? AND year IS NOT NULL ORDER BY year DESC",
            (body_id,))]


def held_months(year: int | None) -> dict[str, int]:
    """{body_id: month} of the editions of this ceremony year with a known date (awards-year item 3, the tile month)."""
    db = _reader() if year else None
    if db is None:
        return {}
    out: dict[str, int] = {}
    with closing(db):
        for r in db.execute("SELECT body_id, held_on FROM award_edition WHERE year = ? AND held_on IS NOT NULL AND "
                            "held_on != ''", (year,)):
            try:
                out[r["body_id"]] = date.fromisoformat(r["held_on"][:10]).month
            except ValueError:
                pass
    return out


def data_years(body_id: str, kind: str) -> set[int]:
    """Ceremony years of a body that have nominations of this kind ('film' | 'tv') - the picker's year strip
    (`has_data`, Awards ballot 2026-10-14). Empty without a DB."""
    db = _reader()
    if db is None:
        return set()
    with closing(db):
        return {r["year"] for r in db.execute(
            "SELECT DISTINCT e.year FROM award_edition e WHERE e.body_id = ? AND e.year IS NOT NULL AND EXISTS (SELECT 1 "
            "FROM award_nomination n JOIN award_category c ON c.body_id = n.body_id AND c.cat_key = n.cat_key WHERE "
            "n.body_id = e.body_id AND n.ordinal = e.ordinal AND c.kind = ?)", (body_id, kind))}


def latest_synced_year(body_id: str, kind: str) -> int | None:
    """The newest year with nominations of this kind for the body (else the newest known year)."""
    db = _reader()
    if db is None:
        return None
    with closing(db):
        row = db.execute(
            "SELECT MAX(e.year) AS y FROM award_edition e WHERE e.body_id = ? AND e.state IN ('done','partial') AND "
            "EXISTS (SELECT 1 FROM award_nomination n JOIN award_category c ON c.body_id = n.body_id AND c.cat_key = "
            "n.cat_key WHERE n.body_id = e.body_id AND n.ordinal = e.ordinal AND c.kind = ?)", (body_id, kind)).fetchone()
        if row and row["y"]:
            return row["y"]
        row = db.execute("SELECT MAX(year) AS y FROM award_edition WHERE body_id = ? AND year <= ?",
                         (body_id, date.today().year)).fetchone()
        return row["y"] if row else None


def _entities(db, qids) -> dict[str, dict]:
    qids = [q for q in dict.fromkeys(qids) if is_qid(q)]
    out: dict[str, dict] = {}
    for i in range(0, len(qids), 500):
        chunk = qids[i:i + 500]
        for r in db.execute(f"SELECT * FROM award_entity WHERE qid IN ({','.join('?' * len(chunk))})", chunk):
            out[r["qid"]] = dict(r)
    return out


def edition_page(body_id: str, year: int, kind: str) -> dict | None:
    """One ceremony for the Awards page: {edition, categories: [{cat_key, name, rank, grp, lead, entries}]} — entries
    grouped per work (people folded in) for work-led categories and per nominee line (work + pos) for person-led ones,
    winners first.
    Each entry carries `work` / `people` with their award_entity row (or None). None when no edition that year."""
    db = _reader()
    if db is None:
        return None
    with closing(db):
        ed = db.execute("SELECT * FROM award_edition WHERE body_id = ? AND year = ? ORDER BY ordinal DESC LIMIT 1",
                        (body_id, year)).fetchone()
        if not ed:
            return None
        ed = dict(ed)
        rows = [dict(r) for r in db.execute(
            "SELECT n.*, c.name AS cat_name, c.rank, c.grp, c.lead, c.kind FROM award_nomination n JOIN award_category c "
            "ON c.body_id = n.body_id AND c.cat_key = n.cat_key WHERE n.body_id = ? AND n.ordinal = ? AND c.kind = ? "
            "ORDER BY c.rank, c.name, n.pos, n.rowid", (body_id, ed["ordinal"], kind))]
        ents = _entities(db, [r["work_qid"] for r in rows] + [r["person_qid"] for r in rows])
    cats: dict[str, dict] = {}
    for r in rows:
        c = cats.setdefault(r["cat_key"], {"cat_key": r["cat_key"], "name": r["cat_name"], "rank": r["rank"],
                                           "grp": r["grp"] or "more", "lead": r["lead"] or "work", "entries": [],
                                           "_by": {}})
        if c["lead"] == "person" and r["person_qid"]:
            # one nominee line: its film + its line position (co-writers share a line, two actors of one film don't)
            key = ("p", r["work_qid"], r["pos"]) if r["work_qid"] else ("p", r["person_qid"])
        else:
            key = ("w", r["work_qid"] or r["person_qid"])
        e = c["_by"].get(key)
        if e is None:
            e = {"won": 0, "pos": r["pos"], "work": None, "people": []}
            c["_by"][key] = e
            c["entries"].append(e)
        e["won"] = max(e["won"], r["won"])
        e["pos"] = min(e["pos"], r["pos"])
        if r["work_qid"] and e["work"] is None:
            e["work"] = {"qid": r["work_qid"], "title": r["work_title"], "ent": ents.get(r["work_qid"])}
        if r["person_qid"] and all(p["qid"] != r["person_qid"] for p in e["people"]):
            e["people"].append({"qid": r["person_qid"], "name": r["person_name"], "ent": ents.get(r["person_qid"])})
    out = []
    for c in cats.values():
        c.pop("_by")
        c["entries"].sort(key=lambda e: (-e["won"], e["pos"]))
        out.append(c)
    out.sort(key=lambda c: (c["rank"] if c["rank"] is not None else seed.MORE_RANK, c["name"] or ""))
    return {"edition": ed, "categories": out}


def _entity_qids_for(db, item_keys, kind: str) -> list[str]:
    tmdb, tvdb = [], []
    for k in item_keys or []:
        m = re.match(r"^(tmdb|tvdb):(\d{1,10})$", str(k or ""))
        if m:
            (tmdb if m.group(1) == "tmdb" else tvdb).append(int(m.group(2)))
    qids: list[str] = []
    col = "tmdb_movie" if kind == "movie" else "tmdb_tv"
    for col_name, vals in ((col, tmdb), ("tvdb", tvdb if kind != "movie" else [])):
        if vals:
            qids += [r["qid"] for r in db.execute(
                f"SELECT qid FROM award_entity WHERE {col_name} IN ({','.join('?' * len(vals))})", vals)]
    return list(dict.fromkeys(qids))


def _body_name(body_id: str) -> str:
    return (seed.BY_ID.get(body_id) or {}).get("name", body_id)


def work_awards(item_keys, kind: str) -> list[dict]:
    """A film / show's rows across every ceremony: [{body_id, body, year, ordinal, won, noms, cats: [{name, won}]}],
    newest first. `item_keys`: 'tmdb:<id>' (a film's TMDB movie id or a show's TMDB TV id, per `kind`) / 'tvdb:<id>'."""
    db = _reader()
    if db is None:
        return []
    with closing(db):
        qids = _entity_qids_for(db, item_keys, kind)
        if not qids:
            return []
        rows = [dict(r) for r in db.execute(
            f"SELECT n.body_id, n.ordinal, n.cat_key, MAX(n.won) AS won, c.name, c.rank, e.year "
            f"FROM award_nomination n JOIN award_category c ON c.body_id = n.body_id AND c.cat_key = n.cat_key "
            f"JOIN award_edition e ON e.body_id = n.body_id AND e.ordinal = n.ordinal "
            f"WHERE n.work_qid IN ({','.join('?' * len(qids))}) GROUP BY n.body_id, n.ordinal, n.cat_key", qids)]
    groups: dict[tuple, dict] = {}
    for r in rows:
        g = groups.setdefault((r["body_id"], r["ordinal"]), {
            "body_id": r["body_id"], "body": _body_name(r["body_id"]), "ordinal": r["ordinal"], "year": r["year"],
            "won": 0, "noms": 0, "cats": []})
        g["noms"] += 1
        g["won"] += 1 if r["won"] else 0
        g["cats"].append({"name": r["name"], "won": bool(r["won"]), "rank": r["rank"] or 0})
    out = list(groups.values())
    for g in out:
        g["cats"].sort(key=lambda c: (not c["won"], c["rank"], c["name"] or ""))
    sort_of = {b["id"]: b["sort"] for b in seed.BODIES}
    out.sort(key=lambda g: (-(g["year"] or 0), sort_of.get(g["body_id"], 99)))
    return out


def person_awards(tmdb_person: int) -> dict:
    """{wins, noms, rows: [{body_id, body, year, cat, won, work_title, work: entity | None}]} newest first; the
    counts are distinct (ceremony, category) pairs."""
    empty = {"wins": 0, "noms": 0, "rows": []}
    db = _reader()
    if db is None:
        return empty
    with closing(db):
        qids = [r["qid"] for r in db.execute("SELECT qid FROM award_entity WHERE tmdb_person = ?", (int(tmdb_person),))]
        if not qids:
            return empty
        rows = [dict(r) for r in db.execute(
            f"SELECT n.body_id, n.ordinal, n.cat_key, n.work_qid, n.work_title, MAX(n.won) AS won, c.name, c.rank, e.year "
            f"FROM award_nomination n JOIN award_category c ON c.body_id = n.body_id AND c.cat_key = n.cat_key "
            f"JOIN award_edition e ON e.body_id = n.body_id AND e.ordinal = n.ordinal "
            f"WHERE n.person_qid IN ({','.join('?' * len(qids))}) GROUP BY n.body_id, n.ordinal, n.cat_key, n.work_qid",
            qids)]
        ents = _entities(db, [r["work_qid"] for r in rows])
    seen: dict[tuple, bool] = {}
    out = []
    for r in rows:
        k = (r["body_id"], r["ordinal"], r["cat_key"])
        seen[k] = seen.get(k, False) or bool(r["won"])
        out.append({"body_id": r["body_id"], "body": _body_name(r["body_id"]), "year": r["year"], "cat": r["name"],
                    "won": bool(r["won"]), "work_title": r["work_title"] or "", "work": ents.get(r["work_qid"]),
                    "rank": r["rank"] or 0})
    sort_of = {b["id"]: b["sort"] for b in seed.BODIES}
    out.sort(key=lambda r: (-(r["year"] or 0), sort_of.get(r["body_id"], 99), r["rank"]))
    return {"wins": sum(1 for v in seen.values() if v), "noms": len(seen), "rows": out}


def win_rows(movie_ids=(), tv_ids=(), tvdb_ids=(), qids=()) -> list[dict]:
    """Poster winner badges (awards-ui item 3): every WON (ceremony, category) of the works matching these TMDB movie /
    TMDB TV / TheTVDB ids or QIDs, in ONE statement (ids passed as JSON arrays, so a page of 1,000 posters is still one
    query): [{qid, tmdb_movie, tmdb_tv, tvdb, body_id, year, cat, rank}]. [] without a media.db (never creates it)."""
    ints = [json.dumps([int(x) for x in v if str(x).isdigit()]) for v in (movie_ids, tv_ids, tvdb_ids)]
    qs = json.dumps([q for q in qids if is_qid(q)])
    if ints == ["[]"] * 3 and qs == "[]":
        return []
    db = _reader()
    if db is None:
        return []
    with closing(db):
        return [dict(r) for r in db.execute(
            "SELECT e.qid, e.tmdb_movie, e.tmdb_tv, e.tvdb, n.body_id, ed.year, c.name AS cat, c.rank "
            "FROM award_entity e JOIN award_nomination n ON n.work_qid = e.qid AND n.won = 1 "
            "JOIN award_category c ON c.body_id = n.body_id AND c.cat_key = n.cat_key "
            "JOIN award_edition ed ON ed.body_id = n.body_id AND ed.ordinal = n.ordinal "
            "WHERE e.qid IN (SELECT qid FROM award_entity WHERE tmdb_movie IN (SELECT value FROM json_each(?)) "
            "UNION SELECT qid FROM award_entity WHERE tmdb_tv IN (SELECT value FROM json_each(?)) "
            "UNION SELECT qid FROM award_entity WHERE tvdb IN (SELECT value FROM json_each(?)) "
            "UNION SELECT value FROM json_each(?))", (*ints, qs))]


MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")


def _known_dates(body_ids) -> dict[str, list[date]]:
    db = _reader()
    out: dict[str, list[date]] = {}
    if db is None:
        return out
    with closing(db):
        for r in db.execute("SELECT body_id, held_on FROM award_edition WHERE held_on IS NOT NULL AND held_on != ''"):
            if r["body_id"] in body_ids:
                try:
                    out.setdefault(r["body_id"], []).append(date.fromisoformat(r["held_on"][:10]))
                except ValueError:
                    pass
    return out


def coming_up(today: date, kind: str, limit: int = 4) -> list[dict]:
    """The next ceremonies of this kind grouped by month, soonest first, `limit` months:
    [{month: 'MAR', year, events: [{body_id, name, date: '14 Mar' | None}]}]. A body's next date is a known edition date on or
    after today (day precision, from the sync), else its usual month (this year if not past, else next year)."""
    bs = [b for b in seed.BODIES if kind in b["kinds"].split(",") and _shown(b)]
    known = _known_dates({b["id"] for b in bs})
    nxt = []
    for b in bs:
        dates = sorted(d for d in known.get(b["id"], []) if d >= today)
        if dates:
            d, exact = dates[0], True
        else:
            m = b["usual_month"]
            held_this_month = any(d.year == today.year and d.month == m and d < today for d in known.get(b["id"], []))
            year = today.year if (m > today.month or (m == today.month and not held_this_month)) else today.year + 1
            d, exact = date(year, m, 1), False
        nxt.append((d, exact, b))
    nxt.sort(key=lambda x: (x[0].year, x[0].month, x[2]["sort"]))
    out: list[dict] = []
    for d, exact, b in nxt:
        label = MONTHS[d.month - 1]
        if not out or out[-1]["_ym"] != (d.year, d.month):
            if len(out) >= limit:
                break
            out.append({"month": label, "year": d.year, "_ym": (d.year, d.month), "events": []})
        out[-1]["events"].append({"body_id": b["id"], "name": b["name"],
                                 "date": f"{d.day} {d.strftime('%b')}" if exact else None})
    for g in out:
        g.pop("_ym")
    return out


def sync_status() -> dict:
    """{updated: ISO | None, done: n, total: n, failed: bool} for the staleness line."""
    db = _reader()
    if db is None:
        return {"updated": None, "done": 0, "total": 0, "failed": False}
    with closing(db):
        row = db.execute("SELECT SUM(CASE WHEN state IN ('done','partial','skipped') THEN 1 ELSE 0 END) AS done, "
                         "COUNT(*) AS total FROM award_edition WHERE year IS NULL OR year <= ?",
                         (date.today().year,)).fetchone()
        last = get_sync(db, "last_pass_at")
        ok = get_sync(db, "last_pass_ok", "1")
    return {"updated": last, "done": row["done"] or 0, "total": row["total"] or 0, "failed": ok == "0"}

