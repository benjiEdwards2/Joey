"""Media app frame (F1, 2026-10-06): the one section/tab map for every Media page.
Pure: no area name lives here — Home resolves to the registry's first `layout: shelves` area.
"""
from __future__ import annotations

from urllib.parse import parse_qs, parse_qsl, urlencode, urlsplit

HOME_ID = "home"

SECTIONS: list[dict] = [
    {"id": "home", "label": "Home", "href": None, "prefixes": [], "tabs": []},
    {"id": "movies", "label": "Movies", "href": "/media/movies", "prefixes": ["/media/movies"],
     "tabs": [("My films", "/media/movies"), ("Watchlist", "/media/movies/watchlist"),
              ("By year", "/media/years?kind=movie"),
              ("Tonight", "/media/movies/tonight")]},
    {"id": "tv", "label": "TV Shows", "href": "/media/tv", "prefixes": ["/media/tv"],
     "tabs": [("My shows", "/media/tv"), ("Watchlist", "/media/tv/watchlist"),
              ("By year", "/media/years?kind=tv"),
              ("Tonight", "/media/tv/tonight")]},
    {"id": "diary", "label": "Diary", "href": "/media/diary", "prefixes": ["/media/diary", "/media/history"],
     "tabs": [("Diary", "/media/diary"), ("To rate", "/media/history")]},
    {"id": "server", "label": "Server", "href": "/media/playing",
     "prefixes": ["/media/playing", "/media/server", "/media/library", "/media/downloads", "/media/requests", "/media/apps"],
     "tabs": [("Live", "/media/playing"), ("History", "/media/server/history"), ("Library", "/media/library"), ("Downloads", "/media/downloads"),
              ("Requests", "/media/requests"), ("Health", "/media/apps")]},
    {"id": "discover", "label": "Discover", "href": "/media/discover",
     "prefixes": ["/media/discover", "/media/title"], "tabs": []},
]
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
    """{sections, section, tabs, home_href, accent, here}; counts only when > 0."""
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
    sections = [{"id": s["id"], "label": s["label"], "href": home_href if s["id"] == HOME_ID else s["href"],
                 "on": section is not None and s["id"] == section["id"],
                 "count": counts.get(s["id"], 0) or 0} for s in SECTIONS]
    tabs = []
    if section:
        scores = [_tab_on(h, path, kind) for _, h in section["tabs"]]
        top = max(scores, default=0)
        tab_counts = {"/media/movies/watchlist": waiting.get("wl_movie", 0),
                      "/media/tv/watchlist": waiting.get("wl_tv", 0)}
        tabs = [{"label": label, "href": h, "on": bool(top) and sc == top, "count": tab_counts.get(h, 0) or 0}
                for (label, h), sc in zip(section["tabs"], scores)]
    keep = [(k, v) for k, v in parse_qsl(request.url.query, keep_blank_values=True) if k != "owner_view"]
    here = path + (f"?{urlencode(keep, doseq=True)}" if keep else "")
    return {"sections": sections, "section": section, "tabs": tabs, "home_href": home_href,
            "accent": area.accent if area else None, "here": here}
