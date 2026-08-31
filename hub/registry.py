"""The areas.yaml loader — refuses invalid registries with EVERY violation listed.

"Rooms are config, not code": the tab bar, hub grid, routes, and tiles all render
from the Registry object this module returns. A registry that loads is trustably
valid; nothing downstream re-validates.
"""

from __future__ import annotations

import re
from enum import Enum
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, ValidationError

# The FROZEN D13 connector/envelope id namespace (WP0, 2026-08-25).
FROZEN_SNAPSHOT_IDS = {
    "open_meteo", "gcal", "clickup", "macromates",
    "home_assistant", "jellyfin", "nas_stats", "money",
}

MAX_AREAS = 9  # hard ceiling (DECISIONS 2026-08-17); "locked at 8" is yaml content

ACCENT_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


class Tier(str, Enum):
    link = "link"
    embed = "embed"
    ingest = "ingest"


class Owner(str, Enum):
    you = "you"
    her = "her"
    shared = "shared"


class Tile(BaseModel):
    id: str
    label: str
    tier: Tier
    owner: Owner
    href: Optional[str] = None
    snapshot: Optional[str] = None
    stale_after_minutes: Optional[int] = None
    setup_note: Optional[str] = None


class HubSize(str, Enum):
    """Weighted bento size of the area's hub summary card (gate decision 2026-08-28)."""
    s11 = "s11"  # 1×1 (default)
    s21 = "s21"  # 2 wide
    s22 = "s22"  # 2 wide, 2 tall (hero)


class Area(BaseModel):
    id: str
    name: str
    accent: str
    icon: str
    summary_tile: str
    hub_size: HubSize = HubSize.s11
    tiles: list[Tile]


class Registry(BaseModel):
    areas: list[Area]


def _cross_checks(reg: Registry) -> list[str]:
    """Every rule pydantic's field types can't express, aggregated."""
    errors: list[str] = []

    if not 1 <= len(reg.areas) <= MAX_AREAS:
        errors.append(
            f"registry has {len(reg.areas)} areas — must be between 1 and {MAX_AREAS} (hard cap)"
        )

    seen_areas: set[str] = set()
    seen_tiles: set[str] = set()
    for area in reg.areas:
        if area.id in seen_areas:
            errors.append(f"duplicate area id '{area.id}'")
        seen_areas.add(area.id)

        if not ACCENT_RE.match(area.accent):
            errors.append(f"area '{area.id}': accent '{area.accent}' is not #RRGGBB")

        if not area.icon.strip():
            errors.append(f"area '{area.id}': icon must be a non-empty icon id")

        tile_ids = {t.id for t in area.tiles}
        if area.summary_tile not in tile_ids:
            errors.append(
                f"area '{area.id}': summary_tile '{area.summary_tile}' does not exist in its tiles"
            )

        for tile in area.tiles:
            where = f"area '{area.id}' tile '{tile.id}'"
            if tile.id in seen_tiles:
                errors.append(f"duplicate tile id '{tile.id}' (tile ids are global)")
            seen_tiles.add(tile.id)

            if tile.tier is Tier.link:
                if not tile.href:
                    errors.append(f"{where}: tier link requires href")
            else:  # embed / ingest
                if tile.stale_after_minutes is None or tile.stale_after_minutes <= 0:
                    errors.append(f"{where}: tier {tile.tier.value} requires stale_after_minutes > 0")
                if not tile.snapshot:
                    errors.append(f"{where}: tier {tile.tier.value} requires a snapshot id")
                elif tile.snapshot not in FROZEN_SNAPSHOT_IDS:
                    errors.append(
                        f"{where}: snapshot '{tile.snapshot}' is not in the frozen D13 namespace "
                        f"{sorted(FROZEN_SNAPSHOT_IDS)}"
                    )

    return errors


def load_registry(path: str | Path) -> Registry:
    """Load and validate areas.yaml. Raises ONE ValueError listing every violation."""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    try:
        reg = Registry.model_validate(raw)
    except ValidationError as exc:
        lines = [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()]
        raise ValueError(
            f"areas.yaml invalid — {len(lines)} violation(s):\n  " + "\n  ".join(lines)
        ) from None

    errors = _cross_checks(reg)
    if errors:
        raise ValueError(
            f"areas.yaml invalid — {len(errors)} violation(s):\n  " + "\n  ".join(errors)
        )
    return reg
