"""P1a (2026-10-22): the arr feed's `library_sizes` block — per-title size on disk for the hub's Free space page, from
the library lists the counts already fetch (no extra call). Transform off the fixtures, the size fallbacks, the
null-when-not-fetched rule and the schema."""

import copy

import jsonschema

from connectors.stubs import Arr
from tests.connectors.helpers import SCHEMA, fake_requests
from tests.connectors.helpers import live, raw  # noqa: F401  (fixtures)
from tests.connectors.test_arr_upgrades import failing

GIB = 1024 ** 3


def test_radarr_rows_are_movies_with_a_file_biggest_first(raw):
    data = Arr().transform(raw)
    jsonschema.validate(data, SCHEMA)
    assert data["library_sizes"]["radarr"] == [
        {"tmdb_id": 1002, "title": "Desert Crossing", "year": 2024, "size_bytes": 13314398618},
        {"tmdb_id": 1001, "title": "Harbour Lights", "year": 2025, "size_bytes": 4831838208}]   # no-file movies left out


def test_sonarr_rows_carry_both_ids_and_ended(raw):
    rows = Arr().transform(raw)["library_sizes"]["sonarr"]
    assert rows == [
        {"tvdb_id": 2001, "tmdb_id": 3001, "title": "Quiet Coast", "size_bytes": 20 * GIB, "ended": True},
        {"tvdb_id": 2002, "tmdb_id": 3002, "title": "Iron Valley", "size_bytes": 6 * GIB, "ended": False}]
    # Paper Moons has 0 bytes on disk: left out


def test_size_fallbacks_and_status_ended(raw):
    raw = copy.deepcopy(raw)
    raw["raw_radarr_movie"] = [
        {"id": 1, "title": "Stats", "tmdbId": 1, "hasFile": True, "statistics": {"sizeOnDisk": 300}},
        {"id": 2, "title": "File", "tmdbId": 2, "hasFile": True, "movieFile": {"size": 200}},
        {"id": 3, "title": "Flagged no file", "tmdbId": 3, "hasFile": False, "sizeOnDisk": 900},
        {"id": 4, "title": "Zero", "tmdbId": 4, "hasFile": True, "sizeOnDisk": 0}]
    raw["raw_sonarr_series"] = [{"id": 1, "title": "Old", "tvdbId": 9, "status": "ended",
                                 "statistics": {"sizeOnDisk": 100}}]
    sizes = Arr().transform(raw)["library_sizes"]
    assert [(r["title"], r["size_bytes"]) for r in sizes["radarr"]] == [("Stats", 300), ("File", 200)]
    assert sizes["sonarr"] == [{"tvdb_id": 9, "tmdb_id": None, "title": "Old", "size_bytes": 100, "ended": True}]


def test_a_list_not_fetched_is_null(raw):
    old = {k: v for k, v in raw.items() if k not in ("raw_radarr_movie", "raw_sonarr_series")}
    data = Arr().transform(old)
    jsonschema.validate(data, SCHEMA)
    assert data["library_sizes"] == {"radarr": None, "sonarr": None}


def test_a_failed_movie_list_call_nulls_only_radarr(live, monkeypatch, raw):
    failing(monkeypatch, raw, "/api/v3/movie", app="radarr")
    data = Arr().run()["data"]
    assert data["library_sizes"]["radarr"] is None and data["library_sizes"]["sonarr"]
    jsonschema.validate(data, SCHEMA)


def test_no_extra_call(live, monkeypatch, raw):
    calls = fake_requests(monkeypatch, raw)
    Arr().run()
    assert len(calls) == 17   # unchanged since WP-U1 (2026-10-21): the sizes reuse the counts' library lists
