"""JY-252 (2026-10-26): reuse FastAPI's per-endpoint dependency analysis across the suite's fresh apps.

Most hub tests build a new app (`importlib.reload(hub.main)`). FastAPI 0.138 builds each route's state lazily, on the
first request that walks past it, and per app; 80 % of that is `get_dependant` (signature + one pydantic TypeAdapter per
parameter). The endpoints themselves are module-level functions that the reload does not touch, so every test paid
~55 ms on the laptop (more on the NAS) to analyse the same ~200 functions again.

The memo keys on everything `get_dependant` reads (path, the endpoint itself, name, scopes, use_cache, scope) and hands
out a shallow copy each time: `_populate_api_route_state` inserts the route's own `dependencies=[...]` into the copy's
list, and `dataclasses.replace` drops the cached properties that read that list (`_uses_scopes`,
`_security_dependencies`). Sub-dependants and parameter fields stay shared between copies: on 0.138.0 FastAPI only
reads them after `get_dependant` returns. Entries (endpoint functions included) are held strongly for the worker's
life: about 200 endpoints. A reloaded or monkeypatched endpoint is a different function, so it is analysed afresh.
Requests, routing, validation and the dependencies themselves run unchanged; only the repeated analysis is skipped.

Applied only on the pinned FastAPI (`hub/requirements.txt`); any other version runs unmemoised (slower, still correct).
`tests/hub/test_route_memo.py` pins the version, that the memo is on, and that dependencies run once per request.
"""
from __future__ import annotations

import dataclasses

MEMO_FASTAPI_VERSION = "0.138.0"


def install() -> bool:
    """Swap fastapi.routing.get_dependant for the memo. -> True when installed (or already in place)."""
    try:
        import fastapi
        import fastapi.routing as routing
    except ImportError:  # an environment without the hub's dependencies
        return False
    if fastapi.__version__ != MEMO_FASTAPI_VERSION:
        return False
    real = routing.get_dependant
    if getattr(real, "jy252_memo", False):
        return True
    seen: dict = {}

    def get_dependant(*, path, call, name=None, own_oauth_scopes=None, parent_oauth_scopes=None, use_cache=True,
                      scope=None):
        key = (path, call, name, tuple(own_oauth_scopes or ()), tuple(parent_oauth_scopes or ()), use_cache, scope)
        first = seen.get(key)
        if first is None:
            first = seen[key] = real(path=path, call=call, name=name, own_oauth_scopes=own_oauth_scopes,
                                     parent_oauth_scopes=parent_oauth_scopes, use_cache=use_cache, scope=scope)
        return dataclasses.replace(first, dependencies=list(first.dependencies))

    get_dependant.jy252_memo = True
    get_dependant.real = real
    get_dependant.seen = seen
    routing.get_dependant = get_dependant
    return True
