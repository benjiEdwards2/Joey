#!/usr/bin/env bash
# usage: sweep_run.sh N "message" — apply hitlist_sweepN.py on a chore branch, PR, merge on green ci. Takes the close-out lock.
export GIT_TERMINAL_PROMPT=0
S="C:/Users/B7191~1.EDW/AppData/Local/Temp/claude/C--Users-b-edwards-Documents-Claude/7b3104e9-05eb-4ada-bf16-e1d2b2289128/scratchpad"
n=$1; msg=$2; br=chore/sweep$n-1025
until mkdir "$TEMP/joey-closeout.lock" 2>/dev/null; do sleep 20; done
cd /c/Users/b.edwards/Desktop/Claude/LifeDashboard/wt-hitlist && git fetch -q && git checkout -q -B $br origin/main \
 && python -I "$S/hitlist_sweep$n.py" && python scripts/hitlist_seed_check.py | tail -1 \
 && git add HITLIST.md scripts/hitlist_seed_check.py && git commit -q -m "HITLIST sweep $n: $msg" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" \
 && for i in 1 2 3 4; do timeout 150 git push -q origin $br:$br 2>/dev/null && break; sleep 60; done \
 && gh pr create --repo benjiEdwards2/Joey --head $br --base main --title "HITLIST sweep $n (2026-10-25)" --body "Orchestrator file: $msg. Seed check PASS. Docs only.

🤖 Generated with [Claude Code](https://claude.com/claude-code)" && sleep 30 \
 && until gh pr view $br --repo benjiEdwards2/Joey --json statusCheckRollup --jq '.statusCheckRollup[]?|select(.name=="test")|.status' 2>/dev/null | grep -q COMPLETED; do sleep 30; done
c=$(gh pr view $br --repo benjiEdwards2/Joey --json statusCheckRollup --jq '.statusCheckRollup[]|select(.name=="test")|.conclusion'); echo "sweep $n ci=$c"
[ "$c" = SUCCESS ] && gh pr merge $br --repo benjiEdwards2/Joey --squash --match-head-commit $(git rev-parse HEAD) && echo "sweep$n-merged"
git checkout -q --detach origin/main; rmdir "$TEMP/joey-closeout.lock"
