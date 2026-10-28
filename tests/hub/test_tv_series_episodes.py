"""JY-192 (U6, 2026-10-25): series and episodes on the TV (findings S1, X1-X3; tv-v2 shell 01-title screens 2 and 3).

In TV mode a series / season / episode page shows a Seasons shelf (2:3 season cards) and an Episodes shelf (16:9 stills
through the /img proxy, a word chip + progress bar, OK = the Jellyfin hand-off of that episode); the episode page's
hero leads with the episode; Back goes to the series (tv.js, `data-tv-up`); the rating is a Rate button opening the
existing picker in a strip (Gate 1 pick 1B). Off the TV nothing changes. The watch words are the signed-in viewer's own
(the page's per-viewer Episodes read), never the household's. The node tests use the JY-187 fake DOM (skip without node).
"""
import re

import pytest

from tests.hub.fake_jellyfin import ADMIN_ID, ALIAS_ID, FRIEND_ID, OTHER_ID, PUBLIC_URL
from tests.hub.guest_pages import TV_UA, guest_client, sign_in
from tests.hub.test_tv_mode import run_tv_pages
from tests.hub.tv_css import design_px

SHOW = "5e7105e7" * 4
S1, S2 = "5ea50001" * 4, "5ea50002" * 4
E1, E2, E3, E4 = ("e0000001" * 4, "e0000002" * 4, "e0000003" * 4, "e0000004" * 4)
TICKS = 600_000_000
TV = {"User-Agent": TV_UA}
# the household snapshot says the show is watched: none of it may reach a friend's shelves
LIB = {"server_id": "srv-1", "library": {"movies": 0, "episodes": 4}, "movies": [], "latest": [],
       "shows": [{"title": "Sample Show", "jf_id": SHOW, "item_key": f"jf:{SHOW}", "played": True, "unplayed": 0,
                  "last_played_at": "1999-01-01"}]}


def ep(jf_id, season_id, season_no, number, name, aired="2026-09-01"):
    return {"Id": jf_id, "Name": name, "Type": "Episode", "IndexNumber": number, "ParentIndexNumber": season_no,
            "SeasonId": season_id, "SeasonName": f"Season {season_no}", "SeriesId": SHOW, "SeriesName": "Sample Show",
            "PremiereDate": f"{aired}T00:00:00Z", "RunTimeTicks": 43 * TICKS}


EPISODES = [ep(E1, S1, 1, 1, "Pilot Light"), ep(E2, S1, 1, 2, "Second Wind"), ep(E3, S1, 1, 3, "Far Future", "2099-01-01"),
            ep(E4, S2, 2, 1, "New Start")]


@pytest.fixture()
def tvc(monkeypatch, tmp_path):
    client, fake = guest_client(monkeypatch, tmp_path, {"jellyfin": LIB})
    fake.items[SHOW] = {"Id": SHOW, "Type": "Series", "Name": "Sample Show", "ProductionYear": 2026,
                        "Overview": "A show synopsis."}
    fake.items[S1] = {"Id": S1, "Type": "Season", "Name": "Season 1", "IndexNumber": 1, "SeriesId": SHOW,
                      "SeriesName": "Sample Show"}
    for e in EPISODES:
        fake.items[e["Id"]] = {**e, "Overview": f"What happens in {e['Name']}."}
    fake.episodes[SHOW] = EPISODES
    # the household (admin) and another friend have watched; the signed-in friend is 20 min into E1
    fake.played[ADMIN_ID] = {E1, E2}
    fake.played[OTHER_ID] = {E1}
    fake.positions[FRIEND_ID] = {E1: 20 * TICKS}
    with client as c:
        c.fake = fake
        sign_in(c, fake, FRIEND_ID)
        yield c


def section(html: str, cls: str) -> str:
    m = re.search(r'<section class="sec tvshelf ' + cls + r'"[^>]*>(.*?)</section>', html, flags=re.S)
    assert m, f"no {cls} shelf"
    return m.group(1)


def cards(shelf: str) -> list[str]:
    return re.findall(r'<a class="card-poster[^"]*"[^>]*>.*?</a>', shelf, flags=re.S)


def text(fragment: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", fragment)).strip()


# ---- 1-3: the Seasons and Episodes shelves on the series page ----

def test_tv_series_page_has_the_seasons_and_episodes_shelves(tvc):
    html = tvc.get(f"/media/item/{SHOW}", headers=TV).text
    assert '<details class="seasonbox' not in html                          # S1: no <details> list on the TV
    seasons = cards(section(html, "tv-seasons"))
    assert len(seasons) == 2
    assert f'href="/media/item/{S1}"' in seasons[0] and f"/img/jf:{S1}?h=" in seasons[0]
    assert "Season 1" in text(seasons[0]) and "0 of 3 watched" in text(seasons[0])
    eps = section(html, "tv-eps")
    assert "Episodes · Season 1" in eps                                     # the next episode's season
    one, two, three = cards(eps)
    for card, jf in ((one, E1), (two, E2), (three, E3)):
        assert f'src="/img/jf:{jf}?h=400' in card                           # 16:9 still through the proxy
    assert "E1 · Pilot Light" in text(one) and "E2 · Second Wind" in text(two)


def test_ok_on_an_episode_card_is_the_jellyfin_hand_off(tvc):
    eps = section(tvc.get(f"/media/item/{SHOW}", headers=TV).text, "tv-eps")
    one, two, three = cards(eps)
    href = re.search(r'href="([^"]+)"', two).group(1).replace("&amp;", "&")
    assert href.startswith(PUBLIC_URL + "/web/#/details?id=" + E2) and f'data-jf-id="{E2}"' in two
    # not aired: no hand-off, the card opens the episode page
    assert f'href="/media/item/{E3}"' in three and "data-jf-id" not in three


def test_episode_cards_carry_state_words_and_progress(tvc):
    one, two, three = cards(section(tvc.get(f"/media/item/{SHOW}", headers=TV).text, "tv-eps"))
    assert "Next" in text(one) and "23m left" in text(one)                  # 20 of 43 min in: the next to watch
    assert re.search(r'<span class="bar" role="img" aria-label="\d+% watched">', one)
    assert "Watched" not in text(two) and "Next" not in text(two)
    assert "Not aired" in text(three)


# ---- 7: a friend's shelves are the friend's own ----

def test_a_friend_sees_only_their_own_watch_state(tvc):
    html = tvc.get(f"/media/item/{SHOW}", headers=TV).text
    shelves = section(html, "tv-seasons") + section(html, "tv-eps")
    assert "Watched" not in text(shelves) and "0 of 3 watched" in text(shelves)   # the household watched E1 + E2
    reads = [c for c in tvc.fake.calls if c[0] == "GET" and c[1] == f"/Shows/{SHOW}/Episodes"]
    assert reads and {str((c[4] or {}).get("userId")) for c in reads} == {FRIEND_ID}
    sign_in(tvc, tvc.fake, OTHER_ID)                                        # another friend, who watched E1
    html = tvc.get(f"/media/item/{SHOW}", headers=TV).text
    one = cards(section(html, "tv-eps"))[0]
    assert "Watched" in text(one) and "1 of 3 watched" in text(section(html, "tv-seasons"))


# ---- 8: no live image call on render ----

def test_rendering_the_shelves_makes_no_image_call(tvc):
    tvc.get(f"/media/item/{SHOW}", headers=TV)
    tvc.get(f"/media/item/{E2}", headers=TV)
    assert not [p for p in tvc.fake.paths() if "/Images" in p]


# ---- 4-5: the episode page ----

def test_tv_episode_hero_leads_with_the_episode(tvc):
    html = tvc.get(f"/media/item/{E2}", headers=TV).text
    start = html.index('<header class="pagehead hero-detail')
    hero = html[start:html.index("</header>", start)]
    assert f'data-tv-up="/media/item/{SHOW}"' in hero                       # X1: Back = series
    assert 'class="crumbs"' not in html                                      # no breadcrumb on the TV
    assert f'src="/img/jf:{E2}?h=600' in hero and "tv-epstill" in hero       # the still leads
    assert re.search(r'<p class="epeyebrow tv-eyebrow">Sample Show<span class="sep"> · </span>Season 1</p>', hero)
    assert re.search(r'<h1 class="hero-detail-title">Second Wind</h1>', hero)
    assert "E2 of 3" in text(hero) and "What happens in Second Wind." in hero
    btns = re.search(r'<div class="hero-detail-btns">(.*?)</div>\s*(?:<div class="tv-rate"|</div>)', hero, flags=re.S).group(1)
    assert f'data-jf-id="{E2}"' in btns
    assert re.search(rf'<a class="btn btn-glass" href="/media/item/{S1}">Season</a>', btns)
    assert "data-tv-rate" in btns
    eps = section(html, "tv-eps")
    two = cards(eps)[1]
    assert "This one" in text(two)


def test_tv_season_page_keeps_the_eyebrow_and_marks_this_season(tvc):
    html = tvc.get(f"/media/item/{S1}", headers=TV).text
    assert '<p class="epeyebrow">Season 1 of 2</p>' in html                 # JY-116
    assert f'data-tv-up="/media/item/{SHOW}"' in html
    s1, s2 = cards(section(html, "tv-seasons"))
    assert "This season" in text(s1) and 'aria-current="page"' in s1 and "This season" not in text(s2)


# ---- 6: the Rate button (Gate 1 pick 1B) ----

def test_tv_rating_is_a_rate_button_over_the_existing_picker(tvc):
    film = "f11f" * 8
    tvc.fake.items[film] = {"Id": film, "Type": "Movie", "Name": "Chip Film", "ProductionYear": 2001,
                            "Overview": "A synopsis line.", "RunTimeTicks": 100 * TICKS}
    html = tvc.get(f"/media/item/{film}", headers=TV).text
    btn = re.search(r'<button type="button" class="btn btn-glass tv-ratebtn"[^>]*>.*?</button>', html, flags=re.S).group(0)
    assert 'data-tv-rate' in btn and 'aria-controls="tv-rate"' in btn and 'aria-expanded="false"' in btn
    assert text(btn) == "Rate"
    assert '<div class="tv-rate" id="tv-rate" hidden>' in html
    strip = html[html.index('<div class="tv-rate" id="tv-rate" hidden>'):]
    assert strip.count('name="score"') == 10 and 'action="/media/rate"' in strip


# ---- off the TV nothing changes ----

def test_off_the_tv_the_pages_are_unchanged(tvc):
    show = tvc.get(f"/media/item/{SHOW}").text
    assert '<details class="seasonbox' in show and "tvshelf" not in show and "data-tv-rate" not in show
    epp = tvc.get(f"/media/item/{E2}").text
    assert 'class="crumbs"' in epp and "data-tv-up" not in epp and "tv-epstill" not in epp
    assert "S01E02 · Second Wind" in epp


# ---- 10: the CSS block ----

def test_the_u6_css_block(tvc):
    css = design_px(tvc.get("/static/tv.css").text)
    start = css.index("/* ---- U6 (JY-192")
    block = re.sub(r"/\*.*?\*/", "", css[start:], flags=re.S)
    assert ":hover" not in block
    sizes = [float(x) for x in re.findall(r"font-size:\s*([\d.]+)px", block)]
    assert sizes and min(sizes) >= 18
    for rule in (".tvshelf", ".tv-eps", "aspect-ratio: 16 / 9", ".tv-rate[hidden]", ".crumbs", ".tv-epstill"):
        assert rule in block, rule


# ---- 5-6 under node: the Rate strip and Back = series (tv.js) ----

RATE_PAGE = r"""
var strip, rateBtn;
function ratetitle(path, up) {
  var main = shell('movies');
  rateBtn = new El('button', { name: 'rate', cls: ['tv-ratebtn'], attrs: { 'data-tv-rate': '', 'aria-controls': 'tv-rate',
                                'aria-expanded': 'false' }, top: 300, left: 700 });
  rateBtn.append(new El('span', { name: 'ratelbl', cls: ['tv-ratelbl'], top: 300, left: 700 }));
  rateBtn.children[0].textContent = 'Rate';
  var hero = new El('header', { cls: ['pagehead', 'hero-detail'], attrs: up ? { 'data-tv-up': up } : {}, top: 100 });
  main.append(hero);
  main.append(new El('div', { cls: ['hero-detail-btns'], kids: [
    new El('a', { name: 'play', attrs: { href: '/jf/play', 'data-jf-id': 'x' }, top: 300, left: 100 }), rateBtn] }));
  var pick = new El('form', { cls: ['ratepick'] });
  for (var i = 1; i <= 10; i++) pick.append(new El('button', { name: 'chip' + i, attrs: { name: 'score' }, top: 380, left: 100 + (i - 1) * 70 }));
  strip = new El('div', { cls: ['tv-rate'], attrs: { id: 'tv-rate', hidden: '' }, kids: [pick] });
  main.append(strip);
  poster(main, 's1', 900, 1, 0);
}
function click(el) { fire('click', { target: el, preventDefault: function () {} }); }
function rated(n) {   /* htmx swaps the picker for the rated form (outerHTML) */
  strip.children = [];
  var num = new El('span', { cls: ['stat-number'], top: 380 }); num.textContent = String(n);
  strip.append(new El('form', { cls: ['rated'], kids: [num, new El('button', { name: 'undo', cls: ['undo'], top: 380 })] }));
  fire('htmx:afterSwap', { detail: {} }); fire('htmx:afterSettle', {}); flush();
}
var replaced = [];
window.location.replace = function (u) { replaced.push(u); };
"""


def run_rate(gc, tmp_path, scenario):
    return run_tv_pages(gc, tmp_path, RATE_PAGE + scenario)


@pytest.fixture()
def gc(monkeypatch, tmp_path):
    client, fake = guest_client(monkeypatch, tmp_path)
    with client as c:
        c.fake = fake
        sign_in(c, fake, FRIEND_ID)
        yield c


def test_the_rate_button_opens_the_strip_and_back_closes_it_under_node(gc, tmp_path):
    out = run_rate(gc, tmp_path, r"""
load('/media/item/1', function () { ratetitle('/media/item/1'); });
key('ArrowRight');
out.on_button = now();
out.hidden_before = 'hidden' in strip.attrs;
click(rateBtn); flush();
out.opened = now(); out.hidden_open = 'hidden' in strip.attrs; out.expanded = rateBtn.attrs['aria-expanded'];
out.back = window.joeyTV.back();
out.after_back = now(); out.hidden_after = 'hidden' in strip.attrs; out.replaced = replaced.length;
click(rateBtn); flush();
key('ArrowRight'); key('ArrowRight');
rated(3);
out.after_rating = now(); out.hidden_rated = 'hidden' in strip.attrs; out.label = rateBtn.children[0].textContent;
""")
    assert out == {"on_button": "rate", "hidden_before": True, "opened": "chip1", "hidden_open": False,
                   "expanded": "true", "back": True, "after_back": "rate", "hidden_after": True, "replaced": 0,
                   "after_rating": "rate", "hidden_rated": True, "label": "Rated 3"}


def test_back_on_an_episode_goes_to_the_series_under_node(gc, tmp_path):
    out = run_rate(gc, tmp_path, r"""
/* from Overview straight to an episode: Back replaces it with the series */
load('/a/media', overview);
load('/media/item/ep1', function () { ratetitle('/media/item/ep1', '/media/item/show'); });
out.from_overview = window.joeyTV.back(); out.to = replaced.slice();
/* from the series to the episode: Back is the shell's own (history back, JY-187 memory) */
replaced = [];
load('/media/item/show', function () { ratetitle('/media/item/show'); });
load('/media/item/ep1', function () { ratetitle('/media/item/ep1', '/media/item/show'); });
out.from_series = window.joeyTV.back(); out.to_series = replaced.slice();
/* a page with no up link: unchanged (false) */
load('/media/item/film', function () { ratetitle('/media/item/film'); });
out.film = window.joeyTV.back();
""")
    assert out == {"from_overview": True, "to": ["/media/item/show"], "from_series": False, "to_series": [],
                   "film": False}


# ---- review round (2026-10-25): JY-188 density underneath, the household viewer ----

def _rules(css: str, selector: str) -> list[str]:
    """The declaration blocks of every rule whose selector list contains `selector` exactly."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    return [body for sels, body in re.findall(r"([^{}]+)\{([^}]*)\}", css)
            if selector in [s.strip() for s in sels.split(",")]]


def _spec(sel: str) -> tuple[int, int, int]:
    s = sel.replace("*", "")
    return (s.count("#"), len(re.findall(r"\.[\w-]+|\[[^\]]+\]|:[\w-]+", s)), len(re.findall(r"(?:^|[\s>+~])[a-z]+", s)))


def test_shelf_captions_stay_visible_over_the_jy188_focus_only_rule(tvc):
    css = design_px(tvc.get("/static/tv.css").text)
    hide, show = "html.tv .card-poster .row-meta", "html.tv .tvshelf .card-poster .row-meta"
    assert any("visibility: hidden" in b for b in _rules(css, hide))          # JY-188: captions on focus only
    assert any("visibility: visible" in b for b in _rules(css, show))         # U6: state captions always
    assert _spec(show) > _spec(hide) and css.rindex(show) > css.rindex(hide)
    html = tvc.get(f"/media/item/{S1}", headers=TV).text                       # the captions are row-meta inside .tvshelf
    s1 = cards(section(html, "tv-seasons"))[0]
    assert re.search(r'<span class="row-meta">.*This season.*0 of 3 watched</span>', s1, flags=re.S)


def test_episode_cards_keep_236px_over_the_jy188_carousel_width(tvc):
    css = design_px(tvc.get("/static/tv.css").text)
    base, eps = "html.tv .carousel > *", "html.tv .tv-eps .carousel > *"
    assert any("width: 92px" in b for b in _rules(css, base))   # JY-259 (2026-10-28): the row card is 92 px (was 104)
    assert any("flex: 0 0 236px; width: 236px" in b for b in _rules(css, eps))
    assert _spec(eps) > _spec(base) and css.rindex(eps) > css.rindex(base)


def test_household_viewer_on_the_tv_sees_their_own_state(tvc):
    """B.'s own session on the media front (the alias user, P3): the shelves are the alias user's watch state, read as
    that user - not the admin's, not a friend's."""
    tvc.fake.played[ALIAS_ID] = {E1}
    sign_in(tvc, tvc.fake, ALIAS_ID)
    tvc.fake.calls.clear()
    html = tvc.get(f"/media/item/{SHOW}", headers=TV).text
    one, two, _ = cards(section(html, "tv-eps"))
    assert "Watched" in text(one) and "Next" in text(two) and "Watched" not in text(two)   # admin watched E2 too
    assert "1 of 3 watched" in text(section(html, "tv-seasons"))
    reads = [c for c in tvc.fake.calls if c[0] == "GET" and c[1] == f"/Shows/{SHOW}/Episodes"]
    assert reads and {str((c[4] or {}).get("userId")) for c in reads} == {ALIAS_ID}
