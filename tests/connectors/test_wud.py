"""WP-S3 (2026-10-06): the live What's Up Docker fetch — one basic-auth GET of
/api/containers, the JSON list returned unchanged, failures sanitised. HTTP is
always intercepted, so the suite stays offline by construction."""

import json
from pathlib import Path

import jsonschema
import pytest
import requests

from connectors.stubs import Wud

URL, USER, PASS = "http://wud.example.invalid:3030", "wuduser", "WUDSECRETpass"
SCHEMA = json.loads((Path(__file__).resolve().parents[2] / "connectors" / "schema" / "data"
                     / "wud.schema.json").read_text(encoding="utf-8"))


class Resp:
    def __init__(self, payload=None, code=200):
        self.payload, self.status_code = payload, code

    def raise_for_status(self):
        if self.status_code >= 400:
            err = requests.HTTPError(f"{self.status_code} for url: {URL}/api/containers")
            err.response = self
            raise err

    def json(self):
        return self.payload


@pytest.fixture()
def live(snapshots, monkeypatch):
    monkeypatch.setenv("CONNECTOR_MODE", "live")
    monkeypatch.setenv("WUD_URL", URL + "/")
    monkeypatch.setenv("WUD_USER", USER)
    monkeypatch.setenv("WUD_PASS", PASS)
    return snapshots


def fixture_raw():
    return json.loads((Path(__file__).resolve().parents[2] / "connectors" / "fixtures" / "wud"
                       / "raw.json").read_text(encoding="utf-8"))


def fake_get(monkeypatch, outcome):
    calls = []

    def get(url, **kw):
        calls.append({"url": url, **kw})
        if isinstance(outcome, Exception):
            raise outcome
        return outcome
    monkeypatch.setattr(requests, "get", get)
    return calls


def test_requires_env_names_the_three_variables():
    assert Wud.requires_env == ("WUD_URL", "WUD_USER", "WUD_PASS")


def test_live_fetch_is_one_basic_auth_get_with_a_timeout(live, monkeypatch):
    calls = fake_get(monkeypatch, Resp(fixture_raw()))
    envelope = Wud().run()
    assert envelope["status"] == "ok"
    assert calls == [{"url": f"{URL}/api/containers", "auth": (USER, PASS), "timeout": 10}]
    jsonschema.validate(envelope["data"], SCHEMA)
    assert (envelope["data"]["monitoring"], envelope["data"]["updates"]) == (17, 2)


def test_digest_update_from_the_live_shape_has_kind_digest_and_no_new_tag(live, monkeypatch):
    # WUD 9: a digest-only update keeps result.tag == the current tag
    fake_get(monkeypatch, Resp([
        {"name": "nginx", "image": {"name": "nginx", "tag": {"value": "alpine"}},
         "updateAvailable": True,
         "updateKind": {"kind": "digest", "localValue": "sha256:aa", "remoteValue": "sha256:bb"},
         "result": {"tag": "alpine", "digest": "sha256:bb"}},
        {"name": "redis", "image": {"name": "redis", "tag": {"value": "7"}},
         "updateAvailable": False, "result": {"tag": "7"}},  # no updateKind at all
    ]))
    data = Wud().run()["data"]
    jsonschema.validate(data, SCHEMA)
    nginx, redis = data["containers"]
    assert (nginx["kind"], nginx["new_tag"], nginx["current_tag"]) == ("digest", None, "alpine")
    assert (redis["kind"], redis["new_tag"], redis["update_available"]) == (None, None, False)
    assert data["secondary"] == "nginx new image digest"


@pytest.mark.parametrize("outcome, reason", [
    (Resp(code=401), "HTTP 401"),
    (requests.ConnectionError(f"pool host=wud.example.invalid {USER}:{PASS}@"), "connection refused"),
    (requests.ConnectTimeout(f"{URL} timed out"), "timeout"),
])
def test_failures_are_sanitised_and_keep_the_previous_data(live, monkeypatch, outcome, reason):
    fake_get(monkeypatch, Resp(fixture_raw()))
    good = Wud().run()
    fake_get(monkeypatch, outcome)
    bad = Wud().run()
    assert bad["status"] == "error" and bad["consecutive_failures"] == 1
    assert bad["error"] == f"RuntimeError: WUD containers failed ({reason})"
    assert bad["data"] == good["data"]
    blob = json.dumps(bad)
    for secret in (PASS, USER, "example.invalid", "http://"):
        assert secret not in blob


def test_a_non_list_payload_is_an_error_not_a_crash(live, monkeypatch):
    fake_get(monkeypatch, Resp({"error": "nope"}))
    envelope = Wud().run()
    assert envelope["status"] == "error" and "unexpected payload" in envelope["error"]


# ---- WP-U1 (2026-10-06): `id` + `auto` per container, from WUD 9.3's triggerInclude/Exclude ----

def test_fixture_rows_carry_id_and_auto_and_the_notify_only_five_are_not_auto(live, monkeypatch):
    fake_get(monkeypatch, Resp(fixture_raw()))
    data = Wud().run()["data"]
    jsonschema.validate(data, SCHEMA)
    by = {c["name"]: c for c in data["containers"]}
    assert {n for n, c in by.items() if not c["auto"]} == {
        "gluetun", "qbittorrent", "prowlarr", "uptime-kuma", "wud"}
    assert all(c["id"] == f"ctr-{n}" for n, c in by.items())
    assert by["vaultwarden"]["auto"] is True and by["uptime-kuma"]["update_available"] is True


@pytest.mark.parametrize("row, auto", [
    ({}, True),
    ({"triggerExclude": "dockercompose.local"}, False),
    ({"triggerExclude": "discord.main, DockerCompose.Local:major"}, False),
    ({"triggerExclude": "discord.main"}, True),
    ({"triggerInclude": "discord.main"}, False),
    ({"triggerInclude": "discord.main,dockercompose.local:minor"}, True),
    ({"triggerInclude": "dockercompose.local", "triggerExclude": "dockercompose.local"}, False),
    ({"labels": {"wud.trigger.exclude": "dockercompose.local"}}, False),
])
def test_auto_follows_wuds_include_exclude_rule(row, auto):
    from connectors.stubs import wud_auto
    assert wud_auto(row) is auto


def test_a_row_without_an_id_reads_null_and_old_envelopes_stay_valid():
    data = Wud().transform([{"name": "x", "image": {"name": "x", "tag": {"value": "1"}},
                             "updateAvailable": False}])
    assert data["containers"][0]["id"] is None
    jsonschema.validate(data, SCHEMA)
    for c in data["containers"]:
        c.pop("id"), c.pop("auto")
    jsonschema.validate(data, SCHEMA)
