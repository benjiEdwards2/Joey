"""WP-L1 (2026-10-21): "Open qBittorrent ↗" on Activity > Downloads and "Open Seerr ↗" on Activity > Requests - the
Health row's logo + gated hostname, read from the media_status snapshot."""
import json
import re
from pathlib import Path

import pytest

from hub import shell
from tests.hub.conftest import app_with, main_raw as main_of
from tests.hub.helpers import make_area, make_tile, write_envelope

SEERR = json.loads((Path(__file__).resolve().parents[2] / "config" / "sample_snapshots" / "jellyseerr.json")
                   .read_text(encoding="utf-8"))["data"]
QB = {"summary": "x", "secondary": "", "active": [], "finished": [], "seeding": 0,
      "totals": {"dl_bps": 0, "up_bps": 0, "dl_text": "0 B/s", "up_text": "0 B/s"}}
APPS = [
    {"id": "qbittorrent", "name": "qBittorrent", "href": "http://192.168.1.10:8080",
     "up": True, "status_text": "Up", "note": None},
    {"id": "jellyseerr", "name": "Seerr", "href": "http://192.168.1.10:5055",
     "up": True, "status_text": "Up", "note": None},
]
PAGES = (("/media/downloads", "qbittorrent", QB, "qbittorrent", "qBittorrent"),
         ("/media/requests", "jellyseerr", SEERR, "jellyseerr", "Seerr"))


@pytest.fixture()
def build(tmp_path, monkeypatch):
    area = make_area("alpha", "dl-t", snapshot="qbittorrent", stale_after_minutes=10, detail="/media/downloads")
    area["tiles"].append(make_tile("req-t", snapshot="jellyseerr", stale_after_minutes=180, detail="/media/requests"))
    area["tiles"].append(make_tile("apps-t", snapshot="media_status", stale_after_minutes=10, detail="/media/apps"))
    factory = app_with(tmp_path, monkeypatch, area)
    snaps = tmp_path / "snaps"

    def go(page_id, page_data, apps=APPS, gated=None):
        write_envelope(snaps, page_id, age_minutes=1, data=page_data)
        if apps is not None:
            write_envelope(snaps, "media_status", age_minutes=1, data={"summary": "x", "apps": apps})
        client = factory(snaps)
        return client

    return go


@pytest.mark.parametrize("path,page_id,data,app_id,name", PAGES)
def test_page_shows_the_app_link_with_logo_and_lan_word(build, path, page_id, data, app_id, name):
    with build(page_id, data) as client:
        body = main_of(client.get(path).text)
    m = re.search(r'<a class="btn btn-glass btn-sm applink" href="([^"]+)" target="_blank" rel="noopener">(.*?)</a>',
                  body, re.S)
    assert m, "link missing"
    assert m.group(1) == dict((a["id"], a["href"]) for a in APPS)[app_id]
    assert re.search(rf'<img class="svc-logo" src="/static/svc/{app_id}\.svg\?v=[0-9a-f]+" alt="" width="20" height="20">',
                     m.group(2))
    assert f"Open {name} ↗" in m.group(2) and ">LAN<" in m.group(2)


@pytest.mark.parametrize("path,page_id,data,app_id,name", PAGES)
def test_gated_hostname_wins_and_drops_the_lan_word(build, path, page_id, data, app_id, name):
    with build(page_id, data) as client:
        shell.registry.gated_hrefs = {app_id: "https://gated.example.invalid"}
        body = main_of(client.get(path).text)
    m = re.search(r'<a class="btn btn-glass btn-sm applink" href="([^"]+)" target="_blank" rel="noopener">(.*?)</a>',
                  body, re.S)
    assert m.group(1) == "https://gated.example.invalid"
    assert ">LAN<" not in m.group(2)
    assert "192.168.1.10" not in m.group(0)


@pytest.mark.parametrize("path,page_id,data,app_id,name", PAGES)
def test_no_link_without_the_media_status_snapshot_or_the_app(build, path, page_id, data, app_id, name):
    with build(page_id, data, apps=None) as client:
        assert "applink" not in main_of(client.get(path).text)
    with build(page_id, data, apps=[a for a in APPS if a["id"] != app_id]) as client:
        assert "applink" not in main_of(client.get(path).text)
