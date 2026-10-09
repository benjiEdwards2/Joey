"""Jellyfin: now playing, up next, latest, counts, watch history, the library lists and
Georgina's view."""

from __future__ import annotations

import os
from datetime import datetime, timedelta

from connectors.base import Connector, home_tz, log, mode, partial_note
from connectors.feeds._common import _ago, _dt, _now
from connectors.feeds._http import http_json, session


TICKS_PER_MINUTE = 600_000_000  # Jellyfin runtime/position ticks are 100 ns units
TICKS_PER_HOUR = TICKS_PER_MINUTE * 60
HISTORY_FETCH_LIMIT = 500  # watched items pulled per sweep
FIXTURE_HER_USER = "georgina"  # fixture mode never reads JELLYFIN_USER_HER
HISTORY_RECENT = 20
HISTORY_TOP = 10           # rows in each most-played / on-this-day list
UP_NEXT_LIMIT = 8
LIBRARY_FETCH_LIMIT = 2000  # whole-library movie/series lists (F3a)
LIBRARY_EVERY_S_DEFAULT = 900  # library lists are re-fetched at most this often (C-18)

# Jellyfin's PlayState.PlayMethod -> a word, never a colour.
PLAY_METHODS = {"DirectPlay": "Direct play", "DirectStream": "Direct stream", "Transcode": "Transcoding"}


def _media_title(item: dict) -> str:
    """'Show · S02E05 · Episode name' for an episode; the plain name otherwise."""
    if item.get("Type") == "Episode" and item.get("SeriesName"):
        season, number = item.get("ParentIndexNumber"), item.get("IndexNumber")
        code = f"S{int(season):02d}E{int(number):02d}" if season is not None and number is not None else None
        return " · ".join(p for p in (item["SeriesName"], code, item["Name"]) if p)
    return item["Name"]


def _item_kind(item: dict) -> str:
    return "episode" if item.get("Type") == "Episode" else "movie"


def _jf_art(item: dict) -> str | None:
    """Jellyfin item id whose art represents this item: an episode shows its series'
    poster (fallback its own id). Refs are `jf:<id>` / `jfb:<id>` — the hub's /img proxy."""
    if item.get("Type") == "Episode" and item.get("SeriesId"):
        return item["SeriesId"]
    return item.get("Id")


def _jf_ref(prefix: str, item: dict) -> str | None:
    art = _jf_art(item)
    return f"{prefix}:{art}" if art else None


def _jf_key(item: dict) -> str | None:
    """Stable identity for ratings/diary (`item_key`): a movie is `tmdb:<id>` (else
    `jf:<ItemId>`); an episode is its SERIES — the payload carries no series provider
    id, so `jf:<SeriesId>` (episodes without a SeriesId fall back to their own id)."""
    if item.get("Type") == "Episode" and item.get("SeriesId"):
        return f"jf:{item['SeriesId']}"
    tmdb = (item.get("ProviderIds") or {}).get("Tmdb")
    if tmdb:
        return f"tmdb:{tmdb}"
    return f"jf:{item['Id']}" if item.get("Id") else None


def _jf_levels(item: dict) -> dict:
    """Per-level rating keys + numbers for a row (F5). `item_key` stays the show key for
    episodes; these let the hub rate at show / season / episode level. Movies: all null."""
    if item.get("Type") != "Episode":
        return {"show_key": None, "season_key": None, "episode_key": None,
                "season": None, "episode": None, "show_title": None}

    def num(v):
        return v if isinstance(v, int) and not isinstance(v, bool) else None
    return {"show_key": f"jf:{item['SeriesId']}" if item.get("SeriesId") else None,
            "season_key": f"jf:{item['SeasonId']}" if item.get("SeasonId") else None,
            "episode_key": f"jf:{item['Id']}" if item.get("Id") else None,
            "season": num(item.get("ParentIndexNumber")), "episode": num(item.get("IndexNumber")),
            "show_title": item.get("SeriesName")}


def _play_method(session: dict) -> str:
    method = PLAY_METHODS.get(session.get("PlayState", {}).get("PlayMethod"))
    if method:
        return method
    # Older servers omit PlayMethod; a TranscodingInfo block still says it.
    return "Transcoding" if session.get("TranscodingInfo") else "Direct play"


class Jellyfin(Connector):
    id = "jellyfin"
    requires_env = ("JELLYFIN_URL", "JELLYFIN_API_KEY")  # JELLYFIN_USER is optional

    ITEM_FIELDS = "DateCreated,SeriesName,SeriesId,SeasonId,ParentIndexNumber,IndexNumber,ProviderIds"
    MOVIE_FIELDS = "DateCreated,ProviderIds,Genres,ProductionYear,Overview"
    SHOW_FIELDS = "DateCreated,ProviderIds,Genres,ProductionYear,Status,RecursiveItemCount,Overview"

    @classmethod
    def _library_params(cls, kind: str) -> dict:
        return {"IncludeItemTypes": kind, "Recursive": "true", "SortBy": "SortName",
                "SortOrder": "Ascending", "Limit": LIBRARY_FETCH_LIMIT,
                "Fields": cls.MOVIE_FIELDS if kind == "Movie" else cls.SHOW_FIELDS}

    @staticmethod
    def pick_user(users: list[dict], preferred: str | None) -> dict:
        """JELLYFIN_USER by name, else the first administrator, else the first user."""
        if not users:
            raise RuntimeError("Jellyfin returned no users")
        if preferred:
            for user in users:
                if user.get("Name") == preferred:
                    return user
        for user in users:
            if user.get("Policy", {}).get("IsAdministrator"):
                return user
        return users[0]

    @staticmethod
    def pick_her_user(users: list[dict], name: str | None) -> dict | None:
        """Georgina's account by EXACT display name, else None. Never falls back to
        the administrator: her view must not show B.'s data by accident."""
        if not name:
            return None
        return next((u for u in users if u.get("Name") == name and u.get("Id")), None)

    @staticmethod
    def _her_name() -> str | None:
        """JELLYFIN_USER_HER in live mode; fixture mode never reads the real env."""
        if mode() == "fixture":
            return FIXTURE_HER_USER
        return os.environ.get("JELLYFIN_USER_HER") or None

    def fetch(self) -> dict:
        client = session()  # one connection for the run's 10-15 calls (C-05)
        try:
            return self._fetch(client)
        finally:
            client.close()

    def _fetch(self, client) -> dict:
        base = os.environ["JELLYFIN_URL"].rstrip("/")
        headers = {"Authorization": f"MediaBrowser Token={os.environ['JELLYFIN_API_KEY']}"}

        def get(label: str, path: str, params: dict | None = None):
            return http_json(f"Jellyfin {label}", base + path, headers=headers, params=params, session=client)

        skipped: dict[str, str] = {}

        def optional(label: str, path: str, params: dict | None = None):
            """Partial-ok (C-09): an optional call that fails is left out of `raw` (its data key is
            then absent / `her` null), logged with the sanitised reason and noted under
            `partial_errors` (C-10); the run stays ok."""
            try:
                return get(label, path, params)
            except RuntimeError as exc:
                log.warning("jellyfin: skipped, %s", exc)
                skipped[label] = exc.reason
                return None

        users = get("users", "/Users")
        uid = self.pick_user(users, os.environ.get("JELLYFIN_USER")).get("Id")
        if not uid:
            raise RuntimeError("Jellyfin user has no Id")
        fields = {"Fields": self.ITEM_FIELDS}
        history_params = {
            "Filters": "IsPlayed", "SortBy": "DatePlayed", "SortOrder": "Descending",
            "Recursive": "true", "IncludeItemTypes": "Movie,Episode",
            "Fields": "UserData,RunTimeTicks,SeriesName,SeriesId,SeasonId,ParentIndexNumber,IndexNumber,ProductionYear,ProviderIds",
            "Limit": HISTORY_FETCH_LIMIT}
        raw = {
            "raw_users": users,
            "raw_system": get("system", "/System/Info/Public"),
            "raw_sessions": get("sessions", "/Sessions"),
            "raw_resume": get("resume", f"/Users/{uid}/Items/Resume",
                              {"Limit": 10, "MediaTypes": "Video", **fields}),
            "raw_nextup": get("next up", "/Shows/NextUp", {"UserId": uid, "Limit": 10, **fields}),
            "raw_latest": get("latest", f"/Users/{uid}/Items/Latest", {"Limit": 5, **fields}),
            "raw_counts": get("counts", "/Items/Counts", {"UserId": uid}),
            "raw_history": get("history", f"/Users/{uid}/Items", history_params),
        }
        # Georgina's view (2026-10-05): only when JELLYFIN_USER_HER names an existing user.
        # Her block needs resume + next up + history; any of them missing makes `her` null.
        her = self.pick_her_user(users, self._her_name())
        # Library lists (F3a): Limit=2000 GETs, two (four with her). Since C-18 they run at most
        # every JELLYFIN_LIBRARY_EVERY_S; in between the previous envelope's lists are reused.
        # Optional, like her view: a failure leaves the key out instead of failing the feed (C-09).
        cache = self._library_cache(with_her=bool(her))
        optional_calls = []
        if cache is None:
            raw["library_fetched_at"] = _now().isoformat(timespec="seconds")
            optional_calls += [
                ("raw_movies", "movies", f"/Users/{uid}/Items", self._library_params("Movie")),
                ("raw_shows", "shows", f"/Users/{uid}/Items", self._library_params("Series")),
            ]
        else:
            raw["library_cache"] = cache
        if her:
            hid = her["Id"]
            optional_calls += [
                ("raw_her_resume", "her resume", f"/Users/{hid}/Items/Resume",
                 {"Limit": 10, "MediaTypes": "Video", **fields}),
                ("raw_her_nextup", "her next up", "/Shows/NextUp", {"UserId": hid, "Limit": 10, **fields}),
                ("raw_her_history", "her history", f"/Users/{hid}/Items", history_params),
            ]
            if cache is None:
                optional_calls += [
                    ("raw_her_movies", "her movies", f"/Users/{hid}/Items", self._library_params("Movie")),
                    ("raw_her_shows", "her shows", f"/Users/{hid}/Items", self._library_params("Series")),
                ]
        for key, label, path, params in optional_calls:
            got = optional(label, path, params)
            if got is not None:
                raw[key] = got
        if not her and os.environ.get("JELLYFIN_USER_HER"):
            log.info("jellyfin: her user not found")
        if skipped:
            raw["errors"] = skipped
        return raw

    def _library_cache(self, with_her: bool) -> dict | None:
        """The previous envelope's library lists (+ her two when `with_her`) when they were
        fetched less than JELLYFIN_LIBRARY_EVERY_S ago (C-18), else None: fetch them now.
        All or nothing: a list missing last time (a failed call) means fetch them all."""
        try:
            every = int(os.environ.get("JELLYFIN_LIBRARY_EVERY_S") or LIBRARY_EVERY_S_DEFAULT)
        except ValueError:
            every = LIBRARY_EVERY_S_DEFAULT
        prev = (self._previous() or {}).get("data") or {}
        her = prev.get("her") or {}
        lists = {"movies": prev.get("movies"), "shows": prev.get("shows")}
        if with_her:
            lists.update(her_movies=her.get("movies"), her_shows=her.get("shows"))
        stamp = prev.get("library_fetched_at")
        if every <= 0 or not stamp or any(rows is None for rows in lists.values()):
            return None
        try:
            age = (_now() - _dt(stamp)).total_seconds()
        except (TypeError, ValueError):
            return None
        return {"fetched_at": stamp, **lists} if 0 <= age < every else None

    @staticmethod
    def _library_row(item: dict) -> dict:
        """Fields shared by movie and show library rows."""
        user = item.get("UserData") or {}
        rating = item.get("CommunityRating")
        return {
            "title": item["Name"],
            "year": item.get("ProductionYear"),
            "jf_id": item["Id"],
            "poster": _jf_ref("jf", item), "backdrop": _jf_ref("jfb", item),
            "played": bool(user.get("Played")),
            "last_played_at": user.get("LastPlayedDate"),
            "added_at": item.get("DateCreated"),
            "community_rating": round(float(rating), 1) if rating is not None else None,
            "genres": list(item.get("Genres") or [])[:3],
        }

    @classmethod
    def _movies(cls, payload: dict) -> list[dict]:
        rows = []
        for item in (payload or {}).get("Items", []):
            ticks = item.get("RunTimeTicks")
            rows.append({**cls._library_row(item), "item_key": _jf_key(item),
                         "runtime_min": int(ticks) // TICKS_PER_MINUTE if ticks else None})
        return rows

    @classmethod
    def _shows(cls, payload: dict) -> list[dict]:
        rows = []
        for item in (payload or {}).get("Items", []):
            ids = item.get("ProviderIds") or {}
            key = (f"tmdb:{ids['Tmdb']}" if ids.get("Tmdb")
                   else f"tvdb:{ids['Tvdb']}" if ids.get("Tvdb") else f"jf:{item['Id']}")
            rows.append({**cls._library_row(item), "item_key": key,
                         "status_word": {"Continuing": "Continuing", "Ended": "Ended"}.get(
                             item.get("Status"), "Unknown"),
                         "episodes": int(item.get("RecursiveItemCount") or 0),
                         "unplayed": int((item.get("UserData") or {}).get("UnplayedItemCount") or 0)})
        return rows

    @staticmethod
    def _history(items: list[dict], now: datetime) -> dict:
        """Watch history for the history page: windows, hours, top shows/movies, on-this-day."""
        week, month = now - timedelta(days=7), now - timedelta(days=30)
        tz = home_tz()  # "on this day" is the household's calendar day, not UTC's (C-08)
        today = now.astimezone(tz)
        played = []  # (item, last-played datetime, runtime hours, plays)
        for item in items:
            stamp = (item.get("UserData") or {}).get("LastPlayedDate")
            if not stamp:
                continue
            plays = int((item.get("UserData") or {}).get("PlayCount") or 1)
            played.append((item, _dt(stamp), int(item.get("RunTimeTicks") or 0) / TICKS_PER_HOUR, plays))
        played.sort(key=lambda p: p[1], reverse=True)

        shows: dict[str, dict] = {}
        for item, _, hours, plays in played:
            if _item_kind(item) == "episode" and item.get("SeriesName"):
                show = shows.setdefault(item["SeriesName"], {"title": item["SeriesName"], "episodes": 0, "hours": 0.0,
                                                             "poster": _jf_ref("jf", item),
                                                             "item_key": _jf_key(item)})
                show["episodes"] += 1
                show["hours"] += hours * plays
        movies = sorted(({"title": item["Name"], "plays": plays, "poster": _jf_ref("jf", item),
                          "item_key": _jf_key(item)} for item, _, _, plays in played
                         if _item_kind(item) == "movie" and plays >= 1),
                        key=lambda m: (-m["plays"], m["title"]))
        return {
            "recent": [{"title": _media_title(item), "kind": _item_kind(item),
                        "watched_at": item["UserData"]["LastPlayedDate"], "when": _ago(dt, now),
                        "poster": _jf_ref("jf", item), "item_key": _jf_key(item),
                        "jf_id": item.get("Id"), **_jf_levels(item)}
                       for item, dt, _, _ in played[:HISTORY_RECENT]],
            "week_count": sum(1 for _, dt, _, _ in played if dt >= week),
            "month_count": sum(1 for _, dt, _, _ in played if dt >= month),
            "hours_total": round(sum(h * plays for _, _, h, plays in played), 1),
            "hours_month": round(sum(h for _, dt, h, _ in played if dt >= month), 1),
            "most_played_shows": [{**s, "hours": round(s["hours"], 1)} for s in sorted(
                shows.values(), key=lambda s: (-s["episodes"], s["title"]))[:HISTORY_TOP]],
            "most_played_movies": movies[:HISTORY_TOP],
            "on_this_day": [{"title": _media_title(item), "kind": _item_kind(item), "years_ago": today.year - d.year,
                             "poster": _jf_ref("jf", item), "item_key": _jf_key(item),
                             "jf_id": item.get("Id")}
                            for item, d in ((item, dt.astimezone(tz)) for item, dt, _, _ in played)
                            if (d.month, d.day) == (today.month, today.day) and d.year < today.year][:HISTORY_TOP],
        }

    @staticmethod
    def _up_next(resume: dict, nextup: dict) -> list[dict]:
        """Resume items first, then next-episode suggestions not already resumable."""
        up_next, seen = [], set()
        for item in resume["Items"]:
            runtime = int(item.get("RunTimeTicks") or 0)
            position = int(item.get("UserData", {}).get("PlaybackPositionTicks") or 0)
            left = max(0, runtime - position) // TICKS_PER_MINUTE
            seen.add(item.get("Id"))
            up_next.append({
                "title": _media_title(item),
                "kind": "episode" if item.get("Type") == "Episode" else "movie",
                "remaining_text": f"{left} min left",
                "poster": _jf_ref("jf", item), "backdrop": _jf_ref("jfb", item),
                "item_key": _jf_key(item), "jf_id": item.get("Id"), **_jf_levels(item),
            })
        for item in nextup["Items"]:
            if item.get("Id") in seen:  # already resumable — don't list twice
                continue
            up_next.append({"title": _media_title(item), "kind": "episode",
                            "remaining_text": "Next episode",
                            "poster": _jf_ref("jf", item), "backdrop": _jf_ref("jfb", item),
                            "item_key": _jf_key(item), "jf_id": item.get("Id"), **_jf_levels(item)})
        return up_next[:UP_NEXT_LIMIT]

    def _her_block(self, raw: dict) -> dict | None:
        """Georgina's up next + history, or None when her keys are absent."""
        if not all(k in raw for k in ("raw_her_resume", "raw_her_nextup", "raw_her_history")):
            return None
        user = self.pick_her_user(raw.get("raw_users") or [], self._her_name())
        block = {"user": (user or {}).get("Name") or "her",
                 "up_next": self._up_next(raw["raw_her_resume"], raw["raw_her_nextup"]),
                 "history": self._history(raw["raw_her_history"].get("Items", []), _now())}
        cache = raw.get("library_cache") or {}
        if "raw_her_movies" in raw:
            block["movies"] = self._movies(raw["raw_her_movies"])
        elif cache.get("her_movies") is not None:
            block["movies"] = cache["her_movies"]
        if "raw_her_shows" in raw:
            block["shows"] = self._shows(raw["raw_her_shows"])
        elif cache.get("her_shows") is not None:
            block["shows"] = cache["her_shows"]
        return block

    def transform(self, raw: dict) -> dict:
        now_playing = []
        for session in raw["raw_sessions"]:
            item = session.get("NowPlayingItem")
            if not item:
                continue
            runtime = int(item.get("RunTimeTicks") or 0)
            position = int(session.get("PlayState", {}).get("PositionTicks") or 0)
            now_playing.append({
                "title": _media_title(item),
                "user": session.get("UserName", "someone"),
                "progress_pct": min(100, round(position / runtime * 100)) if runtime else 0,
                "play_method": _play_method(session),
                "poster": _jf_ref("jf", item),
                "backdrop": _jf_ref("jfb", item),
                "item_key": _jf_key(item),
                "jf_id": item.get("Id"),
                **_jf_levels(item),
            })

        up_next = self._up_next(raw["raw_resume"], raw["raw_nextup"])

        latest = [
            {"title": i["Name"], "added_at": i["DateCreated"], "type": i["Type"], "poster": _jf_ref("jf", i),
             "item_key": _jf_key(i), "jf_id": i.get("Id")}
            for i in raw["raw_latest"]
        ]
        counts = raw["raw_counts"]
        first = now_playing[0] if now_playing else None
        if first:
            secondary = f"{first['title']} · {first['user']} · {first['play_method']}"
        else:
            secondary = up_next[0]["title"] if up_next else "Nothing up next"
        library_lists = {}
        cache = raw.get("library_cache") or {}  # rows reused from the previous envelope (C-18)
        if "raw_movies" in raw:  # older fixtures/snapshots carry none - the keys stay absent
            library_lists["movies"] = self._movies(raw["raw_movies"])
        elif cache.get("movies") is not None:
            library_lists["movies"] = cache["movies"]
        if "raw_shows" in raw:
            library_lists["shows"] = self._shows(raw["raw_shows"])
        elif cache.get("shows") is not None:
            library_lists["shows"] = cache["shows"]
        # live only: when the lists were last fetched (fixtures carry no stamp, so samples don't)
        stamp = raw.get("library_fetched_at") or cache.get("fetched_at")
        if stamp:
            library_lists["library_fetched_at"] = stamp
        data = {
            **library_lists,
            "summary": (
                f"{len(now_playing)} playing now" if now_playing
                else f"Nothing playing · {len(up_next)} up next"
            ),
            "secondary": secondary,
            "now_playing": now_playing,
            "up_next": up_next,
            "latest": latest,
            "server_id": (raw.get("raw_system") or {}).get("Id"),  # older fixtures carry none
            "library": {
                "movies": int(counts["MovieCount"]),
                "episodes": int(counts["EpisodeCount"]),
            },
            # older fixtures/snapshots carry no raw_history — an empty block, never a failure
            "history": self._history((raw.get("raw_history") or {}).get("Items", []), _now()),
            "her": self._her_block(raw),
        }
        for label, why in sorted((raw.get("errors") or {}).items()):
            partial_note(data, label, why)
        return data
