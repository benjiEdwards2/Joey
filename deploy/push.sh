#!/usr/bin/env bash
# Joey push — run from YOUR COMPUTER (Mac / Linux, or Git Bash on Windows), not on the NAS.
# Shows every update on GitHub main that the NAS is not running yet, then (after you say yes) runs
# deploy.sh on the NAS over ssh. deploy.sh stays the only path to production (rule 13); this is a front end.
#
#   deploy/push.sh                 list the pending updates, ask, deploy
#   deploy/push.sh --list          only list the pending updates (no deploy)
#   deploy/push.sh --search WORD   list pending updates whose message mentions WORD (case-insensitive)
#   deploy/push.sh --history [N]   the last N deploys from deploy/history.log (default 15)
#   deploy/push.sh --all [N]       the last N updates on main, deployed or not (default 30)
#   deploy/push.sh --yes           deploy without asking
#
# The NAS: set JOEY_NAS (e.g. export JOEY_NAS=root@192.168.68.59), else root@nas.local is tried.
# Needs ssh access as root to the NAS (the same login you use for deploy.sh). Works on your home network.
set -euo pipefail

NAS="${JOEY_NAS:-root@nas.local}"
REPO=/volume1/Docker/joey/life-dashboard
# git has no host binary on the NAS: every call goes through alpine/git with the deploy key, as in deploy.sh
GIT="docker run --rm -v $REPO:/work -v /root/.ssh:/root/.ssh:ro -w /work -e GIT_SSH_COMMAND='ssh -i /root/.ssh/joey_deploy' alpine/git"
FMT="'--format=%h  %ad  %s' '--date=format:%Y-%m-%d %H:%M'"   # quoted for the NAS shell

mode=deploy search="" n="" yes=0
while [ $# -gt 0 ]; do
    case "$1" in
        --list) mode=list ;;
        --search) mode=list; search="${2:?--search needs a word}"; shift
                  [[ "$search" == *"'"* ]] && { echo "--search: no ' in the word, please" >&2; exit 64; } ;;
        --history) mode=history; n="${2:-}"; [[ "$n" =~ ^[0-9]+$ ]] && shift || n="" ;;
        --all) mode=all; n="${2:-}"; [[ "$n" =~ ^[0-9]+$ ]] && shift || n="" ;;
        --yes|-y) yes=1 ;;
        -h|--help) sed -n 2,14p "$0"; exit 0 ;;
        *) echo "unknown option: $1 (try --help)" >&2; exit 64 ;;
    esac
    shift
done

nas() { ssh "$NAS" "$@"; }

case "$mode" in
    history)
        echo "== last ${n:-15} deploys on the NAS (newest last) =="
        nas "tail -n ${n:-15} $REPO/deploy/history.log"
        exit 0 ;;
    all)
        echo "== last ${n:-30} updates on GitHub main =="
        nas "$GIT fetch -q origin main && $GIT log -n ${n:-30} $FMT origin/main"
        echo; echo "NAS is running: $(nas "$GIT log -1 $FMT HEAD")"
        exit 0 ;;
esac

echo "== checking GitHub for updates ($NAS) =="
nas "$GIT fetch -q origin main"
grep=""; [ -n "$search" ] && grep="-i '--grep=$search'"
pending=$(nas "$GIT log --reverse $grep $FMT HEAD..origin/main")
echo "NAS is running: $(nas "$GIT log -1 $FMT HEAD")"
echo
if [ -z "$pending" ]; then
    if [ -n "$search" ]; then echo "No pending update mentions \"$search\"."; else echo "Up to date — nothing to deploy."; fi
    exit 0
fi
echo "== pending updates (oldest first)${search:+ matching \"$search\"} =="
echo "$pending"
echo
[ "$mode" = list ] && exit 0

if [ "$yes" -eq 0 ]; then
    read -r -p "Deploy these to Joey now? [y/N] " answer
    [[ "$answer" =~ ^[Yy] ]] || { echo "Not deployed."; exit 0; }
fi
echo "== deploying (tests run on the NAS first; this takes several minutes) =="
nas "$REPO/deploy/deploy.sh"
echo
echo "== result =="
nas "tail -n 1 $REPO/deploy/history.log"
