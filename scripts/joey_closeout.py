"""joey.py close-out JY-### (JY-011): gates -> squash merge -> deploy -> verify -> shipped notes -> labels -> worktree.

  python scripts/joey.py close-out JY-### [--accepted-in-chat "<B.'s words, dated>"] [--deploy auto|yes|no]
                                          [--after-fail] [--timeout MIN] [--note TEXT ...] [--dry-run]

Run it from the main clone, not from the item's worktree (the last step removes that worktree).

1. Find the one OPEN PR whose head is feat/JY-###-*.
2. Gates (all checked, one FAIL row each, then a refusal with nothing changed): (a) open, not a draft, mergeable, base
   main; (b) the `ci` check on the head SHA concluded success; (c) a comment whose first line is `Review: ... PASS`,
   posted after the last push (the later of the head commit's date and its ci run's start); (d) B.'s accept: the
   `accepted` label, a comment that is exactly `accepted`, or --accepted-in-chat with B.'s words and a YYYY-MM-DD date.
3. Deploy decision: --deploy auto deploys unless every changed file is Markdown or under .github/.
   When deploying, the read-only NAS preflight runs BEFORE the merge, so its refusals change nothing: deploy window
   (07:00-21:30 Melbourne, not 23:45-00:00 UTC), wait for a running deploy, available memory >= 1,200 MB, last
   history.log line PASS / NOTHING-TO-DEPLOY (else --after-fail, the one retry).
4. --accepted-in-chat is posted as a PR comment; then ONE `gh pr merge N --squash --match-head-commit <sha>`.
   Read-back: state MERGED, merge commit on origin/main after git fetch.
5. Deploy: start deploy.sh (it detaches), wait for a new history line: PASS and new=<merge sha>.
6. Verify: NAS tree on the merge SHA; joey-hub / joey-media / joey-swag running and healthy (polls 10 s, up to 120 s,
   while any is `starting`); COMPOSE_PROFILES=edge,media; in-container smoke; /healthz inside joey-hub.
7. Shipped notes on chore/JY-###-shipped from origin/main (spec Status + Shipped notes, HITLIST row), PR, wait for
   its ci, squash-merge. 8. Labels: drop building/review/accept/accepted, add shipped. 9. joey.py worktree remove.

A FAIL stops everything after it; once the merge has happened the summary lists what is left. A failure after the
merge is finished by hand (re-running finds no open PR). --dry-run runs the read-only checks and prints DRY with the
command for every change. The NAS host comes from JOEY_NAS and is never printed.
Test seams: gh_run, nas, utc_now and sleep are module attributes that tests replace (and joey_common.ssh_run).
"""
import argparse
import datetime as dt
import json
import os
import re
import time
from pathlib import Path

import joey_common as jc
import joey_worktree

ID_RE = re.compile(r"^JY-\d{3}$")
DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
REVIEW_RE = re.compile(r"^Review:.*\bPASS\b")

REPO_NAS = "/volume1/Docker/joey/life-dashboard"
DEPLOY = REPO_NAS + "/deploy"
HISTORY = DEPLOY + "/history.log"
LOCK = "/tmp/joey-deploy.lock"
START_OUT = "/tmp/joey_closeout_deploy_start.txt"
AVAIL_MIN_MB = 1200
CONTAINERS = ("joey-hub", "joey-media", "joey-swag")
PROFILES_LINE = "COMPOSE_PROFILES=edge,media"
HEALTH_POLL_S, HEALTH_MAX_S = 10, 120
DEPLOY_POLL_S = 60
CI_POLL_S = 30
READBACK_S = 60
FILES_LIMIT = 100  # gh pr view --json files returns at most 100 files
STATUS_LABELS = ("building", "review", "accept", "accepted")
PR_FIELDS = ("number,title,state,isDraft,mergeable,mergeStateStatus,baseRefName,headRefName,headRefOid,labels,"
             "comments,commits,files,statusCheckRollup")
MELBOURNE = "Australia/Melbourne"


# ---------- seams (tests replace these) ----------
def utc_now():
    return dt.datetime.now(dt.timezone.utc)


sleep = time.sleep


def gh_run(args, timeout=120):
    """`gh <args>` (JOEY_GH fake in tests); stdout, or RuntimeError with the first output line."""
    try:
        p = jc.run([*jc.gh_cmd(), *args], timeout=timeout)
    except FileNotFoundError:
        raise RuntimeError("gh is not on PATH") from None
    if p.returncode != 0:
        msg = (p.stderr.strip() or p.stdout.strip() or "no output").splitlines()[0]
        raise RuntimeError(f"gh {' '.join(args[:2])} exited {p.returncode}: {msg}")
    return p.stdout


def nas(cmd, stdin=None, timeout=60):
    """One read on the NAS via joey_common.ssh; the host is masked in any error."""
    try:
        return jc.ssh(cmd, stdin=stdin, timeout=timeout)
    except RuntimeError as e:
        raise RuntimeError(_mask_host(str(e))) from None


def ssh_change(r, cmd, stdin=None, timeout=60):
    """A state change on the NAS through joey_common's Runner.ssh_change (DRY in a dry run); stdout, host masked."""
    try:
        return r.ssh_change(cmd, stdin=stdin, timeout=timeout).stdout.strip()
    except RuntimeError as e:
        raise RuntimeError(_mask_host(str(e))) from None


def _mask_host(text):
    host = os.environ.get("JOEY_NAS") or "root@nas.local"
    for h in sorted({host, host.split("@")[-1]}, key=len, reverse=True):
        text = text.replace(h, "<nas>")
    return text


# ---------- time ----------
def _first_sunday(year, month):
    d = dt.date(year, month, 1)
    return d + dt.timedelta(days=(6 - d.weekday()) % 7)


def melbourne_fallback(now_utc):
    """Melbourne time without a tz database: AEST (UTC+10), AEDT (UTC+11) from the first Sunday of October 02:00 AEST
    to the first Sunday of April 03:00 AEDT. Both changes fall at 16:00 UTC the day before."""
    def change(month):
        d = _first_sunday(now_utc.year, month) - dt.timedelta(days=1)
        return dt.datetime(d.year, d.month, d.day, 16, tzinfo=dt.timezone.utc)
    dst = now_utc >= change(10) or now_utc < change(4)
    return now_utc.astimezone(dt.timezone(dt.timedelta(hours=11 if dst else 10)))


def melbourne(now_utc):
    try:
        from zoneinfo import ZoneInfo
        return now_utc.astimezone(ZoneInfo(MELBOURNE))
    except Exception:  # noqa: BLE001 - no tz database (Windows without tzdata, slim images)
        return melbourne_fallback(now_utc)


def window_problem(now_utc):
    """None inside the deploy window, else why not."""
    mel = melbourne(now_utc)
    m = mel.hour * 60 + mel.minute
    if not 7 * 60 <= m < 21 * 60 + 30:
        return f"Melbourne time {mel:%H:%M} is outside the deploy window 07:00-21:30"
    if now_utc.hour * 60 + now_utc.minute >= 23 * 60 + 45:
        return f"UTC time {now_utc:%H:%M} is in the 15 minutes before 00:00 UTC (midnight-UTC test risk)"
    return None


def _ts(s):
    return dt.datetime.fromisoformat(str(s).replace("Z", "+00:00")) if s else None


# ---------- gates (pure: a `gh pr view` dict in, (ok, detail) out) ----------
def gate_open(v):
    ok = (v.get("state") == "OPEN" and not v.get("isDraft") and v.get("mergeable") == "MERGEABLE"
          and v.get("baseRefName") == "main")
    return ok, (f"state={v.get('state')} draft={v.get('isDraft')} mergeable={v.get('mergeable')} "
                f"({v.get('mergeStateStatus')}) base={v.get('baseRefName')}")


def ci_checks(v):
    out = []
    for c in v.get("statusCheckRollup") or []:
        if c.get("__typename") == "StatusContext":
            if c.get("context") == "ci":
                out.append({"status": "COMPLETED", "conclusion": (c.get("state") or "").upper(), "startedAt": None})
        elif c.get("workflowName") == "ci" or c.get("name") == "ci":
            out.append(c)
    return out


def gate_ci(v):
    checks = ci_checks(v)
    sha = (v.get("headRefOid") or "")[:7]
    if not checks:
        return False, f"no ci check on the head {sha}"
    bad = [c for c in checks if c.get("status") != "COMPLETED" or c.get("conclusion") != "SUCCESS"]
    if bad:
        return False, "ci on the head {} is {}".format(
            sha, ", ".join(f"{c.get('status')}/{c.get('conclusion') or '-'}" for c in bad))
    return True, f"ci SUCCESS on the head {sha}"


def push_time(v):
    """When the head was pushed: the later of the head commit's committedDate and its ci run's start (CI starts on
    the push, so a commit dated before a review but pushed after it still counts as later)."""
    head = v.get("headRefOid")
    commits = v.get("commits") or []
    hit = [c for c in commits if c.get("oid") == head] or commits
    times = [_ts(c.get("committedDate")) for c in hit]
    times += [_ts(c.get("startedAt")) for c in ci_checks(v)]
    times = [t for t in times if t]
    return max(times) if times else None


def _first_line(text):
    lines = (text or "").strip().splitlines()
    return lines[0].strip() if lines else ""


def gate_review(v):
    pushed = push_time(v)
    reviews = [c for c in v.get("comments") or [] if REVIEW_RE.match(_first_line(c.get("body")))]
    if not reviews:
        return False, "no `Review: ... PASS` comment"
    fresh = [c for c in reviews if pushed is None or _ts(c.get("createdAt")) > pushed]
    if not fresh:
        return False, (f"{len(reviews)} Review PASS comment(s), all before the last push "
                       f"({pushed:%Y-%m-%dT%H:%MZ}); a later commit needs a fresh review")
    return True, f"Review PASS at {fresh[-1].get('createdAt')} (last push {pushed:%Y-%m-%dT%H:%MZ})"


def gate_accept(v, in_chat):
    """(ok, detail, source for the shipped notes)."""
    if any(lab.get("name") == "accepted" for lab in v.get("labels") or []):
        return True, "label accepted", "the `accepted` label on the PR"
    for c in v.get("comments") or []:
        if (c.get("body") or "").strip().lower() == "accepted":
            return True, f"PR comment accepted ({c.get('createdAt')})", f"PR comment `accepted` ({c.get('createdAt')})"
    if in_chat is not None:
        words = in_chat.strip()
        if not words:
            return False, "--accepted-in-chat is empty", None
        if not DATE_RE.search(words):
            return False, "--accepted-in-chat needs B.'s words with a YYYY-MM-DD date", None
        return True, "accepted in chat (quoted, dated)", f'in chat: "{words}"'
    return False, "no `accepted` label, no `accepted` comment, no --accepted-in-chat", None


def deploy_decision(mode, paths):
    """(deploy?, reason)."""
    if mode == "yes":
        return True, "--deploy yes"
    if mode == "no":
        return False, "--deploy no"
    if len(paths) >= FILES_LIMIT:
        return True, f"the PR lists {len(paths)} files (gh caps at {FILES_LIMIT}): doc-only cannot be proven"
    other = [p for p in paths if not (p.lower().endswith(".md") or p.startswith(".github/"))]
    if not paths:
        return True, "the PR lists no files: doc-only cannot be proven"
    if not other:
        return False, "every changed file is Markdown or under .github/"
    return True, f"{len(other)} changed file(s) beyond Markdown and .github/, e.g. {other[0]}"


# ---------- NAS parsing ----------
CONTAINER_CMD = ("for c in " + " ".join(CONTAINERS) + "; do s=$(docker inspect -f "
                 "'{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{end}}' $c 2>/dev/null) "
                 "|| s=absent; echo \"$c $s\"; done")


def judge_containers(out):
    """('ok' | 'wait' | 'fail', detail) from CONTAINER_CMD output."""
    states = {}
    for line in out.splitlines():
        parts = line.split()
        if parts:
            states[parts[0]] = parts[1:]
    verdict, words = "ok", []
    for c in CONTAINERS:
        st = states.get(c) or ["absent"]
        status, health = st[0], (st[1] if len(st) > 1 else "")
        words.append(f"{c} {status}" + (f" {health}" if health else ""))
        if status != "running" or health == "unhealthy":
            verdict = "fail"
        elif health == "starting" and verdict == "ok":
            verdict = "wait"
    return verdict, "; ".join(words)


def history_ok(line, sha):
    """A history.log line that says PASS with new=<prefix of sha>."""
    m = re.search(r"\bnew=([0-9a-f]{7,40})\b", line)
    return bool(re.match(r"^\S+ PASS ", line) and m and sha.startswith(m.group(1)))


# ---------- shipped-notes edits (pure) ----------
def edit_spec(text, date, notes):
    lines = text.splitlines()
    si = next((i for i, x in enumerate(lines) if x.startswith("Status:")), None)
    if si is None:
        raise jc.Refused("the spec has no `Status:` line")
    hi = [i for i, x in enumerate(lines) if x.strip() == "## Shipped notes"]
    if len(hi) != 1:
        raise jc.Refused(f"the spec has {len(hi)} `## Shipped notes` headings (want 1)")
    lines[si] = f"Status: shipped {date}"
    start = hi[0] + 1
    end = next((i for i in range(start, len(lines)) if lines[i].startswith("## ")), len(lines))
    tail = lines[end:]
    return "\n".join(lines[:start] + notes + ([""] + tail if tail else [])) + "\n"


def edit_hitlist(text, item, pr, spec_path):
    lines = text.splitlines()
    rows = [i for i, x in enumerate(lines) if re.match(rf"^\|\s*{re.escape(item)}\s*\|", x)]
    if len(rows) != 1:
        raise jc.Refused(f"HITLIST.md has {len(rows)} rows for {item} (want 1)")
    cells = [c.strip() for c in lines[rows[0]].strip().strip("|").split("|")]
    if len(cells) != 7:
        raise jc.Refused(f"the HITLIST row for {item} has {len(cells)} cells (want 7)")
    cells[4] = "[x] shipped"
    if f"PR #{pr}" not in cells[5]:
        cells[5] = f"{cells[5]} · PR #{pr}"
    cells[6] = f"[{item}]({spec_path})"
    lines[rows[0]] = "| " + " | ".join(cells) + " |"
    return "\n".join(lines) + "\n"


def shipped_notes(pr, sha, deploy_line, accept, notes, date):
    out = [f"- Shipped {date} with `scripts/joey.py close-out`.",
           f"- PR: #{pr}, squash-merged as `{sha[:7]}` ({sha}).",
           f"- Deploy: {deploy_line}",
           f"- Accept: {accept}"]
    out += (["- Follow-ups:"] + [f"  - {n}" for n in notes]) if notes else ["- Follow-ups: none"]
    return out


# ---------- the run ----------
def close_out(r, a, st):
    item = a.id
    dry = r.dry

    def find_clone():
        if not ID_RE.match(item):
            raise jc.Refused(f"bad id {item!r}: want JY- and 3 digits, e.g. JY-011")
        st["clone"] = jc.clone_root()
        st["slug"] = jc.repo_slug(st["clone"])
        wt = joey_worktree.norm(st["clone"].parent / f"wt-{item}")
        here = joey_worktree.norm(os.getcwd())
        if here == wt or here.startswith(wt + os.sep):
            raise jc.Refused(f"run close-out from the main clone, not from inside wt-{item} (it gets removed)")
        return f"main clone {st['clone'].name}, repo {st['slug']}"

    def find_pr():
        prs = json.loads(gh_run(["pr", "list", "--repo", st["slug"], "--state", "all", "--limit", "200",
                                 "--json", "number,state,headRefName"]))
        mine = [p for p in prs if p["headRefName"].startswith(f"feat/{item}-")]
        open_ = [p for p in mine if p["state"] == "OPEN"]
        if len(open_) > 1:
            raise jc.Refused(f"{len(open_)} open PRs from feat/{item}-*: " + ", ".join(f"#{p['number']}" for p in open_))
        if not open_:
            other = ", ".join(f"#{p['number']} {p['state']}" for p in sorted(mine, key=lambda p: -p["number"]))
            raise jc.Refused(f"no open PR from feat/{item}-*" + (f" ({other})" if other else ""))
        st["pr"] = open_[0]["number"]
        st["branch"] = open_[0]["headRefName"]
        return f"PR #{st['pr']} from {st['branch']}"

    def read_pr():
        for _ in range(3):  # GitHub computes mergeable lazily: UNKNOWN right after a push
            v = json.loads(gh_run(["pr", "view", str(st["pr"]), "--repo", st["slug"], "--json", PR_FIELDS]))
            if v.get("mergeable") != "UNKNOWN":
                break
            sleep(5)
        st["view"] = v
        return f"#{v['number']} '{v.get('title', '')}' head {v['headRefOid'][:7]}, {len(v.get('files') or [])} files"

    r.step("find main clone", find_clone)
    r.step("find the open PR", find_pr)
    r.step("read the PR", read_pr)

    v = st["view"]
    failed = []

    def gate(letter, fn):
        def run():
            ok, detail = fn()[:2]
            if not ok:
                failed.append(letter)
            return ("PASS" if ok else "FAIL"), detail
        return run

    accept = gate_accept(v, a.accepted_in_chat)
    st["accept"] = accept[2]
    r.step("gate a: open, not draft, mergeable, base main", gate("a", lambda: gate_open(v)))
    r.step("gate b: ci success on the head SHA", gate("b", lambda: gate_ci(v)))
    r.step("gate c: Review PASS after the last push", gate("c", lambda: gate_review(v)))
    r.step("gate d: B.'s accept", gate("d", lambda: accept))

    def gates():
        if failed:
            raise jc.Refused(f"{len(failed)} gate(s) failed ({', '.join(failed)}): not merging")
        return "all four gates hold"

    r.step("gates", gates)

    paths = [f["path"] for f in v.get("files") or []]
    st["deploy"], st["deploy_reason"] = deploy_decision(a.deploy, paths)
    r.step("deploy decision", lambda: ("PASS", "deploy: " + st["deploy_reason"]) if st["deploy"]
           else ("SKIP", "no deploy: " + st["deploy_reason"]))
    st["left"] = (["merge"] + (["deploy", "verify"] if st["deploy"] else [])
                  + ["shipped notes", "labels", "worktree"])

    # ---- deploy preflight (read-only, before the merge) ----
    if st["deploy"]:
        def window():
            why = window_problem(utc_now())
            if why:
                raise jc.Refused(why)
            return f"Melbourne {melbourne(utc_now()):%H:%M}, inside 07:00-21:30"

        lock_cmd = f"p=$(cat {LOCK}/pid 2>/dev/null); [ -n \"$p\" ] && kill -0 \"$p\" 2>/dev/null && echo $p || true"

        def idle():
            t0 = utc_now()
            while True:
                pid = nas(lock_cmd).strip()
                if not pid:
                    return "no deploy running"
                if dry:
                    return f"a deploy is running (pid {pid}); a real run would wait up to {a.timeout} min"
                if (utc_now() - t0).total_seconds() >= a.timeout * 60:
                    raise jc.Refused(f"a deploy still holds {LOCK} after {a.timeout} min")
                sleep(DEPLOY_POLL_S)

        def memory():
            out = nas("free -m | awk 'NR==2{print $7}'").strip()
            mb = int(out.split()[-1])
            if mb < AVAIL_MIN_MB:
                raise jc.Refused(f"NAS available memory {mb} MB is under {AVAIL_MIN_MB} MB")
            return f"available {mb} MB (>= {AVAIL_MIN_MB})"

        def last_green():
            last = nas(f"tail -1 {HISTORY}").strip()
            green = re.match(r"^\S+ (PASS|NOTHING-TO-DEPLOY) ", last)
            if not green and not a.after_fail:
                raise jc.Refused(f"last history line is not green: {last} - look first; --after-fail is the one retry")
            return f"last history line: {last}" + ("" if green else " (--after-fail: the one retry)")

        r.step("deploy.1 deploy window", window)
        r.step("deploy.2 no deploy running (waits)", idle)
        r.step("deploy.3 NAS available memory", memory)
        r.step("deploy.4 last deploy green", last_green)

    # ---- merge ----
    pr, slug, head = str(st["pr"]), st["slug"], v["headRefOid"]

    if a.accepted_in_chat is not None and st["accept"] and st["accept"].startswith("in chat"):
        def record_accept():
            body = f"accepted in chat: {a.accepted_in_chat.strip()}"
            r.write_guard(f"gh pr comment {pr} --body \"{body}\"")
            gh_run(["pr", "comment", pr, "--repo", slug, "--body", body])
            return "B.'s words posted as a PR comment"
        r.step("record the accept from chat", record_accept)

    def merge():
        cmd = ["pr", "merge", pr, "--repo", slug, "--squash", "--match-head-commit", head]
        r.write_guard("gh " + jc.cmd_text(cmd))
        gh_run(cmd)  # ONE call, no retries
        st["merged"] = True
        return "gh pr merge exit 0"

    def readback():
        r.write_guard(f"gh pr view {pr} --json state,mergeCommit; git fetch origin; "
                      "git merge-base --is-ancestor <merge sha> origin/main")
        t0 = utc_now()
        while True:
            m = json.loads(gh_run(["pr", "view", pr, "--repo", slug, "--json", "state,mergeCommit"]))
            if m.get("state") == "MERGED":
                break
            if (utc_now() - t0).total_seconds() >= READBACK_S:
                raise jc.Refused(f"PR #{pr} is {m.get('state')} {READBACK_S} s after the merge call")
            sleep(5)
        sha = (m.get("mergeCommit") or {}).get("oid") or ""
        if not sha:
            raise jc.Refused("MERGED but no merge commit reported")
        jc.git("fetch", "origin", cwd=st["clone"])
        rc = jc.run(["git", "merge-base", "--is-ancestor", sha, "origin/main"], cwd=st["clone"]).returncode
        if rc != 0:
            raise jc.Refused(f"merge commit {sha[:7]} is not on origin/main after git fetch")
        st["sha"] = sha
        return f"MERGED as {sha[:7]}, on origin/main"

    r.step("merge.1 gh pr merge --squash (one call)", merge)
    r.step("merge.2 read-back: MERGED, on origin/main", readback)
    st["left"].remove("merge")
    sha = st.get("sha", "")
    show_sha = sha[:7] or "<merge sha>"

    # ---- deploy + verify ----
    if st["deploy"]:
        def start():
            cmd = (f"n=$(wc -l < {HISTORY}); cd {DEPLOY} && (sh deploy.sh > {START_OUT} 2>&1 &) ; sleep 8; "
                   f"echo \"lines=$n\"; head -3 {START_OUT}")
            out = ssh_change(r, cmd, timeout=60)
            m_n = re.search(r"lines=\s*(\d+)", out)
            m_log = re.search(r"log: (\S+)", out)
            if "another deploy is running" in out or not (m_n and m_log):
                raise jc.Refused("deploy.sh did not start: " + " | ".join(out.splitlines()[:3])[:200])
            st["hist_n"], st["deploy_log"] = int(m_n.group(1)), m_log.group(1)
            return f"deploy.sh running detached, log {st['deploy_log']}"

        def wait():
            r.write_guard(f"poll {HISTORY} every {DEPLOY_POLL_S} s, up to {a.timeout} min, for PASS new={show_sha}")
            t0, last = utc_now(), ""
            while (utc_now() - t0).total_seconds() < a.timeout * 60:
                n = int(nas(f"wc -l < {HISTORY}").strip() or 0)
                if n > st["hist_n"]:
                    line = nas(f"tail -1 {HISTORY}").strip()
                    st["history"] = line
                    if not history_ok(line, sha):
                        tail = nas(f"grep -E 'FAIL|Error|passed|failed' {st['deploy_log']} | tail -8")
                        r.log("deploy log tail:\n" + tail)
                        raise jc.Refused(f"history line is not PASS on {sha[:7]}: {line}")
                    return line
                prog = nas(f"grep -E '^== ' {st['deploy_log']} | tail -1").strip()
                if prog and prog != last:
                    r.log(f"  deploy: {prog[-90:]}")
                    last = prog
                sleep(DEPLOY_POLL_S)
            raise jc.Refused(f"no new history line after {a.timeout} min (log {st['deploy_log']})")

        r.step("deploy.5 start deploy.sh (self-detaching)", start)
        r.step("deploy.6 history line PASS on the merge SHA", wait)
        st["left"].remove("deploy")

        def tree():
            cmd = f"docker run --rm -v {REPO_NAS}:/work -w /work alpine/git rev-parse HEAD"
            r.write_guard(f"ssh <nas> '{cmd}' == {show_sha}")
            got = nas(cmd, timeout=120).splitlines()[-1].strip()
            if got != sha:
                raise jc.Refused(f"NAS tree on {got[:7]}, expected {sha[:7]}")
            return f"NAS tree on {sha[:7]}"

        def containers():
            r.write_guard(f"ssh <nas> docker inspect {' '.join(CONTAINERS)} (poll {HEALTH_POLL_S} s while starting, "
                          f"up to {HEALTH_MAX_S} s)")
            waited = 0
            while True:
                verdict, detail = judge_containers(nas(CONTAINER_CMD))
                if verdict == "ok":
                    return detail + (f" (after {waited} s)" if waited else "")
                if verdict == "fail":
                    raise jc.Refused(detail)
                if waited >= HEALTH_MAX_S:
                    raise jc.Refused(f"still starting after {HEALTH_MAX_S} s: {detail}")
                sleep(HEALTH_POLL_S)
                waited += HEALTH_POLL_S

        def profiles():
            cmd = f"grep -E '^COMPOSE_PROFILES=' {DEPLOY}/.env"
            r.write_guard(f"ssh <nas> \"{cmd}\" == {PROFILES_LINE}")
            line = nas(cmd).strip()
            if line != PROFILES_LINE:
                raise jc.Refused(f"{line or 'no COMPOSE_PROFILES line'} (want {PROFILES_LINE})")
            return line

        def smoke():
            cmd = (f"cd {DEPLOY} && docker compose exec -T joey-media python tests/deploy/smoke.py --front media 2>&1; "
                   "echo rc=$?")
            r.write_guard(f"ssh <nas> '{cmd}'")
            out = nas(cmd, timeout=120)
            tail = " ".join(out.split())[-160:]
            if not out.strip().endswith("rc=0"):
                raise jc.Refused(tail)
            return tail

        healthz_py = ("import json, urllib.request\n"
                      "print(urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=5).read().decode())\n")

        def healthz():
            r.write_guard("ssh <nas> 'docker exec -i joey-hub python -' < GET http://127.0.0.1:8000/healthz")
            out = nas("docker exec -i joey-hub python -", stdin=healthz_py)
            try:
                h = json.loads(out.splitlines()[-1])
            except (ValueError, IndexError):
                raise jc.Refused("/healthz did not answer JSON: " + out[-120:]) from None
            if h.get("status") != "ok":
                raise jc.Refused(f"/healthz status {h.get('status')!r}")
            key = next((k for k in ("sha", "commit", "git_sha", "version") if k in h), None)
            if key is None:
                r.log("INFO  the hub's /healthz exposes no commit SHA; NAS tree checked in verify.1 instead")
                return f"status ok, front {h.get('front')}"
            if not str(sha).startswith(str(h[key])[:7]):
                raise jc.Refused(f"/healthz {key}={str(h[key])[:12]}, expected {sha[:7]}")
            return f"status ok, {key} {str(h[key])[:7]}"

        r.step("verify.1 NAS tree on the merge SHA", tree)
        r.step("verify.2 joey-hub / joey-media / joey-swag running healthy", containers)
        r.step("verify.3 COMPOSE_PROFILES=edge,media", profiles)
        r.step("verify.4 in-container smoke --front media", smoke)
        r.step("verify.5 /healthz inside joey-hub", healthz)
        st["left"].remove("verify")

    # ---- shipped notes ----
    clone = st["clone"]
    chore = f"chore/{item}-shipped"
    docs_wt = clone.parent / f"wt-{item}-shipped"
    date = f"{melbourne(utc_now()):%Y-%m-%d}"

    def docs_find():
        names = jc.git("ls-tree", "--name-only", "origin/main", "docs/specs/", cwd=clone).splitlines()
        specs = [n for n in names if Path(n).name.startswith(f"{item}-") and n.endswith(".md")]
        if len(specs) != 1:
            raise jc.Refused(f"{len(specs)} spec files docs/specs/{item}-*.md on origin/main (want 1)")
        st["spec_path"] = specs[0]
        deploy_line = (f"`{st['history']}`" if st.get("history") else
                       "(dry run: the history line goes here)" if st["deploy"] else f"skipped: {st['deploy_reason']}")
        notes = shipped_notes(st["pr"], sha or "<merge sha>", deploy_line, st["accept"], a.note or [], date)
        spec_old = jc.git("show", f"origin/main:{specs[0]}", cwd=clone) + "\n"
        hit_old = jc.git("show", "origin/main:HITLIST.md", cwd=clone) + "\n"
        st["spec_new"] = edit_spec(spec_old, date, notes)
        st["hit_new"] = edit_hitlist(hit_old, item, st["pr"], specs[0])
        if jc.run(["git", "show-ref", "--verify", "--quiet", f"refs/heads/{chore}"], cwd=clone).returncode == 0:
            raise jc.Refused(f"branch {chore} already exists locally")
        if docs_wt.exists():
            raise jc.Refused(f"{docs_wt.name} already exists")
        return f"{specs[0]} and the HITLIST row for {item} found on origin/main"

    def docs_branch():
        r.change(["git", "worktree", "add", str(docs_wt), "-b", chore, "origin/main"], cwd=clone)
        return f"{docs_wt.name} on {chore} from origin/main"

    def docs_commit():
        r.write_guard(f"write {st['spec_path']} + HITLIST.md, commit, git push origin {chore}")
        (docs_wt / st["spec_path"]).write_text(st["spec_new"], encoding="utf-8", newline="\n")
        (docs_wt / "HITLIST.md").write_text(st["hit_new"], encoding="utf-8", newline="\n")
        jc.git("add", st["spec_path"], "HITLIST.md", cwd=docs_wt)
        jc.git("commit", "-q", "-m", f"{item}: shipped (PR #{st['pr']})", cwd=docs_wt)
        jc.git("push", "-q", "origin", chore, cwd=docs_wt)
        st["docs_head"] = jc.git("rev-parse", "HEAD", cwd=docs_wt)
        return f"pushed {chore} at {st['docs_head'][:7]}"

    def docs_pr():
        body = (f"Close-out of {item} (PR #{st['pr']}): spec Status and Shipped notes, HITLIST row shipped.\n\n"
                "Made by `scripts/joey.py close-out`.\n\n"
                "\U0001F916 Generated with [Claude Code](https://claude.com/claude-code)")
        cmd = ["pr", "create", "--repo", slug, "--base", "main", "--head", chore,
               "--title", f"{item}: shipped (PR #{st['pr']})", "--body", body]
        r.write_guard("gh " + jc.cmd_text(cmd[:10]))
        out = gh_run(cmd)
        m = re.search(r"/pull/(\d+)", out)
        if not m:
            raise jc.Refused("gh pr create gave no PR URL")
        st["docs_pr"] = m.group(1)
        return f"PR #{st['docs_pr']}"

    def docs_ci():
        r.write_guard(f"poll the docs PR's ci check every {CI_POLL_S} s, up to {a.timeout} min")
        t0 = utc_now()
        while True:
            dv = json.loads(gh_run(["pr", "view", st["docs_pr"], "--repo", slug, "--json",
                                    "headRefOid,statusCheckRollup"]))
            checks = ci_checks(dv)
            if dv.get("headRefOid") == st["docs_head"] and checks and \
                    all(c.get("status") == "COMPLETED" for c in checks):
                ok, detail = gate_ci(dv)
                if not ok:
                    raise jc.Refused(detail)
                return detail
            if (utc_now() - t0).total_seconds() >= a.timeout * 60:
                raise jc.Refused(f"the docs PR's ci did not finish within {a.timeout} min")
            sleep(CI_POLL_S)

    def docs_merge():
        cmd = ["pr", "merge", st.get("docs_pr", "<docs PR>"), "--repo", slug, "--squash", "--match-head-commit",
               st.get("docs_head", "<docs head>")]
        r.write_guard("gh " + jc.cmd_text(cmd))
        gh_run(cmd)
        m = json.loads(gh_run(["pr", "view", st["docs_pr"], "--repo", slug, "--json", "state"]))
        if m.get("state") != "MERGED":
            raise jc.Refused(f"docs PR #{st['docs_pr']} is {m.get('state')} after the merge call")
        return f"docs PR #{st['docs_pr']} MERGED"

    def docs_cleanup():
        r.change(["git", "worktree", "remove", str(docs_wt)], cwd=clone)
        r.change(["git", "branch", "-D", chore], cwd=clone)
        return f"{docs_wt.name} and {chore} removed locally"

    r.step("docs.1 find the spec and the HITLIST row", docs_find)
    r.step("docs.2 branch chore/JY-###-shipped", docs_branch)
    r.step("docs.3 write, commit, push", docs_commit)
    r.step("docs.4 open the docs PR", docs_pr)
    r.step("docs.5 docs PR ci success", docs_ci)
    r.step("docs.6 squash-merge the docs PR", docs_merge)
    r.step("docs.7 remove the docs worktree", docs_cleanup)
    st["left"].remove("shipped notes")

    # ---- labels ----
    def labels():
        have = {lab.get("name") for lab in v.get("labels") or []}
        drop = [x for x in STATUS_LABELS if x in have]
        cmd = ["pr", "edit", pr, "--repo", slug, "--add-label", "shipped"]
        if drop:
            cmd += ["--remove-label", ",".join(drop)]
        r.write_guard("gh " + jc.cmd_text(cmd))
        gh_run(cmd)
        return "shipped added" + (f", removed {', '.join(drop)}" if drop else "")

    r.step("labels: shipped", labels)
    st["left"].remove("labels")

    # ---- worktree ----
    target = joey_worktree.norm(clone.parent / f"wt-{item}")
    present = any(joey_worktree.norm(w["path"]) == target for w in joey_worktree.worktrees(clone))
    if not present:
        r.step("worktree remove", lambda: ("SKIP", f"no worktree wt-{item}"))
    elif dry:
        r.step("worktree remove", lambda: r.write_guard(f"joey.py worktree remove {item}"))
    else:
        r.log(f"--- joey.py worktree remove {item} ---")
        joey_worktree.cmd_remove(r, argparse.Namespace(id=item, path=None, dry_run=False))
    st["left"].remove("worktree")


def build_parser():
    p = argparse.ArgumentParser(prog="joey.py close-out",
                                description="Merge, deploy, verify and close out one Joey item (JY-011).")
    p.add_argument("id", help="JY-###")
    p.add_argument("--accepted-in-chat", metavar="TEXT",
                   help="B.'s accept words from chat, quoted, with a YYYY-MM-DD date (posted on the PR, kept verbatim)")
    p.add_argument("--deploy", choices=("auto", "yes", "no"), default="auto",
                   help="auto (default): deploy unless every changed file is Markdown or under .github/")
    p.add_argument("--after-fail", action="store_true",
                   help="deploy although the last history.log line is not green (the one retry)")
    p.add_argument("--timeout", type=int, default=90, help="minutes to wait for a deploy or the docs PR's ci (90)")
    p.add_argument("--note", action="append", help="a follow-up for the shipped notes (repeatable)")
    p.add_argument("--dry-run", action="store_true", help="read-only checks run; every change prints DRY")
    return p


def main(argv):
    a = build_parser().parse_args(argv)
    try:
        logs = jc.log_dir(jc.clone_root())
    except Exception:  # noqa: BLE001 - not in a git repo: the first step reports it
        logs = None
    r = jc.Runner("close-out", dry_run=a.dry_run, log_dir=logs)
    st = {}

    def body(runner):
        try:
            close_out(runner, a, st)
        except jc.Stop:
            if st.get("merged"):
                runner.log("not done: " + ", ".join(st.get("left") or []))
            else:
                runner.log("nothing changed: the PR is not merged")
            raise

    return r.execute(f"close-out {a.id}", body)
