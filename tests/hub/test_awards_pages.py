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
from tests.hub.test_media_rate import env, jelly_data, main_of  # noqa: F401  (env is a fixture)
from tests.hub.test_media_ux4_to_rate_tab import subtabs

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
    assert tabs["movies"][-2:] == [("To rate", "/media/movies/to-rate"), ("Awards", "/media/movies/awards")]
    assert tabs["tv"][-2:] == [("To rate", "/media/tv/to-rate"), ("Awards", "/media/tv/awards")]


def test_tab_is_lit_and_defaults_to_the_latest_synced_year(env):
    build, _ = env
    seeded()
    with build(jelly(ALPHA)) as client:
        html = client.get("/media/movies/awards").text
    tabs = subtabs(html)
    assert [t[0] for t in tabs] == ["My films", "Watchlist", "Tonight", "To rate", "Awards"]
    assert [t[0] for t in tabs if t[2]] == ["Awards"]
    b = main_of(html)
    assert '<h2 class="awtitle">Awards</h2>' in b
    assert '<span class="awyear">2025</span>' in b                         # 2026 is pending: not the default
    assert "97th Academy Awards · 2 Mar 2025 · films of 2024" in b
    assert re.search(r'<a class="chip on" href="/media/movies/awards\?body=oscars" aria-current="page">Oscars</a>', b)
    assert [c for c in re.findall(r'<a class="chip[^"]*" href="/media/movies/awards\?body=(\w+)"', b)] == [
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
    assert '<span class="awyear">2025</span>' in junk and "Oscars</a>" in junk   # bad params fall back to defaults


def test_hero_tally_seen_tags_and_links(env):
    build, _ = env
    seeded()
    with build(jelly(ALPHA)) as client:
        b = page(client, "/media/movies/awards")
    hero = re.search(r'<section class="sec awhero">.*?</section>', b, re.S).group(0)
    assert '<div class="seclabel">Best Picture</div>' in hero
    assert '<a class="awwin" href="/media/item/jfalpha">' in hero and "Won · 2 of 2 nominations" in hero
    assert 'src="/img/jf:jfalpha?h=400' in hero and 'class="poster-tag is-seen">Seen ✓</span>' in hero
    assert '<a class="card-poster awthumb" href="/media/title/movie/12">' in hero      # Beta: off-server, TMDB link
    assert '<div class="card-poster awthumb">' in hero and ">Gamma<" in hero            # unresolved: plain, kept
    grid = b.split('<div class="awgrid">', 1)[1]
    assert '<div class="awcat-name">Best Actor</div>' in grid
    assert re.search(r'<div class="row-title">Ann Actor</div>\s*<div class="row-meta"><span class="st-good">Won</span>'
                     r'<span class="sep"> · </span>Alpha<span class="sep"> · </span><span class="st-good">Seen ✓</span>', grid)
    more = b.split('<details class="showmore awmorecats"><summary>More categories · 1</summary>', 1)[1]
    assert "Best Live Action Short Film" in more


def test_not_seen_hides_the_viewers_played_works_and_dims_their_categories(env):
    build, _ = env
    seeded()
    with build(jelly(ALPHA)) as client:
        b = page(client, "/media/movies/awards?unseen=1")
    assert 'aria-pressed="true">Not seen</a>' in b
    hero = re.search(r'<section class="sec awhero">.*?</section>', b, re.S).group(0)
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
    hero = re.search(r'<section class="sec awhero">.*?</section>', b, re.S).group(0)
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
    assert '<div class="seclabel">Coming up</div>' in b and '<div class="microlabel">JAN</div>' in b
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
    assert "/api/v1/movie/12" in reads and all(p.startswith("/api/v1/") for p in reads)
    assert len(reads) <= 60
    with closing(adb.ensure()) as db:
        assert db.execute("SELECT poster FROM award_entity WHERE qid = 'Q1002'").fetchone()["poster"] == "tmdb:/beta123.jpg"
        assert db.execute("SELECT poster FROM award_entity WHERE qid = 'Q2001'").fetchone()["poster"] == "tmdb:/ann.jpg"
    assert "/img/tmdb:/beta123.jpg?h=" in b                               # the hero's posters land before the render


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
