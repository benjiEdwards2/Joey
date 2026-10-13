"""Awards pages (AWARDS_PLAN A4, 2026-10-08): Movies > Awards and TV Shows > Awards, the tab after To rate.

`GET /media/movies/awards` / `GET /media/tv/awards` (`?body=oscars&year=2025&v=films&f=all&s=wins`; the old `unseen=1`
still means `f=unseen`). Two views (Awards ballot, 2026-10-14, BALLOT_CONTRACT.md): `v=films` (default) is the ballot -
the edition pivoted by work, one row per film / show (wins, nominations, category pills, seen / on your server /
watchlisted), filtered (`f`: all, the headline category, acting, direction & writing, craft, not seen, on your server)
and sorted (`s`: most wins, most nominations, A to Z), with a progress head, the short-film categories folded apart and
the person-led winners as a people strip; `v=categories` is every category as a card in curated rank order (Q2: shorts /
documentary / technical fold under "More categories"). The hero and the Most wins podium were dropped (decision B5).
Around both: the picker data (ceremonies, the year strip, the year-keeping switch with its nearest-year fallback +
note, "Latest") and Next up / Coming up. Reads only the media.db `award_*` tables, the watchlist, and the jellyfin
snapshot (on-server posters, the viewer's own played flag, Q4) plus the diary for seen. Off-server posters and
portraits come from Jellyseerr's cached metadata reads (media_discover.meta_get, 6 h + disk), all after the response
(M-46, F2 2026-10-12): the first rows' works first (the headline category's in the categories view, <= FIRST_READS),
then the rest of the visible edition (<= POSTER_READS in all), each stored on its award_entity row so it is read once
and drawn from the next view on. Never calls the award hosts.

Page weight (E7, 2026-10-13): the films view draws its first FIRST_ROWS rows and the categories view its first
FIRST_CARDS cards; the rest comes in ONE htmx request (`/media/{movies,tv}/awards/part/rows` resp.
`/part/categories`, `hx-trigger="revealed"` on a sentinel that swaps itself out). Without JS the sentinel is a plain
link to `?all=1` (the whole view at once).
"""

from __future__ import annotations

import logging
import re
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import date, datetime, timezone
from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from starlette.background import BackgroundTask

from hub import media_awards_db as adb
from hub import media_awards_badges as badges
from hub import media_awards_icons as icons
from hub import media_awards_seed as seed
from hub import media_db, media_discover as md, media_home, media_item, media_pages, media_text, shell
from hub import media_watchlist_db as wl
from hub.ids import JELLYFIN_SNAPSHOT_ID

log = logging.getLogger("hub.media_awards_pages")
router = APIRouter()

PATHS = {"movie": "/media/movies/awards", "tv": "/media/tv/awards"}
PARTS = {k: v + "/part/categories" for k, v in PATHS.items()}
ROW_PARTS = {k: v + "/part/rows" for k, v in PATHS.items()}
AKIND = {"movie": "film", "tv": "tv"}
POSTER_READS, FIRST_READS, READ_WORKERS = 60, 12, 4
FIRST_CARDS = 4             # category cards on the first screen (E7); the rest load through the part route
FIRST_ROWS = 12             # ballot rows on the first screen; the rest load through the rows part route
PILLS = 5                   # category pills on a ballot row; the rest are "+N"
WHO_ICONS = ("person", "clapper")   # pills that name their first person: acting and directing (WP-C3, the mockup)
VIEWS = ("films", "categories")
FILTERS = ("all", "headline", "acting", "direction", "craft", "unseen", "server")
SORTS = {"wins": "Most wins", "noms": "Most nominations", "az": "A to Z"}
FILTER_WORDS = {"all": "All", "acting": "Acting", "craft": "Craft", "unseen": "Not seen", "server": "On your server"}
DIRECTION_WORDS = {"movie": "Direction & writing", "tv": "Writing & directing"}
SHORT_RE = re.compile(r"\bshort\b", re.I)
WRITING_RE = re.compile(r"Writing\s*(?:\((.+)\)|,\s*(.+))")   # short_name: "Writing (X)" / "Writing, X" -> "X"
ALL_SEEN = "Everything here is seen."
NO_MATCH = "Nothing matches that filter."
NOMINEES_SHOWN = 4          # nominee thumbnails on a category card; the rest fold under "+N more"
PEOPLE_SHOWN = 3
EMPTY = "Nothing recorded for this ceremony yet."
PENDING = "Not synced yet"


_date_short = media_text.short_date   # '2025-03-02' -> '2 Mar 2025' ('2 Mar' this year)


def status_line(st: dict) -> dict:
    """{text, failed} — 'Updated 3 Oct · 388 of 402 ceremonies'; nothing synced yet -> 'Not synced yet'."""
    if not st.get("updated") and not st.get("done"):
        return {"text": PENDING, "failed": st.get("failed", False)}
    try:
        when = datetime.fromisoformat(st["updated"]).astimezone(timezone.utc).date().isoformat() if st.get("updated") else None
    except ValueError:
        when = None
    parts = [f"Updated {_date_short(when)}" if when else None, f"{st['done']:,} of {st['total']:,} ceremonies"]
    return {"text": " · ".join(p for p in parts if p), "failed": bool(st.get("failed"))}


# ---- library + seen ----

def _library(data: dict, view: str, kind: str) -> dict[str, dict]:
    """{item_key: row} of the viewer's own library list for this kind (Q4: the viewer's own played flag)."""
    items, _marks = media_pages._library_lists(data or {}, view, kind)
    return {r["item_key"]: r for r in items or [] if isinstance(r, dict) and r.get("item_key")}


def _diary_keys(owner: str) -> set[str]:
    db = media_db._read()
    if db is None:
        return set()
    try:
        with closing(db):
            return {r["item_key"] for r in db.execute("SELECT DISTINCT item_key FROM diary WHERE owner = ?", (owner,))}
    except sqlite3.Error as exc:
        log.warning("awards: diary read skipped: %s", type(exc).__name__)
        return set()


def _keys_of(ent: dict | None, kind: str) -> list[str]:
    if not ent:
        return []
    out = []
    if kind == "movie" and ent.get("tmdb_movie"):
        out.append(f"tmdb:{ent['tmdb_movie']}")
    if kind == "tv":
        if ent.get("tmdb_tv"):
            out.append(f"tmdb:{ent['tmdb_tv']}")
        if ent.get("tvdb"):
            out.append(f"tvdb:{ent['tvdb']}")
    return out


class Seen:
    """Resolves an award work to the viewer's library row and seen state (played, or any diary row for it)."""

    def __init__(self, lib: dict[str, dict], diary: set[str], kind: str):
        self.lib, self.kind = lib, kind
        self.diary = set(diary)
        for key, r in lib.items():           # a TV diary row may hang off the series' jf: key
            if r.get("jf_id") and f"jf:{r['jf_id']}" in diary:
                self.diary.add(key)

    def row(self, ent):
        for k in _keys_of(ent, self.kind):
            if k in self.lib:
                return self.lib[k]
        return None

    def seen(self, ent) -> bool:
        row = self.row(ent)
        if row and row.get("played"):
            return True
        return any(k in self.diary for k in _keys_of(ent, self.kind))


def _work_href(ent: dict | None, row: dict | None, kind: str) -> str | None:
    if row and media_item.ITEM_RE.match(str(row.get("jf_id") or "")):
        return f"/media/item/{row['jf_id']}"
    if ent and kind == "movie" and ent.get("tmdb_movie"):
        return f"/media/title/movie/{ent['tmdb_movie']}"
    if ent and kind == "tv" and ent.get("tmdb_tv"):
        return f"/media/title/tv/{ent['tmdb_tv']}"
    return None


def card(entry: dict, lead: str, seen: Seen, kind: str) -> dict:
    """One nominee for the template: {won, title, sub, poster, href, seen, portrait}."""
    work = entry.get("work") or {}
    went = work.get("ent")
    row = seen.row(went)
    people = entry.get("people") or []
    names = [p["name"] for p in people if p.get("name")]
    work_title = work.get("title") or (went or {}).get("label") or ""
    poster = (row or {}).get("poster") or (went or {}).get("poster")
    href = _work_href(went, row, kind)
    if lead == "person" and people:
        pent = people[0].get("ent") or {}
        title = " · ".join(names[:2]) or "—"
        sub = work_title or None
        portrait = pent.get("poster")
        if pent.get("tmdb_person"):
            href = f"/media/person/{pent['tmdb_person']}"
        pic = portrait or poster
    else:
        title = work_title or " · ".join(names[:2]) or "—"
        sub = " · ".join(names[:PEOPLE_SHOWN]) + (f" +{len(names) - PEOPLE_SHOWN}" if len(names) > PEOPLE_SHOWN else "") \
            if names and work_title else None
        portrait = None
        pic = poster
    return {"won": bool(entry.get("won")), "title": title, "sub": sub or None, "poster": pic, "href": href,
            "seen": seen.seen(went), "work_qid": work.get("qid") or "", "portrait": bool(portrait),
            "_ent": went, "_row": row}


# ---- lazy posters (Jellyseerr meta cache, never the award hosts) ----

def _need_poster(page: dict | None) -> list[dict]:
    """Entities on the visible edition without a picture, in edition order (works and people)."""
    out, seen_q = [], set()
    for c in (page or {}).get("categories") or []:
        for e in c["entries"]:
            for ent in [(e.get("work") or {}).get("ent")] + [p.get("ent") for p in e.get("people") or []]:
                if ent and not ent.get("poster") and ent["qid"] not in seen_q and (
                        ent.get("tmdb_movie") or ent.get("tmdb_tv") or ent.get("tmdb_person")):
                    seen_q.add(ent["qid"])
                    out.append(ent)
    return out


def _fill_order(page: dict | None, first: set[str]) -> list[dict]:
    """The BackgroundTask's queue (F3): the entities of `first` (the first rows' works, or the headline category's
    entities in the categories view) first, up to FIRST_READS, then the rest of the edition; POSTER_READS in all."""
    need = _need_poster(page)
    head = [e for e in need if e["qid"] in first][:FIRST_READS]
    taken = {e["qid"] for e in head}
    return (head + [e for e in need if e["qid"] not in taken])[:POSTER_READS]


def _read_poster(ent: dict) -> str | None:
    if ent.get("kind") == "person" and ent.get("tmdb_person"):
        body = md.meta_get(f"/api/v1/person/{ent['tmdb_person']}")
        return md._ref((body or {}).get("profilePath")) if isinstance(body, dict) else None
    path = (f"/api/v1/movie/{ent['tmdb_movie']}" if ent.get("tmdb_movie") else
            f"/api/v1/tv/{ent['tmdb_tv']}" if ent.get("tmdb_tv") else None)
    if not path:
        return None
    body = md.meta_get(path)
    return md._ref((body or {}).get("posterPath")) if isinstance(body, dict) else None


def fill_later(ents: list[dict]) -> int:
    """The awards page's BackgroundTask (M-46, F2 2026-10-12): the visible edition's missing posters, the first rows'
    works first - all after the response, never before the render."""
    return fill_posters(ents, len(ents))


def fill_posters(ents: list[dict], limit: int) -> int:
    """Read + store up to `limit` posters (in parallel, READ_WORKERS); entities are updated in place. -> filled."""
    ents = ents[:max(0, limit)]
    if not ents or md._creds() is None:
        return 0
    with ThreadPoolExecutor(max_workers=READ_WORKERS) as pool:
        refs = list(pool.map(_read_poster, ents))
    n = 0
    for ent, ref in zip(ents, refs):
        if ref:
            ent["poster"] = ref
            try:
                adb.set_poster(ent["qid"], ref)
                n += 1
            except (sqlite3.Error, OSError) as exc:
                log.warning("awards: poster not stored: %s", type(exc).__name__)
    return n


# ---- the page ----

def _href(kind: str, body: str, year: int | None, unseen: bool = False, path: str | None = None, all_: bool = False,
          v: str = "films", f: str = "all", s: str = "wins") -> str:
    """A link to the Awards page (or one of its parts): body, year, then the view / filter / sort when not the default
    (the old `unseen` flag is written as `f=unseen`), then `all`."""
    f = "unseen" if unseen and f == "all" else f
    q = [("body", body)] + ([("year", str(year))] if year else []) + ([("v", v)] if v != "films" else []) \
        + ([("f", f)] if f != "all" else []) + ([("s", s)] if s != "wins" else []) + ([("all", "1")] if all_ else [])
    return (path or PATHS[kind]) + "?" + urlencode(q)


def _edition_line(body_id: str, ed: dict | None, kind: str) -> str | None:
    if not ed:
        return None
    parts = [ed.get("name") or adb.edition_name(body_id, ed["ordinal"], ed.get("year"))]
    when = _date_short(ed.get("held_on"))
    if when:
        parts.append(when)
    films_of = _films_of(body_id, ed, kind)
    if films_of:
        parts.append(f"films of {films_of}")
    return " · ".join(parts)


def _films_of(body_id: str, ed: dict | None, kind: str) -> int | None:
    """The release year a film edition honours (the year before the ceremony, for the wd / wp sources); None for TV."""
    b = seed.BY_ID.get(body_id) or {}
    if kind == "movie" and b.get("source") in ("wd", "wp") and (ed or {}).get("year"):
        return ed["year"] - 1
    return None


# ---- the ballot (films view, Awards ballot 2026-10-14; BALLOT_CONTRACT.md §2) ----

SORT_KEYS = {"wins": lambda r: (-r["wins"], -r["noms"], r["title"].lower()),
             "noms": lambda r: (-r["noms"], -r["wins"], r["title"].lower()),
             "az": lambda r: r["title"].lower()}


def short_name(name: str | None) -> str:
    """A pill's category name (decision C3): a leading "Best " / "Outstanding " stripped, "Supporting " -> "Supp. ",
    "Original " -> "Orig. ", "Adapted " -> "Adapt. ", a trailing " Feature" / " Feature Film" dropped, and a "Writing"
    name carrying its kind in parentheses or after a comma keeps only that kind ("Writing (Original Screenplay)" ->
    "Orig. Screenplay", WP-C3); nothing else."""
    n = name or ""
    for lead in ("Best ", "Outstanding "):
        if n.startswith(lead):
            n = n[len(lead):]
            break
    n = n.replace("Supporting ", "Supp. ").replace("Original ", "Orig. ").replace("Adapted ", "Adapt. ")
    for tail in (" Feature Film", " Feature"):
        if n.endswith(tail):
            n = n[:-len(tail)]
            break
    m = WRITING_RE.fullmatch(n)
    return (m.group(1) or m.group(2)).strip() if m else n


def is_short(cat: dict) -> bool:
    """A short-film category (decision A3): its works fold under "Shorts", out of the rows, filters and progress."""
    return bool(SHORT_RE.search(cat.get("name") or ""))


def cat_groups(cat: dict, headline_key: str | None) -> set[str]:
    """The filter groups of one category (D1): `headline` = the rank-0 category; `acting` = the person mark;
    `direction` = the clapper / nib marks; `craft` = everything else that is not the headline."""
    shape = icons.cat_icon(cat.get("name"))
    out = {"headline"} if headline_key and cat["cat_key"] == headline_key else set()
    if shape == "person":
        out.add("acting")
    elif shape in ("clapper", "nib"):
        out.add("direction")
    elif not out:
        out.add("craft")
    return out


def _pivot(cats: list[dict]) -> list[dict]:
    """Categories -> their works in edition order: [{qid, title, ent, cats: {cat_key: {name, cat_key, lead, won,
    people}}}]. Two nominee lines of one film in one category fold into one (won if either won; winners' people
    first, as the entries come winners first). Entries without a work are not rows."""
    works: dict[str, dict] = {}
    for c in cats:
        for e in c["entries"]:
            work = e.get("work") or {}
            q = work.get("qid")
            if not q:
                continue
            w = works.get(q)
            if w is None:
                ent = work.get("ent")
                w = works[q] = {"qid": q, "ent": ent, "cats": {},
                                "title": work.get("title") or (ent or {}).get("label") or "—"}
            x = w["cats"].setdefault(c["cat_key"], {"name": c["name"], "cat_key": c["cat_key"], "lead": c["lead"],
                                                     "won": False, "people": []})
            x["won"] = x["won"] or bool(e.get("won"))
            for p in e.get("people") or []:
                if p.get("name") and p["name"] not in x["people"]:
                    x["people"].append(p["name"])
    return list(works.values())


def _tmdb_of(ent: dict | None, kind: str):
    return (ent or {}).get("tmdb_movie" if kind == "movie" else "tmdb_tv")


def ballot_row(w: dict, seen: Seen, kind: str, won_by: dict, wl_keys: set, films_of: int | None = None) -> dict:
    """One work of the edition as a ballot row (contract §2 `row`): its categories won first (edition order kept),
    PILLS of them as short-named pills (acting / directing ones carry their first person), the rest as `more`."""
    ent = w["ent"]
    lib = seen.row(ent)
    cats = sorted(w["cats"].values(), key=lambda x: not x["won"])
    wins, noms = sum(1 for x in cats if x["won"]), len(cats)
    tmdb = _tmdb_of(ent, kind)
    poster = (lib or {}).get("poster") or (ent or {}).get("poster")
    # the server's year; else the edition's "films of" year (award entities carry none; TV has no such year)
    year = (lib or {}).get("year") if isinstance((lib or {}).get("year"), int) else films_of

    def who(x):     # acting and directing pills name their person; the Details fold names everyone
        return x["people"][0] if x["lead"] == "person" and x["people"] and icons.cat_icon(x["name"]) in WHO_ICONS \
            else None

    return {
        "title": w["title"], "year": year, "href": _work_href(ent, lib, kind), "poster": poster,
        "award": won_by.get(w["qid"]), "seen": seen.seen(ent), "on_server": lib is not None,
        "watchlisted": bool(tmdb) and f"tmdb:{tmdb}" in wl_keys,
        "w": {"tmdb_id": tmdb, "kind": kind, "title": w["title"], "year": year, "poster": poster} if tmdb else None,
        "wins": wins, "noms": noms, "won_any": wins > 0,
        "pills": [{"name": short_name(x["name"]), "won": x["won"], "who": who(x)} for x in cats[:PILLS]],
        "more": max(0, noms - PILLS),
        "cats": [{"name": x["name"], "won": x["won"], "who": ", ".join(x["people"]) or None,
                  "lead": "person" if x["lead"] == "person" else "film"} for x in cats],
        "tally": " · ".join(t for t in (_count(wins, "win") if wins else None, _count(noms, "nomination")) if t),
    }


def _watch_keys(owner: str, keys) -> set:
    """The viewer's watchlist keys among `keys`; never raises (empty on a DB problem)."""
    try:
        return wl.contains(owner, keys)
    except (sqlite3.Error, OSError) as exc:
        log.warning("awards: watchlist read skipped: %s", type(exc).__name__)
        return set()


def no_ballot(empty: str | None) -> dict:
    """A ballot with nothing in it (the degraded page): every key the template reads, empty."""
    return {"progress": {"pct": 0, "seen": 0, "total": 0, "headline": None, "server_unseen": 0, "watchlisted": 0},
            "filters": [], "sorts": [], "hidden_seen": None, "rows": [], "rest": 0, "part_rows_href": "",
            "shorts": [], "people": [], "empty": empty}


def ballot(page: dict | None, seen: Seen, kind: str, won_by: dict, owner: str, f: str, s: str, nav,
           empty: str | None, show_all: bool = False, films_of: int | None = None) -> tuple[dict, set[str]]:
    """The films view (contract §2 `ballot`) -> (ballot, the work qids of the rows drawn, for the poster fill order).
    `nav(**state)` links this view with its state changed; `empty` is the page's own wording when there is no edition."""
    all_cats = (page or {}).get("categories") or []
    feature = [c for c in all_cats if not is_short(c)]
    head = next((c for c in feature if c.get("rank") == 0), None)
    hkey = head["cat_key"] if head else None
    works, short_works = _pivot(feature), _pivot([c for c in all_cats if is_short(c)])
    wl_keys = _watch_keys(owner, {f"tmdb:{_tmdb_of(w['ent'], kind)}" for w in works + short_works
                                  if _tmdb_of(w["ent"], kind)})
    items = [(ballot_row(w, seen, kind, won_by, wl_keys, films_of),
              set().union(*(cat_groups(x, hkey) for x in w["cats"].values())), w["qid"]) for w in works]

    def keep(r, groups):
        return (f == "all" or f in groups or (f == "unseen" and not r["seen"]) or (f == "server" and r["on_server"]))

    picked = sorted(((r, q) for r, g, q in items if keep(r, g)), key=lambda t: SORT_KEYS[s](t[0]))
    rows = [r for r, _g, _q in items]
    total, n_seen = len(rows), sum(1 for r in rows if r["seen"])
    heads = [r for r, g, _ in items if "headline" in g]
    labels = {**FILTER_WORDS, "direction": DIRECTION_WORDS[kind],
              "headline": (head["name"] if kind == "movie" else short_name(head["name"])) if head else ""}
    people = []
    for c in feature:               # B6: the acting + directing winners, one per category (its winner's first person)
        if c["lead"] != "person" or icons.cat_icon(c["name"]) not in ("person", "clapper"):
            continue
        p = next((p for e in c["entries"] if e.get("won") for p in e.get("people") or [] if p.get("name")), None)
        if p:
            pent = p.get("ent") or {}
            people.append({"name": p["name"], "cat": short_name(c["name"]), "poster": pent.get("poster"),
                           "href": f"/media/person/{pent['tmdb_person']}" if pent.get("tmdb_person") else None})
    first_n = len(picked) if show_all else FIRST_ROWS
    out = {
        "progress": {"pct": 100 * n_seen // total if total else 0, "seen": n_seen, "total": total,
                     "headline": {"name": head["name"], "seen": sum(1 for r in heads if r["seen"]),
                                  "total": len(heads)} if head else None,
                     "server_unseen": sum(1 for r in rows if r["on_server"] and not r["seen"]),
                     "watchlisted": sum(1 for r in rows if r["watchlisted"])},
        "filters": [{"key": k, "label": labels[k], "on": k == f, "href": nav(f=k)} for k in FILTERS
                    if k != "headline" or head] if total else [],
        "sorts": [{"key": k, "label": label, "on": k == s, "href": nav(s=k)}
                  for k, label in SORTS.items()] if total else [],
        "hidden_seen": n_seen if f == "unseen" else None,
        "rows": [r for r, _ in picked[:first_n]],
        "rest": max(0, len(picked) - first_n),
        "part_rows_href": nav(path=ROW_PARTS[kind]),
        "shorts": [ballot_row(w, seen, kind, won_by, wl_keys, films_of) for w in short_works],
        "people": people,
        "empty": empty or (None if picked or not total else ALL_SEEN if f == "unseen" else NO_MATCH),
    }
    return out, {q for _, q in picked[:first_n]}


# ---- the page context ----

def nearest_year(years: list[int], asked: int) -> int | None:
    """Year-keeping ceremony switch (awards-year, 2026-10-09): the edition year to show when `asked` has none — the
    closest earlier year, else the closest later one; None when there are no years."""
    earlier = [y for y in years if y < asked]
    later = [y for y in years if y > asked]
    return max(earlier) if earlier else (min(later) if later else None)


def tile_month(body_id: str, held: dict[str, int]) -> str | None:
    """A ceremony tile's month line (awards-year item 3): 'Mar' from the selected year's edition date, else the body's
    usual month (the constant Coming up falls back to); None when neither is known."""
    m = held.get(body_id) or (seed.BY_ID.get(body_id) or {}).get("usual_month")
    return date(2000, m, 1).strftime("%b") if m else None


def next_up(coming: list[dict], today: date) -> dict | None:
    """The first event of Coming up (decision B3): {body_id, name, logo, date: 'Sun 11 Jan 2026' | None, days: int |
    None} - the date and the days only when the sync knows the day (else the usual month: both None)."""
    for g in coming:
        for ev in g["events"]:
            when = None
            if ev.get("date"):
                try:
                    when = date(g["year"], adb.MONTHS.index(g["month"]) + 1, int(str(ev["date"]).split()[0]))
                except (ValueError, IndexError):
                    when = None
            return {"body_id": ev["body_id"], "name": ev["name"], "logo": icons.override(ev["body_id"]),
                    "date": f"{when:%a} {when.day} {when:%b %Y}" if when else None,
                    "days": (when - today).days if when else None}
    return None


def awards_ctx(kind: str, body_q: str, year_q: str, unseen: bool, data: dict, view: str, show_all: bool = True,
               v: str = "films", f: str = "all", s: str = "wins") -> tuple[dict, list]:
    """-> (context, entities still to fill after the response). `v` / `f` / `s` are the view, filter and sort (bad
    values fall back to the defaults; `unseen` True is the old `unseen=1`, i.e. `f=unseen`). `show_all` False is the
    page (E7): the films view's `ballot.rows` holds the first FIRST_ROWS rows and `ballot.rest` says how many the rows
    part brings; the categories view's `cats` holds the first FIRST_CARDS cards, `more` is empty and `rest` says how
    many cards the categories part brings. The part requests ask for everything and slice (`rows_part`,
    `categories_part`). The categories view honours only the Not seen filter (as before the ballot)."""
    v = v if v in VIEWS else "films"
    f = f if f in FILTERS else "all"
    f = "unseen" if unseen and f == "all" else f
    s = s if s in SORTS else "wins"
    unseen = f == "unseen"
    akind = AKIND[kind]
    bodies = adb.bodies(akind)
    ids = [b["id"] for b in bodies]
    body = body_q if body_q in ids else ids[0]
    years = adb.years_of(body)
    latest = adb.latest_synced_year(body, akind) or (years[0] if years else None)
    asked = int(year_q) if year_q.isdigit() and body_q in ids else None    # a bad body = a bad link: plain defaults
    year = asked if asked in years else (nearest_year(years, asked) if asked and years else latest)
    missing = {"asked": asked, "shown": year} if asked and year and year != asked else None
    page = adb.edition_page(body, year, akind) if year else None
    owner = media_db.owner_of(view)
    seen = Seen(_library(data, view, kind), _diary_keys(owner), kind)
    ed = (page or {}).get("edition")

    def nav(**over) -> str:
        q = {"body": body, "year": year, "v": v, "f": f, "s": s, **over}
        return _href(kind, q.pop("body"), q.pop("year"), **q)

    state = (ed or {}).get("state")
    empty = None
    if not years:
        empty = PENDING
    elif not page:
        empty = EMPTY
    elif not page["categories"]:
        empty = PENDING if state in ("pending", None) else EMPTY
    won_by = badges.lookup(qids=[(e.get("work") or {}).get("qid") for c in (page or {}).get("categories") or []
                                 for e in c["entries"]])   # awards-ui item 3: one query for the whole edition
    cats, more, the_ballot, first_q = [], [], None, set()
    if v == "films":
        the_ballot, first_q = ballot(page, seen, kind, won_by, owner, f, s, nav, empty, show_all,
                                     _films_of(body, ed, kind))
    for c in ((page or {}).get("categories") or []) if v == "categories" else []:
        cards = [card(e, c["lead"], seen, kind) for e in c["entries"]]
        for x in cards:
            x["award"] = won_by.get(x["work_qid"]) if c["lead"] != "person" else None
        winner_seen = any(x["seen"] for x in cards if x["won"])
        if unseen:
            cards = [x for x in cards if not x["seen"]]
        item = {"name": c["name"], "cat_key": c["cat_key"], "lead": c["lead"], "cards": cards,
                "icon": icons.cat_icon(c["name"]),
                "winners": [x for x in cards if x["won"]], "nominees": [x for x in cards if not x["won"]],
                "dim": unseen and winner_seen, "shown": NOMINEES_SHOWN}
        if c.get("rank") == 0:          # the headline category is the first card now (B5: no hero) and fills first
            first_q |= {ent["qid"] for e in c["entries"] for ent in [(e.get("work") or {}).get("ent")]
                        + [p.get("ent") for p in e.get("people") or []] if ent}
        (cats if c.get("grp") == "core" else more).append(item)
    # M-46 / F2 (2026-10-12): no poster read before the render - the page draws what is stored and the BackgroundTask
    # fills the rest, the first rows' works first (F3), so the next view has them.
    later = _fill_order(page, first_q) if page else []
    years_asc = sorted(years)
    i = years_asc.index(year) if year in years_asc else -1
    prev_y = years_asc[i - 1] if i > 0 else None
    next_y = years_asc[i + 1] if 0 <= i < len(years_asc) - 1 else None
    st = status_line(adb.sync_status())
    today = date.today()
    coming = adb.coming_up(today, akind)
    for i, ev in enumerate(e for m in coming for e in m["events"]):
        ev["next"], ev["logo"] = i == 0, icons.override(ev["body_id"])
    held = adb.held_months(year)
    has_data = adb.data_years(body, akind) if years else set()
    first_n = len(cats) if show_all else FIRST_CARDS
    rest = len(cats[first_n:]) + len(more)
    body_name = (seed.BY_ID.get(body) or {}).get("name", body)
    ctx = {
        "kind": kind, "akind": akind, "base": PATHS[kind], "body": body, "year": year, "unseen": unseen, "view": v,
        "view_hrefs": {x: nav(v=x) for x in VIEWS},
        "bodies": [{**b, "on": b["id"] == body, "href": nav(body=b["id"]), "logo": icons.override(b["id"]),
                    "month": tile_month(b["id"], held)} for b in bodies],
        "years": years,
        "years_list": [{"year": y, "href": nav(year=y), "on": y == year, "has_data": y in has_data} for y in years],
        "year_note": (f"No {body_name} in {missing['asked']} · showing {missing['shown']}") if missing else None,
        "current": {"year": latest, "href": nav(year=None)} if latest and year != latest else None,
        "body_name": body_name,
        "picker": {"name": body_name, "body_id": body, "logo": icons.override(body) or None, "year": year},
        "edition_line": _edition_line(body, ed, kind),
        "prev": {"year": prev_y, "href": nav(year=prev_y)} if prev_y else None,
        "next": {"year": next_y, "href": nav(year=next_y)} if next_y else None,
        "unseen_href": nav(f="all" if unseen else "unseen"),
        "next_up": next_up(coming, today),
        "ballot": the_ballot,
        "cats": cats[:first_n], "more": more if show_all else [], "empty": empty,
        "rest": 0 if show_all else rest,
        "part_href": nav(path=PARTS[kind]), "all_href": nav(all_=True),
        "cats_rest": cats[FIRST_CARDS:], "more_all": more,
        "coming": coming, "sync": st,
    }
    return ctx, later


def degraded_ctx(kind: str, v: str) -> dict:
    """The page's context when media.db cannot be read: every key the template reads, empty (never an undefined
    `ballot`)."""
    v = v if v in VIEWS else "films"
    base = PATHS[kind]
    return {"kind": kind, "akind": AKIND[kind], "base": base, "body": "", "year": None, "unseen": False, "view": v,
            "view_hrefs": {"films": base, "categories": base + "?v=categories"},
            "bodies": [], "years": [], "years_list": [], "year_note": None, "current": None, "body_name": "",
            "picker": None, "edition_line": None, "prev": None, "next": None, "unseen_href": base, "next_up": None,
            "ballot": no_ballot(EMPTY) if v == "films" else None,
            "cats": [], "more": [], "empty": EMPTY, "rest": 0, "part_href": "", "all_href": "",
            "cats_rest": [], "more_all": [], "coming": [], "sync": {"text": PENDING, "failed": False}}


def _page(request: Request, kind: str, body: str, year: str, unseen: str, all_: str = "", v: str = "", f: str = "",
          s: str = ""):
    later: list = []

    def build(data, view):
        nonlocal later
        try:
            ctx, later = awards_ctx(kind, body[:20], year[:4], unseen == "1", data, view, show_all=all_ == "1",
                                    v=v, f=f, s=s)
        except (sqlite3.Error, OSError) as exc:
            log.warning("awards page degraded: %s", type(exc).__name__)
            ctx = degraded_ctx(kind, v)
        return ctx

    resp = media_pages._detail_page(request, "media_awards.html", JELLYFIN_SNAPSHOT_ID, build, always_build=True)
    if later and md._creds() is not None:
        resp.background = BackgroundTask(fill_later, later)
    return resp


@router.get("/media/movies/awards", response_class=HTMLResponse)
def movies_awards(request: Request, body: str = "", year: str = "", unseen: str = "", all: str = "", v: str = "",
                  f: str = "", s: str = ""):
    return _page(request, "movie", body, year, unseen, all[:1], v[:12], f[:12], s[:12])


@router.get("/media/tv/awards", response_class=HTMLResponse)
def tv_awards(request: Request, body: str = "", year: str = "", unseen: str = "", all: str = "", v: str = "",
              f: str = "", s: str = ""):
    return _page(request, "tv", body, year, unseen, all[:1], v[:12], f[:12], s[:12])


def _part_ctx(request: Request, kind: str, body: str, year: str, unseen: str, **state) -> dict:
    """The deferred requests' read (E7): the same query as the page, so the same edition, unsliced ({} when the
    snapshot or media.db cannot be read). No poster fill is queued here (the page already did)."""
    view, _ = shell.resolve_owner_view(request)
    src = shell.find_detail_source(JELLYFIN_SNAPSHOT_ID, shell.get_snapshots(request=request))
    if src is None:
        return {}
    try:
        return awards_ctx(kind, body[:20], year[:4], unseen == "1", media_home.view_jelly(src["data"], view), view,
                          **state)[0]
    except (sqlite3.Error, OSError) as exc:
        log.warning("awards part degraded: %s", type(exc).__name__)
        return {}


def categories_part(request: Request, kind: str, body: str, year: str, unseen: str, f: str = ""):
    """The categories view's ONE deferred request (E7): every category card the first screen did not draw (the core
    cards after the first FIRST_CARDS, then "More categories"), as a fragment that replaces the sentinel."""
    ctx = _part_ctx(request, kind, body, year, unseen, v="categories", f=f[:12])
    return shell.templates.TemplateResponse(request, "_award_cats_part.html",
                                            {"cats": ctx.get("cats_rest") or [], "more": ctx.get("more_all") or []})


@router.get("/media/movies/awards/part/categories", response_class=HTMLResponse)
def movies_awards_part(request: Request, body: str = "", year: str = "", unseen: str = "", f: str = ""):
    return categories_part(request, "movie", body, year, unseen, f)


@router.get("/media/tv/awards/part/categories", response_class=HTMLResponse)
def tv_awards_part(request: Request, body: str = "", year: str = "", unseen: str = "", f: str = ""):
    return categories_part(request, "tv", body, year, unseen, f)


def rows_part(request: Request, kind: str, body: str, year: str, unseen: str, f: str = "", s: str = ""):
    """The films view's ONE deferred request (E7 pattern, F2): the ballot rows after the first FIRST_ROWS, same filter
    and sort, as a fragment that replaces the sentinel."""
    got = (_part_ctx(request, kind, body, year, unseen, f=f[:12], s=s[:12]).get("ballot") or {}).get("rows") or []
    return shell.templates.TemplateResponse(request, "_award_rows_part.html", {"rows": got[FIRST_ROWS:], "kind": kind})


@router.get("/media/movies/awards/part/rows", response_class=HTMLResponse)
def movies_awards_rows(request: Request, body: str = "", year: str = "", unseen: str = "", f: str = "", s: str = ""):
    return rows_part(request, "movie", body, year, unseen, f, s)


@router.get("/media/tv/awards/part/rows", response_class=HTMLResponse)
def tv_awards_rows(request: Request, body: str = "", year: str = "", unseen: str = "", f: str = "", s: str = ""):
    return rows_part(request, "tv", body, year, unseen, f, s)


_count = media_text.plural   # '1 win' / '3 nominations'


def _tally_text(won: int, noms: int) -> str:
    return f"Won {won} of {_count(noms, 'nomination')}" if won else _count(noms, "nomination")


def _grouped(items: list[dict]) -> list[tuple[str, list[dict]]]:
    """[(body_id, items)] in ceremony prestige order (badges.PRESTIGE), each group keeping the items' own order."""
    groups: dict[str, list[dict]] = {}
    for it in items:
        groups.setdefault(it["body_id"], []).append(it)
    order = {b: i for i, b in enumerate(badges.PRESTIGE)}
    return sorted(groups.items(), key=lambda kv: order.get(kv[0], len(order)))


def section_rows(rows: list[dict], kind: str) -> list[dict]:
    """work_awards rows -> the film / TV page section (awards-ui item 5): one group per ceremony (prestige order) with
    its mark and tally ("Won 3 of 7 nominations"), then one whole-link line per edition ("2025 · Won 2 of 3
    nominations", newest first, linked to that ceremony's Awards page) over its category pills (won gold, nominated
    neutral)."""
    page_kind = "movie" if kind == "movie" else "tv"
    out = []
    for body_id, eds in _grouped(rows):
        editions = [{**g, "href": _href(page_kind, g["body_id"], g["year"], False),
                     "line": " · ".join(x for x in (str(g["year"]) if g["year"] else None,
                                                    _tally_text(g["won"], g["noms"])) if x)} for g in eds]
        out.append({"body_id": body_id, "body": eds[0]["body"], "logo": icons.override(body_id),
                    "tally": _tally_text(sum(g["won"] for g in eds), sum(g["noms"] for g in eds)),
                    "editions": editions})
    return out


def person_rows(got: dict) -> dict | None:
    """person_awards -> the person page section (awards-ui item 5), None when there is nothing: the overall "2 wins ·
    5 nominations", then one group per ceremony (prestige order) with its mark and tally, each row "2025 · Best Actor"
    over a gold Won / neutral Nominated pill + the work (one link to the work when it matched, plain otherwise)."""
    if not got or not got.get("rows"):
        return None
    rows = []
    for r in got["rows"]:
        ent = r.get("work") or {}
        kind = "tv" if ent.get("kind") == "tv" else "movie"
        href = (f"/media/title/movie/{ent['tmdb_movie']}" if ent.get("tmdb_movie") else
                f"/media/title/tv/{ent['tmdb_tv']}" if ent.get("tmdb_tv") else None)
        rows.append({**r, "kind": kind, "href": href,
                     "lead": " · ".join(x for x in (str(r["year"]) if r["year"] else None, r["cat"]) if x)})
    groups = []
    for body_id, rs in _grouped(rows):
        cats: dict[tuple, bool] = {}
        for r in rs:
            cats[(r["year"], r["cat"])] = cats.get((r["year"], r["cat"]), False) or r["won"]
        won = sum(cats.values())
        groups.append({"body_id": body_id, "body": rs[0]["body"], "logo": icons.override(body_id), "rows": rs,
                       "tally": " · ".join(x for x in (_count(won, "win") if won else None,
                                                       _count(len(cats), "nomination")) if x)})
    return {"head": f"{_count(got['wins'], 'win')} · {_count(got['noms'], 'nomination')}", "groups": groups,
            "rows": rows}
