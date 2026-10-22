"""Joey TV sign-out control (2026-10-22): POST /signout existed (WP-B2) but no page reached it. On the media front a
signed-in guest's top-bar user chip (avatar initial + name, the WP-M mockup) is a button opening a confirm <dialog>:
"Sign out" is a plain full-page form POST /signout (hx-boost off), "Cancel" closes it (data-close: tv.js back() clicks
it on the remote's Back) and starts focused. No chip button or dialog on /signin, for a visitor who is not signed in,
or on the private front."""
import re
from html.parser import HTMLParser

import pytest

from hub import guest
from tests.hub.fake_jellyfin import FRIEND_ID, HTTPS
from tests.hub.guest_pages import TV_UA, guest_client, sign_in

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


@pytest.mark.parametrize("path", ["/a/media", "/media/movies", "/media/discover"])
@pytest.mark.parametrize("ua", [None, TV_UA])
def test_a_signed_in_guest_page_has_the_chip_and_the_confirm(friend, path, ua):
    r = friend.get(path, headers={"User-Agent": ua} if ua else {})
    assert r.status_code == 200
    top = topbar(r.text)
    chip = re.search(r'<button class="userchip"[^>]*>(.*?)</button>', top, re.S)
    assert chip and 'aria-controls="signout-dlg"' in chip.group(0) and "showModal()" in chip.group(0)
    assert '<span class="avatar" aria-hidden="true">S</span><span class="uname">Sample Friend</span>' in chip.group(1)
    dlg = re.search(r'<dialog id="signout-dlg"[^>]*>(.*?)</dialog>', top, re.S).group(1)
    assert "Sign out of Joey Media?" in dlg and "Signed in as Sample Friend" in dlg
    assert re.search(r'<button class="btn btn-white" type="submit">Sign out</button>', dlg)
    cancel = re.search(r'<button [^>]*>Cancel</button>', dlg).group(0)
    assert "data-close" in cancel and "data-first" in cancel and "autofocus" in cancel and 'type="button"' in cancel
    form = signout_form(r.text)["attrs"]
    assert (form.get("method"), form.get("hx-boost")) == ("post", "false")
    assert top.count('class="userchip"') == 1


def test_tv_css_styles_the_confirm(friend):
    css = friend.get("/static/tv.css").text
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
