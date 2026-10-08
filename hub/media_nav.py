"""Media app frame (F1, 2026-10-06): the one section/tab map for every Media page.
Pure: no area name lives here — Home resolves to the registry's first `layout: shelves` area.
"""
from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

HOME_ID = "home"

SECTIONS: list[dict] = [
    {"id": "home", "label": "Home", "short": "Home", "icon": "house", "href": None, "prefixes": [], "tabs": []},
    {"id": "movies", "label": "Movies", "short": "Movies", "icon": "film", "href": "/media/movies", "prefixes": ["/media/movies"],
     "tabs": [("My films", "/media/movies"), ("Watchlist", "/media/movies/watchlist"),
              ("Tonight", "/media/movies/tonight"), ("To rate", "/media/movies/to-rate")]},
    {"id": "tv", "label": "TV Shows", "short": "TV", "icon": "tv", "href": "/media/tv", "prefixes": ["/media/tv"],
     "tabs": [("My shows", "/media/tv"), ("Watchlist", "/media/tv/watchlist"),
              ("Tonight", "/media/tv/tonight"), ("To rate", "/media/tv/to-rate")]},
    {"id": "diary", "label": "Diary", "short": "Diary", "icon": "diary", "href": "/media/diary", "prefixes": ["/media/diary", "/media/history"],
     "tabs": [("Diary", "/media/diary"), ("To rate", "/media/history")]},
    {"id": "server", "label": "Server", "short": "Server", "icon": "server", "href": "/media/playing",
     "prefixes": ["/media/playing", "/media/server", "/media/library", "/media/downloads", "/media/requests", "/media/apps"],
     "tabs": [("Live", "/media/playing"), ("History", "/media/server/history"), ("Library", "/media/library"), ("Downloads", "/media/downloads"),
              ("Requests", "/media/requests"), ("Health", "/media/apps")]},
    {"id": "discover", "label": "Discover", "short": "Discover", "icon": "compass", "href": "/media/discover",
     "prefixes": ["/media/discover", "/media/following", "/media/title", "/media/person"],
     # Follow (2026-10-07): Discover / Following; a title or person page shows no sub-tab row (none is its own)
     "tabs": [("Discover", "/media/discover"), ("Following", "/media/following")], "tabs_only_on": True},
]
# media-ux4 (2026-10-08): "To rate" is a tab beside Tonight (the films / TV inbox, count when > 0); the To rate section
# left the top of the list pages.
# media-ux2 (2026-10-08): the "By year" tabs are gone from Movies / TV Shows (B.); /media/years stays reachable by
# URL and still lights its section. To restore: add ("By year", "/media/years?kind=movie|tv") back to the tabs —
# _tab_on below still knows how to match it.
YEARS = "/media/years"


def shelves_area(registry):
    return next((a for a in registry.areas if a.layout == "shelves"), None) if registry else None


def _under(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(prefix + "/")


def _kind(query) -> str | None:
    if isinstance(query, str):
        query = {k: v[-1] for k, v in parse_qs(query).items()}
    kind = (query or {}).get("kind")
    return kind if kind in ("movie", "tv") else None


def active_section(path: str, query=None, home_href: str | None = None) -> dict | None:
    """Longest-prefix section for `path`. /media/years is movies unless ?kind=tv."""
    if _under(path, YEARS):
        return next(s for s in SECTIONS if s["id"] == ("tv" if _kind(query) == "tv" else "movies"))
    best, best_len = None, -1
    for s in SECTIONS:
        prefixes = [home_href] if s["id"] == HOME_ID and home_href else s["prefixes"]
        for p in prefixes:
            if _under(path, p) and len(p) > best_len:
                best, best_len = s, len(p)
    return best


def _tab_on(tab_href: str, path: str, kind: str | None) -> int:
    """Match strength of a tab for this page (0 = no match; longer path wins)."""
    tpath, _, tq = tab_href.partition("?")
    if tpath == YEARS:
        want = _kind(tq) or "movie"
        return len(tpath) if _under(path, YEARS) and (kind or "movie") == want else 0
    return len(tpath) if _under(path, tpath) else 0


def nav_context(request, registry, waiting: dict | None, owner_view: str | None = None) -> dict:
    """{sections, section, tabs, home_href}; counts only when > 0."""
    path = request.url.path
    kind = _kind(request.url.query)
    area = shelves_area(registry)
    home_href = f"/a/{area.id}" if area else "/"
    section = active_section(path, request.url.query, home_href if area else None)
    forced = getattr(getattr(request, "state", None), "media_section", None)  # F9: item pages pick Movies / TV Shows by kind
    if forced:
        section = next((s for s in SECTIONS if s["id"] == forced), section)
    waiting = waiting or {}
    counts = {"diary": waiting.get("to_rate", 0), "movies": waiting.get("to_place", 0),
              "tv": waiting.get("to_place", 0)}
    sections = [{"id": s["id"], "label": s["label"], "short": s["short"], "icon": s["icon"], "href": home_href if s["id"] == HOME_ID else s["href"],
                 "on": section is not None and s["id"] == section["id"],
                 "count": counts.get(s["id"], 0) or 0} for s in SECTIONS]
    tabs = []
    if section:
        scores = [_tab_on(h, path, kind) for _, h in section["tabs"]]
        top = max(scores, default=0)
        tab_counts = {"/media/movies/watchlist": waiting.get("wl_movie", 0),
                      "/media/tv/watchlist": waiting.get("wl_tv", 0),
                      "/media/movies/to-rate": waiting.get("to_rate_movie", 0),
                      "/media/tv/to-rate": waiting.get("to_rate_tv", 0)}
        tabs = [{"label": label, "href": h, "on": bool(top) and sc == top, "count": tab_counts.get(h, 0) or 0,
                 "what": "to rate" if h.endswith("/to-rate") else "to get"}
                for (label, h), sc in zip(section["tabs"], scores)]
        if section.get("tabs_only_on") and not top:
            tabs = []
    return {"sections": sections, "section": section, "tabs": tabs, "home_href": home_href}
