"""JY-259 phase 1 (2026-10-28; B.'s pick "JY-259: A · 1A · 2A · 3A · 4A · 5A · 6A · 7A · 8A"): the TV tile kit, the
friends' TV Home (16:9 Continue watching and Next episodes, the row order, a backdrop hero), the focus lift and the
scaling system. Spec: docs/specs/JY-259-tv-revamp.md.

Covers: the row builder (a 2 + 2 library and a 40-title library), the backdrop chain, every tile macro, the 18 px floor
at 960x540 dpr 2, 1280x720, 1920x1080 and 3840x2160, no network on render, media-front isolation (each friend's own
data only) and the web / phone Home left as it was."""
import re
import time
from datetime import datetime, timedelta, timezone

import pytest

from hub import guest, media_discover as md, media_guest_home, media_item, shell, tv_home
from tests.hub.fake_jellyfin import FRIEND_ID, OTHER_ID
from tests.hub.guest_pages import TV_UA, episode, guest_client, movie, shelf_titles, sign_in
from tests.hub.tv_css import design_px, root_px

NOW = datetime.now(timezone.utc)
SID = "5eed" * 8                       # a show both friends have in the library
EP1, EP2, EP3 = "e001" * 8, "e002" * 8, "e003" * 8


def ago(days: float) -> str:
    return (NOW - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S.0000000Z")


def film(n: int, title: str, *, days: float = 400, backdrop=True, **extra) -> dict:
    jf = f"{n:04d}" * 8
    return {"title": title, "jf_id": jf, "item_key": f"tmdb:{9000 + n}", "poster": f"jf:{jf}", "year": 2024,
            "backdrop": f"jfb:{jf}" if backdrop else None, "added_at": ago(days), "community_rating": 7.0,
            "runtime_min": 120, **extra}


SHOW = {"title": "Quiet Coast", "jf_id": SID, "item_key": "tmdb:8001", "poster": f"jf:{SID}", "backdrop": f"jfb:{SID}",
        "year": 2023, "added_at": ago(400), "community_rating": 8.0, "episodes": 3}


def jelly(n_films: int = 2) -> dict:
    movies = [film(i, f"Film {i:02d}", days=400 - i) for i in range(1, n_films + 1)]
    return {"server_id": "srv-1", "summary": "x", "library": {"movies": n_films, "episodes": 3},
            "latest": [{"title": m["title"], "jf_id": m["jf_id"], "item_key": m["item_key"], "type": "Movie",
                        "poster": m["poster"], "added_at": m["added_at"]} for m in movies[-2:]],
            "movies": movies, "shows": [SHOW]}


def show_read(played: tuple = (EP1,), aired_through: int = 3) -> dict:
    """A cached show read (media_item's shape) for one viewer: three episodes in season 1."""
    eps = [{"number": i + 1, "name": f"Part {i + 1}", "jf_id": e, "still": f"jf:{e}", "aired": i < aired_through,
            "played": e in played, "in_progress": False} for i, e in enumerate((EP1, EP2, EP3))]
    return {"item": {"kind": "series", "id": SID}, "seasons": [{"number": 1, "episodes": eps}]}


def watched_ep(ep: str = EP1) -> dict:
    return episode(ep, "Quiet Coast", SID, 1, 1, "Part 1", played_at=ago(1))


@pytest.fixture()
def fc(monkeypatch, tmp_path):
    client, fake = guest_client(monkeypatch, tmp_path, {"jellyfin": jelly()})
    media_guest_home.clear_cache()
    media_item.clear_cache()
    with client as c:
        c.fake = fake
        sign_in(c, fake, FRIEND_ID)
        yield c
    media_item.clear_cache()


def tv_page(c, path=None) -> str:
    r = c.get(path or guest.home_path(), headers={"User-Agent": TV_UA})
    assert r.status_code == 200
    return r.text


def main(html: str) -> str:
    return html.split("<main", 1)[1]


def cache_show(viewer: str, read: dict) -> None:
    media_item._cache[(viewer, SID)] = (time.time(), read)


# ---- the row builder ----

def _shelf(sid, items, **extra):
    return {"id": sid, "title": sid.title(), "see_all_href": None, "items": items, "quiet_text": None, **extra}


def _item(n, **extra):
    jf = f"{n:04d}" * 8
    return {"title": f"T{n}", "sub": None, "poster": f"jf:{jf}", "href": f"/media/item/{jf}", "pct": None,
            "item_key": f"tmdb:{9000 + n}", **extra}


def test_row_order_puts_the_16x9_rows_first_and_because_after_added(monkeypatch):
    monkeypatch.setattr(media_item, "peek", lambda sid: show_read() if sid == SID else None)
    cont = [{**_item(1), "pct": 40, "episode_key": None}]
    watched = [{"title": "Quiet Coast", "show_key": f"jf:{SID}", "episode_key": f"jf:{EP1}", "poster": f"jf:{SID}"}]
    shelves = [_shelf("continue", cont), _shelf("because", [_item(2)], tv_later=True), _shelf("added", [_item(3)]),
               _shelf("month", [_item(4)]), _shelf("top", [_item(5)]), _shelf("short", [_item(6)]),
               _shelf("watched", [_item(7)])]
    out = tv_home.build(shelves, cont, watched, shelves[2]["items"], jelly())
    assert [r["id"] for r in out["rows"]] == ["continue", "next", "added", "because", "month", "top", "short", "watched"]
    assert [r["land"] for r in out["rows"]] == [True, True] + [False] * 6
    assert out["rows"][3].get("tv_later") is True                                 # JY-105 never first focus
    nxt = out["rows"][1]["items"]
    assert [(i["title"], i["sub"], i["still"], i["href"]) for i in nxt] == [
        ("Quiet Coast", "S1 E2 · Part 2", f"jf:{EP2}", f"/media/item/{EP2}")]
    assert cont[0]["still"] == "jfb:" + "0001" * 8                               # a film's 16:9 is its backdrop


def test_a_two_plus_two_library_and_a_forty_title_library():
    small = tv_home.build([_shelf("added", [_item(1), _item(2)]), _shelf("top", [_item(1), _item(2)])],
                          [], [], [_item(1), _item(2)], jelly(2))
    assert [r["id"] for r in small["rows"]] == ["added", "top"]
    assert small["hero"]["eyebrow"] == "New on Joey" and small["hero"]["title"] == "T1"
    big_items = [_item(i) for i in range(1, 41)]
    big = tv_home.build([_shelf("added", big_items[:20]), _shelf("month", big_items[20:])], [], [], big_items[:20], jelly(40))
    assert [len(r["items"]) for r in big["rows"]] == [20, 20]
    assert big["hero"]["backdrop"] == {"ref": "jfb:" + "0001" * 8, "h": 1280, "blur": False}


def test_next_episodes_skips_a_show_in_progress_an_unaired_next_and_an_uncached_show(monkeypatch):
    watched = [{"title": "Quiet Coast", "show_key": f"jf:{SID}", "episode_key": f"jf:{EP1}"}]
    monkeypatch.setattr(media_item, "peek", lambda sid: show_read(aired_through=1))
    assert tv_home.next_episodes(watched, []) == []                              # E2 not aired yet
    monkeypatch.setattr(media_item, "peek", lambda sid: show_read(played=(EP1, EP2)))
    assert [i["still"] for i in tv_home.next_episodes(watched, [])] == [f"jf:{EP3}"]   # E2 seen already: E3
    assert tv_home.next_episodes(watched, [{"show_key": f"jf:{SID}"}]) == []      # it is in Continue watching
    monkeypatch.setattr(media_item, "peek", lambda sid: None)
    assert tv_home.next_episodes(watched, []) == []                              # not cached: no read, no row


# ---- the backdrop chain (B.'s point 2) ----

def test_backdrop_chain_jellyfin_then_tmdb_cache_then_blurred_poster(monkeypatch):
    j = jelly(2)
    item = _item(1)
    assert tv_home.backdrop(item, j) == {"ref": "jfb:" + "0001" * 8, "h": 1280, "blur": False}
    j["movies"][0]["backdrop"] = None
    monkeypatch.setitem(md._cache, "film:/api/v1/movie/9001", (time.time(), {"backdropPath": "/bd9001.jpg"}))
    assert tv_home.backdrop(item, j) == {"ref": "tmdb:/bd9001.jpg", "h": 1280, "blur": False}
    md._cache.pop("film:/api/v1/movie/9001", None)
    assert tv_home.backdrop(item, j) == {"ref": "jf:" + "0001" * 8, "h": 240, "blur": True}
    assert tv_home.backdrop(None, j) is None


# ---- the tile kit ----

def _kit():
    return shell.templates.env.get_template("_tv_tile.html").module


def test_every_tile_macro_renders_one_focusable_link_with_its_shape():
    kit = _kit()
    p = str(kit.poster({"title": "Film A", "sub": "2024", "poster": "jf:aa", "href": "/media/item/aa", "pct": 40}))
    assert p.startswith('<a class="card-poster tvt tvt-poster" href="/media/item/aa">') and "/img/jf:aa?h=600" in p
    assert 'aria-label="40% watched"' in p and '<span class="row-title">Film A</span><span class="row-meta">2024</span>' in p
    land = str(kit.land({"title": "Show B", "sub": "S1 E2 · 23m left", "still": "jf:ep", "still_h": 400,
                         "poster": "jf:sh", "href": "/media/item/ep", "pct": 50}))
    assert 'class="card-poster tvt tvt-land"' in land and "/img/jf:ep?h=400" in land and "jf:sh" not in land
    person = str(kit.person({"name": "Ann Actor", "role": "Detective", "ref": "jf:p1", "href": "/media/person/1"}))
    assert 'tvt-person' in person and "/img/jf:p1?h=240" in person and ">Detective<" in person
    bands = {s: str(kit.request({"title": "R", "poster": "tmdb:/r.jpg", "href": "/x", "state": s}))
             for s in ("lib", "requested", "request", None)}
    assert 'tvt-band-lib">On Joey<' in bands["lib"] and 'tvt-band-requested">Requested<' in bands["requested"]
    assert 'tvt-band-request">Request<' in bands["request"] and 'tvt-band-request">Request<' in bands[None]
    assert all("reqchip" not in b for b in bands.values())                       # a band under the art, not a chip
    col = str(kit.collection({"title": "Mission Films", "poster": "jf:c", "href": "/c", "count": 8}))
    assert "tvt-stack" in col and ">8 films<" in col
    row = str(kit.row({"title": "Continue watching", "land": True, "items": [
        {"title": "Show B", "still": "jf:ep", "still_h": 400, "href": "/media/item/ep"}]}))
    assert '<h2 class="seclabel">Continue watching</h2>' in row and 'class="carousel tvt-row tvt-row-land"' in row
    later = str(kit.row({"title": "Because", "tv_later": True, "land": False, "items": [_item(1)]}))
    assert '<section class="sec" data-tv-later>' in later


def test_the_poster_source_is_one_place():
    """B.'s point 5 (JY-260 swaps the posters later): every TV tile picture URL is made by art() alone."""
    src = (shell.TEMPLATES_DIR / "_tv_tile.html").read_text(encoding="utf-8")
    assert src.count('src="/img/') == 1 and src.count("{{ art(") >= 6


# ---- the scaling system and the 18 px floor (B.'s points 1 and 3) ----

VIEWPORTS = [(960, 540, 2), (1280, 720, 1), (1920, 1080, 1), (3840, 2160, 1)]   # the TCL, a 720p, 1080p and 4K panel


def _sheet() -> str:
    return re.sub(r"/\*.*?\*/", "", (shell.TEMPLATES_DIR.parent / "static" / "tv.css").read_text(encoding="utf-8"), flags=re.S)


@pytest.mark.parametrize("w,h,dpr", VIEWPORTS)
def test_the_18px_floor_holds_at_every_panel(w, h, dpr):
    css = _sheet()
    sizes = [float(x) for x in re.findall(r"font-size:\s*([\d.]+)rem", css)]
    assert sizes and min(sizes) * root_px(css, w, h) >= 18, (w, h, min(sizes))
    assert not re.search(r"font-size:\s*[\d.]+px", css.replace("max(16px", "")), "every font size is rem"
    assert root_px(css, w, h) / min(w / 60, h / 33.75) == 1                     # the same layout, scaled


def test_no_fixed_px_length_is_left_in_the_sheet():
    css = _sheet()
    rule = "html.tv { font-size: max(16px, min(calc(100vw / 60), calc(100vh / 33.75))); }"
    assert rule in css and re.findall(r"\d+px", css.replace(rule, "")) == []
    assert root_px(css, 960, 540) == 16 and root_px(css, 1920, 1080) == 32 and root_px(css, 3840, 2160) == 64


def test_tile_sizes_spacing_and_the_focus_lift():
    css = design_px(_sheet())
    assert re.search(r"\.carousel > \* \{ flex: 0 0 92px; width: 92px; \}", css)          # 8 across in rows
    assert re.search(r"\.carousel\.tvt-row-land > \* \{ flex: 0 0 158px; width: 158px; \}", css)   # 5 x 16:9
    assert 8 * 92 + 7 * 18 <= 864 and 5 * 158 + 4 * 18 <= 864                          # inside the 5 % overscan
    assert re.search(r"repeat\(9, minmax\(0, 1fr\)\); gap: 18px 16px", css)               # grids 9 across
    assert re.search(r"\.card-poster\.tv-focus \{[^}]*transform: scale\(1\.08\)", css)
    assert re.search(r"\.card-poster\.tvt-land\.tv-focus \{ transform: scale\(1\.05\)", css)
    assert re.search(r"\.card-poster \{ transition: transform \.16s ease-out; \}", css)
    assert re.search(r"\.card-poster\.tv-focus \.card-pic \{[^}]*outline: 4px solid var\(--tv-ring\)", css)   # ring kept
    assert re.search(r"\.card-poster\.tv-focus \.card-pic \{ box-shadow: ", css)
    assert re.search(r"html\.tv \.seclabel, html\.tv h2\.seclabel \{[^}]*text-transform: none", css)
    assert ":hover" not in css


# ---- the TV Home page ----

def test_tv_home_draws_the_backdrop_hero_and_16x9_rows(fc):
    fc.fake.resume[FRIEND_ID] = [movie("aaaa" * 8, "Film 01", "9001", at_min=30)]
    fc.fake.history[FRIEND_ID] = [watched_ep()]
    cache_show(FRIEND_ID, show_read())
    html = tv_page(fc)
    body = main(html)
    assert shelf_titles(html)[:3] == ["Continue watching", "Next episodes", "Recently added"]
    assert re.search(r'<div class="tv-bd" aria-hidden="true"><img src="/img/jfb:(?:0001){8}\?h=1280', body)
    assert '<p class="tv-hero-eyebrow">Continue watching</p><p class="tv-hero-title">Film 01</p>' in body
    assert body.count('class="carousel tvt-row tvt-row-land"') == 2
    assert f"/img/jf:{EP2}?h=400" in body and " · 2</h2>" not in body             # the next episode's still; no counts


def test_no_network_on_render(fc, monkeypatch):
    fc.fake.resume[FRIEND_ID] = [movie("aaaa" * 8, "Film 01", "9001", at_min=30)]
    fc.fake.history[FRIEND_ID] = [watched_ep()]
    cache_show(FRIEND_ID, show_read())

    def boom(*a, **k):
        raise AssertionError("a live read on render")
    monkeypatch.setattr(md, "_fetch", boom)                                      # Jellyseerr / TMDB
    monkeypatch.setattr(media_item, "_read", boom)                               # the item read
    monkeypatch.setattr(media_item, "_build", boom)
    fc.fake.calls.clear()
    tv_page(fc)
    paths = sorted({c[1] for c in fc.fake.calls if not c[1].startswith("/Users")})
    assert paths == ["/Items", "/UserItems/Resume"]                              # the two cached per-user reads only
    fc.fake.calls.clear()
    tv_page(fc)
    assert [c[1] for c in fc.fake.calls if not c[1].startswith("/Users")] == []  # warm: nothing at all


def test_each_friend_sees_only_their_own_rows(fc):
    fc.fake.resume[FRIEND_ID] = [movie("aaaa" * 8, "Friend Resume Film", "9001", at_min=30)]
    fc.fake.history[FRIEND_ID] = [watched_ep()]
    cache_show(FRIEND_ID, show_read())                                           # only FRIEND opened the show
    mine = main(tv_page(fc))
    assert "Friend Resume Film" in mine and "Next episodes" in mine
    sign_in(fc, fc.fake, OTHER_ID)
    other = main(tv_page(fc))
    assert "Friend Resume Film" not in other and "Next episodes" not in other and f"jf:{EP2}" not in other
    assert "Continue watching" not in shelf_titles(other)


def test_the_web_and_phone_home_are_unchanged(fc):
    fc.fake.resume[FRIEND_ID] = [movie("aaaa" * 8, "Film 01", "9001", at_min=30)]
    fc.fake.history[FRIEND_ID] = [watched_ep()]
    cache_show(FRIEND_ID, show_read())
    web = fc.get(guest.home_path()).text
    assert "tvt" not in web and "tv-bd" not in web and "tv-hero" not in web and "Next episodes" not in web
    assert shelf_titles(web)[:2] == ["Continue watching", "Recently added"]
    assert re.search(r'<h2 class="seclabel">Continue watching<span class="sep"> · </span>1</h2>', web)   # count kept
