"""Which backdrop a page draws (JY-262, 2026-10-28). Spec: docs/specs/JY-262-tmdb-backdrops.md.

B., 2026-10-28: "use the first background as the home page or carousel image, then if you go into the show. It shows
the second background image or such."

Jellyfin keeps a title's TMDB backdrops as Backdrop images 0, 1, 2... (`BackdropImageTags`). The Home hero and its rows
draw index 0; a title page draws index 1, or index 0 when Jellyfin holds only one or the count is not known. No
Jellyfin backdrop: the cached TMDB backdrop (Seerr's `backdropPath`, the first; the cache holds no second one).
Every ref is an /img ref; nothing here reads anything.

Follow-up (2026-10-28, B. picked option A: "Background: A" / "Use A where there are two posters."): when the poster
pass has stored the title's two top-ranked TMDB backdrops (`jfs:<id>/1` and `/2`, hub/media_posters.fetch_backdrops),
Home uses backdrop1 and the title page backdrop2, else backdrop1, else the chain above. A season or episode page uses
its show's pair (`item["backdrop"]` already names the show). Only local store files are read.
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


def stored(art: str | None, n: int) -> str | None:
    """`jfs:<art>/<n>` when the poster store holds that title's ranked TMDB backdrop n, else None (local reads only)."""
    if not art:
        return None
    from hub import media_posters   # late: the poster modules load Pillow
    return media_posters.stored_backdrop(art, n)


def home(art: str | None) -> str | None:
    """Home's hero / carousel: the stored backdrop1, or None (the caller's JY-262 chain follows)."""
    return stored(art, 1)


def title_page(item: dict | None, row: dict | None, tmdb: str | None) -> str | None:
    """The title page hero: the stored ranked backdrop2, else backdrop1; else the item read's Jellyfin backdrop 1
    (else 0), else the snapshot row's (index 0, count unknown), else the cached TMDB backdrop."""
    ref = str((item or {}).get("backdrop") or (row or {}).get("backdrop") or "")
    art = ref.removeprefix("jfb:").split("/", 1)[0] if ref.startswith("jfb:") else None
    ranked = stored(art, 2) or stored(art, 1)
    if ranked:
        return ranked
    if item:
        art = str(item.get("backdrop") or "").removeprefix("jfb:") or None
        return jellyfin(art, item.get("backdrops"), TITLE) or tmdb
    return (row or {}).get("backdrop") or tmdb
