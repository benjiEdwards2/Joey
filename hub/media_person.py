"""Person pages (F11, 2026-10-06): click a cast or crew name on a film page and see everything that person
is in. Jellyseerr `person/{id}` + `person/{id}/combined_credits` (server-side, cached 10 min via the film
page's cache), split into "On your server" (matched against the Jellyfin snapshot library lists) and
"Everything else" (Films / TV). Upstream failure degrades to words, never a 500; no URL or key in the page.
"""

from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from hub import media_discover as md, media_item
from hub.media_film import _cget

router = APIRouter()

CREDITS_MAX, BIO_MAX, BIO_LEAD = 200, 1200, 400
ID_RE = re.compile(r"^[1-9][0-9]{0,9}$")
DOWN_TEXT = "Couldn't reach Jellyseerr — nothing to show for this person yet"


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


def _credits(body, lib: dict[str, str]) -> list[dict]:
    """combined_credits -> one row per title (cast + crew roles joined), newest first, capped."""
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
            m = merged.setdefault((row["kind"], row["tmdb_id"]), {
                **row, "date": str(c.get("releaseDate") or c.get("firstAirDate") or "")[:10], "roles": []})
            if role and role not in m["roles"]:
                m["roles"].append(role)
    rows = sorted(merged.values(), key=lambda r: r["date"], reverse=True)[:CREDITS_MAX]
    for r in rows:
        r["role"] = " · ".join(r.pop("roles"))
        jf_id = lib.get(f"tmdb:{r['tmdb_id']}")
        r["jf_id"] = jf_id
        r["on_server"] = bool(jf_id) or r["status_word"] in md.ON_DISK
        r["word"] = ("On server" if r["on_server"] else r["status_word"] if r["status_word"] in ("Requested", "Processing")
                     else "Not on server")
        r["item_href"] = f"/media/item/{jf_id}" if jf_id else None
    return rows


def build_person(tmdb_id: int, hub) -> dict:
    snaps = hub.get_snapshots()
    jsrc = hub.find_detail_source(hub.JELLYFIN_SNAPSHOT_ID, snaps)
    lib = _library((jsrc or {}).get("data") or {})
    person = _cget(f"/api/v1/person/{tmdb_id}")
    credits = _cget(f"/api/v1/person/{tmdb_id}/combined_credits")
    if not isinstance(person, dict) and not isinstance(credits, dict):
        return {"down": True, "note": DOWN_TEXT, "name": "Person", "tmdb": tmdb_id}
    person = person if isinstance(person, dict) else {}
    rows = _credits(credits, lib)
    shelf = [r for r in rows if r["jf_id"]]
    rest = [r for r in rows if not r["jf_id"]]
    return {"down": False, "tmdb": tmdb_id, "name": str(person.get("name") or "Unknown")[:120],
            "ref": md._ref(person.get("profilePath")), "dept": str(person.get("knownForDepartment") or "")[:40],
            "life": _life(person), "bio": _bio(person.get("biography")),
            "shelf": shelf, "films": [r for r in rest if r["kind"] == "movie"], "shows": [r for r in rest if r["kind"] == "tv"],
            "head": f"{len(rows)} title{'s' if len(rows) != 1 else ''} · {len(shelf)} on your server"}


@router.get("/media/person/{person_id}", response_class=HTMLResponse)
def person_page(request: Request, person_id: str):
    from hub import main as hub  # late: hub.main includes this router

    if not ID_RE.match(person_id):
        raise HTTPException(404, "No such person")
    view, from_query = hub.resolve_owner_view(request)
    snaps = hub.get_snapshots()
    src = hub.find_detail_source(hub.JELLYSEERR_SNAPSHOT_ID, snaps, detail=md.DISCOVER_DETAIL)
    if src is None:
        raise HTTPException(404, "No such person")
    person = build_person(int(person_id), hub)
    resp = hub.templates.TemplateResponse(request, "media_person.html", {
        "areas": hub.registry.visible_areas, "active_id": None, "owner_view": view,
        "status": hub.build_status(snaps), "src": src, "person": person})
    return hub._maybe_set_cookie(resp, view, from_query)
