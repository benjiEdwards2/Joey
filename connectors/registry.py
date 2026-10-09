"""Which connectors the runner sweeps.

The FROZEN D13 id namespace is wider than this list on purpose:
  * `clickup` stays frozen in the envelope enum but has NO connector —
    ClickUp was removed from v1 (DECISIONS 2026-08-25).
  * `money` is written by Track E's importer, a runner-registered task rather
    than a Connector subclass (D14), so it is not swept here either.
  * PARKED connectors (2026-10-09: `macromates`, `home_assistant`, `nas_stats`)
    keep their class, transform, fixture and schema but have no live `fetch()`.
    Fixture mode builds them (the sample sweep needs no env); live mode sweeps
    one only when every name in its `requires_env` is set — re-enabling a parked
    feed is "set the env", once it has a fetch().
Everything else registers below. WP22 ships the mechanism; WP23 fills the list.
"""

from __future__ import annotations

import os
from typing import Callable

from connectors.base import Connector, mode

# id -> zero-arg factory. Factories (not instances) so tests can swap env first.
_FACTORIES: dict[str, Callable[[], Connector]] = {}
_PARKED: set[str] = set()


def register(factory: Callable[[], Connector], connector_id: str, *, parked: bool = False) -> None:
    _FACTORIES[connector_id] = factory
    if parked:
        _PARKED.add(connector_id)
    else:
        _PARKED.discard(connector_id)


def all_ids() -> list[str]:
    """Every registered id, parked included (what areas.yaml may reference)."""
    return sorted(_FACTORIES)


def parked_ids() -> list[str]:
    return sorted(_PARKED)


def _opted_in(connector_id: str) -> bool:
    needed = getattr(_FACTORIES[connector_id], "requires_env", ())
    return all(os.environ.get(v) for v in needed)


def connector_ids() -> list[str]:
    """The ids a sweep runs now: all of them in fixture mode; in live mode a
    parked connector only when its requires_env are all set."""
    if mode() == "fixture":
        return all_ids()
    return [cid for cid in all_ids() if cid not in _PARKED or _opted_in(cid)]


def build_all() -> list[Connector]:
    return [_FACTORIES[cid]() for cid in connector_ids()]


def _load_stubs() -> None:
    """Import the per-feed stub connectors, which self-register (WP23)."""
    try:
        from connectors import stubs  # noqa: F401
    except ImportError:  # WP22 ships before the stubs exist
        pass


_load_stubs()
