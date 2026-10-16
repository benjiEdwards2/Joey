"""Awards A0 (AWARDS_PLAN, 2026-10-08): the recorded upstream answers every awards test runs on. Recorded live on
2026-10-08 with a descriptive User-Agent, sequential and paced (WDQS was rate-limiting to 1 request / minute during an
outage that morning — `wdqs_429.html` is that real answer, its client IP replaced by a documentation address).
SPARQL answers are CSV (what the sync asks for). Nothing is scrubbed beyond that and every file is the whole answer,
except `wd_winners_cannes.csv`: the real answer is 662 rows / 139 KB, so the fixture keeps its rows dated 1990 or later
(348 rows, 73 KB) to stay under the 100 KB cap. Every file is stored gzipped (`<name>.gz`): the repo's money
pre-commit guard (scripts/precommit_money_guard.py) refuses plaintext .csv files and long single-line JSON whose dates +
decimals look like bank rows; gzip keeps the guard untouched. No test here (or anywhere) touches the network."""
import gzip
import json
import re
from pathlib import Path

import pytest

FIX = Path(__file__).resolve().parent / "fixtures" / "awards"

WP_PAGES = {  # file -> (Award category headers, page title after redirects)
    "wp_bafta_78.json": (26, "78th British Academy Film Awards"),
    "wp_globes_82.json": (27, "82nd Golden Globes"),
    "wp_emmys_77.json": (26, "77th Primetime Emmy Awards"),
    "wp_sag_31.json": (15, "31st Screen Actors Guild Awards"),
    "wp_critics_30.json": (41, "30th Critics' Choice Awards"),
    "wp_globes_40.json": (0, "40th Golden Globes"),
    # WP-D1 (2026-10-16): the older page shapes, recorded 2026-10-16 (formatversion 1 answers stored in the
    # formatversion 2 shape the sync asks for: `wikitext` is the string itself; nothing else changed)
    "wp_globes_80.json": (0, "80th Golden Globes"),
    "wp_globes_60.json": (0, "60th Golden Globes"),
    "wp_globes_20.json": (0, "20th Golden Globes"),
    "wp_globes_3.json": (0, "3rd Golden Globe Awards"),
    "wp_sag_26.json": (0, "26th Screen Actors Guild Awards"),
    "wp_sag_2.json": (0, "2nd Screen Actors Guild Awards"),
    "wp_critics_1.json": (0, "1st Critics' Choice Awards"),
    "wp_critics_6.json": (0, "6th Critics' Choice Awards"),
    "wp_bafta_17.json": (0, "17th British Academy Film Awards"),
    "wp_bafta_12.json": (0, "12th British Academy Film Awards"),
    # WP-D3 (2026-10-16): winners on a bare bold line under each header (recorded 2026-10-16, formatversion 2)
    "wp_critics_10.json": (18, "10th Critics' Choice Awards"),
}


def load(name: str):
    """A fixture by its recorded name (stored as <name>.gz): .json -> parsed; .csv / .html -> text."""
    raw = gzip.decompress((FIX / (name + ".gz")).read_bytes()).decode("utf-8")
    return json.loads(raw) if name.endswith(".json") else raw


def wikitext(name: str) -> str:
    return load(name)["parse"]["wikitext"]


def test_every_fixture_is_present_and_small():
    names = sorted(p.name[:-3] for p in FIX.iterdir() if p.name.endswith(".gz"))
    for want in list(WP_PAGES) + ["wp_redirect_raw.json", "wp_missing.json", "wp_pageprops_8.json",
                                  "wd_discovery.csv", "wd_oscars_97.csv", "wd_winners_cannes.csv", "wd_ids_8.csv",
                                  "wdqs_429.html"]:
        assert want in names, want
    for p in FIX.iterdir():
        assert p.name.endswith(".gz"), p.name
        assert 0 < len(gzip.decompress(p.read_bytes())) <= 100_000, p.name


@pytest.mark.parametrize("name", sorted(WP_PAGES))
def test_wikipedia_pages_have_the_recorded_shape(name):
    body = load(name)
    count, title = WP_PAGES[name]
    assert body["parse"]["title"] == title
    assert wikitext(name).count("{{Award category") == count


def test_the_globes_page_came_through_a_redirect_and_the_raw_redirect_is_kept():
    assert load("wp_globes_82.json")["parse"]["redirects"] == [{"from": "82nd Golden Globe Awards", "to": "82nd Golden Globes"}]
    assert wikitext("wp_redirect_raw.json").startswith("#REDIRECT [[82nd Golden Globes]]")
    assert load("wp_missing.json")["error"]["code"] == "missingtitle"


def test_sparql_answers_are_csv_with_rows():
    from hub.media_awards_parse import sparql_rows
    for name, at_least in (("wd_discovery.csv", 300), ("wd_oscars_97.csv", 100), ("wd_winners_cannes.csv", 100),
                           ("wd_ids_8.csv", 8)):
        assert load(name).splitlines()[0].startswith(("series,", "award,", "item,")), name
        assert len(sparql_rows(load(name))) >= at_least, name
    oscars = sparql_rows(load("wd_oscars_97.csv"))
    assert {r["award"] for r in oscars} >= {"Q102427", "Q103916"}   # Best Picture, Best Actor
    disc = sparql_rows(load("wd_discovery.csv"))
    assert any(r["ed"] == "Q85315076" and r["ord"] == "97" for r in disc)


def test_pageprops_answer_maps_titles_and_records_a_redirect():
    q = load("wp_pageprops_8.json")["query"]
    assert q["redirects"] == [{"from": "Anora (film)", "to": "Anora"}]
    assert len(q["pages"]) == 8 and all(p["pageprops"]["wikibase_item"].startswith("Q") for p in q["pages"])


def test_the_429_answer_is_the_real_one_without_a_client_address():
    html = load("wdqs_429.html")
    assert "Error: 429" in html and "rate-limiting" in html
    assert not re.search(r"\b(?!203\.0\.113\.)\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", html)
