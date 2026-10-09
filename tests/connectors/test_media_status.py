"""Media Phase 1 — the app-health connector. Down is data, never a failed run."""

import json
from pathlib import Path

import jsonschema
import pytest
import requests

from connectors.stubs import MEDIA_APPS, MediaStatus

HOST = "10.9.9.9"
SCHEMA = json.loads(
    (Path(__file__).resolve().parents[2] / "connectors" / "schema" / "data" / "media_status.schema.json")
    .read_text(encoding="utf-8")
)


@pytest.fixture()
def live(snapshots, monkeypatch):
    monkeypatch.setenv("CONNECTOR_MODE", "live")
    monkeypatch.setenv("MEDIA_STATUS_HOST", HOST)
    return snapshots


class Resp:
    def __init__(self, code):
        self.status_code = code


def run_with(monkeypatch, behaviour):
    """behaviour(port) -> status code, or an exception instance to raise."""
    def fake_get(url, timeout=None, **kw):
        assert timeout == 5 and url.startswith(f"http://{HOST}:")
        outcome = behaviour(int(url.split(":")[2].split("/")[0]))
        if isinstance(outcome, Exception):
            raise outcome
        return Resp(outcome)

    monkeypatch.setattr(requests, "get", fake_get)
    return MediaStatus().run()


def test_requires_only_the_host():
    assert MediaStatus.requires_env == ("MEDIA_STATUS_HOST",)


def test_all_up(live, monkeypatch):
    envelope = run_with(monkeypatch, lambda port: 200)
    data = envelope["data"]
    assert envelope["status"] == "ok"
    assert data["summary"] == "11 of 11 up" and data["secondary"] == "All apps up"
    assert all(a["status_text"] == "Up" and a["note"] is None for a in data["apps"])
    assert data["apps"][0]["href"] == f"http://{HOST}:8096"
    jsonschema.validate(data, SCHEMA)


def test_one_down_by_timeout_keeps_the_run_ok(live, monkeypatch):
    prowlarr = next(a["port"] for a in MEDIA_APPS if a["id"] == "prowlarr")
    envelope = run_with(
        monkeypatch,
        lambda port: requests.Timeout(f"timed out http://{HOST}:{port}") if port == prowlarr else 200,
    )
    data = envelope["data"]
    assert envelope["status"] == "ok" and envelope["consecutive_failures"] == 0
    assert data["summary"] == "10 of 11 up" and data["secondary"] == "Down: Prowlarr"
    down = [a for a in data["apps"] if not a["up"]]
    assert [(a["name"], a["status_text"], a["note"]) for a in down] == [("Prowlarr", "Down", "timeout")]
    jsonschema.validate(data, SCHEMA)


def test_connection_refused_and_5xx_notes(live, monkeypatch):
    def behaviour(port):
        if port == 7878:
            return requests.ConnectionError(f"refused {HOST}:{port}")
        if port == 8989:
            return 502
        return 200

    data = run_with(monkeypatch, behaviour)["data"]
    notes = {a["name"]: a["note"] for a in data["apps"] if not a["up"]}
    assert notes == {"Radarr": "connection refused", "Sonarr": "HTTP 502"}


def test_401_counts_as_up(live, monkeypatch):
    data = run_with(monkeypatch, lambda port: 401)["data"]
    assert data["summary"] == "11 of 11 up"


def test_notes_never_contain_a_url_or_host(live, monkeypatch):
    envelope = run_with(monkeypatch, lambda port: RuntimeError(f"boom http://{HOST}:{port}/x"))
    notes = {a["id"]: a["note"] for a in envelope["data"]["apps"]}
    # gluetun is derived, never probed (WP-S2) — its note is fixed words
    assert notes.pop("gluetun") == "no answer via Prowlarr or qBittorrent"
    assert list(notes.values()) == ["RuntimeError"] * 10


def test_fixture_mode_never_touches_the_network(snapshots, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("fixture mode must not probe the network")

    monkeypatch.setattr(requests, "get", boom)
    envelope = MediaStatus().run()
    assert envelope["status"] == "ok"
    assert envelope["data"]["summary"] == "10 of 11 up"
    assert envelope["data"]["apps"][4]["note"] == "timeout"


def test_live_mode_without_host_fails_naming_the_variable(snapshots, monkeypatch):
    monkeypatch.setenv("CONNECTOR_MODE", "live")
    monkeypatch.delenv("MEDIA_STATUS_HOST", raising=False)
    envelope = MediaStatus().run()
    assert envelope["status"] == "error" and "MEDIA_STATUS_HOST" in envelope["error"]


# ---- WP-S2 (2026-10-06): wud / adm probed, gluetun derived (homepage retired 2026-10-09, decision 9) ----


def test_server_apps_are_listed_with_their_ports():
    ports = {a["id"]: a["port"] for a in MEDIA_APPS}
    assert (ports["wud"], ports["adm"]) == (3030, 8000) and "homepage" not in ports and len(MEDIA_APPS) == 11
    assert {a["id"]: a["name"] for a in MEDIA_APPS if a["id"] in ("wud", "adm", "gluetun")} == {
        "gluetun": "Gluetun", "wud": "WUD", "adm": "ADM"}
    assert all(a["id"] == a["id"].lower() for a in MEDIA_APPS)


def test_gluetun_is_never_probed(live, monkeypatch):
    probed = []
    run_with(monkeypatch, lambda port: probed.append(port) or 200)
    assert len(probed) == len(MEDIA_APPS) - 1  # every app except gluetun


@pytest.mark.parametrize("prowlarr_up, qbit_up, gluetun_up", [
    (True, True, True), (False, True, True), (True, False, True), (False, False, False)])
def test_gluetun_up_iff_prowlarr_or_qbittorrent_answers(live, monkeypatch, prowlarr_up, qbit_up, gluetun_up):
    def behaviour(port):
        if port == 9696:
            return 200 if prowlarr_up else requests.ConnectionError("x")
        if port == 8080:
            return 200 if qbit_up else requests.Timeout("x")
        return 200

    apps = {a["id"]: a for a in run_with(monkeypatch, behaviour)["data"]["apps"]}
    assert apps["gluetun"]["up"] is gluetun_up
    assert apps["gluetun"]["note"] == (None if gluetun_up else "no answer via Prowlarr or qBittorrent")


def test_adm_redirect_to_https_counts_as_up(live, monkeypatch):
    seen = {}

    def fake_get(url, timeout=None, allow_redirects=True, **kw):
        seen[url.split(":")[2].split("/")[0]] = allow_redirects
        return Resp(302 if ":8000/" in url else 200)

    monkeypatch.setattr(requests, "get", fake_get)
    apps = {a["id"]: a for a in MediaStatus().run()["data"]["apps"]}
    assert apps["adm"]["up"] and apps["adm"]["href"] == f"http://{HOST}:8000"
    assert seen["8000"] is False  # the redirect is the answer, never followed


def test_new_ids_land_in_the_right_server_groups():
    from hub.server import group_services

    groups = {g["label"]: [a["id"] for a in g["apps"]] for g in group_services([{"id": a["id"]} for a in MEDIA_APPS])}
    assert "gluetun" in groups["Downloads"]
    assert {"wud", "adm"} <= set(groups["System"])


def test_probes_run_concurrently_at_most_six_at_a_time_in_app_order(live, monkeypatch):
    """C-12: sequential 5 s timeouts stretched the 120 s fast loop to ~55 s."""
    import threading
    import time

    lock, active, peak = threading.Lock(), [0], [0]

    def slow(port):
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        time.sleep(0.05)
        with lock:
            active[0] -= 1
        return 200 if port != 7878 else 503

    raw_order = []
    real_fetch = MediaStatus.fetch

    def spy(self):
        raw = real_fetch(self)
        raw_order.extend(r["id"] for r in raw)
        return raw

    monkeypatch.setattr(MediaStatus, "fetch", spy)
    envelope = run_with(monkeypatch, slow)
    assert 2 <= peak[0] <= 6
    assert raw_order == [a["id"] for a in MEDIA_APPS if "via" not in a] + ["gluetun"]
    assert [a["id"] for a in envelope["data"]["apps"]] == [a["id"] for a in MEDIA_APPS]
    assert envelope["data"]["secondary"] == "Down: Radarr"


# ---- N-09 (2026-10-09): MEDIA_STATUS_HOSTS moves the probe onto the shared Docker network ----


def test_probe_hosts_override_the_probe_but_never_the_link(live, monkeypatch):
    monkeypatch.setenv("MEDIA_STATUS_HOSTS",
                       "jellyfin=jellyfin, qbittorrent=gluetun,prowlarr=gluetun,wud=wud:3000")
    probed = []

    def fake_get(url, timeout=None, **kw):
        probed.append(url)
        return Resp(200)

    monkeypatch.setattr(requests, "get", fake_get)
    data = MediaStatus().run()["data"]
    assert {"http://jellyfin:8096/health", "http://gluetun:8080/api/v2/app/version",
            "http://gluetun:9696/ping", "http://wud:3000/", f"http://{HOST}:7878/ping"} <= set(probed)
    assert len(probed) == 10 and not any(u.startswith(f"http://{HOST}:3030") for u in probed)
    hrefs = {a["id"]: a["href"] for a in data["apps"]}
    assert hrefs["jellyfin"] == f"http://{HOST}:8096" and hrefs["wud"] == f"http://{HOST}:3030"
    assert hrefs["qbittorrent"] == hrefs["gluetun"] == f"http://{HOST}:8080"
    assert data["summary"] == "11 of 11 up"


@pytest.mark.parametrize("spec, expected", [
    ("", {}),
    ("jellyfin=jellyfin", {"jellyfin": ("jellyfin", 8096)}),
    ("wud=wud:3000,radarr=radarr", {"wud": ("wud", 3000), "radarr": ("radarr", 7878)}),
    ("nosuch=x,gluetun=gluetun,radarr=,=x,sonarr", {}),        # unknown, derived, blank, malformed
    ("wud=wud:http,sonarr=sonarr:", {}),                       # a port must be digits
])
def test_probe_targets_parse(monkeypatch, spec, expected):
    from connectors.feeds.media_status import probe_targets

    monkeypatch.setenv("MEDIA_STATUS_HOSTS", spec)
    assert probe_targets() == expected
