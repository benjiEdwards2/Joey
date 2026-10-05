"""Downloads (2026-10-06): joins the Radarr/Sonarr queue (arr snapshot) with live qBittorrent
torrents (qbittorrent snapshot). Pure: dicts in, dicts out; absent snapshots are just empty."""
from __future__ import annotations

import re

QB_SNAPSHOT_ID = "qbittorrent"


def caption(state_text, pct, eta_text) -> str:
    """'Downloading · 43% · 12 min' — pieces that are missing are left out."""
    return " · ".join(str(x) for x in (state_text, f"{pct}%" if pct is not None else "", eta_text) if x)


def _pack_title(group) -> str:
    """'Marvel's The Punisher · S01 · 13 episodes' from a season pack's episode rows; falls back
    to the first row's title + ' · N episodes' when series/season cannot be parsed."""
    first = str(group[0].get("title") or "")
    parts = first.split(" · ")
    m = re.match(r"(S\d+)E\d+", parts[1]) if len(parts) > 1 else None
    if parts[0] and m:
        return f"{parts[0]} · {m.group(1)} · {len(group)} episodes"
    return f"{first} · {len(group)} episodes"


def collapse_packs(arr_rows) -> list[dict]:
    """Sonarr reports a season pack as one queue row per episode, all sharing a download_id:
    those become ONE 'season' row (first row's poster/item_key), at the first row's position.
    Rows without a download_id and single-row groups pass through unchanged."""
    groups: dict[str, list[dict]] = {}
    for r in arr_rows or []:
        key = str(r.get("download_id") or "").lower()
        if key:
            groups.setdefault(key, []).append(r)
    rows: list[dict] = []
    for r in arr_rows or []:
        key = str(r.get("download_id") or "").lower()
        group = groups.get(key) if key else None
        if not group or len(group) == 1:
            rows.append(r)
        elif group[0] is r:
            rows.append({**r, "title": _pack_title(group), "kind": "season"})
    return rows


def merge_downloading(arr_rows, qb_data) -> list[dict]:
    """Arr queue rows (season packs collapsed) with live qBittorrent progress overlaid
    (hash == download_id), then the torrents no arr row claims. Every row carries a `caption`;
    rows keep the arr keys."""
    active = {str(t.get("hash") or "").lower(): t for t in ((qb_data or {}).get("active") or [])}
    claimed: set[str] = set()
    rows: list[dict] = []
    for r in collapse_packs(arr_rows):
        key = str(r.get("download_id") or "").lower()
        t = active.get(key) if key else None
        if t is None:
            rows.append({**r, "caption": caption(r.get("status_text"), None, r.get("time_left"))})
            continue
        claimed.add(key)
        eta = t.get("eta_text") or r.get("time_left") or ""
        rows.append({**r, "pct": t.get("pct", r.get("pct")), "status_text": t.get("state_text") or r.get("status_text"),
                     "time_left": eta, "caption": caption(t.get("state_text"), t.get("pct"), t.get("eta_text"))})
    for h, t in active.items():
        if h in claimed:
            continue
        rows.append({"title": t.get("name"), "kind": t.get("kind") or "other", "pct": t.get("pct", 0),
                     "status_text": t.get("state_text"), "time_left": t.get("eta_text") or "",
                     "caption": caption(t.get("state_text"), t.get("pct"), t.get("eta_text")),
                     "poster": None, "item_key": None})
    return rows


def badge_text(row: dict) -> str:
    return f"Downloading · {row.get('pct')}%"


def badges_by_item_key(merged) -> dict[str, str]:
    """item_key -> 'Downloading · 43%' for merged rows that carry a key."""
    return {r["item_key"]: badge_text(r) for r in merged or [] if r.get("item_key")}


def _norm(text) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[._]+", " ", str(text or ""))).strip().lower()


def badge_for_title(merged, title) -> str | None:
    """Badge for a title page: first merged row whose title starts with the page title
    (so a trailing year or 'S01E02' on the row does not matter). None when nothing matches."""
    want = _norm(title)
    if not want:
        return None
    for r in merged or []:
        if _norm(r.get("title")).startswith(want):
            return badge_text(r)
    return None
