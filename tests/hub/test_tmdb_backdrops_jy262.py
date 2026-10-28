"""JY-262 (2026-10-28): which backdrop a page draws. Spec: docs/specs/JY-262-tmdb-backdrops.md.

B., 2026-10-28: "use the first background as the home page or carousel image, then if you go into the show. It shows
the second background image or such."

Jellyfin stores the TMDB backdrops as Backdrop images 0, 1, 2... The Home hero and the 16:9 row draw index 0; a title
page draws index 1, or index 0 when Jellyfin holds only one (or the count is not known). No Jellyfin backdrop: the
cached TMDB backdrop. Every picture goes through /img at h=1280 (1280 wide: TMDB w1280, Jellyfin maxWidth 1280), so
no original-size 4K file reaches the TV. Covers: the index choice and its fallbacks, the proxy's indexed endpoint, no
key or token in any /img URL, no socket on render, and each friend's own reads only."""
import re
import socket
import time

import pytest

from hub import images, media_backdrop, media_discover as md, media_item, tv_home
from tests.hub.fake_jellyfin import FRIEND_ID, KEY, OTHER_ID
from tests.hub.guest_pages import TV_UA, guest_client, movie, sign_in
from tests.hub.test_tv_home_jy259 import _item, jelly, main, tv_page

TV = {"User-Agent": TV_UA}
MOV = "3a3a" * 8
TOKEN_WORDS = ("api_key", "apikey", "token", "X-Emby", "MediaBrowser")


# ---- the index choice and its fallbacks ----

@pytest.mark.parametrize("count, home, title", [
    (3, "jfb:abc", "jfb:abc/1"),     # several TMDB backdrops: Home the first, the title page the second
    (2, "jfb:abc", "jfb:abc/1"),
    (1, "jfb:abc", "jfb:abc"),       # only one: both draw it
    (None, "jfb:abc", "jfb:abc"),    # not known (an older cached read, a snapshot row): index 0, which always exists
    (0, None, None),                 # Jellyfin has none: the caller falls back to the TMDB cache
])
def test_home_draws_index_0_and_the_title_page_index_1(count, home, title):
    assert media_backdrop.jellyfin("abc", count, media_backdrop.HOME) == home
    assert media_backdrop.jellyfin("abc", count, media_backdrop.TITLE) == title
    assert media_backdrop.jellyfin(None, 3, media_backdrop.TITLE) is None


def test_the_count_comes_from_backdrop_image_tags():
    assert media_backdrop.count_of(["a", "b"]) == 2 and media_backdrop.count_of([]) == 0
    assert media_backdrop.count_of(None) is None and media_backdrop.count_of("x") is None


def test_the_title_page_chain_jellyfin_then_row_then_tmdb():
    item = {"backdrop": "jfb:m1", "backdrops": 2}
    pick = media_backdrop.title_page
    assert pick(item, None, "tmdb:/t.jpg") == "jfb:m1/1"
    assert pick({**item, "backdrops": 1}, None, "tmdb:/t.jpg") == "jfb:m1"
    assert pick({**item, "backdrops": None}, None, "tmdb:/t.jpg") == "jfb:m1"
    assert pick({**item, "backdrops": 0}, None, "tmdb:/t.jpg") == "tmdb:/t.jpg"      # no Jellyfin backdrop: TMDB
    assert pick({**item, "backdrops": 0}, None, None) is None
    assert pick(None, {"backdrop": "jfb:r1"}, "tmdb:/t.jpg") == "jfb:r1"             # snapshot row: count unknown
    assert pick(None, {"backdrop": None}, "tmdb:/t.jpg") == "tmdb:/t.jpg"            # off the server: TMDB
    assert pick(None, None, None) is None


def test_the_home_hero_skips_a_jellyfin_backdrop_the_cached_read_says_is_missing(monkeypatch):
    j, item = jelly(2), _item(1)
    jf = "0001" * 8
    monkeypatch.setitem(md._cache, "film:/api/v1/movie/9001", (time.time(), {"backdropPath": "/bd9001.jpg"}))
    reads = {}
    monkeypatch.setattr(media_item, "peek", lambda i: reads.get(i))
    assert tv_home.backdrop(item, j)["ref"] == f"jfb:{jf}"                    # no read cached: the snapshot's index 0
    reads[jf] = {"item": {"backdrops": 4}}
    assert tv_home.backdrop(item, j)["ref"] == f"jfb:{jf}"                    # Home is always index 0, never /1
    reads[jf] = {"item": {"backdrops": 0}}
    assert tv_home.backdrop(item, j) == {"ref": "tmdb:/bd9001.jpg", "h": 1280, "blur": False}
    md._cache.pop("film:/api/v1/movie/9001", None)


def test_the_item_read_records_how_many_backdrops_jellyfin_holds():
    raw = {"Id": "m1", "Type": "Movie", "Name": "M", "BackdropImageTags": ["a", "b", "c"]}
    assert media_item.backdrop_count(raw, "m1", None) == 3
    assert media_item.backdrop_count({**raw, "BackdropImageTags": []}, "m1", None) == 0
    assert media_item.backdrop_count({"Id": "m1"}, "m1", None) is None
    # an episode draws its show's art: the show read's count, not the episode's own tags
    ep = {"Id": "e1", "Type": "Episode", "SeriesId": "s1", "BackdropImageTags": []}
    assert media_item.backdrop_count(ep, "s1", {"item": {"backdrops": 2}}) == 2
    assert media_item.backdrop_count(ep, "s1", None) is None


# ---- the /img proxy ----

@pytest.mark.parametrize("ref, ok", [("jfb:abc/1", True), ("jfb:abc/9", True), ("jfb:abc", True),
                                     ("jfb:abc/0", False), ("jfb:abc/10", False), ("jf:abc/1", False),
                                     ("tmdb:/a.jpg/1", False), ("jfb:abc/x", False)])
def test_the_proxy_takes_a_backdrop_index_only_on_jfb(ref, ok):
    assert bool(images.REF_RE.match(ref)) is ok


def test_the_proxy_reads_the_indexed_backdrop_at_tv_width_with_the_key_in_a_header(monkeypatch):
    monkeypatch.setenv("JELLYFIN_URL", "http://jelly.example.invalid:8096")
    monkeypatch.setenv("JELLYFIN_API_KEY", "JFSECRETkey")
    (url, params, headers), = images._upstreams("jfb", "abc/1", media_backdrop.TV_H)
    assert url.endswith("/Items/abc/Images/Backdrop/1") and params == {"maxWidth": 1280, "quality": 85}
    assert "JFSECRETkey" not in url and "JFSECRETkey" not in str(params)
    (url0, _, _), = images._upstreams("jfb", "abc", media_backdrop.TV_H)
    assert url0.endswith("/Items/abc/Images/Backdrop/0")
    (tmdb, _, _), = images._upstreams("tmdb", "/b.jpg", media_backdrop.TV_H)
    assert tmdb == "https://image.tmdb.org/t/p/w1280/b.jpg"                     # never "original" (up to 4K)


# ---- the friend's TV title page and Home ----

@pytest.fixture()
def fc(monkeypatch, tmp_path):
    from hub import media_guest_home
    client, fake = guest_client(monkeypatch, tmp_path, {"jellyfin": jelly()})
    media_guest_home.clear_cache()
    media_item.clear_cache()
    fake.items[MOV] = {"Id": MOV, "Type": "Movie", "Name": "Two Skies", "ProductionYear": 2024,
                       "Overview": "A film.", "BackdropImageTags": ["t0", "t1", "t2"]}
    with client as c:
        c.fake = fake
        sign_in(c, fake, FRIEND_ID)
        yield c
    media_item.clear_cache()


def hero_bd(html: str) -> str:
    m = re.search(r'<div class="hero-detail-bd" style="--bd: url\(\'/img/([^\']+)\'\)', html)
    assert m, "no hero backdrop"
    return m.group(1)


def img_urls(html: str) -> list[str]:
    return re.findall(r"/img/[^\"')\s]+", html)


def test_the_tv_title_page_draws_the_second_backdrop(fc):
    html = fc.get(f"/media/item/{MOV}", headers=TV).text
    assert hero_bd(html) == f"jfb:{MOV}/1?h=1280"


def test_a_title_with_one_backdrop_draws_it_and_one_with_none_draws_no_jellyfin_backdrop(fc):
    fc.fake.items[MOV]["BackdropImageTags"] = ["t0"]
    assert hero_bd(fc.get(f"/media/item/{MOV}", headers=TV).text) == f"jfb:{MOV}?h=1280"
    media_item.clear_cache()
    fc.fake.items[MOV]["BackdropImageTags"] = []
    html = fc.get(f"/media/item/{MOV}", headers=TV).text
    assert f"jfb:{MOV}" not in html.split("</header>", 1)[0]                   # no 404 fallback card as a backdrop


def test_no_image_url_carries_a_key_or_token(fc):
    pages = [fc.get(f"/media/item/{MOV}", headers=TV).text, tv_page(fc)]
    for html in pages:
        urls = img_urls(html)
        assert urls
        for u in urls:
            assert KEY not in u and not any(w.lower() in u.lower() for w in TOKEN_WORDS), u
    assert "/Images/" not in "".join(pages)                                    # never a direct Jellyfin image URL


def test_no_socket_opens_on_a_warm_title_page_render(fc, monkeypatch):
    fc.get(f"/media/item/{MOV}", headers=TV)                                   # the item read, cached

    def boom(*a, **k):
        raise AssertionError("a live read on render")
    monkeypatch.setattr(socket.socket, "connect", boom)
    monkeypatch.setattr(socket.socket, "connect_ex", boom)
    monkeypatch.setattr(media_item, "_build", boom)
    monkeypatch.setattr(md, "_fetch", boom)
    fc.fake.calls.clear()
    html = fc.get(f"/media/item/{MOV}", headers=TV).text
    assert hero_bd(html) == f"jfb:{MOV}/1?h=1280"
    assert not [c for c in fc.fake.calls if "/Images/" in c[1]]                 # the page never fetches the art itself


def test_each_friend_sees_backdrops_from_their_own_reads_only(fc, monkeypatch):
    """Friend A's cached read says the hero film has no Jellyfin backdrop (TMDB is drawn); friend B has no read of
    their own, so B's Home never sees A's read and draws the snapshot's index 0."""
    jf = "0001" * 8
    monkeypatch.setitem(md._cache, "film:/api/v1/movie/9001", (time.time(), {"backdropPath": "/bd9001.jpg"}))
    for uid in (FRIEND_ID, OTHER_ID):
        fc.fake.resume[uid] = [movie("aaaa" * 8, "Film 01", "9001", at_min=30)]
    media_item._cache[(FRIEND_ID, jf)] = (time.time(), {"item": {"backdrops": 0}})
    mine = main(tv_page(fc))
    assert '<div class="tv-bd" aria-hidden="true"><img src="/img/tmdb:/bd9001.jpg?h=1280' in mine
    sign_in(fc, fc.fake, OTHER_ID)
    other = main(tv_page(fc))
    assert f'<div class="tv-bd" aria-hidden="true"><img src="/img/jfb:{jf}?h=1280' in other
    assert "tmdb:/bd9001.jpg" not in other
    md._cache.pop("film:/api/v1/movie/9001", None)


def test_the_web_and_phone_title_hero_makes_the_same_choice(fc):
    """The title page hero exists off the TV too (media_film.html): it takes the same index; nothing else changes."""
    html = fc.get(f"/media/item/{MOV}").text
    assert 'class="tv-' not in html.split("<main", 1)[1].split("</header>", 1)[0]
    assert hero_bd(html) == f"jfb:{MOV}/1?h=1280" and "--bd-sm" not in html.split("</header>", 1)[0]
