"""Joey TV WP-B8 step 1 (D-P9): tv/VERSION, tv/NOTES.txt and tv/SIGNING_CERT_SHA256 are valid release metadata.

These three files are the only tv/ files in the life-test image (.dockerignore), so this is the deploy gate's view of
the TV app version. The rules are spelled out here independently of deploy/tv_version.py (the CI/NAS helper), and the
two must agree on every case. No real clock: the gate runs on UTC, the cut date is Australia/Sydney.
"""
import re
import sys
from datetime import datetime
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "deploy"))
import tv_version  # noqa: E402

SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
CODE = re.compile(r"^20\d{6}(0[1-9]|[1-9]\d)$")


def _parse(text: str) -> dict:
    pairs = [ln.split("=", 1) for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    return {k.strip(): v.strip() for k, v in pairs}


def problems(version_text: str, notes: str) -> list[str]:
    """The step-1 rules, independent of tv_version."""
    out = []
    values = _parse(version_text)
    if sorted(values) != ["minVersionCode", "versionCode", "versionName"]:
        out.append("keys")
    if not SEMVER.match(values.get("versionName", "")):
        out.append("semver")
    for key in ("versionCode", "minVersionCode"):
        raw = values.get(key, "")
        if not CODE.match(raw):
            out.append(f"{key} format")
            continue
        try:
            datetime.strptime(raw[:8], "%Y%m%d")
        except ValueError:
            out.append(f"{key} date")
            continue
        if int(raw) > 2_100_000_000:
            out.append(f"{key} ceiling")
    codes = [values.get(k, "") for k in ("minVersionCode", "versionCode")]
    if all(CODE.match(c) for c in codes) and int(codes[0]) > int(codes[1]):
        out.append("min above code")
    if not notes.strip():
        out.append("notes empty")
    elif len(notes.strip()) > 500:
        out.append("notes long")
    return out


VERSION = (REPO_ROOT / "tv" / "VERSION").read_text(encoding="utf-8")
NOTES = (REPO_ROOT / "tv" / "NOTES.txt").read_text(encoding="utf-8")
GOOD = "versionName=1.2.3\nversionCode=2026102102\nminVersionCode=2026102101\n"


def test_the_real_version_file_is_valid():
    assert problems(VERSION, NOTES) == []
    assert tv_version.validate_version(tv_version.parse_version_text(VERSION), NOTES) == []
    assert len(VERSION.strip().splitlines()) == 3


@pytest.mark.parametrize("text, notes, why", [
    (GOOD.replace("2026102102", "2026132102"), "x", "month 13"),
    (GOOD.replace("2026102102", "2026102100"), "x", "nn 00"),
    (GOOD.replace("2026102102", "2026023001"), "x", "30 February"),
    (GOOD.replace("minVersionCode=2026102101", "minVersionCode=2026102103"), "x", "min above code"),
    (GOOD.replace("1.2.3", "1.2"), "x", "not semver"),
    (GOOD.replace("1.2.3", "01.2.3"), "x", "leading zero"),
    (GOOD.replace("2026102102", "1926102102"), "x", "not 20xx"),
    (GOOD.replace("2026102102", "2100010101"), "x", "above the ceiling"),   # 2100-01-01 is a real date
    (GOOD + "extra=1\n", "x", "a fourth key"),
    (GOOD.replace("minVersionCode=2026102101\n", ""), "x", "a missing key"),
    (GOOD, "", "empty notes"),
    (GOOD, "n" * 501, "notes over 500"),
])
def test_each_rule_turns_it_red(text, notes, why):
    assert problems(GOOD, "x") == [] and tv_version.validate_version(tv_version.parse_version_text(GOOD), "x") == []
    assert problems(text, notes), why
    assert tv_version.validate_version(tv_version.parse_version_text(text), notes), why


def test_the_ceiling_is_checked_on_a_real_date():
    # 2099-12-31 + 99 = 2099123199 > 2,100,000,000? No: 2,099,123,199 is below; the ceiling bites from 2100-01-01.
    assert problems(GOOD.replace("2026102102", "2099123199"), "x") == []
    assert tv_version.MAX_CODE == 2_100_000_000


def test_signing_cert_fingerprint_when_present():
    """WP-B9 step 1 commits the release certificate's SHA-256 (public). Until then the file is absent."""
    path = REPO_ROOT / "tv" / "SIGNING_CERT_SHA256"
    if not path.exists():
        pytest.skip("tv/SIGNING_CERT_SHA256 arrives with the release keystore (WP-B9)")
    assert re.fullmatch(r"[0-9a-f]{64}", path.read_text(encoding="utf-8").strip())
