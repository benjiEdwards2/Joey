"""WP E7 (2026-10-13): the Awards page's weight - the first screen (tiles, Coming up, stepper, hero, podium, the first
FIRST_CARDS category cards) is the page, every other card loads through ONE htmx request that replaces a sentinel
(no-JS: a plain "All categories" link to ?all=1); category cards use content-visibility; nominee / winner posters are
lazy, async and at the 120 px fetch size. Awards ballot (2026-10-14): the cards are the categories view (`v=categories`);
no hero / podium (B5), so the headline category is the first card."""
import re
from contextlib import closing
from pathlib import Path

from hub import media_awards_db as adb
from hub import media_awards_pages as ap
from tests.hub.test_awards_db import FILM, FILM2
from tests.hub.test_awards_pages import ALPHA, jelly, page
from tests.hub.test_media_rate import env  # noqa: F401  (env is a fixture)

ROOT = Path(__file__).resolve().parents[2]
CORE = [f"Best Core {i}" for i in range(1, 7)]           # six core cards after the headline: three on the page
MORE = ["Best Short A", "Best Short B"]
HEAD = ["Best Picture"]
CATS = "/media/movies/awards?body=oscars&year=2025&v=categories"


def seed_big(core=6, more=2):
    """A 97th Oscars with a hero, `core` core categories and `more` folded ones (explicit rank / grp)."""
    cats = [{"cat_key": "H", "name": "Best Picture", "kind": "film", "lead": "work", "rank": 0, "grp": "core"}]
    noms = [{"cat_key": "H", "work_qid": "Q1001", "work_title": "Alpha", "won": 1, "pos": 0},
            {"cat_key": "H", "work_qid": "Q1002", "work_title": "Beta", "won": 0, "pos": 1}]
    for i, name in enumerate(CORE[:core] + MORE[:more]):
        key, grp = f"K{i}", ("core" if i < core else "more")
        cats.append({"cat_key": key, "name": name, "kind": "film", "lead": "work", "rank": i + 1, "grp": grp})
        noms += [{"cat_key": key, "work_qid": "Q1001", "work_title": "Alpha", "won": 1, "pos": 0},
                 {"cat_key": key, "work_qid": "Q1002", "work_title": "Beta", "won": int(i < 2), "pos": 1},
                 {"cat_key": key, "work_qid": f"~x{i}", "work_title": f"Extra {i}", "won": 0, "pos": 2}]
    with closing(adb.ensure()) as db:
        adb.upsert_editions(db, "oscars", [{"ordinal": 97, "year": 2025, "held_on": "2025-03-02", "wd_qid": "Q85315076"}])
        adb.write_edition(db, "oscars", 97, cats, noms, {e["qid"]: e for e in (FILM, FILM2)}, "done", "wd")
        adb.set_sync(db, "last_pass_at", "2026-10-03T01:00:00+00:00")


def names(html):
    return re.findall(r'<div class="awcat-name">([^<]+)</div>', html)


def test_first_screen_has_four_cards_and_one_sentinel(env):
    build, _ = env
    seed_big()
    with build(jelly(ALPHA)) as client:
        b = page(client, CATS)
    assert names(b) == HEAD + CORE[:3]
    assert "awhero" not in b and "awpodium" not in b                    # B5 (2026-10-14): no hero, no podium
    assert "More categories" not in b and CORE[3] not in b
    sentinels = re.findall(r'<div class="awrest"[^>]*>', b)
    assert len(sentinels) == 1
    s = sentinels[0]
    assert 'hx-get="/media/movies/awards/part/categories?body=oscars&amp;year=2025&amp;v=categories"' in s
    assert 'hx-trigger="revealed"' in s and 'hx-swap="outerHTML"' in s
    assert ('<a class="btn btn-glass btn-sm" href="/media/movies/awards?body=oscars&amp;year=2025&amp;v=categories&amp;'
            'all=1">All categories</a>') in b


def test_the_sentinel_carries_the_unseen_filter_and_the_paths(env):
    build, _ = env
    seed_big()
    with build(jelly(ALPHA)) as client:
        b = page(client, CATS + "&unseen=1")                               # the old flag is written f=unseen
    assert 'hx-get="/media/movies/awards/part/categories?body=oscars&amp;year=2025&amp;v=categories&amp;f=unseen"' in b
    assert 'href="/media/movies/awards?body=oscars&amp;year=2025&amp;v=categories&amp;f=unseen&amp;all=1">All categories</a>' in b
    assert ap.PARTS == {"movie": "/media/movies/awards/part/categories", "tv": "/media/tv/awards/part/categories"}


def test_the_part_brings_exactly_the_rest_and_nothing_else(env):
    build, _ = env
    seed_big()
    with build(jelly(ALPHA)) as client:
        first = names(page(client, CATS))
        r = client.get("/media/movies/awards/part/categories?body=oscars&year=2025&v=categories")
        whole = names(page(client, CATS + "&all=1"))
    assert r.status_code == 200
    part = r.text
    assert "<html" not in part and "<body" not in part                   # a bare fragment
    assert names(part) == CORE[3:] + MORE
    assert '<details class="showmore awmorecats"><summary>More categories · 2</summary>' in part
    assert part.count('class="awgrid awgrid-rest"') == 1
    assert first + names(part) == whole                                  # same cards, same order, as the whole page


def test_all_renders_everything_as_before_with_no_sentinel(env):
    build, _ = env
    seed_big()
    with build(jelly(ALPHA)) as client:
        b = page(client, CATS + "&all=1")
    assert names(b) == HEAD + CORE + MORE and "awrest" not in b
    assert '<details class="showmore awmorecats"><summary>More categories · 2</summary>' in b


def test_nothing_to_defer_means_no_sentinel(env):
    build, _ = env
    seed_big(core=3, more=0)
    with build(jelly(ALPHA)) as client:
        b = page(client, CATS)
        part = client.get("/media/movies/awards/part/categories?body=oscars&year=2025")
    assert names(b) == HEAD + CORE[:3] and "awrest" not in b and "hx-trigger" not in b
    assert part.status_code == 200 and part.text.strip() == ""


def test_the_part_follows_the_unseen_filter_and_survives_junk(env):
    build, _ = env
    seed_big()
    with build(jelly(ALPHA)) as client:                               # Alpha is seen: its winner cards are dimmed
        part = client.get("/media/movies/awards/part/categories?body=oscars&year=2025&unseen=1").text
        new = client.get("/media/movies/awards/part/categories?body=oscars&year=2025&v=categories&f=unseen").text
        nothing = client.get("/media/movies/awards/part/categories?body=bafta&year=1890")
        junk = client.get("/media/tv/awards/part/categories?body=%3Cb%3E&year=zz&f=%3Ci%3E")
    assert 'class="panel awcat is-dim"' in part and ">Alpha<" not in part
    assert new == part                                                 # f=unseen is the old unseen=1
    assert nothing.status_code == 200 and nothing.text.strip() == ""
    assert junk.status_code == 200 and "<b>" not in junk.text and "<i>" not in junk.text


def test_posters_are_lazy_async_and_thumbnail_sized(env):
    build, _ = env
    seed_big()
    with build(jelly(ALPHA)) as client:
        b = page(client, CATS + "&all=1")
        part = client.get("/media/movies/awards/part/categories?body=oscars&year=2025").text
    for html in (b, part):
        imgs = re.findall(r'<img class="poster[^>]*>', html)
        assert imgs and all('loading="lazy"' in i and 'decoding="async"' in i for i in imgs)
    cards = b.split('<div class="awgrid">', 1)[1]            # category cards only
    assert "h=240" not in cards and "h=120" in cards
    assert "h=240" not in part and "h=120" in part
    assert re.search(r'<img class="poster row-poster" src="/img/[^"]*h=120', b)       # the winner row's poster


def test_card_templates_draw_posters_through_the_poster_macro():
    src = (ROOT / "hub" / "templates" / "_award_card.html").read_text(encoding="utf-8")
    assert "<img" not in src                                                   # no hand-rolled <img> in the card pieces
    assert 'poster(c.poster, c.title, h, "row-poster")' in src
    macro = (ROOT / "hub" / "templates" / "_poster.html").read_text(encoding="utf-8")
    assert 'loading="lazy"' in macro and 'decoding="async"' in macro


def test_css_lets_the_browser_skip_off_screen_category_cards():
    css = (ROOT / "hub" / "static" / "control-surface.css").read_text(encoding="utf-8")
    block = css.split("/* ---- E7 awards (2026-10-13) ---- */", 1)[1]
    assert re.search(r"\.awcat \{[^}]*content-visibility: auto;[^}]*contain-intrinsic-size: auto 320px;", block)
