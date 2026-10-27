# JY-221 Retire the four hidden areas

Status: building
Size: M
Live risk: none
Area: `config/areas.yaml`, `connectors/registry.py` (comment only if needed), `deploy/.env.example`, tests under `tests/hub` and `tests/connectors`, `docs/PLAN.md`, `README.md`, `docs/connector-contract.md`, `docs/hub-changelog.md`
Needs: none (JY-220 follows it; both edit `config/areas.yaml`)
Options page: none: no new screen; B. picked option B on the decisions page

Source: `JoeyTV/review/decisions-2026-10-27/options.md`, JY-221.

## Decision
B., 2026-10-27: "Accept every recommendation on the Joey decisions page: merge the 4 built-ahead PRs, drop the 7, apply the rest as recommended." The recommendation for JY-221 is option B: retire all four hidden areas from `areas.yaml` and stop scheduling the three connectors; the code stays for a later revival.

## Problem
Food, Desk, House and Car are hidden, and their three connectors (`macromates`, `home_assistant`, `nas_stats`) are parked waiting for credentials. None has moved in three weeks.

## Acceptance criteria
1. `config/areas.yaml` has no `kitchen`, `desk`, `house` or `car` area. The remaining order is money (hidden), calendar, media, server.
2. `/a/kitchen`, `/a/desk`, `/a/house`, `/a/car` return the ordinary unknown-area 404 (same body as any unknown id). Today a hidden area serves its page, so this is a change: they are gone, not hidden.
3. The hub card row and navigation are unchanged (they already skipped hidden areas).
4. The three connectors stay registered and parked: their code, fixtures and schemas are untouched. A live sweep with no env set runs none of them. Disabled by config, not deleted. Reviving one means adding an area back and setting its env.
5. The id cross-check keeps its two guards: every tile snapshot id has a connector, and every non-parked connector is shown by a tile. Parked connectors are exempt from the second.
6. `deploy/.env.example` comment, `docs/PLAN.md`, `README.md`, `docs/connector-contract.md` and the hub changelog say so.
7. No test is weakened silently: the tests that pinned the retired areas are replaced, not skipped, with dated notes (below).

## Test changes (dated 2026-10-27)
- `test_hidden_areas.py`: parked set is `{money}`; new 404 test for the four retired ids.
- `test_registry.py`: locked order; the Food/MacroMates link tests are replaced by "retired areas are gone".
- `test_area_pages.py`: tests that used `/a/house`, `/a/desk` or `/a/kitchen` use `/a/money` or `/a/calendar`.
- `test_hub_reads_samples.py`: tile count 18 -> 14 (meals, files, climate, car-status removed); `/a/kitchen` is 404.
- `test_id_crosscheck.py`: parked ids exempt from "used by a tile"; new test that a live sweep skips them.

## Data
None. Snapshots for the three connectors are simply no longer displayed.

## Performance budget
None apply (config and tests only).

## Out of scope
- The `joey-macromates` nginx container and `macromates.joeyhome.net`: not an area, untouched.
- `hub/seed_demo.py` demo envelopes: harmless dev data.

## Accept checklist
After deploy, `/a/kitchen` shows the normal 404 and the hub looks the same.

## Questions for B.
None.
