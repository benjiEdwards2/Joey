"""Joey TV release metadata (WP-B8, D-P9): the `tv/VERSION` rules, the `version.json` contract, the APK secret scan and
the cut-date guard. Stdlib only, because it runs in two places:

* GitHub Actions (`.github/workflows/tv.yml`, release half) - `python3 deploy/tv_version.py <command>`;
* the NAS, inside the `life-hub` image - `deploy/tv_publish.py` imports it to verify a downloaded release.

Commands (exit 0 = ok, 1 = a problem, printed one per line):
    check                       tv/VERSION + tv/NOTES.txt are valid
    apk-name                    prints joey-media-<versionName>-<versionCode>.apk
    check-date --today D        versionCode's date part is at most one day after D (YYYY-MM-DD, the run's UTC date)
    meta --apk P --out F [--published ISO]   writes version.json for the APK P
    scan P                      token-shaped strings anywhere in the APK P fail

`--repo` (default: this file's parent's parent) locates tv/VERSION and tv/NOTES.txt.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
CODE_RE = re.compile(r"^20\d{6}(0[1-9]|[1-9]\d)$")   # YYYYMMDDnn, nn 01-99 (Australia/Sydney cut date)
MAX_CODE = 2_100_000_000                                # Google Play's versionCode ceiling
NOTES_MAX = 500
KEYS = ("versionName", "versionCode", "minVersionCode")
APK_NAME_RE = re.compile(r"^joey-media-\d+\.\d+\.\d+-\d{10}\.apk$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
VERSION_JSON_KEYS = ("version", "versionCode", "min_version", "url", "sha256", "notes", "size", "published")

# Token-shaped strings that must never ship in an APK: a JWT / Cloudflare tunnel token (base64 JSON starts `eyJ`),
# an `api_key`, GitHub tokens, a Jellyfin MediaBrowser token value. Images and signature blocks are not scanned.
SECRET_PATTERNS = (
    (re.compile(rb"eyJ[A-Za-z0-9_-]{16,}"), "JWT/tunnel-token-shaped string"),
    (re.compile(rb"(?i)api_key"), "api_key"),
    (re.compile(rb"gh[pousr]_[A-Za-z0-9]{20,}"), "GitHub token"),
    (re.compile(rb"github_pat_[A-Za-z0-9_]{20,}"), "GitHub fine-grained token"),
    (re.compile(rb'MediaBrowser Token="[^"]+'), "Jellyfin token value"),
)
SCAN_SKIP_SUFFIXES = (".png", ".webp", ".jpg", ".jpeg", ".gif", ".rsa", ".dsa", ".ec")


def default_repo() -> Path:
    return Path(__file__).resolve().parent.parent


def parse_version_text(text: str) -> dict:
    """key=value lines; blank lines and # comments ignored."""
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip()
    return out


def code_date(code: str) -> date | None:
    """The calendar date in a versionCode, or None when it is not a real date (month 13, 30 Feb...)."""
    try:
        return datetime.strptime(code[:8], "%Y%m%d").date()
    except ValueError:
        return None


def validate_version(values: dict, notes: str | None = None) -> list[str]:
    problems = []
    if sorted(values) != sorted(KEYS):
        problems.append(f"tv/VERSION keys must be exactly {', '.join(KEYS)} (got {', '.join(sorted(values)) or 'none'})")
    name = values.get("versionName", "")
    if not SEMVER_RE.match(name):
        problems.append(f"versionName {name!r} is not semver MAJOR.MINOR.PATCH")
    codes = {}
    for key in ("versionCode", "minVersionCode"):
        raw = values.get(key, "")
        if not CODE_RE.match(raw):
            problems.append(f"{key} {raw!r} is not YYYYMMDDnn (nn 01-99)")
        elif code_date(raw) is None:
            problems.append(f"{key} {raw!r} is not a real calendar date")
        elif int(raw) > MAX_CODE:
            problems.append(f"{key} {raw} is above {MAX_CODE}")
        else:
            codes[key] = int(raw)
    if len(codes) == 2 and codes["minVersionCode"] > codes["versionCode"]:
        problems.append("minVersionCode is above versionCode")
    if notes is not None:
        text = notes.strip()
        if not text:
            problems.append("tv/NOTES.txt is empty")
        elif len(text) > NOTES_MAX:
            problems.append(f"tv/NOTES.txt is {len(text)} characters (max {NOTES_MAX})")
    return problems


def read_version(repo: Path) -> dict:
    """tv/VERSION as a dict; ValueError (all problems) when it is invalid."""
    values = parse_version_text((repo / "tv" / "VERSION").read_text(encoding="utf-8"))
    problems = validate_version(values)
    if problems:
        raise ValueError("; ".join(problems))
    return values


def read_notes(repo: Path) -> str:
    return (repo / "tv" / "NOTES.txt").read_text(encoding="utf-8").strip()


def apk_name(values: dict) -> str:
    return f"joey-media-{values['versionName']}-{values['versionCode']}.apk"


def check_cut_date(code: str, today: date) -> str | None:
    """A typo guard: the cut date may be at most one day after the run's UTC date (Sydney runs ahead of UTC)."""
    cut = code_date(code)
    if cut is None:
        return f"versionCode {code} has no valid date"
    if cut > today + timedelta(days=1):
        return f"versionCode {code} is dated {cut.isoformat()}, more than a day after {today.isoformat()}"
    return None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def make_version_json(values: dict, notes: str, apk: Path, published: str) -> dict:
    """The version.json the app and tv_publish.py read. `url` is RELATIVE (the file name), so a LAN host override
    also redirects updates; `min_version` is an integer versionCode (DECISIONS F, D-P9)."""
    return {
        "version": values["versionName"],
        "versionCode": int(values["versionCode"]),
        "min_version": int(values["minVersionCode"]),
        "url": apk.name,
        "sha256": sha256_file(apk),
        "notes": notes.strip(),
        "size": apk.stat().st_size,
        "published": published,
    }


def validate_version_json(doc) -> list[str]:
    if not isinstance(doc, dict):
        return ["version.json is not an object"]
    problems = [f"version.json lacks {k}" for k in VERSION_JSON_KEYS if k not in doc]
    if problems:
        return problems
    for key in ("versionCode", "min_version", "size"):
        if not isinstance(doc[key], int) or isinstance(doc[key], bool):
            problems.append(f"version.json {key} is not an integer")
    if not problems:
        if not CODE_RE.match(str(doc["versionCode"])) or not CODE_RE.match(str(doc["min_version"])):
            problems.append("version.json versionCode / min_version is not YYYYMMDDnn")
        elif doc["min_version"] > doc["versionCode"]:
            problems.append("version.json min_version is above versionCode")
    if not isinstance(doc["url"], str) or not APK_NAME_RE.match(doc["url"]):
        problems.append("version.json url is not a relative joey-media-<semver>-<code>.apk name")
    elif isinstance(doc["versionCode"], int) and not doc["url"].endswith(f"-{doc['versionCode']}.apk"):
        problems.append("version.json url does not carry its versionCode")
    if not isinstance(doc["sha256"], str) or not SHA256_RE.match(doc["sha256"]):
        problems.append("version.json sha256 is not 64 lowercase hex")
    if not isinstance(doc["version"], str) or not SEMVER_RE.match(doc["version"]):
        problems.append("version.json version is not semver")
    return problems


def scan_apk(apk: Path) -> list[str]:
    """`<entry>: <what>` for every token-shaped string in the unzipped APK (images and signatures skipped)."""
    hits = []
    with zipfile.ZipFile(apk) as zf:
        for info in zf.infolist():
            if info.is_dir() or info.filename.lower().endswith(SCAN_SKIP_SUFFIXES):
                continue
            data = zf.read(info)
            for pattern, what in SECRET_PATTERNS:
                if pattern.search(data):
                    hits.append(f"{info.filename}: {what}")
    return hits


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Joey TV release metadata")
    parser.add_argument("--repo", type=Path, default=default_repo())
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    sub.add_parser("apk-name")
    p_date = sub.add_parser("check-date")
    p_date.add_argument("--today", required=True)
    p_meta = sub.add_parser("meta")
    p_meta.add_argument("--apk", type=Path, required=True)
    p_meta.add_argument("--out", type=Path, required=True)
    p_meta.add_argument("--published")
    p_scan = sub.add_parser("scan")
    p_scan.add_argument("apk", type=Path)
    args = parser.parse_args(argv)

    if args.cmd == "scan":
        hits = scan_apk(args.apk)
        for hit in hits:
            print(f"FAIL secret scan: {hit}")
        if not hits:
            print(f"PASS secret scan: {args.apk.name}")
        return 1 if hits else 0

    values = parse_version_text((args.repo / "tv" / "VERSION").read_text(encoding="utf-8"))
    problems = validate_version(values, read_notes(args.repo))
    if problems:
        for problem in problems:
            print(f"FAIL {problem}")
        return 1
    if args.cmd == "check":
        print(f"PASS tv/VERSION {values['versionName']} ({values['versionCode']}), min {values['minVersionCode']}")
        return 0
    if args.cmd == "apk-name":
        print(apk_name(values))
        return 0
    if args.cmd == "check-date":
        problem = check_cut_date(values["versionCode"], date.fromisoformat(args.today))
        print(f"FAIL {problem}" if problem else f"PASS cut date of {values['versionCode']} vs {args.today}")
        return 1 if problem else 0
    # meta
    if args.apk.name != apk_name(values):
        print(f"FAIL APK is named {args.apk.name}, expected {apk_name(values)}")
        return 1
    published = args.published or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    doc = make_version_json(values, read_notes(args.repo), args.apk, published)
    problems = validate_version_json(doc)
    if problems:
        for problem in problems:
            print(f"FAIL {problem}")
        return 1
    args.out.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(f"PASS wrote {args.out} for {doc['url']} sha256 {doc['sha256']} size {doc['size']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
