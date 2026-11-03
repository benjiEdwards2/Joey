"""JY-248 (2026-10-25): no Overview section on the media front; the "Joey Media" title is the way Home.

B., 2026-10-25: "Can you also remove the overview section, use the Joey Media as a way of going back to the home.
Expecially on the TV." The guest section row, the phone row and the phone tab bar lose Overview; the brand links
guest_home(), carries `brand-home`, and is aria-current on Home. The household (private) front keeps its Overview pill
(its brand goes to the hub, not Media home): tests/hub/test_media_nav.py and test_guest_nav.py's private-front test pin
it unchanged. The TV walk is in test_tv_mode.py (node, shared fake page)."""
import re

import pytest

from hub import guest
from tests.hub.fake_jellyfin import FRIEND_ID
from tests.hub.guest_pages import TV_UA, guest_client, sign_in
from tests.hub.tv_css import design_px


@pytest.fixture()
def friend(monkeypatch, tmp_path):
    client, fake = guest_client(monkeypatch, tmp_path)
    with client as c:
        c.fake = fake
        sign_in(c, fake, FRIEND_ID)
        yield c


def topbar(html: str) -> str:
    return re.search(r'<header class="topbar">(.*?)</header>', html, re.S).group(1)


def brand(html: str) -> str:
    return re.search(r'<a class="brand[^"]*"[^>]*>', topbar(html)).group(0)


@pytest.mark.parametrize("tv", [False, True])
def test_home_has_no_overview_pill_and_the_brand_is_current(friend, tv):
    headers = {"User-Agent": TV_UA} if tv else {}
    html = friend.get(guest.home_path(), headers=headers).text
    top = topbar(html)
    b = brand(html)
    assert 'class="brand brand-home"' in b and f'href="{guest.home_path()}"' in b
    assert 'aria-current="page"' in b                                   # Home's "you are here"
    row = re.search(r'<nav class="toplinks"[^>]*>(.*?)</nav>', top, re.S).group(1)
    assert "Overview" not in row and "aria-current" not in row          # no section is current on Home
    assert f'href="{guest.home_path()}"' not in row


@pytest.mark.parametrize("path", ["/media/movies", "/media/tv", "/media/diary", "/media/discover"])
def test_section_pages_keep_their_pill_and_the_brand_links_home(friend, path):
    html = friend.get(path).text
    b = brand(html)
    assert f'href="{guest.home_path()}"' in b and "aria-current" not in b
    row = re.search(r'<nav class="toplinks"[^>]*>(.*?)</nav>', topbar(html), re.S).group(1)
    assert re.findall(r'<a href="([^"]+)" aria-current="page">', row) == [path]
    assert ">Overview<" not in html


def test_the_css_gives_the_title_hover_focus_and_a_tv_stop(friend):
    shared = friend.get("/static/control-surface.css").text
    block = shared.split("JY-248 nav", 1)[1]
    assert ".brand-home:hover" in block and ".topbar:has(.brand-home)" in block   # hover; sticky on a phone
    # review 2026-10-25: below the notch in standalone mode, with an opaque band above it
    assert "top: env(safe-area-inset-top, 0px);" in block and "calc(-1 * env(safe-area-inset-top, 0px)) 0 var(--bg)" in block
    tv = design_px(friend.get("/static/tv.css").text)
    # JY-307 P2 (2026-11-03, option B): on the TV the title is the rail's Home stop (a house + "Home"), one rule with the
    # section stops (same 48 px row, the 20 px label size), filled like the current section on Home
    tvblock = tv.split("JY-307 P2", 1)[1]
    assert re.search(r"html\.tv \.tv-searchstop, html\.tv \.brand-home, html\.tv \.toplinks a, html\.tv \.userchip \{[^}]*"
                     r"height: 48px;[^}]*font-size: var\(--tv-fs-label\)", tvblock)
    assert "html.tv .brand-home[aria-current]" in tvblock
