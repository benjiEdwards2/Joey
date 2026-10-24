# JY-234 Preview lock follow-ups

Status: building
Size: S
Live risk: NAS write (the preview lock scripts only; reviewed as L)
Area: `scripts/joey_preview.py` (lock scripts, `LOCK_HOLD_S`), `tests/scripts/test_joey_preview.py`, `deploy/preview/README.md`
Needs: JY-228 (shipped), JY-239 (shipped)
Options page: none: no screen

Source: the JY-228 Opus verifier's low-probability should-fixes (PR #63), 2026-10-24.

## Problem
Four small gaps in the preview's hold on the deploy lock, each unlikely:
1. PID reuse: the release sends TERM to whatever pid is in `LOCK/pid`. If the holder died and the kernel gave its pid to another process, that process gets the TERM.
2. Races: the holder checks `LOCK/owner` and then writes `LOCK/pid`, and both the holder's exit trap and the release check the owner and then remove the lock. A deploy that clears and retakes the lock in between could have its lock damaged.
3. Hold vs teardown: the holder gives the lock up after 60 min, but the step timeouts from the take to the release (replace, 30 min build, 14 min health poll, teardown) add up to about 77 min. A slow run could lose the lock mid-teardown.
4. Where `sleep 0.1` is not supported, each wait loop is 50 naps of 1 s, close to the 60 s ssh timeout.

## Acceptance criteria
1. The release signals the pid in `LOCK/pid` only while that process is alive and its `/proc/<pid>/cmdline` carries this run's token (the holder is `sh -c '<script>'` and its script holds the token). Otherwise (another command line, an empty one such as a zombie's, or no `/proc`) the holder counts as gone: no signal, and the lock is removed. Tested with a fake `/proc` and stand-in `kill` (reused pid, no `/proc`, zombie, own holder) and with a real unrelated process.
2. The holder writes its pid to `LOCK/.pid.<pid>`, checks the owner, then renames it to `LOCK/pid` (`mv`, atomic). If the lock was replaced after the check, the mv fails and the holder exits: it never writes its pid into another lock. If the owner changed before the check, the temp file is removed. Cleanup paths remove any `.pid.*` file too. Tested with stand-in `mv` and `echo` that replace the lock or change the owner at that exact point.
3. What remains is documented in `s_lock_take`: the owner check followed by `rm` (holder trap, release) has a microsecond window in which a deploy.sh that clears this lock as stale could lose its pid file. It needs the holder already dead at that instant, and is the same class as deploy.sh's own stale check followed by `rm -rf`; sh has no atomic compare-and-remove.
4. `LOCK_HOLD_S` is 88 min: at least 5 min over the worst case of every NAS call timeout plus laptop sleep from the take to the release (77 min measured by the test over three slow paths: no `/healthz`, last-poll then memory floor, last-poll success), and under close-out's 90 min wait. The test reads both numbers from the code (fake NAS records each call's timeout; close-out's parser default).
5. The wait loops nap at most `$naps` times: 50 x 0.1 s where `sleep 0.1` works, else 10 x 1 s, so each loop waits at most 10 s. Tested by counting a stand-in `sleep`'s calls (no wall clock).
6. JY-239's rule stands: an unreadable stat is alive in `SH_ALIVE` (unchanged). BusyBox ash and dash only. Docker commands keep `</dev/null`.
7. No test is weakened, skipped or deleted. 2026-10-24, rule 4: `test_lock_scripts_use_deploy_sh_format` pinned `echo $$ > LOCK/pid`; it now pins `echo $$ > LOCK/.pid.$$` and `mv -f LOCK/.pid.$$ LOCK/pid` (criterion 2).

## Data
None.

## Performance budget
NAS available memory >= 1,200 MB (unchanged). A dead laptop now blocks deploys for up to 88 min instead of 60.

## Options and the pick
None: no screen.

## Out of scope
A heartbeat that extends the hold while the laptop is alive (more ssh round trips for a low-probability case). Changes to `deploy.sh` or close-out. The lock.log tail (cosmetic).

## Accept checklist
- CI green; review posted; optional live check in the window: `preview up main`, `preview down`, `/tmp/joey-deploy.lock` gone afterwards.

## Questions for B.
None.

## Shipped notes
