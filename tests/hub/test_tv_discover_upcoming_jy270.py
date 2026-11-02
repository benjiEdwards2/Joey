"""JY-270 P1 shelves + P7 (B. 2026-10-29 "All recommended"): the TV Discover gains the Upcoming films / Upcoming TV
shelves (the TV tile kit, below the grid) and a streaming-service chip row; a chip opens /media/discover/service/{id}
drawn with the TV request tiles (four shelves, no watchlist button). Fake Seerr only, no network; the web stays as it was."""
import re

import pytest

from tests.hub.fake_seerr import Resp, res
from tests.hub.guest_pages import TV_UA
from tests.hub.test_guest_requests import friend  # noqa: F401 - the signed-in friend on the media front
from tests.hub.test_tv_mode import run_tv_pages
from tests.hub.tv_css import design_px

TV = {"User-Agent": TV_UA}
NAMES = ("Netflix", "Disney Plus", "Amazon Prime Video", "Stan", "Binge", "Apple TV Plus", "Paramount Plus",
         "HBO Max", "Foxtel Now", "SBS On Demand", "ABC iview", "9Now", "7plus")
PROVIDERS = [{"id": 100 + i, "name": n, "logoPath": f"/l{i}.png", "displayPriority": i} for i, n in enumerate(NAMES)]


@pytest.fixture()
def tvf(friend):
    """The friend, with upstream Upcoming rows, the AU provider list and a service's discover reads."""
    s = friend.seerr
    s.shelves["/api/v1/discover/movies/upcoming"] = [res(801, "Soon Film One"), res(802, "Soon Film Two")]
    s.shelves["/api/v1/discover/tv/upcoming"] = [res(901, "Soon Show", "tv")]
    real = s.get

    def get(url, headers=None, timeout=None, **kw):
        if "/api/v1/watchproviders/" in str(url):
            return Resp(PROVIDERS)
        if "watchProviders=100" in str(url):
            kind = "tv" if "/discover/tv" in str(url) else "movie"
            return Resp({"page": 1, "totalPages": 1, "results": [res(950 if kind == "movie" else 960, "Svc Title", kind)]})
        return real(url, headers=headers, timeout=timeout, **kw)
    s.get = get
    return friend


def tv(c, url):
    return c.get(url, headers=TV)


def test_tv_discover_has_both_upcoming_shelves_in_the_tile_kit(tvf):
    html = tv(tvf, "/media/discover").text
    for sid, label in (("movies-soon", "Upcoming films"), ("tv-soon", "Upcoming TV")):
        sec = re.search(rf'data-shelf="{sid}">.*?</section>', html, re.S).group(0)
        assert f'seclabel">{label}<' in sec and "tvt-request" in sec
    assert 'href="/media/title/movie/801"' in html and 'href="/media/title/tv/901"' in html
    assert html.index("tv-soon") > html.index("reqgrid")          # below the grid
    assert "/media/watchlist" not in html                         # nothing private


def test_without_upstream_data_the_shelves_are_absent_not_an_error(friend):
    r = tv(friend, "/media/discover")                             # the seeded upcoming lists are empty
    assert r.status_code == 200 and "tv-soon" not in r.text and "Discover unavailable" not in r.text
    friend.seerr.shelves.pop("/api/v1/discover/movies/upcoming")  # a failed read (404) is dropped too
    r = tv(friend, "/media/discover?q=")
    assert r.status_code == 200 and 'data-shelf="movies-soon"' not in r.text


def test_the_service_chip_row_lists_the_13_services(tvf):
    html = tv(tvf, "/media/discover").text
    row = re.search(r'<nav class="chips tv-libchips tv-svcchips".*?</nav>', html, re.S).group(0)
    assert re.findall(r'>([^<]+)</a>', row) == list(NAMES)
    assert 'href="/media/discover/service/100"' in row


def test_web_guest_discover_unchanged(tvf):
    html = tvf.get("/media/discover").text
    assert "tv-svcchips" not in html and "tv-soon" not in html and "/media/discover/service/" not in html


def test_the_service_page_renders_on_the_tv_with_four_shelves(tvf):
    r = tv(tvf, "/media/discover/service/100")
    assert r.status_code == 200
    html = r.text
    for label in ("Popular films", "Popular TV", "New this month", "Top rated"):
        assert f'seclabel">{label}<' in html
    assert html.count('class="carousel tvt-row"') == 4 and "tvt-request" in html
    assert "/media/watchlist" not in html and "wlbtn" not in html


def test_search_partial_smoke(tvf):
    r = tvf.get("/media/discover/search?q=", headers={**TV, "HX-Request": "true"})
    assert r.status_code == 200 and "tv-soon" in r.text
    r = tvf.get("/media/discover/search?q=Searchable", headers={**TV, "HX-Request": "true"})
    assert r.status_code == 200 and "tv-soon" not in r.text


def test_the_chip_css_keeps_the_18px_floor(tvf):
    css = tvf.get("/static/tv.css").text
    block = css[css.index("JY-270 (library filters"):css.index("svg.ic { width: 1.125rem; height: 1.125rem; }")]
    sizes = [float(x) for x in re.findall(r"font-size: ([\d.]+)px", design_px(block))]
    assert sizes and min(sizes) >= 18
    assert "--tv-r" in block


SCENE = r"""
function svc() {
  var main = document.querySelector('main'), nav = new El('nav', { cls: ['chips', 'tv-libchips', 'tv-svcchips'], top: 160 });
  ['netflix', 'stan'].forEach(function (n, i) {
    nav.append(new El('a', { name: 'svc-' + n, cls: ['chip'], attrs: { href: '/media/discover/service/' + (100 + i) }, top: 160, left: 100 + i * 150 }));
  });
  main.children.splice(1, 0, nav); nav.parentElement = main;
}
function page() { discover(''); svc(); }
function servicePage() {
  var main = shell('discover');
  for (var n = 1; n <= 4; n++) poster(main, 's' + n, 950 + n, n - 1, 0);
}
load('/media/discover', page);
out.first = now();
var seen = [];
for (var i = 0; i < 4; i++) { key('ArrowDown'); seen.push(now()); }
out.seen = seen;
load('/media/discover', page);
while (now() !== 'svc-netflix' && now().indexOf('d') !== 0) key('ArrowDown');
if (now() !== 'svc-netflix') { while (now() !== 'svc-netflix' && now() !== 'field' && now() !== 'brand') key('ArrowUp'); }
out.chip = now();
key('ArrowRight'); out.right = now();
boosted('/media/discover/service/101', servicePage);
out.service = now();
load('/media/discover', page);
out.back = now();
"""


def test_dpad_reaches_chips_and_shelves_ok_opens_back_returns(tvf, tmp_path):
    out = run_tv_pages(tvf, tmp_path, SCENE)
    assert any(n.startswith("d") for n in out["seen"]), out          # Down from the search reaches the shelves
    assert out["chip"] == "svc-netflix" and out["right"] == "svc-stan", out
    assert out["service"] == "s1", out                               # OK on a chip opens the service shelves
    assert out["back"] == "svc-stan", out                            # Back: the chip comes back lit


def test_a_services_failure_drops_the_chip_row_not_the_page(tvf, monkeypatch):
    from hub import media_discover as md

    def boom():
        raise RuntimeError("provider read broke")
    monkeypatch.setattr(md, "services", boom)
    r = tv(tvf, "/media/discover")
    assert r.status_code == 200 and "tv-svcchips" not in r.text and "tv-soon" in r.text
