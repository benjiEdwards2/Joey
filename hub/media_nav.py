"""Media app frame (F1, 2026-10-06): the one section/tab map for every Media page.
Pure: no area name lives here — Home resolves to the registry's first `layout: shelves` area.
"""
from __future__ import annotations

HOME_ID = "home"

SECTIONS: list[dict] = [
    {"id": "home", "label": "Home", "short": "Home", "icon": "house", "href": None, "prefixes": [], "tabs": []},
    {"id": "movies", "label": "Movies", "short": "Movies", "icon": "film", "href": "/media/movies", "prefixes": ["/media/movies"],
     "tabs": [("My films", "/media/movies"), ("Watchlist", "/media/movies/watchlist"),
              ("Tonight", "/media/movies/tonight"), ("To Rate", "/media/movies/to-rate"),
              ("Awards", "/media/movies/awards")]},
    {"id": "tv", "label": "TV Shows", "short": "TV", "icon": "tv", "href": "/media/tv", "prefixes": ["/media/tv"],
     "tabs": [("My shows", "/media/tv"), ("Watchlist", "/media/tv/watchlist"),
              ("Tonight", "/media/tv/tonight"), ("To Rate", "/media/tv/to-rate"),
              ("Awards", "/media/tv/awards")]},
    {"id": "diary", "label": "Diary", "short": "Diary", "icon": "diary", "href": "/media/diary", "prefixes": ["/media/diary", "/media/history"],
     "tabs": [("Diary", "/media/diary"), ("To Rate", "/media/history")]},
    # decision 4 (2026-10-09): the Media section reads "Activity" (the hub AREA stays "Server"); id + URLs unchanged.
    {"id": "server", "label": "Activity", "short": "Activity", "icon": "server", "href": "/media/playing",
     "prefixes": ["/media/playing", "/media/server", "/media/library", "/media/downloads", "/media/requests", "/media/apps"],
     "tabs": [("Live", "/media/playing"), ("History", "/media/server/history"), ("Library", "/media/library"), ("Downloads", "/media/downloads"),
              ("Requests", "/media/requests"), ("Health", "/media/apps")]},
    {"id": "discover", "label": "Discover", "short": "Discover", "icon": "compass", "href": "/media/discover",
     "prefixes": ["/media/discover", "/media/following", "/media/title", "/media/person"],
     # Follow (2026-10-07): Discover / Following; a title or person page shows no sub-tab row (none is its own)
     "tabs": [("Discover", "/media/discover"), ("Following", "/media/following")], "tabs_only_on": True},
]
# awards-year (2026-10-09, B.): the tab label reads "To Rate" (Movies, TV Shows and Diary); body copy stays sentence case.
# Awards (2026-10-08): the Awards tab follows To rate on Movies and TV Shows (hub/media_awards_pages.py).
# media-ux4 (2026-10-08): "To rate" is a tab beside Tonight (the films / TV inbox, count when > 0); the To rate section
# left the top of the list pages.
# By-year rankings removed 2026-10-09 (decision 1).


def shelves_area(registry):
    return next((a for a in registry.areas if a.layout == "shelves"), None) if registry else None


def _under(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(prefix + "/")


def active_section(path: str, home_href: str | None = None) -> dict | None:
    """Longest-prefix section for `path`."""
    best, best_len = None, -1
    for s in SECTIONS:
        prefixes = [home_href] if s["id"] == HOME_ID and home_href else s["prefixes"]
        for p in prefixes:
            if _under(path, p) and len(p) > best_len:
                best, best_len = s, len(p)
    return best


def _tab_on(tab_href: str, path: str) -> int:
    """Match strength of a tab for this page (0 = no match; longer path wins)."""
    tpath = tab_href.partition("?")[0]
    return len(tpath) if _under(path, tpath) else 0


def nav_context(request, registry, waiting: dict | None) -> dict:
    """{sections, section, tabs, home_href}; counts only when > 0."""
    path = request.url.path
    area = shelves_area(registry)
    home_href = f"/a/{area.id}" if area else "/"
    section = active_section(path, home_href if area else None)
    forced = getattr(getattr(request, "state", None), "media_section", None)  # F9: item pages pick Movies / TV Shows by kind
    if forced:
        section = next((s for s in SECTIONS if s["id"] == forced), section)
    waiting = waiting or {}
    counts = {"diary": waiting.get("to_rate", 0)}
    sections = [{"id": s["id"], "label": s["label"], "short": s["short"], "icon": s["icon"], "href": home_href if s["id"] == HOME_ID else s["href"],
                 "on": section is not None and s["id"] == section["id"],
                 "count": counts.get(s["id"], 0) or 0} for s in SECTIONS]
    tabs = []
    if section:
        scores = [_tab_on(h, path) for _, h in section["tabs"]]
        top = max(scores, default=0)
        tab_counts = {"/media/movies/watchlist": waiting.get("wl_movie", 0),
                      "/media/tv/watchlist": waiting.get("wl_tv", 0),
                      "/media/movies/to-rate": waiting.get("to_rate_movie", 0),
                      "/media/tv/to-rate": waiting.get("to_rate_tv", 0)}
        tabs = [{"label": label, "href": h, "on": bool(top) and sc == top, "count": tab_counts.get(h, 0) or 0,
                 "what": "to rate" if h.endswith("/to-rate") else "to get"}
                for (label, h), sc in zip(section["tabs"], scores)]
        # E4 (U5, 2026-10-13): an item / title page (a forced section) is no tab's own either, so it shows no sub-tab row
        if (section.get("tabs_only_on") or forced) and not top:
            tabs = []
    # E3 (U4, 2026-10-13): the page names itself — the active tab's label ("My films", "Diary", "Requests"), else the
    # section's ("Discover" on a person page, which draws its own H1 instead); None outside every section.
    on = next((t for t in tabs if t["on"]), None)
    title = on["label"] if on else (section["label"] if section else None)
    return {"sections": sections, "section": section, "tabs": tabs, "home_href": home_href, "title": title}
