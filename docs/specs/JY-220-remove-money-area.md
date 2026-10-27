# JY-220 Remove the hidden Money area

Status: building
Size: L (listed L on the decisions page; the change is small and has no live risk)
Live risk: none
Area: `config/areas.yaml`, `hub/seed_demo.py`, `deploy/docker-compose.yml` (comment), tests under `tests/hub`, `docs/PLAN.md`, `README.md`, `tests/README.md`, `docs/hub-changelog.md`
Needs: none (JY-221 merged first; this branch merged origin/main on 2026-10-27)
Options page: none: no new screen; B. picked option B on the decisions page

Source: `JoeyTV/review/decisions-2026-10-27/options.md`, JY-220.

## Decision
B., 2026-10-27: "Accept every recommendation on the Joey decisions page: merge the 4 built-ahead PRs, drop the 7, apply the rest as recommended." The recommendation for JY-220 is option B: drop Money from Joey, keep the money pre-commit guard.

## Problem
The Money area has been hidden since 2026-10-06 with no importer built. The budget work moved to its own project (`Desktop\Claude\Budget`, xlsx), so the hidden area only adds upkeep. Track E (Westpac import, rules, budget vs actual) will not be built in Joey.

## Acceptance criteria
1. `config/areas.yaml` has no `money` area (tile, setup note, config all gone).
2. `/a/money` returns the ordinary unknown-area 404 (same body as any unknown id). The hub has no dedicated Money route or template; the generic area route is the only one, so nothing else is removed.
3. The money pre-commit guard stays exactly as it is: `scripts/precommit_money_guard.py`, `scripts/hooks/pre-commit`, `tests/money/` and the `docs/setup.md` note are not touched.
4. Tests that only covered Money are replaced, not dropped silently (below). No other test is weakened.
5. The money demo envelope is removed from `hub/seed_demo.py` (invented figures; none should remain anywhere in the repo).
6. The frozen `money` id stays in the envelope schema enum and `hub/registry.py`: the D13 contract is frozen and removing it is a contract change outside this item.
7. Bank data never appears in the repo, a log or a page: this item adds none and removes the demo figures.

## Test changes (dated 2026-10-27)
- `test_hidden_areas.py`: no hidden areas remain; the "parked page still serves" test uses a synthetic hidden area; the retired-404 test now includes money.
- `test_area_pages.py`: the all-not-connected sentence test uses a synthetic area; the hex check no longer visits `/a/money`.
- `test_registry.py`: locked order without money.
- `test_tiles.py`: demo seed makes 4 envelopes, not 5.

## Data
None. The budget lives in its own project (`Desktop\Claude\Budget`).

## Performance budget
None apply.

## Out of scope
- The money guard (kept). The frozen schema enum. `scripts/check_soak.py`'s `--exempt money` default (harmless).

## Accept checklist
After deploy, `/a/money` shows the normal 404, and committing a `.csv` still trips the guard.

## Questions for B.
None.

## Shipped notes
