"""Joey TV WP-B1 (2026-10-21): tests/deploy/route_sweep.py (the WP-B5 BG2 live sweep) covers every PRIVATE pair with
its own verb and every GET template, with no path parameter left unfilled."""
import argparse
import importlib.util
from pathlib import Path

from hub import guest

REPO_ROOT = Path(__file__).resolve().parents[2]


def sweep():
    spec = importlib.util.spec_from_file_location("route_sweep", REPO_ROOT / "tests" / "deploy" / "route_sweep.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ARGS = argparse.Namespace(jf_id="f" * 32, ref="poster/x", area_id="calendar", cookie=None)


def test_plan_covers_every_private_pair_with_its_own_verb():
    mod = sweep()
    plan = mod.plan(ARGS)
    assert plan[0] == ("GET", "/no-such-page")
    methods = {m for m, _ in plan}
    assert {"GET", "POST"} <= methods
    assert len(plan) == len(set(plan))
    for method, template in guest.PRIVATE:
        assert (method, mod.fill(template, ARGS)) in plan, (method, template)
    for method, template in guest.GUEST + guest.RESERVED:
        if method == "GET":
            assert ("GET", mod.fill(template, ARGS)) in plan, template
    assert not [p for _, p in plan if "{" in p]


def test_every_private_sweep_path_is_denied_by_the_gate():
    mod = sweep()
    for method, path in mod.plan(ARGS):
        if (method, path) in {(m, mod.fill(t, ARGS)) for m, t in guest.PRIVATE}:
            assert not guest.allows(method, path), (method, path)
