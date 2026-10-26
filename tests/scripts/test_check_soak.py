"""JY-210: scripts/check_soak.py - the read-only soak check over a copy of _runner_history.jsonl. No network, no NAS."""
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import check_soak  # noqa: E402

END = datetime(2026, 10, 26, 6, 0, tzinfo=timezone.utc)
ALL = ["arr", "gcal", "jellyfin", "money"]


def _iso(at):
    return at.strftime("%Y-%m-%dT%H:%M:%SZ")


def _history(path, hours=24, hourly_every=1, status=None, drop=(), partial_every_min=None):
    """One hourly line per hour (oldest first); `status` maps id -> status (default ok). Optional 2-minute partial lines
    for `arr` (tagged only) so the fast loop does not count as an hourly sweep."""
    status = status or {}
    rows = []
    for h in range(0, hours, hourly_every):
        at = END - timedelta(hours=h)
        res = {cid: {"status": status.get(cid, "ok"), "consecutive_failures": 0, "error": None}
               for cid in ALL if (h, cid) not in drop}
        rows.append({"ran_at": _iso(at), "results": res, "except": ["arr"]})
    if partial_every_min:
        for m in range(0, hours * 60, partial_every_min):
            rows.append({"ran_at": _iso(END - timedelta(minutes=m, seconds=30)),
                         "results": {"arr": {"status": "ok", "consecutive_failures": 0, "error": None}}, "only": ["arr"]})
    rows.sort(key=lambda r: r["ran_at"])
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return path


def test_a_clean_day_passes_and_prints_one_line_per_connector(tmp_path, capsys):
    h = _history(tmp_path / "h.jsonl", hours=25)
    assert check_soak.main([str(h)]) == 0
    out = capsys.readouterr().out
    assert out.count("PASS  ") == len(ALL) + 1  # four connectors + the summary line
    assert "money" in out and "exempt from the ok count" in out
    assert re.search(r"PASS  soak: 25 hourly sweeps", out)


def test_a_connector_with_too_few_ok_beats_fails(tmp_path, capsys):
    # gcal errors on 5 of 24 hourly sweeps -> 19 ok < 22
    h = _history(tmp_path / "h.jsonl", hours=25)
    rows = [json.loads(x) for x in h.read_text().splitlines()]
    for r in rows[-6:-1]:
        r["results"]["gcal"]["status"] = "error"
    h.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    assert check_soak.main([str(h)]) == 1
    out = capsys.readouterr().out
    assert "FAIL  gcal" in out and "ok < 22" in out and "FAIL  soak" in out


def test_error_in_every_result_fails_even_for_the_exempt_id(tmp_path, capsys):
    h = _history(tmp_path / "h.jsonl", hours=25, status={"money": "error", "arr": "error"})
    assert check_soak.main([str(h)]) == 1
    out = capsys.readouterr().out
    assert "FAIL  money" in out and "error in every result" in out and "FAIL  arr" in out


def test_the_exempt_id_is_not_held_to_the_ok_count_but_must_not_report_error(tmp_path, capsys):
    # money reports on only 3 sweeps, all ok: PASS (an empty inbox is normal)
    h = _history(tmp_path / "h.jsonl", hours=25, drop=[(i, "money") for i in range(3, 25)])
    assert check_soak.main([str(h)]) == 0
    # one error among its ok results: FAIL
    rows = [json.loads(x) for x in h.read_text().splitlines()]
    rows[-1]["results"]["money"]["status"] = "error"
    h.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    assert check_soak.main([str(h)]) == 1
    assert "reported error 1x" in capsys.readouterr().out


def test_too_few_hourly_sweeps_fail_and_the_fast_loop_does_not_count(tmp_path, capsys):
    h = _history(tmp_path / "h.jsonl", hours=25, hourly_every=2, partial_every_min=2)  # ~12 hourly + 720 partial lines
    assert check_soak.main([str(h)]) == 1
    out = capsys.readouterr().out
    assert "hourly sweeps < 22" in out
    assert "PASS  arr" in out  # arr has hundreds of ok results from the partial loop, so its own count is fine


def test_an_expected_id_that_never_ran_fails(tmp_path, capsys):
    h = _history(tmp_path / "h.jsonl", hours=25)
    assert check_soak.main([str(h), "--expect", "arr,gcal,jellyfin,uptime_kuma"]) == 1
    assert "FAIL  uptime_kuma" in capsys.readouterr().out


def test_lines_outside_the_window_do_not_count(tmp_path):
    h = _history(tmp_path / "h.jsonl", hours=60)  # 60 hourly lines; only the newest 24 h are in the window
    lines, _ = check_soak.load_history(h)
    res = check_soak.check(lines, END)
    assert res["all_sweeps"] == 25 and res["ok"]
    res = check_soak.check(lines, END, hours=10)
    assert res["all_sweeps"] == 11 and not res["ok"]


def test_malformed_lines_are_skipped_and_counted_and_an_empty_file_is_exit_2(tmp_path, capsys):
    h = _history(tmp_path / "h.jsonl", hours=25)
    h.write_text(h.read_text() + "not json\n{\"ran_at\": \"bad\", \"results\": {}}\n[1]\n", encoding="utf-8")
    assert check_soak.main([str(h)]) == 0
    assert "3 bad line(s) skipped" in capsys.readouterr().out
    empty = tmp_path / "e.jsonl"
    empty.write_text("junk\n", encoding="utf-8")
    assert check_soak.main([str(empty)]) == 2
    assert check_soak.main([str(tmp_path / "missing.jsonl")]) == 2
    assert "ERROR" in capsys.readouterr().out


def test_snapshots_are_checked_for_age_and_error_and_nothing_is_written(tmp_path, capsys):
    h = _history(tmp_path / "h.jsonl", hours=25)
    snaps = tmp_path / "snaps"
    snaps.mkdir()
    (snaps / "arr.json").write_text(json.dumps({"status": "ok", "updated_at": _iso(END - timedelta(minutes=5))}))
    (snaps / "gcal.json").write_text(json.dumps({"status": "ok", "updated_at": _iso(END - timedelta(hours=30))}))
    (snaps / "_runner.json").write_text("{}")   # heartbeat: skipped
    (snaps / "jellyfin.json").write_text("{broken")
    before = sorted((p.name, p.stat().st_size) for p in tmp_path.rglob("*") if p.is_file())
    assert check_soak.main([str(h), "--snapshots", str(snaps)]) == 1
    out = capsys.readouterr().out
    assert "PASS  snapshot arr" in out and "FAIL  snapshot gcal" in out and "updated 30.0 h ago" in out
    assert "FAIL  snapshot jellyfin" in out and "unreadable" in out and "_runner" not in out
    assert sorted((p.name, p.stat().st_size) for p in tmp_path.rglob("*") if p.is_file()) == before  # read only


def test_the_script_has_no_write_calls():
    src = (REPO_ROOT / "scripts" / "check_soak.py").read_text(encoding="utf-8")
    for call in (".write_text(", ".write_bytes(", "open(", "subprocess", "urllib", "socket", "os.remove", "unlink("):
        assert call not in src, call


def test_it_reads_the_line_shape_run_all_really_writes(tmp_path):
    """The runner's own history line (run_all._write_heartbeat) parses: ran_at, results with status, `except` tag."""
    pytest.importorskip("connectors.run_all")
    from connectors import run_all
    snaps = tmp_path / "snaps"
    snaps.mkdir()
    sweep = {"ran_at": _iso(END), "results": {"arr": {"status": "ok", "consecutive_failures": 0, "error": None}},
             "except": ["jellyfin"]}
    import os
    os.environ["SNAPSHOT_DIR"] = str(snaps)
    try:
        run_all._write_heartbeat(sweep, {"arr": 12}, 34)
    finally:
        os.environ.pop("SNAPSHOT_DIR", None)
    lines, skipped = check_soak.load_history(snaps / run_all.HISTORY_NAME)
    assert skipped == 0 and len(lines) == 1 and lines[0]["results"]["arr"]["status"] == "ok" and not lines[0]["only"]


# ---- the runbook the docs name (JY-210) ----

RUNBOOK = REPO_ROOT / "docs" / "runbook.md"


def test_the_runbook_exists_is_indexed_and_its_links_and_paths_resolve():
    if not RUNBOOK.exists():  # the gate image keeps docs/ out (.dockerignore); this runs on the laptop and in CI
        pytest.skip("docs/ is not in the gate image")
    text = RUNBOOK.read_text(encoding="utf-8")
    assert "runbook.md" in (REPO_ROOT / "docs" / "README.md").read_text(encoding="utf-8")
    assert "docs/runbook.md" in (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    anchors = {re.sub(r"[^a-z0-9 -]", "", h.lower()).strip().replace(" ", "-")
               for h in re.findall(r"^#{2,3} (.+)$", text, flags=re.M)}
    for target in re.findall(r"\]\(#([^)]+)\)", text):
        assert target in anchors, target
    for path in re.findall(r"`((?:docs|deploy|scripts|hub|tests|nas_scripts)/[A-Za-z0-9_./-]+\.(?:md|py|sh|yml))`", text):
        if path.startswith("nas_scripts/"):  # lives in the project folder, not this repo
            continue
        assert (REPO_ROOT / path).exists(), path
    for section in ("Deploy", "Rollback", "Preview slot", "Close-out", "TV app release",
                    "NAS power schedule and the deploy window", "Soak check", "Common failures and fixes"):
        assert f"## {section}" in text, section
