"""Radarr + Sonarr (+ optional Prowlarr stats): arrivals, upgrades, this week, the queue,
disk space, library counts and the titles below their quality cutoff (below cutoff), plus the last library search
and each title's size on disk (P1a, 2026-10-22)."""

from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from connectors.base import Connector, home_tz, log, partial_note
from connectors.feeds._common import GIB, _ago, _dt, _duration_words, _now
from connectors.feeds._http import http_json, session


ARR_WINDOW_DAYS = 7
ARR_LIMIT = 20
# (app, url var, key var) — each app is fetched independently
ARR_APPS = (("radarr", "RADARR_URL", "RADARR_API_KEY"), ("sonarr", "SONARR_URL", "SONARR_API_KEY"))
# Library counts (WP-S3, 2026-10-06): fetched after an app's main calls succeed; a failed
# count call nulls only that app's counts object. Queued reuses the queue already fetched.
ARR_COUNT_ENDPOINTS = {
    "radarr": (("raw_radarr_movie", "/api/v3/movie", {}),),
    "sonarr": (("raw_sonarr_series", "/api/v3/series", {}),
               ("raw_sonarr_missing", "/api/v3/wanted/missing", {"pageSize": 1, "monitored": "true"})),
}
# Upgrades (F4a, 2026-10-12): "cutoff unmet" — titles whose file on disk is below the quality
# profile's cutoff — plus the profile list (qualityProfileId -> cutoff name, `want`). Partial-ok:
# a failed cutoff call nulls only that app's list (partial_errors "<app>_upgrades"); a failed
# profile call only nulls `want`. One page, sorted by title, keeps the 120 s loop cheap.
ARR_UPGRADE_PAGE = 100
_CUTOFF_PAGE = {"page": 1, "pageSize": ARR_UPGRADE_PAGE, "monitored": "true", "sortDirection": "ascending"}
ARR_UPGRADE_ENDPOINTS = {
    "radarr": (("raw_radarr_cutoff", "/api/v3/wanted/cutoff",
                {**_CUTOFF_PAGE, "sortKey": "movieMetadata.sortTitle"}),
               ("raw_radarr_qualityprofile", "/api/v3/qualityprofile", {})),
    "sonarr": (("raw_sonarr_cutoff", "/api/v3/wanted/cutoff",
                {**_CUTOFF_PAGE, "sortKey": "series.sortTitle",
                 "includeSeries": "true", "includeEpisodeFile": "true"}),
               ("raw_sonarr_qualityprofile", "/api/v3/qualityprofile", {})),
}
# Last search (WP-U1, 2026-10-21): each app's recent command list (`GET /api/v3/command`, one small call per app,
# partial-ok: a failure only leaves that app out) -> its newest whole-library upgrade / missing search, so the hub can
# say what the last "Search upgrades" actually found ("1 searched · 0 downloaded").
ARR_COMMAND_PATH = "/api/v3/command"
LAST_SEARCH = {"CutoffUnmetMoviesSearch": "upgrades", "CutoffUnmetEpisodeSearch": "upgrades",
               "MissingMoviesSearch": "missing", "MissingEpisodeSearch": "missing"}
# Prowlarr is optional: env unset or the call failing -> `prowlarr: null`, the run stays ok.
# JY-143 (2026-10-24): `/api/v1/indexerstats` is cumulative unless it gets startDate / endDate (verified live), so the
# call asks for the last ARR_WINDOW_DAYS: a failed grab ages out and the hub's amber clears.
STATS_TS = "%Y-%m-%dT%H:%M:%SZ"
PROWLARR_ENV = ("PROWLARR_URL", "PROWLARR_API_KEY")
PROWLARR_STATS = (("grabs", "numberOfGrabs"), ("queries", "numberOfQueries"),
                  ("failed_grabs", "numberOfFailedGrabs"), ("failed_queries", "numberOfFailedQueries"))


def _records(payload) -> list[dict]:
    """v3 history/queue are paged ({records: [...]}); calendar/diskspace are bare lists."""
    return (payload.get("records", []) if isinstance(payload, dict) else payload) or []


def _upgrade_text(record: dict) -> str:
    quality = (record.get("quality") or {}).get("quality") or {}
    name, res = str(quality.get("name") or ""), int(quality.get("resolution") or 0)
    if res >= 2160:
        return "Upgraded to 4K"
    if name.lower().startswith("bluray"):
        return "Upgraded to Blu-ray"
    return f"Upgraded to {res}p" if res else "Upgraded"


def _episode_code(season, number) -> str | None:
    if season is None:
        return None
    return f"S{int(season):02d}" + (f"E{int(number):02d}" if number is not None else "")


def _episode_title(series: str, episode: dict) -> str:
    code = _episode_code(episode.get("seasonNumber"), episode.get("episodeNumber"))
    return " · ".join(p for p in (series, code, episode.get("title")) if p)


def _arr_ref(app: str, record: dict, movie: bool = False) -> str | None:
    """`radarr:<movieId>` / `sonarr:<seriesId>` for the hub's /img proxy (episode and
    season rows use the series id). Nested movie/series wins, the flat id is the
    fallback; `movie=True` marks a Radarr calendar row, whose own id is the movie id."""
    if app == "radarr":
        art = (record.get("movie") or {}).get("id") or record.get("movieId") or (record.get("id") if movie else None)
    else:
        art = (record.get("series") or {}).get("id") or record.get("seriesId")
    return f"{app}:{art}" if art else None


def _arr_key(app: str, record: dict, movie: bool = False) -> str | None:
    """`tmdb:<tmdbId>` (Radarr) / `tvdb:<tvdbId>` (Sonarr) from the nested movie/series
    object, or from the record itself for a Radarr calendar row (`movie=True`)."""
    if app == "radarr":
        tmdb = (record.get("movie") or (record if movie else {})).get("tmdbId")
        return f"tmdb:{tmdb}" if tmdb else None
    tvdb = (record.get("series") or {}).get("tvdbId")
    return f"tvdb:{tvdb}" if tvdb else None


def _timeleft(text) -> str:
    """Servarr 'd.hh:mm:ss' / 'hh:mm:ss' -> '12m' / '1h 05m' (blank when unknown)."""
    try:
        days, _, clock = str(text).rpartition(".")
        h, m, _s = (int(p) for p in clock.split(":"))
        minutes = (int(days or 0) * 24 + h) * 60 + m
    except Exception:
        return ""
    return _duration_words(max(minutes, 1))


class Arr(Connector):
    """Radarr + Sonarr: what arrived / was upgraded this week, what's due, the
    download queue and disk space. One app down is data (app_errors), not a failure."""

    id = "arr"
    requires_env = ("RADARR_URL", "RADARR_API_KEY", "SONARR_URL", "SONARR_API_KEY")

    @staticmethod
    def endpoints(app: str, now: datetime) -> list[tuple[str, str, dict]]:
        since = (now.astimezone(timezone.utc) - timedelta(days=ARR_WINDOW_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
        start = now.astimezone(home_tz()).date()  # the household's today (C-08)
        end = start + timedelta(days=ARR_WINDOW_DAYS)
        hist = {"pageSize": 100, "sortKey": "date", "sortDirection": "descending", "since": since}
        cal = {"start": start.isoformat(), "end": end.isoformat()}
        if app == "radarr":
            extra = {"includeMovie": "true"}
        else:
            extra = {"includeSeries": "true", "includeEpisode": "true"}
            cal["includeSeries"] = "true"
        return [
            (f"raw_{app}_history", "/api/v3/history", {**hist, **extra}),
            (f"raw_{app}_calendar", "/api/v3/calendar", cal),
            (f"raw_{app}_queue", "/api/v3/queue", {"pageSize": 50, **extra}),
            (f"raw_{app}_diskspace", "/api/v3/diskspace", {}),
        ]

    def fetch(self) -> dict:
        client = session()  # one connection per app for the run's ~12 calls (C-05)
        try:
            return self._fetch(client)
        finally:
            client.close()

    def _fetch(self, client) -> dict:
        now = _now()
        raw: dict[str, Any] = {}
        errors: dict[str, str] = {}
        for app, url_var, key_var in ARR_APPS:
            base = os.environ[url_var].rstrip("/")
            headers = {"X-Api-Key": os.environ[key_var]}
            got: dict[str, Any] = {}
            try:
                for key, path, params in self.endpoints(app, now):
                    got[key] = http_json(app, base + path, headers=headers, params=params, session=client)
                raw.update(got)
            except RuntimeError as exc:  # the reason never carries the app URL or key
                errors[app] = exc.reason
                continue
            try:  # counts are partial-ok: a failure here leaves `{app}: null`, nothing else
                for key, path, params in ARR_COUNT_ENDPOINTS[app]:
                    raw[key] = http_json(app, base + path, headers=headers, params=params, session=client)
            except RuntimeError as exc:
                log.warning("arr: %s counts failed (%s)", app, exc.reason)
            for key, path, params in ARR_UPGRADE_ENDPOINTS[app]:  # upgrades: partial-ok too
                try:
                    raw[key] = http_json(app, base + path, headers=headers, params=params, session=client)
                except RuntimeError as exc:
                    log.warning("arr: %s %s failed (%s)", app, key.rsplit("_", 1)[1], exc.reason)
                    if key.endswith("_cutoff"):  # no list: the profile lookup is not needed
                        raw.setdefault("upgrade_errors", {})[app] = exc.reason
                        break
            try:  # WP-U1: the last whole-library search, partial-ok (no note: the hub's line is just absent)
                raw[f"raw_{app}_command"] = http_json(app, base + ARR_COMMAND_PATH, headers=headers, session=client)
            except RuntimeError as exc:
                log.warning("arr: %s command list failed (%s)", app, exc.reason)
        if len(errors) == len(ARR_APPS):
            raise RuntimeError(
                "both apps failed (" + ", ".join(f"{a}: {r}" for a, r in sorted(errors.items())) + ")"
            )
        if errors:
            raw["app_errors"] = errors
        if all(os.environ.get(v) for v in PROWLARR_ENV):
            try:
                raw["raw_prowlarr_indexerstats"] = http_json(
                    "prowlarr", os.environ["PROWLARR_URL"].rstrip("/") + "/api/v1/indexerstats",
                    headers={"X-Api-Key": os.environ["PROWLARR_API_KEY"]}, session=client,
                    params={"startDate": (now - timedelta(days=ARR_WINDOW_DAYS)).astimezone(timezone.utc).strftime(STATS_TS),
                            "endDate": now.astimezone(timezone.utc).strftime(STATS_TS)})
            except RuntimeError as exc:
                log.warning("arr: prowlarr stats failed (%s)", exc.reason)
        return raw

    # ---- counts (WP-S3) ----------------------------------------------------

    @staticmethod
    def _total(payload) -> int:
        """A paged v3 payload's totalRecords (a bare list counts its length)."""
        if isinstance(payload, dict):
            return int(payload.get("totalRecords") or len(payload.get("records") or []))
        return len(payload or [])

    @classmethod
    def _counts(cls, raw: dict) -> tuple[dict | None, dict | None, dict | None]:
        radarr = sonarr = prowlarr = None
        movies = raw.get("raw_radarr_movie")
        if isinstance(movies, list) and "raw_radarr_queue" in raw:
            # Homepage's Radarr semantics (verified against B.'s screenshot 2026-10-06):
            # missing = monitored without a file; wanted = those already released (isAvailable).
            missing = [m for m in movies if m.get("monitored") and not m.get("hasFile")]
            radarr = {"movies": len(movies), "missing": len(missing),
                      "wanted": sum(1 for m in missing if m.get("isAvailable")),
                      "queued": cls._total(raw["raw_radarr_queue"])}
        series = raw.get("raw_sonarr_series")
        if isinstance(series, list) and "raw_sonarr_missing" in raw and "raw_sonarr_queue" in raw:
            sonarr = {"series": len(series), "wanted": cls._total(raw["raw_sonarr_missing"]),
                      "queued": cls._total(raw["raw_sonarr_queue"])}
        for counts, app in ((radarr, "radarr"), (sonarr, "sonarr")):  # F4a: optional key
            if counts is not None and raw.get(f"raw_{app}_cutoff") is not None:
                counts["upgrades"] = cls._total(raw[f"raw_{app}_cutoff"])
        stats = raw.get("raw_prowlarr_indexerstats")
        if isinstance(stats, dict):
            indexers = stats.get("indexers") or []
            prowlarr = {out: sum(int(i.get(src) or 0) for i in indexers) for out, src in PROWLARR_STATS}
            prowlarr["indexers"] = len(indexers)
        return radarr, sonarr, prowlarr

    # ---- transform ---------------------------------------------------------

    @staticmethod
    def _imports(records: list[dict], now: datetime, id_key: str, deleted_event: str, grouped: bool):
        """(arrived, updated) as (datetime, entry) lists. An import is an upgrade
        when flagged (data.isUpgrade) or when the same movie/episode had a file
        deleted 'for an upgrade' at or before the import."""
        cutoff = now - timedelta(days=ARR_WINDOW_DAYS)
        recs = sorted((r for r in records if _dt(r["date"]) >= cutoff),
                      key=lambda r: _dt(r["date"]), reverse=True)
        deletes: dict[Any, list[datetime]] = {}
        for r in recs:
            if r.get("eventType") == deleted_event and "upgrade" in str((r.get("data") or {}).get("reason", "")).lower():
                deletes.setdefault(r.get(id_key), []).append(_dt(r["date"]))

        buckets: dict[bool, dict[Any, list[dict]]] = {False: {}, True: {}}
        for r in recs:  # newest first, so each group's [0] is its newest import
            if r.get("eventType") != "downloadFolderImported":
                continue
            when = _dt(r["date"])
            upgrade = (str((r.get("data") or {}).get("isUpgrade", "")).lower() in ("true", "1")
                       or any(d <= when for d in deletes.get(r.get(id_key), [])))
            if grouped:  # a season's episodes imported together become one line
                key = ((r.get("series") or {}).get("title") or r.get("sourceTitle") or "Unknown",
                       (r.get("episode") or {}).get("seasonNumber"))
            else:
                key = r.get(id_key)
            buckets[upgrade].setdefault(key, []).append(r)

        def entry(group: list[dict], upgrade: bool) -> tuple[datetime, dict]:
            newest = group[0]
            when = _dt(newest["date"])
            if grouped:
                series = (newest.get("series") or {}).get("title") or newest.get("sourceTitle") or "Unknown"
                if len(group) == 1:
                    title, kind = _episode_title(series, newest.get("episode") or {}), "episode"
                else:
                    code = _episode_code((newest.get("episode") or {}).get("seasonNumber"), None)
                    title = " · ".join(p for p in (series, code, f"{len(group)} episodes") if p)
                    kind = "season"
            else:
                title = (newest.get("movie") or {}).get("title") or newest.get("sourceTitle") or "Unknown"
                kind = "movie"
            row = {"title": title, "kind": kind, "when": _ago(when, now), "at": when.isoformat(),
                   "poster": _arr_ref("sonarr" if grouped else "radarr", newest),
                   "item_key": _arr_key("sonarr" if grouped else "radarr", newest)}
            if upgrade:
                row["what"] = _upgrade_text(newest)
            return when, row

        return ([entry(g, False) for g in buckets[False].values()],
                [entry(g, True) for g in buckets[True].values()])

    @staticmethod
    def _this_week(radarr: list[dict], sonarr: list[dict], now: datetime) -> list[dict]:
        tz = home_tz()  # the household's calendar week, not UTC's (C-08)
        today = now.astimezone(tz).date()
        end = today + timedelta(days=ARR_WINDOW_DAYS)
        rows: list[dict] = []
        for m in radarr:
            for field, label in (("digitalRelease", "Digital"), ("physicalRelease", "Disc"),
                                 ("inCinemas", "Cinemas")):
                if not m.get(field):
                    continue
                day = _dt(m[field]).astimezone(tz).date()
                if not today <= day <= end or (label == "Disc" and m.get("hasFile")):
                    continue  # a disc release already on disk is not news
                rows.append({"title": m["title"], "kind": "movie", "date": day.isoformat(), "label": label,
                             "poster": _arr_ref("radarr", m, movie=True),
                             "item_key": _arr_key("radarr", m, movie=True)})
        for e in sonarr:
            stamp = e.get("airDateUtc") or e.get("airDate")
            if not stamp:
                continue
            day = _dt(stamp).astimezone(tz).date()
            if not today <= day <= end:
                continue
            if e.get("episodeNumber") == 1:
                label = "Premiere"
            elif e.get("finaleType") in ("series", "season"):
                label = "Finale"
            else:
                label = ""
            rows.append({"title": _episode_title((e.get("series") or {}).get("title", "Unknown"), e),
                         "kind": "episode", "date": day.isoformat(), "label": label,
                         "poster": _arr_ref("sonarr", e), "item_key": _arr_key("sonarr", e)})
        return sorted(rows, key=lambda r: (r["date"], r["title"]))

    @staticmethod
    def _queue(app: str, records: list[dict]) -> list[dict]:
        rows = []
        for r in records:
            size, left = float(r.get("size") or 0), float(r.get("sizeleft") or 0)
            if app == "radarr":
                title, kind = (r.get("movie") or {}).get("title") or r.get("title") or "Unknown", "movie"
            else:
                series = (r.get("series") or {}).get("title") or r.get("title") or "Unknown"
                if r.get("episode"):
                    title, kind = _episode_title(series, r["episode"]), "episode"
                else:
                    code = _episode_code(r.get("seasonNumber"), None)
                    title, kind = " · ".join(p for p in (series, code) if p), "season"
            rows.append({
                "title": title, "kind": kind,
                "pct": min(100, max(0, round((size - left) / size * 100))) if size else 0,
                "status_text": str(r.get("status") or "queued").capitalize(),
                "time_left": _timeleft(r.get("timeleft")),
                "poster": _arr_ref(app, r), "item_key": _arr_key(app, r),
                # the download client's id (a torrent hash) — joins a qbittorrent row
                "download_id": str(r["downloadId"]).lower() if r.get("downloadId") else None,
            })
        return rows

    @staticmethod
    def _group_words(names: list[str]) -> str | None:
        """A cutoff quality GROUP's members in a few words (WP-U1, 2026-10-21): "WEBRip-1080p, WEBDL-1080p,
        Bluray-1080p" -> "WEB/Bluray 1080p"; "Bluray-2160p, Remux-2160p" -> "Bluray/Remux 2160p". Sources collapse
        (WEBRip / WEBDL -> WEB) per resolution, resolutions in member order; a name without "-<res>p" (SDTV, DVD) stays
        as it is. None for no members."""
        by_res: dict[str, list[str]] = {}
        for name in names:
            m = re.fullmatch(r"(.+?)-(\d{3,4}p)", name)
            src, res = (m.group(1), m.group(2)) if m else (name, "")
            src = "WEB" if src.upper().startswith("WEB") else src
            if src not in by_res.setdefault(res, []):
                by_res[res].append(src)
        return "/".join(" ".join(p for p in ("/".join(srcs), res) if p) for res, srcs in by_res.items()) or None

    @classmethod
    def _cutoff_names(cls, profiles) -> dict[Any, str]:
        """qualityProfileId -> its cutoff in words. The cutoff id names a quality (its name), or a quality group (a
        top-level item with its own id, no `quality`): then its members collapsed (_group_words) - never the group's
        own name ("Default" says nothing; live Sonarr, 2026-10-21) - the group name only when it lists no members."""
        names: dict[Any, str] = {}
        for p in profiles if isinstance(profiles, list) else []:
            for item in p.get("items") or []:
                own = item.get("quality") or {}
                if (own.get("id") if own else item.get("id")) == p.get("cutoff"):
                    if own:
                        name = own.get("name")
                    else:
                        members = [str(q["name"]) for q in ((i.get("quality") or {}) for i in item.get("items") or [])
                                   if q.get("name")]
                        name = cls._group_words(members) or item.get("name")
                    if name:
                        names[p.get("id")] = str(name)
                    break
        return names

    @staticmethod
    def _profile_names(profiles) -> dict[Any, str]:
        """qualityProfileId -> the profile's own name ("1080p"), for the hub's Why? hint (WP-U1)."""
        if not isinstance(profiles, list):
            return {}
        return {p.get("id"): str(p["name"]) for p in profiles if isinstance(p, dict) and p.get("name")}

    @staticmethod
    def _last_search(raw: dict) -> list[dict]:
        """Per app, the newest whole-library upgrade / missing search on its command list (WP-U1, 2026-10-21):
        [{name: upgrades|missing, app, status, ended, message}], Radarr first; an app without one (or whose command
        call failed) is left out. `message` is the app's own summary ("Completed search for 1 episodes. 0 reports
        downloaded."), at most 200 characters."""
        out = []
        for app in ("radarr", "sonarr"):
            cmds = [c for c in raw.get(f"raw_{app}_command") or [] if isinstance(c, dict)
                    and str(c.get("name") or c.get("commandName") or "") in LAST_SEARCH]
            if not cmds:
                continue
            c = max(cmds, key=lambda c: (str(c.get("queued") or c.get("started") or ""), int(c.get("id") or 0)))
            out.append({"name": LAST_SEARCH[str(c.get("name") or c.get("commandName"))], "app": app,
                        "status": str(c.get("status") or "unknown").lower(),
                        "ended": str(c["ended"]) if c.get("ended") else None,
                        "message": str(c.get("message") or "")[:200] or None})
        return out

    @classmethod
    def _upgrades(cls, raw: dict) -> dict:
        """Cutoff-unmet titles: Radarr one row per movie, Sonarr episodes grouped per series.
        An app whose cutoff list is unavailable (down, or the call failed) is null."""
        def quality(file) -> dict:
            return ((file or {}).get("quality") or {}).get("quality") or {}

        radarr = sonarr = None
        if raw.get("raw_radarr_cutoff") is not None:
            want = cls._cutoff_names(raw.get("raw_radarr_qualityprofile"))
            profile = cls._profile_names(raw.get("raw_radarr_qualityprofile"))
            # Radarr's cutoff records carry movieFileId but no movieFile (verified live, Radarr 6.4):
            # the held quality comes from the library list fetched for the counts, joined on id.
            files = {m.get("id"): m.get("movieFile") for m in raw.get("raw_radarr_movie") or []
                     if isinstance(m, dict) and m.get("movieFile")}
            radarr = sorted((
                {"item_key": _arr_key("radarr", m, movie=True), "title": m.get("title") or "Unknown",
                 "year": m.get("year") or None, "arr_id": m.get("id"),
                 "have": quality(m.get("movieFile") or files.get(m.get("id"))).get("name"), "want": want.get(m.get("qualityProfileId")),
                 "profile": profile.get(m.get("qualityProfileId")), "poster": _arr_ref("radarr", m, movie=True)}
                for m in _records(raw["raw_radarr_cutoff"])), key=lambda r: (r["title"].casefold(), r["arr_id"] or 0))
        if raw.get("raw_sonarr_cutoff") is not None:
            want = cls._cutoff_names(raw.get("raw_sonarr_qualityprofile"))
            profile = cls._profile_names(raw.get("raw_sonarr_qualityprofile"))
            groups: dict[Any, list[dict]] = {}
            for e in _records(raw["raw_sonarr_cutoff"]):
                groups.setdefault((e.get("series") or {}).get("id") or e.get("seriesId"), []).append(e)
            sonarr = []
            for sid, eps in groups.items():
                series = next((e["series"] for e in eps if e.get("series")), {})
                held = [q for q in (quality(e.get("episodeFile")) for e in eps) if q.get("name")]
                lowest = min(held, key=lambda q: (int(q.get("resolution") or 0), str(q["name"])), default={})
                first = min(eps, key=lambda e: (e.get("seasonNumber") or 0, e.get("episodeNumber") or 0))
                sonarr.append({
                    "item_key": _arr_key("sonarr", {"series": series}), "title": series.get("title") or "Unknown",
                    "arr_id": sid, "episodes": len(eps), "have": lowest.get("name"),
                    "want": want.get(series.get("qualityProfileId")),
                    "profile": profile.get(series.get("qualityProfileId")),
                    "sample": _episode_code(first.get("seasonNumber"), first.get("episodeNumber")),
                    "episode_id": first.get("id") if isinstance(first.get("id"), int) else None,
                    "poster": _arr_ref("sonarr", {"series": series, "seriesId": sid})})
            sonarr.sort(key=lambda r: (r["title"].casefold(), r["arr_id"] or 0))
        totals = {"movies": cls._total(raw["raw_radarr_cutoff"]) if radarr is not None else 0,
                  "episodes": cls._total(raw["raw_sonarr_cutoff"]) if sonarr is not None else 0,
                  "series": len(sonarr or [])}
        return {"radarr": radarr, "sonarr": sonarr, "totals": totals, "last_search": cls._last_search(raw)}

    @staticmethod
    def _library_sizes(raw: dict) -> dict:
        """Per-title size on disk (P1a, 2026-10-22) for the hub's Free space page, from the library lists the counts
        already fetch (no extra call): Radarr movies with a file (`sizeOnDisk`, else `statistics.sizeOnDisk`, else the
        movie file's `size`), Sonarr series with episodes on disk (`statistics.sizeOnDisk`; `ended` from the series'
        `ended`, else `status` "ended"). Biggest first; an app whose list was not fetched is null."""
        def size(*values) -> int:
            for v in values:
                try:
                    n = int(v or 0)
                except (TypeError, ValueError):
                    continue
                if n > 0:
                    return n
            return 0

        def num(v) -> int | None:
            return v if isinstance(v, int) and not isinstance(v, bool) and v > 0 else None

        def biggest(rows) -> list[dict]:
            return sorted(rows, key=lambda r: (-r["size_bytes"], r["title"].casefold()))

        radarr = sonarr = None
        movies = raw.get("raw_radarr_movie")
        if isinstance(movies, list):
            radarr = biggest(
                {"tmdb_id": num(m.get("tmdbId")), "title": str(m.get("title") or "Unknown"), "year": num(m.get("year")),
                 "size_bytes": n}
                for m in movies if isinstance(m, dict) and m.get("hasFile")
                and (n := size(m.get("sizeOnDisk"), (m.get("statistics") or {}).get("sizeOnDisk"),
                               (m.get("movieFile") or {}).get("size"))))
        series = raw.get("raw_sonarr_series")
        if isinstance(series, list):
            sonarr = biggest(
                {"tvdb_id": num(s.get("tvdbId")), "tmdb_id": num(s.get("tmdbId")),
                 "title": str(s.get("title") or "Unknown"), "size_bytes": n,
                 "ended": s.get("ended") is True or str(s.get("status") or "").lower() == "ended"}
                for s in series if isinstance(s, dict) and (n := size((s.get("statistics") or {}).get("sizeOnDisk"))))
        return {"radarr": radarr, "sonarr": sonarr}

    def transform(self, raw: dict) -> dict:
        now = _now()
        arrived: list[tuple[datetime, dict]] = []
        updated: list[tuple[datetime, dict]] = []
        for app, id_key, deleted, grouped in (("radarr", "movieId", "movieFileDeleted", False),
                                              ("sonarr", "episodeId", "episodeFileDeleted", True)):
            a, u = self._imports(_records(raw.get(f"raw_{app}_history")), now, id_key, deleted, grouped)
            arrived += a
            updated += u
        arrived_rows = [row for _, row in sorted(arrived, key=lambda p: p[0], reverse=True)]
        updated_rows = [row for _, row in sorted(updated, key=lambda p: p[0], reverse=True)]

        # Already arrived this week -> not also listed under "This week". Sonarr keys are
        # per series, so a row only counts as arrived when its title starts with the arrived
        # row's (a season group "Show · S02 · 3 episodes" matches its S02 episodes only).
        arrived_prefix = [(r["item_key"], re.sub(r" · \d+ episodes$", "", r["title"]))
                          for r in arrived_rows if r.get("item_key")]
        this_week = [r for r in self._this_week(_records(raw.get("raw_radarr_calendar")),
                                                _records(raw.get("raw_sonarr_calendar")), now)
                     if not any(r["item_key"] == k and r["title"].startswith(pre)
                                for k, pre in arrived_prefix)]
        downloading = (self._queue("radarr", _records(raw.get("raw_radarr_queue")))
                       + self._queue("sonarr", _records(raw.get("raw_sonarr_queue"))))

        disk, seen = [], set()
        for d in _records(raw.get("raw_radarr_diskspace")) + _records(raw.get("raw_sonarr_diskspace")):
            total, free = int(d.get("totalSpace") or 0), int(d.get("freeSpace") or 0)
            # One NAS volume shows up under several mount paths: dedupe on the sizes (to the GiB).
            volume = (round(total / GIB), round(free / GIB))
            if volume in seen or not total:
                continue
            seen.add(volume)
            disk.append({"path": d["path"], "free_gb": round(free / GIB, 1),
                         "total_gb": round(total / GIB, 1),
                         "pct_used": round((total - free) / total * 100)})

        data = {
            "summary": (f"{len(arrived_rows)} arrived this week · {len(downloading)} downloading"
                        if arrived_rows else "Nothing new this week"),
            "secondary": (arrived_rows[0]["title"] if arrived_rows
                          else this_week[0]["title"] if this_week else ""),
            "arrived": arrived_rows[:ARR_LIMIT],
            "updated": updated_rows[:ARR_LIMIT],
            "this_week": this_week[:ARR_LIMIT],
            "downloading": downloading[:ARR_LIMIT],
            "disk": disk[:ARR_LIMIT],
        }
        data["radarr"], data["sonarr"], data["prowlarr"] = self._counts(raw)
        data["upgrades"] = self._upgrades(raw)
        data["library_sizes"] = self._library_sizes(raw)   # P1a (2026-10-22): the hub's Free space page
        if raw.get("app_errors"):
            data["app_errors"] = dict(raw["app_errors"])
            for app, why in sorted(raw["app_errors"].items()):
                partial_note(data, app, why)
        for app, why in sorted((raw.get("upgrade_errors") or {}).items()):
            partial_note(data, f"{app}_upgrades", why)
        return data
