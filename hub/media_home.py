"""Media helpers the hub page, the Media home and the Media detail pages share (W3 split of hub/main.py, H-44): the
one ratings read per page (_ratings / score_for), the owner view of the Jellyfin data (view_jelly), the Media home's hero + poster shelves (build_shelves), the rating inbox (_to_rate) and
waiting counts, the Media frame (media_frame, Jinja `media_nav`), and the hub's Media card builders (media_hero,
hub_shelf). Sets its Jinja globals (score_for, status_of, media_nav, item_href, row_href, resume_flash,
resume_acts) on the shared shell env at import.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import Request

from hub import (media_db, media_discover, media_downloads, media_follow, media_item, media_nav, media_plays_db,
                 media_resume, media_status_words, media_text, media_watchlist, shell)
from hub.ids import ARR_SNAPSHOT_ID, JELLYFIN_SNAPSHOT_ID, QBIT_SNAPSHOT_ID
from hub.store import ago_text, data_of, parse_utc, tile_state

log = logging.getLogger("hub.media_home")


# Media detail paths (2026-10-05). Keyed by
# connector id (hub/ids.py) like the upcoming list — never an area name (WP17 grep exception).
HISTORY_DETAIL = "/media/history"  # the tile reading the jellyfin snapshot as watch history
HISTORY_PLAYS = "/media/server/history"  # F7 play history (Play stats, linked from Activity > History; nav-tidy 2026-10-13)
DIARY_DETAIL = "/media/diary"      # the tile reading it as the watch diary
TO_RATE_DAYS = 30      # rating inbox window on /media/history


def _parse_ts(value) -> datetime:
    """ISO timestamp -> aware datetime (store.parse_utc); raises ValueError when it is not one."""
    dt = parse_utc(value)
    if dt is None:
        raise ValueError("not a timestamp")
    return dt


LEVEL_KEYS = ("item_key", "show_key", "season_key", "episode_key")


class Ratings(dict):
    """{key: score} plus the owner's rating level, so templates can call score_for(row, ratings)."""
    level = "show"


def _ratings(view: str, *row_lists) -> Ratings:
    """ONE get_ratings() per page render, for the view's owner (her view = her own ratings).
    Fetches every key kind a row carries (show / season / episode) so score_for can pick."""
    owner = media_db.owner_of(view)
    out = Ratings(media_db.get_ratings((r.get(k) for rows in row_lists for r in rows or [] for k in LEVEL_KEYS),
                                       owner))
    out.level = media_db.rating_level(owner)
    return out


def score_for(row, ratings, level=None):
    """A row's score: the current level's key when it has one that is rated, else the show's
    (item_key). Movies and rows without level keys read item_key as ever."""
    level = level or getattr(ratings, "level", "show")
    key = row.get(level + "_key") if level in media_db.LEVELS else None
    if key and key in ratings:
        return ratings[key]
    return ratings.get(row.get("item_key")) if row.get("item_key") else None


shell.templates.env.globals["score_for"] = score_for
shell.templates.env.globals["status_of"] = media_status_words.status   # M-19: a status word's colour class


def view_jelly(jelly: dict, view: str) -> dict:
    """The Jellyfin data as the owner view sees it. In the her view up_next/history are
    Georgina's own (empty when her block is null — never B.'s), `her_missing` says so;
    sessions, latest and library stay server-wide. Other views are returned untouched."""
    if view != "her" or not jelly:
        return jelly
    her = jelly.get("her")
    return {**jelly, "up_next": (her or {}).get("up_next") or [],
            "history": (her or {}).get("history") or {}, "her_missing": her is None}


def _ago_text(value, now: datetime) -> str:
    """store.ago_text ('3d ago') for an ISO timestamp (Jellyfin's 7-digit fractions tolerated); "" when it is not one."""
    at = parse_utc(value)
    return ago_text((now - at).total_seconds() / 60.0) if at else ""


def _library_text(library: dict) -> str:
    parts = [media_text.plural(library[k], s, p)
             for k, s, p in (("movies", "movie", "movies"), ("episodes", "episode", "episodes"))
             if isinstance(library.get(k), int)]
    return " · ".join(parts)


SHELF_MAX = 15         # items per poster shelf
LIBRARY_DETAIL = "/media/library"
PLAYING_DETAIL = "/media/playing"


def item_href(jf_id=None, key=None) -> str | None:
    """Joey item page (F9) for a Jellyfin id, or for a `jf:<id>` rating key; None otherwise."""
    if not jf_id and str(key or "").startswith("jf:"):
        jf_id = key[3:]
    return f"/media/item/{jf_id}" if jf_id and media_item.ITEM_RE.match(str(jf_id)) else None


def row_href(jf_id=None, key=None, kind=None) -> str | None:
    """Whole-row link (B., 2026-10-06): Joey item page, else the tmdb title page, else None."""
    url = item_href(jf_id, key)
    k = str(key or "")
    if not url and kind in ("movie", "tv") and k.startswith("tmdb:") and k[5:].isdigit():
        url = f"/media/title/{kind}/{k[5:]}"
    return url


def waiting_counts(recent, ratings, details, to_rate_rows=None) -> dict:
    """What waits on the owner: titles to rate (full, uncapped inbox).
    `details` = the detail paths of the tiles visible in this owner view; a count whose
    tile is hidden is 0. Shared by the area page and the hub card. `to_rate_rows`: the inbox when the caller
    already built it (media_frame)."""
    rows = _to_rate(recent, ratings) if to_rate_rows is None and HISTORY_DETAIL in details else to_rate_rows
    to_rate = len(rows) if HISTORY_DETAIL in details else 0
    return {"to_rate": to_rate}


def _recent(snaps, view: str) -> list:
    """The viewer's recent watch history (her view = hers) from the jellyfin snapshot."""
    jelly = snaps.get(JELLYFIN_SNAPSHOT_ID)
    return (view_jelly(jelly.data if jelly else {}, view).get("history") or {}).get("recent") or []


def area_waiting(area, snaps, view: str, recent=None, ratings=None, to_rate_rows=None) -> dict:
    """waiting_counts for an area straight from snapshots + owner view (hub card, Media frame). `recent` /
    `ratings` / `to_rate_rows` when the caller already has them (media_frame builds them once for both counts)."""
    recent = _recent(snaps, view) if recent is None else recent
    counts = waiting_counts(recent, _ratings(view, recent) if ratings is None else ratings,
                            {t.detail for t in area.tiles if t.detail and shell.owner_visible(t, view)}, to_rate_rows)
    return counts


def to_rate_tab_counts(snaps, view: str, recent=None, ratings=None, to_rate_rows=None) -> dict:
    """The Movies / TV Shows "To rate" tab counts (media-ux4): the viewer's own inbox split by kind."""
    recent = _recent(snaps, view) if recent is None else recent
    rows = to_rate_rows if to_rate_rows is not None else (
        _to_rate(recent, _ratings(view, recent) if ratings is None else ratings) if recent else [])
    return {"to_rate_movie": sum(1 for r in rows if r["kind"] == "movie"),
            "to_rate_tv": sum(1 for r in rows if r["kind"] == "tv")}


def media_frame(request: Request) -> dict:
    """Template global `media_nav(request)`: the Media bar/tabs context (cached per request)."""
    cached = getattr(request.state, "media_nav", None)
    if cached is None:
        view, _ = shell.resolve_owner_view(request)
        area = media_nav.shelves_area(shell.registry)
        snaps = getattr(request.state, "snaps", None)  # media-speed: a route's own read, when it shared one
        snaps = shell.get_snapshots(request=request) if snaps is None else snaps
        recent = _recent(snaps, view)
        ratings = _ratings(view, recent) if area or recent else None  # H-29: ONE ratings read for both counts
        inbox = _to_rate(recent, ratings) if recent and ratings is not None else []   # M-24: ONE inbox for both
        waiting = area_waiting(area, snaps, view, recent, ratings, inbox) if area else {}
        try:
            jelly = snaps.get(JELLYFIN_SNAPSHOT_ID)
            waiting = {**waiting, **media_watchlist.tab_counts(media_db.owner_of(view), jelly.data if jelly else None)}
        except Exception as exc:  # the Watchlist count is a nicety: never break the frame
            log.warning("watchlist count skipped: %s", type(exc).__name__)
        try:
            waiting = {**waiting, **to_rate_tab_counts(snaps, view, recent, ratings, inbox)}
        except Exception as exc:  # the To rate tab count is a nicety too (media-ux4)
            log.warning("to rate count skipped: %s", type(exc).__name__)
        cached = request.state.media_nav = media_nav.nav_context(request, shell.registry, waiting)
    return cached


shell.templates.env.globals["media_nav"] = media_frame
shell.templates.env.globals["item_href"] = item_href
shell.templates.env.globals["row_href"] = row_href
shell.templates.env.globals["resume_flash"] = lambda request: media_resume.flash_text(request.query_params) if request else (None, None)


def resume_acts(row: dict, owner: str) -> dict | None:
    """Move on (2026-10-08): what a Continue watching card offers — Mark watched always, Reset progress only on a
    resume row (not a next-up suggestion). None without a Jellyfin id."""
    jf = str((row or {}).get("jf_id") or "")
    if not media_item.ITEM_RE.match(jf):
        return None
    resume = media_resume.in_progress(row)
    series = None if resume else media_resume.series_of(row)   # media-ux2: a Next Up suggestion can be hidden
    return {"jf_id": jf, "owner": owner, "reset": resume, "hide": bool(series), "series": series}


shell.templates.env.globals["resume_acts"] = resume_acts


def media_hero(jelly: dict, link: str | None, allow_newest: bool = True) -> dict | None:
    """The one item the Media hero shows: playing now, else first resume item, else the
    newest arrival. Pure; shared by the area page (build_shelves) and the hub card."""
    server_id = jelly.get("server_id")

    def hero(row, kind_word, sub, **extra):
        return {"kind_word": kind_word, "title": row.get("title"), "poster": row.get("poster"),
                "backdrop": row.get("backdrop"), "sub": sub,
                "href": shell._deep_link(link, row.get("jf_id"), server_id),
                "progress_pct": None, "user": None, "play_method": None, **extra}

    playing = jelly.get("now_playing") or []
    if playing:
        p = playing[0]
        return hero(p, "Playing now", f"{p.get('user')} · {p.get('play_method')} · {p.get('progress_pct')}%",
                    user=p.get("user"), play_method=p.get("play_method"), progress_pct=p.get("progress_pct"))
    up_next = jelly.get("up_next") or []
    if up_next:
        return hero(up_next[0], "Jump back in", up_next[0].get("remaining_text"))
    latest = sorted(jelly.get("latest") or [], key=lambda r: str(r.get("added_at") or ""), reverse=True)
    if allow_newest and latest:
        return hero(latest[0], "Newest arrival", f"Added {_ago_text(latest[0].get('added_at'), datetime.now(timezone.utc))}")
    return None


def build_shelves(area, tiles, snaps, view: str) -> dict:
    """Hero + poster shelves for a `layout: shelves` area. Pure over its inputs (plus the
    ratings DB). A shelf renders only when the registry tile it stands for is visible in
    the owner view; snapshots/DB missing just leave quiet words (torate: omitted)."""
    by_detail = {r["tile"].detail: r for r in tiles if r["tile"].detail}
    link = next((r["st"]["href"] for r in tiles if r["st"]["state"] == "link"), None)

    def data_of(snapshot_id):
        snap = snaps.get(snapshot_id)
        return snap.data if snap else {}

    jelly = view_jelly(data_of(JELLYFIN_SNAPSHOT_ID), view)
    her_unset = bool(jelly.get("her_missing"))  # her view, no Georgina user wired yet
    jelly_row = next((r for r in tiles if r["tile"].snapshot == JELLYFIN_SNAPSHOT_ID), None)
    now = datetime.now(timezone.utc)

    up_next = (jelly.get("up_next") or [])
    hero = media_hero(jelly, link, allow_newest=False)
    if hero and hero["href"] is None:
        hero["href"] = link  # no deep link for the row: fall back to the Jellyfin launcher
    if hero and hero["kind_word"] == "Jump back in":
        hero["kind_word"] = "Up next"  # the area page keeps its original word
    kind_word = hero["kind_word"] if hero else "Nothing playing"

    def item(r, sub, href, **extra):
        return {"title": r.get("title"), "sub": sub, "poster": r.get("poster"),
                "href": href, **{k: r.get(k) for k in LEVEL_KEYS}, **extra}

    def jf_item(r, sub, fallback, **extra):
        """Row that opens its Joey item page (F9) when it carries a jf_id, else a Joey page."""
        return item(r, sub, item_href(r.get("jf_id")) or fallback, **extra)

    shelves: list[dict] = []

    def add(sid, title, detail, items, quiet, omit_empty=False):
        if detail not in by_detail or (omit_empty and not items):
            return
        shelves.append({"id": sid, "title": title, "see_all_href": detail,
                        "items": items, "quiet_text": quiet})

    recent = ((jelly.get("history") or {}).get("recent") or [])
    arrived = list(data_of(ARR_SNAPSHOT_ID).get("arrived") or [])
    latest = sorted(jelly.get("latest") or [], key=lambda r: str(r.get("added_at") or ""), reverse=True)
    added, seen = [], set()
    for r, sub, from_jf in ([(r, _ago_text(r.get("added_at"), now), True) for r in latest]
                            + [(r, r.get("when", ""), False) for r in arrived]):
        key = r.get("item_key") or r.get("title")
        if key in seen:
            continue
        seen.add(key)
        added.append(jf_item(r, sub, LIBRARY_DETAIL) if from_jf else item(r, sub, LIBRARY_DETAIL))
    added = added[:SHELF_MAX]
    arr = data_of(ARR_SNAPSHOT_ID)
    # media-ux2 (2026-10-08, B.): "This week" and "Recently watched" left Media home (Activity → Library keeps This week,
    # Diary > To rate keeps Recently watched; the hub page's own Recently watched band is separate).
    downloading = [item(r, r["caption"], LIBRARY_DETAIL) for r in
                   media_downloads.merge_downloading(arr.get("downloading"), data_of(QBIT_SNAPSHOT_ID))][:SHELF_MAX]

    ratings = _ratings(view, up_next, added, recent, downloading)  # ONE query for every shelf

    unset_text = "Her Jellyfin account isn't set up yet"
    add("continue", "Continue watching", PLAYING_DETAIL,
        [jf_item(n, n.get("remaining_text"), PLAYING_DETAIL, acts=resume_acts(n, media_db.owner_of(view)))
         for n in up_next[:SHELF_MAX]],
        unset_text if her_unset else "Nothing up next")
    add("added", "Recently added", LIBRARY_DETAIL, added, "Nothing added recently")
    add("downloading", "Downloading", LIBRARY_DETAIL, downloading, "", omit_empty=True)
    most_shows, most_films = media_plays_db.most_played_30(media_db.owner_filter(view))
    most = ([item({"title": e["title"], "poster": e["poster"], "item_key": e["key"]},
                  f"{e['episodes']} episode{'' if e['episodes'] == 1 else 's'} · {e['hours']} h", item_href(e.get("jf_id"), e["key"]) or HISTORY_PLAYS)
             for e in most_shows]
            + [item({"title": e["title"], "poster": e["poster"], "item_key": e["key"]},
                    f"{e['plays']} play{'' if e['plays'] == 1 else 's'} · {e['hours']} h", item_href(e.get("jf_id"), e["key"]) or HISTORY_PLAYS)
               for e in most_films])
    try:  # Follow (2026-10-07): only once something is followed; behind the Discover tile like /media/following
        followed = media_follow.home_items() if media_discover.DISCOVER_DETAIL in by_detail else None
    except Exception as exc:  # the home page never fails on the follow shelf
        log.warning("follow shelf skipped: %s", type(exc).__name__)
        followed = None
    if followed is not None:
        shelves.append({"id": "following", "title": "New from people you follow", "see_all_href": media_follow.FOLLOWING,
                        "items": [item(r, r["sub"], r["href"]) for r in followed], "quiet_text": "Nothing new yet"})
    if most:  # F7: not behind a registry tile, so it skips add()'s detail gate
        shelves.append({"id": "mostplayed", "title": "Most played · 30 days", "see_all_href": HISTORY_PLAYS,
                        "items": most, "quiet_text": ""})
    for sh in shelves:
        for it in sh["items"]:
            it["score"] = score_for(it, ratings)
            for k in LEVEL_KEYS:
                it.pop(k, None)

    return {
        "hero": hero, "kind_word": kind_word, "shelves": shelves,
        "waiting": waiting_counts(recent, ratings, set(by_detail)),
        "open_href": link,
        "freshness": jelly_row["st"] if jelly_row else None,
    }


def _to_rate_title(r: dict, kind: str, level: str) -> str:
    """Inbox title for a TV row at its rating level; a row missing the numbers falls back."""
    if level == "season" and r.get("show_title") and r.get("season") is not None:
        return f"{r['show_title']} · Season {r['season']}"
    if level == "episode":
        return r["title"]
    return media_db.base_title(r["title"], kind)


def _to_rate(recent, ratings) -> list[dict]:
    """The rating inbox: unrated titles watched in the last TO_RATE_DAYS, one per rating key.
    TV rows follow the owner's level (ratings.level): one entry per show / season / episode
    (a row without that level's key falls back to its show); movies are always one title."""
    level = getattr(ratings, "level", "show")
    cutoff = datetime.now(timezone.utc) - timedelta(days=TO_RATE_DAYS)
    seen, rows = set(), []
    for r in recent:
        kind = media_db.norm_kind(r.get("kind"))
        row_level = level if kind == "tv" and r.get(level + "_key") else "show"
        key = r.get(row_level + "_key") if row_level != "show" else r.get("item_key")
        try:
            fresh = _parse_ts(r["watched_at"]) >= cutoff
        except Exception:
            continue
        if not key or key in ratings or key in seen or not fresh:
            continue
        seen.add(key)
        rows.append({"item_key": key, "kind": kind, "year": None, "level": row_level,
                     "title": _to_rate_title(r, kind, row_level),
                     "poster": r.get("poster"), "when": r.get("when", ""), "jf_id": r.get("jf_id")})
    return rows


def _profile_rows(jelly: dict, view: str, pick) -> list[tuple[dict, str]]:
    """(row, owner) pairs from B.'s and Georgina's Jellyfin profiles as the owner view sees
    them: you = B.'s, her = hers, both = B.'s then hers. `pick(profile_dict)` -> rows."""
    mine = [(r, "you") for r in pick(jelly)]
    hers = [(r, "her") for r in pick(jelly.get("her") or {})]
    return {"you": mine, "her": hers}.get(view, mine + hers)


def _split_title(row) -> tuple[str, str]:
    """'Show · S02E05 · Name' -> ('Show', 'S02E05 · Name'); a film keeps its title + 'Film'."""
    head, _, rest = str(row.get("title") or "").partition(" · ")
    return head, rest or ("Film" if row.get("kind") == "movie" else "")


def hub_shelf(area, snaps, view: str) -> dict | None:
    """Hub "Recently watched" band for a `layout: shelves` area (its Continue watching band left the hub in media-ux2,
    2026-10-08; Media home keeps it). Present when that area's jellyfin tile is visible; rows only from the snapshot."""
    tiles = [t for t in area.tiles if shell.owner_visible(t, view)]
    jtile = next((t for t in tiles if t.snapshot == JELLYFIN_SNAPSHOT_ID), None)
    if jtile is None:
        return None
    st = tile_state(jtile, snaps)
    snap = snaps.get(JELLYFIN_SNAPSHOT_ID)
    jelly = data_of(snap)

    def item(row, owner, when, fallback):
        title, sub = _split_title(row)
        url = item_href(row.get("jf_id"))
        return {"title": title, "sub": " · ".join(x for x in (owner.title(), sub) if x),  # owner first: never ellipsised
                "when": when, "poster": row.get("poster"), "href": url or fallback,
                "pct": row.get("progress_pct")}  # _shelf.html's shape

    watched = None
    if any(t.detail == DIARY_DETAIL for t in tiles):
        rows = _profile_rows(jelly, view, lambda p: (p.get("history") or {}).get("recent") or [])
        if view == "both":
            def when(pair):
                try:
                    return _parse_ts(pair[0].get("watched_at")).timestamp()
                except Exception:
                    return 0.0
            rows = sorted(rows, key=when, reverse=True)
        watched = [item(r, o, r.get("when"), DIARY_DETAIL) for r, o in rows][:SHELF_MAX]
    return {"href": f"/a/{area.id}", "st": st, "watched": watched}
