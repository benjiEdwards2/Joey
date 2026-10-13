"""Awards UI (awards-ui, 2026-10-09): the visual pass on Movies / TV Shows > Awards, poster winner badges, the podium
and the film / person Awards sections. Item 1: the self-drawn ceremony marks (currentColor, labelled or aria-hidden
beside words, an override logo in hub/static/awards/ wins)."""
import re
from pathlib import Path

import jinja2
import pytest

from hub import media_awards_icons as icons

TEMPLATES = Path(__file__).resolve().parents[2] / "hub" / "templates"
ENV = jinja2.Environment(loader=jinja2.FileSystemLoader(str(TEMPLATES)), autoescape=True)


def icon(*args, **kw):
    t = ENV.from_string('{% from "_award_icons.html" import award_icon %}{{ award_icon(*a, **k) }}')
    return t.render(a=args, k=kw)


@pytest.mark.parametrize("name", icons.SHAPES)
def test_every_mark_is_a_labelled_current_colour_svg(name):
    out = icon(name, 20)
    assert out.startswith(f'<svg class="awic awic-{name}" viewBox="0 0 24 24" width="20" height="20" fill="currentColor"')
    assert re.search(r'role="img" aria-label="[^"]+"', out)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(", out)                  # tints from the parent's colour only
    assert "<path" in out or "<circle" in out


def test_ceremony_marks_are_distinct_drawings():
    bodies = {n: re.sub(r'<svg[^>]*>', "", icon(n)) for n in icons.BODY_IDS}
    assert len(set(bodies.values())) == len(icons.BODY_IDS)
    assert re.sub(r'<svg[^>]*>', "", icon("trophy")) not in bodies.values()   # none falls back to the trophy


def test_names_labels_and_decorative_use():
    assert 'aria-label="Oscars"' in icon("oscars") and 'aria-label="Critics&#39; Choice"' in icon("critics")
    assert 'aria-label="Best Picture"' in icon("trophy", label="Best Picture")
    deco = icon("laurel", deco=True)
    assert 'aria-hidden="true"' in deco and "aria-label" not in deco and "role=" not in deco
    assert 'aria-label="Award"' in icon("no-such-mark")                        # unknown -> trophy, still labelled


def test_override_logo_wins_and_keeps_the_name_as_alt(tmp_path, monkeypatch):
    monkeypatch.setattr(icons, "OVERRIDE_DIR", tmp_path)
    icons.override.cache_clear()
    try:
        assert icons.override("oscars") is None
        (tmp_path / "oscars.svg").write_text("<svg/>", encoding="utf-8")
        assert icons.override("oscars") is None                               # cached per process (deploy-only folder)
        icons.override.cache_clear()
        assert icons.override("oscars") == "/static/awards/oscars.svg"
        assert icons.override("../etc") is None and icons.override("trophy") is None
    finally:
        icons.override.cache_clear()
    out = icon("oscars", 24, src="/static/awards/oscars.svg")
    assert out == '<img class="awic awlogo" src="/static/awards/oscars.svg" width="24" height="24" alt="Oscars">'
    assert 'alt=""' in icon("oscars", src="/x.svg", deco=True)


def test_shipped_override_folder_has_only_its_readme():
    files = sorted(p.name for p in icons.OVERRIDE_DIR.iterdir())
    assert files == ["README.md"]                                              # Joey ships no brand files


@pytest.mark.parametrize("name, shape", [
    ("Best Picture", "reel"), ("Outstanding Drama Series", "reel"), ("Palme d'Or", "reel"),
    ("Best Director", "clapper"), ("Outstanding Directing – Feature Film", "clapper"),
    ("Best Actor", "person"), ("Best Actress in a Supporting Role", "person"),
    ("Outstanding Performance by a Cast in a Motion Picture", "person"),
    ("Best Original Screenplay", "nib"), ("Outstanding Writing for a Drama Series", "nib"),
    ("Best Original Score", "trophy"), (None, "trophy")])
def test_category_icons(name, shape):
    assert icons.cat_icon(name) == shape


def test_icon_css_is_a_token_free_recipe():
    css = (TEMPLATES.parent / "static" / "control-surface.css").read_text(encoding="utf-8")
    assert re.search(r"\.awic \{[^}]*flex-shrink: 0", css)


# ---- item 2 (rewritten 2026-10-14, awards ballot): the picker sheet, the control row, the rows ----
# The hero / podium / ceremony-tile row / year stepper / year select of awards-ui are gone; these pin their replacements
# against the contract-shaped context kept in test_awards_ballot_templates.py (the whole-page tests that need the Python
# side live in test_awards_pages.py, WP-C1).
from tests.hub.film_page import whole
from tests.hub.test_awards_ballot_templates import CARD, body, ctx, page as ballot_page, render, row as ballot_row

CSS = (TEMPLATES.parent / "static" / "control-surface.css").read_text(encoding="utf-8")
TAIL = CSS.split("/* Awards ballot (2026-10-14) */", 1)[1]      # ONE dated tail block holds the ballot's rules


def test_sheet_tiles_carry_marks_and_the_picked_one_is_gold():
    s = render("_award_sheet.html", ctx())
    nav = re.search(r'<nav class="awtilegrid" aria-label="Ceremonies">(.*?)</nav>', s, re.S).group(1)
    tiles = re.findall(r'<a class="(awtile[^"]*)" href="[^"]*body=(\w+)[^"]*"[^>]*><svg class="awic awic-(\w+)"[^>]*'
                       r'aria-hidden="true"[^>]*>.*?</svg><span class="awtile-name">([^<]+)</span>'
                       r'<span class="awtile-month">\w+</span></a>', nav, re.S)   # awards-year item 3: + the month line
    assert [(t[1], t[2]) for t in tiles] == [("oscars", "oscars"), ("bafta", "bafta"), ("critics", "critics")]
    assert [t[1] for t in tiles if t[0] == "awtile on"] == ["oscars"]
    assert re.search(r"\.awtile\.on \{[^}]*border-color: var\(--gold\)", CSS)
    assert re.search(r"\.awtile\.on \.awic \{ color: var\(--gold\); \}", CSS)
    assert re.search(r"\.awtilegrid \{ display: grid; grid-template-columns: repeat\(3, minmax\(0, 1fr\)\)", TAIL)   # a grid in the sheet
    assert not re.search(r"\.awtile \{[^}]*(width: 96px|flex: 0 0 96px)", CSS)       # no fixed-width scrolling row any more


def test_override_logo_replaces_a_tile_and_the_picker_mark():
    c = ctx()
    c["bodies"][1]["logo"] = "/static/awards/bafta.png"
    c["picker"] = {**c["picker"], "name": "BAFTA", "body_id": "bafta", "logo": "/static/awards/bafta.png"}
    s = render("_award_sheet.html", c)
    assert '<img class="awic awlogo" src="/static/awards/bafta.png" width="28" height="28" alt="">' \
           '<span class="awtile-name">BAFTA</span>' in s
    assert '<img class="awic awlogo" src="/static/awards/bafta.png" width="18" height="18" alt=""><span class="awpick-name">BAFTA' in s
    assert "awic-oscars" in s                                                # the others keep their drawings


def test_coming_up_has_a_mark_per_ceremony_and_flags_the_next_one():
    p = ballot_page()
    fold = p.split('<div class="stats awcoming">', 1)[1].split("</details>", 1)[0]
    evs = re.findall(r'<span class="awev( is-next)?"><svg class="awic awic-(\w+)"[^>]*aria-hidden="true"', fold)
    assert [e[1] for e in evs] == ["globes", "critics"] and [e for e in evs if e[0]] == [evs[0]]   # exactly one, the soonest
    assert fold.count('<span class="awnext">Next</span>') == 1               # a word, not colour alone


def test_year_strip_current_year_is_gold_and_a_phone_tap_target():
    assert re.search(r"\.awyears \.chip\[aria-current\] \{[^}]*var\(--gold-soft\)[^}]*var\(--gold\)", TAIL)
    assert re.search(r"\.awyears \.chip\.is-off \{ opacity: \.35; \}", TAIL)    # no edition: dim (and aria-disabled in the markup)
    assert re.search(r"@media \(max-width: 767px\) \{ \.awyears \.chip \{ height: 36px; \} \}", TAIL)
    assert "<select" not in render("_award_sheet.html", ctx()) and "awyearform" not in ballot_page()   # the year select is gone


def test_picker_is_a_bottom_sheet_on_a_phone_and_a_dropdown_from_640px():
    sheet = re.search(r"\.awsheet \{([^}]*)\}", TAIL).group(1)
    assert "position: fixed" in sheet and "bottom: 0" in sheet and "overflow-y: auto" in sheet
    assert "env(safe-area-inset-bottom)" in sheet and "var(--tab-lift)" in sheet   # clears the phone tab bar and the home bar
    assert re.search(r"\.awscrim \{[^}]*position: fixed;[^}]*var\(--scrim\)", TAIL)
    wide = re.search(r"@media \(min-width: 640px\) \{(.*?)\n\}", TAIL, re.S).group(1)
    assert re.search(r"\.awsheet \{ position: absolute; top: calc\(100% \+ 8px\);", wide) and "background: transparent" in wide
    row = re.search(r"\.awctl \{([^}]*)\}", TAIL).group(1)
    assert "position: sticky" in row and "top: var(--aw-top)" in row
    assert "--aw-top: 49px" in row and "--aw-top: calc(57px + env(safe-area-inset-top, 0px))" in TAIL   # under the Media bar (E3)
    z = int(re.search(r"z-index: (\d+)", row).group(1))
    assert z < int(re.search(r"\.topbar \{[^}]*z-index: (\d+)", CSS).group(1))      # never over the Media bar
    assert not re.search(r"(backdrop-filter|transform|filter):", row)          # a fixed sheet inside it would be fixed to the row


def test_ballot_css_is_one_dated_block_with_tokens_only():
    assert CSS.count("/* Awards ballot (2026-10-14) */") == 1
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(", TAIL)
    for gone in ("awhero", "awpodium", "awpod", "awwin", "awtally", "awseen", "awtiles", "awstep", "awyearform", "awpill"):
        assert not re.search(rf"\.{gone}\b", CSS), gone
    assert not re.search(r"\.awyear[ ,{]", CSS)                                  # the select's rules; .awyears / .awyearnote stay
    root = CSS.split(":root {", 1)[1].split("}", 1)[0]
    for tok in ("--silver:", "--bronze:", "--silver-soft:", "--bronze-soft:"):
        assert root.count(tok) == 1 and CSS.count(tok) == 1, tok              # the tokens outlive the podium


def test_ballot_layout_css_phone_first_no_sideways_page():
    assert re.search(r"\.awfilters \{[^}]*flex-wrap: nowrap;[^}]*overflow-x: auto;", TAIL)      # scrolls inside its own box
    assert re.search(r"@media \(min-width: 1024px\) \{ \.awfilters \{ flex-wrap: wrap; overflow: visible;", TAIL)
    assert re.search(r"\.awfilm \{ display: grid; grid-template-columns: 56px minmax\(0, 1fr\) auto;", TAIL)   # 56 px poster
    assert re.search(r"\.awfilm\.is-won \{ border-color: var\(--gold-line\); \}", TAIL)
    assert re.search(r"\.awfilm-srv \{ color: var\(--sky\); \}", TAIL)
    assert re.search(r"\.awring \.val \{ stroke: var\(--good\);", TAIL)         # the ring is --good, the words carry the numbers
    assert re.search(r"\.awctl \.awed \{ order: 3; flex: 1 1 100%;", TAIL)      # phone: the edition line takes its own line
    assert re.search(r"\.awfilm \.awdetail \{ grid-column: 1 / -1;", TAIL)


def test_category_cards_have_a_mark_and_gold_winners():
    grid = body(view="categories", ballot=None, cats=[CARD]).split('<div class="awgrid">', 1)[1]
    assert re.search(r'<div class="awcat-head"><svg class="awic awic-person"[^>]*aria-hidden="true"[^>]*>.*?</svg>'
                     r'<div class="awcat-name">Best Actor</div></div>', grid, re.S)
    assert '<span class="awframe is-won' in grid
    assert re.search(r"\.awthumb \.card-pic > img \{[^}]*var\(--line\)", CSS)  # nominees: a faint neutral outline


def test_gold_tokens_are_defined_once_in_root():
    root = CSS.split(":root {", 1)[1].split("}", 1)[0]
    for tok in ("--gold:", "--gold-soft:", "--gold-line:"):
        assert root.count(tok) == 1 and CSS.count(tok) == 1, tok


# ---- item 3: poster winner badges ----
from contextlib import closing  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from hub import media_awards_badges as badges, media_awards_db as adb, media_db  # noqa: E402
from tests.hub.test_awards_db import seed_oscars  # noqa: E402
from tests.hub import test_media_library_pages as lib  # noqa: E402
from tests.hub.test_media_frame import env as frame_env  # noqa: E402,F401  (fixture)


def win(body, cat, rank, year, qid="Q1"):
    return {"qid": qid, "tmdb_movie": None, "tmdb_tv": None, "tvdb": None, "body_id": body, "cat": cat, "rank": rank,
            "year": year}


def test_badge_takes_the_most_prestigious_ceremony_and_counts_the_rest():
    b = badges.badge_of([win("bafta", "Best Film", 0, 2025), win("oscars", "Best Actor", 300, 2025),
                         win("oscars", "Best Picture", 0, 2025), win("sag", "Outstanding Cast", 0, 2025),
                         win("bafta", "Best Editing", 1000, 2025)])
    assert b == {"body_id": "oscars", "logo": None, "more": 2,
                 "label": "Won Best Picture · Oscars 2025 · +2 more ceremonies"}
    assert badges.badge_of([win("cannes", "Palme d'Or", 0, 2024), win("globes", "Best Motion Picture – Drama", 0, 2025)]
                           )["body_id"] == "cannes"                          # Cannes outranks BAFTA / Globes
    assert badges.badge_of([win("wga", "Best Original Screenplay", 0, 2020)])["label"] == \
        "Won Best Original Screenplay · WGA 2020"
    assert badges.badge_of([]) is None
    assert badges.PRESTIGE == ("oscars", "cannes", "bafta", "globes", "emmys", "critics", "sag", "dga", "pga", "wga")


def test_lookup_is_one_query_per_page_winners_only_and_cached(monkeypatch):
    with closing(adb.ensure()) as db:
        seed_oscars(db)
    calls = []
    real = adb.win_rows
    monkeypatch.setattr(adb, "win_rows", lambda *a: calls.append(a) or real(*a))
    badges._cache.clear()
    pairs = [("movie", "tmdb:11"), ("movie", "tmdb:12"), ("movie", "jf:abc")] + [("movie", f"tmdb:{900 + i}")
                                                                                   for i in range(300)]
    got = badges.lookup(pairs)
    assert set(got) == {("movie", "tmdb:11")}                                # Beta (tmdb:12) was only nominated
    assert got[("movie", "tmdb:11")]["label"] == "Won Best Picture · Oscars 2025"
    assert len(calls) == 1                                                    # 303 posters, one query
    badges.lookup(list(reversed(pairs)))
    assert len(calls) == 1                                                    # same set within TTL: cached
    monkeypatch.setattr(badges, "TTL", 0.0)
    badges.lookup(pairs)
    assert len(calls) == 2
    assert badges.lookup(qids=["Q1001", "Q1002", "~gamma"]) == {"Q1001": got[("movie", "tmdb:11")]}
    assert badges.lookup([("tv", "tmdb:11")]) == {}                          # a film id is not a show id


def test_lookup_without_media_db_never_creates_it():
    badges._cache.clear()
    assert badges.lookup([("movie", "tmdb:11")]) == {} and not media_db.db_path().exists()
    rows = badges.attach([{"item_key": "tmdb:11", "kind": "movie"}, {"tmdb_id": 5, "kind": "tv"}, "junk"])
    assert [r["award"] for r in rows] == [None, None]


def test_attach_keys_rows_by_item_key_or_tmdb_id_and_kind():
    with closing(adb.ensure()) as db:
        seed_oscars(db)
    badges._cache.clear()
    rows = badges.attach([{"item_key": "tmdb:11"}, {"tmdb_id": 11, "kind": "movie"}, {"tmdb_id": 11, "kind": "tv"},
                          {"item_key": "jf:x"}, {"tmdb_id": 12}], "movie")
    assert [bool(r["award"]) for r in rows] == [True, True, False, False, False]


def test_library_grid_badges_winners_with_a_gold_frame(frame_env):
    main = frame_env(jellyfin=lib.jelly(), arr=lib.ARRV)
    with closing(adb.ensure()) as db:
        seed_oscars(db)
    badges._cache.clear()
    with TestClient(main.app) as c:
        b = c.get("/media/movies?view=grid&group=0").text.split("<main", 1)[1]
    grid = b.split('class="poster-grid libgrid"', 1)[1]
    alpha = grid.split(">Alpha Film<", 1)[0].rsplit('class="card-poster"', 1)[1]
    assert '<span class="card-pic is-won">' in alpha
    assert re.search(r'<span class="awbadge" role="img" aria-label="Won Best Picture · Oscars 2025" '
                     r'title="Won Best Picture · Oscars 2025"><svg class="awic awic-oscars"[^>]*aria-hidden="true"', alpha)
    bravo = grid.split(">Bravo Film<", 1)[0].rsplit('class="card-poster"', 1)[1]
    assert "is-won" not in bravo and "awbadge" not in bravo                   # a nomination alone: no badge, no frame
    assert grid.count('class="awbadge"') == 1


def test_badge_css_sits_bottom_right_with_tokens():
    assert re.search(r"\.awbadge \{ position: absolute; right: 6px; bottom: 6px;", CSS)
    assert re.search(r"\.card-pic\.is-won > img \{[^}]*var\(--gold\)", CSS)


def test_ballot_row_posters_carry_the_winner_badge_and_a_nominee_none():
    b = body()
    assert 'aria-label="Won Best Picture · Oscars 2025"' in ballot_row("Anora", b)       # the winner's poster
    assert b.count('class="awbadge"') == 1                                                # Conclave / Nickel Boys: nominees only
    conclave = ballot_row("Conclave", b)
    assert "awbadge" not in conclave and "awfilm-pic is-won" not in conclave


from tests.hub import test_media_discover as disc  # noqa: E402
from tests.hub.test_media_discover import env as disc_env  # noqa: E402,F401  (fixture)
from tests.hub.helpers import env as film_env  # noqa: F401  (re-export: defined in tests/hub/helpers.py)


def card_of(html, title):
    return html.split(f">{title}<", 1)[0].rsplit('<span class="card-pic', 1)[1]


def test_discover_cards_badge_winners(disc_env):
    with closing(adb.ensure()) as db:
        adb.upsert_editions(db, "bafta", [{"ordinal": 78, "year": 2025}])
        adb.write_edition(db, "bafta", 78, [{"cat_key": "best-film", "name": "Best Film", "kind": "film", "lead": "work"}],
                          [{"cat_key": "best-film", "work_qid": "Q9002", "work_title": "Film Four", "won": 1, "pos": 0},
                           {"cat_key": "best-film", "work_qid": "Q9003", "work_title": "Film Three", "won": 0, "pos": 1}],
                          {"Q9002": {"qid": "Q9002", "kind": "film", "label": "Film Four", "tmdb_movie": 2},
                           "Q9003": {"qid": "Q9003", "kind": "film", "label": "Film Three", "tmdb_movie": 3}}, "done", "wp")
    badges._cache.clear()
    client, fake = disc_env()
    fake.search_results = {"results": [disc.res(2, "Film Four", media="movie"), disc.res(5, "Film None", media="movie")]}
    with client:
        b = disc.main_of(client.get("/media/discover").text)
        part = client.get("/media/discover/search?q=film").text
    four = card_of(b, "Film Four")
    assert four.startswith(' is-won">') and 'aria-label="Won Best Film · BAFTA 2025"' in four and "awic-bafta" in four
    assert "awbadge" not in card_of(b, "Film Three") and "awbadge" not in card_of(b, "Film Five")
    assert 'aria-label="Won Best Film · BAFTA 2025"' in card_of(part, "Film Four")   # the search partial too
    assert "awbadge" not in card_of(part, "Film None")


def test_film_page_similar_rows_badge_winners(film_env):
    with closing(adb.ensure()) as db:
        seed_oscars(db)                                                       # Alpha (tmdb 11) won Best Picture
    badges._cache.clear()
    client, _ = film_env()
    with client:
        b = whole(client, "/media/title/movie/603").split("<main", 1)[1]
    one = card_of(b, "Similar One")
    assert one.startswith(' is-won">') and 'aria-label="Won Best Picture · Oscars 2025"' in one
    assert "awbadge" not in card_of(b, "Similar Two") and "awbadge" not in card_of(b, "Rec One")


# ---- item 4 (the Most wins podium) removed 2026-10-14: the ballot ranks by wins (the default sort); see the ballot tests ----


# ---- item 5: film / TV and person Awards sections ----
from hub import media_awards_pages as pages  # noqa: E402


def wrow(body, year, won, noms, cats=()):
    return {"body_id": body, "body": body.title(), "ordinal": year - 1900, "year": year, "won": won, "noms": noms,
            "cats": [{"name": c, "won": w, "rank": 0} for c, w in cats]}


def test_film_section_groups_by_ceremony_in_prestige_order_with_tallies():
    rows = [wrow("bafta", 2025, 1, 3, [("Best Film", True)]), wrow("cannes", 2024, 1, 1, [("Palme d'Or", True)]),
            wrow("bafta", 2024, 0, 2), wrow("oscars", 2025, 0, 1)]
    got = pages.section_rows(rows, "movie")
    assert [(g["body_id"], g["tally"]) for g in got] == [("oscars", "1 nomination"), ("cannes", "Won 1 of 1 nomination"),
                                                         ("bafta", "Won 1 of 5 nominations")]
    assert [e["line"] for e in got[2]["editions"]] == ["2025 · Won 1 of 3 nominations", "2024 · 2 nominations"]
    assert got[2]["editions"][1]["href"] == "/media/movies/awards?body=bafta&year=2024" and got[0]["logo"] is None


def test_person_section_groups_and_counts_per_ceremony():
    got = pages.person_rows({"wins": 2, "noms": 3, "rows": [
        {"body_id": "globes", "body": "Golden Globes", "year": 2024, "cat": "Best Actress", "won": True,
         "work_title": "A", "work": {"kind": "film", "tmdb_movie": 5}, "rank": 0},
        {"body_id": "oscars", "body": "Oscars", "year": 2025, "cat": "Best Actress", "won": True, "work_title": "A",
         "work": None, "rank": 0},
        {"body_id": "globes", "body": "Golden Globes", "year": 2023, "cat": "Best Actress", "won": False,
         "work_title": "B", "work": None, "rank": 0}]})
    assert got["head"] == "2 wins · 3 nominations"
    assert [(g["body_id"], g["tally"], [r["lead"] for r in g["rows"]]) for g in got["groups"]] == [
        ("oscars", "1 win · 1 nomination", ["2025 · Best Actress"]),
        ("globes", "1 win · 2 nominations", ["2024 · Best Actress", "2023 · Best Actress"])]
    assert got["groups"][1]["rows"][0]["href"] == "/media/title/movie/5" and got["groups"][1]["rows"][1]["href"] is None
    assert pages.person_rows({"rows": []}) is None


def test_section_pills_say_won_or_nominated_beyond_colour():
    src = (TEMPLATES / "_award_card.html").read_text(encoding="utf-8")
    pill = src.split("{% macro cat_pill(name, won) -%}", 1)[1].split("{%- endmacro %}", 1)[0]
    assert '<span class="vh">Won: </span>' in pill and '<span class="vh">Nominated: </span>' in pill
    assert 'award_icon("laurel", 12, deco=true)' in pill                     # a shape too, not only gold
    assert re.search(r"\.awchip\.is-won \{[^}]*var\(--gold\)", CSS) and re.search(r"\.awchip \{[^}]*var\(--line\)", CSS)


def test_film_section_folds_older_editions_per_ceremony():
    env_ = jinja2.Environment(loader=jinja2.FileSystemLoader(str(TEMPLATES)), autoescape=True)
    g = pages.section_rows([wrow("oscars", y, 0, 1, [("Best Picture", False)]) for y in (2025, 2024, 2023, 2022, 2021)],
                           "movie")[0]
    out = env_.from_string('{% import "_award_card.html" as aw %}{{ aw.film_group(g) }}').render(g=g)
    shown, folded = out.split('<details class="showmore"><summary>Show more · 2</summary>', 1)
    assert shown.count('class="awline"') == 3 and folded.count('class="awline"') == 2
