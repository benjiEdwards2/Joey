"""JY-189 (U3; TV_UI_EVALUATION G2, T1, T2): in TV mode posters on shelves, grids and Tonight are fetched at h=600
(they were upscaled from 160x240 files); desktop and phone keep h=240; Tonight carries its TV layout hooks and tv.css
holds the matching rules. TV mode is forced here by patching the `tv_mode` Jinja global (the real trigger, the
JoeyTV/ user agent or cookie, is covered in test_tv_mode.py and only runs on the guest front)."""
import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.hub.test_media_frame import env  # noqa: F401
from tests.hub.test_media_library_pages import ARRV, body, jelly


def heights(html: str) -> set[str]:
    return set(re.findall(r'<img class="poster[^"]*" src="/img/[^"]*\?h=(\d+)&amp;', html))


@pytest.fixture()
def tv(monkeypatch):
    def force(on: bool):
        monkeypatch.setitem(sys.modules["hub.shell"].templates.env.globals, "tv_mode", lambda request: on)
    return force


PAGES = ["/media/movies/tonight", "/media/movies?view=grid", "/a/alpha"]


@pytest.mark.parametrize("path", PAGES)
def test_tv_mode_asks_for_600_and_normal_mode_is_unchanged(env, tv, path):
    main = env(jellyfin=jelly(), arr=ARRV)
    with TestClient(main.app) as c:
        tv(False)
        plain = body(c, path)[1]
        tv(True)
        big = body(c, path)[1]
    assert "240" in heights(plain) and "600" not in heights(plain), path     # non-TV: exactly as before
    assert heights(big) == {"600"}, path                                       # TV: every card poster is 600
    assert 'width="400" height="600"' in big


def test_tonight_has_its_tv_hooks_in_tv_mode(env, tv):
    main = env(jellyfin=jelly(), arr=ARRV)
    with TestClient(main.app) as c:
        tv(True)
        b = body(c, "/media/movies/tonight")[1]
    assert '<section class="sec tn">' in b and '<div class="poster-grid big">' in b
    assert b.count('class="card-poster tcard"') == 2 and '<div class="tn-deal"><a class="btn btn-secondary"' in b


def test_poster_macro_only_changes_with_the_tv_flag(env):
    from hub import shell
    tpl = shell.templates.env.from_string('{% from "_poster.html" import poster %}{{ poster("jf:ab", "Ab", 240) }}|{{ poster("jf:ab", "Ab", 240, "", true) }}|{{ poster("jf:ab", "Ab", 120, "row-poster") }}')
    a, b, c = tpl.render().split("|")
    assert "?h=240&amp;" in a and "?h=600&amp;" in b and "?h=120&amp;" in c


def test_tv_css_carries_the_tonight_rules_without_touching_the_shared_sheet():
    root = Path(__file__).resolve().parents[2] / "hub" / "static"
    tvcss = re.sub(r"/\*.*?\*/", "", (root / "tv.css").read_text(encoding="utf-8"), flags=re.S)
    assert re.search(r"html\.tv \.poster-grid\.big \{[^}]*display: flex[^}]*gap: 40px", tvcss)
    assert re.search(r"html\.tv \.poster-grid\.big \.card-poster \{[^}]*width: 200px", tvcss)
    assert re.search(r"html\.tv \.sec\.tn \{", tvcss) and ".tn-deal" in tvcss
    assert "html.tv" not in (root / "control-surface.css").read_text(encoding="utf-8")
