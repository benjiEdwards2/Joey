"""Server → Downloads "Quiet (5 Mbps) · Full speed" (P4, 2026-10-22): the qBittorrent download cap toggle against a faked
qBittorrent (`requests.get` / `requests.post` monkeypatched; the suite's conftest routes `upstream.session` through them, so
nothing hits the network). The password and the URL must never reach a page, a redirect or a log. Plus the connector's new
`dl_limit_bps` / `dl_limit_text` snapshot fields, pinned off the fixture."""
import copy
import importlib
import json
import logging
import re
from pathlib import Path

import jsonschema
import pytest
import requests
from fastapi.testclient import TestClient
from requests.cookies import RequestsCookieJar

from hub import server_quiet
from hub.store import Snapshot
from tests.hub.helpers import write_envelope

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / "config" / "sample_snapshots"
URL, USER, PASSWORD = "http://qbit.secret-host.invalid:8080", "joeywriter", "QBITSECRETpass"
EVIL = {"origin": "https://evil.example"}


def main_of(html):
    return html.split("<main", 1)[1]


def txt(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html))


def row(html):
    """The quiet row, or '' when the page has none."""
    m = re.search(r'<div class="quietrow" id="downloads">(.*?)</div>', html, re.S)
    return m.group(1) if m else ""


class Resp:
    def __init__(self, status=200, body=None, cookies=None):
        self.status_code, self._body = status, body
        self.cookies = RequestsCookieJar()
        for name, value in (cookies or {}).items():
            self.cookies.set(name, value)

    def json(self):
        return self._body


class FakeQbit:
    """qBittorrent 5.x as far as P4 touches it: login 204 + SID cookie, setDownloadLimit 200, transfer/info reading the
    cap back the way qBittorrent stores it (KiB/s, so 625000 comes back as 624640)."""

    def __init__(self):
        self.limit, self.calls = 0, []
        self.login = Resp(204, None, {"SID": "sid123"})
        self.set_status, self.info_status, self.readback = 200, 200, None

    def post(self, url, **kw):
        self.calls.append({"method": "POST", "url": url, **kw})
        if isinstance(self.login, Exception):
            raise self.login
        if url.endswith("/api/v2/auth/login"):
            return self.login
        if url.endswith("/api/v2/transfer/setDownloadLimit"):
            if self.set_status == 200:
                self.limit = int(kw["data"]["limit"]) // 1024 * 1024
            return Resp(self.set_status)
        raise AssertionError(url)

    def get(self, url, **kw):
        self.calls.append({"method": "GET", "url": url, **kw})
        if url.endswith("/api/v2/transfer/info"):
            limit = self.limit if self.readback is None else self.readback
            return Resp(self.info_status, {"dl_info_speed": 0, "dl_rate_limit": limit})
        raise AssertionError(url)


@pytest.fixture(autouse=True)
def _fresh():
    server_quiet.clear_cache()
    yield
    server_quiet.clear_cache()


@pytest.fixture()
def qbit(monkeypatch):
    fake = FakeQbit()
    monkeypatch.setattr(requests, "post", fake.post)
    monkeypatch.setattr(requests, "get", fake.get)
    return fake


@pytest.fixture()
def creds(monkeypatch):
    monkeypatch.setenv("QBIT_URL", URL + "/")
    monkeypatch.setenv("QBIT_USER", USER)
    monkeypatch.setenv("QBIT_PASS", PASSWORD)
    for name in ("QUIET_MBPS", "NAS_SLEEP_WINDOW"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture()
def env(tmp_path, monkeypatch, qbit):
    monkeypatch.delenv("AREAS_PATH", raising=False)
    snaps = tmp_path / "snaps"
    snaps.mkdir()
    monkeypatch.setenv("SNAPSHOT_DIR", str(snaps))
    for name in ("STACKCTL_URL", "STACKCTL_TOKEN", "WUD_URL", "WUD_USER", "WUD_PASS", "QUIET_MBPS", "NAS_SLEEP_WINDOW",
                 "QBIT_URL", "QBIT_USER", "QBIT_PASS"):
        monkeypatch.delenv(name, raising=False)

    def build(qbit_env=True, limit=0, drop_field=False, drop_snapshot=False):
        for name, value in (("QBIT_URL", URL + "/"), ("QBIT_USER", USER), ("QBIT_PASS", PASSWORD)):
            if qbit_env:
                monkeypatch.setenv(name, value)
            else:
                monkeypatch.delenv(name, raising=False)
        for p in SAMPLES.glob("*.json"):
            if p.stem.startswith("_") or (drop_snapshot and p.stem == "qbittorrent"):
                continue
            data = json.loads(p.read_text(encoding="utf-8"))["data"]
            if p.stem == "qbittorrent":
                data["dl_limit_bps"] = limit
                if drop_field:
                    data.pop("dl_limit_bps")
                    data.pop("dl_limit_text")
            write_envelope(snaps, p.stem, age_minutes=1, data=data)
        import hub.main
        importlib.reload(hub.main)
        return TestClient(hub.main.app)
    build.qbit = qbit
    return build


def snap(data, updated_at="2026-10-22T00:00:00+00:00"):
    return {"qbittorrent": Snapshot(connector="qbittorrent", status="ok", fetched_at=updated_at, updated_at=updated_at,
                                    consecutive_failures=0, error=None, data=data, age_minutes=1.0)}


# ---- status(snaps): the mode from the snapshot ----
@pytest.mark.parametrize("bps, mode, text", [
    (625000, "quiet", "Capped at 5 Mbps"),
    (624640, "quiet", "Capped at 5 Mbps"),      # what qBittorrent reads back (it keeps KiB/s)
    (0, "full", "Unlimited"),
    (250000, "custom", "Capped at 2 Mbps"),
    (5120000, "custom", "Capped at 41 Mbps"),   # 5000 KiB/s typed into qBittorrent's own box
])
def test_status_from_the_snapshot(creds, bps, mode, text):
    assert server_quiet.status(snap({"summary": "x", "dl_limit_bps": bps})) == {"configured": True, "mode": mode,
                                                                                "text": text}


def test_status_not_configured_without_snapshot_field_or_creds(creds, monkeypatch):
    off = {"configured": False, "mode": None, "text": ""}
    assert server_quiet.status({}) == off
    assert server_quiet.status(snap({"summary": "x"})) == off                        # an envelope from before P4
    assert server_quiet.status(snap({"summary": "x", "dl_limit_bps": None})) == off
    monkeypatch.delenv("QBIT_PASS")
    assert server_quiet.status(snap({"summary": "x", "dl_limit_bps": 0})) == off     # the hub cannot write: no row


def test_quiet_mbps_env_overrides_and_junk_falls_back(creds, monkeypatch):
    assert server_quiet.quiet_bps() == server_quiet.QUIET_BPS == 625_000
    monkeypatch.setenv("QUIET_MBPS", "8")
    assert server_quiet.quiet_bps() == 1_000_000
    assert server_quiet.status(snap({"summary": "x", "dl_limit_bps": 999_424}))["mode"] == "quiet"
    for junk in ("", "fast", "0", "-3"):
        monkeypatch.setenv("QUIET_MBPS", junk)
        assert server_quiet.quiet_bps() == 625_000, junk


# ---- set_mode: login, setDownloadLimit, read back ----
def test_set_quiet_posts_the_limit_and_confirms(creds, qbit):
    out = server_quiet.set_mode("quiet")
    assert out == {"ok": True, "mode": "quiet", "text": "Quiet mode on"}
    assert [(c["method"], c["url"].removeprefix(URL)) for c in qbit.calls] == [
        ("POST", "/api/v2/auth/login"), ("POST", "/api/v2/transfer/setDownloadLimit"), ("GET", "/api/v2/transfer/info")]
    login, put, info = qbit.calls
    assert login["data"] == {"username": USER, "password": PASSWORD} and login["headers"] == {"Referer": URL}
    assert put["data"] == {"limit": 625000} and put["cookies"] == {"SID": "sid123"}
    assert info["cookies"] == {"SID": "sid123"} and all(c["timeout"] == 10 for c in qbit.calls)


def test_set_full_posts_zero_and_the_page_mode_follows_before_the_next_sweep(creds, qbit):
    qbit.limit = 624640
    before = snap({"summary": "x", "dl_limit_bps": 624640})
    assert server_quiet.status(before)["mode"] == "quiet"
    assert server_quiet.set_mode("full") == {"ok": True, "mode": "full", "text": "Full speed"}
    assert qbit.calls[1]["data"] == {"limit": 0}
    assert server_quiet.status(before)["mode"] == "full"                           # the kept, newer answer wins
    later = snap({"summary": "x", "dl_limit_bps": 250000}, updated_at="2099-01-01T00:00:00+00:00")
    assert server_quiet.status(later)["mode"] == "custom"                          # a newer sweep wins again


def test_older_qbittorrent_200_ok_login_with_a_qbt_sid_cookie_works(creds, qbit):
    qbit.login = Resp(200, None, {"QBT_SID_8080": "abc"})
    assert server_quiet.set_mode("quiet")["ok"] is True
    assert qbit.calls[1]["cookies"] == {"QBT_SID_8080": "abc"}


@pytest.mark.parametrize("login, logged", [
    (Resp(403), "HTTP 403"),
    (Resp(200, None, {}), "no session cookie"),                                       # 4.x 200 "Fails."
    (requests.ConnectionError(f"{URL} user={USER} pass={PASSWORD}"), "ConnectionError"),
])
def test_login_refused_is_ok_false_and_logs_only_the_type(creds, qbit, caplog, login, logged):
    qbit.login = login
    with caplog.at_level(logging.WARNING):
        out = server_quiet.set_mode("quiet")
    assert out == {"ok": False, "mode": "quiet", "text": "Couldn't reach qBittorrent"}
    assert [c["url"].removeprefix(URL) for c in qbit.calls] == ["/api/v2/auth/login"]   # nothing set
    assert logged in caplog.text
    assert PASSWORD not in caplog.text and "secret-host" not in caplog.text and USER not in caplog.text


@pytest.mark.parametrize("tweak", ["set_refused", "info_refused", "readback_differs"])
def test_unconfirmed_change_is_ok_false(creds, qbit, caplog, tweak):
    if tweak == "set_refused":
        qbit.set_status = 403
    elif tweak == "info_refused":
        qbit.info_status = 500
    else:
        qbit.readback = 250000
    with caplog.at_level(logging.WARNING):
        assert server_quiet.set_mode("quiet")["ok"] is False
    assert server_quiet._kept == {} and PASSWORD not in caplog.text


def test_set_mode_never_calls_without_creds_or_for_a_junk_mode(qbit, monkeypatch):
    for name in ("QBIT_URL", "QBIT_USER", "QBIT_PASS"):
        monkeypatch.delenv(name, raising=False)
    assert server_quiet.set_mode("quiet")["ok"] is False
    monkeypatch.setenv("QBIT_URL", URL)
    monkeypatch.setenv("QBIT_USER", USER)
    monkeypatch.setenv("QBIT_PASS", PASSWORD)
    assert server_quiet.set_mode("custom")["ok"] is False
    assert qbit.calls == []


# ---- routes ----
@pytest.mark.parametrize("mode, words, button", [
    ("quiet", "caps qBittorrent's total download speed at 5 Mbps", "Turn on Quiet mode"),
    ("full", "removes qBittorrent's download cap", "Go full speed"),
])
def test_get_confirm_renders_and_calls_nothing(env, mode, words, button):
    with env(limit=250000) as client:
        r = client.get(f"/server/downloads/cap?mode={mode}")
    body = txt(main_of(r.text)).replace("&#39;", "'")
    assert r.status_code == 200 and words in body and "Downloads · Capped at 2 Mbps" in body
    assert 'method="post" action="/server/downloads/cap"' in r.text and f'name="mode" value="{mode}"' in r.text
    assert button in body and 'href="/server#downloads"' in r.text
    assert env.qbit.calls == [] and PASSWORD not in r.text and "secret-host" not in r.text


def test_get_confirm_when_already_on_or_not_configured_offers_no_button(env):
    with env(limit=0) as client:
        g = main_of(client.get("/server/downloads/cap?mode=full").text)
        junk = client.get("/server/downloads/cap?mode=custom", follow_redirects=False)
    assert "Full speed is already on." in g and 'action="/server/downloads/cap"' not in g
    assert junk.status_code == 303 and junk.headers["location"] == "/server#downloads"
    with env(qbit_env=False) as client:
        g = main_of(client.get("/server/downloads/cap?mode=quiet").text)
    assert "qBittorrent is not connected on the hub" in g and 'action="/server/downloads/cap"' not in g


def test_post_without_same_origin_is_refused(env):
    with env() as client:
        r = client.post("/server/downloads/cap", data={"mode": "quiet"}, headers=EVIL, follow_redirects=False)
    assert r.status_code == 403 and env.qbit.calls == []


@pytest.mark.parametrize("mode, flag, words", [("quiet", "quiet", "Quiet mode on"), ("full", "full", "Full speed")])
def test_post_sets_the_cap_and_redirects_with_the_flash(env, caplog, mode, flag, words):
    start = 0 if mode == "quiet" else 624640
    env.qbit.limit = start
    with caplog.at_level(logging.WARNING), env(limit=start) as client:
        r = client.post("/server/downloads/cap", data={"mode": mode}, follow_redirects=False)
        page = client.get(r.headers["location"]).text
    assert r.status_code == 303 and r.headers["location"] == f"/server?cap={flag}#downloads"
    q = row(page)
    assert f'<p class="metaline quietrow-flash st-good" role="status">{words}</p>' in q
    on = "Quiet (5 Mbps)" if mode == "quiet" else "Full speed"
    assert f'<span class="chip on" aria-current="true">{on}</span>' in q                  # the page already follows
    assert PASSWORD not in page + caplog.text + r.headers["location"] and "secret-host" not in page + caplog.text


def test_post_that_fails_flashes_couldnt_reach(env):
    env.qbit.login = requests.ConnectTimeout(f"{URL} {PASSWORD}")
    with env() as client:
        r = client.post("/server/downloads/cap", data={"mode": "quiet"}, follow_redirects=False)
        page = client.get(r.headers["location"]).text
    assert r.headers["location"] == "/server?cap=failed#downloads"
    assert '<p class="metaline quietrow-flash st-warn" role="status">Couldn&#39;t reach qBittorrent</p>' in row(page)
    assert '<span class="chip on" aria-current="true">Full speed</span>' in row(page)     # unchanged


def test_post_junk_mode_or_no_creds_redirects_without_a_call(env):
    with env() as client:
        r = client.post("/server/downloads/cap", data={"mode": "custom"}, follow_redirects=False)
    assert r.headers["location"] == "/server#downloads" and env.qbit.calls == []
    with env(qbit_env=False) as client:
        r = client.post("/server/downloads/cap", data={"mode": "quiet"}, follow_redirects=False)
    assert r.headers["location"] == "/server#downloads" and env.qbit.calls == []


# ---- the Server page row ----
def test_page_shows_one_row_under_downloads_with_the_sleep_window(env, monkeypatch):
    with env(limit=0) as client:
        html = client.get("/server").text
    q = row(html)
    assert html.count('class="quietrow"') == 1 and env.qbit.calls == []                  # the render calls nothing
    assert '<span class="quietrow-label">Downloads</span>' in q
    assert '<a class="chip" href="/server/downloads/cap?mode=quiet">Quiet (5 Mbps)</a>' in q
    assert '<span class="chip on" aria-current="true">Full speed</span>' in q
    assert "NAS sleeps 22:00–07:00" in q and "Capped" not in q and 'role="status"' not in q
    services = main_of(html).split('id="services"', 1)[1].split('id="updates"', 1)[0]
    downloads = services.split('<h2 class="seclabel">Downloads</h2>', 1)[1].split("</section>", 1)[0]
    assert 'class="quietrow"' in downloads and downloads.index("libhealth") < downloads.index("quietrow")
    monkeypatch.setenv("NAS_SLEEP_WINDOW", "23:00–06:30")
    with env(limit=625000) as client:
        q = row(client.get("/server").text)
    assert '<span class="chip on" aria-current="true">Quiet (5 Mbps)</span>' in q and "NAS sleeps 23:00–06:30" in q
    assert '<a class="chip" href="/server/downloads/cap?mode=full">Full speed</a>' in q


def test_custom_cap_shows_its_words_with_both_chips_as_links(env):
    with env(limit=250000) as client:
        q = row(client.get("/server").text)
    assert '<span class="metaline">Capped at 2 Mbps</span>' in q and "chip on" not in q
    assert 'href="/server/downloads/cap?mode=quiet"' in q and 'href="/server/downloads/cap?mode=full"' in q


@pytest.mark.parametrize("kw", [{"qbit_env": False}, {"drop_field": True}, {"drop_snapshot": True}])
def test_page_hides_the_row_when_not_configured(env, kw):
    with env(**kw) as client:
        r = client.get("/server?cap=quiet")
    assert r.status_code == 200 and 'class="quietrow"' not in r.text and "Quiet mode on" not in r.text


def test_junk_cap_flash_is_ignored(env):
    with env() as client:
        q = row(client.get("/server?cap=<script>").text)
    assert q and "<script>" not in q and 'role="status"' not in q


def test_css_is_one_dated_tail_block():
    css = (ROOT / "hub" / "static" / "control-surface.css").read_text(encoding="utf-8")
    assert css.count("/* P4 quiet mode (2026-10-22)") == 1
    tail = css.split("/* P4 quiet mode (2026-10-22)", 1)[1]
    assert re.search(r"\.quietrow \{[^}]*display: flex;[^}]*flex-wrap: wrap;", tail)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(", tail)


def test_template_edit_is_one_commented_block():
    html = (ROOT / "hub" / "templates" / "server.html").read_text(encoding="utf-8")
    assert html.count("{# P4 quiet mode (2026-10-22)") == 1 and html.count("quietrow") == 3


# ---- the connector's snapshot fields ----
def test_connector_exposes_the_download_limit():
    from connectors.stubs import QBittorrent
    schema = json.loads((ROOT / "connectors" / "schema" / "data" / "qbittorrent.schema.json").read_text(encoding="utf-8"))
    raw = QBittorrent().fetch_fixture()
    for limit, text in ((0, "Unlimited"), (625000, "5 Mbps"), (624640, "5 Mbps"), (250000, "2 Mbps"),
                        (5120000, "41 Mbps"), (100000, "0.8 Mbps"), (1024, "8 kbps"), (-1, "Unlimited")):
        r = copy.deepcopy(raw)
        r["raw_transfer"]["dl_rate_limit"] = limit
        data = QBittorrent().transform(r)
        jsonschema.validate(data, schema)
        assert (data["dl_limit_bps"], data["dl_limit_text"]) == (max(0, limit), text), limit
    r = copy.deepcopy(raw)
    del r["raw_transfer"]["dl_rate_limit"]
    data = QBittorrent().transform(r)
    jsonschema.validate(data, schema)
    assert data["dl_limit_bps"] is None and data["dl_limit_text"] is None
    sample = json.loads((SAMPLES / "qbittorrent.json").read_text(encoding="utf-8"))["data"]
    assert (sample["dl_limit_bps"], sample["dl_limit_text"]) == (0, "Unlimited")


def test_contract_doc_pins_the_fields_and_the_live_write():
    text = (ROOT / "docs" / "connector-contract.md").read_text(encoding="utf-8")
    para = text.split("**qBittorrent download cap (P4, 2026-10-22).**", 1)[1].split("\n\n", 1)[0]
    for needle in ("`dl_limit_bps`", "`dl_limit_text`", "dl_rate_limit", "0 = no cap", "Unlimited", "5 Mbps",
                   "Older envelopes lack both"):
        assert needle in para, needle
    live = text.split("**Nineteenth exception (2026-10-22): Server → Downloads Quiet mode", 1)[1].split("\n\n", 1)[0]
    for needle in ("POST /api/v2/auth/login", "POST /api/v2/transfer/setDownloadLimit", "GET /api/v2/transfer/info",
                   "same_origin", "624640", "makes no call", "Not a GUEST route", "never the\nURL, user or password"):
        assert needle in live, needle
