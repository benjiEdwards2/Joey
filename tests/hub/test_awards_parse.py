"""Awards A2 (AWARDS_PLAN, 2026-10-08): the pure parsers, golden-tested on the recorded A0 answers."""
import pytest

from hub import media_awards_parse as ap
from tests.hub.test_awards_fixtures import load, wikitext


def block(name, label):
    parsed = ap.parse_award_blocks(wikitext(name))
    assert parsed["shape"] == ap.SHAPE_OK
    return next(b for b in parsed["blocks"] if b["label"] == label)


def labels(entries):
    return [((e["work"] or {}).get("label"), [p["label"] for p in e["people"]]) for e in entries]


def test_bafta_best_film_is_conclave_won_with_four_nominees_and_their_people():
    b = block("wp_bafta_78.json", "Best Film")
    assert b["page"] == "BAFTA Award for Best Film"
    win, *noms = b["entries"]
    assert win["won"] and win["lead"] == "work"
    assert win["work"] == {"title": "Conclave (film)", "label": "Conclave"}
    assert [p["label"] for p in win["people"]] == ["Tessa Ross", "Juliette Howell", "Michael A. Jackman"]
    assert [n["work"]["label"] for n in noms] == ["Anora", "The Brutalist", "A Complete Unknown", "Emilia Pérez"]
    assert not any(n["won"] for n in noms) and all(n["people"] for n in noms)
    brutalist = noms[1]["people"]   # unlinked producers are kept as plain names
    assert {"title": None, "label": "Nick Gordon"} in brutalist and {"title": "Brady Corbet", "label": "Brady Corbet"} in brutalist


def test_bafta_acting_rows_lead_with_the_person_and_drop_the_role():
    b = block("wp_bafta_78.json", "Best Actor in a Leading Role")
    win = b["entries"][0]
    assert win["won"] and win["lead"] == "person"
    assert win["people"] == [{"title": "Adrien Brody", "label": "Adrien Brody"}]
    assert win["work"]["title"] == "The Brutalist"
    chalamet = b["entries"][1]                     # "… as [[Bob Dylan]]" is a role, never a nominee
    assert [p["label"] for p in chalamet["people"]] == ["Timothée Chalamet"]


def test_globes_drama_is_the_brutalist_plus_five_and_film_by_heading():
    b = block("wp_globes_82.json", "Best Motion Picture – Drama")
    assert b["kind"] == "film"
    assert labels(b["entries"])[0] == ("The Brutalist", []) and b["entries"][0]["won"]
    assert len(b["entries"]) == 6 and sum(e["won"] for e in b["entries"]) == 1
    tv = block("wp_globes_82.json", "Best Television Series – Drama")
    assert tv["kind"] == "tv" and tv["entries"][0]["work"]["label"] == "Shōgun"   # "(FX / Hulu)" stripped


def test_emmys_drama_winner_is_marked_by_the_double_dagger_and_networks_are_stripped():
    b = block("wp_emmys_77.json", "Outstanding Drama Series")
    assert b["entries"][0]["won"] and b["entries"][0]["work"]["label"] == "The Pitt"
    assert len(b["entries"]) == 8 and sum(e["won"] for e in b["entries"]) == 1
    assert all("(" not in e["work"]["label"] for e in b["entries"])
    d = block("wp_emmys_77.json", "Outstanding Directing for a Comedy Series")["entries"][0]
    assert d["lead"] == "work" and d["work"]["label"] == "The Studio"           # ': "The Oner"' is the episode
    assert [p["label"] for p in d["people"]] == ["Seth Rogen", "Evan Goldberg"]


@pytest.mark.parametrize("name,count", [("wp_bafta_78.json", 26), ("wp_globes_82.json", 27), ("wp_emmys_77.json", 26),
                                        ("wp_sag_31.json", 15), ("wp_critics_30.json", 41)])
def test_every_category_is_parsed_with_exactly_one_or_more_winner(name, count):
    parsed = ap.parse_award_blocks(wikitext(name))
    assert len(parsed["blocks"]) == count
    for b in parsed["blocks"]:
        assert b["entries"], b["label"]
        assert any(e["won"] for e in b["entries"]), b["label"]


def test_mixed_pages_split_film_and_tv_by_section():
    for name, film, tv in (("wp_sag_31.json", 6, 9), ("wp_critics_30.json", 21, 20), ("wp_globes_82.json", 15, 12)):
        kinds = [b["kind"] for b in ap.parse_award_blocks(wikitext(name))["blocks"]]
        assert (kinds.count("film"), kinds.count("tv")) == (film, tv), name


def test_old_globes_page_and_a_redirect_are_reported_not_guessed():
    assert ap.parse_award_blocks(wikitext("wp_globes_40.json")) == {"shape": "none", "redirect": None, "blocks": []}
    got = ap.parse_award_blocks(wikitext("wp_redirect_raw.json"))
    assert got["shape"] == "redirect" and got["redirect"] == "82nd Golden Globes"
    assert ap.parse_award_blocks("")["shape"] == "none"


def test_titles_of_lists_category_pages_works_and_people_once():
    blocks = ap.parse_award_blocks(wikitext("wp_bafta_78.json"))["blocks"]
    titles = ap.titles_of(blocks)
    assert titles[0] == "BAFTA Award for Best Film" and titles.count("Anora") == 1
    assert "Bob Dylan" not in titles and len(titles) == len(set(titles))


def test_oscars_97th_edition_rows_give_26_categories_and_ten_best_picture_films():
    rows = ap.sparql_rows(load("wd_oscars_97.csv"))
    got = ap.wd_nominations(rows, prefixes=("Academy Award for ",))
    cats = {c["cat_key"]: c for c in got["categories"]}
    assert len(cats) == 26
    assert cats["Q102427"]["name"] == "Best Picture" and cats["Q102427"]["lead"] == "work"
    assert cats["Q103916"]["name"] == "Best Actor" and cats["Q103916"]["lead"] == "person"
    bp = [n for n in got["nominations"] if n["cat_key"] == "Q102427" and not n["person_qid"]]
    assert len(bp) == 10 and [n["work_title"] for n in bp if n["won"]] == ["Anora"]
    actor = [n for n in got["nominations"] if n["cat_key"] == "Q103916" and n["won"]]
    assert [(n["person_name"], n["work_title"]) for n in actor] == [("Adrien Brody", "The Brutalist")]
    anora = got["entities"]["Q123185887"]
    assert anora["kind"] == "film" and anora["tmdb_movie"] == 1064213


def test_winners_only_rows_use_the_seed_names():
    rows = [{**r, "won": "1"} for r in ap.sparql_rows(load("wd_winners_cannes.csv")) if (r.get("date") or "")[:4] == "2024"]
    got = ap.wd_nominations(rows, names={"Q179808": "Palme d'Or"})
    palme = [n for n in got["nominations"] if n["cat_key"] == "Q179808"]
    assert [n["work_title"] for n in palme if not n["person_qid"]] == ["Anora"]
    assert next(c for c in got["categories"] if c["cat_key"] == "Q179808")["name"] == "Palme d'Or"


def test_ids_and_pageprops_resolve_titles_to_tmdb_ids():
    qids = ap.qids_from_pageprops(load("wp_pageprops_8.json"))
    assert qids["Anora (film)"] == qids["Anora"] == "Q123185887"      # the redirect maps back to the asked title
    ents = ap.entities_from(load("wd_ids_8.csv"))
    assert ents["Q116701124"]["tmdb_movie"] == 974576 and ents["Q116701124"]["kind"] == "film"   # Conclave
    assert ents["Q56276181"]["kind"] == "tv" and ents["Q56276181"]["tmdb_tv"] == 126308          # Shōgun
    assert ents["Q56276181"]["tvdb"] == 392573
    assert ents["Q104514"]["kind"] == "person" and ents["Q104514"]["tmdb_person"]                 # Adrien Brody


def test_ordinals_and_titles():
    assert [ap.ordinal(n) for n in (1, 2, 3, 4, 11, 12, 13, 21, 22, 23, 97, 101, 111)] == [
        "1st", "2nd", "3rd", "4th", "11th", "12th", "13th", "21st", "22nd", "23rd", "97th", "101st", "111th"]
    assert ap.wp_title("{ord} Academy Awards", 97) == "97th Academy Awards"
    assert ap.slug("Best Motion Picture – Drama") == "best-motion-picture-drama"
    assert ap.slug("Palme d'Or") == "palme-d-or"


def test_entry_details():
    p = ap.parse_award_blocks("{{Award category|#fff|[[X Award for Best Film|Best Film]]}}\n"
                              "* '''''[[A (film)|A]]'' (France)'''\n"
                              "** ''[[B]]'' – [[Jo Bloggs]] and [[Al Smith]]<ref>x</ref>\n"
                              "** {{sortname|Ann|Lee}} – ''[[C (film)|C]]'' as Someone\n")
    a, b, c = p["blocks"][0]["entries"]
    assert a["won"] and a["work"]["label"] == "A" and not a["people"]
    assert [x["label"] for x in b["people"]] == ["Jo Bloggs", "Al Smith"] and not b["won"]
    assert c["lead"] == "person" and c["people"] == [{"title": "Ann Lee", "label": "Ann Lee"}] and c["work"]["label"] == "C"
