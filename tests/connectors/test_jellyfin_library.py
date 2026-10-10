"""F3a — whole-library movie/show lists (and Georgina's) on the jellyfin data block."""

import copy
import json
from pathlib import Path

import jsonschema
import pytest

from connectors.stubs import Jellyfin

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads((ROOT / "connectors" / "schema" / "data" / "jellyfin.schema.json").read_text(encoding="utf-8"))


@pytest.fixture()
def raw():
    return Jellyfin().fetch_fixture()


@pytest.fixture()
def data(snapshots, raw):
    out = Jellyfin().transform(raw)
    jsonschema.validate(out, SCHEMA)
    return out


def test_movie_rows_have_exactly_the_contract_keys(data):
    assert set(data["movies"][0]) == {
        "title", "year", "jf_id", "item_key", "poster", "backdrop", "runtime_min", "played",
        "last_played_at", "added_at", "community_rating", "genres"}
    assert data["movies"][1] == {
        "title": "Harbour Lights", "year": 2021, "jf_id": "item-fixture-6", "item_key": "tmdb:116",
        "poster": "jf:item-fixture-6", "backdrop": "jfb:item-fixture-6", "runtime_min": 104, "played": True,
        "last_played_at": "2025-12-31T18:30:00.0000000Z", "added_at": "2025-12-30T09:12:00.0000000Z",
        "community_rating": None, "genres": ["Drama"]}


def test_movie_rating_rounds_genres_cap_and_missing_provider_ids_fall_back(data):
    first, _, no_ids, unplayed = data["movies"]
    assert first["community_rating"] == 7.8 and first["genres"] == ["Drama", "Road Movie", "Adventure"]
    assert no_ids["item_key"] == "jf:item-fixture-8" and no_ids["played"] is False
    assert no_ids["last_played_at"] is None and no_ids["added_at"].startswith("2025-12-28")
    assert unplayed["genres"] == [] and unplayed["played"] is False


def test_movie_without_runtime_or_userdata_is_null_and_unplayed(snapshots, raw):
    raw = copy.deepcopy(raw)
    raw["raw_movies"]["Items"] = [{"Id": "m1", "Name": "Bare"}]
    row = Jellyfin().transform(raw)["movies"][0]
    assert row["runtime_min"] is None and row["played"] is False and row["year"] is None
    assert row["item_key"] == "jf:m1" and row["genres"] == [] and row["community_rating"] is None


def test_show_rows_status_words_and_counts(data):
    by = {s["title"]: s for s in data["shows"]}
    assert set(by["Quiet Coast"]) == {
        "title", "year", "jf_id", "item_key", "poster", "backdrop", "status_word", "episodes", "unplayed",
        "played", "last_played_at", "added_at", "community_rating", "genres"}
    assert (by["Quiet Coast"]["status_word"], by["Quiet Coast"]["unplayed"], by["Quiet Coast"]["episodes"]) == ("Continuing", 7, 18)
    assert (by["Night Ferry"]["status_word"], by["Night Ferry"]["played"], by["Night Ferry"]["unplayed"]) == ("Ended", True, 0)
    never = by["Garden Lane"]
    assert never["status_word"] == "Unknown" and never["last_played_at"] is None and never["played"] is False
    assert never["episodes"] == never["unplayed"] == 6 and never["community_rating"] is None


def test_show_item_key_prefers_tmdb_then_tvdb_then_jf(data):
    by = {s["title"]: s["item_key"] for s in data["shows"]}
    assert by == {"Quiet Coast": "tmdb:2201", "Night Ferry": "tvdb:7002", "Garden Lane": "jf:series-fixture-3"}


def test_show_missing_counts_default_to_zero(snapshots, raw):
    raw = copy.deepcopy(raw)
    raw["raw_shows"]["Items"] = [{"Id": "s1", "Name": "Bare", "Status": "Paused"}]
    row = Jellyfin().transform(raw)["shows"][0]
    assert (row["episodes"], row["unplayed"], row["status_word"]) == (0, 0, "Unknown")


def test_show_with_zero_items_on_disk_is_left_out(snapshots, raw):
    """2026-10-10: an unaired show Sonarr added is an empty Jellyfin Series (RecursiveItemCount 0) — not listed."""
    raw = copy.deepcopy(raw)
    raw["raw_shows"]["Items"] = [{"Id": "s1", "Name": "Empty", "RecursiveItemCount": 0},
                                 {"Id": "s2", "Name": "Has one", "RecursiveItemCount": 1}]
    assert [s["title"] for s in Jellyfin().transform(raw)["shows"]] == ["Has one"]


def test_her_arrays_only_when_her_keys_are_present(snapshots, raw):
    data = Jellyfin().transform(raw)
    assert [m["title"] for m in data["her"]["movies"]] == ["Harbour Lights", "Desert Crossing", "Salt Flats"]
    assert [s["title"] for s in data["her"]["shows"]] == ["Garden Lane", "Night Ferry"]
    assert data["her"]["movies"][1]["played"] is True
    assert data["her"]["shows"][0]["unplayed"] == 5
    assert data["movies"][1]["played"] is True and data["movies"][2]["played"] is False  # B.'s side untouched
    bare = {k: v for k, v in raw.items() if not k.startswith("raw_her_")}
    assert Jellyfin().transform(bare)["her"] is None
    no_lists = {k: v for k, v in raw.items() if k not in ("raw_her_movies", "raw_her_shows")}
    her = Jellyfin().transform(no_lists)["her"]
    assert "movies" not in her and "shows" not in her


def test_older_snapshots_without_the_lists_still_validate(snapshots, raw):
    old = {k: v for k, v in raw.items() if k not in ("raw_movies", "raw_shows", "raw_her_movies", "raw_her_shows")}
    out = Jellyfin().transform(old)
    assert "movies" not in out and "shows" not in out
    jsonschema.validate(out, SCHEMA)


def test_schema_rejects_extra_or_malformed_keys(data):
    bad = copy.deepcopy(data)
    bad["movies"][0]["extra"] = 1
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, SCHEMA)
    bad = copy.deepcopy(data)
    bad["shows"][0]["status_word"] = "Cancelled"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, SCHEMA)
    bad = copy.deepcopy(data)
    bad["her"]["shows"][0]["extra"] = 1
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, SCHEMA)


def test_sample_snapshot_carries_the_lists():
    sample = json.loads((ROOT / "config" / "sample_snapshots" / "jellyfin.json").read_text(encoding="utf-8"))
    assert len(sample["data"]["movies"]) >= 4 and len(sample["data"]["shows"]) >= 3
    assert sample["data"]["her"]["movies"] and sample["data"]["her"]["shows"]
