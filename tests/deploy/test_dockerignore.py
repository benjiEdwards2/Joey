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
