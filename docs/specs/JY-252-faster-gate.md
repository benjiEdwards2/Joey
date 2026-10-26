# JY-252 Bring the deploy gate back down

Status: shipped 2026-10-26
Size: M
Live risk: none (tests only; deploy.sh and the hub are unchanged)
Area: `tests/conftest.py`, `tests/route_memo.py` (new), `tests/hub/test_route_memo.py` (new), `tests/README.md`, this spec
Needs: none
Options page: none: no screen

Brief from the orchestrator, 2026-10-26. The builder wrote this spec, measured and built it.

## Problem
On the NAS the full gate was 281–305 s on 2026-10-24 (after JY-235) and the last deploys took 435–480 s (`deploy/history.log` `dur=`) after the batch of merges and the TV UI round. It is still under the 10-minute budget, but it is rising. Find and cut the slow tests without losing coverage.

## What the numbers say

NAS deploys (`dur=` from the shipped notes in `docs/specs/`; the NAS was not reachable for this item):

| Deploys | Gate | `dur=` |
|---|---|---|
| c7c5eed … 26b38cb (2026-10-24 19:25–21:06) | `-n 2` | 281–305 s |
| 81524f3 … 62e533d (2026-10-25 09:07–10:13) | `-n 2` (avail 1,852–2,027 MB) | 433–480 s |
| 37bac74 (13:08) | `-n 2` | 420 s |
| ac96013, b0cec29, 417ef98, 18c0d86 (13:46–16:26) | `-n 2` | 350–368 s |
| 42f9dd8, 49096ca | `-n 1` (avail 1,617 / 1,719 MB) | 532–544 s |
| e3f5cc3, d0c790e (the last two) | `-n 1` (avail 1,634 / 1,629 MB) | 466–483 s |

- The last two deploys (466 s, 483 s) ran the JY-240 middle band, `-n 1`, because available memory was 1,629–1,634 MB.
- With `-n 2`, the same-size suite ran 350–368 s in the afternoon and 433–480 s in the morning before. Later commits carry more tests and ran faster, so most of the morning excess is the NAS's load at the time, not the tests.
- The suite did grow: ~200 tests since 26b38cb. On the laptop that is +8 % for the non-tooling tests (below).

Laptop, `python -m pytest -q -n 2 tests/` (Windows 11, Python 3.12; the laptop is shared and noisy, so the A/B rows were run back to back):

| Commit | Tests | Full suite | Without `tests/scripts` |
|---|---|---|---|
| 8ffae27 (2026-10-24 12:07, before JY-227) | 3,470 | 922 s (1 failed: `test_budgets.py::test_local_slow_hub_page_fails`) | |
| 26b38cb (last ~300 s NAS deploy) | 3,656 | 601 s | 250 s |
| dd51768 (main at branch time) | 3,862 | 531 s, 551 s | 269 s |
| 4149c4e (origin/main, 2026-10-26), back to back | 3,600 without scripts | | 258 s, 244 s |
| **JY-252**, back to back with the row above | 3,587 without scripts | | **212 s, 216 s** |
| **JY-252** full | 3,866 | **403 s** | 230 s |

Sum of per-test time by area, dd51768 → JY-252 (JUnit `time`, `-n 2`): `tests/hub` 511 → 334 s (−35 %), `tests/connectors` 35 → 21 s, `tests/deploy` 41 → 30 s.

## What was slow
1. **Every fresh app re-analyses every endpoint (the hot spot).** Most hub tests build a new app (`importlib.reload(hub.main)`). FastAPI 0.138 builds each route's state lazily on the first request that walks past it, once per app: ~55 ms on the laptop for a first `/healthz` on a fresh app against ~2 ms after. 80 % of that is `fastapi.routing.get_dependant` (signature + one pydantic `TypeAdapter` per parameter). In a cProfile of a third of `tests/hub` (1,046 tests), FastAPI route matching was 59 s of 228 s. Every new test that builds an app (all of the TV and guest rounds' tests) pays it again. On the NAS's slower CPU the share is larger, because the Windows file-system costs that pad the laptop numbers are not there (tmpfs since JY-235).
2. **The laptop's top 40 are all `tests/scripts`** (`test_joey_preview` release tests 21 s, `test_joey_worktree` list 17 s, `test_joey_closeout` 7–11 s each). That is Git for Windows' `sh`/`git` process start-up; JY-227 measured these tests as cheap on the NAS. Not changed.
3. **Grown files since 26b38cb**: `tests/deploy/test_deploy_script.py` +17.6 s (JY-240's nine `deploy.sh` runs under `sh`, ~2 s each on Windows, fast under Linux `sh`); `test_tv_mode.py` +4.6 s (the `_under_node` tests, which skip in the gate: no node in `life-test`); `test_guest_follow_scope.py` 4.6 s, `test_home_shelves.py` 3.5 s, `test_episode_ratings.py` +2.9 s: per-test app set-up, no single slow test. No new real `sleep`, timeout or `drain_extras` wait was found: the JY-243/244 drains wait only for reads already in flight.
4. Also measured, not changed: the registry load (`yaml.safe_load` of `config/areas.yaml`, 17.7 ms pure Python vs 2.0 ms with libyaml's `CSafeLoader`, ~1,800 loads per suite) made no measurable wall difference on the laptop, and it is hub code. Possible follow-up.

## The change
`tests/route_memo.py`, installed from `tests/conftest.py`, wraps `fastapi.routing.get_dependant`: the analysis is done once per worker for each (path, endpoint function, name, scopes, use_cache, scope), and each call gets a shallow copy (`dataclasses.replace` with a new `dependencies` list, so a route's own `dependencies=[...]` are added to that route only, and the cached properties that read the list are rebuilt). The copies are not fully independent: the sub-dependants inside the list, the parameter `ModelField`s and the other per-parameter lists are shared between copies. That is safe on 0.138.0 because FastAPI only reads them after `get_dependant` returns (it inserts into the top-level list only, and `get_flat_dependant` builds new lists); a FastAPI bump fails the version pin first, and then this has to be checked again. The memo holds its entries, endpoint functions included, strongly for the worker's life. Weak references are not a small change, because the key is a tuple that holds the function. The memo is bounded by the distinct endpoint functions: about 200, plus those of the few tests that reload a router module, and it is freed when the xdist worker exits. A reloaded or monkeypatched endpoint is a different function, so it is analysed afresh. Routing, validation, the dependencies and the endpoints all run as before; no test, assertion or marker changed. The memo is applied only on the pinned FastAPI (`hub/requirements.txt`, 0.138.0); any other version runs without it.

## Acceptance criteria
1. Full suite green with the change: `3865 passed, 1 skipped` (laptop, `-n 2`, 403 s; node installed, so the `_under_node` tests ran). After the rebase onto 4149c4e: `3894 passed, 1 skipped, 2 warnings in 403.07s` (2026-10-26).
2. No test deleted, skipped, moved behind a marker or weakened. The diff touches no existing test.
3. `tests/hub/test_route_memo.py` pins: the memo is on and its version equals the `hub/requirements.txt` pin and the installed FastAPI (a FastAPI bump fails here first); on any other FastAPI version `install()` returns False and leaves FastAPI's own `get_dependant` in place (review, 2026-10-26); dependencies run once per request on three fresh apps over one router and validation still answers 422; two calls get distinct dependency lists and an insert into one never reaches the other or the memo (fails if the memo hands out the shared object); the hub's same-origin guard refuses a cross-site `POST /media/follow/person/77` after each of three reloads.
4. Laptop time: non-tooling suite 258/244 s → 212/216 s back to back (−14 %); full suite 531–551 s → 403 s, below 26b38cb's 601 s.
5. NAS: the next deploys' `dur=` are recorded in the shipped notes (needs the NAS; not measured here).

## Data
None.

## Performance budget
Full gate (`deploy.sh`) ≤ 10 min. Measured on the laptop only (above); the NAS proof is the next deploys' `dur=`.

## Options and the pick
None: no screen.

## Out of scope
`deploy.sh` and the JY-240 memory bands (the last two deploys ran `-n 1` on 1,629–1,634 MB available); NAS load in the mornings; the Windows-only cost of the `tests/scripts` and `test_deploy_script` subprocess tests; hub code (the libyaml registry load).

## Accept checklist
- `tests/route_memo.py` and `tests/hub/test_route_memo.py` read sensibly; `tests/conftest.py` gains the install call only.
- The PR shows the full-suite output and the A/B lines.
- After the next deploy: `dur=` with `gate=-n2` near or under the 2026-10-24 level (281–305 s).

## Questions for B.
1. The last two deploys ran `-n 1` because the NAS had 1,629–1,634 MB available before the gate (JY-240 band 1,460–1,719 MB). That alone costs ~100–170 s. A) Leave the bands as they are (recommended: they hold the 1,200 MB floor). B) Open an item to find what holds NAS memory at deploy time.

## Shipped notes
- Closed out with `scripts/joey.py close-out`.
- PR: #198, squash-merged as `4a7e032` (4a7e0328f93e8b443486830cc56d4b80f75d3a54).
- Deploy: skipped: --deploy no
- Accept: in chat: "B., orchestrator session, 2026-10-24: Approve all changes. If I dont need to review any directions of changes, etc. Just close it out and apply the acceptance."
- Follow-ups: none
