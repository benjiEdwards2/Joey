"""Awards pages (AWARDS_PLAN A4, 2026-10-08): Movies > Awards and TV Shows > Awards, the tab after To rate.

`GET /media/movies/awards` / `GET /media/tv/awards` (`?body=oscars&year=2025&unseen=1`): Coming up (the next ceremonies
by month), the ceremony picker (chips), the year stepper (ceremony year, Q1), the Not seen chip, the hero category
(winner poster large + its tally at this ceremony + the nominees), then every category as a card in curated rank order
(Q2: shorts / documentary / technical fold under "More categories"). Reads only the media.db `award_*` tables and the
jellyfin snapshot (on-server posters, the viewer's own played flag, Q4) plus the diary for ✓ seen. Off-server posters
and portraits come from Jellyseerr's cached metadata reads (media_discover.meta_get, 6 h + disk): the hero category's
before the render (≤ HERO_READS), the rest of the visible edition after the response (≤ POSTER_READS in all), each
stored on its award_entity row so it is read once. Never calls the award hosts.
"""

from __future__ import annotations

import logging
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
from hub import media_db, media_discover as md, media_item

log = logging.getLogger("hub.media_awards_pages")
router = APIRouter()

PATHS = {"movie": "/media/movies/awards", "tv": "/media/tv/awards"}
AKIND = {"movie": "film", "tv": "tv"}
POSTER_READS, HERO_READS, READ_WORKERS = 60, 12, 4
NOMINEES_SHOWN = 4          # nominee thumbnails on a category card; the rest fold under "+N more"
PEOPLE_SHOWN = 3
EMPTY = "Nothing recorded for this ceremony yet."
PENDING = "Not synced yet"


def _date_short(value) -> str | None:
    """'2025-03-02' -> '2 Mar 2025' ('2 Mar' this year); junk -> None."""
    try:
        d = date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None
    return f"{d.day} {d.strftime('%b')}" + ("" if d.year == date.today().year else f" {d.year}")


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

def _library(data: dict, view: str, kind: str, hub) -> dict[str, dict]:
    """{item_key: row} of the viewer's own library list for this kind (Q4: the viewer's own played flag)."""
    items, _marks = hub._library_lists(data or {}, view, kind)
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


def hero_backdrop(c: dict | None, kind: str) -> str | None:
    """The hero card's backdrop (awards-ui item 2): the winner's library backdrop, else its TMDB backdrop through the
    Jellyseerr meta cache (6 h + disk, the same read the poster fill makes), else None (a plain gradient)."""
    if not c:
        return None
    if (c.get("_row") or {}).get("backdrop"):
        return c["_row"]["backdrop"]
    ent = c.get("_ent") or {}
    path = (f"/api/v1/movie/{ent['tmdb_movie']}" if kind == "movie" and ent.get("tmdb_movie") else
            f"/api/v1/tv/{ent['tmdb_tv']}" if kind == "tv" and ent.get("tmdb_tv") else None)
    if not path or md._creds() is None:
        return None
    try:
        body = md.meta_get(path)
    except Exception as exc:  # the hero never fails on its backdrop
        log.warning("awards: backdrop skipped: %s", type(exc).__name__)
        return None
    return md._ref(body.get("backdropPath")) if isinstance(body, dict) else None


# ---- lazy posters (Jellyseerr meta cache, never the award hosts) ----

def _need_poster(page: dict | None, hero_only: bool) -> list[dict]:
    """Entities on the visible edition without a picture, hero category first."""
    out, seen_q = [], set()
    for c in (page or {}).get("categories") or []:
        if hero_only and c.get("rank") != 0:
            continue
        for e in c["entries"]:
            for ent in [(e.get("work") or {}).get("ent")] + [p.get("ent") for p in e.get("people") or []]:
                if ent and not ent.get("poster") and ent["qid"] not in seen_q and (
                        ent.get("tmdb_movie") or ent.get("tmdb_tv") or ent.get("tmdb_person")):
                    seen_q.add(ent["qid"])
                    out.append(ent)
    return out


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

def _href(kind: str, body: str, year: int | None, unseen: bool) -> str:
    q = [("body", body)] + ([("year", str(year))] if year else []) + ([("unseen", "1")] if unseen else [])
    return PATHS[kind] + "?" + urlencode(q)


def _edition_line(body_id: str, ed: dict | None, kind: str) -> str | None:
    if not ed:
        return None
    b = seed.BY_ID.get(body_id) or {}
    parts = [ed.get("name") or adb.edition_name(body_id, ed["ordinal"], ed.get("year"))]
    when = _date_short(ed.get("held_on"))
    if when:
        parts.append(when)
    if kind == "movie" and b.get("source") in ("wd", "wp") and ed.get("year"):
        parts.append(f"films of {ed['year'] - 1}")
    return " · ".join(parts)


def _tally(page: dict) -> dict[str, tuple[int, int]]:
    """{work_qid: (categories won, categories nominated)} at this ceremony (this page's kind)."""
    out: dict[str, dict[str, bool]] = {}
    for c in page.get("categories") or []:
        for e in c["entries"]:
            q = (e.get("work") or {}).get("qid")
            if q:
                cats = out.setdefault(q, {})
                cats[c["cat_key"]] = cats.get(c["cat_key"], False) or bool(e.get("won"))
    return {q: (sum(cats.values()), len(cats)) for q, cats in out.items()}


def awards_ctx(kind: str, body_q: str, year_q: str, unseen: bool, data: dict, view: str, hub) -> tuple[dict, list]:
    """-> (context, entities still to fill after the response)."""
    akind = AKIND[kind]
    bodies = adb.bodies(akind)
    ids = [b["id"] for b in bodies]
    body = body_q if body_q in ids else ids[0]
    years = adb.years_of(body, akind)
    year = int(year_q) if year_q.isdigit() and int(year_q) in years else (adb.latest_synced_year(body, akind) or
                                                                        (years[0] if years else None))
    page = adb.edition_page(body, year, akind) if year else None
    if page:
        fill_posters(_need_poster(page, hero_only=True), HERO_READS)
    later = _need_poster(page, hero_only=False)[:max(0, POSTER_READS - HERO_READS)] if page else []
    owner = media_db.owner_of(view)
    seen = Seen(_library(data, view, kind, hub), _diary_keys(owner), kind)
    ed = (page or {}).get("edition")
    hero, cats, more = None, [], []
    tally = _tally(page) if page else {}
    won_by = badges.lookup(qids=[(e.get("work") or {}).get("qid") for c in (page or {}).get("categories") or []
                                 for e in c["entries"]])   # awards-ui item 3: one query for the whole edition
    for c in (page or {}).get("categories") or []:
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
        if c.get("rank") == 0 and hero is None:
            w = item["winners"][0] if item["winners"] else None
            t = tally.get(w["work_qid"]) if w and w["work_qid"] else None
            item["tally"] = (f"Won {t[0]} of {t[1]} nomination{'s' if t[1] != 1 else ''}" if t else None)
            item["backdrop"] = hero_backdrop(w, kind)
            hero = item
        elif c.get("grp") == "core":
            cats.append(item)
        else:
            more.append(item)
    years_asc = sorted(years)
    i = years_asc.index(year) if year in years_asc else -1
    prev_y = years_asc[i - 1] if i > 0 else None
    next_y = years_asc[i + 1] if 0 <= i < len(years_asc) - 1 else None
    st = status_line(adb.sync_status())
    coming = adb.coming_up(date.today(), akind)
    for i, ev in enumerate(e for m in coming for e in m["events"]):
        ev["next"], ev["logo"] = i == 0, icons.override(ev["body_id"])
    state = (ed or {}).get("state")
    empty = None
    if not years:
        empty = PENDING
    elif not page:
        empty = EMPTY
    elif not page["categories"]:
        empty = PENDING if state in ("pending", None) else EMPTY
    ctx = {
        "kind": kind, "akind": akind, "base": PATHS[kind], "body": body, "year": year, "unseen": unseen,
        "bodies": [{**b, "on": b["id"] == body, "href": _href(kind, b["id"], None, unseen), "logo": icons.override(b["id"])}
                   for b in bodies],
        "years": years,
        "body_name": (seed.BY_ID.get(body) or {}).get("name", body),
        "edition_line": _edition_line(body, ed, kind),
        "prev": {"year": prev_y, "href": _href(kind, body, prev_y, unseen)} if prev_y else None,
        "next": {"year": next_y, "href": _href(kind, body, next_y, unseen)} if next_y else None,
        "unseen_href": _href(kind, body, year, not unseen),
        "hero": hero, "cats": cats, "more": more, "empty": empty,
        "coming": coming, "sync": st,
    }
    return ctx, later


def _page(request: Request, kind: str, body: str, year: str, unseen: str):
    from hub import main as hub  # late: hub.main includes this router
    later: list = []

    def build(data, view):
        nonlocal later
        try:
            ctx, later = awards_ctx(kind, body[:20], year[:4], unseen == "1", data, view, hub)
        except (sqlite3.Error, OSError) as exc:
            log.warning("awards page degraded: %s", type(exc).__name__)
            ctx = {"kind": kind, "bodies": [], "years": [], "hero": None, "cats": [], "more": [], "coming": [],
                   "empty": EMPTY, "sync": {"text": PENDING, "failed": False}, "edition_line": None,
                   "prev": None, "next": None, "unseen": False, "unseen_href": PATHS[kind]}
        return ctx

    resp = hub._detail_page(request, "media_awards.html", hub.JELLYFIN_SNAPSHOT_ID, build, always_build=True)
    if later and md._creds() is not None:
        resp.background = BackgroundTask(fill_posters, later, len(later))
    return resp


@router.get("/media/movies/awards", response_class=HTMLResponse)
def movies_awards(request: Request, body: str = "", year: str = "", unseen: str = ""):
    return _page(request, "movie", body, year, unseen)


@router.get("/media/tv/awards", response_class=HTMLResponse)
def tv_awards(request: Request, body: str = "", year: str = "", unseen: str = ""):
    return _page(request, "tv", body, year, unseen)


def _count(n: int, word: str) -> str:
    return f"{n} {word}{'s' if n != 1 else ''}"


def section_rows(rows: list[dict], kind: str) -> list[dict]:
    """work_awards rows -> the film / TV page section: one line per ceremony + its categories, linked to that page."""
    page_kind = "movie" if kind == "movie" else "tv"
    out = []
    for g in rows:
        tally = f"Won {g['won']} of {_count(g['noms'], 'nomination')}" if g["won"] else _count(g["noms"], "nomination")
        out.append({**g, "href": _href(page_kind, g["body_id"], g["year"], False),
                    "line": " · ".join(x for x in (f"{g['body']} {g['year']}" if g["year"] else g["body"], tally) if x)})
    return out


def person_rows(got: dict) -> dict | None:
    """person_awards -> the person page section, None when there is nothing."""
    if not got or not got.get("rows"):
        return None
    rows = []
    for r in got["rows"]:
        ent = r.get("work") or {}
        kind = "tv" if ent.get("kind") == "tv" else "movie"
        href = (f"/media/title/movie/{ent['tmdb_movie']}" if ent.get("tmdb_movie") else
                f"/media/title/tv/{ent['tmdb_tv']}" if ent.get("tmdb_tv") else None)
        rows.append({**r, "kind": kind, "href": href,
                     "lead": " · ".join(x for x in (f"{r['body']} {r['year']}" if r["year"] else r["body"], r["cat"]) if x)})
    return {"head": f"{_count(got['wins'], 'win')} · {_count(got['noms'], 'nomination')}", "rows": rows}
