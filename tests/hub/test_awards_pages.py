"""Awards A4 (AWARDS_PLAN, 2026-10-08): Movies > Awards / TV Shows > Awards — the tab after To rate, body / year
defaults (latest synced), the stepper's bounds, the Not seen filter hiding the viewer's played works, pending wording,
the staleness line, lazy posters through the Jellyseerr meta cache only, no literal colours, no <a> inside .row-title.
Awards ballot (WP-C1, 2026-10-14): the Python behaviour is asserted on the context (`awards_ctx`), not on markup, so the
ballot templates (WP-C2) can change the page; the ballot itself is tested in test_awards_ballot.py."""
import re
from contextlib import closing
from pathlib import Path

import pytest

from hub import media_awards_db as adb
from hub import media_awards_pages as ap
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


def ctx(body="", year="", unseen=False, data=None, kind="movie", view="both", show_all=False, **state):
    """The page's context as `GET /media/<kind>/awards?body&year&...` builds it (the first screen by default)."""
    return ap.awards_ctx(kind, body, year, unseen, data if data is not None else jelly(ALPHA), view,
                         show_all=show_all, **state)[0]


def hrefs(items):
    return [x["href"] for x in items]


def test_sections_list_awards_after_to_rate():
    tabs = {s["id"]: s["tabs"] for s in media_nav.SECTIONS}
    assert tabs["movies"][-2:] == [("To rate", "/media/movies/to-rate"), ("Awards", "/media/movies/awards")]   # nav-tidy: sentence case
    assert tabs["tv"][-2:] == [("To rate", "/media/tv/to-rate"), ("Awards", "/media/tv/awards")]


def test_tab_is_lit_and_defaults_to_the_latest_synced_year(env):
    build, _ = env
    seeded()
    with build(jelly(ALPHA)) as client:
        html = client.get("/media/movies/awards").text
    tabs = subtabs(html)
    assert [t[0] for t in tabs] == ["My films", "To rate", "Awards"]   # nav-tidy (2026-10-13)
    assert [t[0] for t in tabs if t[2]] == ["Awards"]
    b = main_of(html)
    assert "<h1>Awards</h1>" in b and "awtitle" not in b   # E3 (U4): the tab label is the H1; no second "Awards" title
    c = ctx()
    assert (c["body"], c["year"], c["years"]) == ("oscars", 2025, [2026, 2025, 2024])   # 2026 is pending: not the default
    assert c["edition_line"] == "97th Academy Awards · 2 Mar 2025 · films of 2024"
    # awards-year (2026-10-09): the ceremony links keep the year the viewer is on
    assert [(x["id"], x["on"], x["href"]) for x in c["bodies"]][:2] == [
        ("oscars", True, "/media/movies/awards?body=oscars&year=2025"),
        ("globes", False, "/media/movies/awards?body=globes&year=2025")]
    assert [x["id"] for x in c["bodies"]] == ["oscars", "globes", "bafta", "critics", "sag", "dga", "pga", "wga", "cannes"]


def test_stepper_bounds(env):
    seeded()
    mid, old, new = ctx("oscars", "2025"), ctx("oscars", "2024"), ctx("oscars", "2026")
    junk = ctx("nope", "1890")
    assert mid["prev"] == {"year": 2024, "href": "/media/movies/awards?body=oscars&year=2024"}
    assert mid["next"] == {"year": 2026, "href": "/media/movies/awards?body=oscars&year=2026"}
    assert old["prev"] is None and new["next"] is None
    assert new["empty"] == "Not synced yet" and new["ballot"]["empty"] == "Not synced yet"   # pending edition wording
    assert (junk["body"], junk["year"], junk["year_note"]) == ("oscars", 2025, None)        # bad params -> defaults


def test_categories_view_cards_tally_seen_and_links(env):
    """B5 (2026-10-14): no hero - the headline category is the first card of the categories view."""
    seeded()
    c = ctx(v="categories")
    assert [x["name"] for x in c["cats"]] == ["Best Picture", "Best Actor"] and c["ballot"] is None
    bp = c["cats"][0]
    assert [(x["title"], x["won"], x["seen"], x["href"]) for x in bp["cards"]] == [
        ("Alpha", True, True, "/media/item/jfalpha"), ("Beta", False, False, "/media/title/movie/12"),
        ("Gamma", False, False, None), ("Delta", False, False, None)]                  # unresolved: plain, kept
    assert bp["cards"][0]["poster"] == "jf:jfalpha" and bp["icon"] == "reel"
    actor = c["cats"][1]["winners"][0]
    assert (actor["title"], actor["sub"], actor["seen"], actor["href"]) == ("Ann Actor", "Alpha", True,
                                                                           "/media/person/501")
    assert c["more"] == [] and c["rest"] == 1                                          # E7: the short comes in the part
    every = ctx(v="categories", show_all=True)                                        # ... or all at once (?all=1)
    assert [x["name"] for x in every["more"]] == ["Best Live Action Short Film"] and every["rest"] == 0


def test_not_seen_hides_the_viewers_played_works_and_dims_their_categories(env):
    seeded()
    films = ctx(f="unseen")["ballot"]
    assert [r["title"] for r in films["rows"]] == ["Beta", "Delta", "Gamma"] and films["hidden_seen"] == 1
    cats = ctx(v="categories", unseen=True)                                # the old ?unseen=1 link
    assert cats["unseen"] is True
    assert [x["title"] for x in cats["cats"][0]["cards"]] == ["Beta", "Gamma", "Delta"]
    assert cats["cats"][1]["dim"] is True                                  # Best Actor: its winner is seen
    played_not = ctx(f="unseen", data=jelly({**ALPHA, "played": False}))["ballot"]
    assert [r["title"] for r in played_not["rows"]][0] == "Alpha" and played_not["hidden_seen"] == 0


def test_a_diary_row_counts_as_seen(env):
    seeded()
    media_db.add_manual_watch("tmdb:12", "movie", "Beta", 2024, None, "2025-01-01")
    rows = ctx(f="unseen", data=jelly())["ballot"]["rows"]
    assert "Beta" not in [r["title"] for r in rows] and rows[0]["title"] == "Alpha"


def test_staleness_line_and_failed_badge(env):
    seeded()
    assert ctx()["sync"] == {"text": "Updated 3 Oct · 2 of 3 ceremonies", "failed": False}
    with closing(adb.ensure()) as db:
        adb.set_sync(db, "last_pass_ok", "0")
    assert ctx()["sync"]["failed"] is True


def test_tv_page_lists_tv_bodies_and_says_not_synced_yet(env):
    build, _ = env
    with build(jelly(ALPHA)) as client:
        html = client.get("/media/tv/awards").text
    assert [t[0] for t in subtabs(html) if t[2]] == ["Awards"]
    c = ctx(kind="tv")
    assert [x["id"] for x in c["bodies"]][:4] == ["globes", "critics", "sag", "emmys"]
    assert c["bodies"][0]["href"] == "/media/tv/awards?body=globes"
    assert c["empty"] == "Not synced yet" and c["ballot"]["empty"] == "Not synced yet" and c["years_list"] == []
    assert any(m["month"] == "JAN" for m in c["coming"])
    assert not media_db.db_path().exists()                                 # rendering never creates media.db


def test_coming_up_shows_a_known_date(env):
    from datetime import date, timedelta
    seeded()
    soon = date.today() + timedelta(days=20)
    with closing(adb.ensure()) as db:
        adb.upsert_editions(db, "oscars", [{"ordinal": 99, "year": soon.year, "held_on": soon.isoformat()}])
    events = [e for m in ctx()["coming"] for e in m["events"]]
    oscars = next(e for e in events if e["body_id"] == "oscars")
    assert oscars["date"] == f"{soon.day} {soon:%b}" and oscars["name"] == "Oscars"
    assert events[0]["next"] and not any(e["next"] for e in events[1:])


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
        page(client, "/media/movies/awards")
    assert "/api/v1/movie/12" in reads and all(p.startswith("/api/v1/") for p in reads)
    assert len(reads) <= 60
    with closing(adb.ensure()) as db:
        assert db.execute("SELECT poster FROM award_entity WHERE qid = 'Q1002'").fetchone()["poster"] == "tmdb:/beta123.jpg"
        assert db.execute("SELECT poster FROM award_entity WHERE qid = 'Q2001'").fetchone()["poster"] == "tmdb:/ann.jpg"
    # M-46 / F2 (2026-10-12): no poster read before the render - the BackgroundTask stores them for the next view
    assert next(r for r in ctx()["ballot"]["rows"] if r["title"] == "Beta")["poster"] == "tmdb:/beta123.jpg"


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
    seeded()
    c = ctx("oscars", "2024", unseen=True)                                 # the old ?unseen=1 is written f=unseen
    assert hrefs(c["bodies"])[:2] == ["/media/movies/awards?body=oscars&year=2024&f=unseen",
                                      "/media/movies/awards?body=globes&year=2024&f=unseen"]


def test_a_missing_year_lands_on_the_closest_earlier_year_with_a_note(env):
    seeded()
    seed_globes([2021, 2023, 2026])
    earlier, later, held = ctx("globes", "2025"), ctx("globes", "2019"), ctx("oscars", "2025")
    assert earlier["year"] == 2023                                           # 2023 beats the nearer-by-a-year 2026
    assert earlier["year_note"] == "No Golden Globes in 2025 · showing 2023"
    assert earlier["bodies"][0]["href"] == "/media/movies/awards?body=oscars&year=2023"   # the tiles carry the year shown
    assert later["year"] == 2021 and later["year_note"] == "No Golden Globes in 2019 · showing 2021"   # the closest later
    assert held["year_note"] is None                                         # the year exists: no note


def test_current_year_chip_links_to_the_latest_synced_year_unless_already_there(env):
    seeded()
    old = ctx("oscars", "2024", unseen=True)
    assert old["current"] == {"year": 2025, "href": "/media/movies/awards?body=oscars&f=unseen"}
    assert ctx("oscars", "2025")["current"] is None and ctx("oscars")["current"] is None
    pending = ctx("oscars", "2026")
    assert pending["current"]["href"] == "/media/movies/awards?body=oscars"   # 2026 is pending: 2025 is current
    assert pending["year_note"] is None


# ---- awards-year item 3 (2026-10-09): the ceremony tiles say the month the ceremony is held ----

def tile_months(c):
    return {x["name"]: x["month"] for x in c["bodies"]}


def test_tiles_show_the_month_from_the_selected_years_edition_date(env):
    seeded()
    with closing(adb.ensure()) as db:            # an off-season date proves the edition's own date wins
        seed_oscars(db, ordinal=95, year=2023, held_on="2023-04-12")
    y2023 = tile_months(ctx("oscars", "2023"))
    y2025 = tile_months(ctx("oscars", "2025"))
    assert y2023["Oscars"] == "Apr" and y2025["Oscars"] == "Mar"
    assert list(y2025) == ["Oscars", "Golden Globes", "BAFTA", "Critics' Choice", "SAG", "DGA", "PGA", "WGA",
                           "Cannes"] and all(y2025.values())              # tile order unchanged, every tile has one


def test_tile_month_falls_back_to_the_usual_month_without_a_date(env):
    seeded()                                     # 2026 is pending with no held_on; BAFTA / Globes have no editions
    b = tile_months(ctx("oscars", "2026"))
    tv = tile_months(ctx(kind="tv", data={}))                              # no media data at all
    assert (b["Oscars"], b["BAFTA"], b["Golden Globes"], b["Cannes"]) == ("Mar", "Feb", "Jan", "May")
    assert tv["Emmys"] == "Sep"


def test_the_page_renders_before_any_poster_read_first_rows_first_after(env, monkeypatch):
    """M-46 / F2 (2026-10-12): no Jellyseerr read on the request path - the posters are handed to the BackgroundTask,
    which runs after the response; F3 (2026-10-14): the first rows' works first (no hero backdrop any more)."""
    build, _ = env
    seeded()
    monkeypatch.setattr(md, "_creds", lambda: ("http://seerr.invalid", "k"))
    monkeypatch.setattr(md, "meta_get", lambda *a, **k: pytest.fail("a meta read before the render"))
    queued = []
    monkeypatch.setattr(ap, "fill_later", lambda ents: queued.append([e["qid"] for e in ents]))
    with build(jelly()) as client:
        page(client, "/media/movies/awards")
    ents = queued[0]
    assert ents == ["Q1001", "Q1002", "Q2001"]               # Alpha, Beta (the rows' works), then Ann Actor's portrait
    assert len(ents) <= ap.POSTER_READS and len(set(ents)) == len(ents)
