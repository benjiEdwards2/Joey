"""Joey TV sign-out control (2026-10-22): POST /signout existed (WP-B2) but no page reached it. On the media front a
signed-in guest's top-bar user chip is a button opening a confirm <dialog>. Option D + pop-up P2
(JoeyTV/mockups/signout-options.html): one pill = avatar initial + name + an exit icon, labelled "Sign out <name>";
the pop-up explains what signing out costs; "Sign out" (orange, exit icon) is a plain full-page form POST /signout
(hx-boost off); "Stay signed in" closes it (data-close: tv.js back() clicks it on the remote's Back) and starts focused.
No chip button or dialog on /signin, for a visitor who is not signed in, or on the private front."""
import re
from html.parser import HTMLParser

import pytest

from hub import guest
from tests.hub.fake_jellyfin import FRIEND_ID, HTTPS
from tests.hub.guest_pages import TV_UA, guest_client, sign_in
from tests.hub.tv_css import design_px

CLEARED = "__Host-jm_session=; Max-Age=0; Path=/; HttpOnly; Secure; SameSite=Lax"


@pytest.fixture()
def gc(monkeypatch, tmp_path):
    client, fake = guest_client(monkeypatch, tmp_path)
    with client as c:
        c.fake = fake
        yield c


@pytest.fixture()
def friend(gc):
    gc.token = sign_in(gc, gc.fake, FRIEND_ID)
    return gc


def topbar(html: str) -> str:
    return re.search(r'<header class="topbar">(.*?)</header>', html, re.S).group(1)


class Forms(HTMLParser):
    """Each <form>: its attributes and the (name, value) of its named inputs / buttons."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.forms: list[dict] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "form":
            self.forms.append({"attrs": a, "fields": []})
        elif tag in ("input", "button") and self.forms and a.get("name"):
            self.forms[-1]["fields"].append((a["name"], a.get("value") or ""))


def signout_form(html: str) -> dict:
    p = Forms()
    p.feed(topbar(html))
    (form,) = [f for f in p.forms if f["attrs"].get("action") == "/signout"]
    return form


EXIT_ICON = '<svg class="ic" viewBox="0 0 24 24" aria-hidden="true"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/>'
P2_BODY = ("You're signed in as Sample Friend on this device. To come back you'll need a new Quick Connect code "
           "(or your password).")


def chip_of(html: str) -> re.Match:
    return re.search(r'<button class="userchip"[^>]*>(.*?)</button>', topbar(html), re.S)


def dialog_of(html: str) -> str:
    return re.search(r'<dialog id="signout-dlg"[^>]*>(.*?)</dialog>', topbar(html), re.S).group(1)


@pytest.mark.parametrize("path", ["/a/media", "/media/movies", "/media/discover"])
@pytest.mark.parametrize("ua", [None, TV_UA])
def test_a_signed_in_guest_page_has_the_chip_and_the_confirm(friend, path, ua):
    r = friend.get(path, headers={"User-Agent": ua} if ua else {})
    assert r.status_code == 200
    top = topbar(r.text)
    chip = chip_of(r.text)
    assert chip and 'aria-controls="signout-dlg"' in chip.group(0) and "showModal()" in chip.group(0)
    assert '<span class="avatar" aria-hidden="true">S</span><span class="uname">Sample Friend</span>' in chip.group(1)
    dlg = dialog_of(r.text)
    assert "Sign out of Joey Media?" in dlg
    assert P2_BODY in dlg
    assert re.search(r'<button class="btn btn-signout" type="submit"><svg class="ic"[^>]*aria-hidden="true">.*?</svg>'
                     r'<span>Sign out</span></button>', dlg, re.S)
    stay = re.search(r'<button [^>]*>Stay signed in</button>', dlg).group(0)
    assert "data-close" in stay and "data-first" in stay and "autofocus" in stay and 'type="button"' in stay
    assert "Cancel" not in dlg and "metaline" not in dlg
    form = signout_form(r.text)["attrs"]
    assert (form.get("method"), form.get("hx-boost")) == ("post", "false")
    assert top.count('class="userchip"') == 1


def test_the_pill_is_labelled_sign_out_and_carries_the_exit_icon(friend):
    chip = chip_of(friend.get("/media/movies", headers={"User-Agent": TV_UA}).text)
    assert 'aria-label="Sign out Sample Friend"' in chip.group(0) and 'title="Sign out Sample Friend"' in chip.group(0)
    inner = chip.group(1)
    assert inner.endswith("</svg>") and EXIT_ICON in inner                  # the exit icon, last, hidden from AT
    assert '<span class="xlbl" aria-hidden="true">Sign out</span>' in inner  # the words TV shows on focus
    assert inner.index('class="uname"') < inner.index('class="xlbl"') < inner.index("<svg")


def test_only_stay_signed_in_is_autofocused(friend):
    dlg = dialog_of(friend.get("/media/movies").text)
    buttons = re.findall(r"<button [^>]*>", dlg)
    assert len(buttons) == 2
    signout, stay = buttons
    assert "autofocus" not in signout and "data-first" not in signout and "data-close" not in signout
    assert "autofocus" in stay and "data-first" in stay
    assert dlg.count("autofocus") == 1 and dlg.index("btn-signout") < dlg.index("Stay signed in")


def test_a_long_name_truncates_in_the_pill(friend):
    friend.fake.users[FRIEND_ID]["Name"] = long = "Alexandra Montgomery-Smithson the Third"
    sign_in(friend, friend.fake, FRIEND_ID)
    chip = chip_of(friend.get("/media/movies", headers={"User-Agent": TV_UA}).text)
    assert f'<span class="uname">{long}</span>' in chip.group(1) and f'aria-label="Sign out {long}"' in chip.group(0)
    shared = friend.get("/static/control-surface.css").text
    assert re.search(r"\.userchip \.uname \{[^}]*overflow: hidden; text-overflow: ellipsis; white-space: nowrap", shared)
    assert re.search(r"button\.userchip \.uname \{ max-width: 12em; \}", shared)
    tv = design_px(friend.get("/static/tv.css").text)
    assert re.search(r"html\.tv button\.userchip \.uname \{ max-width: 150px;", tv)
    # the TV section row never shrinks, so only the pill gives way (its name ellipsises) and nothing in the row moves
    assert re.search(r"html\.tv \.toplinks \{[^}]*flex-shrink: 0", tv)


def test_the_pop_up_buttons_are_styled_like_the_mockup(friend):
    shared = friend.get("/static/control-surface.css").text
    assert "--signout: #f97316;" in shared and "--signout-fg: #1a0a00;" in shared
    assert ".btn-signout { background: var(--signout); color: var(--signout-fg); }" in shared
    tv = re.sub(r"/\*.*?\*/", "", design_px(friend.get("/static/tv.css").text), flags=re.S)
    assert ".btn-signout { background: #f97316; color: #1a0a00;" in tv
    # TV: the focused pill shows the words "Sign out" (tv.js marks D-pad focus with .tv-focus)
    assert re.search(r"html\.tv button\.userchip:focus-visible \.xlbl, html\.tv button\.userchip\.tv-focus \.xlbl \{ "
                     r"max-width: 110px", tv)
    # ...and the name folds away for them (no half-cut name beside the avatar initial)
    assert re.search(r"html\.tv button\.userchip:focus-visible \.uname, html\.tv button\.userchip\.tv-focus \.uname \{ "
                     r"max-width: 0", tv)


def test_tv_css_styles_the_confirm(friend):
    css = design_px(friend.get("/static/tv.css").text)
    assert "html.tv .signoutdlg {" in css and "html.tv .signoutdlg::backdrop" in css


def test_no_chip_button_on_the_signin_page(gc):
    r = gc.get("/signin")
    assert r.status_code == 200
    assert "userchip" not in r.text and "signout" not in r.text


def test_no_chip_button_for_a_visitor_who_is_not_signed_in(gc):
    r = gc.get("/no-such-page")
    assert r.status_code == 404
    assert "signout" not in r.text and '<button class="userchip"' not in r.text
    assert '<div class="userchip">' in topbar(r.text)        # the plain chip ("Not signed in"), as before


def test_the_private_front_has_no_chip_button(monkeypatch, tmp_path):
    client, _ = guest_client(monkeypatch, tmp_path)
    monkeypatch.setenv("JOEY_FRONT", "private")
    with client as c:
        html = c.get("/media/movies").text
    assert "signout" not in html and '<button class="userchip"' not in html and "signoutdlg" not in html
    assert '<div class="userchip">' in topbar(html)


def test_the_form_signs_out_from_a_same_origin_post(friend):
    form = signout_form(friend.get("/media/movies").text)
    r = friend.post(form["attrs"]["action"], data=dict(form["fields"]), headers={"Origin": HTTPS},
                    follow_redirects=False)
    assert (r.status_code, r.headers["location"]) == (303, "/signin")
    assert CLEARED in r.headers.get_list("set-cookie")
    assert friend.fake.count("POST", "/Sessions/Logout") == 1 and friend.token not in friend.fake.tokens
    friend.cookies.clear()
    assert friend.get(guest.home_path(), follow_redirects=False).headers["location"].startswith("/signin")
