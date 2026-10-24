"""JY-190 (L4, TV UI review 2026-10-23): sign-out deletes the friend's Jellyfin device.

/Sessions/Logout leaves the device row behind, so a friend capped at MaxActiveSessions 2 who signs out and back in
holds two devices and Quick Connect's Authorize answers 403. /signout now deletes the device of THIS browser
(`__Host-jm_dev`) with the admin key - only when Jellyfin says that device was last used by the friend whose session is
signing out, and only for a friend (`jf:<id>`), never a household user. A failed or unreachable device call never
fails the sign-out, and its log line carries no name, token, key or device id. Jellyfin = tests/hub/fake_jellyfin.py."""
import logging

import pytest
import requests
from fastapi.testclient import TestClient

from tests.hub.fake_jellyfin import ALIAS_ID, DEV, FRIEND_ID, HTTPS, KEY, OTHER_ID, FakeJellyfin, media_env, reload_app

CLEARED = "__Host-jm_session=; Max-Age=0; Path=/; HttpOnly; Secure; SameSite=Lax"
HOUSE_DEV = "ab" * 16


@pytest.fixture()
def fake(monkeypatch):
    media_env(monkeypatch)
    return FakeJellyfin().install(monkeypatch)


@pytest.fixture()
def client(fake, monkeypatch):
    from hub import guest_auth
    monkeypatch.setattr(guest_auth, "sleep", lambda s: None)
    with TestClient(reload_app(), base_url=HTTPS) as c:
        c.cookies.set("__Host-jm_dev", DEV)
        yield c


def sign_in(c, user="Sample Friend", pw="right-pw-1"):
    r = c.post("/signin/password", data={"username": user, "password": pw}, follow_redirects=False)
    assert r.status_code == 303, r.text[:200]


def sign_out(c):
    r = c.post("/signout", follow_redirects=False)
    assert (r.status_code, r.headers["location"]) == (303, "/signin")
    assert CLEARED in r.headers.get_list("set-cookie")
    return r


def deletes(fake):
    return [c for c in fake.calls if c[0] == "DELETE" and c[1] == "/Devices"]


def test_signout_deletes_the_friends_own_device_after_the_logout(client, fake):
    sign_in(client)
    assert DEV in fake.devices
    sign_out(client)
    (call,) = deletes(fake)
    assert call[2] == {"Token": KEY} and call[4].get("id") == DEV        # the admin key, this browser's device
    order = [c[1] for c in fake.calls if c[1] in ("/Sessions/Logout", "/Devices")]
    assert order == ["/Sessions/Logout", "/Devices"]                       # the token is revoked first
    assert DEV not in fake.devices


def test_a_household_users_signout_never_deletes_a_device(client, fake):
    sign_in(client, "Sample Alias", "alias-pw-4")                         # the alias user = household `you`
    assert DEV in fake.devices
    sign_out(client)
    assert deletes(fake) == [] and DEV in fake.devices


def test_a_device_last_used_by_someone_else_is_never_deleted(client, fake):
    """A friend whose device cookie names a household device (or another friend's) signs out: nothing is deleted."""
    sign_in(client)
    fake.add_device(HOUSE_DEV, ALIAS_ID)
    fake.add_device("cd" * 16, OTHER_ID)
    for dev in (HOUSE_DEV, "cd" * 16):
        client.cookies.set("__Host-jm_dev", dev)
        sign_out(client)
        sign_in(client)
    assert deletes(fake) == []
    assert HOUSE_DEV in fake.devices and "cd" * 16 in fake.devices


def test_a_device_of_another_app_is_never_deleted(client, fake):
    sign_in(client)
    fake.devices[DEV]["AppName"] = "Jellyfin Android TV"
    sign_out(client)
    assert deletes(fake) == []


def test_no_session_no_device_call(client, fake):
    sign_out(client)
    assert not [c for c in fake.calls if c[1].startswith("/Devices")]


def test_a_failed_delete_still_signs_out_and_logs_no_secret(client, fake, caplog):
    caplog.set_level(logging.DEBUG)
    sign_in(client)
    (token,) = fake.tokens
    fake.device_delete_status = 500
    sign_out(client)
    assert len(deletes(fake)) == 1
    text = caplog.text
    assert "guest: device not removed" in text
    for word in ("Sample Friend", "right-pw-1", token, KEY, DEV):
        assert word not in text, word


def test_jellyfin_unreachable_for_the_device_check_still_signs_out(client, fake, caplog):
    caplog.set_level(logging.DEBUG)
    sign_in(client)
    fake.devices_raises = requests.ConnectTimeout
    sign_out(client)
    assert deletes(fake) == []
    assert "guest: device not removed" in caplog.text and DEV not in caplog.text and KEY not in caplog.text


def test_the_device_calls_run_after_the_response_is_sent(fake, monkeypatch):
    """Review should-fix (2026-10-25): the device lookup and delete run as a BackgroundTask after the 303, so a hung
    Jellyfin never holds the sign-out up. The ASGI send is wrapped: the final body goes out before the lookup starts."""
    from hub import guest_auth
    monkeypatch.setattr(guest_auth, "sleep", lambda s: None)
    events = []
    app = reload_app()

    async def wrapped(scope, receive, send):
        async def rec(msg):
            if (scope.get("path") == "/signout" and msg["type"] == "http.response.body"
                    and not msg.get("more_body")):
                events.append("response sent")
            await send(msg)
        await app(scope, receive, rec)

    real_get = fake.get

    def get(url, **kw):
        if url.endswith("/Devices/Info"):
            events.append("device lookup")
        return real_get(url, **kw)
    monkeypatch.setattr(requests, "get", get)
    with TestClient(wrapped, base_url=HTTPS) as c:
        c.cookies.set("__Host-jm_dev", DEV)
        sign_in(c)
        sign_out(c)
    assert events == ["response sent", "device lookup"]
    assert len(deletes(fake)) == 1 and DEV not in fake.devices


def test_the_signout_identity_read_has_a_short_timeout(client, fake, monkeypatch):
    from hub import guest_auth
    sign_in(client)
    guest_auth.clear()                                                    # no cached verdict: /Users/Me is asked
    seen = []
    real_get = fake.get

    def get(url, **kw):
        if url.endswith("/Users/Me"):
            seen.append(kw.get("timeout"))
        return real_get(url, **kw)
    monkeypatch.setattr(requests, "get", get)
    sign_out(client)
    assert seen == [guest_auth.SIGNOUT_WHO_TIMEOUT] and guest_auth.SIGNOUT_WHO_TIMEOUT <= 3
    assert len(deletes(fake)) == 1
