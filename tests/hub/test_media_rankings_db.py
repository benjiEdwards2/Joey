"""Year rankings storage (2026-10-05): overview counts, place/move/unplace/reset, unknown-year bucket."""
import pytest

from hub import media_db


@pytest.fixture(autouse=True)
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("MEDIA_DB_PATH", str(tmp_path / "media.db"))


def rate_some():
    for key, title, year, score in (("tmdb:1", "Alpha", 2020, 9), ("tmdb:2", "Bravo", 2020, 7),
                                    ("tmdb:3", "Charlie", 2020, 8), ("tmdb:4", "Delta", 2021, 6),
                                    ("tmdb:5", "Echo", None, 5)):
        media_db.set_rating(key, score, "movie", title, year, "tmdb:/p.jpg")


def titles(year):
    return [r["title"] for r in media_db.year_list(year)["ranked"]]


def test_no_db_reads_empty(tmp_path):
    assert media_db.years_overview() == []
    assert media_db.year_list(2020) == {"ranked": [], "unranked": []}
    assert not (tmp_path / "media.db").exists()


def test_overview_counts_and_order():
    rate_some()
    media_db.place(2020, "tmdb:2")
    ov = media_db.years_overview()
    assert [o["year"] for o in ov] == [2021, 2020, None]
    by = {o["year"]: o for o in ov}
    assert (by[2020]["ranked_count"], by[2020]["unranked_count"]) == (1, 2)
    assert by[2020]["top"]["title"] == "Bravo" and by[2021]["top"] is None
    assert by[2021]["unranked_count"] == 1


def test_place_appends_then_inserts_and_shifts():
    rate_some()
    media_db.place(2020, "tmdb:1")
    media_db.place(2020, "tmdb:2")
    media_db.place(2020, "tmdb:3", position=1)
    assert titles(2020) == ["Charlie", "Alpha", "Bravo"]
    assert [r["position"] for r in media_db.year_list(2020)["ranked"]] == [1, 2, 3]
    assert media_db.place(2020, "tmdb:4") is False          # rated in another year
    assert media_db.year_list(2020)["unranked"] == []


def test_unranked_sorted_by_score_then_title():
    rate_some()
    assert [r["title"] for r in media_db.year_list(2020)["unranked"]] == ["Alpha", "Charlie", "Bravo"]


def test_move_swaps_and_clamps():
    rate_some()
    for k in ("tmdb:1", "tmdb:2", "tmdb:3"):
        media_db.place(2020, k)
    media_db.move(2020, "tmdb:3", -1)
    assert titles(2020) == ["Alpha", "Charlie", "Bravo"]
    media_db.move(2020, "tmdb:1", -1)                        # clamp at the top
    assert titles(2020) == ["Alpha", "Charlie", "Bravo"]
    media_db.move(2020, "tmdb:1", 1)
    assert titles(2020) == ["Charlie", "Alpha", "Bravo"]
    media_db.move(2020, "tmdb:2", 5)                         # clamp at the bottom, ±1 only
    assert titles(2020) == ["Charlie", "Alpha", "Bravo"]


def test_unplace_closes_gap_and_reset_clears():
    rate_some()
    for k in ("tmdb:1", "tmdb:2", "tmdb:3"):
        media_db.place(2020, k)
    media_db.unplace(2020, "tmdb:1")
    ranked = media_db.year_list(2020)["ranked"]
    assert [(r["position"], r["title"]) for r in ranked] == [(1, "Bravo"), (2, "Charlie")]
    media_db.reset_year(2020)
    assert media_db.year_list(2020)["ranked"] == []
    assert len(media_db.year_list(2020)["unranked"]) == 3


def test_unknown_year_bucket():
    rate_some()
    media_db.place(None, "tmdb:5")
    assert titles(None) == ["Echo"]
    assert media_db.place(None, "tmdb:1") is False
    assert media_db.years_overview()[-1] == {"year": None, "ranked_count": 1, "unranked_count": 0,
                                             "top": {"title": "Echo", "poster": "tmdb:/p.jpg", "item_key": "tmdb:5"}}
