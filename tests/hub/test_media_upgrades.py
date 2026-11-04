"""F4b (2026-10-12): "Upgrade available" — the hub side of the arr snapshot's `data.upgrades` (Radarr / Sonarr cutoff
unmet). Unit tests for hub/media_upgrades.py: the index, the note, the show bridging (tvdb key, a known TheTVDB id,
the unique title) and the Downloads block. Pages and the per-title search: test_media_upgrades_pages.py.
Re-pointed WP-U1 (2026-10-21): the label reads "Below cutoff · <have> → wants <want>".
Re-pointed JY-275 (2026-11-04): rows carry `note` = "Upgrade available" only once a kept Why? answer found an accepted
release (tests.hub.upgrade_kept.keep), else ''; the old sentence is `detail`. The Downloads block splits rows / unchecked."""
import json
from pathlib import Path
from types import SimpleNamespace

from hub import media_upgrades as mu
from tests.hub.upgrade_kept import keep

SAMPLE = json.loads((Path(__file__).resolve().parents[2] / "config" / "sample_snapshots" / "arr.json")
                    .read_text(encoding="utf-8"))["data"]["upgrades"]


def snaps(upgrades=..., **extra):
    data = {"summary": "x", **extra}
    if upgrades is not ...:
        data["upgrades"] = upgrades
    return {"arr": SimpleNamespace(data=data)}


def test_note_film_show_and_unknown_cutoff():
    assert mu.note({"have": "WEBDL-720p", "want": "Bluray-1080p"}) == "Below cutoff · WEBDL-720p → wants Bluray-1080p"
    assert (mu.note({"episodes": 3, "have": "SDTV", "want": "WEB 1080p"})
            == "Below cutoff · 3 episodes · SDTV → wants WEB 1080p")
    assert mu.note({"episodes": 1, "have": "SDTV", "want": None}) == "Below cutoff · 1 episode"
    assert mu.note({"have": None, "want": None}) == "Below cutoff"
    assert mu.note({"have": None, "want": "Bluray-1080p"}) == "Below cutoff · wants Bluray-1080p"
    assert mu.note(None) == ""


def test_index_keys_both_lists_by_item_key():
    idx = mu.index(snaps(SAMPLE))
    assert set(idx) == {"tmdb:1001", "tmdb:1002", "tmdb:1003", "tvdb:2001", "tvdb:2002"}
    assert idx["tmdb:1001"]["app"] == "radarr" and idx["tvdb:2001"]["app"] == "sonarr"
    assert idx["tmdb:1001"]["note"] == "" and idx["tvdb:2001"]["note"] == ""          # JY-275: not checked -> nothing
    assert idx["tmdb:1001"]["detail"] == "Below cutoff · WEBDL-720p → wants Bluray-1080p"
    keep("radarr", 1)
    keep("sonarr", 1, viable=False)
    idx = mu.index(snaps(SAMPLE))
    assert idx["tmdb:1001"]["note"] == "Upgrade available" and idx["tvdb:2001"]["note"] == ""


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
    keep("sonarr", 1)
    keep("sonarr", 2)
    keep("radarr", 1)
    mu.attach(shows, snaps(SAMPLE), "tv")
    assert [r["upgrade"] for r in shows] == ["Upgrade available", "Upgrade available", "", "", ""]
    assert shows[0]["upgrade_href"] == "/media/downloads?why=sonarr:1&why_step=grab&pick=0#why-sonarr-1"
    assert shows[2]["upgrade_href"] is None
    films = [{"item_key": "tmdb:1001", "title": "Harbour Lights"}, {"item_key": "jf:x", "title": "Desert Crossing"}]
    mu.attach(films, snaps(SAMPLE), "movie")
    assert films[0]["upgrade"] == "Upgrade available" and films[1]["upgrade"] == ""   # films: key only
    old = [{"item_key": "tmdb:1001", "title": "Harbour Lights"}]
    mu.attach(old, snaps(), "movie")
    assert old[0]["upgrade"] == ""


def test_attach_uses_a_known_tvdb():
    shows = [{"item_key": "tmdb:1", "title": "Renamed Locally", "tvdb_id": 2001}]
    keep("sonarr", 1)
    mu.attach(shows, snaps(SAMPLE), "tv", tvdb_of=lambda r: r.get("tvdb_id"))
    assert shows[0]["upgrade"] == "Upgrade available"


def test_block_states():
    assert mu.block({}) is None and mu.block(snaps()) is None            # older envelope: the block is absent
    assert mu.block(snaps({"radarr": None, "sonarr": None, "totals": {}})) == {"state": "off"}
    b = mu.block(snaps(SAMPLE))
    assert b["state"] == "ok" and b["totals_text"] == "3 films · 2 shows" and b["off"] == []
    assert b["rows"] == [] and len(b["unchecked"]) == 5                  # JY-275: nothing checked -> nothing listed
    assert [(r["kind"], r["title"]) for r in b["unchecked"]][:1] == [("movie", "Copper Sky")]
    assert b["unchecked"][-1]["note"] == "" and b["unchecked"][-1]["detail"].startswith("Below cutoff · 3 episodes")
    keep("sonarr", 1)
    keep("radarr", 3, viable=False)
    b = mu.block(snaps(SAMPLE))
    assert [(r["kind"], r["title"], r["note"]) for r in b["rows"]] == [("tv", "Quiet Coast", "Upgrade available")]
    assert len(b["unchecked"]) == 4
    half = mu.block(snaps({"radarr": SAMPLE["radarr"], "sonarr": None, "totals": {"movies": 1}}))
    assert half["totals_text"] == "1 film" and half["off"] == ["Sonarr"]


def test_attach_title_match_skips_a_title_the_library_holds_twice():
    shows = [{"item_key": "tmdb:6", "title": "Quiet Coast"}, {"item_key": "tmdb:7", "title": "Quiet Coast"}]
    mu.attach(shows, snaps(SAMPLE), "tv")
    assert [r["upgrade"] for r in shows] == ["", ""]


def test_norm_title_drops_a_trailing_year():
    """Sonarr names a show "Brothers (2026)" when another Brothers exists; Jellyfin's row is just "Brothers"."""
    from hub.media_upgrades import norm_title
    assert norm_title("Brothers (2026)") == norm_title("Brothers") == "brothers"
    assert norm_title("The Wanted Man (2025)") == "wanted man"
    assert norm_title("2001") == "2001"                          # a bare year title stays itself
    assert norm_title("Blade Runner 2049") == "blade runner 2049"   # only a parenthesised year is dropped


def test_viable_is_one_rule_and_expires_after_a_day(monkeypatch):
    """JY-275: is_viable reads the kept answer only (24 h, was 1 h) - never a call."""
    from hub import media_upgrade_why as w
    assert w.TTL == 86400
    row = {"app": "radarr", "arr_id": 1}
    assert mu.is_viable(row) is False and mu.flag(row) == ""
    keep("radarr", 1)
    assert mu.is_viable(row) is True and mu.flag(row) == "Upgrade available"
    assert mu.is_viable({"kind": "movie", "arr_id": 1}) is True
    now = w._clock()
    monkeypatch.setattr(w, "_clock", lambda: now + 86400 + 1)
    assert mu.is_viable(row) is False


def test_upgrade_href_is_the_grab_confirm_of_the_accepted_release():
    """B., 2026-11-04: "If accepted, it should then try grab"."""
    assert mu.upgrade_href({"app": "radarr", "arr_id": 1}) is None
    keep("radarr", 1, viable=False)
    assert mu.upgrade_href({"app": "radarr", "arr_id": 1}) is None
    keep("radarr", 1)
    assert mu.upgrade_href({"kind": "movie", "arr_id": 1}) == "/media/downloads?why=radarr:1&why_step=grab&pick=0#why-radarr-1"
