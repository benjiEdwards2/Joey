"""Free space (P1a, 2026-10-22): `GET /server/space`, the biggest watched films and finished shows still on disk.

B., 2026-10-22: LIST ONLY — nothing here deletes, and the page has no button that changes anything; each row links to
its Joey item page, where B. decides. Pure snapshot reads (no arr or Jellyfin call at render): sizes from the arr
snapshot's `library_sizes` (connectors/feeds/arr.py), watch state from the jellyfin snapshot's library rows.

* A watched film: a Jellyfin `movies` row with `played`, joined to a Radarr row by TMDB id.
* A finished show: a Jellyfin `shows` row with episodes and `unplayed == 0`, joined to a Sonarr row by TheTVDB id or
  TMDB id (Jellyfin's show key prefers TMDB, Sonarr's own key is TheTVDB), and Sonarr says the series has `ended`.
* Joined by provider ids from the rows' `item_key` (`tmdb:<id>` / `tvdb:<id>`), never by title.
* The TOP biggest of each, then one list by size. The head line adds "(≈ N days at this rate)" only when the Server
  page's disk forecast exists: the freed share of the forecast volume over its least-squares rate (`server.disk_days`).
  JY-031 (2026-10-23, fix round): the forecast is the hub loop's cached item (hub/server_history.py `forecast`), the
  one in the Server page's Attention, so the two never disagree (was `server.history_band(...)["forecast"]`).

Owner-only: PRIVATE in hub/guest.py (the media front 404s it). Watch state is the owner's ("you") Jellyfin rows.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from hub import server, server_alerts, server_history, shell
from hub.ids import ARR_SNAPSHOT_ID, JELLYFIN_SNAPSHOT_ID, SYSTEM_SNAPSHOT_ID, home_tz
from hub.media_home import row_href
from hub.media_text import plural, short_date
from hub.store import connected, data_of, parse_utc

router = APIRouter()

TOP = 10
GIB = 1024 ** 3
EMPTY = "Nothing watched is taking space yet"
NOT_CONNECTED = "Not connected"


def _id(v) -> int | None:
    s = str(v if v is not None and not isinstance(v, bool) else "")
    return int(s) if s.isdigit() and 0 < len(s) <= 10 and int(s) > 0 else None


def _key_id(key, prefix: str) -> int | None:
    """`tmdb:603` -> 603 for prefix "tmdb"; anything else -> None."""
    kind, _, ident = str(key or "").partition(":")
    return _id(ident) if kind == prefix else None


def size_text(n: int) -> str:
    return f"{n / GIB:,.1f} GB"


def _watched_text(stamp) -> str:
    at = parse_utc(stamp)
    if at is None:
        return "Watched"
    tz = home_tz()
    return "Watched " + (short_date((at.astimezone(tz) if tz else at).date().isoformat()) or "").strip()


def _films(jelly: dict, radarr: list) -> list[dict]:
    by_tmdb = {i: r for r in radarr if isinstance(r, dict) and (i := _id(r.get("tmdb_id")))}
    rows, seen = [], set()
    for m in jelly.get("movies") or []:
        if not isinstance(m, dict) or not m.get("played"):
            continue
        tmdb = _key_id(m.get("item_key"), "tmdb")
        hit = by_tmdb.get(tmdb)
        if not hit or tmdb in seen or not isinstance(hit.get("size_bytes"), int) or hit["size_bytes"] <= 0:
            continue
        seen.add(tmdb)
        rows.append({"kind": "movie", "title": m.get("title") or hit.get("title") or "Unknown",
                     "year": m.get("year") or hit.get("year"), "size": hit["size_bytes"],
                     "state_text": _watched_text(m.get("last_played_at")),
                     "href": row_href(m.get("jf_id"), m.get("item_key"), "movie")})
    return rows


def _shows(jelly: dict, sonarr: list) -> list[dict]:
    entries = [r for r in sonarr if isinstance(r, dict)]
    by_tvdb = {i: r for r in entries if (i := _id(r.get("tvdb_id")))}
    by_tmdb = {i: r for r in entries if (i := _id(r.get("tmdb_id")))}
    rows, seen = [], set()
    for s in jelly.get("shows") or []:
        if not isinstance(s, dict) or not s.get("episodes") or s.get("unplayed") != 0:
            continue
        key = s.get("item_key")
        hit = by_tvdb.get(_key_id(key, "tvdb")) or by_tmdb.get(_key_id(key, "tmdb"))
        if not hit or hit.get("ended") is not True or id(hit) in seen:
            continue
        if not isinstance(hit.get("size_bytes"), int) or hit["size_bytes"] <= 0:
            continue
        seen.add(id(hit))
        rows.append({"kind": "tv", "title": s.get("title") or hit.get("title") or "Unknown", "year": s.get("year"),
                     "size": hit["size_bytes"], "state_text": "Finished · " + plural(int(s["episodes"]), "episode"),
                     "href": row_href(s.get("jf_id"), key, "tv")})
    return rows


def _biggest(rows: list[dict]) -> list[dict]:
    return sorted(rows, key=lambda r: (-r["size"], str(r["title"]).casefold()))


def freed_days(freed_bytes: int, samples, snaps, forecast: dict | None = None) -> float | None:
    """Days of growth the freed bytes buy back at the forecast's rate, or None when the Server page has no forecast.
    `forecast`: the cached forecast item (JY-031), the one the Server page's Attention shows."""
    if not forecast or freed_bytes <= 0:
        return None
    path = forecast["key"].partition(":")[2]
    rows = [s for s in samples or [] if isinstance(s, dict) and s.get("at") is not None]
    week = [(s["at"], p) for s in rows if (p := server._vol_pct(s, path)) is not None]
    days = server.disk_days(week)
    total = next((server._num(v.get("total_gb")) for v in data_of(snaps.get(SYSTEM_SNAPSHOT_ID)).get("volumes") or []
                  if isinstance(v, dict) and v.get("path") == path), None)
    if not days or not total:
        return None
    rate = (server.DISK_TARGET_PCT - week[-1][1]) / days     # % of the volume per day
    return (freed_bytes / GIB) / total * 100 / rate if rate > 0 else None


def build(snaps, samples=None, now: datetime | None = None, forecast: dict | None = None) -> dict:
    """{connected, rows, head, empty}. `rows`: [{kind, title, year, size, size_text, state_text, href}] biggest first.
    `forecast`: the cached disk forecast item (JY-031), else no "(≈ N days)". `now`: unused since JY-031 (the cache
    holds the clock), kept for callers."""
    sizes = data_of(snaps.get(ARR_SNAPSHOT_ID)).get("library_sizes")
    if not isinstance(sizes, dict) or not connected(snaps.get(JELLYFIN_SNAPSHOT_ID)):
        return {"connected": False, "rows": [], "head": None, "empty": NOT_CONNECTED}
    jelly = data_of(snaps.get(JELLYFIN_SNAPSHOT_ID))
    rows = _biggest(_biggest(_films(jelly, sizes.get("radarr") or []))[:TOP]
                    + _biggest(_shows(jelly, sizes.get("sonarr") or []))[:TOP])
    for r in rows:
        r["size_text"] = size_text(r["size"])
    if not rows:
        return {"connected": True, "rows": [], "head": None, "empty": EMPTY}
    freed = sum(r["size"] for r in rows)
    gb = freed / GIB
    head = (f"Removing {'it' if len(rows) == 1 else f'all {len(rows)}'} frees ~"
            + (f"{gb:,.0f} GB" if gb >= 10 else f"{gb:.1f} GB"))
    days = freed_days(freed, samples, snaps, forecast)
    if days is not None:
        head += f" (≈ {server._days_text(days)} at this rate)"
    return {"connected": True, "rows": rows, "head": head, "empty": None}


@router.get("/server/space", response_class=HTMLResponse)
def space_page(request: Request):
    area = next((a for a in shell.registry.areas if a.layout == server.SERVER_LAYOUT), None)
    if area is None:
        return shell.not_found_page(request)
    samples = server_history.recent()
    forecast, _ = server_alerts.forecast_or_keep(server_history.forecast, samples)   # JY-031: as on the Server page
    sp = build(shell.get_snapshots(request=request), samples, forecast=forecast)
    return shell.render_page(request, "server_space.html", {"area": area, "sp": sp}, active_id=area.id)
