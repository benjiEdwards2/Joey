"""JY-294 (option A, B. 2026-11-06): the person page's Awards section opens with a carousel of the works they were
nominated for or won with - poster, a gold "N won" / neutral "N nom" ribbon, the award lines - and folds the
per-ceremony list under "All awards by ceremony". media.db and the page's own credits only; the TV keeps #awards hidden."""
import re
from pathlib import Path

from hub import media_awards_pages as pages
from tests.hub.conftest import main_of  # noqa: F401
from tests.hub.helpers import env  # noqa: F401
from tests.hub.test_awards_sections import awards_section, three_bodies
from tests.hub.test_media_person import seed as seed_person
from tests.hub.tv_css import design_px

ROOT = Path(__file__).resolve().parents[2]


def row(body, year, cat, won, title, ent=None):
    return {"body_id": body, "body": body.title(), "year": year, "cat": cat, "won": won, "work_title": title,
            "work": ent, "rank": 0}


def test_works_group_count_and_order():
    a = {"qid": "Q1", "kind": "film", "tmdb_movie": 5, "poster": "tmdb:/a.jpg"}
    b = {"qid": "Q2", "kind": "tv", "tmdb_tv": 9, "poster": None}
    sec = pages.person_rows({"wins": 2, "noms": 5, "rows": [
        row("oscars", 2020, "Best Actress", False, "A", a), row("globes", 2021, "Best Actress", True, "A", a),
        row("globes", 2021, "Best Actress", True, "A", a),                 # the same category twice counts once
        row("emmys", 2022, "Lead Actress", True, "B", b), row("emmys", 2023, "Lead Actress", False, "B", b),
        row("bafta", 2019, "Best Actress", False, "C"), row("sag", 2024, "Ensemble", False, "")]})
    got = pages.person_works(sec, {("tv", 9): "tmdb:/b.jpg"})
    assert [(w["title"], w["ribbon"], w["noms"]) for w in got] == [("B", "1 won", 2), ("A", "1 won", 2), ("C", "1 nom", 1)]
    assert got[0]["poster"] == "tmdb:/b.jpg" and got[0]["href"] == "/media/title/tv/9"   # credits poster fallback
    assert got[1]["poster"] == "tmdb:/a.jpg" and got[2]["poster"] is None and got[2]["href"] is None
    assert [(c["text"], c["won"]) for c in got[1]["lines"]] == [("Globes 2021 · Best Actress", True),
                                                                ("Oscars 2020 · Best Actress", False)]
    assert pages.person_works(None) == [] and pages.person_works({"rows": []}) == []


def test_works_fold_lines_past_three():
    sec = pages.person_rows({"wins": 0, "noms": 5, "rows": [row("oscars", y, "Best Actor", False, "A") for y in
                                                             (2020, 2021, 2022, 2023, 2024)]})
    w = pages.person_works(sec)[0]
    assert [c["text"] for c in w["lines"]] == ["Oscars 2024 · Best Actor", "Oscars 2023 · Best Actor",
                                               "Oscars 2022 · Best Actor"] and w["more"] == 2


def test_person_page_draws_the_carousel_and_folds_the_list(env):
    three_bodies()
    client, both = env()
    seed_person(both)
    with client:
        b = main_of(client.get("/media/person/55").text)
    sec = awards_section(b)
    car, rest = sec.split('<details class="showmore awall"><summary>All awards by ceremony</summary>', 1)
    cards = re.findall(r'<(a|div) class="card-poster awwork"(?: href="([^"]*)")?><span class="card-pic( is-won)?">'
                       r'<img[^>]*src="/img/([^"?]*)\?[^>]*><span class="poster-tag awribbon( is-won)?">([^<]+)</span>'
                       r'</span><span class="row-title">([^<]+)</span>', car)
    assert [(c[0], c[1], c[3], c[5], c[6]) for c in cards] == [
        ("a", "/media/title/movie/603", "tmdb:/hl.jpg", "1 won", "Harbour Lights"),   # credits poster
        ("div", "", "none", "1 won", "Unlinked"), ("a", "/media/title/movie/604", "none", "1 nom", "Other Film")]
    assert cards[0][2] == " is-won" and cards[2][2] == "" and cards[2][4] == ""
    assert ('<span class="awwork-line is-won">BAFTA 2025 · Best Actress in a Leading Role '
            '<span class="awwork-word">Won</span></span>') in car                    # the word shows, not only gold
    assert '<span class="awwork-line">Oscars 2025 · Best Actor <span class="awwork-word">Nominated</span></span>' in car
    assert rest.count('class="awline"') == 4 and 'class="awgroups"' in rest     # the list, folded
    assert car.index('<p class="metaline">2 wins · 4 nominations</p>') < car.index('class="carousel awworks"')


def test_css_ribbons_and_tv_keeps_awards_hidden():
    css = (ROOT / "hub" / "static" / "control-surface.css").read_text(encoding="utf-8")
    assert re.search(r"\.poster-tag\.awribbon\.is-won \{[^}]*var\(--gold\)", css)
    assert re.search(r"\.awwork-line\.is-won \{[^}]*var\(--gold\)", css)
    tv = design_px((ROOT / "hub" / "static" / "tv.css").read_text(encoding="utf-8"))
    hide = next(line for line in tv.splitlines() if "html.tv #awards" in line)
    assert hide.rstrip().endswith("{ display: none; }")                        # Q3 default: the TV keeps as is
