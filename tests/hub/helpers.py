"""Shared hub test helpers (W3 tests, T-03, 2026-10-09): the builders and sample data that many test modules
import — snapshot envelopes, registry/area/tile builders, the Jellyfin / Jellyseerr / shelf fakes and samples.
The modules that used to define them still re-export them, so old `from tests.hub.test_store import write_envelope`
style imports keep working; new code imports from here."""
import importlib
from contextlib import closing
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
import requests
import yaml
from fastapi.testclient import TestClient


class FakeResponse:
    """A requests-style response: `.json()` returns the body, `.status_code` the status."""

    def __init__(self, body=None, status=200):
        self._b, self.status_code = body, status

    def json(self):
        return self._b


def write_envelope(d: Path, connector: str, age_minutes: int = 10, data: dict | None = None,
                   status: str = "ok") -> None:
    ts = (datetime.now(timezone.utc) - timedelta(minutes=age_minutes)).isoformat()
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{connector}.json").write_text(json.dumps({
        "connector": connector, "schema_version": 1,
        "fetched_at": ts, "updated_at": ts, "status": status,
        "consecutive_failures": 0, "error": None,
        "data": data if data is not None else {"summary": "VALUE"},
    }), encoding="utf-8")


def write_history(d: Path, sweeps: list, junk: list | None = None) -> Path:
    """Append run_all-shaped lines: each sweep is (minutes_ago, {cid: status | (status, error)})."""
    d.mkdir(parents=True, exist_ok=True)
    path = d / "_runner_history.jsonl"
    now = datetime.now(timezone.utc)
    with path.open("a", encoding="utf-8") as fh:
        for minutes_ago, results in sweeps:
            res = {}
            for cid, r in results.items():
                status, error = r if isinstance(r, tuple) else (r, None)
                res[cid] = {"status": status, "consecutive_failures": 0, "error": error}
            fh.write(json.dumps({"ran_at": (now - timedelta(minutes=minutes_ago)).isoformat(),
                                 "results": res}) + "\n")
        for line in junk or []:
            fh.write(line + "\n")
    return path


AREAS_YAML = Path(__file__).resolve().parents[2] / "config" / "areas.yaml"


def make_tile(tid: str, **over) -> dict:
    tile = {
        "id": tid, "label": "T", "tier": "embed", "owner": "shared",
        "snapshot": "open_meteo", "stale_after_minutes": 60, "setup_note": "n",
    }
    tile.update(over)
    return {k: v for k, v in tile.items() if v is not None}


def make_area(aid: str, tid: str | None = None, **tile_over) -> dict:
    tid = tid or f"{aid}-t"
    return {
        "id": aid, "name": aid.title(), "icon": aid,
        "summary_tile": tid, "tiles": [make_tile(tid, **tile_over)],
    }


def write_registry(tmp_path: Path, *areas: dict) -> Path:
    p = tmp_path / "areas.yaml"
    p.write_text(yaml.safe_dump({"areas": list(areas)}), encoding="utf-8")
    return p


LINK = "http://nas.example.invalid:8096"


NOW = datetime.now(timezone.utc)


TODAY = NOW.date().isoformat()


RECENT = [
    {"title": "Harbour Lights", "item_key": "m1", "kind": "movie", "poster": "jf:1",
     "when": "yesterday", "watched_at": (NOW - timedelta(days=1)).isoformat()},
    {"title": "Rated One", "item_key": "m2", "kind": "movie", "poster": None,
     "when": "2 days ago", "watched_at": (NOW - timedelta(days=2)).isoformat()},
    {"title": "Old One", "item_key": "m3", "kind": "movie", "poster": None,
     "when": "long ago", "watched_at": (NOW - timedelta(days=90)).isoformat()},
]


JELLY = {
    "summary": "1 playing now",
    "now_playing": [{"title": "Playing Now Title", "user": "Sample Person", "progress_pct": 42,
                     "play_method": "Transcoding", "poster": "jf:np", "backdrop": "jfb:np"}],
    "up_next": [{"title": "Dust and Daylight", "remaining_text": "31 min left", "poster": None,
                 "item_key": "u1"}],
    "latest": [{"title": "Fresh Film", "item_key": "dup", "poster": "jf:f",
                "added_at": (NOW - timedelta(days=1)).isoformat()}],
    "history": {"recent": RECENT},
}


ARR = {"summary": "x", "arrived": [{"title": "Fresh Film", "item_key": "dup", "when": "today"},
                                   {"title": "Arr Only", "item_key": "a1", "when": "today"}],
       "this_week": [{"title": "Due Show", "kind": "episode", "date": TODAY, "label": "Premiere", "item_key": "tvdb:9"}],
       "downloading": [{"title": "Fetching Film", "kind": "movie", "pct": 40, "status_text": "Downloading",
                        "time_left": "12 min", "item_key": None}]}


SEERR_REQUESTS = {"summary": "x", "requests": [{"title": "Wanted", "item_key": "r1", "status_text": "Pending",
                                       "href": "http://x.invalid"}]}


def shelf_area(layout="shelves"):
    area = make_area("alpha", "play-t", snapshot="jellyfin", stale_after_minutes=10, detail="/media/playing")
    area["layout"] = layout
    t = area["tiles"]
    t.append(make_tile("lib-t", snapshot="arr", stale_after_minutes=180, detail="/media/library"))
    t.append(make_tile("req-t", snapshot="jellyseerr", stale_after_minutes=180, detail="/media/requests"))
    t.append(make_tile("apps-t", snapshot="media_status", stale_after_minutes=10, detail="/media/apps"))
    t.append(make_tile("hist-t", snapshot="jellyfin", stale_after_minutes=10, detail="/media/history", owner="you"))
    t.append(make_tile("diary-t", snapshot="jellyfin", stale_after_minutes=10, detail="/media/diary", owner="you"))
    t.append({"id": "open-t", "label": "Open Jellyfin", "tier": "link", "owner": "shared", "href": LINK})
    return area


URL = "http://jf.secret-host.invalid:8096"


KEY = "jf-SECRET-key-123"


YESTERDAY = (date.today() - timedelta(days=1)).isoformat() + "T00:00:00.0000000Z"


TOMORROW = (date.today() + timedelta(days=3)).isoformat() + "T00:00:00.0000000Z"


TICKS = 600_000_000


STREAMS = [{"Type": "Video", "Codec": "hevc", "Height": 2160, "Width": 3840, "VideoRangeType": "HDR10"},
           {"Type": "Audio", "Codec": "eac3", "Channels": 6, "Profile": "Dolby Digital Plus + Dolby Atmos", "IsDefault": True}]


SOURCES = [{"Container": "mkv", "Size": 20 * 1024 ** 3, "MediaStreams": STREAMS}]


SEASON_NO = {"sea1": 4}   # E1: an episode names its season (SeasonName, ParentIndexNumber), as Jellyfin's do


def ep(i, name, played=False, pos=0, premiere=YESTERDAY, season="sea1"):
    n = SEASON_NO.get(season)
    return {"Id": f"ep{i}", "Name": name, "IndexNumber": i, "PremiereDate": premiere, "SeasonId": season,
            "SeasonName": f"Season {n}" if n is not None else None, "ParentIndexNumber": n,
            "UserData": {"Played": played, "PlaybackPositionTicks": pos}}


ITEMS = {
    "mov1": {"Id": "mov1", "Type": "Movie", "Name": "Harbour Lights", "ProductionYear": 2019,
             "Overview": "A ferry pilot returns home.", "Genres": ["Drama", "Thriller"], "RunTimeTicks": 112 * TICKS,
             "CommunityRating": 7.84, "OfficialRating": "M", "ProviderIds": {"Tmdb": "603"},
             "UserData": {"Played": False, "PlaybackPositionTicks": 80 * TICKS},
             "People": [{"Name": "Ada Actor", "Type": "Actor", "Role": "Pilot"}, {"Name": "Dee Director", "Type": "Director"}],
             "MediaSources": SOURCES},
    "ep3": {"Id": "ep3", "Type": "Episode", "Name": "Penny for Your Thoughts", "SeriesId": "ser1",
            "SeasonId": "sea1", "SeriesName": "Quiet Show", "ParentIndexNumber": 4, "IndexNumber": 3,
            "PremiereDate": "2026-10-12T00:00:00.0000000Z", "RunTimeTicks": 45 * TICKS, "Overview": "Coins go missing.",
            "UserData": {"Played": True, "PlaybackPositionTicks": 0}, "MediaSources": SOURCES},
    "ser1": {"Id": "ser1", "Type": "Series", "Name": "Quiet Show", "ProductionYear": 2020, "Genres": ["Comedy"],
             "ProviderIds": {"Tmdb": "100"}, "Overview": "A quiet show.", "UserData": {"Played": False}},
}


SEASONS = [{"Id": "sea1", "Name": "Season 4", "IndexNumber": 4}]


EPISODES = [ep(1, "One", True), ep(2, "Two", True), ep(3, "Three", True), ep(4, "Four", pos=5 * TICKS),
            ep(5, "Five"), ep(6, "Six", premiere=TOMORROW)]


def not_season_state(calls):
    """The calls minus WP-T1's one Sonarr series-list read (2026-10-19): the season-state words' BackgroundTask runs after
    the render, but TestClient runs it before get() returns. Asserts it is at most that one read."""
    rest = [c for c in calls if not (c[0] == "GET" and c[1].endswith("/api/v3/series") and not c[2])]
    assert len(calls) - len(rest) <= 1
    return rest


def not_quality(calls):
    """The calls minus WP-R1's quality reads (2026-10-21): the arr quality-profile lists (the Request confirm step, the
    Requests page's BackgroundTask) and that task's Radarr lookups of film rows (TestClient runs it before get() returns)."""
    return [c for c in calls if not (c[0] == "GET" and (c[1].endswith("/api/v3/qualityprofile")
                                                        or (c[1].endswith("/api/v3/movie") and "tmdbId" in (c[2] or {}))))]


class JellyfinFake:
    def __init__(self):
        self.calls, self.fail = [], False

    def get(self, url, params=None, headers=None, timeout=None, **kw):
        assert url.startswith(URL) and headers == {"Authorization": f"MediaBrowser Token={KEY}"}
        path = url[len(URL):]
        self.calls.append((path, params))
        if self.fail:
            raise requests.ConnectionError(url)
        if path == "/Users":
            return FakeResponse([{"Id": "u1", "Name": "Ben", "Policy": {"IsAdministrator": True}}])
        if path == "/System/Info/Public":
            return FakeResponse({"Id": "pubsrv"})
        if path.startswith("/Users/u1/Items/"):
            it = ITEMS.get(path.rsplit("/", 1)[1])
            return FakeResponse(it) if it else FakeResponse({}, 404)
        if path == "/Shows/ser1/Seasons":
            return FakeResponse({"Items": SEASONS})
        if path == "/Shows/ser1/Episodes":
            return FakeResponse({"Items": EPISODES})
        return FakeResponse({}, 404)


def deep(jf_id, server="srv-1"):
    return f"{LINK}/web/#/details?id={jf_id}&amp;serverId={server}"


LINKED = {
    "summary": "x", "server_id": "srv-1",
    "now_playing": [{"title": "Playing Now Title", "user": "Sam", "progress_pct": 42, "play_method": "Direct",
                     "poster": "jf:np", "backdrop": "jfb:np", "jf_id": "np1", "item_key": "jf:np1"}],
    "up_next": [{"title": "Dust and Daylight", "remaining_text": "31 min left", "poster": None, "jf_id": "resume-id",
                 "item_key": "jf:ser9", "show_key": "jf:ser9", "season_key": "jf:sea9", "episode_key": "jf:resume-id"}],
    "latest": [{"title": "Fresh Film", "type": "Movie", "item_key": "tmdb:5", "poster": None, "jf_id": "new-id",
                "added_at": NOW.isoformat()}],
    "history": {"recent": [{"title": "Quiet Show · S01E02 · B", "kind": "episode", "poster": None,
                            "when": "today", "watched_at": NOW.isoformat(), "jf_id": "e2", "item_key": "jf:ser1",
                            "show_key": "jf:ser1", "season_key": "jf:sea1", "episode_key": "jf:e2",
                            "season": 1, "episode": 2, "show_title": "Quiet Show"}]},
}


SEERR_URL = "http://seerr.secret-host.invalid:5055"


SKEY = "k-SECRET-0123456789"


FILM = {"id": 603, "title": "Harbour Lights", "releaseDate": "2019-05-05", "tagline": "Come home", "runtime": 112,
        "overview": "A ferry pilot returns home.", "voteAverage": 7.4, "posterPath": "/hl.jpg", "backdropPath": "/hlb.jpg",
        "genres": [{"name": "Drama"}], "mediaInfo": {"status": 5},
        "credits": {"cast": [{"name": "Ada Actor", "character": "Pilot", "profilePath": "/ada.jpg"},
                             {"name": "Bo Bit", "character": "Deckhand"}],
                    "crew": [{"name": "Dee Director", "job": "Director"}, {"name": "Cy Camera", "job": "Cinematographer"}]},
        "collection": {"id": 9, "name": "Harbour Collection"},
        "watchProviders": [{"iso_3166_1": "AU", "flatrate": [{"name": "Netflix"}], "rent": [{"name": "Apple TV"}]},
                           {"iso_3166_1": "US", "flatrate": [{"name": "USOnly"}]}],
        "relatedVideos": [{"url": "https://www.youtube.com/watch?v=seerr1", "site": "YouTube", "type": "Trailer"}],
        "releases": {"results": [{"iso_3166_1": "AU", "release_dates": [
            {"type": 3, "release_date": "2019-05-05T00:00:00.000Z"}, {"type": 4, "release_date": "2019-08-01T00:00:00.000Z"}]}]}}


PLAIN = {"id": 701, "title": "Plain Film", "releaseDate": "2024-01-01", "posterPath": "/pf.jpg", "backdropPath": "/pfb.jpg",
         "overview": "Nothing yet.", "mediaInfo": {"status": 1}}


SHOW = {"id": 100, "name": "Quiet Show", "firstAirDate": "2020-01-01", "numberOfSeasons": 1, "numberOfEpisodes": 6,
        "posterPath": "/qs.jpg", "createdBy": [{"name": "Cass Creator"}], "mediaInfo": {"status": 5},
        "seasons": [{"seasonNumber": 4, "name": "Season 4", "episodeCount": 6, "airDate": "2020-01-01"}]}


def prow(i, title, status=None):
    r = {"id": i, "title": title, "releaseDate": "2020-01-01", "posterPath": f"/p{i}.jpg", "mediaType": "movie"}
    if status:
        r["mediaInfo"] = {"status": status}
    return r


class Seerr:
    def __init__(self):
        self.table = {
            "/api/v1/movie/603": FILM, "/api/v1/movie/701": PLAIN, "/api/v1/tv/100": SHOW,
            "/api/v1/movie/603/ratingscombined": {"rt": {"criticsScore": 92}, "imdb": {"criticsScore": 7.9}},
            "/api/v1/movie/603/similar": {"results": [prow(11, "Similar One", 5), prow(12, "Similar Two")]},
            "/api/v1/movie/603/recommendations": {"results": [prow(13, "Rec One")]},
            "/api/v1/collection/9": {"parts": [prow(603, "Harbour Lights", 5), prow(604, "Harbour Lights 2"), prow(605, "Harbour Lights 3")]}}
        self.post_status = 201
        self.posts = []

    def get(self, path):
        return FakeResponse(self.table[path]) if path in self.table else FakeResponse({}, 404)


class Both:
    """requests.get / post for both services."""

    def __init__(self):
        self.jf, self.seerr, self.fail_jf, self.fail_seerr, self.calls = JellyfinFake(), Seerr(), False, False, []

    def get(self, url, params=None, headers=None, timeout=None, **kw):
        self.calls.append(url)
        if url.startswith(URL):
            self.jf.fail = self.fail_jf
            return self.jf.get(url, params=params, headers=headers, timeout=timeout)
        assert url.startswith(SEERR_URL) and headers == {"X-Api-Key": SKEY}
        if self.fail_seerr:
            raise requests.ConnectionError(url)
        return self.seerr.get(url[len(SEERR_URL):])

    def post(self, url, json=None, headers=None, timeout=None, **kw):
        self.seerr.posts.append((url, json))
        return FakeResponse({}, self.seerr.post_status)


LIB_MOVIES = [{"item_key": "tmdb:603", "jf_id": "mov1", "title": "Harbour Lights", "year": 2019},
              {"item_key": "tmdb:604", "jf_id": "mov2", "title": "Harbour Lights 2", "year": 2022}]
LIB_SHOWS = [{"item_key": "tmdb:100", "jf_id": "ser1", "title": "Quiet Show", "year": 2020}]


@pytest.fixture()
def env(tmp_path, monkeypatch):
    from hub import media_discover, media_files, media_film, media_item  # lazy: keep helpers import-light
    area = shelf_area()
    area["tiles"].append(make_tile("disc-t", snapshot="jellyseerr", stale_after_minutes=180, detail="/media/discover"))
    monkeypatch.setenv("AREAS_PATH", str(write_registry(tmp_path, area, make_area("beta"))))
    monkeypatch.setenv("MEDIA_DB_PATH", str(tmp_path / "media.db"))
    monkeypatch.setenv("SNAPSHOT_DIR", str(tmp_path / "snaps"))
    monkeypatch.setenv("PLAY_RECORDER", "off")
    for k, v in (("JELLYFIN_URL", URL), ("JELLYFIN_API_KEY", KEY), ("JELLYSEERR_URL", SEERR_URL), ("JELLYSEERR_API_KEY", SKEY)):
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("JELLYFIN_USER", raising=False)
    monkeypatch.setattr(media_film, "BADGES_DIR", tmp_path / "badges")

    def build(arr=None, seerr_snap=None, jelly_extra=None):
        snaps = tmp_path / "snaps"
        write_envelope(snaps, "jellyfin", age_minutes=1,
                       data={"summary": "x", "server_id": "srv-1", "movies": LIB_MOVIES, "shows": LIB_SHOWS, **(jelly_extra or {})})
        write_envelope(snaps, "arr", age_minutes=1, data={"summary": "x", **(arr or {})})
        write_envelope(snaps, "jellyseerr", age_minutes=1, data={"summary": "x", "requests": seerr_snap or []})
        import hub.main
        importlib.reload(hub.main)
        for clear in (media_files.clear_cache, media_item.clear_cache, media_discover.clear_cache):
            clear()
        both = Both()
        monkeypatch.setattr(requests, "get", both.get)
        monkeypatch.setattr(requests, "post", both.post)
        return TestClient(hub.main.app), both

    return build


# ---- Month in Review + Wrapped (E6, 2026-10-13): media.db builders, samples and the Diary fixture ----

WRAP_NOW = datetime(2026, 10, 13, 20, 0)


def local(day: date, hour=20, minute=0) -> datetime:
    from hub import media_wrapped
    return media_wrapped._local(day) + timedelta(hours=hour, minutes=minute)


def diary(key, kind, title, day, owner="you", source="jellyfin", year=None, poster=None, show_key=None,
          show_title=None, season=None, episode=None):
    from hub import media_store
    with closing(media_store.connect()) as db, db:
        db.execute("INSERT INTO diary(item_key, kind, title, year, poster, watched_on, source, owner, created_at, show_key,"
                   " season, episode, show_title) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (key, kind, title, year, poster, day, source, owner, "2026-01-01T00:00:00", show_key, season,
                    episode, show_title))


def play(jf_id, kind, title, start: datetime, minutes, runtime=None, owner="you", item_key=None, show_key=None,
         show_title=None):
    from hub import media_plays_db, media_store
    end = start + timedelta(minutes=minutes)
    with closing(media_store.connect()) as db, db:
        db.execute("INSERT INTO play(user_name, owner, jf_id, item_key, show_key, title, show_title, kind, runtime_min,"
                   " started_at, last_seen_at, position_pct, finished) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   ("u", owner, jf_id, item_key, show_key, title, show_title, kind, runtime,
                    media_plays_db._iso(start), media_plays_db._iso(end), 100, 1))


def eps(show_key, show_title, days, start_ep=1, owner="you"):
    for i, d in enumerate(days):
        diary(f"{show_key}e{start_ep + i}", "tv", show_title, d, owner=owner, show_key=show_key, show_title=show_title,
              season=1, episode=start_ep + i, poster=f"jf:{show_key[3:]}")


WRAP_MOVIES = [{"item_key": "tmdb:1", "jf_id": "anora1", "title": "Anora", "year": 2024, "poster": "jf:anora1", "runtime_min": 139},
          {"item_key": "tmdb:2", "jf_id": "old1", "title": "Old Film", "year": 1959, "poster": "jf:old1", "runtime_min": 100},
          {"item_key": "tmdb:3", "jf_id": "mid1", "title": "Mid Film", "year": 2001, "poster": "jf:mid1"}]
WRAP_SHOWS = [{"item_key": "tmdb:100", "jf_id": "ser1", "title": "Quiet Show", "episodes": 26, "unplayed": 6,
          "poster": "jf:ser1"},
         {"item_key": "tmdb:200", "jf_id": "ser2", "title": "Done Show", "episodes": 4, "unplayed": 0, "poster": "jf:ser2"}]


def jelly(movies=WRAP_MOVIES, shows=WRAP_SHOWS):
    return {"summary": "x", "server_id": "srv-1", "history": {"recent": []}, "movies": movies, "shows": shows}


@pytest.fixture()
def wrap(tmp_path, monkeypatch):
    """(client builder, db file) for the Diary and Wrapped pages, "today" pinned to Tue 13 Oct 2026, 20:00 at home; the
    jellyfin snapshot carries MOVIES / SHOWS and no history (so no sync adds rows of its own)."""
    from hub import media_wrapped   # lazy: keep helpers import-light
    area = make_area("alpha", "play-t", snapshot="jellyfin", stale_after_minutes=10, detail="/media/playing")
    area["tiles"] += [make_tile("hist-t", snapshot="jellyfin", stale_after_minutes=10, detail="/media/history", owner="you"),
                      make_tile("diary-t", snapshot="jellyfin", stale_after_minutes=10, detail="/media/diary", owner="you")]
    monkeypatch.setenv("AREAS_PATH", str(write_registry(tmp_path, area)))
    monkeypatch.setenv("MEDIA_DB_PATH", str(tmp_path / "data" / "media.db"))
    monkeypatch.setenv("SNAPSHOT_DIR", str(tmp_path / "snaps"))
    monkeypatch.setattr(media_wrapped, "_now", lambda: local(WRAP_NOW.date(), 20))
    media_wrapped.clear()

    def build(**kw):
        write_envelope(tmp_path / "snaps", "jellyfin", age_minutes=1, data=jelly(**kw))
        import hub.main
        importlib.reload(hub.main)
        return TestClient(hub.main.app)
    return build, tmp_path / "data" / "media.db"


def seed_year():
    """2026: Anora (rated 9, a rewatch), Old Film (rated 7), Mid Film (no runtime, rated 10); Quiet Show x5 episodes,
    Done Show x2; one hand-logged film; plays from 6 Oct (the recorder's start) on Sunday nights."""
    from hub import media_db, media_store
    media_store.connect().close()
    diary("tmdb:1", "movie", "Anora", "2025-12-30")                                 # last year: makes 2026's a rewatch
    diary("tmdb:2", "movie", "Old Film", "2026-01-02", poster="jf:old1")
    diary("tmdb:3", "movie", "Mid Film", "2026-03-10")
    diary("tmdb:1", "movie", "Anora", "2026-10-06", poster="jf:anora1")                # the play below covers it
    diary("tmdb:9", "movie", "Hand Logged", "2026-10-12", source="manual", year=2026)
    eps("jf:ser1", "Quiet Show", ["2026-03-10", "2026-03-11", "2026-03-12", "2026-10-11", "2026-10-12"])
    eps("jf:ser2", "Done Show", ["2026-03-14", "2026-03-15"])
    media_db.set_rating("tmdb:1", 9, "movie", "Anora")
    media_db.set_rating("tmdb:2", 7, "movie", "Old Film")
    media_db.set_rating("tmdb:3", 10, "movie", "Mid Film")
    play("anora1", "movie", "Anora", local(date(2026, 10, 6), 21), 130, runtime=139, item_key="tmdb:1")
    play("ep4", "episode", "Quiet Show · S01E04", local(date(2026, 10, 11), 21), 45, runtime=45, item_key="jf:ep4",
         show_key="jf:ser1", show_title="Quiet Show")
    play("ep5", "episode", "Quiet Show · S01E05", local(date(2026, 10, 11), 22), 45, runtime=45, item_key="jf:ep5",
         show_key="jf:ser1", show_title="Quiet Show")
