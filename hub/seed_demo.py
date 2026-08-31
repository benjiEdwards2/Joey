"""Seed demo snapshot envelopes into data/demo-snapshots/ (standing dev fixture).

Fresh: open_meteo, macromates, jellyfin, money. Stale: home_assistant (5 h old
vs 120-min stale_after). Deliberately ABSENT: gcal, nas_stats — those tiles must
render "Not connected". Every envelope validates against the frozen schema.

Run:  python -m hub.seed_demo   (from the repo root)
Then: SNAPSHOT_DIR=data/demo-snapshots uvicorn hub.main:app
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data" / "demo-snapshots"


def envelope(connector: str, data: dict, age_minutes: int = 12) -> dict:
    ts = (datetime.now(timezone.utc) - timedelta(minutes=age_minutes)).isoformat()
    return {
        "connector": connector,
        "schema_version": 1,
        "fetched_at": ts,
        "updated_at": ts,
        "status": "ok",
        "consecutive_failures": 0,
        "error": None,
        "data": data,
    }


SEEDS = [
    envelope("macromates", {
        "summary": "Burrito bowls tonight",
        "secondary": "4 items on the shopping list",
        "meals": [{"day": "Wed", "meal": "Chicken burrito bowls", "owner": "shared"}],
    }, age_minutes=25),
    envelope("money", {
        "summary": "$1,240 left of $6,800 aimed",
        "secondary": "Next bill: Electricity $184 — Fri 29th",
        "pct_aim_used": 82, "pct_month_gone": 84,
    }, age_minutes=12),
    envelope("open_meteo", {
        "summary": "18 °C · light rain",
        "secondary": "today 14–19 °C · rain easing 4 pm",
    }, age_minutes=18),
    envelope("jellyfin", {
        "summary": "Slow Horses S4E3",
        "secondary": "34 min left · 2 new episodes",
    }, age_minutes=55),
    envelope("home_assistant", {
        "summary": "21.5 °C inside",
        "secondary": "heating off",
    }, age_minutes=5 * 60),  # STALE against 120-min tiles
]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for env in SEEDS:
        path = OUT / f"{env['connector']}.json"
        path.write_text(json.dumps(env, indent=2), encoding="utf-8")
        print(f"wrote {path}")
    print(f"{len(SEEDS)} envelopes seeded; gcal + nas_stats deliberately absent")


if __name__ == "__main__":
    main()
