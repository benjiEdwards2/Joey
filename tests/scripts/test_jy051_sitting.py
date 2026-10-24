"""JY-051: scripts/jy051_sitting.py - logcat parsing, pasted web results, the matrix cells and file, the adb lines.
No network, no adb, no gh: every command here runs with --dry-run or on pure helpers."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import jy051_sitting as js  # noqa: E402
import player_study as ps  # noqa: E402

ID1 = ps.TEST_ITEMS[0][0]
ID7 = ps.TEST_ITEMS[6][0]


def run(engine="T2", n=1, k=1, ok=True, ms=1500, device="TV", network="LAN", **kw):
    rec = {"kind": "run", "device": device, "network": network, "engine": engine, "n": n, "id": ps.TEST_ITEMS[n - 1][0],
           "run": k, "ok": ok, "err": "" if ok else "ERROR_CODE_DECODING_FAILED", "ms_frame": ms if ok else None,
           "ms_playing": ms + 20 if ok else None}
    rec.update(kw)
    return rec


@pytest.fixture(autouse=True)
def no_subprocess(monkeypatch, tmp_path):
    monkeypatch.setenv("JY051_DIR", str(tmp_path / "state"))
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("no subprocess in tests"))
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("no subprocess in tests"))


# ---------------------------------------------------------------- logcat and pasted results

def test_parse_logcat_keeps_only_jy051_json():
    lines = [
        "1729730000.123  4321  4321 I JY051   : " + json.dumps(run()),
        "1729730000.200  4321  4321 I JY051   : not json",
        "1729730000.300  4321  4321 I Other   : {\"kind\": \"run\"}",
        "--------- beginning of main",
        "1729730001.000  4321  4321 I JY051   : {\"kind\":\"done\",\"engine\":\"T1\"}\r\n",
    ]
    recs = js.parse_logcat(lines)
    assert [r["kind"] for r in recs] == ["run", "done"]
    assert recs[0]["ms_frame"] == 1500


def test_final_done_is_the_one_after_sign_out():
    assert not js.is_final_done({"kind": "done", "engine": "T1"})          # the page's T1 half
    assert not js.is_final_done({"kind": "done", "phase": "matrix"})       # matrix half, resume test may follow
    assert js.is_final_done({"kind": "done", "aborted": False})
    assert not js.is_final_done({"kind": "run"})


def test_extract_web_finds_blobs_in_pasted_text():
    blob = {"v": 1, "kind": "jy051-web", "session": {"device": "Phone"}, "runs": [run(device="Phone", engine="W1")]}
    text = "here you go:\n" + json.dumps(blob) + "\nand again " + json.dumps(blob) + " {not json"
    found = js.extract_web(text)
    assert len(found) == 2 and found[0]["session"]["device"] == "Phone"
    assert js.extract_web("nothing here") == []


def test_clean_record_checks_ids_and_strips_urls():
    good = run(err="hls networkError https://jellyfin.example:8443/videos/x?ApiKey=abc")
    out = js.clean_record(good)
    assert "https://" not in out["err"] and "<url>" in out["err"]
    assert js.clean_record(dict(run(), id="f" * 32)) is None            # id does not match the test file
    assert js.clean_record(dict(run(), n=13)) is None
    assert js.clean_record({"kind": "session", "device": "TV"}) is None
    assert js.clean_record({"kind": "resume_stop", "n": 1, "id": ID1, "position_s": 300})["position_s"] == 300


def test_dedupe_drops_repeated_pastes():
    a, b = run(k=1), run(k=2)
    assert js.dedupe([a, b, dict(a)]) == [a, b]


# ---------------------------------------------------------------- matrix cells

def test_candidates_map_device_and_engine():
    assert js.candidate(run(device="PC", engine="W2")) == "W2"
    assert js.candidate(run(device="Phone", engine="W1")) == "P1-W1"
    assert js.candidate(run(device="TV", engine="W1")) == "T1-W1"
    assert js.candidate(run(device="TV", engine="T2F")) == "T2F"
    assert js.candidate(run(device="PC", engine="T2")) is None


def test_aggregate_median_counts_ok_runs_only():
    recs = [run(k=1, ms=1000), run(k=2, ms=3000), run(k=3, ok=False), run(k=1, n=7, ms=6000, method="Remux+Audio",
                                                                        audio="unsupported audio/vnd.dts")]
    cells = js.aggregate(recs)
    c = cells[("TV", "T2", "LAN", 1)]
    assert c["runs"] == 3 and c["ok"] == 2 and c["median_ms"] == 2000
    assert js.cell_text(c, "LAN") == "2.0 s (2/3)"
    c7 = cells[("TV", "T2", "LAN", 7)]
    assert js.cell_text(c7, "LAN") == "6.0 s remux+A no-audio OVER"
    assert "OVER" not in js.cell_text(c7, "Remote")                       # 10 s budget remotely


def test_failed_cell_and_verdicts():
    cells = js.aggregate([run(ok=False), run(k=2, n=6, verdict="no"), run(k=1, n=8, verdict="yes", ms=900)])
    assert js.cell_text(cells[("TV", "T2", "LAN", 1)], "LAN").startswith("FAIL ERROR_CODE_DECODING_FAILED")
    assert js.cell_text(cells[("TV", "T2", "LAN", 6)], "LAN").endswith("BAD-eye")
    assert js.cell_text(cells[("TV", "T2", "LAN", 8)], "LAN") == "0.9 s ok-eye"
    # the page's playing-event fallback counts when rVFC is missing
    assert js.first_frame({"ms_frame": None, "ms_playing": 1234}) == 1234.0


def test_render_matrix_and_resume():
    recs = [run(device="PC", engine="W1", ms=800), run(device="PC", engine="W2", ms=2400, method="Remux"),
            run(device="Phone", engine="W2", network="Remote", ms=7000),
            {"kind": "resume_stop", "device": "TV", "n": 1, "id": ID1, "position_s": 301},
            {"kind": "resume", "device": "Phone", "network": "LAN", "n": 1, "id": ID1, "saved_s": 300,
             "started_s": 300, "ms_playing": 900}]
    sessions = [{"device": "TV", "model": "Smart TV", "sdk": 34, "webview": "com.google.android.webview 130",
                 "video": ["h264", "hevc"], "audio": ["aac", "ac3"], "audio_ffmpeg": ["aac", "dts"], "hdr_types": [2]},
                {"device": "PC", "network": "LAN", "ua": "Mozilla/5.0", "caps": {"mp4": {"h264": True}, "mkv": False}}]
    md = js.render_matrix(recs, sessions, "2026-10-24 12:00")
    assert "| # | Tests | W1 LAN | W2 LAN |" in md
    assert "| P1-W2 Remote |" in md and "7.0 s" in md
    assert "### TV\nNot measured yet." in md
    assert "TV stopped row 1 at 5:01." in md and "PASS" in md
    assert "Smart TV" in md and "HDR display no" in md
    for n in range(1, 13):
        assert f"| {n} | " in md


def test_splice_keeps_text_outside_markers():
    doc = f"head\n{js.START}\nold\n{js.END}\ntail\n"
    out = js.splice(doc, "new body")
    assert out == f"head\n{js.START}\nnew body\n{js.END}\ntail\n"
    with pytest.raises(SystemExit):
        js.splice("no markers", "x")
    with pytest.raises(SystemExit):
        js.splice(f"{js.END}\n{js.START}", "x")


def test_matrix_template_has_the_markers():
    path = REPO_ROOT / "docs" / "specs" / "JY-051-matrix.md"
    if not path.exists():
        pytest.skip("docs/ is not in the gate image")
    js.splice(path.read_text(encoding="utf-8"), "x")


# ---------------------------------------------------------------- adb lines and dry runs

def test_am_start_carries_settings_and_no_credential():
    argv = js.am_start({"engines": "T1,T2", "runs": 3, "h_all": False, "network": "LAN"})
    assert argv[:7] == ["shell", "am", "start", "-S", "-W", "-n", "net.joeyhome.study/.StudyActivity"]
    assert ["--es", "engines", "T1,T2"] == argv[7:10] and ["--ei", "runs", "3"] == argv[10:13]
    assert ["--ez", "h_all", "false"] == argv[13:16]
    assert "token" not in " ".join(argv)
    with pytest.raises(SystemExit):
        js.am_start({"rows": "1; reboot"})


def test_dry_run_tv_prints_adb_lines(capsys):
    assert js.main(["tv", "--dry-run", "--serial", "1.2.3.4:5555", "--rows", "1,7"]) == 0
    out = capsys.readouterr().out
    assert "DRY adb shell am start -S -W -n net.joeyhome.study/.StudyActivity" in out
    assert "--es rows 1,7" in out and "--es look 6,7,8,11,12" in out
    assert "sign in as joeytest" in out


def test_dry_run_install_fetch_uninstall(capsys):
    assert js.main(["install", "--dry-run"]) == 0
    assert js.main(["fetch-apk", "--dry-run"]) == 0
    assert js.main(["uninstall", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "DRY adb uninstall net.joeyhome.study" in out and "DRY adb install" in out
    assert "gh run download -R benjiEdwards2/Joey <latest> -n joey-study-apk" in out


def test_ingest_and_matrix_end_to_end(tmp_path, capsys):
    blob = {"v": 1, "kind": "jy051-web", "session": {"device": "PC", "network": "LAN", "ua": "x", "caps": {}},
            "runs": [run(device="PC", engine="W1", ms=700), run(device="PC", engine="W1", k=2, ms=900),
                     dict(run(device="PC", engine="W2"), id="0" * 32)]}
    paste = tmp_path / "paste.txt"
    paste.write_text("results: " + json.dumps(blob), encoding="utf-8")
    assert js.main(["ingest", str(paste)]) == 0
    tv = js.state_dir() / "tv-matrix-1.jsonl"
    tv.write_text("\n".join(json.dumps(r) for r in [{"kind": "session", "device": "TV", "model": "M"},
                                                   run(engine="T2F", n=7, ms=4000)]), encoding="utf-8")
    out = tmp_path / "matrix.md"
    out.write_text(f"# m\n{js.START}\nold\n{js.END}\nnotes\n", encoding="utf-8")
    assert js.main(["matrix", "--out", str(out)]) == 0
    md = out.read_text(encoding="utf-8")
    assert "0.8 s" in md and "4.0 s" in md and md.endswith(f"{js.END}\nnotes\n")
    assert "from 3 records" in md                                        # the bad-id run was dropped
    with pytest.raises(SystemExit):
        js.main(["ingest", str(out)])                                     # a file without results is refused


def test_bad_arguments_refused():
    with pytest.raises(SystemExit):
        js.main(["tv", "--dry-run", "--engines", "T9"])
    with pytest.raises(SystemExit):
        js.main(["tv", "--dry-run", "--rows", "1;2"])
    with pytest.raises(SystemExit):
        js.main(["ingest", "--dry-run"])
