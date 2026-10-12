"""Server → Update now + Ignore (WP-U1, 2026-10-06). Real registry, sample snapshots copied
into a tmp dir (uptime-kuma = excluded tag update, vaultwarden = auto digest update);
`requests.post` is monkeypatched, nothing hits the network. Assertions sit inside <main>."""
import importlib
import json
import logging
import re
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
import requests
from fastapi.testclient import TestClient

from hub import media_db, server_updates
from tests.hub.helpers import write_envelope

SAMPLES = Path(__file__).resolve().parents[2] / "config" / "sample_snapshots"
URL, USER, PASS = "http://wud.secret-host.invalid:3030", "wudSECRETuser", "wudSECRETpass"
EVIL = {"origin": "https://evil.example"}


class Resp:
    def __init__(self, status=200):
        self.status_code = status


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.delenv("AREAS_PATH", raising=False)
    snaps = tmp_path / "snaps"
    snaps.mkdir()
    monkeypatch.setenv("SNAPSHOT_DIR", str(snaps))
    for name in ("WUD_URL", "WUD_USER", "WUD_PASS"):
        monkeypatch.delenv(name, raising=False)
    calls = []

    def post(url, **kw):
        calls.append({"url": url, **kw})
        if isinstance(build.outcome, Exception):
            raise build.outcome
        return build.outcome
    monkeypatch.setattr(requests, "post", post)

    def build(wud_env=True, **data):
        if wud_env:
            monkeypatch.setenv("WUD_URL", URL + "/")
            monkeypatch.setenv("WUD_USER", USER)
            monkeypatch.setenv("WUD_PASS", PASS)
        for p in SAMPLES.glob("*.json"):
            if not p.stem.startswith("_"):
                write_envelope(snaps, p.stem, age_minutes=1,
                               data=json.loads(p.read_text(encoding="utf-8"))["data"])
        for cid, d in data.items():
            write_envelope(snaps, cid, age_minutes=1, data=d)
        import hub.main
        importlib.reload(hub.main)
        return TestClient(hub.main.app)
    build.outcome, build.calls = Resp(200), calls
    return build


def main_of(html):
    return html.split("<main", 1)[1]


def txt(html):
    """Visible text of a fragment (tags stripped): the " · " joins sit in .sep spans."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html))


def band(html):
    return main_of(html).split('id="updates"', 1)[1].split('id="attention"', 1)[0]


def runs():
    with closing(sqlite3.connect(media_db.db_path())) as db:
        return db.execute("SELECT container, tag, outcome, note FROM server_update_runs ORDER BY id").fetchall()


def test_confirm_page_states_the_facts_and_posts_back(env):
    with env() as client:
        r = client.get("/server/updates/vaultwarden/run?step=confirm")
    assert r.status_code == 200
    body = main_of(r.text)
    for fact in ("vaultwarden/server", "latest", "New build", server_updates.CONFIRM_TEXT):
        assert fact in body
    assert 'method="post" action="/server/updates/vaultwarden/run"' in body
    assert URL not in r.text and "secret-host" not in r.text


def test_confirm_page_for_an_excluded_row_is_a_manual_update_with_a_major_warning(env):
    with env() as client:
        body = main_of(client.get("/server/updates/uptime-kuma/run?step=confirm").text)
    assert "1.23.16 → 2.0.2" in body and server_updates.MANUAL_CONFIRM_TEXT in body
    assert "Major version jump (1.23.16 → 2.0.2)" in body and "gluetun" not in body
    assert server_updates.CONFIRM_TEXT not in body
    assert 'method="post" action="/server/updates/uptime-kuma/run"' in body


def _with(name, **fields):
    wud = json.loads((SAMPLES / "wud.json").read_text(encoding="utf-8"))["data"]
    row = next(c for c in wud["containers"] if c["name"] == name)
    row.update(update_available=True, kind="tag", **fields)
    return wud


@pytest.mark.parametrize("name, new_tag", [("qbittorrent", "5.1.3"), ("prowlarr", "1.38.0")])
def test_vpn_routed_excluded_rows_warn_of_a_network_drop_and_run_manual(env, name, new_tag):
    with env(wud=_with(name, new_tag=new_tag)) as client:
        body = main_of(client.get(f"/server/updates/{name}/run?step=confirm").text)
        r = client.post(f"/server/updates/{name}/run", follow_redirects=False)
    assert server_updates.MANUAL_CONFIRM_TEXT in body and "gluetun (VPN)" in body
    assert "Major version" not in body
    assert r.status_code == 303 and r.headers["location"] == f"/server?flash=requested&c={name}#updates"
    assert env.calls == [{"url": f"{URL}/api/containers/ctr-{name}/triggers/dockercompose/manual",
                          "auth": (USER, PASS), "timeout": 10}]
    assert runs() == [(name, new_tag, "requested", None)]


def test_gluetun_warns_that_qbittorrent_and_prowlarr_may_need_a_restart(env):
    with env(wud=_with("gluetun", new_tag="v3.41.0")) as client:
        body = main_of(client.get("/server/updates/gluetun/run?step=confirm").text)
    assert server_updates.MANUAL_CONFIRM_TEXT in body
    assert "qBittorrent and Prowlarr share gluetun&#39;s network" in body or \
        "qBittorrent and Prowlarr share gluetun's network" in body


def test_excluded_row_posts_to_the_manual_trigger(env):
    with env() as client:
        r = client.post("/server/updates/uptime-kuma/run", follow_redirects=False)
    assert r.status_code == 303
    assert env.calls == [{"url": f"{URL}/api/containers/ctr-uptime-kuma/triggers/dockercompose/manual",
                          "auth": (USER, PASS), "timeout": 10}]
    assert runs() == [("uptime-kuma", "2.0.2", "requested", None)]


def test_wud_itself_is_always_refused_even_when_auto(env):
    with env(wud=_with("wud", new_tag="8.2.0", auto=True)) as client:
        g = main_of(client.get("/server/updates/wud/run?step=confirm").text)
        r = client.post("/server/updates/wud/run", follow_redirects=False)
        b = band(client.get("/server").text)
    assert "Update WUD by hand." in g and 'method="post" action="/server/updates/wud/run"' not in g
    assert r.status_code == 409 and "Update WUD by hand." in main_of(r.text)
    assert env.calls == []
    row = b.split(">wud<", 1)[1].split('<div class="row has-form">', 1)[0]
    assert "Update WUD by hand" in row and "Update now" not in row


def _joey(wud=None, name="joey-cloudflared"):
    """The sample WUD data plus a pending Joey-deployed container (not in the media-server compose)."""
    wud = wud or json.loads((SAMPLES / "wud.json").read_text(encoding="utf-8"))["data"]
    wud["containers"].append({"auto": True, "current_tag": "2025.8.1", "id": f"ctr-{name}", "image": "cloudflare/cloudflared",
                              "kind": "tag", "name": name, "new_tag": "2025.9.0", "update_available": True})
    return wud


@pytest.mark.parametrize("name", ["joey-cloudflared", "joey-macromates"])
def test_joey_containers_update_on_the_next_deploy_never_through_wud(env, name):
    with env(wud=_joey(name=name)) as client:
        g = main_of(client.get(f"/server/updates/{name}/run?step=confirm").text)
        r = client.post(f"/server/updates/{name}/run", follow_redirects=False)
        b = band(client.get("/server").text)
        i = client.post(f"/server/updates/{name}/ignore", follow_redirects=False)
    assert "Updates on next Joey deploy." in g and f'action="/server/updates/{name}/run"' not in g
    assert r.status_code == 409 and "Updates on next Joey deploy." in main_of(r.text)
    assert env.calls == []
    row = b.split(f">{name}<", 1)[1].split("</form>", 1)[0]
    assert "Updates on next Joey deploy" in row and "Update now" not in row and ">Ignore<" in row
    assert i.status_code == 303                      # Ignore still allowed


def test_post_without_same_origin_is_refused_and_calls_nothing(env):
    with env() as client:
        r = client.post("/server/updates/vaultwarden/run", headers=EVIL, follow_redirects=False)
    assert r.status_code == 403 and env.calls == []


@pytest.mark.parametrize("name, words", [
    ("jellyfin", "No update is pending for jellyfin"),       # not update_available
    ("ghost", "No update is pending for ghost"),             # not in the snapshot
])
def test_post_for_an_ineligible_row_is_refused_without_a_call(env, name, words):
    with env() as client:
        r = client.post(f"/server/updates/{name}/run", follow_redirects=False)
    assert r.status_code == 409 and words in main_of(r.text)
    assert env.calls == []
    assert not media_db.db_path().is_file() or runs() == []


def test_happy_path_calls_the_verified_wud_endpoint_records_and_flashes(env):
    with env() as client:
        r = client.post("/server/updates/vaultwarden/run", follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"] == "/server?flash=requested&c=vaultwarden#updates"
        page = client.get(r.headers["location"]).text
    assert env.calls == [{"url": f"{URL}/api/containers/ctr-vaultwarden/triggers/dockercompose/local",
                          "auth": (USER, PASS), "timeout": 10}]   # no body (WUD 9.3)
    assert runs() == [("vaultwarden", "latest", "requested", None)]
    b = band(page)
    assert "Update requested for vaultwarden" in b
    row = b.split(">vaultwarden<", 1)[1].split("</div>", 1)[0]
    assert "Requested just now" in row


def test_requested_clears_once_the_snapshot_tag_moves_on(env):
    wud = json.loads((SAMPLES / "wud.json").read_text(encoding="utf-8"))["data"]
    with env() as client:
        client.post("/server/updates/vaultwarden/run")
    kuma = next(c for c in wud["containers"] if c["name"] == "uptime-kuma")
    kuma.update(auto=True)
    for c in wud["containers"]:
        if c["name"] == "vaultwarden":
            c.update(update_available=True, kind="tag", new_tag="1.35.0")  # a newer target
    with env(wud=wud) as client:
        b = band(client.get("/server").text)
    assert ">vaultwarden<" in b and "Requested" not in b
    assert b.count("Update now") == 2   # uptime-kuma (manual) and vaultwarden


def test_ignore_and_unignore_hide_and_restore_the_row_and_the_count(env):
    with env() as client:
        r = client.post("/server/updates/uptime-kuma/ignore", follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"].endswith("#updates")
        b = band(client.get("/server").text)
        shown, folded = b.split("<details", 1)
        assert "1 update · 1 ignored" in txt(shown) and "uptime-kuma" not in shown
        assert "Ignored · 1" in txt(folded) and "uptime-kuma" in folded and "/unignore" in folded
        client.post("/server/updates/uptime-kuma/unignore")
        b = band(client.get("/server").text)
    assert "17 monitored · 2 updates" in txt(b) and "<details" not in b and "uptime-kuma" in b


def test_a_new_tag_resurfaces_an_ignored_row(env):
    with env() as client:
        client.post("/server/updates/uptime-kuma/ignore")
    wud = json.loads((SAMPLES / "wud.json").read_text(encoding="utf-8"))["data"]
    next(c for c in wud["containers"] if c["name"] == "uptime-kuma")["new_tag"] = "2.1.0"
    with env(wud=wud) as client:
        b = band(client.get("/server").text)
    assert "<details" not in b and "1.23.16 → 2.1.0" in b


def test_rows_show_update_now_and_excluded_rows_keep_the_manual_chip(env):
    with env() as client:
        b = band(client.get("/server").text)
    kuma = b.split(">uptime-kuma<", 1)[1].split('<div class="row has-form">', 1)[0]
    vault = b.split(">vaultwarden<", 1)[1].split('<div class="row has-form">', 1)[0]
    assert 'class="btn btn-ghost btn-sm" type="submit">Ignore<' in kuma         # Ignore is a ghost button
    assert 'class="btn btn-primary btn-sm" href="/server/updates/vaultwarden/run?step=confirm">Update now' in vault
    assert "Manual · excluded" in kuma and "Ignore" in kuma
    assert 'href="/server/updates/uptime-kuma/run?step=confirm">Update now' in kuma
    assert "Manual · excluded" not in vault
    assert 'href="/server/updates/vaultwarden/run?step=confirm">Update now' in vault


def test_missing_wud_env_is_words_not_500_and_no_call(env):
    with env(wud_env=False) as client:
        r = client.post("/server/updates/vaultwarden/run", follow_redirects=False)
        g = client.get("/server/updates/vaultwarden/run?step=confirm")
    assert r.status_code == 409 and "WUD is not configured on the hub" in main_of(r.text)
    assert g.status_code == 200 and "WUD is not configured" in main_of(g.text)
    assert env.calls == []


@pytest.mark.parametrize("outcome, flash, note", [
    (Resp(401), "WUD refused (HTTP 401)", "HTTP 401"),
    (requests.ConnectTimeout(f"{URL} timed out {USER}:{PASS}"), "WUD unreachable", "ConnectTimeout"),
    (requests.ConnectionError(f"pool host=wud.secret-host.invalid"), "WUD unreachable", "ConnectionError"),
])
def test_wud_failures_are_sanitised(env, caplog, outcome, flash, note):
    env.outcome = outcome
    with caplog.at_level(logging.WARNING), env() as client:
        r = client.post("/server/updates/vaultwarden/run", follow_redirects=False)
        page = client.get(r.headers["location"]).text
    assert r.status_code == 303 and flash in band(page)
    assert runs() == [("vaultwarden", "latest", "refused" if "HTTP" in note else "unreachable", note)]
    blob = page + caplog.text + json.dumps(runs())
    for secret in (USER, PASS, "secret-host", URL):
        assert secret not in blob
    assert "Requested" not in band(page).split("</details>")[0].split(">vaultwarden<", 1)[1].split("</div>", 1)[0]


def test_flash_ignores_junk_and_bad_names_never_500(env):
    with env() as client:
        b = band(client.get("/server?flash=requested&c=<script>").text)
        assert "Update requested" not in b and "<script>" not in b
        assert client.get("/server/updates/bad name!/run?step=confirm").status_code == 404
        assert client.get("/server/updates/vaultwarden/run", follow_redirects=False).status_code == 303
        assert client.post("/server/updates/ghost/ignore").status_code == 409


def test_updates_band_without_a_wud_snapshot_still_renders(env, tmp_path):
    client = env()
    (tmp_path / "snaps" / "wud.json").unlink()
    with client:
        r = client.get("/server")
        p = client.post("/server/updates/vaultwarden/run", follow_redirects=False)
    assert r.status_code == 200 and "Not connected" in band(r.text)
    assert p.status_code == 409 and env.calls == []
