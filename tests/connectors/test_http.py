"""C-05 (2026-10-09): the one HTTP helper every live feed uses — reasons are type/status
only, only the given keyword arguments reach requests, and one Session serves a whole run."""

from datetime import datetime, timezone

import pytest
import requests

from connectors.feeds import _http
from connectors.feeds._http import http_json, reason
from connectors.feeds.arr import Arr

URL = "http://svc.example.invalid:1234/api?token=SECRET"


class Resp:
    def __init__(self, payload=None, code=200, text=""):
        self.payload, self.status_code, self.text = payload, code, text

    def raise_for_status(self):
        if self.status_code >= 400:
            err = requests.HTTPError(f"{self.status_code} for url: {URL}")
            err.response = self
            raise err

    def json(self):
        return self.payload


@pytest.mark.parametrize("exc, word", [
    (requests.ConnectTimeout(URL), "timeout"),       # a ConnectionError too: timeout wins
    (requests.ReadTimeout(URL), "timeout"),
    (requests.ConnectionError(URL), "connection refused"),
    (ValueError(URL), "ValueError"),
])
def test_reason_is_one_word_never_the_url(exc, word):
    assert reason(exc) == word


def test_reason_prefers_the_http_status():
    err = requests.HTTPError(URL)
    err.response = Resp(code=503)
    assert reason(err) == "HTTP 503"


def test_only_given_keywords_reach_requests_and_timeout_defaults_to_10(monkeypatch):
    seen = []
    monkeypatch.setattr(requests, "get", lambda url, **kw: seen.append(kw) or Resp({"a": 1}))
    assert http_json("Svc things", URL) == {"a": 1}
    assert http_json("Svc things", URL, params={"x": 1}, auth=("", "k")) == {"a": 1}
    assert seen == [{"timeout": 10}, {"timeout": 10, "params": {"x": 1}, "auth": ("", "k")}]


def test_text_mode_and_post(monkeypatch):
    monkeypatch.setattr(requests, "post", lambda url, **kw: Resp(text=f"posted {sorted(kw)}"))
    assert http_json("Svc login", URL, method="POST", data={"u": 1}, text=True) == \
        "posted ['data', 'timeout']"


@pytest.mark.parametrize("outcome, word", [
    (Resp(code=401), "HTTP 401"),
    (requests.ConnectionError(f"Max retries exceeded with url: {URL}"), "connection refused"),
    (Resp(payload=None), None),  # json() fine, returns None
])
def test_failures_read_label_failed_reason_and_carry_it(monkeypatch, outcome, word):
    def get(url, **kw):
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(requests, "get", get)
    if word is None:
        assert http_json("Svc things", URL) is None
        return
    with pytest.raises(RuntimeError) as info:
        http_json("Svc things", URL)
    assert type(info.value) is RuntimeError  # envelopes keep reading "RuntimeError: ..."
    assert str(info.value) == f"Svc things failed ({word})" and info.value.reason == word
    assert info.value.__cause__ is None and info.value.__suppress_context__
    assert "SECRET" not in str(info.value) and "example.invalid" not in str(info.value)


def test_a_run_makes_every_call_on_one_session_and_closes_it(snapshots, monkeypatch):
    """Arr's ~11 calls ride one Session (one connection per app), never requests.get."""
    raw = Arr().fetch_fixture()
    monkeypatch.setenv("CONNECTOR_MODE", "live")
    for var, value in (("RADARR_URL", "http://radarr.example.invalid:7878"), ("RADARR_API_KEY", "r"),
                       ("SONARR_URL", "http://sonarr.example.invalid:8989"), ("SONARR_API_KEY", "s")):
        monkeypatch.setenv(var, value)
    monkeypatch.delenv("PROWLARR_URL", raising=False)
    monkeypatch.setattr("connectors.feeds.arr._now", lambda: datetime(2026, 1, 1, tzinfo=timezone.utc))
    monkeypatch.setattr(requests, "get", lambda *a, **k: pytest.fail("a call bypassed the session"))
    sessions = []

    class CountingSession:
        def __init__(self):
            self.calls, self.closed = [], False
            sessions.append(self)

        def get(self, url, **kw):
            self.calls.append(url)
            app = "radarr" if "radarr" in url else "sonarr"
            return Resp(raw[f"raw_{app}_{url.rsplit('/', 1)[1]}"])

        def close(self):
            self.closed = True

    monkeypatch.setattr(requests, "Session", CountingSession)
    envelope = Arr().run()
    assert envelope["status"] == "ok", envelope["error"]
    assert len(sessions) == 1 and sessions[0].closed
    assert len(sessions[0].calls) == 15  # 4 + 1 + 2 Radarr, 4 + 2 + 2 Sonarr (F4a: cutoff + qualityprofile)


def test_session_is_a_requests_session(monkeypatch):
    monkeypatch.undo()  # drop conftest's routed stand-in; a real Session opens no socket
    s = _http.session()
    try:
        assert isinstance(s, requests.Session)
    finally:
        s.close()
