"""Joey TV WP-B2 step 2 (2026-10-21): the guest session on the media front - a Jellyfin token in a cookie, re-validated
against Jellyfin `/Users/Me` (verdict cached Q27 = 60 s), resolved to the ONE owner mapping (hub.identity.
owner_for_jellyfin: the alias user is `you`, everyone else `jf:<id>`), and refused when Jellyfin says the token is dead,
the user is disabled, an administrator, or has remote access off (P1, 2026-10-19: joey-media reaches Jellyfin from a
LAN bridge, so Jellyfin never applies the remote-access flag itself). Jellyfin slow or down = a 503 page, the cookie
kept, never cached as invalid. Jellyfin is the fake in tests/hub/fake_jellyfin.py (real 12.2 shapes)."""
import logging

import pytest
import requests
from fastapi.testclient import TestClient

from hub import guest, guest_auth
from hub.identity import Identity
from tests.hub.fake_jellyfin import (ADMIN_ID, ALIAS_ID, DEV, DISABLED_ID, FRIEND_ID, HTTPS, REMOTE_OFF_ID,
                                     FakeJellyfin, media_env, reload_app, session_cookie)

CLEARED = "__Host-jm_session=; Max-Age=0; Path=/; HttpOnly; Secure; SameSite=Lax"


@pytest.fixture()
def fake(monkeypatch):
    media_env(monkeypatch)
    return FakeJellyfin().install(monkeypatch)


@pytest.fixture()
def clock(monkeypatch):
    now = [1_000_000.0]
    monkeypatch.setattr(guest_auth, "clock", lambda: now[0])
    return now


@pytest.fixture()
def client(fake):
    with TestClient(reload_app(), base_url=HTTPS) as c:
        yield c


def home():
    return guest.home_path()


def get(c, path, token=None, **kw):
    if token is not None:
        c.cookies.clear()
        for k, v in session_cookie(token).items():
            c.cookies.set(k, v)
    return c.get(path, follow_redirects=False, **kw)


def set_cookies(r) -> list[str]:
    return r.headers.get_list("set-cookie")


# ---- the identity ----

def test_valid_token_gives_the_friends_identity(fake):
    token = fake.token_for(FRIEND_ID)
    who = guest_auth.validate(token, DEV)
    assert who == Identity(owner=f"jf:{FRIEND_ID}", name="Sample Friend", jf_user_id=FRIEND_ID, jf_token=token)
    assert token not in repr(who)


def test_the_alias_user_is_you_with_its_own_jellyfin_id(fake):
    """Q16 / DECISIONS #21: the shared outside user resolves to `you` through identity.owner_for_jellyfin - the same
    jf_user_id, no second mapping."""
    who = guest_auth.validate(fake.token_for(ALIAS_ID), DEV)
    assert (who.owner, who.jf_user_id) == ("you", ALIAS_ID)


def test_without_aliases_the_same_user_is_a_friend(monkeypatch):
    media_env(monkeypatch, aliases=None)
    fake = FakeJellyfin().install(monkeypatch)
    who = guest_auth.validate(fake.token_for(ALIAS_ID), DEV)
    assert who.owner == f"jf:{ALIAS_ID}"   # no silent `you`


def test_a_verdict_is_kept_for_the_ttl(fake, clock):
    token = fake.token_for(FRIEND_ID)
    assert guest_auth.VERDICT_TTL == 60   # Q27
    guest_auth.validate(token, DEV)
    clock[0] += guest_auth.VERDICT_TTL - 1
    guest_auth.validate(token, DEV)
    assert fake.count("GET", "/Users/Me") == 1
    clock[0] += 2   # TTL + 1 s after the first check
    guest_auth.validate(token, DEV)
    assert fake.count("GET", "/Users/Me") == 2


def test_the_validation_header_is_the_12_2_form(fake):
    token = fake.token_for(FRIEND_ID)
    guest_auth.validate(token, DEV)
    auth = [c[2] for c in fake.calls if c[1] == "/Users/Me"][0]
    assert auth == {"Client": "Joey Media", "Device": "Joey Media web", "DeviceId": DEV,
                    "Version": guest_auth.VERSION, "Token": token}
    guest_auth.clear()
    guest_auth.validate(token, DEV, tv=True)
    assert [c[2] for c in fake.calls if c[1] == "/Users/Me"][-1]["Device"] == "Joey Media TV"


# ---- through the gate ----

def test_a_signed_in_friend_gets_the_guest_home(client, fake, caplog):
    caplog.set_level(logging.INFO, logger="hub")
    r = get(client, home(), fake.token_for(FRIEND_ID))
    assert r.status_code == 200
    assert f"GET {home()} owner=jf:{FRIEND_ID} -> 200" in caplog.text
    assert "Sample Friend" not in caplog.text


@pytest.mark.parametrize("case", ["unknown token", "403", "disabled"])
def test_a_dead_session_goes_to_signin_and_the_cookie_is_cleared(client, fake, case):
    token = fake.token_for(DISABLED_ID if case == "disabled" else FRIEND_ID)
    if case == "unknown token":
        fake.tokens.clear()
    if case == "403":
        fake.me_status = 403
    r = get(client, home(), token)
    assert (r.status_code, r.headers["location"]) == (303, "/signin")
    assert CLEARED in set_cookies(r)


@pytest.mark.parametrize("uid,reason", [(ADMIN_ID, "admin"), (REMOTE_OFF_ID, "remote-off")])
def test_an_admin_or_remote_off_user_never_holds_a_guest_session(client, fake, caplog, uid, reason):
    """P1 (2026-10-19, B. accepted): the hub enforces what Jellyfin cannot see from the LAN bridge."""
    caplog.set_level(logging.INFO)
    r = get(client, home(), fake.token_for(uid))
    assert (r.status_code, r.headers["location"]) == (303, "/signin")
    assert CLEARED in set_cookies(r)
    assert f"guest: refused {reason} jf:{uid}" in caplog.text
    assert fake.users[uid]["Name"] not in caplog.text


def test_a_disabled_user_is_signed_out_after_the_ttl(client, fake, clock):
    token = fake.token_for(FRIEND_ID)
    assert get(client, home(), token).status_code == 200
    fake.users[FRIEND_ID]["policy"]["IsDisabled"] = True
    assert get(client, home(), token).status_code == 200   # inside the verdict TTL
    clock[0] += guest_auth.VERDICT_TTL + 1
    r = get(client, home(), token)
    assert r.status_code == 303 and CLEARED in set_cookies(r)


@pytest.mark.parametrize("failure", ["timeout", "503"])
def test_jellyfin_unreachable_is_a_503_and_the_cookie_is_kept(client, fake, failure):
    token = fake.token_for(FRIEND_ID)
    if failure == "timeout":
        fake.me_raises = requests.Timeout
    else:
        fake.me_status = 503
    r = get(client, home(), token)
    assert r.status_code == 503
    assert not [h for h in set_cookies(r) if "jm_session" in h]
    assert "Sample Friend" not in r.text and "Recently added" not in r.text and "<nav" not in r.text
    fake.me_raises, fake.me_status = None, None
    assert get(client, home(), token).status_code == 200   # nothing was cached
    assert fake.count("GET", "/Users/Me") == 2


def test_the_household_lookup_failing_is_unreachable_not_invalid(client, fake):
    fake.users_list_fails = True
    r = get(client, home(), fake.token_for(FRIEND_ID))
    assert r.status_code == 503 and not [h for h in set_cookies(r) if "jm_session" in h]


def test_a_slow_jellyfin_keeps_a_recent_valid_verdict(client, fake, clock):
    """Under NAS swap pressure /Users/Me can take more than 10 s (W3, 2026-10-21): a verdict that WAS valid is served
    for STALE_GRACE past its TTL while Jellyfin does not answer - never for a token Jellyfin refused."""
    token = fake.token_for(FRIEND_ID)
    assert get(client, home(), token).status_code == 200
    fake.me_raises = requests.Timeout
    clock[0] += guest_auth.VERDICT_TTL + 1
    assert get(client, home(), token).status_code == 200
    clock[0] += guest_auth.STALE_GRACE
    assert get(client, home(), token).status_code == 503


def test_htmx_without_a_session_is_told_to_go_to_signin(client, fake):
    r = client.get(home(), headers={"HX-Request": "true"}, follow_redirects=False)
    assert r.headers.get("HX-Redirect") == "/signin" and r.status_code == 200
    r = get(client, home(), "0" * 32, headers={"HX-Request": "true"})
    assert r.headers.get("HX-Redirect") == "/signin" and CLEARED in set_cookies(r)


def test_public_paths_answer_without_a_session_and_never_ask_jellyfin(client, fake):
    for path in ("/static/control-surface.css", "/healthz", "/signin"):
        assert get(client, path).status_code == 200, path
    token = fake.token_for(FRIEND_ID)
    for path in ("/static/control-surface.css", "/healthz"):
        assert get(client, path, token).status_code == 200, path
    assert fake.count("GET", "/Users/Me") == 0


def test_a_malformed_cookie_is_cleared_without_calling_jellyfin(client, fake):
    r = get(client, home(), "not-a-token_0000")
    assert r.status_code == 303 and CLEARED in set_cookies(r)
    assert fake.count("GET", "/Users/Me") == 0


def test_a_forged_access_header_with_a_friend_session_changes_nothing(client, fake, caplog):
    caplog.set_level(logging.INFO, logger="hub")
    r = get(client, home(), fake.token_for(FRIEND_ID),
            headers={"Cf-Access-Authenticated-User-Email": "you@example.com"})
    assert r.status_code == 200 and f"owner=jf:{FRIEND_ID}" in caplog.text
