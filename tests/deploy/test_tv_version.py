"""Joey TV WP-B8 step 3 helpers (deploy/tv_version.py): the version.json the release job generates, the APK secret
scan, the cut-date typo guard and the CLI the workflow calls. Synthetic APKs (plain zips) and tmp repos only."""
import json
import sys
import zipfile
from datetime import date
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "deploy"))
import tv_version  # noqa: E402

VERSION = "versionName=1.4.0\nversionCode=2026110302\nminVersionCode=2026102101\n"


def _repo(tmp_path, version=VERSION, notes="Faster start-up.\n"):
    (tmp_path / "tv").mkdir(parents=True)
    (tmp_path / "tv" / "VERSION").write_text(version, encoding="utf-8")
    (tmp_path / "tv" / "NOTES.txt").write_text(notes, encoding="utf-8")
    return tmp_path


def _apk(path: Path, entries: dict) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return path


CLEAN = {"AndroidManifest.xml": b"\x03\x00manifest", "classes.dex": b"dex\n035\x00https://media.joeyhome.net",
         "res/drawable/banner.png": b"\x89PNG eyJhbGciOiJIUzI1NiIsInR5cCI6 (images are not scanned)"}


def test_meta_writes_the_version_json_contract(tmp_path):
    repo = _repo(tmp_path)
    apk = _apk(tmp_path / "joey-media-1.4.0-2026110302.apk", CLEAN)
    out = tmp_path / "version.json"
    rc = tv_version.main(["--repo", str(repo), "meta", "--apk", str(apk), "--out", str(out),
                          "--published", "2026-11-03T01:02:03Z"])
    assert rc == 0
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert list(doc) == list(tv_version.VERSION_JSON_KEYS)
    assert doc["version"] == "1.4.0" and doc["versionCode"] == 2026110302
    assert doc["min_version"] == 2026102101 and isinstance(doc["min_version"], int)   # integer, DECISIONS F
    assert doc["url"] == "joey-media-1.4.0-2026110302.apk"                              # relative
    assert doc["sha256"] == tv_version.sha256_file(apk) and doc["size"] == apk.stat().st_size
    assert doc["notes"] == "Faster start-up." and doc["published"] == "2026-11-03T01:02:03Z"
    assert tv_version.validate_version_json(doc) == []


def test_meta_refuses_a_misnamed_apk(tmp_path, capsys):
    repo = _repo(tmp_path)
    apk = _apk(tmp_path / "app-sideload-release.apk", CLEAN)
    assert tv_version.main(["--repo", str(repo), "meta", "--apk", str(apk), "--out", str(tmp_path / "v.json")]) == 1
    assert "expected joey-media-1.4.0-2026110302.apk" in capsys.readouterr().out


def test_apk_name_and_check(tmp_path, capsys):
    repo = _repo(tmp_path)
    assert tv_version.main(["--repo", str(repo), "apk-name"]) == 0
    assert capsys.readouterr().out.strip() == "joey-media-1.4.0-2026110302.apk"
    assert tv_version.main(["--repo", str(repo), "check"]) == 0
    bad = _repo(tmp_path / "b", version=VERSION.replace("2026110302", "2026110300"))
    assert tv_version.main(["--repo", str(bad), "check"]) == 1


def test_the_real_repo_passes_check():
    assert tv_version.main(["--repo", str(REPO_ROOT), "check"]) == 0


@pytest.mark.parametrize("entries, hit", [
    ({"classes.dex": b"..eyJhIjoiYWJjIiwidCI6IjEyMyJ9.."}, "JWT/tunnel-token-shaped string"),
    ({"assets/config.json": b'{"api_key": "x"}'}, "api_key"),
    ({"classes2.dex": b"ghp_" + b"A" * 36}, "GitHub token"),
    ({"res/raw/x": b"github_pat_" + b"B" * 30}, "GitHub fine-grained token"),
    ({"classes.dex": b'MediaBrowser Token="deadbeef'}, "Jellyfin token value"),
])
def test_scan_finds_token_shaped_strings(tmp_path, entries, hit):
    apk = _apk(tmp_path / "a.apk", {**CLEAN, **entries})
    hits = tv_version.scan_apk(apk)
    assert hits and hit in hits[0]
    assert tv_version.main(["scan", str(apk)]) == 1


def test_scan_passes_a_clean_apk_and_skips_images(tmp_path):
    apk = _apk(tmp_path / "a.apk", CLEAN)
    assert tv_version.scan_apk(apk) == []
    assert tv_version.main(["scan", str(apk)]) == 0


@pytest.mark.parametrize("code, today, ok", [
    ("2026110302", date(2026, 11, 3), True),
    ("2026110402", date(2026, 11, 3), True),      # Sydney is ahead of UTC: one day of slack
    ("2026110502", date(2026, 11, 3), False),     # two days ahead = a typo
    ("2026010101", date(2026, 11, 3), True),      # old cut dates are fine (re-runs)
])
def test_cut_date_guard(code, today, ok):
    assert (tv_version.check_cut_date(code, today) is None) is ok


@pytest.mark.parametrize("mutate", [
    lambda d: d.update(url="https://media.joeyhome.net/app/joey-media-1.4.0-2026110302.apk"),   # absolute
    lambda d: d.update(url="joey-media-1.4.0-2026110399.apk"),                                   # wrong code
    lambda d: d.update(min_version="2026102101"),                                                # string, not int
    lambda d: d.update(min_version=2026110303),                                                  # above code
    lambda d: d.update(sha256="ABC"),
    lambda d: d.pop("notes"),
    lambda d: d.update(version="1.4"),
])
def test_version_json_validation(mutate):
    doc = {"version": "1.4.0", "versionCode": 2026110302, "min_version": 2026102101,
           "url": "joey-media-1.4.0-2026110302.apk", "sha256": "a" * 64, "notes": "n", "size": 10,
           "published": "2026-11-03T01:02:03Z"}
    assert tv_version.validate_version_json(doc) == []
    mutate(doc)
    assert tv_version.validate_version_json(doc)
