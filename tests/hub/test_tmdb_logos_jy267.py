"""JY-267 (2026-10-29): TMDB title logos instead of plain text. Spec: docs/specs/JY-267-tmdb-logos.md.

B., 2026-10-29: "I like A for both options." (picks 1A 2A 3A 4A: Jellyfin RemoteImages type=Logo through the poster
pass, no new key; no dark-logo detection; viewer language, then English, then any; on the phone the logo replaces the
title). Covers P1 (rank, fetch w500, store, size cap, SVG skipped, monthly, cleared, survives a re-render, the switch,
/img `jfs:<id>/logo` with its `v` only), P2 (web and phone Home hero and title page, the onerror text path, the <h1>
unchanged, the friend front, no network on render) and P3 (the TV Home hero and title page), plus a smoke test for
each changed route. Fixtures are tiny Pillow PNGs; nothing touches the network."""
import html as htmllib
import io
import json
import logging
import re
import socket
from pathlib import Path

import pytest
from PIL import Image

from hub import images, media_item, media_posters as mp, media_posters_store as ms, shell, tv_home
from tests.hub.conftest import main_of
from tests.hub.film_page import whole
from tests.hub.guest_pages import TV_UA
from tests.hub.helpers import env  # noqa: F401 (the film-page fixture)
from tests.hub.test_media_posters import LIB, GetOnly, Resp, fakes, snaps  # noqa: F401 (fixture)
from tests.hub.test_tmdb_backdrops_jy262 import MOV, fc  # noqa: F401 (fixture)
from tests.hub.test_tv_home_jy259 import main, tv_page

TV = {"User-Agent": TV_UA}
TMDB = "https://image.tmdb.org/t/p/original"
SHOW, HERO = "c" * 32, "0001" * 8
CSS = (Path(shell.TEMPLATES_DIR).parent / "static" / "control-surface.css").read_text(encoding="utf-8")
TV_JS = (Path(shell.TEMPLATES_DIR).parent / "static" / "tv.js").read_text(encoding="utf-8")
TV_CSS = (Path(shell.TEMPLATES_DIR).parent / "static" / "tv.css").read_text(encoding="utf-8")


def logo(name, lang="en", votes=5, rating=5.0, width=500, ext="png"):
    return {"ProviderName": "TheMovieDb", "Type": "Logo", "Language": lang, "CommunityRating": rating,
            "VoteCount": votes, "Width": width, "Height": width // 4, "Url": f"{TMDB}/{name}.{ext}"}


def png(w=500, h=125, colour=(255, 255, 255, 255), noise=False):
    """A small transparent PNG (alpha kept); `noise` makes an incompressible one for the size cap."""
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    im.paste(Image.new("RGBA", (w // 2, h // 2), colour), (w // 4, h // 4))
    if noise:
        import os
        im = Image.frombytes("RGBA", (w, h), os.urandom(w * h * 4))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def put(jf_id, w=500, h=125, ver="1a2b3c4d5e"):
    """Store a logo for a title as the pass would (versioned, published)."""
    ms.save_logo(jf_id, ver, png(w, h), w, h)
    return ver


def urls(found):
    return [g["url"].rsplit("/", 1)[1] for g in found]


# ---- P1: the ranking ----

def test_ranking_language_first_then_english_then_any_then_votes_rating_width(monkeypatch):
    got = mp.rank_logos([logo("en-many", "en", 50), logo("fr", "fr", 1), logo("none", None, 99),
                         logo("de-top", "de", 9, 9.0), logo("de-low", "de", 9, 5.0), logo("de-wide", "de", 9, 5.0, 900)],
                        lang="de")
    assert urls(got) == ["de-top.png", "de-wide.png", "de-low.png", "en-many.png", "none.png", "fr.png"]
    monkeypatch.delenv("POSTERS_LOGO_LANG", raising=False)
    assert mp.logo_lang() == "en"                                          # default: English, then any
    assert urls(mp.rank_logos([logo("none", None, 99), logo("en", "en", 1)])) == ["en.png", "none.png"]
    monkeypatch.setenv("POSTERS_LOGO_LANG", "fr")
    assert urls(mp.rank_logos([logo("en", "en", 9), logo("fr", "fr", 1)])) == ["fr.png", "en.png"]
    monkeypatch.setenv("POSTERS_LOGO_LANG", "../x")                        # junk: English
    assert mp.logo_lang() == "en"


def test_ranking_tmdb_only_svg_skipped_deduped_and_no_logo():
    got = mp.rank_logos([logo("a"), logo("a"), logo("vector", ext="svg"),
                         {"Url": "https://evil.example/x.png", "VoteCount": 999}, "junk", None])
    assert urls(got) == ["a.png"]
    assert mp.rank_logos([]) == [] and mp.rank_logos(None) == [] and mp.rank_logos([logo("v", ext="svg")]) == []


def test_the_logo_is_fetched_500_wide_never_original():
    assert mp.w500(f"{TMDB}/a.png") == "https://image.tmdb.org/t/p/w500/a.png"


# ---- P1: the pass ----

@pytest.fixture()
def lgfakes(fakes, monkeypatch):
    jf, tmdb, out = fakes
    monkeypatch.setenv("POSTERS_LOGOS", "on")
    lists = {"Logo": [logo("lg-one", "en", 9), logo("lg-two", "en", 2), logo("lg-svg", "en", 99, ext="svg")]}
    real = jf.get

    def get(url, params=None, **kw):
        if "/RemoteImages" in url and (params or {}).get("type") == "Logo":
            jf.calls.append(url)
            jf.params.append(params)
            return Resp(body={"Images": lists["Logo"]})
        return real(url, params=params, **kw)
    monkeypatch.setattr(jf, "get", get)
    bodies = {"lg-one": png(500, 125), "lg-two": png(400, 200), "lg-big": png(400, 200, noise=True)}
    tmdb.routes.update({f"/w500/{k}.png": (lambda b=b: Resp(data=b, ctype="image/png")) for k, b in bodies.items()})
    return jf, tmdb, out, lists


def logo_reads(jf):
    return [u for u, p in zip(jf.calls, jf.params) if (p or {}).get("type") == "Logo"]


def test_the_pass_stores_the_top_logo_as_png_with_alpha_for_films_and_series_not_seasons(lgfakes):
    jf, tmdb, out, lists = lgfakes
    counts = mp.dry_pass(snaps(LIB), pause=0)
    assert counts["logos"] == 3 and counts["failed"] == 0                     # 2 films + 1 series; no season
    for jf_id in ("a" * 32, "b" * 32, SHOW):
        path = ms.logo_path(jf_id)
        assert path.name.endswith(".logo.png") and (out / jf_id / "logo").is_file()
        with Image.open(path) as im:
            assert im.format == "PNG" and im.mode == "RGBA" and im.size == (500, 125)
            assert im.getpixel((0, 0))[3] == 0                                 # the transparency is kept
        assert ms.logo_info(jf_id)[1:] == (500, 125)
    assert ms.logo_path("1" * 32) is None                                      # seasons use their show's
    assert all(p["providerName"] == "TheMovieDb" and p["includeAllLanguages"] == "true"
               for p in jf.params if (p or {}).get("type") == "Logo")
    assert [u for u in tmdb.calls if "/w500/lg-one" in u] and not [u for u in tmdb.calls if "/original/lg-" in u]
    assert not [u for u in tmdb.calls if "lg-svg" in u]                        # the SVG (top votes) is skipped
    assert json.loads((out / SHOW / "meta.json").read_text())["logo"].endswith("lg-one.png")


def test_logos_are_read_at_most_monthly_and_survive_a_poster_re_render(lgfakes, monkeypatch):
    jf, tmdb, out, lists = lgfakes
    mp.dry_pass(snaps(LIB), pause=0)
    jf.calls.clear()
    jf.params.clear()
    assert mp.dry_pass(snaps(LIB), pause=0)["logos"] == 0 and logo_reads(jf) == []
    ver = ms.logo_version(SHOW)
    monkeypatch.setattr(mp.render, "RENDER_VERSION", 98)                       # every poster re-renders ...
    mp.dry_pass(snaps(LIB), pause=0)
    assert ms.logo_version(SHOW) == ver and "logo_at" in ms.read_meta(SHOW)    # ... the logo stays
    monkeypatch.setattr(mp, "LOGOS_TTL_S", 0)                                   # a month later: a new pick
    lists["Logo"] = [logo("lg-two", "en", 50)]
    mp.dry_pass(snaps(LIB), pause=0)
    assert ms.logo_version(SHOW) != ver and ms.logo_info(SHOW)[1:] == (400, 200)
    assert len(list((out / SHOW).glob("*.logo.png"))) == 1                     # the old file is gone


def test_a_title_tmdb_no_longer_has_a_logo_for_is_cleared(lgfakes, monkeypatch):
    jf, tmdb, out, lists = lgfakes
    mp.dry_pass(snaps(LIB), pause=0)
    monkeypatch.setattr(mp, "LOGOS_TTL_S", 0)
    lists["Logo"] = [logo("only-svg", ext="svg")]                              # nothing usable left
    mp.dry_pass(snaps(LIB), pause=0)
    assert ms.logo_path(SHOW) is None and not list((out / SHOW).glob("*.logo.png"))
    assert mp.stored_logo(SHOW) is None and ms.read_meta(SHOW)["logo"] is None


def test_a_300_kb_logo_is_refused_logged_and_the_text_drawn(lgfakes, caplog):
    jf, tmdb, out, lists = lgfakes
    big = png(400, 200, noise=True)
    big = big if len(big) > 300 * 1024 else big + b"\0" * (300 * 1024 - len(big))   # a 300 KB file
    tmdb.routes["/w500/lg-big.png"] = lambda: Resp(data=big, ctype="image/png")
    lists["Logo"] = [logo("lg-big", "en", 9)]
    with caplog.at_level(logging.WARNING, logger="hub.media_posters"):
        counts = mp.dry_pass(snaps(LIB), pause=0)
    assert counts["logos"] == 3 and counts["failed"] == 0
    assert ms.logo_path(SHOW) is None and mp.stored_logo(SHOW) is None
    assert ms.read_meta(SHOW)["logo_refused"] is True
    assert any("refused" in r.getMessage() for r in caplog.records)
    assert not any("image.tmdb.org" in r.getMessage() for r in caplog.records)   # never a URL in the log
    with pytest.raises(ValueError):
        ms.logo_png(big)


def test_a_404_top_logo_falls_through_to_the_next_ranked_one(lgfakes):
    jf, tmdb, out, lists = lgfakes
    tmdb.routes = {k: v for k, v in tmdb.routes.items() if "lg-one" not in k}   # the top pick's w500 file: 404
    counts = mp.dry_pass(snaps(LIB), pause=0)
    assert counts["logos"] == 3 and counts["failed"] == 0
    assert ms.logo_info(SHOW)[1:] == (400, 200)                                  # lg-two, the second ranked
    assert ms.read_meta(SHOW)["logo"].endswith("lg-two.png") and "logo_refused" not in ms.read_meta(SHOW)


def test_the_fall_through_is_bounded_to_the_top_three(lgfakes):
    jf, tmdb, out, lists = lgfakes
    lists["Logo"] = [logo(f"miss{i}", "en", 10 - i) for i in range(3)] + [logo("lg-one", "en", 1)]
    assert mp.dry_pass(snaps(LIB), pause=0)["logos"] == 0 and ms.logo_path(SHOW) is None   # 4th never tried
    assert not [u for u in tmdb.calls if "/w500/lg-one" in u]


def test_a_logo_failure_changes_nothing_and_is_retried(lgfakes):
    jf, tmdb, out, lists = lgfakes
    tmdb.routes = {k: v for k, v in tmdb.routes.items() if "/w500/lg-" not in k}   # every try fails upstream
    counts = mp.dry_pass(snaps(LIB), pause=0)
    assert counts["logos"] == 0 and ms.logo_path(SHOW) is None and "logo_at" not in ms.read_meta(SHOW)
    assert ms.read_meta(SHOW)["logo_fails"] == 1


def test_the_switch_turns_the_step_and_the_drawing_off(lgfakes, monkeypatch):
    monkeypatch.setenv("POSTERS_LOGOS", "off")
    jf, tmdb, out, lists = lgfakes
    assert mp.dry_pass(snaps(LIB), pause=0)["logos"] == 0 and logo_reads(jf) == []
    put(SHOW)
    assert mp.stored_logo(SHOW) is None and mp.url_version(f"jfs:{SHOW}/logo") == ""
    assert mp.served_logo(SHOW) is None
    monkeypatch.setenv("POSTERS_LOGOS", "on")
    assert mp.stored_logo(SHOW)["src"] == f"/img/jfs:{SHOW}/logo?v={ms.logo_version(SHOW)}"
    monkeypatch.setenv("POSTERS", "off")                                        # the whole poster store off
    assert mp.stored_logo(SHOW) is None


def test_the_logo_step_counts_against_the_pass_limit(lgfakes, monkeypatch):
    monkeypatch.setenv("POSTERS_PER_PASS", "4")
    first = mp.dry_pass(snaps(LIB), pause=0)
    assert first["rendered"] + first["logos"] <= 4 and first["more"] is True


# ---- P1: /img jfs:<id>/logo ----

@pytest.fixture()
def img_client(monkeypatch, tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    app = FastAPI()
    app.include_router(images.router)
    monkeypatch.setenv("POSTERS_LOGOS", "on")
    monkeypatch.setattr(images, "cache_dir", lambda: tmp_path / "imgcache")
    monkeypatch.setenv("JELLYFIN_URL", "http://jf.test")
    monkeypatch.setenv("JELLYFIN_API_KEY", "k" * 32)
    jf = GetOnly({})
    monkeypatch.setattr(images.upstream, "session", lambda name: jf)
    with TestClient(app) as c:
        c.jf = jf
        yield c


def test_img_serves_the_stored_logo_only_with_its_version(img_client):
    ver = put(SHOW)
    assert mp.url_version(f"jfs:{SHOW}/logo") == ver
    hit = img_client.get(f"/img/jfs:{SHOW}/logo?v={ver}")
    assert hit.status_code == 200 and hit.content == ms.logo_path(SHOW).read_bytes()
    assert hit.headers["content-type"] == "image/png" and hit.headers["cache-control"] == images.HIT_CACHE
    for bad in (f"/img/jfs:{SHOW}/logo", f"/img/jfs:{SHOW}/logo?v=0000000000", f"/img/jfs:{SHOW}/logo?v=../x"):
        miss = img_client.get(bad)                                             # never without the published v
        assert miss.status_code == 404 and miss.headers["cache-control"] == "no-store"
    assert img_client.jf.calls == []                                           # no Jellyfin fallback, no network
    assert images.warm(f"jfs:{SHOW}/logo", 400) == "skipped"


@pytest.mark.parametrize("ref", ["jfs:../logo", "jfs:..%2F..%2Fmedia.db/logo", "jfs:abc/logo2", "jfs:abc/Logo",
                                 "jfs:abc/logo/x", "jfs:/logo", "jfs:abc/logo.png"])
def test_a_hostile_logo_ref_is_rejected(img_client, ref):
    put(SHOW)
    assert img_client.get(f"/img/{ref}?v={ms.logo_version(SHOW)}").status_code == 404
    assert img_client.jf.calls == []


def test_a_title_with_no_logo_is_a_404_so_the_page_draws_text(img_client):
    resp = img_client.get(f"/img/jfs:{SHOW}/logo?v=1a2b3c4d5e")
    assert resp.status_code == 404 and img_client.jf.calls == []


# ---- P2: the web and phone title page ----

def hero_of(b):
    return b.split('<header class="pagehead hero-detail', 1)[1].split("</header>", 1)[0]


def test_web_title_page_draws_the_logo_with_the_h1_and_alt_kept(env, monkeypatch):  # noqa: F811
    monkeypatch.setenv("POSTERS_LOGOS", "on")
    client, _ = env()
    with client:
        plain = hero_of(main_of(whole(client, "/media/item/mov1")))            # smoke: no logo, the old h1
        assert '<h1 class="hero-detail-title">Harbour Lights (2019)</h1>' in plain and "title-logo" not in plain
        ver = put("mov1")
        h = hero_of(main_of(whole(client, "/media/item/mov1")))
    m = re.search(r'<h1 class="hero-detail-title has-logo"><img class="title-logo" src="([^"]+)" alt="([^"]+)" '
                  r'width="500" height="125" style="--lw: 500; --lh: 125" decoding="async" onerror="[^"]+">'
                  r'<span class="title-logo-text">([^<]+)</span></h1>', h)
    assert m, h[:2000]
    assert htmllib.unescape(m.group(1)) == f"/img/jfs:mov1/logo?v={ver}"
    assert m.group(2) == "Harbour Lights" and m.group(3) == "Harbour Lights (2019)"   # alt: the title; text: fallback
    assert "logo-failed" in h and "this.remove()" in h                         # onerror -> the words, same box


def test_a_season_or_episode_page_draws_its_shows_logo(env, monkeypatch):  # noqa: F811
    monkeypatch.setenv("POSTERS_LOGOS", "on")
    client, _ = env()
    with client:
        put("ser1")
        show = hero_of(main_of(whole(client, "/media/item/ser1")))
        ep = hero_of(main_of(whole(client, "/media/item/ep3")))
    assert "/img/jfs:ser1/logo?v=" in show
    assert "/img/jfs:ser1/logo?v=" in ep and "Penny for Your Thoughts" in ep   # the episode name stays as text


def test_the_macro_without_a_logo_is_exactly_the_old_markup():
    tpl = shell.templates.env.from_string('{% from "_pagehead.html" import title_h1, pagehead %}'
                                          '{{ title_h1(t, ref, "hero-detail-title") }}|{{ title_h1(t) }}|'
                                          '{% call pagehead(t, backdrop=ref, logo=ref) %}{% endcall %}')
    out = tpl.render(t="A & B", ref=f"jfb:{SHOW}")
    assert out.startswith('<h1 class="hero-detail-title">A &amp; B</h1>|<h1>A &amp; B</h1>|')
    assert "<h1>A &amp; B</h1>" in out.split("|", 2)[2]


def test_a_hostile_title_stays_inside_the_alt(monkeypatch):
    monkeypatch.setenv("POSTERS_LOGOS", "on")
    put(SHOW)
    xss = '" onload="alert(1)'
    out = shell.templates.env.from_string('{% from "_pagehead.html" import title_h1 %}{{ title_h1(t, ref) }}'
                                          ).render(t=xss, ref=f"jfs:{SHOW}/2")
    assert 'onload="alert' not in out and "&#34; onload=&#34;alert(1)" in out


# ---- P2: the web Home hero ----

def test_web_home_hero_draws_the_logo(tmp_path, monkeypatch):
    import importlib
    from fastapi.testclient import TestClient
    from tests.hub.helpers import JELLY, make_area, shelf_area, write_envelope, write_registry
    monkeypatch.setenv("POSTERS_LOGOS", "on")
    monkeypatch.setenv("AREAS_PATH", str(write_registry(tmp_path, shelf_area(), make_area("beta"))))
    monkeypatch.setenv("MEDIA_DB_PATH", str(tmp_path / "media.db"))
    monkeypatch.setenv("SNAPSHOT_DIR", str(tmp_path / "snaps"))
    write_envelope(tmp_path / "snaps", "jellyfin", age_minutes=1, data=JELLY)
    import hub.main
    importlib.reload(hub.main)
    with TestClient(hub.main.app) as client:
        plain = main_of(client.get("/a/alpha?s=new").text)                     # smoke: no logo, the words
        assert '<span class="homecar-title">Fresh Film</span>' in plain
        ver = put("f")
        page = client.get("/a/alpha?s=new")
    assert page.status_code == 200
    body = main_of(page.text)
    # JY-277 option B (2026-11-03, docs/specs/JY-277-overview-B.md): the hero is the carousel; its slide draws the stored logo, the words kept for a failed load
    assert f'<img class="homecar-logo" src="/img/jfs:f/logo?v={ver}"' in body
    assert '<span class="homecar-title" hidden>Fresh Film</span>' in body


# ---- P2: per-surface sizes (CSS), no new colours ----

def test_the_css_holds_the_spec_sizes_per_surface():
    block = CSS.split("/* JY-267", 1)[1].split("/* TV episode flow", 1)[0]
    assert "min(60%, calc(120px * var(--lw) / var(--lh)), calc(var(--lw) * 1.5px))" in block      # web
    assert "min(70%, calc(90px * var(--lw) / var(--lh)), calc(var(--lw) * 1.5px))" in block       # phone
    assert "aspect-ratio: var(--lw) / var(--lh)" in block                      # the box is known before it loads
    assert "html.tv" not in block                                              # the TV rules live in tv.css
    tv = TV_CSS.split("/* JY-267", 1)[1]
    assert "min(30vw, calc(5rem * var(--lw) / var(--lh)), calc(var(--lw) * .046875rem))" in tv     # TV, <= 1.5x
    for css in (block, tv):
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(", css)              # no new colours


# ---- P2: friend front, no network on render ----

def test_a_friend_gets_a_logo_only_for_a_title_they_may_see(fc, monkeypatch):  # noqa: F811
    monkeypatch.setenv("POSTERS_LOGOS", "on")
    ver = put(MOV)
    fc.get(f"/media/item/{MOV}")                                               # the friend's own read: MOV is shown
    seen = fc.get(f"/img/jfs:{MOV}/logo?v={ver}")
    assert seen.status_code == 200 and seen.headers["content-type"] == "image/png"
    hidden = "9f9f" * 8                                                        # never shown to this friend
    ms.save_logo(hidden, ver, png(), 500, 125)
    resp = fc.get(f"/img/jfs:{hidden}/logo?v={ver}")                          # a 404 (onerror -> the words), never
    assert resp.status_code == 404 and resp.headers["cache-control"] == "no-store"   # a 200 title card
    assert resp.content != ms.logo_path(hidden).read_bytes()


def test_no_network_on_a_title_page_render_with_a_stored_logo(fc, monkeypatch):  # noqa: F811
    monkeypatch.setenv("POSTERS_LOGOS", "on")
    put(MOV)
    fc.get(f"/media/item/{MOV}", headers=TV)                                   # the item read, cached

    def boom(*a, **k):
        raise AssertionError("a live read on render")
    monkeypatch.setattr(socket.socket, "connect", boom)
    monkeypatch.setattr(socket.socket, "connect_ex", boom)
    monkeypatch.setattr(media_item, "_build", boom)
    monkeypatch.setattr(mp, "remote_logos", boom)
    monkeypatch.setattr(mp, "fetch_art", boom)
    for headers in (TV, {}):
        html = fc.get(f"/media/item/{MOV}", headers=headers).text
        assert f"/img/jfs:{MOV}/logo?v=" in hero_of(html)


# ---- P3: the TV Home hero and title page ----

def test_the_tv_title_page_draws_the_logo(fc, monkeypatch):  # noqa: F811
    monkeypatch.setenv("POSTERS_LOGOS", "on")
    plain = hero_of(fc.get(f"/media/item/{MOV}", headers=TV).text)            # smoke: no logo, the words
    assert '<h1 class="hero-detail-title">Two Skies</h1>' in plain
    ver = put(MOV)
    h = hero_of(fc.get(f"/media/item/{MOV}", headers=TV).text)
    assert f'<img class="title-logo" src="/img/jfs:{MOV}/logo?v={ver}" alt="Two Skies"' in h
    assert '<span class="title-logo-text">Two Skies</span>' in h               # no year on the TV, as before


def test_the_tv_home_hero_draws_the_logo_and_each_tile_carries_its_own(fc, monkeypatch):  # noqa: F811
    from tests.hub.fake_jellyfin import FRIEND_ID
    from tests.hub.guest_pages import movie
    monkeypatch.setenv("POSTERS_LOGOS", "on")
    fc.fake.resume[FRIEND_ID] = [movie("aaaa" * 8, "Film 01", "9001", at_min=30)]   # the hero: Film 01 (HERO)
    plain = main(tv_page(fc))                                                  # smoke: no logo, today's words
    assert '<p class="tv-hero-title">Film 01</p><img class="tv-hero-logo" alt="" hidden decoding="async"' in plain
    ver = put(HERO)
    body = main(tv_page(fc))
    assert (f'<p class="tv-hero-title" hidden>Film 01</p><img class="tv-hero-logo" src="/img/jfs:{HERO}/logo?v={ver}"'
            f' alt="Film 01" width="500" height="125"') in body
    heroes = [json.loads(htmllib.unescape(m)) for m in re.findall(r"data-hero='([^']*)'", body)]
    withlogo = [h for h in heroes if h.get("logo")]
    assert withlogo and all(h["logo"]["src"] == f"/img/jfs:{HERO}/logo?v={ver}" for h in withlogo)
    assert all("logo" not in h for h in heroes if h["title"] != "Film 01")     # no logo stored: no key, the words


def test_tile_hero_logo_comes_from_the_library_row(monkeypatch):
    monkeypatch.setenv("POSTERS_LOGOS", "on")
    put(HERO)
    th = tv_home.tile_hero({"title": "T", "poster": f"jf:{HERO}"}, {"movies": [{"jf_id": HERO}]}, None)
    assert th["logo"] == {"src": f"/img/jfs:{HERO}/logo?v={ms.logo_version(HERO)}", "w": 500, "h": 125}
    assert "logo" not in tv_home.tile_hero({"title": "U", "poster": "jf:" + "9" * 32}, {}, None)


def test_tv_js_swaps_the_logo_with_focus_and_falls_back_to_the_words():
    fn = TV_JS.split("function heroLogo(box, d) {", 1)[1].split("\n  }\n", 1)[0]
    assert "'.tv-hero-logo'" in fn and "img.setAttribute('src', lg.src)" in fn and "t.setAttribute('hidden', '')" in fn
    assert "img.setAttribute('hidden', '')" in fn and "img.removeAttribute('src')" in fn
    assert "heroLogo(box, d);" in TV_JS.split("function showHero(el) {", 1)[1].split("\n  }\n", 1)[0]
    assert "fetch(" not in fn and "XMLHttpRequest" not in fn                   # the browser's /img load only
    assert "html.tv .tv-hero-title[hidden], html.tv .tv-hero-logo[hidden] { display: none; }" in TV_CSS
