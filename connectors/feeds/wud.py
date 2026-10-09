"""What's Up Docker: container image updates (Server area)."""

from __future__ import annotations

import os

from connectors.base import Connector
from connectors.feeds._http import http_json


# What's Up Docker (2026-10-06, WP-S1). The raw shape IS WUD's GET /api/containers
# list (subset: name, image.name, image.tag.value, updateAvailable, updateKind.kind,
# result.tag), so the live fetch (WP-S3) returns the response JSON unchanged.
# WUD 9: `updateKind` is only meaningful when an update exists; a digest-only update has
# kind "digest" and `result.tag` == the current tag, so `new_tag` is null for it.


# WUD 9.3 (WP-U1, 2026-10-06): each /api/containers row carries `id` (the Docker container
# id, used by POST /api/containers/{id}/triggers/{type}/{name}) and the optional
# comma-separated `triggerInclude` / `triggerExclude` strings WUD builds from the
# `wud.trigger.include` / `wud.trigger.exclude` labels (entries are "type.name" with an
# optional ":threshold"; matched case-insensitively). `auto` mirrors WUD's own
# association rule for the one update trigger the hub may run.
WUD_UPDATE_TRIGGER = "dockercompose.local"


def _wud_trigger_ids(value) -> set[str]:
    return {part.split(":")[0].strip().lower() for part in str(value or "").split(",") if part.strip()}


def wud_auto(row: dict) -> bool:
    """True when `dockercompose.local` applies to this WUD container row: not excluded and,
    if an include list is set, included. The label is read as a fallback when the
    field is absent, so an excluded container can never read as auto."""
    labels = row.get("labels") if isinstance(row.get("labels"), dict) else {}
    exclude = row.get("triggerExclude") or labels.get("wud.trigger.exclude")
    include = row.get("triggerInclude") or labels.get("wud.trigger.include")
    if WUD_UPDATE_TRIGGER in _wud_trigger_ids(exclude):
        return False
    return not include or WUD_UPDATE_TRIGGER in _wud_trigger_ids(include)


class Wud(Connector):
    """Container image updates as WUD sees them (Server area)."""

    id = "wud"
    requires_env = ("WUD_URL", "WUD_USER", "WUD_PASS")

    def fetch(self) -> list:
        # One call, so no session.
        payload = http_json("WUD containers", os.environ["WUD_URL"].rstrip("/") + "/api/containers",
                            auth=(os.environ["WUD_USER"], os.environ["WUD_PASS"]))
        if not isinstance(payload, list):
            raise RuntimeError("WUD containers failed (unexpected payload)")
        return payload

    def transform(self, raw: list) -> dict:
        containers = []
        for c in raw or []:
            image = c.get("image") or {}
            update = bool(c.get("updateAvailable"))
            kind = (c.get("updateKind") or {}).get("kind")
            kind = kind if update and kind in ("tag", "digest") else None
            new_tag = (c.get("result") or {}).get("tag") if kind == "tag" else None
            containers.append({
                "name": str(c.get("name") or "?"),
                "image": str(image.get("name") or ""),
                "current_tag": str((image.get("tag") or {}).get("value") or ""),
                "new_tag": None if new_tag is None else str(new_tag),
                "update_available": update,
                "kind": kind,
                "id": str(c["id"]) if c.get("id") else None,
                "auto": wud_auto(c),
            })
        containers.sort(key=lambda c: (not c["update_available"], c["name"]))
        updates = [c for c in containers if c["update_available"]]
        if updates:
            first = updates[0]
            change = (f"{first['current_tag']} → {first['new_tag']}" if first["new_tag"]
                      else "new image digest")
            secondary = f"{first['name']} {change}"
            if len(updates) > 1:
                secondary += f" (+{len(updates) - 1} more)"
        else:
            secondary = f"{len(containers)} containers monitored"
        return {
            "summary": (f"{len(updates)} update{'' if len(updates) == 1 else 's'} available"
                        if updates else "All up to date"),
            "secondary": secondary,
            "monitoring": len(containers),
            "updates": len(updates),
            "containers": containers,
        }
