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


# ---- item 2: the page layout ----
from tests.hub.test_awards_pages import ALPHA, jelly, page, seeded  # noqa: E402
from tests.hub.test_media_rate import env  # noqa: E402,F401  (env is a fixture)
from hub import media_discover as md  # noqa: E402

CSS = (TEMPLATES.parent / "static" / "control-surface.css").read_text(encoding="utf-8")


def hero_of(b):
    return re.search(r'<section class="sec awhero[^"]*">.*?</section>', b, re.S).group(0)


def test_ceremony_tiles_carry_marks_and_the_picked_one_is_gold(env):
    build, _ = env
    seeded()
    with build(jelly(ALPHA)) as client:
        b = page(client, "/media/movies/awards?body=bafta")
    nav = re.search(r'<nav class="awtiles" aria-label="Ceremonies"><div class="awtiles-row">(.*?)</div></nav>', b, re.S).group(1)
    tiles = re.findall(r'<a class="(awtile[^"]*)" href="[^"]*body=(\w+)"[^>]*><svg class="awic awic-(\w+)"[^>]*'
                       r'aria-hidden="true"[^>]*>.*?</svg><span class="awtile-name">([^<]+)</span></a>', nav, re.S)
    assert [(t[1], t[2]) for t in tiles] == [(x, x) for x in ("oscars", "globes", "bafta", "critics", "sag", "dga", "pga",
                                                              "wga", "cannes")]
    assert [t[1] for t in tiles if t[0] == "awtile on"] == ["bafta"] and "Critics&#39; Choice" in nav
    assert re.search(r"\.awtile\.on \{[^}]*border-color: var\(--gold\)", CSS)
    assert re.search(r"\.awtile\.on \.awic \{ color: var\(--gold\); \}", CSS)
    assert re.search(r"\.awtiles \{[^}]*overflow-x: auto", CSS)                # scrolls inside its own box


def test_override_logo_replaces_a_tile_mark(env, tmp_path, monkeypatch):
    monkeypatch.setattr(icons, "OVERRIDE_DIR", tmp_path)
    icons.override.cache_clear()
    (tmp_path / "bafta.png").write_bytes(b"\x89PNG")
    build, _ = env
    seeded()
    try:
        with build(jelly(ALPHA)) as client:
            b = page(client, "/media/movies/awards")
    finally:
        icons.override.cache_clear()
    assert '<img class="awic awlogo" src="/static/awards/bafta.png" width="28" height="28" alt="">' \
           '<span class="awtile-name">BAFTA</span>' in b
    assert "awic-oscars" in b                                                 # the others keep their drawings


def test_coming_up_has_a_mark_per_ceremony_and_flags_the_next_one(env):
    build, _ = env
    seeded()
    with build(jelly(ALPHA)) as client:
        b = page(client, "/media/movies/awards")
    strip = b.split('<div class="stats awcoming">', 1)[1].split("</section>", 1)[0]
    evs = re.findall(r'<span class="awev( is-next)?"><svg class="awic awic-(\w+)"[^>]*aria-hidden="true"', strip)
    assert len(evs) >= 4 and [e for e in evs if e[0]] == [evs[0]]               # exactly one, the soonest
    assert strip.count('<span class="awnext">Next</span>') == 1                 # a word, not colour alone


def test_year_select_keeps_body_and_not_seen(env):
    build, _ = env
    seeded()
    with build(jelly(ALPHA)) as client:
        b = page(client, "/media/movies/awards?body=oscars&year=2024&unseen=1")
    form = re.search(r'<form class="awyearform" method="get" action="/media/movies/awards">(.*?)</form>', b, re.S).group(1)
    assert '<input type="hidden" name="body" value="oscars"><input type="hidden" name="unseen" value="1">' in form
    assert '<label class="vh" for="awyear">Ceremony year</label>' in form
    assert re.findall(r'<option value="(\d+)"( selected)?>', form) == [("2026", ""), ("2025", ""), ("2024", " selected")]
    assert 'onchange="this.form.submit()"' in form and "<noscript>" in form   # works without JS too
    assert re.search(r"\.awyear\.select \{[^}]*font-size: (1[6-9]|2\d)px", CSS)  # >= 16 px: no zoom on a phone
    assert b.index("‹ 2024") < b.index("awyearform") < b.index("2025 ›") < b.index("97th Academy Awards") \
        if "‹ 2024" in b else b.index("awyearform") < b.index("2025 ›")


def test_hero_is_gold_framed_on_the_winners_backdrop(env, monkeypatch):
    build, _ = env
    seeded()
    with build(jelly({**ALPHA, "backdrop": "jfb:jfalpha"})) as client:
        hero = hero_of(page(client, "/media/movies/awards"))
    assert hero.startswith('<section class="sec awhero has-bd">')
    assert '<img class="awhero-bd" src="/img/jfb:jfalpha?h=1280" alt=""' in hero
    assert '<span class="card-pic awframe is-won">' in hero
    assert re.search(r'<span class="awtally"><svg class="awic awic-laurel"[^>]*aria-hidden="true"[^>]*>.*?</svg>'
                     r'Won 2 of 2 nominations</span>', hero, re.S)
    assert re.search(r'<span class="awseen st-good"><svg[^>]*>.*?</svg>Seen</span>', hero, re.S)
    assert '<div class="microlabel awhero-label">Nominated · ' in hero
    with build(jelly(ALPHA)) as client:                                      # no library backdrop, no Jellyseerr
        hero = hero_of(page(client, "/media/movies/awards"))
    assert hero.startswith('<section class="sec awhero">') and "awhero-bd" not in hero


def test_hero_backdrop_comes_from_the_meta_cache_for_an_off_server_winner(env, monkeypatch):
    build, _ = env
    seeded()
    reads = []
    monkeypatch.setattr(md, "_creds", lambda: ("http://seerr.invalid", "k"))
    monkeypatch.setattr(md, "meta_get", lambda path, ttl=None: reads.append(path) or {"backdropPath": "/wide.jpg",
                                                                                         "posterPath": "/p.jpg"})
    with build(jelly()) as client:                                           # Alpha is not on the server
        hero = hero_of(page(client, "/media/movies/awards"))
    assert '<img class="awhero-bd" src="/img/tmdb:/wide.jpg?h=1280"' in hero and "/api/v1/movie/11" in reads


def test_category_cards_have_a_mark_and_gold_winners(env):
    build, _ = env
    seeded()
    with build(jelly(ALPHA)) as client:
        b = page(client, "/media/movies/awards")
    grid = b.split('<div class="awgrid">', 1)[1]
    assert re.search(r'<div class="awcat-head"><svg class="awic awic-person"[^>]*aria-hidden="true"[^>]*>.*?</svg>'
                     r'<div class="awcat-name">Best Actor</div></div>', grid, re.S)
    assert '<span class="awframe is-won' in grid
    assert re.search(r"\.awthumb \.card-pic > img \{[^}]*var\(--line\)", CSS)  # nominees: a faint neutral outline


def test_gold_tokens_are_defined_once_in_root():
    root = CSS.split(":root {", 1)[1].split("}", 1)[0]
    for tok in ("--gold:", "--gold-soft:", "--gold-line:"):
        assert root.count(tok) == 1 and CSS.count(tok) == 1, tok
