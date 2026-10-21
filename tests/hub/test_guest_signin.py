"""Joey TV WP-B2 step 3-4 (2026-10-21): the media front's sign-in - Quick Connect first (DECISIONS B #18, Q33: the web
page IS the TV sign-in), username + password as the fallback, sign-out revoking the Jellyfin token. Cookies:
`__Host-jm_session` (the token, 90 days absolute - Q26), `__Host-jm_qc` (the Quick Connect secret, 10 min),
`__Host-jm_dev` (this browser's Jellyfin DeviceId, 400 days). Password failures: 5 per username in 15 min, then
refused WITHOUT asking Jellyfin (Q28 / D-P15), so the guest path never reaches Jellyfin's lockout (10). No username,
password, token or secret is ever logged. Jellyfin = tests/hub/fake_jellyfin.py (real 12.2 shapes)."""
import html
import logging
import re

import pytest
import requests
from fastapi.testclient import TestClient

from hub import guest, guest_auth
from tests.hub.fake_jellyfin import (ADMIN_ID, DEV, FRIEND_ID, HTTPS, OTHER_ID, FakeJellyfin, media_env, reload_app)

EVIL = {"Origin": "https://evil.example"}
SESSION_ATTRS = "; Max-Age=7776000; Path=/; HttpOnly; Secure; SameSite=Lax"
QC_ATTRS = "; Max-Age=600; Path=/; HttpOnly; Secure; SameSite=Lax"
DEV_ATTRS = "; Max-Age=34560000; Path=/; HttpOnly; Secure; SameSite=Lax"
CLEARED = "__Host-jm_session=; Max-Age=0; Path=/; HttpOnly; Secure; SameSite=Lax"
WRONG = "Wrong username or password"


@pytest.fixture()
def fake(monkeypatch):
    media_env(monkeypatch)
    return FakeJellyfin().install(monkeypatch)


@pytest.fixture()
def slept(monkeypatch):
    calls = []
    monkeypatch.setattr(guest_auth, "sleep", calls.append)
    return calls


@pytest.fixture()
def clock(monkeypatch):
    now = [5_000_000.0]
    monkeypatch.setattr(guest_auth, "clock", lambda: now[0])
    return now


@pytest.fixture()
def client(fake, slept):
    with TestClient(reload_app(), base_url=HTTPS) as c:
        c.cookies.set("__Host-jm_dev", DEV)
        yield c


def cookie_lines(r, name):
    return [h for h in r.headers.get_list("set-cookie") if h.startswith(name + "=")]


def password(c, user, pw, **kw):
    return c.post("/signin/password", data={"username": user, "password": pw, **kw}, follow_redirects=False)


def start_qc(c):
    return c.post("/signin/qc/start", follow_redirects=False)


# ---- the page and the device id ----

def test_signin_page_offers_quick_connect_and_the_password_form(fake, slept):
    with TestClient(reload_app(), base_url=HTTPS) as c:
        r = c.get("/signin")
    assert r.status_code == 200
    assert "Quick Connect" in r.text and 'name="password"' in r.text and 'action="/signin/password"' in r.text
    (dev,) = cookie_lines(r, "__Host-jm_dev")
    assert re.fullmatch(r"__Host-jm_dev=[0-9a-f]{32}" + re.escape(DEV_ATTRS), dev)


def test_signin_page_keeps_an_existing_device_id(client):
    assert not cookie_lines(client.get("/signin"), "__Host-jm_dev")


def test_signin_routes_are_404_on_the_private_front(monkeypatch, fake, slept):
    monkeypatch.delenv("JOEY_FRONT")
    with TestClient(reload_app(), base_url=HTTPS) as c:
        assert c.get("/signin").status_code == 404
        assert c.post("/signin/password", data={"username": "Sample Friend", "password": "right-pw-1"}).status_code == 404
    assert not fake.calls


# ---- Quick Connect ----

def test_qc_start_sets_the_secret_cookie_and_shows_the_code(client, fake):
    r = start_qc(client)
    assert r.status_code == 200
    (secret,) = fake.qc
    assert cookie_lines(r, "__Host-jm_qc") == [f"__Host-jm_qc={secret}{QC_ATTRS}"]
    assert "482 916" in r.text and "Quick Connect" in r.text
    assert secret not in r.text
    assert fake.qc[secret]["device"] == DEV
    assert [c[2]["DeviceId"] for c in fake.calls if c[1] == "/QuickConnect/Initiate"] == [DEV]


def test_qc_poll_waits_then_signs_in(client, fake):
    start_qc(client)
    (secret,) = fake.qc
    r = client.get("/signin/qc/poll", headers={"HX-Request": "true"})
    assert r.status_code == 200 and "HX-Redirect" not in r.headers and not cookie_lines(r, "__Host-jm_session")
    fake.authorize(secret, FRIEND_ID)
    r = client.get("/signin/qc/poll", headers={"HX-Request": "true"})
    (token,) = fake.tokens
    assert cookie_lines(r, "__Host-jm_session") == [f"__Host-jm_session={token}{SESSION_ATTRS}"]
    assert cookie_lines(r, "__Host-jm_qc") == ["__Host-jm_qc=; Max-Age=0; Path=/; HttpOnly; Secure; SameSite=Lax"]
    assert r.headers["HX-Redirect"] == guest.home_path()
    devices = {c[2].get("DeviceId") for c in fake.calls if c[1].startswith(("/QuickConnect", "/Users/Authenticate"))}
    assert devices == {DEV}   # the same DeviceId through the whole flow
    assert client.get(guest.home_path(), follow_redirects=False).status_code == 200


def test_qc_poll_returns_to_next(client, fake):
    assert 'value="/media/movies"' in client.get("/signin?next=%2Fmedia%2Fmovies").text
    r = client.post("/signin/qc/start", data={"next": "/media/movies"}, follow_redirects=False)
    poll = re.search(r'hx-get="([^"]+)"', r.text).group(1).replace("&amp;", "&")
    assert poll == "/signin/qc/poll?next=%2Fmedia%2Fmovies"
    (secret,) = fake.qc
    fake.authorize(secret, FRIEND_ID)
    assert client.get(poll, headers={"HX-Request": "true"}).headers["HX-Redirect"] == "/media/movies"


def test_qc_approved_by_an_admin_is_refused_and_the_token_revoked(client, fake):
    start_qc(client)
    (secret,) = fake.qc
    fake.authorize(secret, ADMIN_ID)
    r = client.get("/signin/qc/poll", headers={"HX-Request": "true"})
    assert not cookie_lines(r, "__Host-jm_session") and "HX-Redirect" not in r.headers
    assert "can't sign in here" in r.text
    assert fake.count("POST", "/Sessions/Logout") == 1 and not fake.tokens


def test_qc_poll_without_a_code_or_with_an_expired_one(client, fake):
    r = client.get("/signin/qc/poll", headers={"HX-Request": "true"})
    assert r.status_code == 200 and "Get a new code" in r.text
    start_qc(client)
    fake.qc.clear()   # Jellyfin forgot the request (expired)
    r = client.get("/signin/qc/poll", headers={"HX-Request": "true"})
    assert "expired" in r.text and cookie_lines(r, "__Host-jm_qc")[0].startswith("__Host-jm_qc=; Max-Age=0")


# ---- password fallback ----

def test_a_right_password_signs_in(client, fake):
    r = password(client, "Sample Friend", "right-pw-1", next="/media/tv")
    (token,) = fake.tokens
    assert (r.status_code, r.headers["location"]) == (303, "/media/tv")
    assert cookie_lines(r, "__Host-jm_session") == [f"__Host-jm_session={token}{SESSION_ATTRS}"]
    assert [c[2]["DeviceId"] for c in fake.calls if c[1] == "/Users/AuthenticateByName"] == [DEV]


def test_next_never_leaves_the_site(client, fake):
    r = password(client, "Sample Friend", "right-pw-1", next="https://evil.example/x")
    assert r.headers["location"] == guest.home_path()


def test_a_wrong_password_is_refused_slowly_without_a_cookie(client, fake, slept):
    r = password(client, "Sample Friend", "nope")
    assert r.status_code == 200 and WRONG in r.text
    assert not cookie_lines(r, "__Host-jm_session")
    assert slept == [guest_auth.WRONG_DELAY_S] and guest_auth.WRONG_DELAY_S == 1


def test_an_admins_right_password_is_refused_and_counts(client, fake, clock):
    """P1 (2026-10-19): the admin can never hold a guest session - the same words as a wrong password."""
    r = password(client, "Sample Admin", "admin-pw-3")
    assert WRONG in r.text and not cookie_lines(r, "__Host-jm_session")
    assert fake.count("POST", "/Sessions/Logout") == 1 and not fake.tokens
    for _ in range(guest_auth.FAIL_LIMIT - 1):
        password(client, "Sample Admin", "admin-pw-3")
    before = fake.count("POST", "/Users/AuthenticateByName")
    assert WRONG in password(client, "Sample Admin", "admin-pw-3").text
    assert fake.count("POST", "/Users/AuthenticateByName") == before   # counted: the 6th never reached Jellyfin


def test_the_sixth_failure_never_reaches_jellyfin(client, fake, clock):
    assert (guest_auth.FAIL_LIMIT, guest_auth.FAIL_WINDOW_S) == (5, 900)
    for _ in range(5):
        password(client, "Sample Friend", "nope")
    assert fake.count("POST", "/Users/AuthenticateByName") == 5
    r = password(client, "SAMPLE FRIEND", "right-pw-1")   # the key is the lowercased name
    assert WRONG in r.text and not cookie_lines(r, "__Host-jm_session")
    assert fake.count("POST", "/Users/AuthenticateByName") == 5
    assert cookie_lines(password(client, "Other Friend", "other-pw-2"), "__Host-jm_session")   # unaffected
    clock[0] += guest_auth.FAIL_WINDOW_S + 1
    assert cookie_lines(password(client, "Sample Friend", "right-pw-1"), "__Host-jm_session")


def test_jellyfin_down_during_password_is_its_own_words_and_not_counted(client, fake):
    fake.byname_raises = requests.Timeout
    r = password(client, "Sample Friend", "right-pw-1")
    assert "Couldn't reach Jellyfin" in html.unescape(r.text) and WRONG not in r.text
    fake.byname_raises = None
    for _ in range(guest_auth.FAIL_LIMIT - 1):
        password(client, "Sample Friend", "nope")
    assert cookie_lines(password(client, "Sample Friend", "right-pw-1"), "__Host-jm_session")


# ---- sign-out ----

def test_signout_revokes_the_token_and_clears_the_cookie(client, fake):
    password(client, "Sample Friend", "right-pw-1")
    (token,) = fake.tokens
    assert client.get(guest.home_path(), follow_redirects=False).status_code == 200
    r = client.post("/signout", follow_redirects=False)
    logouts = [c for c in fake.calls if c[1] == "/Sessions/Logout"]
    assert [c[2].get("Token") for c in logouts] == [token]
    assert (r.status_code, r.headers["location"]) == (303, "/signin")
    assert CLEARED in r.headers.get_list("set-cookie")
    me_before = fake.count("GET", "/Users/Me")
    client.cookies.set("__Host-jm_session", token)
    assert client.get(guest.home_path(), follow_redirects=False).status_code == 303   # the verdict was evicted
    assert fake.count("GET", "/Users/Me") == me_before + 1


def test_signout_without_a_session_still_clears(client, fake):
    r = client.post("/signout", follow_redirects=False)
    assert r.status_code == 303 and CLEARED in r.headers.get_list("set-cookie")
    assert not fake.count("POST", "/Sessions/Logout")


# ---- CSRF, cookies over http, logs ----

@pytest.mark.parametrize("path", ["/signin/qc/start", "/signin/password", "/signout"])
def test_a_cross_origin_post_is_refused(client, fake, path):
    assert client.post(path, headers=EVIL, data={"username": "x", "password": "y"}).status_code == 403
    assert not [c for c in fake.calls if c[0] == "POST"]


def test_plain_cookie_names_only_with_joey_cookie_secure_0(monkeypatch, fake, slept):
    monkeypatch.setenv("JOEY_COOKIE_SECURE", "0")
    with TestClient(reload_app()) as c:   # http preview
        r = password(c, "Sample Friend", "right-pw-1")
        (token,) = fake.tokens
        assert cookie_lines(r, "jm_session") == [f"jm_session={token}; Max-Age=7776000; Path=/; HttpOnly; SameSite=Lax"]
        assert c.get(guest.home_path(), follow_redirects=False).status_code == 200


def test_logs_never_carry_a_name_password_token_or_secret(client, fake, caplog):
    caplog.set_level(logging.DEBUG)
    password(client, "Sample Friend", "nope")
    password(client, "Sample Friend", "right-pw-1")
    start_qc(client)
    (secret,) = fake.qc
    fake.authorize(secret, OTHER_ID)
    client.get("/signin/qc/poll", headers={"HX-Request": "true"})
    client.post("/signout")
    text = caplog.text
    assert fake.calls and "guest:" in text
    for word in ("Sample Friend", "Other Friend", "right-pw-1", "nope", secret, *fake.tokens,
                 *(c[2].get("Token") for c in fake.calls if c[2].get("Token"))):
        assert word not in text, word
    assert f"jf:{FRIEND_ID}" in text


# ---- step 4: the TV sign-in is this web page (Q33) ----

def test_signin_renders_in_tv_mode_under_the_tv_user_agent(client):   # WP-B3: TV mode (was an xfail in WP-B2)
    r = client.get("/signin", headers={"User-Agent": "Mozilla/5.0 JoeyTV/1.0.0 (2026102101)"})
    assert 'class="tv' in r.text
