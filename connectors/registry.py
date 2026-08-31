"""Which connectors the runner sweeps.

The FROZEN D13 id namespace is wider than this list on purpose:
  * `clickup` stays frozen in the envelope enum but has NO connector —
    ClickUp was removed from v1 (DECISIONS 2026-08-25).
  * `money` is written by Track E's importer, a runner-registered task rather
    than a Connector subclass (D14), so it is not swept here either.
Everything else registers below. WP22 ships the mechanism; WP23 fills the list.
"""

from __future__ import annotations

from typing import Callable

from connectors.base import Connector

# id -> zero-arg factory. Factories (not instances) so tests can swap env first.
_FACTORIES: dict[str, Callable[[], Connector]] = {}


def register(factory: Callable[[], Connector], connector_id: str) -> None:
    _FACTORIES[connector_id] = factory


def connector_ids() -> list[str]:
    return sorted(_FACTORIES)


def build_all() -> list[Connector]:
    return [_FACTORIES[cid]() for cid in connector_ids()]


def _load_stubs() -> None:
    """Import the per-feed stub connectors, which self-register (WP23)."""
    try:
        from connectors import stubs  # noqa: F401
    except ImportError:  # WP22 ships before the stubs exist
        pass


_load_stubs()
