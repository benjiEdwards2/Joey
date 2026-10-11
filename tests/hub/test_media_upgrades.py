"""F4b (2026-10-12): "Upgrade available" — the hub side of the arr snapshot's `data.upgrades` (Radarr / Sonarr cutoff
unmet). Unit tests for hub/media_upgrades.py: the index, the note, the show bridging (tvdb key, a known TheTVDB id,
the unique title) and the Downloads block. Pages and the per-title search: test_media_upgrades_pages.py."""
import json
from pathlib import Path
from types import SimpleNamespace

from hub import media_upgrades as mu

SAMPLE = json.loads((Path(__file__).resolve().parents[2] / "config" / "sample_snapshots" / "arr.json")
                    .read_text(encoding="utf-8"))["data"]["upgrades"]


def snaps(upgrades=..., **extra):
    data = {"summary": "x", **extra}
    if upgrades is not ...:
        data["upgrades"] = upgrades
    return {"arr": SimpleNamespace(data=data)}


def test_note_film_show_and_unknown_cutoff():
    assert mu.note({"have": "WEBDL-720p", "want": "Bluray-1080p"}) == "Upgrade available · WEBDL-720p → Bluray-1080p"
    assert (mu.note({"episodes": 3, "have": "SDTV", "want": "WEB 1080p"})
            == "Upgrade available · 3 episodes · SDTV → WEB 1080p")
    assert mu.note({"episodes": 1, "have": "SDTV", "want": None}) == "Upgrade available · 1 episode"
    assert mu.note({"have": None, "want": None}) == "Upgrade available"
    assert mu.note({"have": None, "want": "Bluray-1080p"}) == "Upgrade available · to Bluray-1080p"
    assert mu.note(None) == ""


def test_index_keys_both_lists_by_item_key():
    idx = mu.index(snaps(SAMPLE))
    assert set(idx) == {"tmdb:1001", "tmdb:1002", "tmdb:1003", "tvdb:2001", "tvdb:2002"}
    assert idx["tmdb:1001"]["app"] == "radarr" and idx["tvdb:2001"]["app"] == "sonarr"
    assert idx["tmdb:1001"]["note"] == "Upgrade available · WEBDL-720p → Bluray-1080p"
    assert idx["tvdb:2001"]["note"] == "Upgrade available · 3 episodes · SDTV → WEB 1080p"


def test_index_is_empty_without_upgrades_or_with_null_lists():
    assert mu.index({}) == {} and mu.index(snaps()) == {}
    assert mu.index(snaps({"radarr": None, "sonarr": None, "totals": {}})) == {}
    assert set(mu.index(snaps({"radarr": None, "sonarr": SAMPLE["sonarr"]}))) == {"tvdb:2001", "tvdb:2002"}
    assert mu.index(snaps("junk")) == {}


def test_find_film_only_by_its_tmdb_key_and_never_a_sonarr_row():
    idx = mu.index(snaps(SAMPLE))
    assert mu.find(idx, "movie", "tmdb:1002")["title"] == "Desert Crossing"
    assert mu.find(idx, "movie", "tmdb:9999") is None
    assert mu.find(idx, "movie", "tvdb:2001") is None                 # a show's row never labels a film
    assert mu.find(idx, "tv", "tmdb:1002") is None                     # a film's row never labels a show (tmdb spaces)


def test_find_show_by_tvdb_key_known_tvdb_then_unique_title():
    idx = mu.index(snaps(SAMPLE))
    assert mu.find(idx, "tv", "tvdb:2001")["title"] == "Quiet Coast"
    assert mu.find(idx, "tv", "tmdb:77", tvdb="2002")["title"] == "Iron Valley"
    assert mu.find(idx, "tv", "tmdb:77", tvdb=2002)["title"] == "Iron Valley"
    assert mu.find(idx, "tv", "tmdb:77", title="The Quiet Coast!")["title"] == "Quiet Coast"   # normalised title
    assert mu.find(idx, "tv", "tmdb:77", title="Elsewhere") is None


def test_title_match_needs_a_unique_sonarr_title():
    rows = [{"item_key": "tvdb:1", "title": "Same", "arr_id": 1, "episodes": 1},
            {"item_key": "tvdb:2", "title": "Same", "arr_id": 2, "episodes": 1}]
    idx = mu.index(snaps({"radarr": [], "sonarr": rows}))
    assert mu.find(idx, "tv", "tmdb:5", title="Same") is None


def test_attach_labels_rows_and_needs_a_unique_library_title():
    shows = [{"item_key": "tmdb:2201", "title": "Quiet Coast"}, {"item_key": "tvdb:2002", "title": "Iron Valley"},
             {"item_key": "tmdb:5", "title": "Garden Lane"}, {"item_key": "tmdb:6", "title": "Night Ferry"},
             {"item_key": "tmdb:7", "title": "Night Ferry"}]
    mu.attach(shows, snaps(SAMPLE), "tv")
    assert [r["upgrade"] for r in shows] == ["Upgrade available · 3 episodes · SDTV → WEB 1080p",
                                             "Upgrade available · 1 episode · WEBDL-720p → Bluray-1080p", "", "", ""]
    films = [{"item_key": "tmdb:1001", "title": "Harbour Lights"}, {"item_key": "jf:x", "title": "Desert Crossing"}]
    mu.attach(films, snaps(SAMPLE), "movie")
    assert films[0]["upgrade"].startswith("Upgrade available") and films[1]["upgrade"] == ""   # films: key only
    old = [{"item_key": "tmdb:1001", "title": "Harbour Lights"}]
    mu.attach(old, snaps(), "movie")
    assert old[0]["upgrade"] == ""


def test_attach_uses_a_known_tvdb():
    shows = [{"item_key": "tmdb:1", "title": "Renamed Locally", "tvdb_id": 2001}]
    mu.attach(shows, snaps(SAMPLE), "tv", tvdb_of=lambda r: r.get("tvdb_id"))
    assert "3 episodes" in shows[0]["upgrade"]


def test_block_states():
    assert mu.block({}) is None and mu.block(snaps()) is None            # older envelope: the block is absent
    assert mu.block(snaps({"radarr": None, "sonarr": None, "totals": {}})) == {"state": "off"}
    b = mu.block(snaps(SAMPLE))
    assert b["state"] == "ok" and b["totals_text"] == "3 films · 2 shows" and b["off"] == []
    assert [(r["kind"], r["title"]) for r in b["rows"]][:1] == [("movie", "Copper Sky")]
    assert b["rows"][-1]["kind"] == "tv" and b["rows"][-1]["note"].startswith("Upgrade available · 3 episodes")
    half = mu.block(snaps({"radarr": SAMPLE["radarr"], "sonarr": None, "totals": {"movies": 1}}))
    assert half["totals_text"] == "1 film" and half["off"] == ["Sonarr"]


def test_attach_title_match_skips_a_title_the_library_holds_twice():
    shows = [{"item_key": "tmdb:6", "title": "Quiet Coast"}, {"item_key": "tmdb:7", "title": "Quiet Coast"}]
    mu.attach(shows, snaps(SAMPLE), "tv")
    assert [r["upgrade"] for r in shows] == ["", ""]
