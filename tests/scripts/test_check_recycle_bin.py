"""JY-265 phase 0: scripts/check_recycle_bin.py - the read-only recycle-bin check. No network, no NAS: the probe's
`get` seam answers from the config/mediamanagement fixtures, and ssh is faked."""
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import check_recycle_bin as crb  # noqa: E402

FIX = REPO_ROOT / "tests" / "hub" / "fixtures"
KEYS = {"RADARR_URL": "http://radarr.secret-host.invalid:7878", "RADARR_API_KEY": "r-SECRET",
        "SONARR_URL": "http://sonarr.secret-host.invalid:8989", "SONARR_API_KEY": "s-SECRET"}


def body(app):
    return json.loads((FIX / f"arr_{app}_mediamanagement.json").read_text(encoding="utf-8"))["body"]


def fake_get(answers):
    seen = []

    def get(url, key):
        seen.append((url, key))
        app = "radarr" if "radarr" in url else "sonarr"
        status, b = answers[app]
        if isinstance(status, type) and issubclass(status, Exception):
            raise status(f"refused: {url} key={key}")
        return status, b
    return get, seen


def test_the_probe_reads_one_get_per_app_and_reports_path_and_days(monkeypatch):
    for k, v in KEYS.items():
        monkeypatch.setenv(k, v)
    get, seen = fake_get({"radarr": (200, body("radarr")), "sonarr": (200, body("sonarr"))})
    rows = crb.probe(get)
    assert [u for u, _ in seen] == [KEYS["RADARR_URL"] + "/api/v3/config/mediamanagement",
                                    KEYS["SONARR_URL"] + "/api/v3/config/mediamanagement"]
    assert rows == [{"app": "radarr", "answered": True, "set": True, "path": "/data/recycle-bin/radarr", "days": 7, "why": ""},
                    {"app": "sonarr", "answered": True, "set": True, "path": "/data/recycle-bin/sonarr", "days": 7, "why": ""}]


def test_blank_bin_unconfigured_app_and_errors_are_words_without_secrets(monkeypatch, capsys):
    for k, v in KEYS.items():
        monkeypatch.setenv(k, v)
    blank = {**body("radarr"), "recycleBin": ""}
    get, _ = fake_get({"radarr": (200, blank), "sonarr": (ConnectionError, None)})
    rows = crb.probe(get)
    assert rows[0]["answered"] and not rows[0]["set"] and rows[1]["why"] == "ConnectionError"
    assert crb.report(rows) == 1
    out = capsys.readouterr().out
    assert "FAIL  Radarr: recycle bin set: no · cleanup days: 7" in out and "FAIL  Sonarr: no answer (ConnectionError)" in out
    assert "SECRET" not in out and "secret-host" not in out
    monkeypatch.delenv("SONARR_URL")
    assert crb.read_app("sonarr", get)["why"] == "not configured in the hub"
    get, _ = fake_get({"radarr": (401, None), "sonarr": (200, body("sonarr"))})
    assert crb.read_app("radarr", get)["why"] == "HTTP 401"


def test_report_pass_prints_yes_path_and_days_only(capsys):
    rows = [{"app": "radarr", "answered": True, "set": True, "path": "/data/recycle-bin/radarr", "days": 7, "why": ""},
            {"app": "sonarr", "answered": True, "set": True, "path": "/data/recycle-bin/sonarr", "days": 7, "why": ""}]
    assert crb.report(rows) == 0
    assert capsys.readouterr().out.splitlines() == [
        "PASS  Radarr: recycle bin set: yes · path: /data/recycle-bin/radarr · cleanup days: 7",
        "PASS  Sonarr: recycle bin set: yes · path: /data/recycle-bin/sonarr · cleanup days: 7",
        "PASS  recycle bin: radarr=yes, sonarr=yes"]


def test_main_pipes_itself_into_joey_hub_with_the_probe_flag(monkeypatch, capsys):
    import joey_common
    sent = {}

    def ssh_run(cmd, stdin=None, timeout=60):
        sent.update(cmd=cmd, stdin=stdin)
        rows = [{"app": a, "answered": True, "set": True, "path": f"/data/recycle-bin/{a}", "days": 7, "why": ""}
                for a in crb.APPS]
        return subprocess.CompletedProcess(cmd, 0, json.dumps(rows) + "\n", "")
    monkeypatch.setattr(joey_common, "ssh_run", ssh_run)
    assert crb.main([]) == 0
    assert sent["cmd"] == "docker exec -i joey-hub python - --probe"
    assert sent["stdin"] == (REPO_ROOT / "scripts" / "check_recycle_bin.py").read_text(encoding="utf-8")
    assert "PASS  recycle bin" in capsys.readouterr().out


def test_main_says_error_when_ssh_fails_or_the_answer_is_junk(monkeypatch, capsys):
    import joey_common

    def down(cmd, stdin=None, timeout=60):
        raise RuntimeError("ssh to the NAS failed (NAS off 22:00-07:00, or off the home LAN?): <nas>")
    monkeypatch.setattr(joey_common, "ssh_run", down)
    assert crb.main([]) == 2
    monkeypatch.setattr(joey_common, "ssh_run", lambda *a, **k: subprocess.CompletedProcess(a, 1, "Traceback", ""))
    assert crb.main([]) == 2
    assert capsys.readouterr().out.count("ERROR") == 2


def test_the_script_is_get_only():
    src = (REPO_ROOT / "scripts" / "check_recycle_bin.py").read_text(encoding="utf-8")
    assert 'method="GET"' in src
    for word in ("PUT", "POST", "DELETE", "requests.", ".write_text(", "os.remove", "unlink("):
        assert word not in src, word
