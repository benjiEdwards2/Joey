"""Awards A5 (AWARDS_PLAN, 2026-10-08): the film / TV page gains an Awards section (one line per ceremony + its
categories, each linked to that ceremony's Awards page; absent when the title has none) and the person page an Awards
section ("2 wins · 5 nominations" + rows; hidden when none). Both read media.db only."""
import re
from contextlib import closing

from hub import media_awards_db as adb
from tests.hub.test_media_film import env, main_of  # noqa: F401  (env is a fixture)
from tests.hub.test_media_person import seed as seed_person

HARBOUR = {"qid": "Q7001", "kind": "film", "label": "Harbour Lights", "tmdb_movie": 603, "tmdb_tv": None,
           "tmdb_person": None, "imdb": None, "tvdb": None}
OTHER = {**HARBOUR, "qid": "Q7002", "label": "Other Film", "tmdb_movie": 604}
ADA = {"qid": "Q8001", "kind": "person", "label": "Ada Actor", "tmdb_movie": None, "tmdb_tv": None, "tmdb_person": 55,
       "imdb": None, "tvdb": None}
ENTS = {e["qid"]: e for e in (HARBOUR, OTHER, ADA)}


def cat(key, name, lead="work"):
    return {"cat_key": key, "name": name, "kind": "film", "lead": lead}


def three_bodies():
    with closing(adb.ensure()) as db:
        adb.upsert_editions(db, "oscars", [{"ordinal": 97, "year": 2025}])
        adb.upsert_editions(db, "bafta", [{"ordinal": 78, "year": 2025}])
        adb.upsert_editions(db, "globes", [{"ordinal": 81, "year": 2024}])
        adb.write_edition(db, "oscars", 97, [cat("Q102427", "Best Picture"), cat("Q103916", "Best Actor", "person")], [
            {"cat_key": "Q102427", "work_qid": "Q7001", "work_title": "Harbour Lights", "won": 1, "pos": 0},
            {"cat_key": "Q103916", "work_qid": "Q7001", "work_title": "Harbour Lights", "person_qid": "Q8001",
             "person_name": "Ada Actor", "won": 0, "pos": 1}], ENTS, "done", "wd")
        adb.write_edition(db, "bafta", 78, [cat("best-film", "Best Film"),
                                            cat("best-actress", "Best Actress in a Leading Role", "person"),
                                            cat("best-editing", "Best Editing")], [
            {"cat_key": "best-film", "work_qid": "Q7001", "work_title": "Harbour Lights", "won": 1, "pos": 0},
            {"cat_key": "best-actress", "work_qid": "Q7001", "work_title": "Harbour Lights", "person_qid": "Q8001",
             "person_name": "Ada Actor", "won": 1, "pos": 0},
            {"cat_key": "best-editing", "work_qid": "Q7001", "work_title": "Harbour Lights", "won": 0, "pos": 2}],
            ENTS, "done", "wp")
        adb.write_edition(db, "globes", 81, [cat("gg-drama", "Best Motion Picture – Drama"),
                                             cat("gg-actress", "Best Actress in a Motion Picture – Drama", "person"),
                                             cat("gg-actress-2", "Best Supporting Actress – Motion Picture", "person")], [
            {"cat_key": "gg-drama", "work_qid": "Q7001", "work_title": "Harbour Lights", "won": 0, "pos": 1},
            {"cat_key": "gg-actress", "work_qid": "Q7002", "work_title": "Other Film", "person_qid": "Q8001",
             "person_name": "Ada Actor", "won": 0, "pos": 2},
            {"cat_key": "gg-actress-2", "work_qid": "~unlinked", "work_title": "Unlinked", "person_qid": "Q8001",
             "person_name": "Ada Actor", "won": 1, "pos": 0}], ENTS, "done", "wp")


def awards_section(b):
    m = re.search(r'<section class="sec" id="awards">.*?</section>', b, re.S)
    return m.group(0) if m else None


def test_film_page_lists_each_ceremony_with_its_categories_and_links(env):
    three_bodies()
    client, _ = env()
    with client:
        b = main_of(client.get("/media/title/movie/603").text)
    sec = awards_section(b)
    assert sec and '<div class="seclabel">Awards</div>' in sec
    lines = re.findall(r'<a class="awline" href="([^"]+)"><div class="row-title">([^<]+)</div>', sec)
    assert lines == [("/media/movies/awards?body=oscars&amp;year=2025", "Oscars 2025 · Won 1 of 2 nominations"),
                     ("/media/movies/awards?body=bafta&amp;year=2025", "BAFTA 2025 · Won 2 of 3 nominations"),
                     ("/media/movies/awards?body=globes&amp;year=2024", "Golden Globes 2024 · 1 nomination")]
    assert '<span class="st-good">Won</span> Best Picture · Best Actor' in sec
    assert '<span class="st-good">Won</span> Best Film · <span class="st-good">Won</span> Best Actress in a Leading Role · Best Editing' in sec
    assert b.index('id="awards"') < b.index('<div class="filmbody">')     # under the stats strip


def test_film_page_has_no_awards_section_without_rows(env):
    client, _ = env()
    with client:
        b = main_of(client.get("/media/title/movie/603").text)
    assert awards_section(b) is None and 'id="awards"' not in b


def test_person_page_counts_wins_and_nominations_and_links_matched_works(env):
    three_bodies()
    client, both = env()
    seed_person(both)
    with client:
        b = main_of(client.get("/media/person/55").text)
    sec = awards_section(b)
    assert sec and '<p class="metaline">2 wins · 4 nominations</p>' in sec
    rows = re.findall(r'<(a|div) class="awline"(?: href="([^"]*)")?><div class="row-title">([^<]+)</div>'
                      r'<div class="row-meta">(.*?)</div>', sec)
    assert [(r[2], re.sub(r"<[^>]+>", "", r[3])) for r in rows] == [
        ("Oscars 2025 · Best Actor", "Nominated · Harbour Lights"),
        ("BAFTA 2025 · Best Actress in a Leading Role", "Won · Harbour Lights"),
        ("Golden Globes 2024 · Best Actress in a Motion Picture – Drama", "Nominated · Other Film"),
        ("Golden Globes 2024 · Best Supporting Actress – Motion Picture", "Won · Unlinked")]
    assert rows[0][0] == "a" and rows[0][1] == "/media/title/movie/603"
    assert rows[3][0] == "div" and rows[3][1] == ""                       # unmatched work: plain row
    assert b.index('id="awards"') < b.index("On your server") if "On your server" in b else True


def test_person_page_hides_the_section_when_none(env):
    client, both = env()
    seed_person(both)
    with client:
        b = main_of(client.get("/media/person/55").text)
    assert awards_section(b) is None
