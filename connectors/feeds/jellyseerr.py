"""Jellyseerr: the request queue, with titles from capped per-request TMDB lookups."""

from __future__ import annotations

import os
import re
from datetime import datetime

from connectors.base import Connector, mode
from connectors.feeds._common import FIXTURE_MEDIA_HOST, _ago, _dt, _now
from connectors.feeds._http import http_json, session


SEERR_LIST_TAKE = 100      # requests fetched per sweep (newest first, every status)
SEERR_PENDING_TAKE = 200   # WP-RQ1 (2026-10-22): pending requests fetched on their own, so none is cut by the cap
SEERR_ROW_LIMIT = 60       # rows kept in the data block besides the pending ones (every pending row is always kept)
SEERR_LOOKUP_CAP = 20      # new TMDB title lookups per sweep (the rest keep "TMDB #id")
# Jellyseerr request.status / media.status -> a word, never a colour. Seerr v3: 4 = FAILED, 5 = COMPLETED
# (the media is in Jellyfin, so "Available"). An unknown code is still an open request -> "Approved", not "Pending".
SEERR_REQUEST_STATUS = {1: "Pending", 2: "Approved", 3: "Declined", 4: "Failed", 5: "Available"}
SEERR_MEDIA_STATUS = {5: "Available", 4: "Partly available", 3: "Processing"}


def _seerr_kind(request: dict) -> str:
    kind = request.get("type") or (request.get("media") or {}).get("mediaType")
    return "tv" if kind == "tv" else "movie"


def _seerr_status_text(request: dict) -> str:
    text = SEERR_REQUEST_STATUS.get(request.get("status"), "Approved")
    if text == "Approved":  # an approved request reports how far the download got
        text = SEERR_MEDIA_STATUS.get((request.get("media") or {}).get("status"), text)
    return text


def _seerr_year(value) -> int | None:
    match = re.match(r"(\d{4})", str(value or ""))
    return int(match.group(1)) if match else None


def _seerr_int(value) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _seerr_name(by: dict) -> str:
    """JY-230: the requester's name, never an email (Seerr's displayName falls back to the user's email)."""
    for key in ("displayName", "jellyfinUsername", "username"):
        name = str(by.get(key) or "").strip()
        if name and "@" not in name:
            return name[:80]
    return "someone"


def _seerr_jf(by: dict) -> str | None:
    """JY-230: the requester's Jellyfin user id (dash-less, lower case), so the hub can say "you" / "her"."""
    jf = str(by.get("jellyfinUserId") or "").replace("-", "").strip().lower()
    return jf if re.fullmatch(r"[0-9a-f]{32}", jf) else None


def _seerr_seasons(request: dict) -> list[int]:
    """The request's season numbers (Seerr `seasons[].seasonNumber`), sorted, Specials (0) included as Seerr has them."""
    nums = {s.get("seasonNumber") for s in request.get("seasons") or [] if isinstance(s, dict)}
    return sorted(n for n in nums if isinstance(n, int) and not isinstance(n, bool) and n >= 0)


class Jellyseerr(Connector):
    """Jellyseerr's request queue. Titles come from per-request TMDB lookups,
    capped per sweep and reused from the previous envelope; one failed lookup
    leaves that row as 'TMDB #id' and never fails the run."""

    id = "jellyseerr"
    requires_env = ("JELLYSEERR_URL", "JELLYSEERR_API_KEY")

    def fetch(self) -> dict:
        client = session()  # one connection for the run's up to 23 calls (C-05)
        try:
            return self._fetch(client)
        finally:
            client.close()

    def _fetch(self, client) -> dict:
        base = os.environ["JELLYSEERR_URL"].rstrip("/")
        headers = {"X-Api-Key": os.environ["JELLYSEERR_API_KEY"]}

        def get(label: str, path: str, params: dict | None = None):
            return http_json(f"Seerr {label}", base + path, headers=headers, params=params, session=client)

        raw_count = get("count", "/api/v1/request/count")
        raw_requests = get("requests", "/api/v1/request",
                           {"take": SEERR_LIST_TAKE, "skip": 0, "sort": "added", "filter": "all"})
        # WP-RQ1 (2026-10-22): every pending request, however old - B. approves or declines them from the Requests page
        raw_pending = get("pending requests", "/api/v1/request",
                          {"take": SEERR_PENDING_TAKE, "skip": 0, "sort": "added", "filter": "pending"})

        # Titles already resolved last sweep are reused, so repeats cost no calls.
        known: dict[str, dict] = {}
        for row in ((self._previous() or {}).get("data") or {}).get("requests", []):
            if (row.get("tmdb_id") and "poster" in row  # pre-poster rows are looked up again
                    and not str(row.get("title", "")).startswith("TMDB #")):
                known[f"{row['kind']}:{row['tmdb_id']}"] = {
                    "title": row["title"], "name": row["title"],
                    "releaseDate": str(row["year"]) if row.get("year") else None,
                    "posterPath": (row.get("poster") or "").removeprefix("tmdb:") or None}
        titles, lookups = {}, 0
        for request in [*raw_pending.get("results", []), *raw_requests.get("results", [])]:   # pending titles first
            tmdb = (request.get("media") or {}).get("tmdbId")
            if not tmdb:
                continue
            kind = _seerr_kind(request)
            key = f"{kind}:{tmdb}"
            if key in titles:
                continue
            if key in known:
                titles[key] = known[key]
            elif lookups < SEERR_LOOKUP_CAP:
                lookups += 1
                try:
                    titles[key] = get("title lookup", f"/api/v1/{kind}/{tmdb}")
                except Exception:  # row stays "TMDB #id"
                    pass
        return {"raw_count": raw_count, "raw_requests": raw_requests, "raw_pending": raw_pending, "raw_titles": titles}

    def transform(self, raw: dict) -> dict:
        now = _now()
        host = (f"http://{FIXTURE_MEDIA_HOST}:5055" if mode() == "fixture"
                else os.environ["JELLYSEERR_URL"].rstrip("/"))
        titles = raw.get("raw_titles") or {}
        rows: list[tuple[bool, datetime, dict]] = []
        seen: set[int] = set()
        for request in [*(raw.get("raw_pending") or {}).get("results", []),
                        *(raw.get("raw_requests") or {}).get("results", [])]:
            if int(request["id"]) in seen:   # a pending request is in both lists
                continue
            seen.add(int(request["id"]))
            media = request.get("media") or {}
            tmdb = media.get("tmdbId")
            kind = _seerr_kind(request)
            info = titles.get(f"{kind}:{tmdb}") or {}
            title = info.get("title") or info.get("name") or f"TMDB #{tmdb}"
            created = _dt(request["createdAt"])
            by = request.get("requestedBy") or {}
            rows.append((request.get("status") == 1, created, {
                "id": int(request["id"]),
                "kind": kind,
                "tmdb_id": int(tmdb) if tmdb else 0,
                "title": title,
                "year": _seerr_year(info.get("releaseDate") or info.get("firstAirDate")),
                "requested_by": _seerr_name(by),
                "status_text": _seerr_status_text(request),
                "when": _ago(created, now),
                "href": f"{host}/{kind}/{tmdb}",
                "poster": f"tmdb:{info['posterPath']}" if info.get("posterPath") else None,
                "item_key": f"tmdb:{tmdb}" if tmdb else None,
                # Remove (2026-10-08): Sonarr finds a series by its TVDB id when the hub stops its search (TV only).
                **({"tvdb_id": int(media["tvdbId"]) if str(media.get("tvdbId") or "").isdigit() else None}
                   if kind == "tv" else {}),
                # WP-RQ1 (2026-10-22): what the requester chose (Seerr's stored arr profile id, null = the server's
                # default; TV: the season numbers) and who asked (their Seerr user id), for Approve / Decline.
                "profile_id": _seerr_int(request.get("profileId")),
                **({"seasons": _seerr_seasons(request)} if kind == "tv" else {}),
                "requested_by_id": _seerr_int(by.get("id")),
                "requested_by_jf": _seerr_jf(by),   # JY-230: the owner word on the Requests page
            }))
        rows.sort(key=lambda r: r[1], reverse=True)    # newest first ...
        rows.sort(key=lambda r: not r[0])              # ... then pending first (stable)
        # WP-RQ1: every pending row is kept; the cap applies to the rest
        n_pending = sum(1 for r in rows if r[0])
        requests_out = [r[2] for r in rows][:n_pending + SEERR_ROW_LIMIT]

        count = raw.get("raw_count") or {}
        counts = {k: int(count.get(k) or 0)
                  for k in ("pending", "approved", "available", "declined", "total")}
        counts["available"] += int(count.get("completed") or 0)   # Seerr v3 splits Completed out of available
        pending = [r for r in requests_out if r["status_text"] == "Pending"]
        open_requests = counts["pending"] or counts["approved"]
        return {
            "summary": (f"{counts['pending']} pending · {counts['approved']} approved"
                        if open_requests else "No open requests"),
            "secondary": pending[0]["title"] if pending else "",
            "counts": counts,
            "requests": requests_out,
        }
