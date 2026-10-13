"""Awards A4 (AWARDS_PLAN, 2026-10-08): Movies > Awards / TV Shows > Awards — the tab after To rate, body / year
defaults (latest synced), the stepper's bounds, the Not seen filter hiding the viewer's played works, pending wording,
the staleness line, lazy posters through the Jellyseerr meta cache only, no literal colours, no <a> inside .row-title."""
import re
from contextlib import closing
from pathlib import Path

import pytest

from hub import media_awards_db as adb
from hub import media_db, media_discover as md, media_nav
from tests.hub.test_awards_db import seed_oscars
from tests.hub.conftest import main_raw as main_of  # noqa: F401
from tests.hub.test_media_rate import env, jelly_data  # noqa: F401  (env is a fixture)
from tests.hub.test_media_to_rate_pages import subtabs

TEMPLATES = Path(__file__).resolve().parents[2] / "hub" / "templates"
ALPHA = {"added_at": "2024-03-02T10:00:00.0000000Z", "backdrop": None, "community_rating": 7.8, "genres": ["Drama"],
         "item_key": "tmdb:11", "jf_id": "jfalpha", "last_played_at": "2025-12-20T20:00:00.0000000Z", "played": True,
         "poster": "jf:jfalpha", "runtime_min": 118, "title": "Alpha", "year": 2024}


def jelly(*movies):
    return {**jelly_data(), "movies": list(movies)}


def seeded(pending_2026=True, older=True):
    with closing(adb.ensure()) as db:
        seed_oscars(db)
        if older:
            seed_oscars(db, ordinal=96, year=2024, held_on="2024-03-10")
        if pending_2026:
            adb.upsert_editions(db, "oscars", [{"ordinal": 98, "year": 2026}])
        adb.set_sync(db, "last_pass_at", "2026-10-03T01:00:00+00:00")


def page(client, path):
    r = client.get(path)
    assert r.status_code == 200, path
    return main_of(r.text)


def test_sections_list_awards_after_to_rate():
    tabs = {s["id"]: s["tabs"] for s in media_nav.SECTIONS}
    assert tabs["movies"][-2:] == [("To Rate", "/media/movies/to-rate"), ("Awards", "/media/movies/awards")]
    assert tabs["tv"][-2:] == [("To Rate", "/media/tv/to-rate"), ("Awards", "/media/tv/awards")]


def test_tab_is_lit_and_defaults_to_the_latest_synced_year(env):
    build, _ = env
    seeded()
    with build(jelly(ALPHA)) as client:
        html = client.get("/media/movies/awards").text
    tabs = subtabs(html)
    assert [t[0] for t in tabs] == ["My films", "Watchlist", "Tonight", "To Rate", "Awards"]
    assert [t[0] for t in tabs if t[2]] == ["Awards"]
    b = main_of(html)
    assert "<h1>Awards</h1>" in b and "awtitle" not in b   # E3 (U4): the tab label is the H1; no second "Awards" title
    assert '<option value="2025" selected>2025</option>' in b              # 2026 is pending: not the default
    assert '<option value="2026">2026</option>' in b                       # awards-ui: the year is a native select
    assert "97th Academy Awards · 2 Mar 2025 · films of 2024" in b
    # awards-year (2026-10-09): the tiles keep the year the viewer is on
    assert re.search(r'<a class="awtile on" href="/media/movies/awards\?body=oscars&amp;year=2025" aria-current="page">'
                     r'<svg class="awic awic-oscars"[^>]*aria-hidden="true"[^>]*>.*?</svg><span class="awtile-name">Oscars'
                     r'</span><span class="awtile-month">Mar</span></a>', b)   # awards-year item 3: + the month line
    assert [c for c in re.findall(r'<a class="awtile[^"]*" href="/media/movies/awards\?body=(\w+)&amp;year=2025"', b)] == [
        "oscars", "globes", "bafta", "critics", "sag", "dga", "pga", "wga", "cannes"]


def test_stepper_bounds(env):
    build, _ = env
    seeded()
    with build(jelly(ALPHA)) as client:
        mid = page(client, "/media/movies/awards?body=oscars&year=2025")
        old = page(client, "/media/movies/awards?body=oscars&year=2024")
        new = page(client, "/media/movies/awards?body=oscars&year=2026")
        junk = page(client, "/media/movies/awards?body=nope&year=1890")
    assert 'href="/media/movies/awards?body=oscars&amp;year=2024" aria-label="Previous ceremony, 2024">‹ 2024</a>' in mid
    assert 'href="/media/movies/awards?body=oscars&amp;year=2026" aria-label="Next ceremony, 2026">2026 ›</a>' in mid
    assert '<span class="btn btn-glass btn-sm" aria-disabled="true">‹</span>' in old
    assert '<span class="btn btn-glass btn-sm" aria-disabled="true">›</span>' in new
    assert '<p class="empty">Not synced yet</p>' in new                   # pending edition wording
    assert '<option value="2025" selected>2025</option>' in junk and 'Oscars</span><span class="awtile-month">Mar</span></a>' in junk   # bad params -> defaults


def test_hero_tally_seen_tags_and_links(env):
    build, _ = env
    seeded()
    with build(jelly(ALPHA)) as client:
        b = page(client, "/media/movies/awards")
    hero = re.search(r'<section class="sec awhero[^"]*">.*?</section>', b, re.S).group(0)
    assert re.search(r'<span class="awpill is-won"><svg class="awic awic-trophy"[^>]*>.*?</svg>Best Picture</span>', hero)
    assert '<a class="awwin" href="/media/item/jfalpha">' in hero and "Won 2 of 2 nominations" in hero
    assert 'src="/img/jf:jfalpha?h=400' in hero and 'class="poster-tag is-seen">Seen ✓</span>' in hero
    assert '<a class="card-poster awthumb" href="/media/title/movie/12">' in hero      # Beta: off-server, TMDB link
    assert '<div class="card-poster awthumb">' in hero and ">Gamma<" in hero            # unresolved: plain, kept
    grid = b.split('<div class="awgrid">', 1)[1]
    assert '<div class="awcat-name">Best Actor</div>' in grid
    assert re.search(r'<div class="row-title">Ann Actor</div>\s*<div class="row-meta"><span class="aw-won"><svg[^>]*>.*?</svg>Won</span>'
                     r'<span class="sep"> · </span>Alpha<span class="sep"> · </span><span class="st-good">Seen ✓</span>', grid)
    more = b.split('<details class="showmore awmorecats"><summary>More categories · 1</summary>', 1)[1]
    assert "Best Live Action Short Film" in more


def test_not_seen_hides_the_viewers_played_works_and_dims_their_categories(env):
    build, _ = env
    seeded()
    with build(jelly(ALPHA)) as client:
        b = page(client, "/media/movies/awards?unseen=1")
    assert re.search(r'aria-pressed="true"><svg class="ic"[^>]*>.*?</svg>Not seen</a>', b)
    hero = re.search(r'<section class="sec awhero[^"]*">.*?</section>', b, re.S).group(0)
    assert "Alpha" not in hero and ">Beta<" in hero
    assert 'class="panel awcat is-dim"' in b                               # Best Actor: its winner is seen
    with build(jelly({**ALPHA, "played": False})) as client:
        b = page(client, "/media/movies/awards?unseen=1")
    assert "awwin" in b and "Seen ✓" not in b


def test_a_diary_row_counts_as_seen(env):
    build, _ = env
    seeded()
    media_db.add_manual_watch("tmdb:12", "movie", "Beta", 2024, None, "2025-01-01")
    with build(jelly()) as client:
        b = page(client, "/media/movies/awards?unseen=1")
    hero = re.search(r'<section class="sec awhero[^"]*">.*?</section>', b, re.S).group(0)
    assert ">Beta<" not in hero and ">Alpha<" in hero


def test_staleness_line_and_failed_badge(env):
    build, _ = env
    seeded()
    with build(jelly(ALPHA)) as client:
        b = page(client, "/media/movies/awards")
        assert "Updated 3 Oct · 2 of 3 ceremonies" in b and "badge-wait" not in b
        with closing(adb.ensure()) as db:
            adb.set_sync(db, "last_pass_ok", "0")
        b = page(client, "/media/movies/awards")
    assert '<span class="badge badge-wait">Sync failed · retrying</span>' in b


def test_tv_page_lists_tv_bodies_and_says_not_synced_yet(env):
    build, _ = env
    with build(jelly(ALPHA)) as client:
        html = client.get("/media/tv/awards").text
    assert [t[0] for t in subtabs(html) if t[2]] == ["Awards"]
    b = main_of(html)
    assert re.findall(r'href="/media/tv/awards\?body=(\w+)"', b)[:4] == ["globes", "critics", "sag", "emmys"]
    assert '<p class="empty">Not synced yet</p>' in b and "Not synced yet</p>" in b
    assert '<h2 class="seclabel">Coming up</h2>' in b and '<div class="microlabel">JAN</div>' in b
    assert not media_db.db_path().exists()                                 # rendering never creates media.db


def test_coming_up_shows_a_known_date_in_teal(env):
    from datetime import date, timedelta
    build, _ = env
    seeded()
    soon = date.today() + timedelta(days=20)
    with closing(adb.ensure()) as db:
        adb.upsert_editions(db, "oscars", [{"ordinal": 99, "year": soon.year, "held_on": soon.isoformat()}])
    with build(jelly(ALPHA)) as client:
        b = page(client, "/media/movies/awards")
    strip = b.split('<div class="stats awcoming">', 1)[1].split("</section>", 1)[0]
    assert f'<span class="aw-date">Oscars · {soon.day} {soon:%b}</span>' in strip
    assert strip.index("aw-date") < strip.index("Golden Globes") or soon.month == 1


def test_lazy_posters_come_from_the_jellyseerr_meta_cache_only(env, monkeypatch):
    build, _ = env
    seeded()
    reads = []
    monkeypatch.setattr(md, "_creds", lambda: ("http://seerr.invalid", "k"))
    monkeypatch.setattr(md, "meta_get", lambda path, ttl=None: reads.append(path) or {"posterPath": "/beta123.jpg",
                                                                                         "profilePath": "/ann.jpg"})
    import requests
    monkeypatch.setattr(requests, "get", lambda *a, **k: pytest.fail("no live call from an awards page"))
    with build(jelly(ALPHA)) as client:
        b = page(client, "/media/movies/awards")
        again = page(client, "/media/movies/awards")
    assert "/api/v1/movie/12" in reads and all(p.startswith("/api/v1/") for p in reads)
    assert len(reads) <= 60
    with closing(adb.ensure()) as db:
        assert db.execute("SELECT poster FROM award_entity WHERE qid = 'Q1002'").fetchone()["poster"] == "tmdb:/beta123.jpg"
        assert db.execute("SELECT poster FROM award_entity WHERE qid = 'Q2001'").fetchone()["poster"] == "tmdb:/ann.jpg"
    # M-46 / F2 (2026-10-12): no poster read before the render - the BackgroundTask stores them for the next view
    assert "/img/tmdb:/beta123.jpg?h=" not in b and "/img/tmdb:/beta123.jpg?h=" in again


def test_awards_templates_use_tokens_and_whole_link_rows(env):
    for name in ("media_awards.html", "_award_card.html"):
        src = (TEMPLATES / name).read_text(encoding="utf-8")
        assert not re.findall(r"#[0-9a-fA-F]{3,8}\b", " ".join(re.findall(r'style="([^"]*)"', src))), name
        assert "rgb(" not in src and "rgba(" not in src and "style=" not in src, name
    build, _ = env
    seeded()
    with build(jelly(ALPHA)) as client:
        b = page(client, "/media/movies/awards")
    for cls in ("row-title", "awwin-title", "awcat-name"):
        for inner in re.findall(rf'class="{cls}">(.*?)</(?:div|span)>', b, re.S):
            assert "<a" not in inner, (cls, inner)
    assert not re.search(r'<a [^>]*>(?:(?!</a>).)*<a ', b, re.S)            # no link inside a link


# ---- awards-year (2026-10-09): switching ceremony keeps the year; nearest-year fallback + note; "Current year" ----

def seed_globes(years):
    with closing(adb.ensure()) as db:
        adb.upsert_editions(db, "globes", [{"ordinal": y - 1943, "year": y} for y in years])


def test_ceremony_tiles_carry_the_current_year_and_the_unseen_flag(env):
    build, _ = env
    seeded()
    with build(jelly(ALPHA)) as client:
        b = page(client, "/media/movies/awards?body=oscars&year=2024&unseen=1")
    assert re.findall(r'<a class="awtile[^"]*" href="(/media/movies/awards\?body=(?:oscars|globes)[^"]*)"', b) == [
        "/media/movies/awards?body=oscars&amp;year=2024&amp;unseen=1",
        "/media/movies/awards?body=globes&amp;year=2024&amp;unseen=1"]


def test_a_missing_year_lands_on_the_closest_earlier_year_with_a_note(env):
    build, _ = env
    seeded()
    seed_globes([2021, 2023, 2026])
    with build(jelly(ALPHA)) as client:
        earlier = page(client, "/media/movies/awards?body=globes&year=2025")
        later = page(client, "/media/movies/awards?body=globes&year=2019")
        held = page(client, "/media/movies/awards?body=oscars&year=2025")
    assert '<option value="2023" selected>2023</option>' in earlier          # 2023 beats the nearer-by-a-year 2026
    assert '<p class="metaline awyearnote">No Golden Globes in 2025 · showing 2023</p>' in earlier
    assert 'href="/media/movies/awards?body=oscars&amp;year=2023"' in earlier   # the tiles carry the year shown
    assert '<option value="2021" selected>2021</option>' in later            # nothing earlier: the closest later
    assert "No Golden Globes in 2019 · showing 2021" in later
    assert "awyearnote" not in held                                          # the year exists: no note


def test_current_year_chip_links_to_the_latest_synced_year_unless_already_there(env):
    build, _ = env
    seeded()
    with build(jelly(ALPHA)) as client:
        old = page(client, "/media/movies/awards?body=oscars&year=2024&unseen=1")
        latest = page(client, "/media/movies/awards?body=oscars&year=2025")
        default = page(client, "/media/movies/awards?body=oscars")
        pending = page(client, "/media/movies/awards?body=oscars&year=2026")
    assert ('<a class="chip awcur" href="/media/movies/awards?body=oscars&amp;unseen=1" aria-label="Current year, 2025">'
            'Current year</a>') in old
    assert "awcur" not in latest and "awcur" not in default
    assert 'class="chip awcur" href="/media/movies/awards?body=oscars"' in pending   # 2026 is pending: 2025 is current
    assert "awyearnote" not in pending and "awyearnote" not in default


# ---- awards-year item 3 (2026-10-09): the ceremony tiles say the month the ceremony is held ----

def tile_months(b):
    return dict(re.findall(r'<span class="awtile-name">([^<]+)</span><span class="awtile-month">(\w+)</span>', b))


def test_tiles_show_the_month_from_the_selected_years_edition_date(env):
    build, _ = env
    seeded()
    with closing(adb.ensure()) as db:            # an off-season date proves the edition's own date wins
        seed_oscars(db, ordinal=95, year=2023, held_on="2023-04-12")
    with build(jelly(ALPHA)) as client:
        y2023 = tile_months(page(client, "/media/movies/awards?body=oscars&year=2023"))
        y2025 = tile_months(page(client, "/media/movies/awards?body=oscars&year=2025"))
    assert y2023["Oscars"] == "Apr" and y2025["Oscars"] == "Mar"
    assert list(y2025) == ["Oscars", "Golden Globes", "BAFTA", "Critics&#39; Choice", "SAG", "DGA", "PGA", "WGA",
                           "Cannes"]                                       # tile order unchanged, every tile has one


def test_tile_month_falls_back_to_the_usual_month_without_a_date(env):
    build, _ = env
    seeded()                                     # 2026 is pending with no held_on; BAFTA / Globes have no editions
    with build(jelly(ALPHA)) as client:
        b = tile_months(page(client, "/media/movies/awards?body=oscars&year=2026"))
        tv = tile_months(page(client, "/media/tv/awards"))                 # no media data at all
    assert (b["Oscars"], b["BAFTA"], b["Golden Globes"], b["Cannes"]) == ("Mar", "Feb", "Jan", "May")
    assert tv["Emmys"] == "Sep"


def test_the_page_renders_before_any_poster_read_hero_first_after(env, monkeypatch):
    """M-46 / F2 (2026-10-12): no Jellyseerr read on the request path - the posters (hero category first) and a missing
    hero backdrop are handed to the BackgroundTask, which runs after the response."""
    from hub import media_awards_pages as ap
    build, _ = env
    seeded()
    monkeypatch.setattr(md, "_creds", lambda: ("http://seerr.invalid", "k"))
    monkeypatch.setattr(md, "meta_get", lambda *a, **k: pytest.fail("a meta read before the render"))
    queued = []
    monkeypatch.setattr(ap, "fill_later", lambda ents, paths: queued.append(([e["qid"] for e in ents], paths)))
    with build(jelly()) as client:
        b = page(client, "/media/movies/awards")
    assert "awhero" in b and queued
    ents, paths = queued[0]
    assert ents and len(ents) <= ap.POSTER_READS and len(set(ents)) == len(ents)
    assert paths == ["/api/v1/movie/11"]                                  # the off-server winner's backdrop, later
