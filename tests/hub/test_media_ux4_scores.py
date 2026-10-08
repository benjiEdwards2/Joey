"""media-ux4 item 3 (2026-10-08): one rating style. Every score on the film page is a .scorepill — a small monogram logo,
the source's name and the score in ONE format (IMDb 8.0 · RT 90% · Metacritic 74 · TMDB 8.1 · Yours 8 / "Rate");
Metacritic is tinted by its band (good >= 61, mid 40-60, bad < 40) with the number always shown; the IMDb / TMDB /
Letterboxd site links are neutral logo pills of the same family (the yellow / sky / green .linkchip is gone)."""
import re
from pathlib import Path

import pytest

from hub import media_db, media_film
from tests.hub.test_media_film import env, main_of  # noqa: F401  (env is a fixture)

ROOT = Path(__file__).resolve().parents[2]
CSS = (ROOT / "hub" / "static" / "control-surface.css").read_text(encoding="utf-8")
LOGOS = ROOT / "hub" / "static" / "logos"


def pills(b):
    box = b.split('<div class="scorepills">', 1)[1].split("</div>", 1)[0]
    return re.findall(r'class="scorepill sp-(\w+)[^"]*"[^>]*><img class="sp-logo" src="([^"]+)" alt="" width="16" height="16">'
                      r'<span class="sp-name">([^<]+)</span><b class="sp-val[^"]*"[^>]*>([^<]+)</b>', box)


def test_score_pills_in_one_format_and_order(env):
    client, _ = env()
    with client:
        b = main_of(client.get("/media/title/movie/603").text)
    assert pills(b) == [("imdb", "/static/logos/imdb.svg", "IMDb", "7.9"),
                        ("rt", "/static/logos/rt.svg", "RT", "92%"),
                        ("tmdb", "/static/logos/tmdb.svg", "TMDB", "7.8"),
                        ("you", "/static/logos/you.svg", "Yours", "Rate")]
    assert '<a class="scorepill sp-you" href="#rate">' in b and '<section class="sec" id="rate">' in b
    stats = b.split('<div class="stats numbers">', 1)[1]
    assert ">Runtime</div>" in stats and ">Rated</div>" in stats                  # plain stats stay beside the pills
    assert " / 10" not in stats and " %<" not in stats and ">Community</div>" not in stats


def test_your_rating_pill_keeps_grade_gold_and_undo(env):
    client, _ = env()
    with client:
        media_db.set_rating("tmdb:603", 10, "movie", "Harbour Lights", year=2019)
        b = main_of(client.get("/media/title/movie/603").text)
    you = b.split('<form class="rated ratedpill" id="rate"', 1)[1].split("</form>", 1)[0]
    assert '<span class="sp-name">Yours</span><b class="sp-val score-9 gold-text-glow" title="Your rating: 10 out of 10">10</b>' in you
    assert 'hx-delete="/media/rate/tmdb%3A603"' in you and ">Undo</button>" in you
    assert ("you", "/static/logos/you.svg", "Yours", "10") in pills(b) and "ratepick" not in b


def test_tmdb_pill_from_the_jellyseerr_vote_when_off_server(env):
    client, both = env()
    both.seerr.table["/api/v1/movie/701"] = {**both.seerr.table["/api/v1/movie/701"], "voteAverage": 6.51}
    with client:
        b = main_of(client.get("/media/title/movie/701").text)
    assert ("tmdb", "/static/logos/tmdb.svg", "TMDB", "6.5") in pills(b)


@pytest.mark.parametrize("value, text", [(8, "8.0"), (7.84, "7.8"), ("7.4 / 10", "7.4"), ("8.1", "8.1"),
                                         (None, None), (0, None), ("", None), ("n/a", None)])
def test_score_text(value, text):
    assert media_film.score_text(value) == text


@pytest.mark.parametrize("score, band", [(100, "good"), (61, "good"), (60, "mid"), (40, "mid"), (39, "bad"), (0, "bad"),
                                         (None, None), ("74", None), (True, None)])
def test_metacritic_band(score, band):
    assert media_film.mc_band(score) == band


def test_metacritic_band_tints_are_tokens_and_the_rest_are_neutral():
    for band, colour in (("good", "var(--good)"), ("mid", "var(--score-6)"), ("bad", "var(--bad)")):
        assert re.search(rf"\.sp-mc-{band} \.sp-val \{{ color: {re.escape(colour)}; \}}", CSS)
        assert f".sp-mc-{band} {{ border-color:" in CSS
    pill = CSS.split(".scorepill {", 1)[1].split("}", 1)[0]
    assert "border: 1px solid var(--line)" in pill and "background: var(--surface)" in pill


def test_site_links_are_neutral_logo_pills(env):
    client, _ = env()
    with client:
        b = main_of(client.get("/media/title/movie/603").text)
    hero = b.split("</header>", 1)[0]
    sites = re.findall(r'<a class="scorepill sitepill" href="([^"]+)" target="_blank" rel="noopener"><img class="sp-logo" '
                       r'src="([^"]+)" alt="" width="16" height="16">([^<]+)</a>', hero)
    assert [(s[1], s[2]) for s in sites] == [("/static/logos/imdb.svg", "IMDb"), ("/static/logos/tmdb.svg", "TMDB"),
                                             ("/static/logos/lbxd.svg", "Letterboxd")]
    assert sites[1][0] == "https://www.themoviedb.org/movie/603" and sites[2][0] == "https://letterboxd.com/tmdb/603"
    assert "linkchip" not in b


def test_the_linkchip_colours_are_gone_from_the_stylesheet_and_templates():
    assert "linkchip" not in CSS and "--imdb-bg" not in CSS and "--lbxd-fg" not in CSS
    for f in (ROOT / "hub" / "templates").glob("*.html"):
        assert "linkchip" not in f.read_text(encoding="utf-8"), f.name


def test_monogram_logos_ship_as_plain_svgs():
    for i in media_film.LOGO_IDS:
        svg = (LOGOS / f"{i}.svg").read_text(encoding="utf-8")
        assert svg.startswith("<svg") and 'viewBox="0 0 20 20"' in svg and "<script" not in svg and len(svg) < 600, i


def test_a_logo_dropped_in_the_badges_folder_overrides_the_monogram(env, tmp_path):
    client, _ = env()
    (tmp_path / "badges").mkdir()
    (tmp_path / "badges" / "logo-imdb.png").write_bytes(b"\x89PNG")
    with client:
        b = main_of(client.get("/media/title/movie/603").text)
    assert ("imdb", "/static/badges/logo-imdb.png", "IMDb", "7.9") in pills(b)
    assert 'src="/static/badges/logo-imdb.png" alt="" width="16" height="16">IMDb</a>' in b     # the site pill too
