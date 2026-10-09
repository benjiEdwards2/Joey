"""Meal plan from MacroMates (Supabase). PARKED (2026-10-09, C-01): transform only, no live fetch()."""

from __future__ import annotations

from connectors.base import Connector


class MacroMates(Connector):
    id = "macromates"
    requires_env = ("SUPABASE_URL", "SUPABASE_KEY")

    def transform(self, raw: dict) -> dict:
        meals = {m["id"]: m["name"] for m in raw["meals"]}
        entries = {e["slot_id"]: e for e in raw["plan_entries"]}

        week = []
        tonight = None
        for slot in raw["plan_slots"]:
            entry = entries.get(slot["id"])
            if not entry:
                continue
            meal = meals.get(entry["meal_id"], "TBD")
            week.append({"day": slot["day"], "meal": meal})
            if (slot["day"], slot["meal_time"]) == (raw["today"]["day"], raw["today"]["meal_time"]):
                tonight = {"meal": meal, "serves": int(entry["serves"])}

        return {
            "summary": f"Tonight: {tonight['meal']}" if tonight else "Nothing planned tonight",
            "secondary": (
                f"Serves {tonight['serves']} · {len(week)} nights planned" if tonight
                else f"{len(week)} nights planned"
            ),
            "tonight": tonight,
            "week": week,
            "owner": "shared",
        }
