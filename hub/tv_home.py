"""The friends' TV Home (JY-259 phase 1, 2026-10-28; B.'s pick "JY-259: A · 1A · 2A · 3A · 4A · 5A · 6A · 7A · 8A").
Spec: docs/specs/JY-259-tv-revamp.md.

TV mode only: hub.media_guest_home.build adds `sh.tv` when the request is in TV mode, and area_shelves.html draws it
with the tile kit (_tv_tile.html). The web and phone Home keep `sh.shelves` exactly as before.

* Rows, in this order, each left out when empty: Continue watching (16:9), Next episodes (16:9), Recently added,
  Because you rated (JY-105, never first focus), New on Joey this month, Top rated on Joey, Films under 100 minutes,
  Recently watched.
* A static hero over a backdrop: the first Continue watching item, else the newest addition. The backdrop is the
  Jellyfin backdrop from the snapshot row (index 0, JY-262; skipped when this viewer's cached item read says Jellyfin
  holds none), else the TMDB backdrop from the Jellyseerr title cache, else the poster (drawn blurred and dimmed).
  Every image is an /img ref (the existing proxy and its disk cache).
* Never a call (rule 7): everything comes from what build() has already read (the viewer's two cached Jellyfin
  shelves, the scrubbed snapshot) and the hub's caches (media_item.peek for the viewer's own show reads, the
  Jellyseerr title cache). Next episodes uses only shows this viewer has opened (their item read is cached).

Phase 2 (2026-10-28): the hero follows the focused tile. Every row tile carries `hero` (tile_hero(): the backdrop URL,
title, facts and a one-line synopsis), worked out here from the same caches, so tv.js swaps the hero from the page
alone; its only network use is the /img fetch of the next backdrop. Each row names its hero eyebrow (ROW_EYEBROW).
"""
from __future__ import annotations

from urllib.parse import quote

from hub import images, media_backdrop, media_home, media_item, media_text

ROW_ORDER = ("continue", "next", "added", "because", "month", "top", "short", "watched")
LAND_ROWS = frozenset({"continue", "next"})   # 16:9 stills; every other row is 2:3 posters
NEXT_TITLE = "Next episodes"
HERO_H = media_backdrop.TV_H   # 1280 wide: the backdrop size media_warmup already warms (BACKDROP_H)
STILL_H = 400            # an episode still: the size the TV episode shelf asks for (media_film.html)
BLUR_H = 240             # the blurred poster fallback: the list-row poster size (warmed)
SYNOPSIS_MAX = 240       # one line on the TV (tv.css clamps it); the rest is never sent
# phase 2: the hero eyebrow while it shows a tile of that row (any other row: its own label)
ROW_EYEBROW = {"continue": "Pick up where you left off", "next": "Up next", "added": "Just added"}


def _id(ref) -> str | None:
    """The Jellyfin id in a `jf:` / `jfb:` ref (or a `jf:` rating key)."""
    text = str(ref or "")
    for prefix in ("jf:", "jfb:"):
        if text.startswith(prefix) and media_item.ITEM_RE.match(text[len(prefix):]):
            return text[len(prefix):]
    return None


def _index(jelly: dict) -> dict:
    """Phase 2: the snapshot's movies / shows rows by Jellyfin id and by item key, built once per Home render."""
    out: dict = {}
    for kind, rows in (("tv", jelly.get("shows")), ("movie", jelly.get("movies"))):   # a film wins a shared key
        for r in rows or []:
            if isinstance(r, dict):
                for k in (r.get("jf_id"), r.get("item_key")):
                    if k:
                        out[k] = (r, kind)
    return out


def _library_row(item: dict, jelly: dict, index: dict | None = None) -> tuple[dict, str] | None:
    """The snapshot's movies / shows row for a tile (by the Jellyfin id its poster names, else its item key)."""
    want_id, want_key = _id(item.get("poster")), item.get("item_key")
    if index is not None:
        return (want_id and index.get(want_id)) or (want_key and index.get(want_key)) or None
    for kind, rows in (("movie", jelly.get("movies")), ("tv", jelly.get("shows"))):
        for r in rows or []:
            if isinstance(r, dict) and ((want_id and r.get("jf_id") == want_id)
                                        or (want_key and r.get("item_key") == want_key)):
                return r, kind
    return None


def _tmdb_backdrop(item_key, kind: str) -> str | None:
    """The TMDB backdrop of a title from the Jellyseerr title cache only (the film page's read); None when not cached."""
    from hub import media_discover as md, media_film   # late: media_film is a large module
    text = str(item_key or "")
    if not text.startswith("tmdb:") or not text[5:].isdigit():
        return None
    body = media_film._cpeek(f"/api/v1/{kind}/{text[5:]}")
    return md._ref(body.get("backdropPath")) if isinstance(body, dict) else None


def backdrop(item: dict | None, jelly: dict, index: dict | None = None) -> dict | None:
    """The one backdrop chain (B.'s point 2): Jellyfin backdrop, else TMDB backdrop (cached), else the blurred poster.
    -> {"ref", "h", "blur"} or None."""
    if not item:
        return None
    found = _library_row(item, jelly or {}, index)
    row, kind = found if found else ({}, "movie")
    jf_id = _id(row.get("backdrop"))
    read = media_item.peek(jf_id) if jf_id else None   # JY-262: this viewer's own cached read, if any (no call)
    if row.get("backdrop") and ((read or {}).get("item") or {}).get("backdrops") != 0:
        return {"ref": row["backdrop"], "h": HERO_H, "blur": False}   # the snapshot's ref is backdrop 0 (HOME)
    tmdb = _tmdb_backdrop(row.get("item_key") or item.get("item_key"), kind)
    if tmdb:
        return {"ref": tmdb, "h": HERO_H, "blur": False}
    if item.get("poster"):
        return {"ref": item["poster"], "h": BLUR_H, "blur": True}
    return None


def still(row: dict) -> tuple[str | None, int]:
    """A Continue watching tile's 16:9 picture: the episode's own still, or the film's backdrop."""
    ep = _id(row.get("episode_key"))
    if ep:
        return f"jf:{ep}", STILL_H
    jf_id = _id(row.get("poster"))
    return (f"jfb:{jf_id}", HERO_H) if jf_id else (None, STILL_H)


def _next_after(show: dict | None, episode_id: str) -> tuple | None:
    """(season number, episode) of the first aired, unwatched, not-started episode after `episode_id` in a cached show
    read (the viewer's own: media_item keys a friend's reads by viewer). None when the show is not cached, the episode
    is not in it, or the next one has not aired."""
    eps = [(s.get("number"), e) for s in (show or {}).get("seasons") or [] for e in s.get("episodes") or []
           if isinstance(e, dict)]
    at = next((i for i, (_, e) in enumerate(eps) if e.get("jf_id") == episode_id), None)
    if at is None:
        return None
    for season, e in eps[at + 1:]:
        if not e.get("aired"):
            return None
        if not e.get("played") and not e.get("in_progress"):
            return season, e
    return None


def next_episodes(watched, resume) -> list[dict]:
    """Next episodes: per show in the viewer's Recently watched (newest first), the episode after the one watched,
    from the cache only. Shows already in Continue watching are left out."""
    busy = {r.get("show_key") for r in resume or [] if r.get("show_key")}
    out, seen = [], set()
    for r in watched or []:
        show_key, show_id, ep_id = r.get("show_key"), _id(r.get("show_key")), _id(r.get("episode_key"))
        if not (show_id and ep_id) or show_key in seen or show_key in busy:
            continue
        seen.add(show_key)
        nxt = _next_after(media_item.peek(show_id), ep_id)
        if nxt is None:
            continue
        season, e = nxt
        code = f"S{season} E{e.get('number')}" if season is not None else f"E{e.get('number')}"
        out.append({"title": r.get("title") or "Episode", "sub": f"{code} · {e.get('name') or 'Episode'}",
                    "still": e.get("still"), "still_h": STILL_H, "poster": r.get("poster"), "pct": None,
                    "href": media_home.item_href(e.get("jf_id")), "show_key": show_key})
    return out[:media_home.SHELF_MAX]


def img_url(ref, title, h: int) -> str:
    """The /img URL exactly as _tv_tile.html's art() writes it (unescaped), so the backdrop tv.js swaps to is the same
    browser-cache entry as the one the page drew (a test pins the two equal)."""
    return f"/img/{ref or 'none'}?h={h}&t={quote(images.fallback_letters(title), safe='/')}"


def _synopsis(row: dict, kind: str, item: dict) -> str:
    """One line of synopsis from the caches only: this viewer's cached item read, else the Jellyseerr title cache."""
    from hub import media_film   # late: media_film is a large module
    jf_id = row.get("jf_id") or _id(item.get("poster"))
    text = ((media_item.peek(jf_id) or {}).get("item") or {}).get("overview") if jf_id else None
    key = str(row.get("item_key") or item.get("item_key") or "")
    if not text and key.startswith("tmdb:") and key[5:].isdigit():
        body = media_film._cpeek(f"/api/v1/{kind}/{key[5:]}")
        text = body.get("overview") if isinstance(body, dict) else None
    text = " ".join(str(text or "").split())
    return text if len(text) <= SYNOPSIS_MAX else text[:SYNOPSIS_MAX - 1].rsplit(" ", 1)[0] + "\u2026"


def _facts(row: dict, kind: str, item: dict, land: bool) -> str:
    """The hero facts line: a 16:9 tile's own line first (where you are: "S1 E2 · 20m left"), then year · Film / Show
    · runtime from the snapshot row."""
    year = row.get("year")
    parts = [item.get("sub") if land else None, str(year) if isinstance(year, int) else None,
             ("Show" if kind == "tv" else "Film") if row else None,
             media_text.duration(row["runtime_min"]) if kind == "movie" and row.get("runtime_min") else None]
    return " · ".join(p for p in parts if p)


def tile_hero(item: dict, jelly: dict, index: dict, land: bool = False) -> dict:
    """Phase 2: what the hero shows while this tile has focus: {"bd": URL or None, "blur", "title", "facts", "syn"}."""
    row, kind = _library_row(item, jelly, index) or ({}, "movie")
    bd = backdrop(item, jelly, index)
    title = item.get("title") or ""
    return {"bd": img_url(bd["ref"], title, bd["h"]) if bd else None, "blur": bool(bd and bd["blur"]),
            "title": title, "facts": _facts(row, kind, item, land), "syn": _synopsis(row, kind, item)}


def build(shelves: list[dict], resume, watched, added, jelly: dict) -> dict:
    """`sh.tv`: {"hero", "rows"} from the guest Home's shelves (already filtered and decorated by build()).
    Call before media_guest_home.build pops the rating keys (the backdrop chain reads item_key)."""
    by_id = {s.get("id"): s for s in shelves}
    for it in (by_id.get("continue") or {}).get("items") or []:
        it["still"], it["still_h"] = still(it)
    nxt = next_episodes(watched, resume)
    if nxt:
        by_id["next"] = {"id": "next", "title": NEXT_TITLE, "see_all_href": None, "items": nxt, "quiet_text": None}
    rows = [{**by_id[k], "land": k in LAND_ROWS} for k in ROW_ORDER if by_id.get(k, {}).get("items")]
    rows += [{**s, "land": False} for s in shelves if s.get("id") not in ROW_ORDER and s.get("items")]
    jelly = jelly or {}
    index = _index(jelly)
    for r in rows:   # phase 2: each tile carries what the hero shows while it has focus (page data only)
        r["eyebrow"] = ROW_EYEBROW.get(r.get("id"), r.get("title"))
        r["items"] = [{**it, "hero": tile_hero(it, jelly, index, r["land"])} for it in r["items"]]
    cont = (by_id.get("continue") or {}).get("items") or []
    first, eyebrow = (cont or [None])[0], "Pick up where you left off"   # JY-259 review: never the row's own label
    if first is None:
        first, eyebrow = (added or [None])[0], "Just added"
    hero = None
    if first:
        th = tile_hero(first, jelly, index, land=bool(cont))
        hero = {"eyebrow": eyebrow, "title": first.get("title"), "sub": th["facts"], "syn": th["syn"],
                "backdrop": backdrop(first, jelly, index)}
    return {"hero": hero, "rows": rows}
