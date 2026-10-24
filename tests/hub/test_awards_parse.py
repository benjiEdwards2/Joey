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


def test_a_shapeless_page_and_a_redirect_are_reported_not_guessed():
    # WP-D1 (2026-10-16): the 40th Globes page (tables) parses now; prose with no category shape is still "none"
    prose = "Prose only.\n==See also==\n* [[Somewhere]]\n===Notes===\n* a note"
    assert ap.parse_award_blocks(prose) == {"shape": "none", "redirect": None, "blocks": []}
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


# ---- WP-D1 (2026-10-16): the three older page shapes, on real pages recorded 2026-10-16 ----

def parsed(name):
    got = ap.parse_award_blocks(wikitext(name))
    assert got["shape"] == ap.SHAPE_OK and got["redirect"] is None
    return got["blocks"]


def lead_names(b):
    return [(e["won"], e["lead"], (e["work"] or {}).get("label"), [p["label"] for p in e["people"]]) for e in b["entries"]]


@pytest.mark.parametrize("name,count,film,tv", [("wp_globes_80.json", 27, 14, 13), ("wp_globes_60.json", 24, 13, 11),
                                                ("wp_globes_20.json", 18, 14, 4), ("wp_globes_40.json", 26, 15, 11),
                                                ("wp_sag_26.json", 15, 6, 9), ("wp_sag_2.json", 13, 5, 8)])
def test_table_pages_give_one_block_per_header_cell_each_with_one_winner(name, count, film, tv):
    blocks = parsed(name)
    assert len(blocks) == count
    assert ([b["kind"] for b in blocks].count("film"), [b["kind"] for b in blocks].count("tv")) == (film, tv)
    for b in blocks:
        assert b["entries"] and sum(e["won"] for e in b["entries"]) == 1, b["label"]


def test_table_labels_are_the_link_target_without_its_award_prefix_and_captions_are_not_categories():
    blocks = parsed("wp_globes_80.json")
    by = {b["label"]: b for b in blocks}
    drama = by["Best Motion Picture – Drama"]                     # the cell reads "Drama"
    assert drama["page"] == "Golden Globe Award for Best Motion Picture – Drama" and drama["kind"] == "film"
    assert lead_names(drama)[0] == (True, "work", "The Fabelmans", [])
    assert [e["work"]["label"] for e in drama["entries"][1:]] == ["Avatar: The Way of Water", "Elvis", "Tár",
                                                                    "Top Gun: Maverick"]
    actor = by["Best Actor in a Motion Picture – Drama"]          # the cell reads "Actor"
    assert lead_names(actor)[0] == (True, "person", "Elvis", ["Austin Butler"]) and len(actor["entries"]) == 5
    assert "Best Motion Picture" not in by and "Drama" not in by and "Actor" not in by   # caption / fragments
    assert by["Best Television Series – Drama"]["kind"] == "tv"


def test_sag_tables_lead_with_the_actor_and_cast_rows_carry_the_whole_cast():
    by = {b["label"]: b for b in parsed("wp_sag_26.json")}
    lead = by["Outstanding Performance by a Male Actor in a Leading Role"]
    assert lead["page"] == "Screen Actors Guild Award for Outstanding Performance by a Male Actor in a Leading Role"
    assert lead_names(lead)[0] == (True, "person", "Joker", ["Joaquin Phoenix"]) and len(lead["entries"]) == 5
    cast = by["Outstanding Performance by a Cast in a Motion Picture"]   # a colspan=2 cell under a colspan=2 header
    win = cast["entries"][0]
    assert win["won"] and win["lead"] == "work" and win["work"]["label"] == "Parasite" and len(win["people"]) == 10
    early = {b["label"]: b for b in parsed("wp_sag_2.json")}["Outstanding Performance by a Cast in a Motion Picture"]
    assert early["entries"][0]["work"]["label"] == "Apollo 13" and "Tom Hanks" in [
        p["label"] for p in early["entries"][0]["people"]]


def test_globes_1963_keeps_unlinked_full_names_and_both_split_categories_on_one_page():
    blocks = parsed("wp_globes_20.json")
    by = {b["label"]: b for b in blocks}
    assert lead_names(by["Best Motion Picture – Drama"])[0][2] == "Lawrence of Arabia"
    assert len(by["Best Motion Picture – Drama"]["entries"]) == 10
    assert "Best Film Promoting International Understanding" in by           # unlinked, no "Other – " caption prefix
    comedy = [b for b in blocks if b["page"] == "Golden Globe Award for Best Motion Picture – Musical or Comedy"]
    assert [b["entries"][0]["work"]["label"] for b in comedy] == ["That Touch of Mink", "The Music Man"]


def test_unlinked_header_cells_take_their_caption_and_a_winner_written_in_the_cell():
    by = {b["label"]: b for b in parsed("wp_globes_40.json")}
    series = by["Best Television Series – Drama"]                 # "! colspan=2 |Best Television Series" then "!Drama"
    assert series["page"] is None and lead_names(series)[0] == (True, "work", "Hill Street Blues", [])
    assert len(series["entries"]) == 5
    assert "Best Performance in a Television Series – Drama – Actor" in by
    assert "Actor" not in by                                      # three different "Actor" cells never collide


def test_bold_list_pages_give_winners_only_blocks():
    by = {b["label"]: b for b in parsed("wp_critics_6.json")}
    assert len(by) == 15 and all(len(b["entries"]) == 1 and b["entries"][0]["won"] for b in by.values())
    assert lead_names(by["Best Picture"]) == [(True, "work", "Gladiator", [])] and by["Best Picture"]["page"] is None
    assert lead_names(by["Best Actor"]) == [(True, "person", "Gladiator", ["Russell Crowe"])]
    assert "Top 11 films" not in by                               # a heading list is never read on a list-shape page
    first = {b["label"]: b for b in parsed("wp_critics_1.json")}
    assert len(first) == 10 and lead_names(first["Best Picture"])[0][2] == "Sense and Sensibility"
    tie = first["Best Supporting Actor"]["entries"]
    assert [(e["won"], e["people"][0]["label"]) for e in tie] == [(True, "Ed Harris"), (True, "Kevin Spacey")]


def test_heading_pages_bafta_1964_winner_line_nominees_and_person_in_film():
    blocks = parsed("wp_bafta_17.json")
    assert [b["label"] for b in blocks] == ["Best Film", "Best British Film", "Best Foreign Actor", "Best British Actor",
                                            "Best British Actress", "Best Foreign Actress", "Best British Screenplay",
                                            "Best Animated Film"]
    best = blocks[0]
    assert lead_names(best)[0] == (True, "work", "Tom Jones", []) and len(best["entries"]) == 12
    assert best["entries"][0]["work"]["title"] == "Tom Jones (1963 film)" and sum(e["won"] for e in best["entries"]) == 1
    foreign = blocks[2]                                           # ''' ''[[Person]] in [[Film]]'' ''' (all italic)
    assert lead_names(foreign)[0] == (True, "person", "Divorce, Italian Style", ["Marcello Mastroianni"])
    assert lead_names(foreign)[1] == (False, "person", "David and Lisa", ["Howard Da Silva"])
    assert lead_names(blocks[6]) == [(True, "work", "Tom Jones", ["John Osborne"])]
    assert lead_names(blocks[7])[0] == (True, "work", "Automania 2000", [])


def test_heading_pages_bafta_1959_and_globes_1946():
    by = {b["label"]: b for b in parsed("wp_bafta_12.json")}
    assert len(by) == 7 and lead_names(by["Best Foreign Actor"])[0] == (True, "person", "The Defiant Ones",
                                                                       ["Sidney Poitier"])
    assert len(by["Best Foreign Actor"]["entries"]) == 10 and len(by["Best Film"]["entries"]) == 14
    globes = parsed("wp_globes_3.json")                           # "==Winners==": every entry won
    assert len(globes) == 7 and all(e["won"] for b in globes for e in b["entries"])
    first = globes[0]                                             # a linked heading: the stripped target is the label
    assert first["label"] == "Best Motion Picture – Drama" and first["page"].endswith("Best Motion Picture – Drama")
    assert lead_names(first) == [(True, "work", "The Lost Weekend", [])]
    assert lead_names(globes[1]) == [(True, "person", "The Lost Weekend", ["Ray Milland"])]


def test_structural_headings_are_never_categories():
    text = ("==Winners and nominees==\n===Film===\n====Best Picture====\n'''''[[A]]'''''\n* ''[[B]]''\n"
            "====Best Actor====\n'''[[Jo Bloggs]] in ''[[A]]'''''\n* Ann Lee in ''[[B]]''\n"
            "===Multiple nominations===\n* ''[[A]]'' – 3\n===Presenters===\n* [[Some Host]]\n"
            "===Empty Category===\nNo list here.\n==See also==\n* [[Elsewhere]]\n==References==\n* [[Ref]]\n")
    blocks = ap.parse_award_blocks(text)["blocks"]
    assert [(b["label"], b["kind"]) for b in blocks] == [("Best Picture", "film"), ("Best Actor", "film")]
    assert lead_names(blocks[1]) == [(True, "person", "A", ["Jo Bloggs"]), (False, "person", "B", ["Ann Lee"])]


def test_mixed_shapes_take_every_block_in_page_order_once():
    text = ("{{Award category|#fff|[[X Award for Best Film|Best Film]]}}\n* '''''[[A]]'''''\n** ''[[B]]''\n"
            "{| class=wikitable\n|-\n! [[X Award for Best Film|Film]] !! [[X Award for Best Director|Director]]\n|-\n"
            "| valign=top |\n* '''''[[A]]'''''\n| valign=top |\n* '''[[Jo Bloggs]] – ''[[A]]'''''\n"
            "** [[Al Smith]] – ''[[B]]''\n|}\n* '''Best Song:'''\n** \"Tune\" – ''[[A]]''\n")
    blocks = ap.parse_award_blocks(text)["blocks"]
    assert [(b["label"], b["page"]) for b in blocks] == [("Best Film", "X Award for Best Film"),
                                                         ("Best Director", "X Award for Best Director"),
                                                         ("Best Song", None)]
    assert len(blocks[0]["entries"]) == 2                         # the table's duplicate Best Film cell is dropped
    assert [e["won"] for e in blocks[1]["entries"]] == [True, False] and blocks[2]["entries"][0]["won"]


# ---- WP-D3 (2026-10-16): the winner on a bare bold line inside an {{Award category}} block ----

def test_critics_2005_winners_sit_on_a_bare_bold_line_under_each_header():
    blocks = parsed("wp_critics_10.json")
    assert len(blocks) == 18
    for b in blocks:                                              # one winner, first, then the `*` nominees
        assert [e["won"] for e in b["entries"]] == [True] + [False] * (len(b["entries"]) - 1), b["label"]
        assert b["entries"][0]["pos"] == 0
    by = {b["label"]: b for b in blocks}
    assert lead_names(by["Best Picture"])[0] == (True, "work", "Sideways", [])     # '''''[[Sideways]]'''''
    assert len(by["Best Picture"]["entries"]) == 10
    assert lead_names(by["Best Actor"])[0] == (True, "person", "Ray", ["Jamie Foxx"])   # '''[[Jamie Foxx]] – ''[[Ray]]'''''


def test_a_bare_bold_winner_line_never_double_marks_and_other_bare_lines_stay_ignored():
    text = ("{{Award category|#fff|[[X Award for Best Film|Best Film]]}}\n'''''[[A (film)|A]]'''''\n"
            "* ''[[B]]''\n* ''[[C]]''\n[[File:A.jpg|thumb]]\n{{Clear}}\n<ref>x</ref>\n''[[D]]''\n"
            "{{Award category|#fff|[[X Award for Best Actor|Best Actor]]}}\n'''[[Jo Bloggs]] – ''[[A (film)|A]]'''''\n"
            "* [[Al Smith]] – ''[[B]]''\n")
    film, actor = ap.parse_award_blocks(text)["blocks"]
    assert lead_names(film) == [(True, "work", "A", []), (False, "work", "B", []), (False, "work", "C", [])]
    assert lead_names(actor) == [(True, "person", "A", ["Jo Bloggs"]), (False, "person", "B", ["Al Smith"])]


@pytest.mark.parametrize("name,winners", [("wp_globes_82.json", 27), ("wp_bafta_78.json", 26), ("wp_emmys_77.json", 26),
                                          ("wp_sag_31.json", 15), ("wp_critics_30.json", 42)])
def test_award_category_pages_keep_their_winner_counts(name, winners):
    assert sum(e["won"] for b in parsed(name) for e in b["entries"]) == winners


# ---- JY-152 (2026-10-24): the parser leftovers ----

def test_bafta_1966_award_category_headers_inside_table_cells_each_carry_one_winner():
    blocks = parsed("wp_bafta_19.json")
    assert len(blocks) == 18 and all(sum(e["won"] for e in b["entries"]) == 1 for b in blocks)
    best = blocks[0]
    assert (best["label"], best["page"]) == ("Best Film", "BAFTA Award for Best Film")
    assert lead_names(best)[0] == (True, "work", "My Fair Lady", ["George Cukor"]) and len(best["entries"]) == 5
    assert [e["won"] for e in best["entries"]] == [True, False, False, False, False]
