"""Upgrade available (F4b, 2026-10-12). B.: "show me if an upgrade is available … a small light-blue text underneath
the movie saying 'Upgrade available', and allow me to decide if I want to download that upgrade."

Pure helpers over the `arr` snapshot's `data.upgrades` (Radarr / Sonarr "cutoff unmet": the file on disk is below the
quality profile's cutoff — it does NOT mean a better release is out there; "Search for upgrade" asks the app to look).
No I/O: callers pass the snapshots. The label renders under list rows (Movies / TV, grid and list), in the film / show
hero under the status line, on Requests rows and as the Upgrades block on Activity › Downloads.

Keys: Radarr rows are `tmdb:<id>` like the library's films. Sonarr rows are `tvdb:<id>` while Jellyfin's show rows
prefer `tmdb:<id>`, so a show is matched by (1) its own `tvdb:` key, (2) a TheTVDB id the caller knows (the Jellyfin
item's ProviderIds.Tvdb, cached by the show page — media_item.peek — or a Jellyseerr request's tvdb_id), else (3) the
normalised title when exactly one Sonarr row and exactly one library show carry it.
"""
from __future__ import annotations

import re

from hub.ids import ARR_SNAPSHOT_ID

APPS = {"movie": "radarr", "tv": "sonarr"}


def _arr(snaps) -> dict:
    snap = (snaps or {}).get(ARR_SNAPSHOT_ID)
    data = getattr(snap, "data", None) if snap is not None else None
    return data if isinstance(data, dict) else {}


def upgrades(snaps) -> dict | None:
    """The snapshot's `upgrades` object, or None (no arr snapshot / an older envelope without the key)."""
    up = _arr(snaps).get("upgrades")
    return up if isinstance(up, dict) else None


def note(row: dict | None) -> str:
    """'Upgrade available · WEBDL-720p → Bluray-1080p'; a show: 'Upgrade available · 3 episodes · SDTV → WEB 1080p'.
    The quality part is left out when `want` is unknown; without `have` it reads 'to Bluray-1080p'."""
    if not row:
        return ""
    parts = ["Upgrade available"]
    n = row.get("episodes")
    if isinstance(n, int) and not isinstance(n, bool) and n > 0:
        parts.append(f"{n} episode{'' if n == 1 else 's'}")
    if row.get("want"):
        parts.append(f"{row['have']} → {row['want']}" if row.get("have") else f"to {row['want']}")
    return " · ".join(parts)


def norm_title(text) -> str:
    """Lower-case, no punctuation, no leading article, single spaces (media_library's rule). A parenthesised
    trailing year is dropped first: Sonarr disambiguates "Brothers (2026)" but Jellyfin's row is "Brothers"
    (seen live 2026-10-12); a bare number in a title ("Blade Runner 2049") is kept."""
    text = re.sub(r"\s*\((19|20)\d\d\)\s*$", "", str(text or ""))
    words = re.sub(r"[^a-z0-9]+", " ", text.lower()).split()
    return " ".join(words[1:] if len(words) > 1 and words[0] in ("the", "a", "an") else words)


def index(snaps) -> dict:
    """{item_key: row} over both lists; each row gains `app` ('radarr' | 'sonarr') and its `note`. Empty when the
    snapshot has no `upgrades` (older envelope) or both lists are null."""
    up = upgrades(snaps) or {}
    out: dict = {}
    for app in ("radarr", "sonarr"):
        for r in up.get(app) or []:
            if isinstance(r, dict) and r.get("item_key"):
                out[str(r["item_key"])] = {**r, "app": app, "note": note(r)}
    return out


def _titles(idx: dict) -> dict:
    """{normalised title: row} for Sonarr rows whose title is unique among them."""
    seen: dict = {}
    for r in idx.values():
        if r["app"] == "sonarr":
            seen.setdefault(norm_title(r.get("title")), []).append(r)
    return {t: rows[0] for t, rows in seen.items() if t and len(rows) == 1}


def find(idx: dict, kind: str, item_key=None, tvdb=None, title=None, titles: dict | None = None) -> dict | None:
    """The upgrade row for a title of this kind, or None. A film matches its `tmdb:` key only (TMDB movie and TV ids are
    separate spaces, so a row of the other app never matches); a show its `tvdb:` key, then `tvdb`, then the unique
    title (`titles` = _titles(idx), passed in to build it once per page)."""
    if not idx:
        return None
    app = APPS["tv" if kind == "tv" else "movie"]
    hit = idx.get(str(item_key or ""))
    if hit and hit["app"] == app:
        return hit
    if app == "radarr":
        return None
    tv = str(tvdb or "")
    if tv.isdigit():
        hit = idx.get(f"tvdb:{int(tv)}")
        if hit and hit["app"] == "sonarr":
            return hit
    if title:
        return (_titles(idx) if titles is None else titles).get(norm_title(title))
    return None


def attach(rows, snaps, kind: str | None, tvdb_of=lambda r: None) -> None:
    """Set `upgrade` (the note, or '') on each library / request row in place. `kind` None = each row's own `kind`
    (Requests mixes films and shows). `tvdb_of(row)` -> a TheTVDB id the caller knows for the row, or None. The title
    match needs the name unique among these rows too."""
    idx = index(snaps)
    rows = list(rows or [])
    if not idx:
        for r in rows:
            r["upgrade"] = ""
        return
    titles = _titles(idx)
    count: dict = {}
    for r in rows:
        count[norm_title(r.get("title"))] = count.get(norm_title(r.get("title")), 0) + 1
    for r in rows:
        unique = count.get(norm_title(r.get("title"))) == 1
        k = kind or ("tv" if r.get("kind") == "tv" else "movie")
        hit = find(idx, k, r.get("item_key"), tvdb_of(r), r.get("title") if unique else None, titles)
        r["upgrade"] = hit["note"] if hit else ""


def block(snaps) -> dict | None:
    """The Activity › Downloads "Upgrades" block: None when the snapshot has no `upgrades` (older envelope — the block
    is absent); {state: 'off'} when both lists are null; else {rows, totals_text, off: [app names whose list is null]}.
    Rows carry `kind` (movie | tv) for the linker, `note`, `poster`, `title`."""
    up = upgrades(snaps)
    if up is None:
        return None
    radarr, sonarr = up.get("radarr"), up.get("sonarr")
    if radarr is None and sonarr is None:
        return {"state": "off"}
    totals = up.get("totals") if isinstance(up.get("totals"), dict) else {}
    films = totals.get("movies") if isinstance(totals.get("movies"), int) else len(radarr or [])
    shows = totals.get("series") if isinstance(totals.get("series"), int) else len(sonarr or [])
    pieces = []
    if radarr is not None:
        pieces.append(f"{films} film{'' if films == 1 else 's'}")
    if sonarr is not None:
        pieces.append(f"{shows} show{'' if shows == 1 else 's'}")
    rows = ([{**r, "kind": "movie", "note": note(r)} for r in radarr or [] if isinstance(r, dict)]
            + [{**r, "kind": "tv", "note": note(r)} for r in sonarr or [] if isinstance(r, dict)])
    return {"state": "ok", "rows": rows, "totals_text": " · ".join(pieces),
            "off": [name for name, lst in (("Radarr", radarr), ("Sonarr", sonarr)) if lst is None]}
