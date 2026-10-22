"""Private sign-out (2026-10-22): joeyhome.net had no way to sign out. With a Cloudflare Access identity the top-bar user
chip is the same button + confirm <dialog> as the guest front (test_guest_signout_chip.py), but "Sign out" is a plain
GET link to Cloudflare Access's own logout, /cdn-cgi/access/logout (served by Cloudflare's edge, never by this app),
with hx-boost off. Local preview (no Access identity) keeps the static chip. The guest front never renders the Access
logout link, and the private front never the /signout form."""
import re

import pytest

from hub.identity import IDENTITY_HEADER
from tests.hub.fake_jellyfin import FRIEND_ID
from tests.hub.guest_pages import guest_client, sign_in
from tests.hub.test_owner_filter import client  # noqa: F401  (fixture)

YOU = "you@example.com"
LOGOUT = "/cdn-cgi/access/logout"


@pytest.fixture(autouse=True)
def _owner_env(monkeypatch):
    monkeypatch.setenv("OWNER_EMAIL_YOU", YOU)
    monkeypatch.delenv("OWNER_NAME_YOU", raising=False)


def topbar(html: str) -> str:
    return re.search(r'<header class="topbar">(.*?)</header>', html, re.S).group(1)


@pytest.mark.parametrize("path", ["/", "/weather"])
def test_signed_in_private_page_has_the_chip_and_the_access_logout(client, path):  # noqa: F811
    r = client.get(path, headers={IDENTITY_HEADER: YOU})
    assert r.status_code == 200
    top = topbar(r.text)
    chip = re.search(r'<button class="userchip"[^>]*>(.*?)</button>', top, re.S)
    assert chip and f'title="{YOU}"' in chip.group(0) and 'aria-controls="signout-dlg"' in chip.group(0)
    assert "showModal()" in chip.group(0) and f"<small>{YOU}</small>" in chip.group(1)
    dlg = re.search(r'<dialog id="signout-dlg"[^>]*>(.*?)</dialog>', top, re.S).group(1)
    assert "Sign out of Joey?" in dlg and f"Signed in as {YOU}" in dlg
    link = re.search(r'<a [^>]*>Sign out</a>', dlg).group(0)
    assert f'href="{LOGOUT}"' in link and 'hx-boost="false"' in link
    cancel = re.search(r'<button [^>]*>Cancel</button>', dlg).group(0)
    assert "data-close" in cancel and "autofocus" in cancel and 'type="button"' in cancel
    assert 'action="/signout"' not in r.text and "<form" not in dlg      # never the guest POST /signout
    assert top.count('class="userchip"') == 1


def test_local_preview_keeps_the_static_chip(client):  # noqa: F811
    top = topbar(client.get("/").text)
    assert '<div class="userchip"><span class="avatar"' in top and "<small>Local preview</small>" in top
    assert '<button class="userchip"' not in top and "signout-dlg" not in top and LOGOUT not in top


def test_no_app_route_for_the_access_logout(client):  # noqa: F811
    assert client.get(LOGOUT, headers={IDENTITY_HEADER: YOU}, follow_redirects=False).status_code == 404


@pytest.mark.parametrize("signed_in", [True, False])
def test_the_guest_front_never_renders_the_access_logout(monkeypatch, tmp_path, signed_in):
    c, fake = guest_client(monkeypatch, tmp_path)
    with c:
        if signed_in:
            sign_in(c, fake, FRIEND_ID)
        html = c.get("/media/movies" if signed_in else "/no-such-page", headers={IDENTITY_HEADER: YOU}).text
    assert "cdn-cgi" not in html and "Sign out of Joey?" not in html
    assert ('action="/signout"' in html) is signed_in
