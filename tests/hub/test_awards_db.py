"""Awards A1 (AWARDS_PLAN, 2026-10-08): the award_* tables in media.db — round-trip, PK dedupe, reads never create the
file, coming_up with and without a known date, old shows matched via TheTVDB."""
from contextlib import closing
from datetime import date

from hub import media_awards_db as adb
from hub import media_awards_seed as seed
from hub import media_db

FILM = {"qid": "Q1001", "kind": "film", "label": "Alpha", "tmdb_movie": 11, "tmdb_tv": None, "tmdb_person": None,
        "imdb": None, "tvdb": None}
FILM2 = {**FILM, "qid": "Q1002", "label": "Beta", "tmdb_movie": 12}
ACTOR = {"qid": "Q2001", "kind": "person", "label": "Ann Actor", "tmdb_movie": None, "tmdb_tv": None, "tmdb_person": 501,
         "imdb": None, "tvdb": None}
SHOW = {"qid": "Q3001", "kind": "tv", "label": "Old Show", "tmdb_movie": None, "tmdb_tv": None, "tmdb_person": None,
        "imdb": None, "tvdb": 7001}


def seed_oscars(db, ordinal=97, year=2025, held_on="2025-03-02"):
    adb.upsert_editions(db, "oscars", [{"ordinal": ordinal, "year": year, "held_on": held_on, "wd_qid": "Q85315076"}])
    cats = [{"cat_key": "Q102427", "name": "Best Picture", "kind": "film", "lead": "work"},
            {"cat_key": "Q103916", "name": "Best Actor", "kind": "film", "lead": "person"},
            {"cat_key": "Q99", "name": "Best Live Action Short Film", "kind": "film", "lead": "work"}]
    noms = [{"cat_key": "Q102427", "work_qid": "Q1001", "work_title": "Alpha", "won": 1, "pos": 0},
            {"cat_key": "Q102427", "work_qid": "Q1002", "work_title": "Beta", "won": 0, "pos": 1},
            {"cat_key": "Q102427", "work_qid": "~gamma", "work_title": "Gamma", "won": 0, "pos": 2},
            {"cat_key": "Q102427", "work_qid": "~delta", "work_title": "Delta", "won": 0, "pos": 3},
            {"cat_key": "Q103916", "work_qid": "Q1001", "work_title": "Alpha", "person_qid": "Q2001",
             "person_name": "Ann Actor", "won": 1, "pos": 0},
            {"cat_key": "Q103916", "work_qid": "Q1002", "work_title": "Beta", "person_qid": "~bob-b",
             "person_name": "Bob B", "won": 0, "pos": 1},
            {"cat_key": "Q99", "work_qid": "Q1002", "work_title": "Beta", "won": 0, "pos": 0}]
    return adb.write_edition(db, "oscars", ordinal, cats, noms, {e["qid"]: e for e in (FILM, FILM2, ACTOR)}, "done", "wd")


def test_reads_never_create_the_file():
    assert not media_db.db_path().exists()
    assert adb.years_of("oscars") == [] and adb.edition_page("oscars", 2025, "film") is None
    assert adb.work_awards(["tmdb:11"], "movie") == [] and adb.person_awards(501)["rows"] == []
    assert adb.sync_status()["total"] == 0 and adb.coming_up(date(2026, 10, 8), "film")
    assert adb.bodies("film")[0] == {"id": "oscars", "name": "Oscars"}
    assert not media_db.db_path().exists()


def test_ensure_seeds_the_bodies_once():
    with closing(adb.ensure()) as db:
        rows = [dict(r) for r in db.execute("SELECT * FROM award_body ORDER BY sort")]
    assert [r["id"] for r in rows] == [b["id"] for b in sorted(seed.BODIES, key=lambda b: b["sort"])]
    assert rows[0]["wp_title_fmt"] == "{ord} Academy Awards" and rows[0]["usual_month"] == 3


def test_round_trip_edition_page_groups_and_ranks():
    with closing(adb.ensure()) as db:
        assert seed_oscars(db) == 7
    page = adb.edition_page("oscars", 2025, "film")
    assert page["edition"]["name"] == "97th Academy Awards" and page["edition"]["state"] == "done"
    names = [c["name"] for c in page["categories"]]
    assert names == ["Best Picture", "Best Actor", "Best Live Action Short Film"]   # hero, core, folded
    bp = page["categories"][0]
    assert bp["rank"] == 0 and bp["grp"] == "core" and page["categories"][2]["grp"] == "more"
    assert [(e["work"]["title"], e["won"]) for e in bp["entries"]] == [("Alpha", 1), ("Beta", 0), ("Gamma", 0), ("Delta", 0)]
    assert bp["entries"][0]["work"]["ent"]["tmdb_movie"] == 11 and bp["entries"][2]["work"]["ent"] is None
    actor = page["categories"][1]["entries"]
    assert actor[0]["people"][0]["name"] == "Ann Actor" and actor[0]["work"]["title"] == "Alpha"
    assert adb.years_of("oscars") == [2025] and adb.latest_synced_year("oscars", "film") == 2025
    assert adb.edition_page("oscars", 2025, "tv")["categories"] == []


def test_rewrite_replaces_the_edition_and_dedupes_on_the_primary_key():
    with closing(adb.ensure()) as db:
        seed_oscars(db)
        seed_oscars(db)                               # a second pull of the same edition: same rows, not doubled
        dup = [{"cat_key": "Q102427", "work_qid": "Q1001", "work_title": "Alpha", "won": 0, "pos": 0},
               {"cat_key": "Q102427", "work_qid": "Q1001", "work_title": "Alpha", "won": 1, "pos": 0}]
        n = adb.write_edition(db, "oscars", 97, [{"cat_key": "Q102427", "name": "Best Picture", "kind": "film",
                                                  "lead": "work"}], dup, {}, "done", "wd")
        count = db.execute("SELECT COUNT(*) AS n, MAX(won) AS w FROM award_nomination").fetchone()
    assert n == 1 and count["n"] == 1 and count["w"] == 1


def test_offset_and_wikidata_facts_merge_without_losing_state():
    with closing(adb.ensure()) as db:
        seed_oscars(db)
        adb.upsert_editions(db, "oscars", [{"ordinal": 97, "year": 2025}])   # no new facts: state + date kept
        row = dict(db.execute("SELECT * FROM award_edition WHERE body_id = 'oscars' AND ordinal = 97").fetchone())
    assert row["state"] == "done" and row["held_on"] == "2025-03-02" and row["wd_qid"] == "Q85315076"


def test_work_awards_counts_wins_per_ceremony():
    with closing(adb.ensure()) as db:
        seed_oscars(db)
    got = adb.work_awards(["tmdb:12"], "movie")
    assert got == [{"body_id": "oscars", "body": "Oscars", "ordinal": 97, "year": 2025, "won": 0, "noms": 3,
                    "cats": [{"name": "Best Picture", "won": False, "rank": 0},
                             {"name": "Best Actor", "won": False, "rank": got[0]["cats"][1]["rank"]},
                             {"name": "Best Live Action Short Film", "won": False, "rank": got[0]["cats"][2]["rank"]}]}]
    alpha = adb.work_awards(["tmdb:11"], "movie")[0]
    assert (alpha["won"], alpha["noms"]) == (2, 2)
    assert adb.work_awards(["tmdb:11"], "tv") == []      # a TMDB TV id 11 is a different title


def test_old_shows_match_via_tvdb():
    with closing(adb.ensure()) as db:
        adb.upsert_editions(db, "emmys", [{"ordinal": 20, "year": 1968}])
        adb.write_edition(db, "emmys", 20, [{"cat_key": "Q989438", "name": "Outstanding Drama Series", "kind": "tv",
                                             "lead": "work"}],
                          [{"cat_key": "Q989438", "work_qid": "Q3001", "work_title": "Old Show", "won": 1, "pos": 0}],
                          {"Q3001": SHOW}, "done", "wp")
    got = adb.work_awards(["tvdb:7001"], "tv")
    assert got[0]["body"] == "Emmys" and got[0]["year"] == 1968 and got[0]["won"] == 1
    assert adb.work_awards(["tvdb:7001"], "movie") == []


def test_person_awards_counts_distinct_categories():
    with closing(adb.ensure()) as db:
        seed_oscars(db)
        adb.upsert_editions(db, "bafta", [{"ordinal": 78, "year": 2025}])
        adb.write_edition(db, "bafta", 78, [{"cat_key": "best-actor", "name": "Best Actor in a Leading Role",
                                             "kind": "film", "lead": "person"}],
                          [{"cat_key": "best-actor", "work_qid": "Q1001", "work_title": "Alpha", "person_qid": "Q2001",
                            "person_name": "Ann Actor", "won": 0, "pos": 1}], {}, "done", "wp")
    got = adb.person_awards(501)
    assert (got["wins"], got["noms"]) == (1, 2)
    assert [(r["body"], r["year"], r["cat"], r["won"], r["work_title"]) for r in got["rows"]] == [
        ("Oscars", 2025, "Best Actor", True, "Alpha"), ("BAFTA", 2025, "Best Actor in a Leading Role", False, "Alpha")]
    assert got["rows"][0]["work"]["tmdb_movie"] == 11


def test_coming_up_uses_usual_months_then_a_known_date():
    film = adb.coming_up(date(2026, 10, 8), "film")
    assert [g["month"] for g in film] == ["JAN", "FEB", "MAR", "MAY"]
    assert [i["name"] for i in film[0]["events"]] == ["Golden Globes", "Critics' Choice"]
    assert [i["name"] for i in film[1]["events"]] == ["BAFTA", "SAG", "DGA", "PGA"]
    assert all(i["date"] is None for g in film for i in g["events"])
    tv = adb.coming_up(date(2026, 10, 8), "tv")
    assert [(g["month"], [i["name"] for i in g["events"]]) for g in tv] == [
        ("JAN", ["Golden Globes", "Critics' Choice"]), ("FEB", ["SAG"]), ("SEP", ["Emmys"])]
    with closing(adb.ensure()) as db:
        adb.upsert_editions(db, "oscars", [{"ordinal": 99, "year": 2027, "held_on": "2027-03-14"}])
    film = adb.coming_up(date(2026, 10, 8), "film")
    mar = next(g for g in film if g["month"] == "MAR")
    assert {"body_id": "oscars", "name": "Oscars", "date": "14 Mar"} in mar["events"]


def test_coming_up_rolls_a_month_already_held_to_next_year():
    with closing(adb.ensure()) as db:
        adb.upsert_editions(db, "emmys", [{"ordinal": 78, "year": 2026, "held_on": "2026-09-14"}])
    tv = adb.coming_up(date(2026, 9, 20), "tv")
    assert tv[-1]["month"] == "SEP" and tv[-1]["year"] == 2027
    assert adb.coming_up(date(2026, 9, 1), "tv")[0] == {"month": "SEP", "year": 2026, "events": [
        {"body_id": "emmys", "name": "Emmys", "date": "14 Sep"}]}


def test_sync_status_and_titles_cache():
    with closing(adb.ensure()) as db:
        seed_oscars(db)
        adb.upsert_editions(db, "oscars", [{"ordinal": 96, "year": 2024}])
        adb.remember_titles(db, {"Anora": "Q123185887", "Nope": ""})
        assert adb.cached_titles(db, ["Anora", "Nope", "Other"]) == {"Anora": "Q123185887", "Nope": ""}
        adb.set_sync(db, "last_pass_at", "2026-10-03T01:00:00+00:00")
    st = adb.sync_status()
    assert (st["done"], st["total"], st["updated"], st["failed"]) == (1, 2, "2026-10-03T01:00:00+00:00", False)


def test_local_keys_are_never_qids():
    assert adb.local_key("Nick Gordon") == "~nick-gordon" and not adb.is_qid(adb.local_key("Q5"))
    assert adb.is_qid("Q102427") and not adb.is_qid("") and not adb.is_qid("best-film")
