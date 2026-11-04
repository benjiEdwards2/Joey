"""Upgrade available (F4b, 2026-10-12). B.: "show me if an upgrade is available … a small light-blue text underneath
the movie saying 'Upgrade available', and allow me to decide if I want to download that upgrade."

Pure helpers over the `arr` snapshot's `data.upgrades` (Radarr / Sonarr "cutoff unmet": the file on disk is below the
quality profile's cutoff — it does NOT mean a better release is out there; "Search for upgrade" asks the app to look).
No I/O: callers pass the snapshots. The label renders under list rows (Movies / TV, grid and list), in the film / show
hero under the status line, on Requests rows and as the Upgrades block on Activity › Downloads.

WP-U1 (2026-10-21): the label is now "Below cutoff · HDTV-1080p → wants WEB/Bluray 1080p" (B. saw "Upgrade available"
on a title for which every release on the indexers was rejected); `last_search` words the snapshot's last library search,
and Downloads' "Why?" (hub/media_upgrade_why.py) asks the app what it would grab and why not.

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


LABEL = "Below cutoff"   # WP-U1 (2026-10-21): was "Upgrade available" - the file is below the profile's cutoff, which
#                           does not mean a better release exists (live: every Brothers release rejected)


def note(row: dict | None) -> str:
    """'Below cutoff · WEBDL-720p → wants Bluray-1080p'; a show: 'Below cutoff · 3 episodes · SDTV → wants WEB 1080p'
    (WP-U1, 2026-10-21; was 'Upgrade available · … → …'). The quality part is left out when `want` is unknown; without
    `have` it reads 'wants Bluray-1080p'."""
    if not row:
        return ""
    parts = [LABEL]
    n = row.get("episodes")
    if isinstance(n, int) and not isinstance(n, bool) and n > 0:
        parts.append(f"{n} episode{'' if n == 1 else 's'}")
    if row.get("want"):
        parts.append(f"{row['have']} → wants {row['want']}" if row.get("have") else f"wants {row['want']}")
    return " · ".join(parts)


FLAG = "Upgrade available"   # JY-275 (2026-11-04): the one blue word, only when a check found an acceptable release


def is_viable(row: dict | None) -> bool:
    """JY-275: a cutoff-unmet row is flagged only when its kept Why? answer (media_upgrade_why, 24 h, in memory) found
    an accepted release. The single rule every surface uses. Never a call."""
    if not row:
        return False
    from hub import media_upgrade_why   # late: it imports this module
    app = row.get("app") or ("radarr" if row.get("kind") == "movie" else "sonarr")
    return media_upgrade_why.viable(app, row.get("arr_id"))


def flag(row: dict | None) -> str:
    """FLAG for a viable row, else '' (JY-275: was the 'Below cutoff · …' sentence on every cutoff-unmet title)."""
    return FLAG if is_viable(row) else ""


ASK = "upgrade_ask=1#upgrade"


def upgrade_href(row: dict) -> str | None:
    """JY-275: a row's Upgrade button = the title page with its Upgrade confirm open (the one confirmed POST lives
    there). A local `href` wins, else /media/title/<kind>/<tmdb> from a `tmdb:` key; None when neither is known."""
    href = str(row.get("href") or "")
    if href.startswith("/media/"):
        return f"{href}{'&' if '?' in href else '?'}{ASK}"
    key = str(row.get("item_key") or "")
    if key.startswith("tmdb:") and key[5:].isdigit():
        return f"/media/title/{'tv' if row.get('kind') == 'tv' else 'movie'}/{key[5:]}?{ASK}"
    return None


def tvdb_of(row: dict) -> str | None:
    """A Sonarr row's TheTVDB id from its `tvdb:` key, else None."""
    key = str(row.get("item_key") or "")
    return key[5:] if key.startswith("tvdb:") and key[5:].isdigit() else None


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
                row = {**r, "app": app}
                out[str(r["item_key"])] = {**row, "note": flag(row), "detail": note(r)}
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
        r["upgrade_href"] = upgrade_href({**r, "kind": k}) if r["upgrade"] else None   # JY-275: the row's button


SEARCH_WORDS = {"upgrades": "Last upgrade search", "missing": "Last missing search", "search": "Last search"}  # JY-302
_SEARCH_MSG = re.compile(r"search for (\d+) \w+\. (\d+) reports? downloaded", re.I)


def _when(stamp) -> str | None:
    """'21 Oct 01:00' in the household's zone from an ISO stamp, else None."""
    from datetime import datetime
    from hub.ids import home_tz
    try:
        dt = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(home_tz())
    return f"{dt.day} {dt:%b %H:%M}"


def last_search(snaps) -> list[dict]:
    """Activity › Downloads, under the Search buttons (WP-U1, 2026-10-21): one line per app from the snapshot's
    `upgrades.last_search` -> [{parts, warn}]: parts 'Last upgrade search', 'Sonarr', '21 Oct 01:00', '1 searched', and
    `warn` the amber words — '0 downloaded' when it found nothing, 'failed' — else None. A message the pattern does not
    fit is shown verbatim; a running search reads 'running'. [] for an older envelope or no search yet."""
    out = []
    for s in (upgrades(snaps) or {}).get("last_search") or []:
        if not isinstance(s, dict) or s.get("name") not in SEARCH_WORDS or s.get("app") not in APPS.values():
            continue
        parts, warn = [SEARCH_WORDS[s["name"]], "Radarr" if s["app"] == "radarr" else "Sonarr"], None
        status = str(s.get("status") or "")
        if status in ("queued", "started"):
            parts.append("running")
        else:
            when = _when(s.get("ended")) if s.get("ended") else None
            if when:
                parts.append(when)
            m = _SEARCH_MSG.search(str(s.get("message") or ""))
            if status == "failed":
                warn = "failed"
            elif m:
                parts.append(f"{m.group(1)} searched")
                got = int(m.group(2))
                if got:
                    parts.append(f"{got} downloaded")
                else:
                    warn = "0 downloaded"
            elif s.get("message"):
                parts.append(str(s["message"]))
        out.append({"parts": parts, "warn": warn})
    return out


def block(snaps) -> dict | None:
    """The Activity › Downloads "Upgrades" block: None when the snapshot has no `upgrades` (older envelope — the block
    is absent); {state: 'off'} when both lists are null; else {rows, totals_text, off: [app names whose list is null]}.
    Rows carry `kind` (movie | tv) for the linker, `note` (FLAG or ''), `detail`, `poster`, `title`. JY-275: `rows` holds
    only viable rows, `unchecked` the others."""
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
    rows = ([{**r, "kind": "movie", "app": "radarr"} for r in radarr or [] if isinstance(r, dict)]
            + [{**r, "kind": "tv", "app": "sonarr"} for r in sonarr or [] if isinstance(r, dict)])
    rows = [{**r, "note": flag(r), "detail": note(r)} for r in rows]
    # JY-275: `rows` = the viable ones (flag + Upgrade); `unchecked` = the rest, folded away with their Why?
    return {"state": "ok", "rows": [r for r in rows if r["note"]], "unchecked": [r for r in rows if not r["note"]],
            "totals_text": " · ".join(pieces),
            "off": [name for name, lst in (("Radarr", radarr), ("Sonarr", sonarr)) if lst is None]}
