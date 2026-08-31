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
