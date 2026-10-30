"""JY-270 years (B. 2026-10-30: "Can we please only use the major awards ceremonies. We need to allow people to go left or
right on awards to years or click a drop down view to select years."): the config/awards.yaml ceremony filter, and the TV
year stepper + list run under node in the JY-187 fake DOM (tests/hub/test_tv_mode.py)."""
from pathlib import Path

import pytest

from hub import media_awards_db as adb
from tests.hub.fake_jellyfin import FRIEND_ID
from tests.hub.guest_pages import guest_client, sign_in
from tests.hub.test_tv_mode import run_tv_pages

MAJORS = ["oscars", "globes", "bafta", "critics", "sag", "cannes", "emmys"]


# ---- the ceremony filter (config, not code) ----

def test_the_repo_config_keeps_the_majors_only():
    assert adb.shown_ids() == set(MAJORS)
    assert [b["id"] for b in adb.bodies("film")] == ["oscars", "globes", "bafta", "critics", "sag", "cannes"]
    assert [b["id"] for b in adb.bodies("tv")] == ["globes", "critics", "sag", "emmys"]


def test_the_filter_follows_the_file(monkeypatch, tmp_path):
    f = tmp_path / "awards.yaml"
    f.write_text("ceremonies:\n  - oscars\n  - dga\n", encoding="utf-8")
    monkeypatch.setattr(adb, "SHOWN_PATH", f)
    assert [b["id"] for b in adb.bodies("film")] == ["oscars", "dga"]
    f.write_text("ceremonies: []\n", encoding="utf-8")          # an empty list = every ceremony (widen later)
    assert len(adb.bodies("film")) == 9
    monkeypatch.setattr(adb, "SHOWN_PATH", tmp_path / "missing.yaml")
    assert adb.shown_ids() is None and len(adb.bodies("film")) == 9


def test_next_up_skips_the_hidden_ceremonies():
    from datetime import date
    names = {i["name"] for g in adb.coming_up(date(2026, 10, 8), "film", limit=12) for i in g["events"]}
    assert not names & {"DGA", "PGA", "WGA"} and "Oscars" in names


# ---- the TV stepper and list, under node ----

YEARS = r"""
function awards(on) {   /* the TV Awards page: ceremony chips, the year stepper + its hidden list, one shelf */
  var main = shell('movies'), cer = new El('nav', { cls: ['chips', 'awtv-cer'], top: 120 });
  ['oscars', 'globes'].forEach(function (b, i) {
    var attrs = { href: '/media/movies/awards?body=' + b };
    if (!i) { attrs['aria-current'] = 'true'; attrs['data-first'] = ''; }
    cer.append(new El('a', { name: 'cer-' + b, cls: ['chip'], attrs: attrs, top: 120, left: 100 + i * 150 }));
  });
  main.append(cer);
  var ys = [2025, 2024, 2023], i = ys.indexOf(on);
  var btn = new El('button', { name: 'yearbtn', cls: ['chip', 'awtv-yrbtn'], top: 170, left: 100, attrs: {
    type: 'button', 'data-tv-year': '', 'data-prev': String(ys[(i + 1) % 3]), 'data-next': String(ys[(i + 2) % 3]),
    'aria-controls': 'awtv-yrlist', 'aria-expanded': 'false' } });
  var list = new El('div', { name: 'list', cls: ['awtv-yrlist'], top: 220,
                             attrs: { id: 'awtv-yrlist', role: 'listbox', hidden: '' } });
  ys.forEach(function (y, n) {
    var attrs = { href: '/media/movies/awards?body=oscars&year=' + y, role: 'option', 'data-year': String(y) };
    if (y === on) attrs['aria-selected'] = 'true';
    list.append(new El('a', { name: 'y' + y, cls: ['chip'], attrs: attrs, top: 220 + n * 50, left: 100 }));
  });
  main.append(new El('nav', { cls: ['chips', 'awtv-yr'], top: 170, kids: [btn, list] }));
  poster(main, 'p1', 1, 1, 0);
}
function link(y) { return document.querySelector('[data-year="' + y + '"]'); }
function openNow() { return document.querySelector('[id="awtv-yrlist"]').getAttribute('hidden') === null; }
"""


@pytest.fixture()
def gc(monkeypatch, tmp_path):
    client, fake = guest_client(monkeypatch, tmp_path)
    with client as c:
        sign_in(c, fake, FRIEND_ID)
        yield c


def test_left_right_on_the_stepper_step_the_year_and_keep_the_focus_under_node(gc, tmp_path):
    out = run_tv_pages(gc, tmp_path, YEARS + r"""
load('/media/movies/awards', function () { awards(2024); });
out.first = now();
key('ArrowDown'); out.down = now();
key('ArrowRight'); out.right_clicked = [link(2025).clicks || 0, link(2023).clicks || 0];
/* the boosted swap of the 2025 page lands; the stepper takes the focus back */
fire('htmx:beforeSwap', { detail: { boosted: true, shouldSwap: true } });
awards(2025); fire('htmx:afterSettle', {}); flush();
out.after_step = now();
key('ArrowLeft'); out.left_clicked = link(2024).clicks || 0;
out.list_closed = !openNow();
""")
    assert out == {"first": "cer-oscars", "down": "yearbtn", "right_clicked": [1, 0], "after_step": "yearbtn",
                   "left_clicked": 1, "list_closed": True}


def test_ok_opens_the_year_list_up_down_move_back_closes_under_node(gc, tmp_path):
    out = run_tv_pages(gc, tmp_path, YEARS + r"""
load('/media/movies/awards', function () { awards(2024); });
key('ArrowDown');
var stopped = press('Enter');
out.open = [openNow(), stopped, now(), document.querySelector('[data-tv-year]').getAttribute('aria-expanded')];
key('ArrowDown'); out.down = now();
key('ArrowLeft'); out.left = now();               /* Left / Right do nothing in the list */
key('ArrowDown'); out.bottom = now();             /* the D-pad stays in the open list */
key('ArrowUp'); key('ArrowUp'); key('ArrowUp'); out.top = now();
out.back = window.joeyTV.back();
out.closed = [!openNow(), now()];
press('Enter'); key('ArrowUp');
press('Enter');                                   /* OK on a year: its link is followed (the browser's click) ... */
fire('htmx:beforeSwap', { detail: { boosted: true, shouldSwap: true } });
awards(2025); fire('htmx:afterSettle', {}); flush();
out.after_pick = now();                           /* ... and the new page focuses the stepper */
""")
    assert out == {"open": [True, True, "y2024", "true"], "down": "y2023", "left": "y2023", "bottom": "y2023",
                   "top": "y2025", "back": True, "closed": [True, "yearbtn"], "after_pick": "yearbtn"}
