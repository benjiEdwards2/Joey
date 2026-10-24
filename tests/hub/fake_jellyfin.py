"""A fake Jellyfin 12.2 for the guest sign-in tests (Joey TV WP-B2, 2026-10-21).

Every response body is built from the REAL, redacted response shapes captured by the W3 probe on 2026-10-21
(tests/hub/fixtures/jellyfin_qc_*.json): the fake swaps in its own invented users, secrets and tokens, so a drift in
Jellyfin's shapes shows up here instead of on the TV. Names are invented ("Sample Friend"); no real id, name or token.

Installed by monkeypatching `requests.get / post / delete` (hub.upstream.session is routed through `requests` by
tests/hub/conftest.py). Auth is the 12.2 form: `Authorization: MediaBrowser Client="…", Device="…", DeviceId="…",
Version="…"[, Token="…"]` (a bare X-Emby-Token is refused, as the real server does); the admin key arrives as
`MediaBrowser Token=<key>`.
"""
from __future__ import annotations

import copy
import json
import re
import secrets
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import requests

FIXTURES = Path(__file__).resolve().parent / "fixtures"
URL = "http://jellyfin.test:8096"
KEY = "admin-key-SECRET-0001"
PUBLIC_URL = "https://jellyfin.example.test:8443"   # JELLYFIN_PUBLIC_URL in tests: a port, like production's :8443

FRIEND_ID = "f00d" * 8
OTHER_ID = "beef" * 8
ADMIN_ID = "a" * 32
ALIAS_ID = "a1" * 16
REMOTE_OFF_ID = "0ff0" * 8
DISABLED_ID = "d15a" * 8


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"jellyfin_qc_{name}.json").read_text(encoding="utf-8"))


def parse_auth(value: str | None) -> dict:
    """`MediaBrowser Client="x", Token="y"` -> {"Client": "x", "Token": "y"} (quoted or bare values)."""
    if not value or not value.startswith("MediaBrowser "):
        return {}
    return {k: v for k, v in re.findall(r'(\w+)="?([^",]*)"?', value[len("MediaBrowser "):])}


class Resp:
    def __init__(self, body=None, status=200):
        self.status_code = status
        self._body = body

    def json(self):
        if self._body is None:
            raise ValueError("no body")
        return self._body


class FakeJellyfin:
    def __init__(self):
        self.users = {
            FRIEND_ID: {"Name": "Sample Friend", "pw": "right-pw-1", "policy": {}},
            OTHER_ID: {"Name": "Other Friend", "pw": "other-pw-2", "policy": {}},
            ADMIN_ID: {"Name": "Sample Admin", "pw": "admin-pw-3", "policy": {"IsAdministrator": True}},
            ALIAS_ID: {"Name": "Sample Alias", "pw": "alias-pw-4", "policy": {}},
            REMOTE_OFF_ID: {"Name": "Lounge Only", "pw": "lounge-pw-5", "policy": {"EnableRemoteAccess": False}},
            DISABLED_ID: {"Name": "Gone Friend", "pw": "gone-pw-6", "policy": {"IsDisabled": True}},
        }
        self.tokens: dict[str, str] = {}      # token -> user id
        self.qc: dict[str, dict] = {}         # secret -> {"code", "device", "uid"}
        self.calls: list[tuple] = []          # (method, path, auth dict, json, params)
        self.me_status: int | None = None     # force /Users/Me to answer this status
        self.me_raises: type[Exception] | None = None
        self.users_list_fails = False
        self.byname_raises: type[Exception] | None = None
        self.items: dict[str, dict] = {}      # jf id -> a minimal item body (GET /Users/{uid}/Items/{id})
        self.played: dict[str, set] = {}      # user id -> the item ids that user has watched
        self.resume: dict[str, list] = {}     # user id -> GET /UserItems/Resume Items (WP-B3 guest Overview)
        self.history: dict[str, list] = {}    # user id -> GET /Items?IsPlayed=true&SortBy=DatePlayed Items
        self.shelf_raises: type[Exception] | None = None   # the two shelf reads raise this (Jellyfin down)
        # JY-190 (L4): Jellyfin's device list. A sign-in adds its DeviceId (LastUserId in the dashed GUID form the API
        # returns); /Sessions/Logout leaves it behind, as 12.2 does; only the admin key may read or delete one.
        self.devices: dict[str, dict] = {}
        self.devices_raises: type[Exception] | None = None   # GET /Devices/Info raises this
        self.device_delete_status = 204                    # DELETE /Devices answers this status

    # ---- test helpers ----
    def token_for(self, uid: str) -> str:
        token = secrets.token_hex(16)
        self.tokens[token] = uid
        return token

    def authorize(self, secret: str, uid: str) -> None:
        """The phone approving the code (the session is created at Authorize time, as on 12.2)."""
        self.qc[secret]["uid"] = uid

    def paths(self, method: str | None = None) -> list[str]:
        return [c[1] for c in self.calls if method is None or c[0] == method]

    def count(self, method: str, path: str) -> int:
        return sum(1 for c in self.calls if c[0] == method and c[1] == path)

    def install(self, monkeypatch) -> "FakeJellyfin":
        monkeypatch.setattr(requests, "get", self.get)
        monkeypatch.setattr(requests, "post", self.post)
        monkeypatch.setattr(requests, "delete", self.delete)
        return self

    # ---- shapes from the fixtures ----
    def _user_body(self, uid: str) -> dict:
        u = self.users[uid]
        body = copy.deepcopy(fixture("users_me")["body"])
        body.update(Name=u["Name"], Id=uid, ServerId="srv-fake")
        body["Policy"] = {**body["Policy"], "InvalidLoginAttemptCount": 0, **u["policy"]}
        return body

    def _auth_body(self, uid: str, token: str, auth: dict) -> dict:
        body = copy.deepcopy(fixture("authenticate")["body"])
        body["User"] = self._user_body(uid)
        body["SessionInfo"].update(UserId=uid, UserName=self.users[uid]["Name"], DeviceId=auth.get("DeviceId"),
                                   Client=auth.get("Client"), DeviceName=auth.get("Device"))
        body.update(AccessToken=token, ServerId="srv-fake")
        self.add_device(auth.get("DeviceId"), uid, auth.get("Client"))
        return body

    def add_device(self, device_id: str, uid: str, app: str = "Joey Media") -> None:
        dashed = "-".join((uid[:8], uid[8:12], uid[12:16], uid[16:20], uid[20:]))
        self.devices[device_id] = {"Id": device_id, "Name": "Joey Media TV", "AppName": app, "AppVersion": "1.0.0",
                                   "LastUserName": self.users[uid]["Name"], "LastUserId": dashed,
                                   "DateLastActivity": "2026-10-23T09:00:00.0000000Z"}

    def _qc_body(self, name: str, secret: str) -> dict:
        body = copy.deepcopy(fixture(name)["body"])
        q = self.qc[secret]
        body.update(Secret=secret, Code=q["code"], DeviceId=q["device"], Authenticated=q["uid"] is not None)
        return body

    # ---- the HTTP surface ----
    def _record(self, method, url, headers, json_body=None, params=None):
        if not url.startswith(URL):
            raise requests.ConnectionError("no network in tests")   # Seerr / TMDB / OMDb: unreachable
        assert "X-Emby-Token" not in (headers or {}) and "X-Emby-Authorization" not in (headers or {})
        parts = urlsplit(url)
        query = {k: v[-1] for k, v in parse_qs(parts.query).items()}
        auth = parse_auth((headers or {}).get("Authorization"))
        self.calls.append((method, parts.path, auth, json_body, {**query, **(params or {})}))
        return parts.path, auth, {**query, **(params or {})}

    def _client_ok(self, auth: dict) -> bool:
        return all(auth.get(k) for k in ("Client", "Device", "DeviceId", "Version"))

    def get(self, url, params=None, headers=None, timeout=None, **kw):
        assert timeout, "every Jellyfin call carries a timeout"
        path, auth, query = self._record("GET", url, headers, params=params)
        if path == "/Users":
            assert auth == {"Token": KEY}, "the household read uses the admin key"
            if self.users_list_fails:
                return Resp({}, 500)
            return Resp([{"Id": uid, "Name": u["Name"], "Policy": {"IsAdministrator": bool(
                u["policy"].get("IsAdministrator"))}} for uid, u in self.users.items()])
        if path == "/Users/Me":
            if self.me_raises:
                raise self.me_raises(f"Read timed out: {url}")
            if self.me_status:
                return Resp({}, self.me_status)
            uid = self.tokens.get(auth.get("Token") or "")
            if uid is None or not self._client_ok(auth):
                return Resp(None, 401)
            return Resp(self._user_body(uid))
        if path == "/QuickConnect/Connect":
            if query.get("secret") not in self.qc:
                return Resp(None, 404)
            name = "connect_ok" if self.qc[query["secret"]]["uid"] else "connect_pending"
            return Resp(self._qc_body(name, query["secret"]))
        if path in ("/UserItems/Resume", "/Items") and (auth.get("Token") or "") in self.tokens:
            if self.shelf_raises:
                raise self.shelf_raises(f"Read timed out: {url}")
            uid = self.tokens[auth["Token"]]
            if str(query.get("userId")) != uid or not self._client_ok(auth):
                return Resp(None, 401)
            rows = (self.resume if path == "/UserItems/Resume" else self.history).get(uid, [])
            return Resp({"Items": copy.deepcopy(rows), "TotalRecordCount": len(rows), "StartIndex": 0})
        if path == "/Devices/Info":
            if auth != {"Token": KEY}:
                return Resp(None, 401)
            if self.devices_raises:
                raise self.devices_raises(f"Read timed out: {url}")
            dev = self.devices.get(str(query.get("id")))
            return Resp(copy.deepcopy(dev)) if dev else Resp(None, 404)
        m = re.fullmatch(r"/Users/([0-9a-f]{32})/Items/([A-Za-z0-9-]+)", path)
        if m and m.group(2) in self.items:
            played = m.group(2) in self.played.get(m.group(1), set())
            return Resp({**self.items[m.group(2)], "UserData": {"Played": played, "PlaybackPositionTicks": 0}})
        return Resp({}, 404)

    def post(self, url, params=None, json=None, data=None, headers=None, timeout=None, **kw):
        assert timeout, "every Jellyfin call carries a timeout"
        path, auth, query = self._record("POST", url, headers, json_body=json, params=params)
        if path == "/QuickConnect/Initiate":
            if not self._client_ok(auth):
                return Resp(None, 400)
            secret = secrets.token_hex(32)
            self.qc[secret] = {"code": "482916", "device": auth["DeviceId"], "uid": None}
            return Resp(self._qc_body("initiate", secret))
        if path == "/Users/AuthenticateWithQuickConnect":
            q = self.qc.get((json or {}).get("Secret"))
            if not q or not q["uid"] or not self._client_ok(auth):
                return Resp(None, 401)
            token = self.token_for(q["uid"])
            return Resp(self._auth_body(q["uid"], token, auth))
        if path == "/Users/AuthenticateByName":
            if self.byname_raises:
                raise self.byname_raises(f"Read timed out: {url}")
            body = json or {}
            uid = next((i for i, u in self.users.items() if u["Name"] == body.get("Username")), None)
            if uid is None or self.users[uid]["pw"] != body.get("Pw") or not self._client_ok(auth):
                return Resp(None, 401)
            token = self.token_for(uid)
            return Resp(self._auth_body(uid, token, auth))
        if path == "/Sessions/Logout":
            self.tokens.pop(auth.get("Token") or "", None)
            return Resp(fixture("logout")["body"], fixture("logout")["http_status"])
        if path.startswith(("/UserPlayedItems/", "/UserItems/")):
            return Resp({}, 200)
        return Resp({}, 404)

    def delete(self, url, params=None, headers=None, timeout=None, **kw):
        assert timeout
        path, auth, query = self._record("DELETE", url, headers, params=params)
        if path == "/Devices":
            if auth != {"Token": KEY}:
                return Resp(None, 401)
            if self.device_delete_status < 300:
                self.devices.pop(str(query.get("id")), None)
            return Resp(None, self.device_delete_status)
        return Resp({}, 200)


# ---- the media-front app the guest tests share ----

REPO_ROOT = Path(__file__).resolve().parents[2]
DEV = "de" * 16                     # a __Host-jm_dev value (32 hex)
HTTPS = "https://testserver"       # __Host- cookies are Secure: the test client must speak https


def media_env(monkeypatch, aliases: str | None = "Sample Alias") -> None:
    monkeypatch.setenv("AREAS_PATH", str(REPO_ROOT / "config" / "areas.yaml"))
    monkeypatch.setenv("JOEY_FRONT", "media")
    monkeypatch.setenv("JELLYFIN_URL", URL)
    monkeypatch.setenv("JELLYFIN_API_KEY", KEY)
    monkeypatch.setenv("JELLYFIN_USER", "Sample Admin")
    monkeypatch.setenv("JELLYFIN_PUBLIC_URL", PUBLIC_URL)
    monkeypatch.delenv("JELLYFIN_USER_HER", raising=False)
    monkeypatch.delenv("JOEY_COOKIE_SECURE", raising=False)
    monkeypatch.delenv("OWNER_EMAIL_YOU", raising=False)
    if aliases is None:
        monkeypatch.delenv("JELLYFIN_USER_ALIASES", raising=False)
    else:
        monkeypatch.setenv("JELLYFIN_USER_ALIASES", aliases)


def reload_app():
    import importlib

    import hub.main
    importlib.reload(hub.main)
    return hub.main.app


def session_cookie(token: str, secure: bool = True) -> dict:
    prefix = "__Host-" if secure else ""
    return {f"{prefix}jm_session": token, f"{prefix}jm_dev": DEV}
