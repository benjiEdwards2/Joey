# JY-241 joey.py crashes printing non-cp1252 text to a Windows pipe

Status: building
Size: S
Live risk: none
Area: `scripts/joey.py`, `scripts/joey_common.py`, `scripts/budgets.py`, `tests/scripts/`
Needs: none
Options page: none: no screen

Source: found 2026-10-24 closing out JY-235.

## Problem
`python scripts/joey.py close-out JY-235 ...` with stdout piped crashed in `joey_common.Runner.log` (`print(line, flush=True)`) with `UnicodeEncodeError: 'charmap' codec can't encode character '≤'`: the PR title contains a less-than-or-equal sign. The step never finished and the close-out silently did nothing. Workaround was `PYTHONIOENCODING=utf-8`.

## Acceptance criteria
1. `joey.py` `main` makes stdout and stderr UTF-8 with `errors="replace"` (`joey_common.utf8_stdio()`, guarded with `hasattr(stream, "reconfigure")`); `budgets.py` `main` does the same.
2. The log file writes are already explicit UTF-8 (`Runner.log`); a test proves a non-cp1252 line lands in the log intact.
3. Tests, with `PYTHONIOENCODING=cp1252` and stdout piped: `joey.py worktree list` with a branch named with a less-than-or-equal sign and an emoji exits 0 and the line is in stdout and the log (fails without the fix, checked by hand); `Runner.log` after `utf8_stdio()` prints and logs the same text; `budgets.main` prints it.
4. No other test is weakened, skipped or deleted.

## Data
None.

## Performance budget
None apply.

## Out of scope
Other entry points (`deploy/`, hub code); only the two CLIs under `scripts/` named above.

## Accept checklist
`PYTHONIOENCODING=cp1252` and a piped `joey.py close-out` on a PR with a non-ASCII title finishes.

## Shipped notes
