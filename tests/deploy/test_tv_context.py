"""Joey TV WP-B8 (WP-B7 leftover, 2026-10-21): the life-test image does `COPY . .`, so the Docker build context must
not carry the Android project (`tv/`), least of all the committed public debug p12. Only the three release-metadata
files the gate reads stay in: tv/VERSION, tv/NOTES.txt, tv/SIGNING_CERT_SHA256. And git tracks exactly one keystore,
the labelled debug key.

`.dockerignore` follows Go filepath.Match (`*` never crosses `/`), later lines win, and a path is excluded when the last
rule matching it or one of its parent directories is not a `!` rule. `_excluded` models exactly that, enough for these
patterns.
"""
import os
import shutil
import subprocess
from fnmatch import fnmatchcase
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEBUG_P12 = "tv/app/debug-signing/joeytv-debug.p12"
KEEP = ["tv/VERSION", "tv/NOTES.txt", "tv/SIGNING_CERT_SHA256"]
DROP = ["tv/README.md", "tv/app/build.gradle.kts", DEBUG_P12, "tv/ci/check_apk.sh",
        "tv/app/src/main/java/net/joeyhome/media/MainActivity.kt", "tv/settings.gradle.kts"]
KEYSTORE_SUFFIXES = (".jks", ".keystore", ".p12")


def _patterns(text: str | None = None) -> list[str]:
    text = (REPO_ROOT / ".dockerignore").read_text(encoding="utf-8") if text is None else text
    return [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]


def _match(pattern: str, path: str) -> bool:
    pattern = pattern.rstrip("/")
    if pattern.startswith("**/"):
        tail = pattern[3:]
        parts = path.split("/")
        return any(_match(tail, "/".join(parts[i:])) for i in range(len(parts)))
    if pattern.count("/") != path.count("/"):
        return False   # `*` never crosses `/`
    return fnmatchcase(path, pattern)


def _excluded(path: str, patterns: list[str]) -> bool:
    parts = path.split("/")
    candidates = ["/".join(parts[:i]) for i in range(1, len(parts) + 1)]
    excluded = False
    for raw in patterns:
        negate = raw.startswith("!")
        pattern = raw[1:] if negate else raw
        if any(_match(pattern, c) for c in candidates):
            excluded = not negate
    return excluded


def test_tv_is_excluded_except_the_release_metadata():
    patterns = _patterns()
    assert "tv/*" in patterns
    for keep in KEEP:
        assert "!" + keep in patterns
        assert patterns.index("!" + keep) > patterns.index("tv/*")   # later lines win
        assert not _excluded(keep, patterns), keep
    for drop in DROP:
        assert _excluded(drop, patterns), drop


def test_removing_any_tv_rule_breaks_the_guard():
    """Meta: each line is load-bearing - without `tv/*` the debug p12 enters the image; without a `!` line the gate
    cannot read that file."""
    patterns = _patterns()
    without_star = [p for p in patterns if p != "tv/*"]
    assert not _excluded(DEBUG_P12, without_star)
    for keep in KEEP:
        assert _excluded(keep, [p for p in patterns if p != "!" + keep]), keep


def test_secrets_and_env_rules_still_apply_inside_tv():
    """A NAS-style env file or backup dropped under tv/ stays out of the context."""
    assert _excluded("tv/x.env", _patterns())
    assert _excluded("tv/app/tv.env", _patterns())
    assert _excluded("tv/edge.env.bak-2026-10-21-1200", _patterns())


def _walk_keystores() -> list[str]:
    found = []
    skip = {".git", ".venv", "node_modules", ".gradle", "build", ".pytest_cache", "__pycache__"}
    for root, dirs, files in os.walk(REPO_ROOT):
        dirs[:] = [d for d in dirs if d not in skip]
        for name in files:
            if name.lower().endswith(KEYSTORE_SUFFIXES):
                found.append(Path(root, name).relative_to(REPO_ROOT).as_posix())
    return sorted(found)


def test_the_only_keystore_on_disk_is_the_debug_key():
    """Laptop/CI checkout: exactly the debug key. Gate image (tv/ excluded): none at all."""
    assert set(_walk_keystores()) <= {DEBUG_P12}


def test_git_tracks_only_the_debug_keystore():
    """The same guard tv.yml runs before any release build. Skipped where there is no git checkout (the gate image
    excludes .git/); the on-disk walk above still runs there."""
    git = shutil.which("git")
    if git is None or not (REPO_ROOT / ".git").exists():
        import pytest
        pytest.skip("no git checkout here (life-test image)")
    out = subprocess.run([git, "-C", str(REPO_ROOT), "ls-files", "*.jks", "*.keystore", "*.p12"],
                         capture_output=True, text=True, check=True).stdout.split()
    assert out == [DEBUG_P12]


def test_gitignore_blocks_every_other_keystore():
    lines = [ln.strip() for ln in (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()]
    for pattern in ("*.jks", "*.keystore", "*.p12", "keystore.properties"):
        assert pattern in lines
    assert "!/" + DEBUG_P12 in lines
