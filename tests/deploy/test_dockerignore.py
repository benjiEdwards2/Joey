"""Review D-01 (2026-10-09): the union life-test image does `COPY . .`, so the build context
must never carry a secrets file. `.dockerignore` patterns use Go filepath.Match semantics
(`*` does not cross `/`), so only the `**/` forms catch deploy/.env, hub.env, connectors.env.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PATTERNS = [line.strip() for line in (REPO_ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")]


def test_secret_env_files_are_excluded_in_every_subdirectory():
    for pattern in ("**/.env", "**/*.env"):
        assert pattern in PATTERNS
    # root-only forms are the bug this replaced
    assert ".env" not in PATTERNS and "*.env" not in PATTERNS


def test_env_example_stays_in_the_context():
    # tests/deploy/test_cloudflared.py reads deploy/.env.example inside the gate image
    assert "!**/*.env.example" in PATTERNS
    assert PATTERNS.index("!**/*.env.example") > PATTERNS.index("**/*.env")  # later lines win


def test_runtime_and_cache_files_are_excluded():
    for pattern in ("**/__pycache__/", "**/*.pyc", "deploy/history.log", ".preview/"):
        assert pattern in PATTERNS


# WP-A4 (2026-10-19): nas_scripts/append_env.sh and edge_cf_ini.sh leave `deploy/.env.bak-*` and
# `deploy/edge.env.bak-<date>-<HHMM>` behind. Neither matches `**/*.env` (the name ends in .bak-...),
# so a token-bearing backup was COPY'd into life-test and failed test_no_cloudflare_token_value_anywhere_in_deploy.
BACKUP_NAMES = ["edge.env.bak-2026-10-19-1210", ".env.bak-fix"]  # second has no date: `*` may be empty


def _matches(pattern, rel_path):
    # `**/X` = X in any directory; `*` never crosses `/`, so match X against the basename (enough for these names)
    from fnmatch import fnmatchcase
    return fnmatchcase(rel_path.rsplit("/", 1)[-1], pattern.removeprefix("**/"))


def test_nas_env_backups_are_excluded_from_the_build_context():
    assert "**/*.bak-*" in PATTERNS
    for name in BACKUP_NAMES:
        assert _matches("**/*.bak-*", f"deploy/{name}")


def test_nas_env_backups_are_gitignored():
    patterns = [line.strip() for line in (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.lstrip().startswith("#")]
    assert "*.bak-*" in patterns
    for name in BACKUP_NAMES:
        assert _matches("*.bak-*", f"deploy/{name}")
