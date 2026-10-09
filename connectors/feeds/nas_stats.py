"""NAS share capacity + files added. PARKED (2026-10-09, C-01): transform only, no live fetch()."""

from __future__ import annotations

import json
from pathlib import Path

from connectors.base import Connector

NAS_RECENT_DAYS = 7


class NasStats(Connector):
    """Capacity comes from the NAS; the per-share file counts come from walking
    a directory tree, which is what the live WP30 connector will do over the
    mounted shares."""

    id = "nas_stats"
    requires_env = ("NAS_SHARES_ROOT",)

    def fetch_fixture(self) -> dict:
        meta = json.loads((self.fixture_dir / "raw_shares.json").read_text(encoding="utf-8"))
        # since=0 -> every fixture file counts as recent, so the snapshot stays
        # byte-reproducible whatever mtimes a fresh checkout happens to have.
        return {"meta": meta, "root": self.fixture_dir / "tree", "since_ts": 0.0}

    def transform(self, raw: dict) -> dict:
        root = Path(raw["root"])
        shares = [
            {
                "name": share["name"],
                "total_gb": share["total_gb"],
                "free_gb": share["free_gb"],
                "files_added_7d": count_files(root / share["name"], raw["since_ts"]),
            }
            for share in raw["meta"]["shares"]
        ]
        free = sum(s["free_gb"] for s in shares)
        added = sum(s["files_added_7d"] for s in shares)
        return {
            "summary": f"{free:,.0f} GB free across {len(shares)} shares",
            "secondary": f"{added} files added in {NAS_RECENT_DAYS} days",
            "shares": shares,
        }


def count_files(share_root: Path, since_ts: float) -> int:
    """Files anywhere under `share_root` modified at or after `since_ts`."""
    if not share_root.is_dir():
        return 0
    return sum(
        1 for p in share_root.rglob("*")
        if p.is_file() and p.stat().st_mtime >= since_ts
    )
