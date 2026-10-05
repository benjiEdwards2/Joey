#!/usr/bin/env python
"""Pre-commit guard: committing plaintext money data is impossible (WP37).

Blocks any staged file that could carry bank transactions unless it is
age-encrypted or explicitly allowlisted, and any staged line that looks like
a bank row (date + signed decimal amount on one CSV-ish line).
Install (once per clone):  git config core.hooksPath scripts/hooks
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import PurePosixPath

ALLOWED_SUFFIXES = {".age"}
ALLOWLIST_NAMES = {"schema.sql", "README.md", "requirements.txt"}
ALLOWLIST_PATTERNS = (
    re.compile(r"\.py$"),
    re.compile(r"\.schema\.json$"),
    re.compile(r"(rules|seed)[^/]*\.ya?ml$"),
)

# A date and a signed decimal amount on the same comma/semicolon-ish line
BANK_ROW = re.compile(
    r"(\d{1,4}[/-]\d{1,2}[/-]\d{1,4}).*[,;].*(-?\$?\d{1,3}(,\d{3})*\.\d{2})"
)


def staged_files() -> list[str]:
    out = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
        capture_output=True, text=True, check=True,
    ).stdout
    return [l for l in out.splitlines() if l.strip()]


def staged_content(path: str) -> str:
    # encoding pinned: Windows would otherwise decode as cp1252 and crash on UTF-8
    r = subprocess.run(["git", "show", f":{path}"], capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    return r.stdout if r.returncode == 0 and r.stdout else ""


def is_allowlisted(path: str) -> bool:
    p = PurePosixPath(path)
    if p.suffix in ALLOWED_SUFFIXES:
        return True
    if p.name in ALLOWLIST_NAMES:
        return True
    return any(pat.search(path) for pat in ALLOWLIST_PATTERNS)


def check_path(path: str) -> str | None:
    """Money-shaped file in a money-shaped place?"""
    p = PurePosixPath(path)
    in_money = path.startswith("connectors/money/")
    is_dataish = p.suffix in {".csv", ".db"}
    if (in_money or is_dataish) and not is_allowlisted(path):
        where = "under connectors/money/" if in_money else f"a {p.suffix} file"
        return (f"{path}: {where} may only be committed age-encrypted (.age) or "
                f"allowlisted (schema.sql, *.py, rules/seed yaml, *.schema.json, README)")
    return None


def check_lines(path: str) -> str | None:
    if PurePosixPath(path).suffix in {".png", ".jpg", ".age", ".ico"}:
        return None
    if is_allowlisted(path):
        # Code and schema files may legitimately carry sample rows (tests,
        # rule examples). Data files never reach here — check_path blocks them.
        return None
    content = staged_content(path)
    for i, line in enumerate(content.splitlines()[:5000], 1):
        if BANK_ROW.search(line):
            return (f"{path}:{i}: line looks like a bank transaction row "
                    f"(date + signed decimal amount) — money plaintext never reaches git")
    return None


def main() -> int:
    # Windows consoles default to cp1252 and choke on the ✗ below (2026-10-05)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    problems: list[str] = []
    for path in staged_files():
        for check in (check_path, check_lines):
            msg = check(path)
            if msg:
                problems.append(msg)
                break
    if problems:
        print("COMMIT BLOCKED by scripts/precommit_money_guard.py:\n")
        for p in problems:
            print(f"  ✗ {p}")
        print("\nEncrypt with age (*.age) or keep money data out of the repo "
              "(SQLite lives on the box; drops live in drop/, which is git-ignored).")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
