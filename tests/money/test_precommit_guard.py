"""WP37 — money pre-commit guard logic."""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from precommit_money_guard import BANK_ROW, check_path, is_allowlisted  # noqa: E402


def test_csv_anywhere_is_blocked():
    assert check_path("drop/august.csv") is not None
    assert check_path("connectors/money/samples/x.csv") is not None


def test_db_blocked_and_age_allowed():
    assert check_path("connectors/money/history.db") is not None
    assert check_path("connectors/money/golden_month.csv.age") is None


def test_allowlist_passes():
    for p in ("connectors/money/schema.sql", "connectors/money/importer.py",
              "connectors/money/rules_categories.yaml", "connectors/money/README.md",
              "connectors/money/money.schema.json"):
        assert check_path(p) is None, p


def test_bank_row_heuristic():
    assert BANK_ROW.search("2026-08-14,WOOLWORTHS METFORD,-184.32,4211.90")
    assert BANK_ROW.search("14/08/2026;EFTPOS FUEL;-72.50")
    assert not BANK_ROW.search("stale_after_minutes: 11520  # 8 days")
    assert not BANK_ROW.search("2026-08-14 release notes, version 1.2")


def test_is_allowlisted_never_passes_raw_csv():
    assert not is_allowlisted("connectors/money/samples/aug.csv")


def test_guard_survives_utf8_content_in_staged_files(tmp_path):
    """Regression (2026-08-31): UTF-8 '·'/'—' in staged HTML crashed the guard —
    subprocess decoded `git show` as cp1252 and returned None."""
    import subprocess
    repo = tmp_path / "r"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", repo], check=True)
    subprocess.run(["git", "-C", repo, "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", repo, "config", "user.name", "t"], check=True)
    (repo / "page.html").write_text("<h1>Joey · joeyhome.net — “fancy”</h1>", encoding="utf-8")
    subprocess.run(["git", "-C", repo, "add", "page.html"], check=True)
    guard = REPO_ROOT / "scripts" / "precommit_money_guard.py"
    r = subprocess.run([sys.executable, str(guard)], cwd=repo,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert r.returncode == 0, r.stdout + r.stderr


def test_svg_images_skip_the_line_heuristic():
    """WP-U3 (2026-10-07): minified logo path data ("m1-2-3 … ,12.34") looks like a bank row;
    .svg joins the image suffixes the line check skips. check_path still guards money paths."""
    from precommit_money_guard import check_lines
    assert check_lines("hub/static/svc/sonarr.svg") is None
    assert check_path("connectors/money/x.csv") is not None
