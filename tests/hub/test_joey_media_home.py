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
    tv = friend.get("/static/tv.css").text
    tvblock = tv.split("JY-248 nav", 1)[1]
    assert "html.tv .brand-home" in tvblock and ".brand-home[aria-current]" in tvblock
    # JY-188 compact chrome (2026-10-25): the stop is as tall as a section pill, so it fits the 64 px bar (27 + 36 + 1);
    # its text stays the brand's 22 px (>= the 18 px floor)
    pill = re.search(r"html\.tv \.toplinks a \{[^}]*height: (\d+)px", tv).group(1)
    stop = re.search(r"html\.tv \.brand-home \{[^}]*height: (\d+)px", tv).group(1)
    assert stop == pill and int(stop) + 27 + 1 <= 64
    assert int(re.search(r"html\.tv \.brand b \{[^}]*font-size: (\d+)px", tv).group(1)) >= 18
    assert "font-size" not in tvblock.split("*/", 1)[1].split("html.tv .userchip", 1)[0]
