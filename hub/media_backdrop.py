"""Which backdrop a page draws (JY-262, 2026-10-28). Spec: docs/specs/JY-262-tmdb-backdrops.md.

B., 2026-10-28: "use the first background as the home page or carousel image, then if you go into the show. It shows
the second background image or such."

Jellyfin keeps a title's TMDB backdrops as Backdrop images 0, 1, 2... (`BackdropImageTags`). The Home hero and its rows
draw index 0; a title page draws index 1, or index 0 when Jellyfin holds only one or the count is not known. No
Jellyfin backdrop: the cached TMDB backdrop (Seerr's `backdropPath`, the first; the cache holds no second one).
Every ref is an /img ref; nothing here reads anything.
"""
from __future__ import annotations

HOME, TITLE = 0, 1
TV_H = 1280   # /img ?h=1280: 1280 wide (TMDB w1280, Jellyfin maxWidth 1280); never TMDB "original" (up to 4K)


def count_of(tags) -> int | None:
    """How many backdrops Jellyfin holds, from `BackdropImageTags`; None when the read did not say."""
    return len(tags) if isinstance(tags, list) else None


def jellyfin(art: str | None, count: int | None, want: int) -> str | None:
    """The `jfb:` ref of backdrop `want` of item `art`: index `want` when Jellyfin holds more than `want`, else
    index 0 (which every item with a backdrop has; also when the count is unknown). None when it holds none."""
    if not art or count == 0:
        return None
    index = want if isinstance(count, int) and count > want else 0
    return f"jfb:{art}/{index}" if index else f"jfb:{art}"


def title_page(item: dict | None, row: dict | None, tmdb: str | None) -> str | None:
    """The title page hero: the item read's backdrop 1 (else 0), else the snapshot row's (index 0, count unknown),
    else the cached TMDB backdrop."""
    if item:
        art = str(item.get("backdrop") or "").removeprefix("jfb:") or None
        return jellyfin(art, item.get("backdrops"), TITLE) or tmdb
    return (row or {}).get("backdrop") or tmdb
