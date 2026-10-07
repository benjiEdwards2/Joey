"""BOM radar loop (2026-10-06) — rides the open_meteo connector as an extra fetch step.

Since the RADAR SUPERSESSION (2026-10-07) the step is gated OFF by default (Windy is the
radar surface); these tests set RADAR_LOOP=1 to keep exercising the parked code path.

ftplib is replaced by an in-memory fake throughout; the suite never reaches
ftp.bom.gov.au (conftest refuses any unmocked FTP connection).
"""

import ftplib
import json

import jsonschema
import pytest
import requests

from connectors import stubs
from connectors.stubs import OpenMeteo, prune_radar_dir, radar_frame_stamps
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

PNG = b"\x89PNG\r\n\x1a\n"
FIXTURE_RAW = json.loads((REPO_ROOT / "connectors" / "fixtures" / "open_meteo" / "raw.json")
                         .read_text(encoding="utf-8"))
DATA_SCHEMA = json.loads((REPO_ROOT / "connectors" / "schema" / "data" / "open_meteo.schema.json")
                         .read_text(encoding="utf-8"))

# As listed by the real server (NLST returns full paths), other stations mixed in.
STAMPS = ["202610060019", "202610060024", "202610060029", "202610060034",
          "202610060039", "202610060044", "202610060049", "202610060054"]
LISTING = ([f"/anon/gen/radar/IDR023.T.{s}.png" for s in reversed(STAMPS)]
           + ["/anon/gen/radar/IDR023.gif", "/anon/gen/radar/IDR022.T.202610060059.png",
              "/anon/gen/radar/IDR021.T.202610060059.png", "/anon/gen/radar/IDR023.T.bad.png"])


class FakeFTP:
    """Minimal ftplib.FTP stand-in; `files` maps path -> bytes, RETRs are recorded."""
    files: dict = {}
    listing: list = []
    seen: list = []
    fail_on: str | None = None

    def __init__(self, host, timeout=None):
        FakeFTP.seen.append(("connect", host, timeout))

    def login(self):
        FakeFTP.seen.append(("login",))

    def set_pasv(self, val):
        FakeFTP.seen.append(("pasv", val))

    def nlst(self, path):
        FakeFTP.seen.append(("nlst", path))
        return list(FakeFTP.listing)

    def retrbinary(self, cmd, callback):
        path = cmd.split(" ", 1)[1]
        FakeFTP.seen.append(("retr", path))
        if FakeFTP.fail_on and FakeFTP.fail_on in path:
            raise ftplib.error_perm("550 gone")
        callback(FakeFTP.files.get(path, PNG + path.encode()))

    def quit(self):
        FakeFTP.seen.append(("quit",))


@pytest.fixture()
def live(monkeypatch, snapshots):
    monkeypatch.setenv("CONNECTOR_MODE", "live")
    monkeypatch.setenv("RADAR_LOOP", "1")
    monkeypatch.setenv("WEATHER_LAT", "-37.84")
    monkeypatch.setenv("WEATHER_LON", "144.88")

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return json.loads(json.dumps(FIXTURE_RAW))

    monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResponse())
    FakeFTP.files, FakeFTP.listing, FakeFTP.seen, FakeFTP.fail_on = {}, list(LISTING), [], None
    monkeypatch.setattr(ftplib, "FTP", FakeFTP)
    return snapshots


def _validate(data):
    jsonschema.Draft202012Validator(DATA_SCHEMA).validate(data)


# ---- filename parsing + latest-6 selection --------------------------------------------


def test_stamps_pick_the_latest_six_for_the_station_oldest_first():
    assert radar_frame_stamps(LISTING, "IDR023", 6) == STAMPS[-6:]


def test_stamps_accept_bare_names_and_ignore_junk():
    names = ["IDR023.T.202610060054.png", "  IDR023.T.202610060049.png\n", "IDR023.gif",
             "IDR0232.T.202610060059.png", "IDR023.T.20261006005.png", "readme.txt"]
    assert radar_frame_stamps(names, "IDR023", 6) == ["202610060049", "202610060054"]
    assert radar_frame_stamps([], "IDR023", 6) == []


# ---- the live run: shape, storage, schema ---------------------------------------------


def test_live_run_stores_layers_and_frames_and_emits_the_radar_block(live):
    env = OpenMeteo().run()
    assert env["status"] == "ok"
    radar = env["data"]["radar"]
    assert radar["station"] == "IDR023" and radar["fetched_ok"] is True
    assert radar["layers"] == ["layer_background.png", "layer_topography.png",
                               "layer_locations.png", "layer_range.png"]
    assert [f["file"] for f in radar["frames"]] == [f"frame_{s}.png" for s in STAMPS[-6:]]
    assert radar["frames"][0]["time_iso"] == "2026-10-06T00:29:00+00:00"
    assert env["data"]["summary"] == "18.3 °C · light rain"      # weather untouched
    _validate(env["data"])

    rdir = live / "radar"
    on_disk = sorted(p.name for p in rdir.iterdir())
    assert on_disk == sorted(radar["layers"] + [f["file"] for f in radar["frames"]])
    assert (rdir / "frame_202610060054.png").read_bytes() == \
        PNG + b"/anon/gen/radar/IDR023.T.202610060054.png"
    assert (rdir / "layer_range.png").read_bytes() == \
        PNG + b"/anon/gen/radar_transparencies/IDR023.range.png"
    # anonymous, passive, 10 s timeout, and the connection is closed
    assert ("connect", "ftp.bom.gov.au", 10) in FakeFTP.seen
    assert ("login",) in FakeFTP.seen and ("pasv", True) in FakeFTP.seen
    assert FakeFTP.seen[-1] == ("quit",)


def test_second_run_prunes_frames_no_envelope_references(live):
    OpenMeteo().run()
    rdir = live / "radar"
    (rdir / "stray.png").write_bytes(PNG)
    (rdir / ".frame_x.png.1.2.tmp").write_bytes(PNG)

    FakeFTP.listing = LISTING + ["/anon/gen/radar/IDR023.T.202610060059.png",
                                 "/anon/gen/radar/IDR023.T.202610060104.png"]
    OpenMeteo().run()       # new set = 0039..0104; the previous envelope's 0029..0054 kept
    names = {p.name for p in rdir.iterdir()}
    assert "stray.png" not in names and ".frame_x.png.1.2.tmp" not in names
    assert "frame_202610060029.png" in names and "frame_202610060104.png" in names

    OpenMeteo().run()       # same set again — now 0029/0034 are referenced by nothing
    names = {p.name for p in rdir.iterdir()}
    assert "frame_202610060029.png" not in names and "frame_202610060034.png" not in names
    assert len([n for n in names if n.startswith("frame_")]) == 6
    assert len([n for n in names if n.startswith("layer_")]) == 4


def test_prune_keeps_only_the_named_files(tmp_path):
    for n in ("a.png", "b.png", "c.tmp"):
        (tmp_path / n).write_bytes(b"x")
    assert prune_radar_dir(tmp_path, {"a.png"}) == ["b.png", "c.tmp"]
    assert [p.name for p in tmp_path.iterdir()] == ["a.png"]


# ---- failure isolation: radar trouble never fails the weather -------------------------


@pytest.mark.parametrize("break_it", ["connect", "listing_empty", "frame_missing", "not_png"])
def test_radar_failure_leaves_weather_ok_with_radar_absent(live, monkeypatch, break_it):
    if break_it == "connect":
        class Down:
            def __init__(self, *a, **k):
                raise TimeoutError("timed out")
        monkeypatch.setattr(ftplib, "FTP", Down)
    elif break_it == "listing_empty":
        FakeFTP.listing = ["/anon/gen/radar/IDR022.T.202610060059.png"]
    elif break_it == "frame_missing":
        FakeFTP.fail_on = "IDR023.T.202610060054"
    else:
        FakeFTP.files = {"/anon/gen/radar_transparencies/IDR023.topography.png": b"<html>"}

    env = OpenMeteo().run()
    assert env["status"] == "ok" and env["error"] is None
    assert env["data"]["summary"] == "18.3 °C · light rain"
    assert "radar" not in env["data"]
    _validate(env["data"])
    assert not (live / "radar").exists() or not any((live / "radar").iterdir())


def test_radar_failure_after_success_keeps_last_frames_marked_stale(live, monkeypatch):
    first = OpenMeteo().run()["data"]["radar"]
    FakeFTP.fail_on = "IDR023.T."          # BOM drops the frames mid-pull
    env = OpenMeteo().run()
    assert env["status"] == "ok"
    radar = env["data"]["radar"]
    assert radar["fetched_ok"] is False
    assert radar["frames"] == first["frames"] and radar["layers"] == first["layers"]
    _validate(env["data"])
    for f in radar["frames"]:                # nothing was written or pruned by the failed pull
        assert (live / "radar" / f["file"]).is_file()


def test_unmocked_ftp_is_refused_and_isolated(monkeypatch, snapshots):
    """The conftest guard: the existing live-fetch test path stays offline and ok."""
    monkeypatch.setenv("CONNECTOR_MODE", "live")
    monkeypatch.setenv("RADAR_LOOP", "1")
    monkeypatch.setenv("WEATHER_LAT", "-37.84")
    monkeypatch.setenv("WEATHER_LON", "144.88")

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return json.loads(json.dumps(FIXTURE_RAW))

    monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResponse())
    env = OpenMeteo().run()
    assert env["status"] == "ok" and "radar" not in env["data"]


@pytest.mark.parametrize("value", [None, "0", "true", ""])
def test_radar_step_is_off_unless_radar_loop_is_1(live, monkeypatch, value):
    """RADAR SUPERSESSION (2026-10-07): without RADAR_LOOP=1 the BOM step never runs."""
    if value is None:
        monkeypatch.delenv("RADAR_LOOP", raising=False)
    else:
        monkeypatch.setenv("RADAR_LOOP", value)
    monkeypatch.setattr(stubs, "fetch_radar", lambda c: pytest.fail("radar step ran while gated off"))
    env = OpenMeteo().run()
    assert env["status"] == "ok" and env["error"] is None
    assert env["data"]["summary"] == "18.3 °C · light rain"
    assert "radar" not in env["data"]
    assert FakeFTP.seen == []                       # no FTP connection attempted
    assert not (live / "radar").exists()
    _validate(env["data"])


def test_fixture_mode_never_runs_the_radar_step(snapshots, monkeypatch):
    monkeypatch.setattr(stubs, "fetch_radar", lambda c: pytest.fail("radar in fixture mode"))
    env = OpenMeteo().run()
    assert env["status"] == "ok" and "radar" not in env["data"]
    assert not (snapshots / "radar").exists()


def test_schema_rejects_a_frame_name_that_could_escape_the_dir():
    bad = {"summary": "x", "now_c": 1, "condition_text": "x", "today_min_c": 0,
           "today_max_c": 1, "rain_prob_pct": 0,
           "radar": {"station": "IDR023", "fetched_ok": True, "layers": [],
                     "frames": [{"file": "../open_meteo.json", "time_iso": "2026-10-06T00:00"}]}}
    with pytest.raises(jsonschema.ValidationError):
        _validate(bad)
