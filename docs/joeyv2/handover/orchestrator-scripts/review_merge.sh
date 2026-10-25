#!/usr/bin/env bash
# usage: review_merge.sh PR JY-### review.md  — post the review, mark ready, wait for ci, close out with --deploy no.
export GIT_TERMINAL_PROMPT=0
SCR="C:/Users/B7191~1.EDW/AppData/Local/Temp/claude/C--Users-b-edwards-Documents-Claude/7b3104e9-05eb-4ada-bf16-e1d2b2289128/scratchpad"
pr=$1; id=$2; body=$3
gh pr comment $pr --repo benjiEdwards2/Joey --body-file "$body" >/dev/null && echo "$id review posted"
gh pr ready $pr --repo benjiEdwards2/Joey 2>/dev/null
sleep 15
until gh pr view $pr --repo benjiEdwards2/Joey --json statusCheckRollup --jq '.statusCheckRollup[]?|select(.name=="test")|.status' 2>/dev/null | grep -q COMPLETED; do sleep 30; done
echo "$id ci=$(gh pr view $pr --repo benjiEdwards2/Joey --json statusCheckRollup --jq '.statusCheckRollup[]|select(.name=="test")|.conclusion')"
# close-outs share the clone: one at a time
until mkdir "$TEMP/joey-closeout.lock" 2>/dev/null; do sleep 20; done
bash "$SCR/closeout_chain.sh" "$id:new:${4:-no}" 2>&1 | tail -8
rmdir "$TEMP/joey-closeout.lock"
