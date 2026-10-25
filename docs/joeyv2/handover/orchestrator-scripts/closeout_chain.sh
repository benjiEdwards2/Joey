#!/usr/bin/env bash
# Run Joey close-outs one after another; retry an item (with --resume) when it stops on a GitHub/git timeout.
# usage: closeout_chain.sh "JY-229:resume:no" "JY-233:resume:auto" "JY-144:new:auto" ...
A="B., orchestrator session, 2026-10-24: Approve all changes. If I dont need to review any directions of changes, etc. Just close it out and apply the acceptance."
export JOEY_NAS=root@192.168.68.59 GIT_TERMINAL_PROMPT=0 PYTHONIOENCODING=utf-8
cd /c/Users/b.edwards/Desktop/Claude/LifeDashboard/life-dashboard || exit 1
for spec in "$@"; do
  id=${spec%%:*}; rest=${spec#*:}; mode=${rest%%:*}; dep=${rest#*:}
  for t in 1 2 3 4; do
    git fetch -q; git merge -q --ff-only origin/main
    flags="--deploy $dep"; { [ "$mode" = resume ] || [ $t -gt 1 ]; } && flags="$flags --resume"
    out=$(python scripts/joey.py close-out "$id" $flags --accepted-in-chat "$A" 2>&1)
    echo "== $id try $t ($flags)"; echo "$out" | grep -E "^(FAIL|SKIP|WARN)|summary|REFUSED|merge.2|deploy.6|docs.6" | cut -c1-180
    echo "$out" | grep -qE "TimeoutExpired|timed out|merge conflicts" || break
    sleep 90
  done
done
