"""JY-250 (2026-10-25): the failures of the grouped TV session (JoeyTV\\scripts\\logs\\tv_session_1025.log), checks 7, 9 /
36, 13, 15 and 28. The CSS fixes are read from tv.css (rule, value and specificity over the base rule); Back from an
episode (#15) runs tv.js under node with the JY-187 fake DOM plus a history model of the shell's WebView."""
import re
from pathlib import Path

import pytest

from tests.hub.fake_jellyfin import FRIEND_ID
from tests.hub.guest_pages import guest_client, sign_in
from tests.hub.test_tv_series_episodes import RATE_PAGE, _rules, _spec
from tests.hub.test_tv_mode import run_tv_pages
from tests.hub.tv_css import design_px

STATIC = Path(__file__).resolve().parents[2] / "hub" / "static"
TV_CSS = design_px((STATIC / "tv.css").read_text(encoding="utf-8"))
BASE_CSS = (STATIC / "control-surface.css").read_text(encoding="utf-8")


def px(body: str, prop: str) -> float:
    m = re.search(rf"(?:^|[;\s]){prop}:\s*([\d.]+)px", body)
    assert m, (prop, body)
    return float(m.group(1))


def wins(tv_sel: str, base_sel: str) -> bool:
    """The TV rule outranks the base rule (tv.css loads after control-surface.css)."""
    return _spec(tv_sel) > _spec(base_sel)


# ---- #7: the 404 page is centred on the TV ----

def test_404_resets_the_narrow_max_width_on_the_tv():
    assert any("max-width: 32rem" in b for b in _rules(BASE_CSS, ".narrow"))   # the page section is "sec narrow nf"
    sel = "html.tv .sec.nf"
    assert any(re.search(r"max-width:\s*none", b) for b in _rules(TV_CSS, sel)), "no max-width reset on the TV 404"
    assert wins(sel, ".narrow")
    assert '<section class="sec narrow nf">' in (STATIC.parent / "templates" / "404.html").read_text(encoding="utf-8")


# ---- #9 / #36: the Tonight row fits the 864 px safe area ----

SAFE_W = 960 - 2 * 48   # the 960 px TV viewport less the 48 px overscan margins
DEAL_W = 164            # "Deal again" as drawn on the TCL (2026-10-25 capture: 884 px row - 3 x 200 - 3 x 40)
RING = 7                # the 4 px focus ring, 3 px out (tv.js RING)


def test_tonight_row_fits_inside_the_safe_area():
    card = _rules(TV_CSS, "html.tv .poster-grid.big .card-poster")
    grid = _rules(TV_CSS, "html.tv .poster-grid.big")
    sec = _rules(TV_CSS, "html.tv .sec.tn")
    w = px(card[-1], "width")
    gap = px(next(b for b in grid if "gap" in b), "gap")
    col = px(next(b for b in sec if "column-gap" in b), "column-gap")
    assert w == 200                                                  # JY-189's cards (posters fetched at h=400) stay
    row = 3 * w + 2 * gap + col + DEAL_W
    assert row + 2 * RING <= SAFE_W, f"Tonight row {row} px (+ rings) > {SAFE_W} px"


# ---- #13: the season page's "Season N of M" eyebrow is TV size ----

def test_season_eyebrow_is_at_least_18px_on_the_tv():
    assert any("font-size: 12px" in b for b in _rules(BASE_CSS, ".epeyebrow"))
    sel = "html.tv .epeyebrow"
    rules = _rules(TV_CSS, sel)
    assert rules and px(rules[-1], "font-size") >= 18
    assert wins(sel, ".epeyebrow")
    tv_eyebrow = _rules(TV_CSS, "html.tv .hero-detail-text > .tv-eyebrow")[-1]   # JY-192's eyebrow: the same look
    for decl in ("font-size: 18px", "font-weight: 600", "letter-spacing: .1em", "text-transform: uppercase",
                 "color: var(--tv-t4)"):
        assert decl in tv_eyebrow and decl in rules[-1], decl


# ---- #28: the Diary month card is one row on the TV ----

def test_diary_month_card_is_a_row_on_the_tv():
    assert any("flex-direction: column" in b for b in _rules(BASE_CSS, ".monthcard"))
    sel = "html.tv .tvmonth"
    assert any("flex-direction: row" in b for b in _rules(TV_CSS, sel)), "the month card stacks (column) on the TV"
    assert wins(sel, ".monthcard")


# ---- #15: Episode (from Home) -> Back -> series -> Back -> Home, under node ----

HISTORY = RATE_PAGE + r"""
/* The shell's WebView history. enter() is a navigation that adds an entry: without a user gesture (the session script's
   `location.href = ...`) Chromium marks the entry being left skippable, and WebView goBack() passes over it;
   history.back() from the page does not. location.replace() swaps the current entry. */
var PAGES = {
  '/media/movies': function () { movies(1); },
  '/a/media': overview,
  '/media/item/show': function () { ratetitle('/media/item/show'); },
  '/media/item/ep1': function () { ratetitle('/media/item/ep1', '/media/item/show'); }
};
var hist = [], at = -1, todo = null;
function go(path) { load(path, PAGES[path]); }
function enter(path, gesture) {
  if (at >= 0 && !gesture) hist[at].skip = true;
  hist = hist.slice(0, at + 1); hist.push({ path: path }); at = hist.length - 1;
  go(path);
}
window.location.replace = function (u) { todo = function () { hist[at] = { path: u }; go(u); }; };
window.history = {
  get length() { return hist.length; },
  back: function () { todo = function () { if (at > 0) { at--; go(hist[at].path); } }; }
};
function shellBack() {   /* tv/ BackPolicy: ask the page; else exit on Home; else WebView goBack */
  todo = null;
  var handled = window.joeyTV.back(), next = todo;
  todo = null;
  if (next) next();
  if (handled) return window.location.pathname;
  if (window.location.pathname === '/a/media') return 'exit';
  var i = at - 1;
  while (i >= 0 && hist[i].skip) i--;
  if (i < 0) return 'no history';   /* the shell then loads Home (LOAD_HOME) */
  at = i; go(hist[i].path);
  return window.location.pathname;
}
function trip(n) { var s = []; for (var i = 0; i < n; i++) s.push(shellBack()); return s; }
"""


@pytest.fixture()
def gc(monkeypatch, tmp_path):
    client, fake = guest_client(monkeypatch, tmp_path)
    with client as c:
        sign_in(c, fake, FRIEND_ID)
        yield c


def run_back(gc, tmp_path, scenario):
    return run_tv_pages(gc, tmp_path, HISTORY + scenario)


@pytest.mark.parametrize("gesture", [True, False], ids=["remote", "no-gesture"])
def test_episode_from_home_back_series_back_home_under_node(gc, tmp_path, gesture):
    """#15: the remote (OK on a poster: a user gesture) and the session script (`location.href`, none) both end on Home,
    with JY-187's remembered poster focused there, and the next Back exits."""
    out = run_back(gc, tmp_path, rf"""
enter('/media/movies', true);
enter('/a/media', true);
['ArrowDown', 'ArrowRight'].forEach(key);
out.picked = now();
enter('/media/item/ep1', {'true' if gesture else 'false'});
out.steps = trip(1);
out.hist_after_up = hist.map(function (h) {{ return h.path; }});
out.steps = out.steps.concat(trip(1));
out.home_focus = now();
out.steps = out.steps.concat(trip(1));
""")
    assert out["hist_after_up"] == ["/media/movies", "/a/media", "/media/item/show"]   # the series replaced the episode
    assert out["steps"] == ["/media/item/show", "/a/media", "exit"]
    assert out["home_focus"] == out["picked"] and out["picked"].startswith("o")


def test_series_then_episode_back_is_plain_history_and_never_loops_under_node(gc, tmp_path):
    """JY-192's no-loop guarantee: from the series to an episode, Back is the shell's own (the series), and the next
    Back leaves the series for the page before it, never the episode again. A stale up-mark does not survive leaving
    the series."""
    out = run_back(gc, tmp_path, r"""
enter('/a/media', true);
enter('/media/item/show', true);
enter('/media/item/ep1', true);
out.a = trip(3);
enter('/a/media', true);
enter('/media/item/ep1', true);
out.b = trip(1);                      /* up: the series replaces the episode */
enter('/media/item/ep1', true);       /* OK on the episode again */
out.b = out.b.concat(trip(3));
""")
    assert out["a"] == ["/media/item/show", "/a/media", "exit"]
    assert out["b"] == ["/media/item/show", "/media/item/show", "/a/media", "exit"]


def test_episode_as_the_first_page_still_goes_up_then_leaves_back_to_the_shell_under_node(gc, tmp_path):
    """A deep link (the hand-off reopen, a process kill): no page before the episode. Back goes to the series; the next
    Back is not taken by the page (the shell loads Home)."""
    out = run_back(gc, tmp_path, r"""
enter('/media/item/ep1', true);
out.steps = trip(2);
""")
    assert out["steps"] == ["/media/item/show", "no history"]
