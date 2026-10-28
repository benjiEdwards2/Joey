"""JY-262 follow-up (2026-10-28): each title's two top-ranked TMDB backdrops, stored locally; Home draws backdrop1,
the title page backdrop2. Spec: docs/specs/JY-262-tmdb-backdrops.md ("Follow-up: ranked backdrops").

B. compared the options on real TMDB images and picked A: "Background: A" / "Use A where there are two posters."
Covers: the ranking, the 2 / 1 / 0 stored-backdrop fallbacks, which page draws which, /img serving them with `&v=`,
no network on render, and the friend front."""
import io
import json
import re
import socket

import pytest
from PIL import Image

from hub import images, media_backdrop, media_item, media_posters as mp, media_posters_store as ms, tv_home
from tests.hub.guest_pages import TV_UA, sign_in
from tests.hub.test_media_posters import LIB, GetOnly, Resp, fakes, snaps  # noqa: F401 (fixture)
from tests.hub.test_tmdb_backdrops_jy262 import MOV, fc, hero_bd  # noqa: F401 (fixture)
from tests.hub.test_tv_home_jy259 import main, tv_page

TV = {"User-Agent": TV_UA}
TMDB = "https://image.tmdb.org/t/p/original"
SHOW, EP, HERO = "c" * 32, "e9e9" * 8, "0001" * 8


def bd(name, lang=None, rating=5.0, votes=10, width=3840):
    return {"ProviderName": "TheMovieDb", "Type": "Backdrop", "Language": lang, "CommunityRating": rating,
            "VoteCount": votes, "Width": width, "Height": width * 9 // 16, "Url": f"{TMDB}/{name}.jpg"}


def jpeg(colour, w=1920, h=1080):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), colour).save(buf, "JPEG")
    return buf.getvalue()


def put(jf_id, *colours):
    """Store backdrops 1..n for a title as the pass would (versioned, published)."""
    for n, colour in enumerate(colours, start=1):
        ms.save_backdrop(jf_id, n, f"{n}abc{n}def{n}", ms.backdrop_jpeg(jpeg(colour)))


# ---- the ranking ----

def test_ranking_prefers_text_less_then_rating_votes_width():
    got = mp.rank_backdrops([bd("en-best", "en", 9.9, 999), bd("a", None, 5.3, 4), bd("b", None, 5.3, 9),
                             bd("c", None, 5.6, 1), bd("d", "", 5.3, 9, 1920),
                             {"Url": "https://evil.example/x.jpg", "CommunityRating": 10}])   # art only from TMDB
    assert [g["url"].rsplit("/", 1)[1] for g in got] == ["c.jpg", "b.jpg"]   # text-less only; rating, votes, width
    assert all(g["lang"] is None for g in got)


def test_ranking_falls_back_to_language_backdrops_when_no_text_less_exists_and_dedupes():
    got = mp.rank_backdrops([bd("x", "en", 6.0), bd("x", "en", 6.0), bd("y", "de", 7.0)])
    assert [g["url"].rsplit("/", 1)[1] for g in got] == ["y.jpg", "x.jpg"]
    assert mp.rank_backdrops([]) == [] and mp.rank_backdrops(None) == []
    assert len(mp.rank_backdrops([bd("only")])) == 1


def test_the_art_is_fetched_1280_wide_never_original():
    assert mp.w1280(f"{TMDB}/a.jpg") == "https://image.tmdb.org/t/p/w1280/a.jpg"


# ---- the pass: 2 / 1 / 0 ----

@pytest.fixture()
def bdfakes(fakes, monkeypatch):
    jf, tmdb, out = fakes
    monkeypatch.setenv("POSTERS_BACKDROPS", "on")
    lists = {"Backdrop": [bd("bd-two", rating=5.2), bd("bd-one", rating=5.8), bd("bd-text", "en", 9.0)]}
    real = jf.get

    def get(url, params=None, **kw):
        if "/RemoteImages" in url and (params or {}).get("type") == "Backdrop":
            jf.calls.append(url)
            jf.params.append(params)
            return Resp(body={"Images": lists["Backdrop"]})
        return real(url, params=params, **kw)
    monkeypatch.setattr(jf, "get", get)
    colours = {"bd-one": (200, 30, 30), "bd-two": (30, 200, 30), "bd-text": (30, 30, 200)}
    tmdb.routes.update({f"/w1280/{k}.jpg": (lambda c=c: Resp(data=jpeg(c), ctype="image/jpeg"))
                        for k, c in colours.items()})
    return jf, tmdb, out, lists


def _colour(path):
    with Image.open(path) as im:
        return im.convert("RGB").getpixel((10, 10))


def test_the_pass_stores_the_top_two_for_films_and_series_not_seasons(bdfakes):
    jf, tmdb, out, lists = bdfakes
    counts = mp.dry_pass(snaps(LIB), pause=0)
    assert counts["backdrops"] == 3 and counts["failed"] == 0                 # 2 films + 1 series; no season
    for jf_id in ("a" * 32, "b" * 32, SHOW):
        one, two = ms.backdrop_path(jf_id, 1), ms.backdrop_path(jf_id, 2)
        assert _colour(one)[0] > 150 and _colour(two)[1] > 150                # bd-one first, bd-two second
        with Image.open(one) as im:
            assert im.width == 1280
    assert ms.backdrop_path("1" * 32, 1) is None                              # seasons use their show's pair
    assert all(p["type"] == "Backdrop" and p["providerName"] == "TheMovieDb" for p in jf.params if p and
               p.get("type") == "Backdrop")
    assert not [u for u in tmdb.calls if "/original/bd-" in u] and [u for u in tmdb.calls if "/w1280/bd-" in u]
    assert json.loads((out / SHOW / "meta.json").read_text())["backdrops"][0].endswith("bd-one.jpg")


def test_one_then_none_clears_the_missing_slots(bdfakes, monkeypatch):
    jf, tmdb, out, lists = bdfakes
    mp.dry_pass(snaps(LIB), pause=0)
    monkeypatch.setattr(mp, "BACKDROPS_TTL_S", 0)
    lists["Backdrop"] = [bd("bd-two")]
    mp.dry_pass(snaps(LIB), pause=0)
    assert _colour(ms.backdrop_path(SHOW, 1))[1] > 150 and ms.backdrop_path(SHOW, 2) is None
    lists["Backdrop"] = []
    mp.dry_pass(snaps(LIB), pause=0)
    assert ms.backdrop_path(SHOW, 1) is None and ms.backdrop_path(SHOW, 2) is None
    assert not list((out / SHOW).glob("*.backdrop*.jpg"))


def test_backdrops_are_read_at_most_monthly_and_survive_a_poster_re_render(bdfakes, monkeypatch, tmp_path):
    jf, tmdb, out, lists = bdfakes
    mp.dry_pass(snaps(LIB), pause=0)
    jf.calls.clear()
    assert mp.dry_pass(snaps(LIB), pause=0)["backdrops"] == 0
    assert not [u for u, p in zip(jf.calls, jf.params) if (p or {}).get("type") == "Backdrop"]
    ver = ms.backdrop_version(SHOW, 1)
    monkeypatch.setattr(mp.render, "RENDER_VERSION", 99)                     # every poster re-renders ...
    mp.dry_pass(snaps(LIB), pause=0)
    assert ms.backdrop_version(SHOW, 1) == ver and "backdrops_at" in ms.read_meta(SHOW)   # ... the backdrops stay


def test_a_backdrop_failure_changes_nothing_and_is_retried(bdfakes):
    jf, tmdb, out, lists = bdfakes
    tmdb.routes = {k: v for k, v in tmdb.routes.items() if "bd-two" not in k}
    counts = mp.dry_pass(snaps(LIB), pause=0)
    assert counts["backdrops"] == 0 and ms.backdrop_path(SHOW, 1) is None and "backdrops_at" not in ms.read_meta(SHOW)


def test_the_switch_turns_the_step_off(bdfakes, monkeypatch):
    monkeypatch.setenv("POSTERS_BACKDROPS", "off")
    assert mp.dry_pass(snaps(LIB), pause=0)["backdrops"] == 0 and ms.backdrop_path(SHOW, 1) is None


# ---- which page uses which ----

@pytest.mark.parametrize("stored, home, title", [
    (2, "jfs:{a}/1", "jfs:{a}/2"),       # two stored: Home the first, the title page the second
    (1, "jfs:{a}/1", "jfs:{a}/1"),       # one: both draw it
    (0, None, "jfb:{a}/1"),              # none: today's JY-262 chain (Jellyfin backdrop 1 of 3)
])
def test_home_takes_backdrop1_and_the_title_page_backdrop2(stored, home, title):
    a = SHOW
    put(a, *[(200, 0, 0), (0, 200, 0)][:stored])
    assert media_backdrop.home(a) == (home.format(a=a) if home else None)
    assert media_backdrop.title_page({"backdrop": f"jfb:{a}", "backdrops": 3}, None, "tmdb:/t.jpg") == title.format(a=a)


def test_a_season_or_episode_page_uses_its_show_pair():
    put(SHOW, (200, 0, 0), (0, 200, 0))
    # media_item gives a season / episode read the show's art as its backdrop
    assert media_backdrop.title_page({"backdrop": f"jfb:{SHOW}", "backdrops": 2}, None, None) == f"jfs:{SHOW}/2"
    assert media_backdrop.title_page(None, {"backdrop": f"jfb:{SHOW}"}, None) == f"jfs:{SHOW}/2"


def test_posters_off_means_today_chain():
    put(SHOW, (200, 0, 0), (0, 200, 0))
    import os
    os.environ["POSTERS"] = "off"
    try:
        assert media_backdrop.home(SHOW) is None and mp.url_version(f"jfs:{SHOW}/1") == ""
    finally:
        os.environ.pop("POSTERS")


# ---- /img ----

def test_img_serves_a_stored_backdrop_with_its_version_and_falls_back_without(monkeypatch, tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    put(SHOW, (200, 0, 0), (0, 200, 0))
    app = FastAPI()
    app.include_router(images.router)
    v2 = mp.url_version(f"jfs:{SHOW}/2")
    assert v2 == ms.backdrop_version(SHOW, 2)
    monkeypatch.setattr(images, "cache_dir", lambda: tmp_path / "imgcache")
    monkeypatch.setenv("JELLYFIN_URL", "http://jf.test")
    monkeypatch.setenv("JELLYFIN_API_KEY", "k" * 32)
    jf = GetOnly({"/Images/Backdrop/1": lambda: Resp(data=b"\xff\xd8jf-backdrop-1", ctype="image/jpeg")})
    monkeypatch.setattr(images.upstream, "session", lambda name: jf)
    with TestClient(app) as c:
        hit = c.get(f"/img/jfs:{SHOW}/2?h=1280&v={v2}")
        assert hit.status_code == 200 and hit.content == ms.backdrop_path(SHOW, 2).read_bytes()
        assert hit.headers["cache-control"] == images.HIT_CACHE and jf.calls == []
        stale = c.get(f"/img/jfs:{SHOW}/2?h=1280&v=0000000000")              # not published: Jellyfin's backdrop 1
        assert stale.content == b"\xff\xd8jf-backdrop-1" and stale.headers["cache-control"] == images.FALLBACK_CACHE
        assert c.get(f"/img/jfs:{SHOW}/3?h=1280").status_code == 404
        assert c.get(f"/img/jfs:..%2F..%2Fmedia.db/1?v={v2}").status_code == 404
    assert images.warm(f"jfs:{SHOW}/1", 1280) == "skipped"                    # local files: nothing to warm


# ---- the pages (friend front, TV), no network on render ----

def test_the_tv_title_page_draws_stored_backdrop2_with_its_version(fc):
    put(MOV, (200, 0, 0), (0, 200, 0))
    html = fc.get(f"/media/item/{MOV}", headers=TV).text
    assert hero_bd(html) == f"jfs:{MOV}/2?h=1280&amp;v={ms.backdrop_version(MOV, 2)}"


def test_the_friend_home_hero_draws_stored_backdrop1(fc):
    put(HERO, (200, 0, 0), (0, 200, 0))
    from tests.hub.fake_jellyfin import FRIEND_ID
    from tests.hub.guest_pages import movie
    fc.fake.resume[FRIEND_ID] = [movie("aaaa" * 8, "Film 01", "9001", at_min=30)]   # the hero: Film 01
    html = main(tv_page(fc))
    m = re.search(r'<div class="tv-bd[^"]*" aria-hidden="true"><img src="/img/([^"]+)"', html)
    assert m and m.group(1).startswith(f"jfs:{HERO}/1?h=1280") and f"v={ms.backdrop_version(HERO, 1)}" in m.group(1)


def test_no_network_on_a_title_page_render_with_stored_backdrops(fc, monkeypatch):
    put(MOV, (200, 0, 0), (0, 200, 0))
    fc.get(f"/media/item/{MOV}", headers=TV)                                   # the item read, cached

    def boom(*a, **k):
        raise AssertionError("a live read on render")
    monkeypatch.setattr(socket.socket, "connect", boom)
    monkeypatch.setattr(socket.socket, "connect_ex", boom)
    monkeypatch.setattr(media_item, "_build", boom)
    monkeypatch.setattr(mp, "remote_backdrops", boom)
    monkeypatch.setattr(mp, "fetch_art", boom)
    assert hero_bd(fc.get(f"/media/item/{MOV}", headers=TV).text).startswith(f"jfs:{MOV}/2?h=1280&amp;v=")


def test_a_friend_gets_the_stored_backdrop_bytes_but_never_the_review_page(fc):
    put(MOV, (200, 0, 0), (0, 200, 0))
    v = ms.backdrop_version(MOV, 2)
    resp = fc.get(f"/img/jfs:{MOV}/2?h=1280&v={v}")
    assert resp.status_code == 200 and resp.content == ms.backdrop_path(MOV, 2).read_bytes()
    assert fc.get("/media/posters").status_code == 404


def test_the_home_hero_chain_is_unchanged_without_stored_backdrops(monkeypatch):
    assert media_backdrop.home(HERO) is None
    hero = tv_home.backdrop({"poster": f"jf:{HERO}"}, {"movies": [{"jf_id": HERO, "backdrop": f"jfb:{HERO}"}]})
    assert hero == {"ref": f"jfb:{HERO}", "h": tv_home.HERO_H, "blur": False}
    put(HERO, (200, 0, 0))
    hero = tv_home.backdrop({"poster": f"jf:{HERO}"}, {"movies": [{"jf_id": HERO, "backdrop": f"jfb:{HERO}"}]})
    assert hero["ref"] == f"jfs:{HERO}/1"


# ---- review of #261 (2026-10-28): the web Home hero, the rate cap, the backoff ----

def test_the_web_home_hero_draws_stored_backdrop1_with_its_version():
    from hub import media_home, shell
    jelly = {"latest": [{"title": "Silo", "jf_id": SHOW, "backdrop": f"jfb:{SHOW}", "added_at": "2026-10-01T00:00:00Z"}]}
    assert media_home.media_hero(jelly, None)["backdrop"] == f"jfb:{SHOW}"           # none stored: as before
    put(SHOW, (200, 0, 0), (0, 200, 0))
    hero = media_home.media_hero(jelly, None)
    assert hero["backdrop"] == f"jfs:{SHOW}/1"
    html = shell.templates.env.from_string('{% from "_pagehead.html" import pagehead %}'
                                           '{% call pagehead("Media", backdrop=bd) %}{% endcall %}').render(bd=hero["backdrop"])
    assert f"jfs%3A{SHOW}%2F1?h=1280&amp;v={ms.backdrop_version(SHOW, 1)}" in html or \
        f"jfs:{SHOW}/1?h=1280&amp;v={ms.backdrop_version(SHOW, 1)}" in html
    assert "--bd-sm" not in html


def test_the_backdrop_step_counts_against_the_pass_limit(bdfakes, monkeypatch):
    """The rate cap: POSTERS_PER_PASS bounds renders AND backdrop fetches together."""
    jf, tmdb, out, lists = bdfakes
    monkeypatch.setenv("POSTERS_PER_PASS", "3")
    first = mp.dry_pass(snaps(LIB), pause=0)
    assert first["rendered"] + first["backdrops"] == 3 and first["more"] is True
    assert [ms.backdrop_path(j, 1) is not None for j in ("b" * 32, "a" * 32, SHOW)].count(True) == first["backdrops"]
    total = first["backdrops"]
    while True:
        got = mp.dry_pass(snaps(LIB), pause=0)
        assert got["rendered"] + got["backdrops"] + got["no_source"] + got["failed"] <= 3
        total += got["backdrops"]
        if not got["more"]:
            break
    assert total == 3                                                          # every film and series, once


def test_a_failing_backdrop_fetch_backs_off_after_three_tries(bdfakes, monkeypatch):
    jf, tmdb, out, lists = bdfakes
    tmdb.routes = {k: v for k, v in tmdb.routes.items() if "/w1280/" not in k}   # the backdrop art never answers
    for _ in range(3):
        assert mp.dry_pass(snaps(LIB), pause=0)["backdrops"] == 0
    meta = ms.read_meta(SHOW)
    assert meta["backdrops_fails"] == 3 and meta["backdrops_retry_at"]
    jf.calls.clear()
    got = mp.dry_pass(snaps(LIB), pause=0)
    assert got["backoff"] >= 3 and got["failed"] == 0
    assert not [u for u, p in zip(jf.calls, jf.params) if (p or {}).get("type") == "Backdrop"]
    monkeypatch.setattr(mp, "in_backoff_until", lambda retry_at, now=None: False)   # a day later
    tmdb.routes.update({f"/w1280/{k}.jpg": (lambda: Resp(data=jpeg((9, 9, 9)), ctype="image/jpeg"))
                        for k in ("bd-one", "bd-two")})
    assert mp.dry_pass(snaps(LIB), pause=0)["backdrops"] == 3
    assert "backdrops_fails" not in ms.read_meta(SHOW)                       # a success clears the count
