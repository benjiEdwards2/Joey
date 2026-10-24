"""Awards sync (AWARDS_PLAN A3, 2026-10-08): a background READ-only pull from public, keyless hosts into the media.db
`award_*` tables (hub/media_awards_db.py). Nothing on a page ever calls these hosts.

Unit of work = one ceremony edition (body, ordinal):
  * Oscars — one SPARQL on query.wikidata.org per edition (`?st pq:P805 wd:<edition>`), nominees + winners + ids.
  * Golden Globes / BAFTA / Critics' Choice / SAG / Emmys — one en.wikipedia.org `action=parse&prop=wikitext` of the
    ceremony page -> `parse_award_blocks` -> the linked titles resolved to QIDs with enwiki `prop=pageprops` (≤ 50 a
    call, redirects followed) and the QIDs to TMDB / IMDb / TheTVDB ids with one SPARQL per ≤ 150 unseen QIDs.
  * Cannes / DGA / PGA / WGA (Q3: winners only in v1) — one SPARQL per body over its curated category QIDs (P166, plus
    P1346 on the category item), run with discovery; each year becomes a `partial` edition keyed ordinal = year.
Measured deviation from the plan (2026-10-08): `wbgetentities` with claims answered 530 KB for 8 titles (≈ 3 MB per
50), so titles resolve through Wikipedia pageprops + a small ids SPARQL instead — same hosts' data, ~1 % of the bytes.

Discovery (one SPARQL for the six ceremony series; editions with ordinal + date, day precision only for `held_on`)
runs when the last one is ≥ 6 days old. Wikipedia-sourced bodies also list editions from `year_offset` (no call), so
they progress while the SPARQL endpoint is down.
Pacing: sequential, one requests.Session per pass, PACE_S between calls, timeout 30 s, one page in memory at a time,
each edition written in one transaction. Backlog newest first, ≤ CAP editions a pass; passes every 6 h while a backlog
exists, then weekly (Sunday ≥ 09:00 local); the NAS-off window (22:00–07:00 local) is skipped. A weekly pass also
re-pulls editions held within the last 120 days or still to come (synced ≥ 6 days ago).
Failures: 429 -> wait Retry-After (max 120 s) once, a second 429 ends the pass (state kept); 5xx / timeout -> the edition
stays pending with the status / type as its note, the pass goes on; a page no parser shape reads -> skipped;
a parser exception -> failed. Logs carry counts and HTTP status / exception type only — never a URL or a title.
Parser bumps (WP-D1, 2026-10-16): `PARSER_V` is stored in award_sync as `parser_v`; when it differs at the start of a pass,
every edition skipped as "no page shape …" goes back to pending and re-enters the normal backlog (newest first, CAP a pass);
WP-D3 (same bump) also re-queues `done` Wikipedia-sourced editions that have nominations but no winner.
`MEDIA_AWARDS=off` disables the loop; without `AWARDS_CONTACT` (the User-Agent contact the WDQS policy requires)
nothing is ever called.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
import time
from contextlib import closing
from datetime import date, datetime, timedelta, timezone

import requests

from hub import media_awards_db as adb
from hub import media_awards_seed as seed
from hub import media_awards_parse as ap
from hub.ids import home_now

log = logging.getLogger("hub.media_awards")

ENV_CONTACT = "AWARDS_CONTACT"
WDQS = "https://query.wikidata.org/sparql"
WP_API = "https://en.wikipedia.org/w/api.php"
PACE_S = 2.0
TIMEOUT = 30
CAP = 40
RETRY_AFTER_MAX = 120
PAGEPROPS_BATCH = 50
IDS_BATCH = 150
RECENT_DAYS = 120
REFRESH_AFTER = timedelta(days=6)
DISCOVER_AFTER = timedelta(days=6)
BACKLOG_EVERY = timedelta(hours=6)
WEEKLY_DAY, WEEKLY_HOUR = 6, 9          # Sunday, from 09:00 local
OFF_FROM, OFF_TO = 22, 7                # the NAS is off 22:00–07:00 local
FIRST_DELAY_S = 180
PARSER_V = 2                            # bump when parse_award_blocks learns a page shape: re-queues the shapeless skips
TICK_S = 3600

# "Nothing there yet" answers: not backlog (they would hold the 6-hourly cadence forever); the weekly refresh of recent /
# coming editions asks again once the pull is ≥ 6 days old.
SOFT_PENDING = ("no edition id", "no page yet", "nothing recorded yet")

_lock = threading.Lock()   # a manual run and the loop never overlap


class RateLimited(Exception):
    """HTTP 429 twice: end the pass."""


class Unavailable(Exception):
    """5xx / timeout / network / unreadable answer: the edition stays pending (str = status or type only)."""


def disabled() -> bool:
    return os.environ.get("MEDIA_AWARDS", "on").strip().lower() in ("off", "0", "false", "no")


def contact() -> str | None:
    value = " ".join(os.environ.get(ENV_CONTACT, "").split())
    return value[:120] or None


def user_agent(who: str) -> str:
    return f"Joey/awards (+https://joeyhome.net; {who})"


def now_home() -> datetime:
    """Wall-clock at home (hub.ids.home_now: the container's local time without a tz database)."""
    return home_now()


def in_off_window(now_local: datetime) -> bool:
    return now_local.hour >= OFF_FROM or now_local.hour < OFF_TO


# ---- the HTTP client: one per pass ----

def _retry_after(value) -> float:
    try:
        return max(0.0, min(float(str(value).strip()), RETRY_AFTER_MAX))
    except (TypeError, ValueError):
        return 30.0


class Client:
    """`pace` = the pause before every call after the first; `wdqs_gap` (manual runs only, scripts/awards_sync.py
    --wdqs-gap) stretches it before a SPARQL call to at least that long since the previous one."""

    def __init__(self, who: str, session=None, sleep=time.sleep, pace: float = PACE_S, wdqs_gap: float = 0.0):
        self.session = session if session is not None else requests.Session()
        self.headers = {"User-Agent": user_agent(who)}
        self.sleep, self.pace, self.calls = sleep, pace, 0
        self.wdqs_gap, self._last_wdqs = wdqs_gap, None

    def close(self) -> None:
        close = getattr(self.session, "close", None)
        if close:
            close()

    def _get(self, url: str, params: dict, accept: str):
        for attempt in (0, 1):
            if self.calls:
                wait = self.pace
                if url == WDQS and self.wdqs_gap and self._last_wdqs is not None:
                    wait = max(wait, self.wdqs_gap - (time.monotonic() - self._last_wdqs))
                self.sleep(wait)               # never two calls without the pause
            self.calls += 1
            if url == WDQS:
                self._last_wdqs = time.monotonic()
            try:
                resp = self.session.get(url, params=params, headers={**self.headers, "Accept": accept}, timeout=TIMEOUT)
            except requests.Timeout:
                raise Unavailable("timeout") from None
            except requests.RequestException as exc:
                raise Unavailable(type(exc).__name__) from None
            code = resp.status_code
            if code == 429:
                if attempt:
                    raise RateLimited("HTTP 429")
                self.sleep(_retry_after(resp.headers.get("Retry-After")))
                continue
            if code != 200:
                raise Unavailable(f"HTTP {code}")
            return resp
        raise RateLimited("HTTP 429")

    def get_json(self, url: str, params: dict):
        try:
            return self._get(url, params, "application/json").json()
        except ValueError:
            raise Unavailable("unreadable answer") from None

    def sparql(self, query: str) -> str:
        """One SPARQL query (GET, so WDQS may cache it) -> the CSV text."""
        resp = self._get(WDQS, {"query": query}, "text/csv")
        resp.encoding = "utf-8"
        return resp.text

    def wp(self, **params):
        return self.get_json(WP_API, {**params, "format": "json", "formatversion": "2"})


# ---- SPARQL (the shapes recorded in tests/hub/fixtures/awards/) ----

_IDS = """  BIND(EXISTS { ?item wdt:P31 wd:Q5 } AS ?human)
  OPTIONAL { ?item wdt:P4947 ?tm } OPTIONAL { ?item wdt:P4983 ?tt } OPTIONAL { ?item wdt:P4985 ?tp }
  OPTIONAL { ?item wdt:P345 ?imdb } OPTIONAL { ?item wdt:P4835 ?tvdb }"""
_WORK = """  OPTIONAL { ?st pq:P1686 ?work . OPTIONAL { ?work wdt:P4947 ?wtm } OPTIONAL { ?work wdt:P4983 ?wtt } OPTIONAL { ?work wdt:P4835 ?wtvdb } }"""
_LABELS = '  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }'


def _values(qids) -> str:
    return " ".join(f"wd:{q}" for q in qids if adb.is_qid(q))


def discovery_query(series, instance_series=()) -> str:
    """Editions with ordinal + date: `series` items hang off P179 (part of the series), `instance_series` off P31
    (the Oscars ceremonies are instances of Q16913666, not parts of it — found live 2026-10-08)."""
    inst = (f"""
  UNION {{ VALUES ?series {{ {_values(instance_series)} }} ?ed wdt:P31 ?series . }}""" if instance_series else "")
    return f"""SELECT ?series ?ed ?ord ?date ?prec WHERE {{
  {{ VALUES ?series {{ {_values(series)} }} ?ed wdt:P179 ?series . }}{inst}
  ?ed wdt:P393 ?ord .
  OPTIONAL {{ ?ed p:P585/psv:P585 ?tv . ?tv wikibase:timeValue ?date ; wikibase:timePrecision ?prec . }}
}}"""


def discovery_series() -> tuple[list[str], list[str]]:
    part = [b["wd_series"] for b in seed.BODIES if b.get("wd_series") and b.get("wd_series_prop", "P179") == "P179"]
    inst = [b["wd_series"] for b in seed.BODIES if b.get("wd_series") and b.get("wd_series_prop") == "P31"]
    return part, inst


def edition_query(edition_qid: str) -> str:
    return f"""SELECT ?award ?awardLabel ?item ?itemLabel ?won ?human ?tm ?tt ?tp ?imdb ?tvdb ?work ?workLabel ?wtm ?wtt ?wtvdb WHERE {{
  {{ ?item p:P166 ?st . ?st ps:P166 ?award . BIND(1 AS ?won) }} UNION {{ ?item p:P1411 ?st . ?st ps:P1411 ?award . BIND(0 AS ?won) }}
  ?st pq:P805 wd:{edition_qid} .
{_WORK}
{_IDS}
{_LABELS}
}}"""


def winners_query(award_qids) -> str:
    return f"""SELECT ?award ?awardLabel ?item ?itemLabel ?date ?human ?tm ?tt ?tp ?imdb ?tvdb ?work ?workLabel ?wtm ?wtt ?wtvdb WHERE {{
  VALUES ?award {{ {_values(award_qids)} }}
  {{ ?item p:P166 ?st . ?st ps:P166 ?award . }} UNION {{ ?award p:P1346 ?st . ?st ps:P1346 ?item . }}
  ?st pq:P585 ?date .
{_WORK}
{_IDS}
{_LABELS}
}}"""


def ids_query(qids) -> str:
    return f"""SELECT ?item ?human ?tm ?tt ?tp ?imdb ?tvdb WHERE {{
  VALUES ?item {{ {_values(qids)} }}
{_IDS}
}}"""


# ---- discovery ----

def _year(value) -> int | None:
    text = str(value or "")
    if text[:1] in "+-":
        text = text[1:]
    return int(text[:4]) if text[:4].isdigit() and int(text[:4]) > 1900 else None


def editions_from_discovery(body) -> dict[str, list[dict]]:
    """discovery answer -> {body_id: [{ordinal, year, held_on, wd_qid}]}; held_on only at day precision (11)."""
    by_series = {b["wd_series"]: b["id"] for b in seed.BODIES if b.get("wd_series")}
    acc: dict[tuple, dict] = {}
    for r in ap.sparql_rows(body):
        body_id = by_series.get(r.get("series") or "")
        try:
            n = int(str(r.get("ord") or "").strip())
        except ValueError:
            continue
        if not body_id or not 0 < n < 1000:
            continue
        e = acc.setdefault((body_id, n), {"ordinal": n, "year": None, "held_on": None, "wd_qid": None})
        if adb.is_qid(r.get("ed")) and not e["wd_qid"]:
            e["wd_qid"] = r["ed"]
        y = _year(r.get("date"))
        if y:
            precise = str(r.get("prec") or "") == "11"
            if precise and not e["held_on"]:
                e["held_on"], e["year"] = str(r["date"]).lstrip("+")[:10], y
            elif e["year"] is None:
                e["year"] = y
    out: dict[str, list[dict]] = {}
    for (body_id, _), e in sorted(acc.items()):
        out.setdefault(body_id, []).append(e)
    return out


def offset_editions(body: dict, today: date) -> list[dict]:
    """Wikipedia-sourced bodies: ordinals 1 .. next year's, year = offset + ordinal (no call)."""
    off = body.get("year_offset")
    if not off or body["source"] != "wp":
        return []
    return [{"ordinal": n, "year": off + n} for n in range(1, today.year + 2 - off)]


def discover(db, client: Client, today: date, counts: dict) -> None:
    for b in seed.BODIES:
        rows = offset_editions(b, today)
        if rows:
            _insert_new(db, b["id"], rows)
    found = editions_from_discovery(client.sparql(discovery_query(*discovery_series())))
    for body_id, rows in found.items():
        adb.upsert_editions(db, body_id, rows)
    for b in seed.BODIES:
        if b["source"] == "wdw":
            counts["rows"] += pull_winners(db, client, b)
            counts["editions"] += 1
    adb.set_sync(db, "discovered_at", datetime.now(timezone.utc).isoformat(timespec="seconds"))


def _insert_new(db, body_id: str, rows: list[dict]) -> None:
    """Offset editions only fill gaps: an existing row (and its Wikidata facts) is never touched."""
    b = seed.BY_ID[body_id]
    with db:
        db.executemany(
            "INSERT OR IGNORE INTO award_edition(body_id, ordinal, year, wp_title, name, state) VALUES(?,?,?,?,?, 'pending')",
            [(body_id, r["ordinal"], r["year"], ap.wp_title(b.get("wp_title_fmt"), r["ordinal"]),
              adb.edition_name(body_id, r["ordinal"], r["year"])) for r in rows])


# ---- per-edition pulls ----

def pull_winners(db, client: Client, body: dict) -> int:
    """Cannes / DGA / PGA / WGA: one SPARQL over the curated categories; each year -> a 'partial' edition."""
    cats = body.get("categories") or {}
    rows = ap.sparql_rows(client.sparql(winners_query(list(cats))))
    by_year: dict[int, list[dict]] = {}
    for r in rows:
        y = _year(r.get("date"))
        if y:
            by_year.setdefault(y, []).append({**r, "won": "1"})
    total = 0
    adb.upsert_editions(db, body["id"], [{"ordinal": y, "year": y} for y in by_year])
    for y, yrows in by_year.items():
        got = ap.wd_nominations(yrows, names=cats, default_kind="film")
        total += adb.write_edition(db, body["id"], y, _ranked(body["id"], got["categories"]), got["nominations"],
                                   got["entities"], "partial", "wd")
    return total


def _ranked(body_id: str, categories: list[dict]) -> list[dict]:
    for i, c in enumerate(categories):
        c["rank"], c["grp"] = seed.rank_of(body_id, c["kind"], c["name"], ap.slug(c["name"]), c.get("order", i))
    return categories


def pull_oscars(db, client: Client, ed: dict) -> tuple[str, int, str | None]:
    if not adb.is_qid(ed.get("wd_qid")):
        return "pending", 0, "no edition id"
    b = seed.BY_ID[ed["body_id"]]
    rows = ap.sparql_rows(client.sparql(edition_query(ed["wd_qid"])))
    got = ap.wd_nominations(rows, prefixes=b.get("prefixes", ()), default_kind="film")
    if not got["nominations"]:
        return ("pending", 0, "nothing recorded yet") if (ed.get("year") or 0) >= date.today().year else ("done", 0, None)
    cats = sorted(got["categories"], key=lambda c: c["name"])
    n = adb.write_edition(db, ed["body_id"], ed["ordinal"], _ranked(ed["body_id"], cats), got["nominations"],
                          got["entities"], "done", "wd")
    return "done", n, None


def resolve_titles(db, client: Client, titles: list[str]) -> dict[str, str]:
    """enwiki titles -> QIDs ('' = none): the award_title cache first, then pageprops for the rest (≤ 50 a call)."""
    known = adb.cached_titles(db, titles)
    todo = [t for t in dict.fromkeys(titles) if t and t not in known]
    for i in range(0, len(todo), PAGEPROPS_BATCH):
        chunk = todo[i:i + PAGEPROPS_BATCH]
        got = ap.qids_from_pageprops(client.wp(action="query", prop="pageprops", ppprop="wikibase_item",
                                               redirects="1", titles="|".join(chunk)))
        fresh = {t: got.get(t, "") for t in chunk}
        adb.remember_titles(db, fresh)
        known.update(fresh)
    return known


def resolve_entities(db, client: Client, qids, labels: dict[str, str]) -> None:
    """Fetch ids for QIDs not yet in award_entity (≤ IDS_BATCH a query)."""
    todo = sorted(set(q for q in qids if adb.is_qid(q)) - adb.known_entities(db, qids))
    for i in range(0, len(todo), IDS_BATCH):
        chunk = todo[i:i + IDS_BATCH]
        ents = ap.entities_from(client.sparql(ids_query(chunk)))
        for q in chunk:
            e = ents.get(q) or {"qid": q, "kind": "other"}
            e["label"] = e.get("label") or labels.get(q)
            ents[q] = e
        with db:
            adb.upsert_entities(db, list(ents.values()))


def _side(ref: dict | None, qids: dict[str, str], by_label: dict[str, str]) -> tuple[str, str]:
    """(key, label) of one nominee side: QID when its title resolved, else '~slug'."""
    if not ref or not ref.get("label"):
        return "", ""
    title = ref.get("title") or by_label.get(ref["label"])
    q = qids.get(title or "", "")
    return (q if adb.is_qid(q) else adb.local_key(ref["label"])), ref["label"]


def named_keys(db, body_id: str) -> dict[tuple[str, str], str]:
    """{(kind, lower-cased name): QID cat_key} of a body's linked categories; a name two of them share is left out."""
    out: dict[tuple[str, str], str] = {}
    seen: set[tuple[str, str]] = set()
    for r in db.execute("SELECT cat_key, name, kind FROM award_category WHERE body_id = ?", (body_id,)):
        if not adb.is_qid(r["cat_key"]):
            continue
        k = (r["kind"], str(r["name"] or "").lower())
        if k in seen:
            out.pop(k, None)
        else:
            seen.add(k)
            out[k] = r["cat_key"]
    return out


def wp_nominations(body_id: str, blocks: list[dict], qids: dict[str, str],
                   named: dict[tuple[str, str], str] | None = None) -> tuple[list[dict], list[dict], dict]:
    """Parsed blocks + resolved titles -> (categories, nominations, labels by QID). A category whose page gave no QID
    takes the key of the one linked category with its kind and name (`named`, JY-152: unlinked table header cells),
    else a slug."""
    b = seed.BY_ID[body_id]
    kinds = b["kinds"].split(",")
    by_label: dict[str, str] = {}
    for blk in blocks:                       # a later unlinked mention reuses the page's linked title
        for e in blk["entries"]:
            for ref in [e.get("work")] + list(e.get("people") or []):
                if ref and ref.get("title"):
                    by_label.setdefault(ref["label"], ref["title"])
    cats: dict[str, dict] = {}
    noms: list[dict] = []
    labels: dict[str, str] = {}
    for order, blk in enumerate(blocks):
        kind = kinds[0] if len(kinds) == 1 else ap.category_kind(blk["label"], blk.get("kind"))
        cq = qids.get(blk.get("page") or "", "")
        cat_key = (cq if adb.is_qid(cq) else (named or {}).get((kind, blk["label"].lower()))
                   or ap.slug(blk["label"]) or f"cat-{order}")
        leads = [e["lead"] for e in blk["entries"]]
        lead = "person" if leads.count("person") > leads.count("work") else "work"
        c = cats.setdefault(cat_key, {"cat_key": cat_key, "name": blk["label"], "kind": kind, "lead": lead,
                                      "order": order})
        for e in blk["entries"]:
            wq, wt = _side(e.get("work"), qids, by_label)
            people = [_side(p, qids, by_label) for p in e.get("people") or []]
            for q, label in [(wq, wt)] + people:
                if adb.is_qid(q):
                    labels.setdefault(q, label)
            base = {"cat_key": c["cat_key"], "work_qid": wq, "work_title": wt, "won": int(bool(e["won"])),
                    "pos": e["pos"]}
            if lead == "work" or not people:
                noms.append({**base, "person_qid": "", "person_name": ""})
            for pq, pn in people:
                noms.append({**base, "person_qid": pq, "person_name": pn})
    return _ranked(body_id, list(cats.values())), noms, labels


def pull_wp(db, client: Client, ed: dict) -> tuple[str, int, str | None]:
    title = ed.get("wp_title")
    if not title:
        return "skipped", 0, "no page title"
    body = client.wp(action="parse", page=title, prop="wikitext", redirects="1")
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        code = str(body["error"].get("code") or "error")[:40]
        if code == "missingtitle":
            future = (ed.get("year") or 0) >= date.today().year
            return ("pending", 0, "no page yet") if future else ("skipped", 0, "no page")
        raise Unavailable(code)
    wikitext = ((body or {}).get("parse") or {}).get("wikitext") if isinstance(body, dict) else None
    if not isinstance(wikitext, str):
        raise Unavailable("unreadable answer")
    parsed = ap.parse_award_blocks(wikitext)
    del body, wikitext
    if parsed["shape"] != ap.SHAPE_OK:
        return "skipped", 0, f"no page shape ({parsed['shape']})"
    blocks = parsed["blocks"]
    titles = ap.titles_of(blocks)
    qids = resolve_titles(db, client, titles)
    cats, noms, labels = wp_nominations(ed["body_id"], blocks, qids, named_keys(db, ed["body_id"]))
    resolve_entities(db, client, list(labels), labels)
    n = adb.write_edition(db, ed["body_id"], ed["ordinal"], cats, noms, [], "done", "wp")
    return "done", n, None


# ---- the pass ----

def requeue_on_parser_bump(db) -> int:
    """A new PARSER_V: editions skipped for their page shape go back to pending, and so do `done` Wikipedia-sourced
    editions with nominations but no winner (WP-D3: a winner line the old parser dropped) — once per bump. A re-pulled
    edition is rewritten whole by `write_edition`. -> editions re-queued (both kinds)."""
    if adb.get_sync(db, "parser_v") == str(PARSER_V):
        return 0
    wp = [b["id"] for b in seed.BODIES if b["source"] == "wp"]
    with db:
        shapeless = db.execute("UPDATE award_edition SET state = 'pending', note = NULL "
                               "WHERE state = 'skipped' AND note LIKE 'no page shape%'").rowcount
        winnerless = db.execute(
            "UPDATE award_edition SET state = 'pending', note = NULL "
            f"WHERE state = 'done' AND body_id IN ({','.join('?' * len(wp))}) AND EXISTS ("
            "SELECT 1 FROM award_nomination n WHERE n.body_id = award_edition.body_id "
            "AND n.ordinal = award_edition.ordinal GROUP BY n.body_id, n.ordinal HAVING MAX(n.won) = 0)", wp).rowcount
    adb.set_sync(db, "parser_v", PARSER_V)
    log.info("awards: parser v%s, %s shapeless skips, %s winner-less editions re-queued", PARSER_V, shapeless,
             winnerless)
    return shapeless + winnerless


def _est_date(ed: dict) -> date | None:
    try:
        return date.fromisoformat(str(ed.get("held_on") or "")[:10])
    except ValueError:
        pass
    b = seed.BY_ID.get(ed["body_id"]) or {}
    return date(ed["year"], b.get("usual_month", 1), 15) if ed.get("year") else None


def select_work(db, today: date, cap: int) -> tuple[list[dict], int]:
    """(editions to pull this pass, backlog size): pending ones up to this year newest first, then (if room) editions
    held within RECENT_DAYS or still to come whose last pull is ≥ 6 days old."""
    rows = [dict(r) for r in db.execute("SELECT * FROM award_edition")]
    src = {b["id"]: b["source"] for b in seed.BODIES}
    rows = [r for r in rows if src.get(r["body_id"]) in ("wd", "wp")]
    backlog = [r for r in rows if r["state"] == "pending" and (r["year"] or 0) <= today.year
               and r.get("note") not in SOFT_PENDING]
    backlog.sort(key=lambda r: (-(r["year"] or 0), seed.BY_ID[r["body_id"]]["sort"]))
    picked = backlog[:cap]
    if len(picked) < cap:
        cut = today - timedelta(days=RECENT_DAYS)
        stale = (datetime.now(timezone.utc) - REFRESH_AFTER).isoformat(timespec="seconds")
        ids = {(r["body_id"], r["ordinal"]) for r in picked}
        due = [r for r in rows if (r["body_id"], r["ordinal"]) not in ids and r["state"] in ("done", "pending")
               and (_est_date(r) or date.min) >= cut and (not r["synced_at"] or r["synced_at"] < stale)]
        due.sort(key=lambda r: (_est_date(r) or date.min), reverse=True)
        picked += due[:cap - len(picked)]
    return picked, len(backlog)


def run_pass(cap: int = CAP, client: Client | None = None, today: date | None = None,
             only: tuple[str, int] | None = None, discover_now: bool | None = None) -> dict:
    """One pass (or one edition with `only=(body_id, ordinal)`). -> counts; never raises."""
    counts = {"editions": 0, "rows": 0, "failed": 0, "skipped": 0, "pending": 0, "calls": 0, "rate_limited": False}
    who = contact()
    if who is None:
        counts["no_contact"] = True
        return counts
    if not _lock.acquire(blocking=False):
        counts["busy"] = True
        return counts
    today = today or now_home().date()
    own = client is None
    client = client or Client(who)
    ok = True
    try:
        with closing(adb.ensure()) as db:
            try:
                counts["requeued"] = requeue_on_parser_bump(db)
                last = adb.get_sync(db, "discovered_at")
                stale = not last or datetime.fromisoformat(last) < datetime.now(timezone.utc) - DISCOVER_AFTER
                if discover_now if discover_now is not None else (stale and only is None):
                    try:
                        discover(db, client, today, counts)
                    except Unavailable as exc:    # Wikipedia-sourced editions still go ahead (offset editions)
                        counts["discovery"] = str(exc)[:60]
                        ok = False
                if only is not None:
                    row = db.execute("SELECT * FROM award_edition WHERE body_id = ? AND ordinal = ?", only).fetchone()
                    work, backlog = ([dict(row)] if row else []), None
                else:
                    work, backlog = select_work(db, today, cap)
                for ed in work:
                    pull = pull_oscars if seed.BY_ID[ed["body_id"]]["source"] == "wd" else pull_wp
                    try:
                        state, n, note = pull(db, client, ed)
                    except Unavailable as exc:
                        adb.set_state(db, ed["body_id"], ed["ordinal"], "pending", str(exc)[:60])
                        counts["pending"] += 1
                        continue
                    except RateLimited:
                        raise
                    except (sqlite3.Error, OSError):
                        raise
                    except Exception as exc:      # a parser bug never stops the pass
                        log.warning("awards: edition failed: %s", type(exc).__name__)
                        adb.set_state(db, ed["body_id"], ed["ordinal"], "failed", type(exc).__name__, synced=True)
                        counts["failed"] += 1
                        continue
                    if state == "done":
                        counts["editions"] += 1
                        counts["rows"] += n
                    else:
                        adb.set_state(db, ed["body_id"], ed["ordinal"], state, note, synced=True)
                        counts["skipped" if state == "skipped" else "pending"] += 1
            except RateLimited:
                counts["rate_limited"] = True
            if only is None:
                _, backlog = select_work(db, today, 0)
                adb.set_sync(db, "backlog", backlog)
                adb.set_sync(db, "last_pass_at", datetime.now(timezone.utc).isoformat(timespec="seconds"))
                failed = (not ok or counts["rate_limited"]) and not counts["editions"]   # outright: nothing landed
                adb.set_sync(db, "last_pass_ok", "0" if failed else "1")
                counts["calls"] = client.calls
    except (sqlite3.Error, OSError) as exc:
        log.warning("awards pass failed: %s", type(exc).__name__)
    finally:
        counts["calls"] = client.calls
        if own:
            client.close()
        _lock.release()
    log.info("awards: %(editions)s editions, %(rows)s rows, %(failed)s failed, %(pending)s pending, "
             "%(skipped)s skipped, %(calls)s calls%(rl)s", {**counts, "rl": " · rate limited" if counts["rate_limited"] else ""})
    return counts


# ---- cadence ----

def due(now_local: datetime, last_iso: str | None, backlog: int) -> bool:
    if in_off_window(now_local):
        return False
    if not last_iso:
        return True
    try:
        last = datetime.fromisoformat(last_iso)
    except ValueError:
        return True
    elapsed = now_local.astimezone(timezone.utc) - last.astimezone(timezone.utc)
    if backlog > 0:
        return elapsed >= BACKLOG_EVERY
    if elapsed >= timedelta(days=8):
        return True
    return now_local.weekday() == WEEKLY_DAY and now_local.hour >= WEEKLY_HOUR and elapsed >= timedelta(hours=20)


def tick(now_local: datetime | None = None) -> dict | None:
    """The loop's hourly step: run a pass when one is due. None when nothing ran."""
    if disabled() or contact() is None:
        return None
    now_local = now_local or now_home()
    if in_off_window(now_local):
        return None
    with closing(adb.ensure()) as db:
        last = adb.get_sync(db, "last_pass_at")
        try:
            backlog = int(adb.get_sync(db, "backlog", "1") or 1)
        except ValueError:
            backlog = 1
    if not due(now_local, last, backlog):
        return None
    return run_pass(today=now_local.date())
