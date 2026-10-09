"""Home Assistant states keyed by area. PARKED (2026-10-09, C-01): transform only, no live fetch()."""

from __future__ import annotations

from connectors.base import Connector


class HomeAssistant(Connector):
    """One feed, three areas — the `areas` keying is what lets House, Car and
    Garden tiles show DIFFERENT things off a single snapshot (WP18 limit)."""

    id = "home_assistant"
    requires_env = ("HA_URL", "HA_TOKEN")

    CAR_HINTS = ("car",)
    GARDEN_HINTS = ("garden", "irrigation", "soil")
    OWNER_BY_AREA = {"house": "shared", "car": "you", "garden": "shared"}

    @classmethod
    def area_of(cls, entity_id: str) -> str:
        name = entity_id.lower()
        if any(h in name for h in cls.CAR_HINTS):
            return "car"
        if any(h in name for h in cls.GARDEN_HINTS):
            return "garden"
        return "house"

    def transform(self, raw: dict) -> dict:
        areas: dict[str, list] = {"house": [], "car": [], "garden": []}
        for state in raw["states"]:
            area = self.area_of(state["entity_id"])
            attributes = state.get("attributes", {})
            areas[area].append({
                "entity_id": state["entity_id"],
                "label": attributes.get("friendly_name", state["entity_id"]),
                "state": str(state["state"]),
                "unit": attributes.get("unit_of_measurement"),
                "owner": self.OWNER_BY_AREA[area],
            })

        house = areas["house"]
        headline = f"{house[0]['label']} {house[0]['state']}{_unit(house[0])}" if house else "TBD"
        counted = ", ".join(f"{len(v)} {k}" for k, v in areas.items())
        return {
            "summary": headline,
            "secondary": counted,
            "areas": areas,
        }


def _unit(entity: dict) -> str:
    return f" {entity['unit']}" if entity.get("unit") else ""
