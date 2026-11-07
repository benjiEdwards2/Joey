"""Person pages (F11, 2026-10-06): click a cast or crew name on a film page and see everything that person
is in. Jellyseerr `person/{id}` + `person/{id}/combined_credits` (server-side, cached 10 min via the film
page's cache), split into "On server" (matched against the Jellyfin snapshot library lists) and
the Films / Film series / Bonus / TV grids. Upstream failure degrades to words, never a 500; no URL or key in the page.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import date
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from hub import media_discover as md, media_follow, media_item, media_person_photo, shell
from hub.ids import JELLYFIN_SNAPSHOT_ID, JELLYSEERR_SNAPSHOT_ID
from hub.media_film import _cget

log = logging.getLogger("hub.media_person")   # M-29: its own logger, not media_discover's
router = APIRouter()

CREDITS_MAX, BIO_MAX, BIO_LEAD = 200, 1200, 400
SHOW_FIRST = 24   # Follow (2026-10-07): a grid shows this many, "Show more" folds the rest
ID_RE = re.compile(r"^[1-9][0-9]{0,9}$")
DOWN_TEXT = "Couldn't reach Seerr — nothing to show for this person yet"


def _bio(text) -> dict | None:
    """{lead, more}: the biography capped at BIO_MAX, the part after ~BIO_LEAD chars folded under 'More'."""
    text = " ".join(str(text or "").split())
    if not text:
        return None
    if len(text) > BIO_MAX:
        text = text[:BIO_MAX].rsplit(" ", 1)[0] + "…"
    if len(text) <= BIO_LEAD + 80:
        return {"lead": text, "more": ""}
    cut = text.rfind(" ", 0, BIO_LEAD)
    cut = cut if cut > 0 else BIO_LEAD
    return {"lead": text[:cut] + "…", "more": text[cut:].strip()}


def _life(person: dict) -> str | None:
    """'Born 12 Mar 1976 · Dublin' / '… · Died 3 Jan 2020'."""
    born, died = md._date_words(person.get("birthday"))[0], md._date_words(person.get("deathday"))[0]
    place = str(person["placeOfBirth"])[:80] if person.get("placeOfBirth") else None
    parts = []
    if born:
        parts.append(f"Born {born}" + (f" · {place}" if place else ""))
    elif place:
        parts.append(place)
    if died:
        parts.append(f"Died {died}")
    return " · ".join(parts) or None


def _library(jelly: dict) -> dict[str, str]:
    """{item_key: jf_id} for every library film and show with a usable Jellyfin id."""
    out = {}
    for field in ("movies", "shows"):
        for r in (jelly or {}).get(field) or []:
            if isinstance(r, dict) and r.get("item_key") and media_item.ITEM_RE.match(str(r.get("jf_id") or "")):
                out[r["item_key"]] = r["jf_id"]
    return out


DOC_GENRE, DOC_VOTES, MIN_VOTES = 99, 100, 10   # JY-293: documentary / bonus thresholds (orchestrator Q3/Q4)
TIERS = ("server", "films", "series", "bonus", "tv")


def _lead(title: str) -> tuple[str, ...]:
    """JY-293 series proxy: the first two words of a title, lower case, punctuation dropped."""
    return tuple(re.findall(r"[a-z0-9]+", title.lower())[:2])


def _tier(r: dict, today: str, leads: dict | None) -> str:
    """JY-293: on server > released films > film series > bonus and other; TV after all films."""
    if r["jf_id"]:
        return "server"
    if r["kind"] == "tv":
        return "tv"
    doc = DOC_GENRE in r["genres"] and r["votes"] < DOC_VOTES
    if r["video"] or not r["date"] or r["date"] > today or r["votes"] < MIN_VOTES or doc:
        return "bonus"
    if leads is None:
        return "films"
    lead = _lead(r["title"])
    return "series" if len(lead) == 2 and leads.get(lead, 0) > 1 else "films"


def _credits(body, lib: dict[str, str]) -> list[dict]:
    """combined_credits -> one row per title (cast + crew roles joined), ordered by JY-293 tier, then newest
    first, votes, title, id; capped after ordering. Each row carries its `tier`."""
    if not isinstance(body, dict):
        return []
    merged: dict[tuple, dict] = {}
    for field in ("cast", "crew"):
        for c in body.get(field) or []:
            row = md._row(c) if isinstance(c, dict) else None
            if not row:
                continue
            if field == "cast":
                role = f"as {str(c['character'])[:80]}" if c.get("character") else ""
            else:
                role = str(c.get("job") or "")[:60]
            try:
                votes = int(c.get("voteCount") or 0)
            except (TypeError, ValueError):
                votes = 0
            m = merged.setdefault((row["kind"], row["tmdb_id"]), {
                **row, "date": str(c.get("releaseDate") or c.get("firstAirDate") or "")[:10], "roles": [],
                "votes": votes, "video": bool(c.get("video")),
                "genres": [g for g in c.get("genreIds") or [] if isinstance(g, int)]})
            if role and role not in m["roles"]:
                m["roles"].append(role)
    today = date.today().isoformat()
    leads: dict[tuple, int] = {}
    for r in merged.values():
        r["jf_id"] = lib.get(f"tmdb:{r['tmdb_id']}")
        # only titles that pass the Films tests count, so a featurette cannot promote a film into Series
        if r["kind"] == "movie" and _tier({**r, "jf_id": None}, today, None) == "films":
            leads[_lead(r["title"])] = leads.get(_lead(r["title"]), 0) + 1
    for r in merged.values():
        r["tier"] = _tier(r, today, leads)
    rows = sorted(merged.values(), key=lambda r: (r["title"].lower(), r["tmdb_id"]))
    rows.sort(key=lambda r: (r["date"], r["votes"]), reverse=True)
    rows.sort(key=lambda r: TIERS.index(r["tier"]))
    rows = rows[:CREDITS_MAX]
    for r in rows:
        r["role"] = " · ".join(r.pop("roles"))
        for k in ("votes", "video", "genres"):
            r.pop(k)
        jf_id = r["jf_id"]
        r["on_server"] = bool(jf_id) or r["status_word"] in md.ON_DISK
        r["word"] = ("On server" if r["on_server"] else r["status_word"] if r["status_word"] in ("Requested", "Processing")
                     else "Not on server")
        r["item_href"] = f"/media/item/{jf_id}" if jf_id else None
    return rows


WRITER_JOBS = ("Screenplay", "Writer", "Story", "Novel")   # JY-280: the film page's Writer chip roles (media_film.CREW_ROLES)


def _writing(body, lib: dict[str, str]) -> list[dict]:
    """JY-280: the writer jobs alone from combined_credits, so the Writer chip lands on their writing work."""
    crew = (body or {}).get("crew") if isinstance(body, dict) else None
    return _credits({"crew": [c for c in crew or [] if isinstance(c, dict) and c.get("job") in WRITER_JOBS]}, lib)


def build_person(tmdb_id: int, snaps=None) -> dict:
    snaps = shell.get_snapshots() if snaps is None else snaps
    jsrc = shell.find_detail_source(JELLYFIN_SNAPSHOT_ID, snaps)
    lib = _library((jsrc or {}).get("data") or {})
    # media-speed: the biography is metadata only (long, restart-proof meta cache); the credits carry each
    # title's request / availability state, so they keep the short cache. Both reads run side by side.
    # JY-291: the tagged-image backdrop read runs beside them; without TMDB_API_KEY it returns at once, no call.
    with ThreadPoolExecutor(max_workers=3) as pool:
        person_f = pool.submit(md.meta_get, f"/api/v1/person/{tmdb_id}")
        tagged_f = pool.submit(media_person_photo.tagged_backdrop, tmdb_id)
        credits = _cget(f"/api/v1/person/{tmdb_id}/combined_credits")
        person = person_f.result()
        tagged = tagged_f.result()
    if not isinstance(person, dict) and not isinstance(credits, dict):
        return {"down": True, "note": DOWN_TEXT, "name": "Person", "tmdb": tmdb_id}
    person = person if isinstance(person, dict) else {}
    rows = _credits(credits, lib)
    here = {(r["kind"], r["tmdb_id"]) for r in rows if r["on_server"]}
    shelf = [r for r in rows if r["jf_id"]]
    rest = [r for r in rows if not r["jf_id"]]
    return {"down": False, "tmdb": tmdb_id, "name": str(person.get("name") or "Unknown")[:120],
            "ref": md._ref(person.get("profilePath")),
            "backdrop": tagged or media_person_photo.credit_backdrop(credits, here),   # JY-291 tagged image, else JY-321 best on-server credit
            "dept": str(person.get("knownForDepartment") or "")[:40],
            "life": _life(person), "bio": _bio(person.get("biography")),
            "shelf": shelf, "films": [r for r in rest if r["tier"] == "films"],
            "series": [r for r in rest if r["tier"] == "series"], "bonus": [r for r in rest if r["tier"] == "bonus"],
            "shows": [r for r in rest if r["tier"] == "tv"],
            "writing": _writing(credits, lib),
            "tv_maker": media_follow.tv_maker(credits),   # F5: Follow covers their new shows too
            "head": f"{len(rows)} title{'s' if len(rows) != 1 else ''} · {len(shelf)} on server"}


# JY-292 (option C, B. 2026-11-06; first slice = source A "often cast together"): the "If you like them you may like"
# shelf. The cast of the person's top acting titles (Seerr title bodies through the 6 h meta cache, paced only when a
# read is cold), co-stars from each title's top billing who share 2+ of those titles. A deferred part: never on render.
LIKE_TITLES, LIKE_BILLED, LIKE_MIN, LIKE_MAX, LIKE_PAUSE = 10, 15, 2, 12, 0.2
LIKE_DEADLINE_S = 12   # one wall-clock budget for the part's reads: a hung Seerr cannot stall it 10 x 8 s
NOT_ACTING = {10763, 10764, 10767}   # TV news, reality, talk: guest spots there are not "cast together"
SELF_RE = re.compile(r"^(self|himself|herself|themselves)\b", re.I)


def _like_titles(credits) -> list[tuple[str, int, str]]:
    """[(kind, tmdb_id, title)]: their acting credits minus bonus videos, talk / news / reality and "Self" roles, most
    voted first (then id), at most LIKE_TITLES."""
    got: dict[tuple, tuple] = {}
    for c in ((credits.get("cast") if isinstance(credits, dict) else None) or []):
        row = md._row(c) if isinstance(c, dict) else None
        if not row or c.get("video") or NOT_ACTING & set(c.get("genreIds") or []) \
                or SELF_RE.match(str(c.get("character") or "").strip()):
            continue
        try:
            votes = int(c.get("voteCount") or 0)
        except (TypeError, ValueError):
            votes = 0
        got.setdefault((row["kind"], row["tmdb_id"]), (votes, row["title"]))
    top = sorted(got.items(), key=lambda kv: (-kv[1][0], kv[0][1]))[:LIKE_TITLES]
    return [(k[0], k[1], v[1]) for k, v in top]


def you_may_like(tmdb_id: int, pause: float = LIKE_PAUSE, deadline: float = LIKE_DEADLINE_S) -> list[dict]:
    """[{id, name, ref, href, why, titles}] - co-stars ranked by titles shared, then billing, then name. [] when
    Seerr is unset / down or nobody shares 2+ titles. Past `deadline` seconds no further title is read: the shelf is
    built from what has been read so far."""
    people: dict[int, dict] = {}
    stop = time.monotonic() + deadline
    for kind, tid, title in _like_titles(_cget(f"/api/v1/person/{tmdb_id}/combined_credits")):
        if time.monotonic() >= stop:
            log.warning("you-may-like: deadline reached, shelf from the titles read so far")
            break
        path = f"/api/v1/{kind}/{tid}"
        cold = md.meta_peek(path) is md.MISSING
        try:
            body = md.meta_get(path)
        except Exception as exc:   # one bad read never stops the shelf
            log.warning("you-may-like read failed: %s", type(exc).__name__)
            body = None
        if cold and pause:
            time.sleep(pause)
        cast = ((body.get("credits") or {}).get("cast") if isinstance(body, dict) else None) or []
        for pos, c in enumerate([c for c in cast if isinstance(c, dict)][:LIKE_BILLED]):
            pid = c.get("id")
            if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0 or pid == tmdb_id or not c.get("name"):
                continue
            p = people.setdefault(pid, {"id": pid, "name": str(c["name"])[:80], "ref": md._ref(c.get("profilePath")),
                                        "titles": [], "kinds": set(), "billing": 0})
            if title not in p["titles"]:
                p["titles"].append(title)
                p["kinds"].add(kind)
                p["billing"] += pos
    picked = sorted((p for p in people.values() if len(p["titles"]) >= LIKE_MIN),
                    key=lambda p: (-len(p["titles"]), p["billing"], p["name"].casefold()))[:LIKE_MAX]
    out = []
    for p in picked:
        n, kinds = len(p["titles"]), p["kinds"]
        noun = "films" if kinds == {"movie"} else "shows" if kinds == {"tv"} else "titles"
        out.append({"id": p["id"], "name": p["name"], "ref": p["ref"], "href": f"/media/person/{p['id']}",
                    "why": f"Cast together in {n} {noun}",
                    "titles": ", ".join(p["titles"][:3]) + (" …" if n > 3 else "")})
    return out


@router.get("/media/person/{person_id}/like", response_class=HTMLResponse)
def person_like(request: Request, person_id: str):
    """JY-292: the deferred "you may like" part; "" (the placeholder goes) when there is nothing or on any failure."""
    if not ID_RE.match(person_id):
        raise HTTPException(404, "No such person")
    try:
        like = you_may_like(int(person_id))
    except Exception as exc:  # the part never fails the page
        log.warning("you-may-like failed: %s", type(exc).__name__)
        like = []
    return md._partial(request, "_person_like.html", like=like) if like else HTMLResponse("")


FIND_NAME_MAX = 100


def _same_name(a, b) -> bool:
    return " ".join(str(a or "").split()).casefold() == " ".join(str(b or "").split()).casefold()


def find_person_id(name: str) -> int | None:
    """JY-118: a name -> its TMDB person id from ONE Seerr search (the first PERSON result whose name matches; titles
    and near-names are skipped). None when Seerr is unset, down, or has no such person. Never called on a page render."""
    body = md._get(f"/api/v1/search?query={quote(name, safe='')}")
    for r in (body.get("results") if isinstance(body, dict) else None) or []:
        if isinstance(r, dict) and r.get("mediaType") == "person" and _same_name(r.get("name"), name):
            try:
                pid = int(r.get("id"))
            except (TypeError, ValueError):
                continue
            if pid > 0:
                return pid
    return None


@router.get("/media/person/find")
def person_find(name: str = ""):
    """JY-118: where a guest or crew name goes. Declared before /media/person/{person_id} so "find" is not an id.
    One lookup per tap -> the person page, else the Discover search for the name (303, never a 500). No name: 404."""
    name = " ".join(name.split())[:FIND_NAME_MAX]
    if not name:
        raise HTTPException(404, "No such person")   # no name, nothing to look up (the guest crawl hits it bare)
    pid = find_person_id(name)
    return RedirectResponse(f"/media/person/{pid}" if pid else f"{md.DISCOVER_DETAIL}?q={quote(name, safe='')}",
                            status_code=303)


@router.get("/media/person/{person_id}", response_class=HTMLResponse)
def person_page(request: Request, person_id: str):
    if not ID_RE.match(person_id):
        raise HTTPException(404, "No such person")
    view, from_query = shell.resolve_owner_view(request)
    snaps = shell.get_snapshots(request=request)
    src = shell.find_detail_source(JELLYSEERR_SNAPSHOT_ID, snaps, detail=md.DISCOVER_DETAIL)
    if src is None:
        raise HTTPException(404, "No such person")
    person = build_person(int(person_id), snaps)
    try:  # Awards (2026-10-08): this person's wins / nominations from the media.db award tables; hidden when none
        from hub import media_awards_db, media_awards_pages
        person["awards"] = media_awards_pages.person_rows(media_awards_db.person_awards(int(person_id)))
        # JY-294: the carousel of their awarded works; a work's poster falls back to the same title in their credits
        posters = {(r["kind"], r["tmdb_id"]): r["poster"] for f in ("shelf", "films", "series", "bonus", "shows")
                   for r in person.get(f) or [] if r.get("poster")}
        person["award_works"] = media_awards_pages.person_works(person["awards"], posters)
    except Exception as exc:  # the page never fails on the awards lookup
        log.warning("awards lookup failed: %s", type(exc).__name__)
        person["awards"], person["award_works"] = None, []
    try:
        row = media_follow.get("person", int(person_id))
    except Exception as exc:  # the page never fails on the follow lookup
        log.warning("follow lookup failed: %s", type(exc).__name__)
        row = None
    person["following"] = row is not None
    person["follow_tv"] = bool(row and row.get("dept") == media_follow.CREATOR)
    resp = shell.render_page(request, "media_person.html", {
        "status": shell.build_status(snaps), "src": src, "person": person, "show_first": SHOW_FIRST,
        "follow_flash": media_follow.flash_text(request)})
    return shell._maybe_set_cookie(resp, view, from_query)
