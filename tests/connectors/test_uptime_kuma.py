"""WP-S4 (2026-10-06): Uptime Kuma 1.23 monitors from the Prometheus /metrics text —
HTTP Basic with an empty username and the API key as password. HTTP is always
intercepted, so the suite stays offline by construction."""

import json
from pathlib import Path

import jsonschema
import pytest
import requests

from connectors.stubs import UptimeKuma

ROOT = Path(__file__).resolve().parents[2]
URL, KEY = "http://kuma.example.invalid:3001", "uk1_KUMASECRETkey"
SCHEMA = json.loads((ROOT / "connectors" / "schema" / "data" / "uptime_kuma.schema.json")
                    .read_text(encoding="utf-8"))
FIXTURE = (ROOT / "connectors" / "fixtures" / "uptime_kuma" / "raw.txt").read_text(encoding="utf-8")


class Resp:
    def __init__(self, text="", code=200):
        self.text, self.status_code = text, code

    def raise_for_status(self):
        if self.status_code >= 400:
            err = requests.HTTPError(f"{self.status_code} for url: {URL}/metrics")
            err.response = self
            raise err


@pytest.fixture()
def live(snapshots, monkeypatch):
    monkeypatch.setenv("CONNECTOR_MODE", "live")
    monkeypatch.setenv("UPTIME_KUMA_URL", URL + "/")
    monkeypatch.setenv("UPTIME_KUMA_API_KEY", KEY)
    return snapshots


def fake_get(monkeypatch, outcome):
    calls = []

    def get(url, **kw):
        calls.append({"url": url, **kw})
        if isinstance(outcome, Exception):
            raise outcome
        return outcome
    monkeypatch.setattr(requests, "get", get)
    return calls


def test_requires_env_names_both_variables():
    assert UptimeKuma.requires_env == ("UPTIME_KUMA_URL", "UPTIME_KUMA_API_KEY")


def test_fixture_transform(snapshots):
    data = UptimeKuma().run()["data"]
    jsonschema.validate(data, SCHEMA)
    assert (data["up"], data["down"], data["total"]) == (5, 1, 6)
    assert data["summary"] == "5 of 6 up" and data["secondary"] == "Prowlarr down"
    assert data["monitors"][0] == {"name": "Prowlarr", "type": "http", "status": "down",
                                   "response_ms": None}
    assert [m["name"] for m in data["monitors"][1:]] == ["Jellyfin", "Jellyseerr", "NAS", "Radarr", "Sonarr"]
    assert data["monitors"][1]["response_ms"] == 38


def test_live_fetch_is_one_basic_auth_get_with_empty_user(live, monkeypatch):
    calls = fake_get(monkeypatch, Resp(FIXTURE))
    envelope = UptimeKuma().run()
    assert envelope["status"] == "ok"
    assert calls == [{"url": f"{URL}/metrics", "auth": ("", KEY), "timeout": 10}]
    jsonschema.validate(envelope["data"], SCHEMA)
    assert envelope["data"]["summary"] == "5 of 6 up"


def test_pending_maintenance_and_urls_never_leak(live, monkeypatch):
    secret_url = "https://lan.example.invalid/hook?token=TOPSECRETtoken123"
    text = "\n".join([
        f'monitor_status{{monitor_name="Backup, nightly",monitor_type="push",monitor_url="{secret_url}",'
        f'monitor_hostname="10.0.0.9",monitor_port="null"}} 2',
        f'monitor_status{{monitor_name="Router",monitor_type="ping",monitor_url="https://",'
        f'monitor_hostname="10.0.0.1",monitor_port="null"}} 3',
        f'monitor_response_time{{monitor_name="Router",monitor_type="ping",monitor_url="https://",'
        f'monitor_hostname="10.0.0.1",monitor_port="null"}} 4',
    ])
    fake_get(monkeypatch, Resp(text))
    data = UptimeKuma().run()["data"]
    jsonschema.validate(data, SCHEMA)
    assert [(m["name"], m["status"], m["response_ms"]) for m in data["monitors"]] == [
        ("Backup, nightly", "pending", None), ("Router", "maintenance", None)]
    assert (data["up"], data["down"], data["total"], data["summary"]) == (0, 0, 2, "0 of 2 up")
    blob = json.dumps(data)
    for leak in ("TOPSECRET", "10.0.0", "example.invalid", "https://"):
        assert leak not in blob


@pytest.mark.parametrize("outcome, reason", [
    (Resp(code=401), "HTTP 401"),
    (requests.ConnectTimeout(f"{URL} timed out"), "timeout"),
])
def test_failures_are_sanitised_and_keep_the_previous_data(live, monkeypatch, outcome, reason):
    fake_get(monkeypatch, Resp(FIXTURE))
    good = UptimeKuma().run()
    fake_get(monkeypatch, outcome)
    bad = UptimeKuma().run()
    assert bad["status"] == "error" and bad["consecutive_failures"] == 1
    assert bad["error"] == f"RuntimeError: Uptime Kuma metrics failed ({reason})"
    assert bad["data"] == good["data"]
    blob = json.dumps(bad)
    for secret in (KEY, "example.invalid", "http://"):
        assert secret not in blob


@pytest.mark.parametrize("text", [
    "<html><body>Login</body></html>",                                  # not metrics at all
    'monitor_status{monitor_name="X",monitor_type="http"} up',          # non-numeric value
    'monitor_status{monitor_name="X",monitor_type="http"} 7',           # unknown status code
    'monitor_status{monitor_type="http",monitor_url="https://x.invalid/?k=SECRETk"} 1',  # no name
    'monitor_status monitor_name="X" 1',                                # no label braces
])
def test_malformed_text_is_an_error_envelope_without_echo(live, monkeypatch, text):
    fake_get(monkeypatch, Resp(text))
    envelope = UptimeKuma().run()
    assert envelope["status"] == "error"
    assert envelope["error"] == "RuntimeError: Uptime Kuma metrics failed (unexpected payload)"
    assert "SECRET" not in json.dumps(envelope)


def test_missing_env_is_an_honest_error(snapshots, monkeypatch):
    monkeypatch.setenv("CONNECTOR_MODE", "live")
    for var in UptimeKuma.requires_env:
        monkeypatch.delenv(var, raising=False)
    envelope = UptimeKuma().run()
    assert envelope["status"] == "error" and "UPTIME_KUMA_URL" in envelope["error"]
