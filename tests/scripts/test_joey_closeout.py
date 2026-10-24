"""JY-011: scripts/joey.py close-out with a fake gh, a fake NAS and a fake clock. No network; no test reads docs/ or
HITLIST.md from this repo (the gate image drops docs/, and the real files change when items ship): inline fixtures.

Two worlds. `lw` (light) has no git at all: clone_root/repo_slug are faked, so the gate, window and other refusals that
stop before the merge cost no repo. `w` (full) gets a throwaway bare origin + clone (and the item's worktree), copied
from a template built once per session (JY-227); FakeGh squash-merges for real into the bare origin (merge-tree +
commit-tree), so the read-back, --resume, the docs PR and worktree remove see real git state. Runner.ssh_change reaches
FakeNas through joey_common.ssh_run. Most tests call joey_closeout.main() in-process; one runs the CLI as a subprocess
through JOEY_GH. Skips when git is not on PATH."""
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
JOEY = REPO_ROOT / "scripts" / "joey.py"
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import joey_closeout as jco  # noqa: E402
import joey_common  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not on PATH")

GH_URL = "https://github.com/example/joey.git"
ITEM, SLUG = "JY-011", "close-out"
BRANCH = f"feat/{ITEM}-{SLUG}"
CHORE = f"chore/{ITEM}-shipped"
SPEC = f"docs/specs/{ITEM}-{SLUG}.md"
NOON_AEDT = dt.datetime(2026, 10, 23, 1, 0, tzinfo=dt.timezone.utc)  # 12:00 Melbourne
FAKE_OID = "1" * 40

SPEC_TEXT = f"""# {ITEM} close-out

Status: building
Size: L

## Acceptance criteria
1. It works.

## Questions for B.
None.

## Shipped notes
(filled at close-out)
"""
HITLIST_TEXT = f"""# Joey HITLIST

| ID | Title | Area | Size | Status | Why | Spec |
| --- | --- | --- | --- | --- | --- | --- |
| JY-010 | worktree | Tooling | M | building | One worktree per item · PR #47 | — |
| {ITEM} | `joey.py close-out` | Tooling | L | building | Claude merges and deploys with checks | — |
"""
HITLIST_CHECK = """import os, sys
if os.environ.get("FAKE_HITLIST_FAIL"):
    print("FAIL: JY-011: spec link missing or file not found")
    sys.exit(1)
print("PASS")
"""


def review(body="Review: PASS (Sonnet reviewer 1)", at="2026-10-23T05:00:00Z"):
    return {"body": body, "createdAt": at}


def pr_view(n, branch, oid, title="JY-011: close-out", files=("scripts/joey_closeout.py",), renames=(),
            labels=("review", "accepted"), comments=None, ci="SUCCESS"):
    return {
        "number": n, "title": title, "state": "OPEN", "isDraft": False, "mergeable": "MERGEABLE",
        "mergeStateStatus": "CLEAN", "baseRefName": "main", "headRefName": branch, "headRefOid": oid,
        "labels": [{"name": x} for x in labels], "mergeCommit": None,
        "comments": list(comments if comments is not None else [review()]),
        "commits": [{"oid": oid, "committedDate": "2026-10-23T04:00:00Z"}],
        "statusCheckRollup": [{"__typename": "CheckRun", "name": "test", "workflowName": "ci", "status": "COMPLETED",
                               "conclusion": ci, "startedAt": "2026-10-23T04:01:00Z"}],
        "_files": [(f, "") for f in files] + list(renames),
    }


class Clock:
    def __init__(self, t=NOON_AEDT):
        self.t, self.slept = t, 0

    def now(self):
        return self.t

    def sleep(self, s):
        self.slept += s
        self.t += dt.timedelta(seconds=s)


class FakeGh:
    """Answers the gh calls close-out and worktree remove make; merges squash into the bare origin for real."""

    def __init__(self, world):
        self.w, self.calls, self.prs = world, [], {}
        self.merge_mode = "ok"  # ok | fail | timeout-but-merged
        self.merge_secs = 0  # how long the item merge "takes" on the fake clock
        self.label_time = "2026-10-23T05:30:00Z"
        # GitHub reality: Commit.pushedDate is null; the push time shows only as a force-push event and as the head's
        # check suite created_at (before any run starts). None = GitHub gives none.
        self.force_pushed_at, self.suite_at = None, "2026-10-23T04:00:05Z"
        self.suites_raise = self.force_raise = False  # the two reads fail (fail closed)
        self.head_specs = []  # file names under docs/specs on the PR head

    def __call__(self, args, timeout=120):
        a = list(args)
        self.calls.append(a)
        if a[:2] == ["api", "graphql"]:  # the head's force-push events (JY-229)
            if self.force_raise:
                raise RuntimeError("gh api exited 1: HTTP 502 Bad Gateway")
            return f"{self.prs[50]['headRefOid']}\t{self.force_pushed_at}\n" if self.force_pushed_at else ""
        if a[0] == "api" and a[1].endswith("/check-suites"):  # the head SHA's check suites (JY-229)
            if self.suites_raise:
                raise RuntimeError("gh api exited 1: HTTP 502 Bad Gateway")
            return f"{self.suite_at}\n" if self.suite_at and self.prs[50]["headRefOid"] in a[1] else ""
        if a[0] == "api":
            if "/contents/docs/specs?ref=" in a[1]:  # the spec listing on the PR head (JY-229)
                return "".join(f"{n}\n" for n in self.head_specs)
            n = int(a[1].split("/")[4])
            if a[1].endswith("/events"):
                return self.label_time + "\n" if self.label_time else ""
            return "".join(f"{f}\t{p}\n" for f, p in self.prs[n]["_files"])
        if a[:2] == ["pr", "list"]:
            prs = list(self.prs.values())
            if "--head" in a:
                prs = [p for p in prs if p["headRefName"] == a[a.index("--head") + 1]]
            fields = a[a.index("--json") + 1].split(",")
            return json.dumps([{k: p[k] for k in fields if k in p} for p in prs])
        if a[:2] == ["pr", "view"]:
            return json.dumps(self.prs[int(a[2])])
        if a[:2] == ["pr", "merge"]:
            p = self.prs[int(a[2])]
            assert "--squash" in a and a[a.index("--match-head-commit") + 1] == p["headRefOid"]
            if self.merge_mode == "fail" and p["number"] == 50:
                raise RuntimeError("gh pr merge exited 1: not mergeable")
            self.merge(p["number"])
            if self.merge_mode == "timeout-but-merged" and p["number"] == 50:
                raise RuntimeError("gh pr merge timed out")
            return ""
        if a[:2] == ["pr", "comment"]:
            self.prs[int(a[2])]["comments"].append({"body": a[a.index("--body") + 1], "createdAt": "2026-10-23T06:00:00Z"})
            return ""
        if a[:2] == ["pr", "edit"]:
            return ""
        if a[:2] == ["pr", "create"]:
            head = a[a.index("--head") + 1]
            n = max(self.prs) + 1
            self.prs[n] = pr_view(n, head, self.w.origin_sha(head), title=a[a.index("--title") + 1], files=(),
                                  labels=(), comments=[])
            return f"https://github.com/example/joey/pull/{n}\n"
        raise AssertionError(f"unexpected gh call {a}")

    def merge(self, n):
        p = self.prs[n]
        p["mergeCommit"] = {"oid": self.w.squash(p["headRefName"], f"{p['title']} (#{n})")}
        p["state"] = "MERGED"
        if n == 50:
            self.w.clock.sleep(self.merge_secs)

    def gh_json(self, args, cwd=None, timeout=60):
        return json.loads(self(args))

    def writes(self):
        return [c for c in self.calls if c[:2] in (["pr", "merge"], ["pr", "comment"], ["pr", "edit"], ["pr", "create"])]


class FakeNas:
    """The NAS: one handler per command shape. Sequences repeat their last value."""

    def __init__(self, world):
        self.w, self.calls = world, []
        self.lock = [""]
        self.free = "2400"
        self.last = ["2026-10-22T23:00:00Z PASS prev=aaaaaaa new=bbbbbbb suite green, smoke ok tv=current"]
        self.pass_line = None  # --resume "already deployed?" read; None = the `last` line
        self.started = False
        self.polls_until_done = 2
        self.result = "PASS"
        self.tree = None  # None = the merge SHA
        self.containers = ["joey-hub running healthy\njoey-media running healthy\njoey-swag running"]
        self.profiles = "COMPOSE_PROFILES=edge,media"
        self.smoke = "smoke ok\nrc=0"
        self.healthz = '{"status": "ok", "areas": 4, "front": "private"}'
        self.raise_on, self.transient = None, 0
        self.on_wait = None  # called once when a lock read reports a running deploy

    @staticmethod
    def _pop(seq):
        return seq.pop(0) if len(seq) > 1 else seq[0]

    def sha(self):
        return self.w.gh.prs[50]["mergeCommit"]["oid"]

    def __call__(self, cmd, stdin=None, timeout=60):
        self.calls.append(cmd)
        if self.raise_on and self.raise_on in cmd:
            raise RuntimeError(jco._mask_host(f"ssh to the NAS failed: connect to host "
                                              f"{os.environ['JOEY_NAS'].split('@')[-1]} port 22"))
        if self.transient and ("docker inspect" in cmd or cmd.startswith("wc -l")):
            self.transient -= 1
            raise RuntimeError("ssh to the NAS failed (NAS off 22:00-07:00, or off the home LAN?): reset by peer")
        if "joey-deploy.lock" in cmd:
            pid = self._pop(self.lock)
            if pid and self.on_wait:
                self.on_wait()
                self.on_wait = None
            return pid
        if cmd.startswith("free -m"):
            return self.free
        if "sh deploy.sh" in cmd:
            self.started = True
            return "lines=5\ndeploy running detached (pid 4242), log: /x/deploy/logs/deploy-1.log\nsafe to disconnect"
        if cmd.startswith("wc -l <"):
            if self.started:
                self.polls_until_done -= 1
                return "6" if self.polls_until_done < 0 else "5"
            return "5"
        if cmd.startswith("grep -E '^[^ ]+ PASS '"):
            return self.pass_line if self.pass_line is not None else self.last[0]
        if cmd.startswith("tail -1"):
            if self.started and self.polls_until_done < 0:
                return (f"2026-10-23T01:10:00Z {self.result} prev=bbbbbbb new={self.sha()[:7]} "
                        "suite green, smoke ok tv=current")
            return self._pop(self.last)
        if cmd.startswith("grep -E '^== '") or cmd.startswith("grep -E 'FAIL"):
            return "== smoke =="
        if "alpine/git rev-parse HEAD" in cmd:
            return self.tree or self.sha()
        if "docker inspect" in cmd:
            assert cmd == jco.CONTAINER_CMD
            return self._pop(self.containers)
        if "COMPOSE_PROFILES" in cmd:
            return self.profiles
        if "smoke.py" in cmd:
            return self.smoke
        if cmd == "docker exec -i joey-hub python -":
            assert "healthz" in stdin
            return self.healthz
        raise AssertionError(f"unexpected NAS command {cmd}")


GIT_ENV = {"GIT_AUTHOR_NAME": "Joey Test", "GIT_AUTHOR_EMAIL": "joey@example.invalid",
           "GIT_COMMITTER_NAME": "Joey Test", "GIT_COMMITTER_EMAIL": "joey@example.invalid",
           "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0"}
NO_GIT_ENV = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")
# JY-227: no background `git maintenance run --auto` after each commit, fetch and push (one process less each)
GITCONFIG = "[maintenance]\n\tauto = false\n[receive]\n\tautogc = false\n"
REPOS = ("origin.git", "life-dashboard", f"wt-{ITEM}")  # what a full world holds on disk, in its root


def git_run(args, cwd, env=None):
    r = subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    assert r.returncode == 0, f"git {args}: {r.stderr}"
    return r.stdout.strip()


def copy_world(src, dst):
    """Copy a world's repos from src to dst and point their absolute paths at dst (what `git worktree repair` and
    `git config url.<origin>.insteadOf` would write), so the copy is the same git state as a fresh build there."""
    for name in REPOS:
        if (src / name).exists():
            shutil.copytree(src / name, dst / name, ignore=shutil.ignore_patterns("*.sample"))
    config = dst / "life-dashboard" / ".git" / "config"
    text = config.read_text(encoding="utf-8")
    start = text.index('[url "') + len('[url "')
    config.write_text(text[:start] + (dst / "origin.git").as_posix() + text[text.index('"]', start):],
                      encoding="utf-8")
    wt = dst / f"wt-{ITEM}"
    if wt.exists():
        admin = dst / "life-dashboard" / ".git" / "worktrees" / wt.name
        with open(wt / ".git", "r+", encoding="utf-8", newline="\n") as f:  # r+: Windows git marks .git hidden
            f.write(f"gitdir: {admin.as_posix()}\n")
            f.truncate()
        (admin / "gitdir").write_text(f"{(wt / '.git').as_posix()}\n", encoding="utf-8")


class Templates:
    """JY-227: the full world's git repos, built once per worker (session) and copied per test. The base is the bare
    origin + clone; each `files` variant adds the item's worktree with one pushed commit touching those files."""

    def __init__(self, root):
        self.root, self.made = root, {}
        (root / "gitconfig").write_text(GITCONFIG, encoding="utf-8")
        self.env = {k: v for k, v in os.environ.items() if k not in NO_GIT_ENV}
        self.env.update(GIT_ENV, GIT_CONFIG_GLOBAL=str(root / "gitconfig"))

    def get(self, files=None):
        """(folder, item tip or None) for the base world (files=None) or the base world plus the item."""
        if files not in self.made:
            base = None if files is None else self.get(None)[0]
            d = self.root / f"t{len(self.made)}"
            d.mkdir()
            self.made[files] = (d, self._base(d) if files is None else self._item(base, d, files))
        return self.made[files]

    def _base(self, d):
        origin, clone = d / "origin.git", d / "life-dashboard"
        git_run(["init", "-q", "--bare", "-b", "main", str(origin)], d, self.env)
        git_run(["init", "-q", "-b", "main", str(clone)], d, self.env)
        (clone / "docs" / "specs").mkdir(parents=True)
        (clone / "scripts").mkdir()
        (clone / ".gitignore").write_text(".env\n/data/\n/.joey/\n", encoding="utf-8")
        (clone / "HITLIST.md").write_text(HITLIST_TEXT, encoding="utf-8")
        (clone / SPEC).write_text(SPEC_TEXT, encoding="utf-8")
        (clone / "scripts" / "hitlist_seed_check.py").write_text(HITLIST_CHECK, encoding="utf-8")
        for args in (["add", "."], ["commit", "-q", "-m", "init"], ["remote", "add", "origin", GH_URL],
                     ["config", f"url.{origin.as_posix()}.insteadOf", GH_URL], ["push", "-q", "-u", "origin", "main"]):
            git_run(args, clone, self.env)
        return None

    def _item(self, base, d, files):
        copy_world(base, d)
        wt = d / f"wt-{ITEM}"
        git_run(["worktree", "add", "-q", str(wt), "-b", BRANCH, "origin/main"], d / "life-dashboard", self.env)
        for f in files:
            p = wt / f
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("work\n", encoding="utf-8")
        git_run(["add", *files], wt, self.env)
        git_run(["commit", "-q", "-m", f"{ITEM}: work"], wt, self.env)
        git_run(["push", "-q", "origin", BRANCH], wt, self.env)
        return git_run(["rev-parse", "HEAD"], wt, self.env)


class World:
    """full=False: no git (clone_root/repo_slug faked). full=True: bare origin + clone, real squash merges. The full
    world's repos are copied from Templates on first use (JY-227): item() as the first step copies the template that
    already holds the item's commit; anything else first copies the base, and item() then builds the commit here."""

    def __init__(self, tmp_path, monkeypatch, capsys, full, templates=None):
        self.root, self.capsys, self.full = tmp_path, capsys, full
        self.monkeypatch, self.templates, self.made = monkeypatch, templates, False
        self.origin = tmp_path / "origin.git"
        self._clone = tmp_path / "life-dashboard"
        self.wt = tmp_path / f"wt-{ITEM}"
        monkeypatch.setenv("JOEY_NAS", "root@10.9.8.7")
        monkeypatch.delenv("JOEY_GH", raising=False)
        monkeypatch.delenv("FAKE_HITLIST_FAIL", raising=False)
        self.clock = Clock()
        self.gh = FakeGh(self)
        self.nas = FakeNas(self)
        monkeypatch.setattr(jco, "gh_run", self.gh)
        monkeypatch.setattr(joey_common, "gh_json", self.gh.gh_json)
        monkeypatch.setattr(jco, "nas", self.nas)
        monkeypatch.setattr(joey_common, "ssh_run", lambda cmd, stdin=None, timeout=60: subprocess.CompletedProcess(
            cmd, 0, stdout=self.nas(cmd, stdin, timeout), stderr=""))
        monkeypatch.setattr(jco, "utc_now", self.clock.now)
        monkeypatch.setattr(jco, "sleep", self.clock.sleep)
        if not full:
            self._clone.mkdir()
            monkeypatch.setattr(joey_common, "clone_root", lambda cwd=None: self._clone)
            monkeypatch.setattr(joey_common, "repo_slug", lambda clone: "example/joey")
            monkeypatch.chdir(self._clone)
            return
        gitconfig = tmp_path / "gitconfig"
        gitconfig.write_text(GITCONFIG, encoding="utf-8")
        for k, val in dict(GIT_ENV, GIT_CONFIG_GLOBAL=str(gitconfig)).items():
            monkeypatch.setenv(k, val)
        for k in NO_GIT_ENV:
            monkeypatch.delenv(k, raising=False)

    def _make(self, files=None):
        """Copy the template repos in, once. Returns the item's tip when the copy already holds the item."""
        if not self.full or self.made:
            return None
        self.made = True
        src, tip = self.templates.get(files)
        copy_world(src, self.root)
        self.monkeypatch.chdir(self._clone)
        return tip

    @property
    def clone(self):
        self._make()
        return self._clone

    def git(self, *args, cwd=None):
        self._make()
        return git_run(args, cwd or self._clone)

    def origin_sha(self, ref):
        return self.git("--git-dir", str(self.origin), "rev-parse", f"refs/heads/{ref}", cwd=self.root)

    def squash(self, branch, msg):
        """GitHub's squash merge, in the bare origin: the merged tree as one new commit on main (JY-227: was a
        scratch clone + merge --squash + commit + push; same commit content, no clone). A conflict fails merge-tree."""
        g = ("--git-dir", str(self.origin))
        tree = self.git(*g, "merge-tree", "--write-tree", "refs/heads/main", f"refs/heads/{branch}", cwd=self.root)
        sha = self.git(*g, "commit-tree", tree.splitlines()[0], "-p", "refs/heads/main", "-m", msg, cwd=self.root)
        self.git(*g, "update-ref", "refs/heads/main", sha, cwd=self.root)
        return sha

    def item(self, files=("scripts/joey_closeout.py",), **view):
        """Light: PR #50 only. Full: the item's worktree with one pushed commit touching `files`, and PR #50."""
        if not self.full:
            self.gh.prs[50] = pr_view(50, BRANCH, FAKE_OID, files=files, **view)
            return FAKE_OID
        tip = self._make(tuple(files))
        if tip is None:  # the base was copied earlier (the test changed main first): build the item here
            self.git("worktree", "add", "-q", str(self.wt), "-b", BRANCH, "origin/main")
            for f in files:
                p = self.wt / f
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text("work\n", encoding="utf-8")
                self.git("add", f, cwd=self.wt)
            self.git("commit", "-q", "-m", f"{ITEM}: work", cwd=self.wt)
            self.git("push", "-q", "origin", BRANCH, cwd=self.wt)
            tip = self.git("rev-parse", "HEAD", cwd=self.wt)
        self.gh.prs[50] = pr_view(50, BRANCH, tip, files=files, **view)
        return tip

    def run(self, *args):
        self._make()
        self.capsys.readouterr()
        rc = jco.main([ITEM, *args])
        return rc, self.capsys.readouterr().out

    def origin_file(self, path):
        self.git("fetch", "-q", "origin")
        return self.git("show", f"origin/main:{path}")

    def log_text(self):
        return "\n".join(p.read_text(encoding="utf-8") for p in (self.clone / ".joey" / "logs").glob("joey_*.log"))


@pytest.fixture(scope="session")
def templates(tmp_path_factory):
    return Templates(tmp_path_factory.mktemp("joey-worlds"))


@pytest.fixture
def lw(tmp_path, monkeypatch, capsys):
    return World(tmp_path, monkeypatch, capsys, full=False)


@pytest.fixture
def w(tmp_path, monkeypatch, capsys, templates):
    return World(tmp_path, monkeypatch, capsys, full=True, templates=templates)


def rows(out):
    return [ln for ln in out.splitlines() if ln[:4] in ("PASS", "FAIL", "SKIP", "DRY ")]


def assert_unchanged(world):
    assert world.gh.writes() == []
    assert not world.nas.started


# ================= full runs =================
def test_happy_path_code_pr_merges_deploys_verifies_and_closes_out(w):
    w.item()
    rc, out = w.run("--note", "watch the first real use")
    assert rc == 0, out
    assert not [x for x in rows(out) if x.startswith(("FAIL", "DRY"))], out
    merges = [c for c in w.gh.calls if c[:2] == ["pr", "merge"]]
    assert len(merges) == 2 and merges[0][2] == "50" and "--squash" in merges[0]  # item PR, then the docs PR
    sha = w.gh.prs[50]["mergeCommit"]["oid"]
    assert "PASS  merge.2 read-back: MERGED, on origin/main - MERGED as " + sha[:7] in out
    assert f"new={sha[:7]}" in out and "PASS  verify.5 /healthz inside joey-hub" in out
    assert "INFO  the hub's /healthz exposes no commit SHA" in out
    assert "PASS  docs.3 write, check, commit, push - hitlist check PASS" in out
    spec = w.origin_file(SPEC)
    assert "Status: shipped 2026-10-23" in spec
    assert f"- PR: #50, squash-merged as `{sha[:7]}` ({sha})." in spec
    assert f"- Deploy: `2026-10-23T01:10:00Z PASS prev=bbbbbbb new={sha[:7]}" in spec
    assert "- Accept: the `accepted` label on the PR" in spec and "  - watch the first real use" in spec
    hit = w.origin_file("HITLIST.md")
    assert f"| {ITEM} | `joey.py close-out` | Tooling | L | [x] shipped | Claude merges and deploys with checks · " \
           f"PR #50 | [spec]({SPEC}) |" in hit
    assert "| JY-010 | worktree | Tooling | M | building |" in hit  # other rows untouched
    docs_commit = w.git("log", "-1", "--format=%B", f"origin/{CHORE}")
    assert docs_commit.strip().endswith("Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>")
    assert [c for c in w.gh.calls if c[:2] == ["pr", "edit"]] == [
        ["pr", "edit", "50", "--repo", "example/joey", "--add-label", "shipped", "--remove-label", "review,accepted"]]
    assert not w.wt.exists() and BRANCH not in w.git("branch")  # worktree removed (gh-proof path)
    assert not (w.root / f"wt-{ITEM}-shipped").exists()


@pytest.mark.parametrize("comment", ["accepted", "  Accepted\n", "ACCEPTED"])
def test_accept_by_exact_comment(w, comment):
    w.item(files=("docs/a.md",), labels=("review",),
           comments=[review(), {"body": comment, "createdAt": "2026-10-23T05:10:00Z"}])
    rc, out = w.run("--dry-run")
    assert rc == 0, out
    assert "PASS  gate d: B.'s accept - PR comment accepted" in out and "WARN" not in out


def test_accepted_in_chat_posted_before_the_merge_and_kept_verbatim(w):
    words = 'B.: "accepted JY-011" 2026-10-23'
    w.item(labels=("review",))
    rc, out = w.run("--accepted-in-chat", words, "--deploy", "no")
    assert rc == 0, out
    comments = [i for i, c in enumerate(w.gh.calls) if c[:2] == ["pr", "comment"]]
    merges = [i for i, c in enumerate(w.gh.calls) if c[:2] == ["pr", "merge"]]
    assert comments and comments[0] < merges[0]
    assert w.gh.calls[comments[0]][-1] == f"accepted in chat: {words}"
    assert f'- Accept: in chat: "{words}"' in w.origin_file(SPEC)


def test_doc_only_pr_skips_deploy_and_never_touches_the_nas(w):
    w.item(files=("docs/a.md", ".github/x.yml"))
    rc, out = w.run()
    assert rc == 0, out
    assert "SKIP  deploy decision - no deploy: every changed file is Markdown or under .github/" in out
    assert w.nas.calls == []
    assert "- Deploy: skipped: every changed file is Markdown or under .github/" in w.origin_file(SPEC)


def test_after_fail_is_the_one_retry(w):
    w.item()
    w.nas.last = ["2026-10-22T23:00:00Z ABORTED prev=a new=b exit 1 before an outcome"]
    rc, out = w.run("--after-fail")
    assert rc == 0, out
    assert "PASS  deploy.4 last deploy green - last history line: 2026-10-22T23:00:00Z ABORTED" in out


def test_low_memory_skip_is_not_green_and_after_fail_retries(w):
    """JY-240 (2026-10-24): deploy.sh skips the gate on a low-memory NAS and logs SKIPPED-LOW-MEMORY. That is not
    green, so the next close-out needs --after-fail (or a later green run) to deploy."""
    w.item()
    w.nas.last = ["2026-10-24T05:00:00Z SKIPPED-LOW-MEMORY prev=a new=b available 1500 MB < 1650 MB before the gate"]
    rc, out = w.run("--after-fail")
    assert rc == 0, out
    assert "PASS  deploy.4 last deploy green - last history line: 2026-10-24T05:00:00Z SKIPPED-LOW-MEMORY" in out


def test_red_deploy_after_merge_stops_and_lists_what_is_left(w):
    w.item()
    w.nas.result = "ROLLED-BACK"
    rc, out = w.run()
    assert rc == 1 and "FAIL  deploy.6 history line PASS on the merge SHA" in out
    assert "not done: deploy, verify, shipped notes, labels, worktree" in out
    assert not [c for c in w.gh.calls if c[:2] in (["pr", "create"], ["pr", "edit"])]
    assert w.wt.exists()


def test_merge_call_fails_but_the_pr_merged_carries_on(w):
    w.item(files=("docs/a.md",))
    w.gh.merge_mode = "timeout-but-merged"
    rc, out = w.run()
    assert rc == 0, out
    assert "PASS  merge.1 gh pr merge --squash (one call) - gh pr merge failed (gh pr merge timed out) but the PR " \
           "is MERGED: carrying on" in out
    assert len([c for c in w.gh.calls if c[:2] == ["pr", "merge"] and c[2] == "50"]) == 1  # never retried


# ---------- verify (6) ----------
def test_health_starting_then_healthy_passes(w):
    w.item()
    starting = "joey-hub running healthy\njoey-media running starting\njoey-swag running"
    w.nas.containers = [starting, starting, w.nas.containers[0]]
    rc, out = w.run()
    assert rc == 0, out
    assert "PASS  verify.2 joey-hub / joey-media / joey-swag running healthy" in out and "(after 20 s)" in out


@pytest.mark.parametrize("state, why", [
    ("joey-hub running healthy\njoey-media running unhealthy\njoey-swag running", "joey-media running unhealthy"),
    ("joey-hub running healthy\njoey-media exited\njoey-swag running", "joey-media exited"),
    ("joey-hub running healthy\njoey-media running healthy\njoey-swag absent", "joey-swag absent"),
])
def test_health_fails_at_once(w, state, why):
    w.item()
    w.nas.containers = [state]
    rc, out = w.run()
    assert rc == 1 and why in out
    assert sum("docker inspect" in c for c in w.nas.calls) == 1
    assert "not done: verify, shipped notes, labels, worktree" in out


def test_health_starting_past_the_limit_fails(w):
    w.item()
    w.nas.containers = ["joey-hub running healthy\njoey-media running starting\njoey-swag running"]
    rc, out = w.run()
    assert rc == 1 and f"still starting after {jco.HEALTH_MAX_S} s" in out
    assert sum("docker inspect" in c for c in w.nas.calls) == jco.HEALTH_MAX_S // jco.HEALTH_POLL_S + 1


def test_transient_ssh_failures_are_retried_in_poll_and_verify(w):
    w.item()
    w.nas.transient = 3  # three exit-255 failures across the history poll and the container check
    rc, out = w.run()
    assert rc == 0, out
    assert out.count("WARN  ssh failed, retry") == 3


def test_wrong_profiles_fail(w):
    w.item()
    w.nas.profiles = "COMPOSE_PROFILES=edge"
    rc, out = w.run()
    assert rc == 1 and "FAIL  verify.3 COMPOSE_PROFILES=edge,media - COMPOSE_PROFILES=edge (want" in out


def test_window_rechecked_before_starting_deploy_sh(w):
    w.item()
    w.clock.t = dt.datetime(2026, 10, 23, 10, 29, tzinfo=dt.timezone.utc)  # 21:29 Melbourne at the preflight
    w.gh.merge_secs = 120  # the merge takes two minutes
    rc, out = w.run()
    assert rc == 1 and "PASS  deploy.1 deploy window" in out
    assert ("FAIL  deploy.5 start deploy.sh (self-detaching) - Melbourne time 21:31 is outside the deploy window "
            "07:00-21:30: not starting deploy.sh") in out
    assert not w.nas.started
    assert "not done: deploy, verify, shipped notes, labels, worktree" in out
    assert f"finish later with: python scripts/joey.py close-out {ITEM} --resume" in out


def test_healthz_non_sha_version_is_info(w):
    w.item()
    w.nas.healthz = '{"status": "ok", "version": "v2.3"}'
    rc, out = w.run()
    assert rc == 0, out
    assert "INFO  /healthz version='v2.3' is not a commit SHA" in out


def test_healthz_sha_compared_when_exposed(w):
    w.item()
    w.nas.healthz = '{"status": "ok", "sha": "deadbee"}'
    rc, out = w.run()
    assert rc == 1 and "FAIL  verify.5 /healthz inside joey-hub - /healthz sha=deadbee" in out


# ---------- shipped notes (7) ----------
def test_missing_hitlist_row_stops_with_a_clear_message(w):
    (w.clone / "HITLIST.md").write_text(HITLIST_TEXT.replace(f"| {ITEM} |", "| JY-099 |"), encoding="utf-8")
    w.git("commit", "-q", "-am", "drop row")
    w.git("push", "-q", "origin", "main")
    w.item(files=("docs/a.md",))
    rc, out = w.run()
    assert rc == 1 and f"FAIL  docs.1 find the spec and the HITLIST row - HITLIST.md has 0 rows for {ITEM}" in out
    assert "not done: shipped notes, labels, worktree" in out
    assert not [c for c in w.gh.calls if c[:2] == ["pr", "create"]]


def test_hitlist_check_failure_blocks_the_docs_commit(w, monkeypatch):
    w.item(files=("docs/a.md",))
    monkeypatch.setenv("FAKE_HITLIST_FAIL", "1")
    rc, out = w.run()
    assert rc == 1 and "FAIL  docs.3 write, check, commit, push - scripts/hitlist_seed_check.py failed" in out
    assert "spec link missing" in out and not [c for c in w.gh.calls if c[:2] == ["pr", "create"]]


def test_blocked_commit_is_a_fail_with_the_hook_message(w):
    w.item(files=("docs/a.md",))
    hooks = w.root / "hooks"
    hooks.mkdir()
    marker = w.root / "hook_ran"
    hook = hooks / "pre-commit"
    hook.write_text(f"#!/bin/sh\necho ran > '{marker.as_posix()}'\n"
                    "echo 'money guard: a date and an amount on one line' >&2\nexit 1\n",
                    encoding="utf-8", newline="\n")
    os.chmod(hook, 0o755)  # Linux git skips a non-executable hook silently (Windows ignores the bit)
    w.git("config", "core.hooksPath", hooks.as_posix())
    rc, out = w.run()
    assert marker.exists(), "the pre-commit hook never ran"
    assert rc == 1 and "FAIL  docs.3 write, check, commit, push - git commit blocked: money guard" in out


@pytest.mark.parametrize("setup, expect, rc_want", [
    ("stale-local", "removed the stale local wt-JY-011-shipped and chore/JY-011-shipped (no unpushed work)", 0),
    ("dirty-local", "holds unpushed work (1 changed files, 0 commits not on origin/main)", 1),
    ("open-pr", "reusing the open docs PR #51", 0),
    ("merged-pr", "SKIP  docs.0 existing chore/JY-###-shipped - docs PR #51 from chore/JY-011-shipped is already "
                  "merged", 0),
])
def test_existing_chore_branch(w, setup, expect, rc_want):
    w.item(files=("docs/a.md",))
    docs_wt = w.root / f"wt-{ITEM}-shipped"
    if setup in ("stale-local", "dirty-local"):
        w.git("worktree", "add", "-q", str(docs_wt), "-b", CHORE, "origin/main")
        if setup == "dirty-local":
            (docs_wt / "HITLIST.md").write_text("half done\n", encoding="utf-8")
    else:  # a docs branch pushed by an earlier run, with its PR
        w.git("worktree", "add", "-q", str(docs_wt), "-b", CHORE, "origin/main")
        (docs_wt / "notes.md").write_text("earlier run\n", encoding="utf-8")
        w.git("add", "notes.md", cwd=docs_wt)
        w.git("commit", "-q", "-m", "earlier docs", cwd=docs_wt)
        w.git("push", "-q", "origin", CHORE, cwd=docs_wt)
        w.git("worktree", "remove", str(docs_wt))
        w.git("branch", "-D", CHORE)
        w.gh.prs[51] = pr_view(51, CHORE, w.origin_sha(CHORE), files=(), labels=(), comments=[])
        if setup == "merged-pr":
            w.gh.prs[51]["state"] = "MERGED"
    rc, out = w.run()
    assert rc == rc_want, out
    assert expect in out
    creates = [c for c in w.gh.calls if c[:2] == ["pr", "create"]]
    assert len(creates) == (1 if setup == "stale-local" else 0)
    if setup == "open-pr":
        assert "PASS  docs.6 squash-merge the docs PR - docs PR #51 MERGED" in out
    if setup == "dirty-local":
        assert docs_wt.exists() and "not done: shipped notes, labels, worktree" in out


@pytest.mark.parametrize("setup, expect, rc_want", [
    ("remote-only", "chore/JY-011-shipped is on origin without a PR: it will be replaced (force-with-lease)", 0),
    ("local-ahead", "holds unpushed work (0 changed files, 1 commits not on origin/main)", 1),
])
def test_chore_branch_remote_only_or_local_ahead(w, setup, expect, rc_want):
    w.item(files=("docs/a.md",))
    docs_wt = w.root / f"wt-{ITEM}-shipped"
    w.git("worktree", "add", "-q", str(docs_wt), "-b", CHORE, "origin/main")
    (docs_wt / "notes.md").write_text("earlier run\n", encoding="utf-8")
    w.git("add", "notes.md", cwd=docs_wt)
    w.git("commit", "-q", "-m", "earlier docs", cwd=docs_wt)
    w.git("worktree", "remove", str(docs_wt))
    if setup == "remote-only":
        w.git("push", "-q", "origin", CHORE)
        w.git("branch", "-D", CHORE)
    rc, out = w.run()
    assert rc == rc_want, out
    assert expect in out
    if setup == "remote-only":
        assert "PASS  docs.3 write, check, commit, push" in out and "PASS  docs.6 squash-merge the docs PR" in out
        assert "Status: shipped" in w.origin_file(SPEC)
        assert "notes.md" not in w.git("ls-tree", "--name-only", "origin/main")  # the old push was replaced
    else:
        assert CHORE in w.git("branch") and not [c for c in w.gh.calls if c[:2] == ["pr", "create"]]


# ---------- --resume (3) ----------
def test_resume_deploys_when_not_deployed_yet(w):
    w.item()
    w.gh.merge(50)  # merged earlier, by hand or by a run that failed after the merge
    rc, out = w.run("--resume")
    assert rc == 0, out
    assert "PASS  find the PR - --resume: PR #50 from feat/JY-011-close-out is MERGED" in out
    assert "gate a:" not in out and "gates and merge skipped" in out
    assert not [c for c in w.gh.calls if c[:2] == ["pr", "merge"] and c[2] == "50"]
    assert "PASS  deploy.0 already deployed? - not deployed yet" in out and w.nas.started
    assert "PASS  verify.1 NAS tree on the merge SHA" in out
    assert "Status: shipped" in w.origin_file(SPEC) and not w.wt.exists()


def test_resume_already_deployed_skips_the_deploy_but_verifies(w):
    w.item()
    w.gh.merge(50)
    sha = w.gh.prs[50]["mergeCommit"]["oid"]
    w.nas.pass_line = f"2026-10-23T00:30:00Z PASS prev=aaaaaaa new={sha[:7]} suite green, smoke ok tv=current"
    rc, out = w.run("--resume")
    assert rc == 0, out
    assert f"SKIP  deploy.0 already deployed? - already deployed: {w.nas.pass_line}" in out
    assert not w.nas.started and "deploy.1" not in out
    assert "PASS  verify.5 /healthz inside joey-hub" in out
    assert f"- Deploy: `{w.nas.pass_line}`" in w.origin_file(SPEC)


def test_resume_rechecks_deployed_after_waiting(w):
    w.item()
    w.gh.merge(50)
    sha = w.gh.prs[50]["mergeCommit"]["oid"]
    w.nas.lock = ["4242", ""]
    line = f"2026-10-23T01:05:00Z PASS prev=aaaaaaa new={sha[:7]} suite green, smoke ok tv=current"
    w.nas.on_wait = lambda: setattr(w.nas, "pass_line", line)  # the running deploy shipped it
    rc, out = w.run("--resume")
    assert rc == 0, out
    assert "PASS  deploy.0 already deployed? - not deployed yet" in out
    assert f"SKIP  deploy.0 already deployed? (again, after the wait) - already deployed: {line}" in out
    assert not w.nas.started and "deploy.3" not in out and "PASS  verify.1 NAS tree on the merge SHA" in out


def test_resume_refuses_a_merge_commit_not_on_main(w):
    tip = w.item()
    w.gh.prs[50].update(state="MERGED", mergeCommit={"oid": tip})  # the branch tip: not on origin/main
    rc, out = w.run("--resume")
    assert rc == 1 and f"merge commit {tip[:7]} is not on origin/main" in out
    assert w.gh.writes() == []


# ---------- worktree (9) ----------
def test_worktree_refusal_is_a_fail_row_not_a_crash(w):
    w.item(files=("docs/a.md",))
    (w.wt / "untracked.txt").write_text("x\n", encoding="utf-8")
    rc, out = w.run()
    assert rc == 1 and "FAIL  worktree clean" in out and "Traceback" not in out
    assert "not done: worktree" in out and w.wt.exists()


def test_no_worktree_is_a_skip(w):
    w.item(files=("docs/a.md",))
    w.git("worktree", "remove", str(w.wt))
    rc, out = w.run()
    assert rc == 0, out
    assert f"SKIP  worktree remove - no worktree wt-{ITEM}" in out


# ---------- dry run (11) ----------
def test_dry_run_on_a_doc_only_pr_changes_nothing(w):
    w.item(files=("docs/a.md",))
    before = (w.git("rev-parse", "origin/main"), w.origin_sha("main"), w.git("branch"))
    rc, out = w.run("--dry-run")
    assert rc == 0, out
    assert {x[:4] for x in rows(out)} <= {"PASS", "DRY ", "SKIP"}, out
    assert [x for x in rows(out) if x.startswith("SKIP")] == \
        ["SKIP  deploy decision - no deploy: every changed file is Markdown or under .github/"]
    assert (f"DRY   merge.1 gh pr merge --squash (one call) - would run: gh pr merge 50 --repo example/joey --squash "
            f"--match-head-commit {w.gh.prs[50]['headRefOid']}") in out
    assert "PASS  docs.1 find the spec and the HITLIST row" in out
    assert "DRY   docs.2 branch chore/JY-###-shipped - would run: git worktree add" in out
    assert "DRY   labels: shipped - would run: gh pr edit 50" in out
    assert f"DRY   worktree remove - would run: joey.py worktree remove {ITEM}" in out
    assert "(DRY RUN: nothing changed)" in out
    assert w.gh.writes() == [] and w.nas.calls == []
    assert (w.git("rev-parse", "origin/main"), w.origin_sha("main"), w.git("branch")) == before
    assert w.wt.exists() and not (w.root / f"wt-{ITEM}-shipped").exists()


@pytest.fixture
def no_spec_on_main(lw, monkeypatch):
    """Light world, dry run before the merge: origin/main has no spec for the item (it comes with the PR)."""
    real = joey_common.git

    def git(*args, **kw):
        if args[:1] == ("ls-tree",):
            return ""
        if args[:1] == ("ls-remote",):
            return ""
        return real(*args, **kw)

    monkeypatch.setattr(joey_common, "git", git)
    monkeypatch.setattr(jco.joey_worktree, "worktrees", lambda clone: [])
    return lw


def test_dry_run_finds_the_spec_on_the_pr_head_before_the_merge(no_spec_on_main):
    lw = no_spec_on_main
    lw.item(files=("docs/a.md",))
    lw.gh.head_specs = ["JY-011-close-out.md", "JY-012-other.md"]
    rc, out = lw.run("--dry-run")
    assert rc == 0, out
    assert (f"DRY   docs.1 find the spec and the HITLIST row - would find {SPEC} after the merge "
            f"(it is on the PR head, not on origin/main yet)") in out
    assert not [x for x in rows(out) if x.startswith("FAIL")], out
    assert ["api", f"repos/example/joey/contents/docs/specs?ref={FAKE_OID}", "--jq", ".[].name"] in lw.gh.calls
    assert lw.gh.writes() == []


def test_dry_run_still_fails_when_the_spec_is_on_neither_main_nor_the_pr_head(no_spec_on_main):
    lw = no_spec_on_main
    lw.item(files=("docs/a.md",))
    lw.gh.head_specs = ["JY-012-other.md"]
    rc, out = lw.run("--dry-run")
    assert rc == 1, out
    assert (f"FAIL  docs.1 find the spec and the HITLIST row - 0 spec files docs/specs/{ITEM}-*.md on origin/main "
            f"or the PR head (want 1)") in out


def test_dry_run_on_a_code_pr_reads_the_nas_but_changes_nothing(w):
    w.item()
    w.nas.lock = ["4242"]
    rc, out = w.run("--dry-run")
    assert rc == 0, out
    assert "a deploy is running (pid 4242); a real run would wait up to 90 min" in out
    for step in ("deploy.5 start deploy.sh", "deploy.6 history line", "verify.1", "verify.2", "verify.5"):
        assert f"DRY   {step}" in out, step
    assert f"would run: ssh <nas> \"{jco.CONTAINER_CMD}\"" in out
    assert not any("deploy.sh" in c or "docker" in c for c in w.nas.calls)
    assert w.gh.writes() == []


def test_cli_dry_run_through_joey_py_with_fake_gh(tmp_path):
    repo = tmp_path / "life-dashboard"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", GH_URL], check=True)
    fake = tmp_path / "fake_gh.py"
    fake.write_text('import json\nprint(json.dumps([{"number": 48, "state": "MERGED", "baseRefName": "main", '
                    '"headRefName": "feat/JY-013-budgets"}]))\n', encoding="utf-8")
    env = dict(os.environ, JOEY_GH=str(fake))
    r = subprocess.run([sys.executable, str(JOEY), "close-out", "JY-013", "--dry-run"], cwd=repo, env=env,
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "=== joey close-out JY-013 (DRY RUN) ===" in r.stdout
    assert "REFUSED: no open PR from feat/JY-013-* (#48 MERGED); to finish the close-out of #48, run again with " \
           "--resume" in r.stdout
    log = "\n".join(p.read_text(encoding="utf-8") for p in (repo / ".joey" / "logs").glob("joey_*.log"))
    assert "[close-out] REFUSED: no open PR" in log


# ================= light runs (no git): refusals before the merge =================
@pytest.mark.parametrize("change, gate", [
    ({"isDraft": True}, "a"), ({"mergeable": "CONFLICTING"}, "a"), ({"mergeable": "UNKNOWN"}, "a"),
    ({"baseRefName": "feat/JY-010-worktree"}, "a"),
    ({"statusCheckRollup": []}, "b"),
    ({"statusCheckRollup": [{"__typename": "CheckRun", "workflowName": "ci", "name": "test", "status": "COMPLETED",
                             "conclusion": "FAILURE", "startedAt": "2026-10-23T04:01:00Z"}]}, "b"),
    ({"statusCheckRollup": [{"__typename": "CheckRun", "workflowName": "ci", "name": "test", "status": "IN_PROGRESS",
                             "conclusion": "", "startedAt": "2026-10-23T04:01:00Z"}]}, "b"),
    ({"comments": []}, "c"),
    ({"comments": [review("Review: FAIL (earlier run said PASS)")]}, "c"),
    ({"comments": [review("Review: must-fix 1; not PASS")]}, "c"),
    ({"comments": [review("Review: PASS (0 FAIL)")]}, "c"),  # any FAIL word vetoes (module docstring)
    ({"comments": [review("Looks good. Review: PASS")]}, "c"),
    ({"comments": [review(at="2026-10-23T03:00:00Z")]}, "c"),  # before the last commit
    ({"comments": [review(), review("Review: FAIL, must-fix 2", at="2026-10-23T05:20:00Z")]}, "c"),  # fresh FAIL vetoes
    ({"labels": [{"name": "review"}]}, "d"),
])
def test_each_gate_refuses_and_changes_nothing(lw, change, gate):
    lw.item()
    lw.gh.prs[50].update(change)
    rc, out = lw.run()
    assert rc == 1
    fails = [x for x in rows(out) if x.startswith("FAIL")]
    assert len(fails) == 2 and fails[0].startswith(f"FAIL  gate {gate}:") and fails[1].startswith("FAIL  gates")
    assert f"REFUSED: 1 gate(s) failed ({gate}): not merging" in out
    assert "nothing changed: the PR is not merged" in out
    assert lw.gh.writes() == [] and lw.nas.calls == []


def test_fail_before_the_push_then_a_fresh_pass_is_a_fix_round(lw):
    lw.item(comments=[review("Review: FAIL, must-fix 3", at="2026-10-23T03:00:00Z"), review()])
    rc, out = lw.run("--deploy", "no", "--dry-run")
    assert "PASS  gate c: Review PASS after the last push, no fresh FAIL" in out


def test_review_before_the_push_is_stale_even_when_the_commit_is_older(lw):
    """The commit is dated before the review but GitHub's push time is after it: a fresh review is needed."""
    lw.item(comments=[review(at="2026-10-23T04:30:00Z")])
    lw.gh.suite_at = "2026-10-23T04:45:00Z"
    rc, out = lw.run()
    assert rc == 1 and "FAIL  gate c" in out and "a later commit needs a fresh review" in out


def test_review_after_the_push_but_before_the_ci_run_starts_passes(lw):
    """JY-229: the check suite is created at the push (04:00:10), the review follows (04:00:30), the ci run starts at
    04:01: the review is fresh (the ci run start is not the push)."""
    lw.item(comments=[review(at="2026-10-23T04:00:30Z")])
    lw.gh.suite_at = "2026-10-23T04:00:10Z"
    rc, out = lw.run("--deploy", "no", "--dry-run")
    assert ("PASS  gate c: Review PASS after the last push, no fresh FAIL - Review PASS at 2026-10-23T04:00:30Z "
            "(last push 2026-10-23T04:00Z)") in out, out
    lw.gh.force_pushed_at = None  # no force-push events at all: normal
    rc, out = lw.run("--deploy", "no", "--dry-run")
    assert "PASS  gate c: Review PASS after the last push" in out, out


@pytest.mark.parametrize("how, reason", [
    ("suites_raise", "check-suites read failed: gh api exited 1: HTTP 502 Bad Gateway"),
    ("suite_at", "check-suites read failed: no check suite on the head SHA"),
    ("force_raise", "force-push read failed: gh api exited 1: HTTP 502 Bad Gateway"),
])
def test_gate_c_fails_closed_when_the_push_time_cannot_be_read(lw, how, reason):
    lw.item(comments=[review(at="2026-10-23T04:30:00Z")])
    setattr(lw.gh, how, None if how == "suite_at" else True)
    rc, out = lw.run("--deploy", "no")
    assert rc == 1, out
    assert f"FAIL  gate c: Review PASS after the last push, no fresh FAIL - cannot read the push time ({reason}); not merging" in out
    assert "REFUSED: 1 gate(s) failed (c): not merging" in out and lw.gh.writes() == []


def test_commit_then_review_then_push_does_not_count_the_review(lw):
    """B committed 10:02, a Review PASS (for A) at 10:05, B pushed 10:07 (the check suite is created then)."""
    lw.item(comments=[review(at="2026-10-23T10:05:00Z")])
    lw.gh.prs[50]["commits"][0]["committedDate"] = "2026-10-23T10:02:00Z"
    lw.gh.prs[50]["statusCheckRollup"][0]["startedAt"] = "2026-10-23T10:07:30Z"
    lw.gh.suite_at = "2026-10-23T10:07:00Z"
    rc, out = lw.run("--deploy", "no")
    assert rc == 1 and "FAIL  gate c" in out and "a later commit needs a fresh review" in out, out
    assert "all before the last push (2026-10-23T10:07Z)" in out


def test_force_push_with_an_old_committer_date_does_not_count_an_older_review(lw):
    """The head commit is dated 04:00 (a rebase keeps dates) but was force-pushed at 04:45, after the review at 04:30."""
    lw.item(comments=[review(at="2026-10-23T04:30:00Z")])
    lw.gh.force_pushed_at = "2026-10-23T04:45:00Z"
    rc, out = lw.run("--deploy", "no")
    assert rc == 1 and "FAIL  gate c" in out and "all before the last push (2026-10-23T04:45Z)" in out, out


def test_push_sources_are_read_for_the_head_sha_only(lw):
    lw.item()
    lw.gh.force_pushed_at, lw.gh.suite_at = "2026-10-23T04:45:00Z", "2026-10-23T04:00:10Z"
    got = jco.read_push_sources("example/joey", 50, FAKE_OID)
    assert got == {"force": jco._ts("2026-10-23T04:45:00Z"), "suite": jco._ts("2026-10-23T04:00:10Z"), "errors": []}
    other = jco.read_push_sources("example/joey", 50, "2" * 40)
    assert other["force"] is None and other["suite"] is None and len(other["errors"]) == 1


def test_all_failed_gates_listed_one_line_each(lw):
    lw.item(labels=(), comments=[], ci="FAILURE")
    lw.gh.prs[50]["isDraft"] = True
    rc, out = lw.run()
    assert rc == 1
    assert [x.split(":")[0] for x in rows(out) if x.startswith("FAIL")] == \
        ["FAIL  gate a", "FAIL  gate b", "FAIL  gate c", "FAIL  gate d", "FAIL  gates - 4 gate(s) failed (a, b, c, d)"]
    assert lw.gh.writes() == []


def test_a_broken_gate_does_not_hide_the_others(lw):
    lw.item(labels=())
    lw.gh.prs[50]["comments"] = [{"body": "Review: PASS", "createdAt": "not a time"}]
    rc, out = lw.run()
    assert rc == 1 and "FAIL  gate c" in out and "ValueError" in out and "FAIL  gate d" in out


def test_accept_comment_must_be_exact(lw):
    lw.item(labels=("review",), comments=[review(), {"body": "accepted, but fix the colour",
                                                      "createdAt": "2026-10-23T05:10:00Z"}])
    rc, out = lw.run()
    assert rc == 1 and "FAIL  gate d" in out


@pytest.mark.parametrize("words", ["accepted", "  "])
def test_accepted_in_chat_needs_words_and_a_date(lw, words):
    lw.item(labels=("review",))
    rc, out = lw.run("--accepted-in-chat", words)
    assert rc == 1 and "FAIL  gate d" in out and lw.gh.writes() == []


def test_no_open_pr_names_resume_when_a_merged_pr_exists(lw):
    lw.gh.prs[48] = dict(pr_view(48, f"feat/{ITEM}-old", "a" * 40), state="MERGED")
    rc, out = lw.run("--dry-run")
    assert rc == 1 and f"no open PR from feat/{ITEM}-* (#48 MERGED); to finish the close-out of #48, run again " \
                       "with --resume" in out
    assert lw.gh.writes() == []


def test_no_pr_at_all(lw):
    rc, out = lw.run("--resume")
    assert rc == 1 and f"REFUSED: no open PR from feat/{ITEM}-*" in out


def test_bad_id_refused(lw):
    assert jco.main(["JY-11", "--dry-run"]) == 1


def test_refuses_from_inside_the_item_worktree(lw, monkeypatch):
    lw.item()
    (lw.root / f"wt-{ITEM}").mkdir()
    monkeypatch.chdir(lw.root / f"wt-{ITEM}")
    rc, out = lw.run()
    assert rc == 1 and "run close-out from the main clone" in out and lw.gh.calls == []


@pytest.mark.parametrize("when, why", [
    (dt.datetime(2026, 10, 23, 11, 0, tzinfo=dt.timezone.utc), "Melbourne time 22:00 is outside"),
    (dt.datetime(2026, 10, 22, 19, 30, tzinfo=dt.timezone.utc), "Melbourne time 06:30 is outside"),
    (dt.datetime(2026, 10, 22, 23, 50, tzinfo=dt.timezone.utc), "in the 15 minutes before 00:00 UTC"),
])
def test_deploy_window_refuses_before_merging(lw, when, why):
    lw.item()
    lw.clock.t = when
    rc, out = lw.run()
    assert rc == 1 and "FAIL  deploy.1 deploy window" in out and why in out
    assert lw.gh.writes() == [] and lw.nas.calls == []


def test_window_rechecked_after_waiting_for_a_running_deploy(lw):
    lw.item()
    lw.clock.t = dt.datetime(2026, 10, 23, 10, 28, tzinfo=dt.timezone.utc)  # 21:28 Melbourne
    lw.nas.lock = ["4242", "4242", "4242", ""]
    rc, out = lw.run()
    assert rc == 1 and "after waiting for the running deploy: Melbourne time 21:31 is outside" in out
    assert_unchanged(lw)


def test_waits_for_a_running_deploy(lw):
    lw.item()
    lw.nas.lock = ["4242", "4242", ""]
    rc, out = lw.run("--dry-run")  # dry run never waits: it reports
    assert "a deploy is running (pid 4242); a real run would wait up to 90 min" in out
    lw.nas.lock = ["4242", "4242", ""]
    lw.gh.merge_mode = "fail"  # stop right after the preflight
    rc, out = lw.run()
    assert "PASS  deploy.2 no deploy running (waits) - no deploy running (waited 2 min, window ok)" in out
    assert lw.clock.slept >= 2 * jco.DEPLOY_POLL_S


@pytest.mark.parametrize("change, gate", [
    (lambda p: p["comments"].append(review("Review: FAIL, must-fix 1", at="2026-10-23T06:00:00Z")), "c"),
    (lambda p: p.update(labels=[{"name": "review"}]), "d"),
])
def test_gates_c_and_d_reread_after_waiting(lw, change, gate):
    lw.item()
    lw.nas.lock = ["4242", ""]
    lw.nas.on_wait = lambda: change(lw.gh.prs[50])
    rc, out = lw.run()
    assert rc == 1 and f"FAIL  gates c and d again, after the wait - after the wait: gate {gate}:" in out
    assert_unchanged(lw)


def test_gates_still_hold_after_waiting(lw):
    lw.item()
    lw.nas.lock = ["4242", ""]
    lw.gh.merge_mode = "fail"  # stop right after the re-check
    rc, out = lw.run()
    assert "PASS  gates c and d again, after the wait - gates c and d still hold after the wait" in out


def test_running_deploy_past_the_timeout_refuses(lw):
    lw.item()
    lw.nas.lock = ["4242"]
    rc, out = lw.run("--timeout", "3")
    assert rc == 1 and "a deploy still holds /tmp/joey-deploy.lock after 3 min" in out
    assert_unchanged(lw)


def test_low_memory_refuses(lw):
    lw.item()
    lw.nas.free = "1100"
    rc, out = lw.run()
    assert rc == 1 and "NAS available memory 1100 MB is under 1200 MB" in out
    assert_unchanged(lw)


def test_red_last_deploy_refuses_without_after_fail(lw):
    lw.item()
    lw.nas.last = ["2026-10-22T23:00:00Z GATE-FAIL prev=a new=b test build or suite red"]
    rc, out = lw.run()
    assert rc == 1 and "last history line is not green" in out
    assert_unchanged(lw)


def test_low_memory_skip_refuses_without_after_fail(lw):
    """JY-240: a SKIPPED-LOW-MEMORY line is not PASS / NOTHING-TO-DEPLOY, so close-out refuses until --after-fail."""
    lw.item()
    lw.nas.last = ["2026-10-24T05:00:00Z SKIPPED-LOW-MEMORY prev=a new=b available 1500 MB < 1650 MB before the gate"]
    rc, out = lw.run()
    assert rc == 1 and "last history line is not green" in out
    assert_unchanged(lw)


def test_failed_merge_never_deploys(lw):
    lw.item()
    lw.gh.merge_mode = "fail"
    rc, out = lw.run()
    assert rc == 1 and "FAIL  merge.1" in out and "(PR state now OPEN)" in out
    assert "nothing changed: the PR is not merged" in out
    assert not lw.nas.started and not any("deploy.sh" in c for c in lw.nas.calls)


def test_a_rename_from_code_is_not_doc_only(lw):
    lw.item(files=(), renames=[("docs/old_tool.md", "scripts/old_tool.py")])
    lw.clock.t = dt.datetime(2026, 10, 23, 11, 0, tzinfo=dt.timezone.utc)  # stop at the window
    rc, out = lw.run()
    assert "PASS  read the changed files - 2 path(s), 1 rename(s): old paths count too" in out
    assert "PASS  deploy decision - deploy: 1 changed path(s) beyond Markdown and .github/, e.g. scripts/old_tool.py" \
        in out


def test_nas_host_never_reaches_output_or_log(lw):
    lw.item()
    lw.nas.raise_on = "free -m"
    rc, out = lw.run()
    assert rc == 1 and "<nas>" in out
    assert "10.9.8.7" not in out and "10.9.8.7" not in lw.log_text()


# ================= pure =================
@pytest.mark.parametrize("mode, files, deploy", [
    ("auto", ["README.md", "docs/specs/JY-011-x.md", ".github/workflows/ci.yml"], False),
    ("auto", ["docs/a.MD"], False),
    ("auto", ["docs/a.md", "hub/main.py"], True),
    ("auto", [".github/pull_request_template.md", "deploy/deploy.sh"], True),
    ("auto", ["docs/new.md", "docs/old.md"], False),  # a doc-to-doc rename
    ("auto", [], True),
    ("auto", [f"docs/{i}.md" for i in range(jco.FILES_LIMIT)], True),
    ("yes", ["docs/a.md"], True),
    ("no", ["hub/main.py"], False),
])
def test_deploy_decision(mode, files, deploy):
    assert jco.deploy_decision(mode, files)[0] is deploy


def _v(**kw):
    v = pr_view(50, BRANCH, FAKE_OID)
    v.update(kw)
    return v


def test_gate_review_without_a_push_time_warns_and_counts_any_review():
    ok, detail, warns = jco.gate_review(_v(commits=[], statusCheckRollup=[], comments=[review(at="2020-01-01T00:00:00Z")]))
    assert ok and warns == ["no push time on the PR: a Review comment of any age counts"]
    assert "last push unknown" in detail


@pytest.mark.parametrize("kw, in_chat, label_time, warn", [
    ({}, None, jco._ts("2026-10-23T03:00:00Z"), "the accepted label (2026-10-23T03:00Z) is older than the last push"),
    ({}, None, None, "the accepted label: time unknown"),
    ({}, None, jco._ts("2026-10-23T05:30:00Z"), None),
    ({"labels": [], "comments": [{"body": "accepted", "createdAt": "2026-10-23T02:00:00Z"}]}, None, None,
     "the accepted comment (2026-10-23T02:00Z) is older than the last push"),
    ({"labels": []}, "B.: go with all, 2026-10-22", None, "the chat accept is dated 2026-10-22, before the last push"),
    ({"labels": []}, "B.: accepted 2026-10-23", None, None),
])
def test_stale_accepts_warn_but_pass(kw, in_chat, label_time, warn):
    ok, _, warns, source = jco.gate_accept(_v(**kw), in_chat, label_time)
    assert ok and source
    assert (warns == []) if warn is None else (len(warns) == 1 and warns[0].startswith(warn)), warns


def test_stale_label_warns_in_a_run(lw):
    lw.item(files=("docs/a.md",))
    lw.gh.label_time = "2026-10-23T03:00:00Z"
    lw.gh.merge_mode = "fail"
    rc, out = lw.run()
    assert "WARN  the accepted label (2026-10-23T03:00Z) is older than the last push (2026-10-23T04:00Z)" in out
    assert "PASS  gate d: B.'s accept - label accepted" in out


def test_edits_on_inline_fixtures():
    notes = jco.shipped_notes(50, "a" * 40, "`line`", "the `accepted` label on the PR", [])
    new_spec = jco.edit_spec(SPEC_TEXT, "2026-10-24", notes)
    assert "\nStatus: shipped 2026-10-24\n" in new_spec and "(filled at close-out)" not in new_spec
    assert new_spec.rstrip().endswith("- Follow-ups: none")
    before, after = SPEC_TEXT.split("## Shipped notes")[0].splitlines(), new_spec.split("## Shipped notes")[0].splitlines()
    assert [(a, b) for a, b in zip(before, after) if a != b] == [("Status: building", "Status: shipped 2026-10-24")]
    assert not any(jco.DATE_RE.search(x) for x in notes)  # the date lives in Status: only (money guard)
    new_hit = jco.edit_hitlist(HITLIST_TEXT, ITEM, 50, SPEC)
    row = [x for x in new_hit.splitlines() if x.startswith(f"| {ITEM} |")][0]
    assert row.split("|")[5].strip() == "[x] shipped" and "PR #50" in row and row.endswith(f"| [spec]({SPEC}) |")
    changed = [(a, b) for a, b in zip(HITLIST_TEXT.splitlines(), new_hit.splitlines()) if a != b]
    assert len(changed) == 1 and len(HITLIST_TEXT.splitlines()) == len(new_hit.splitlines())
    assert jco.edit_hitlist(new_hit, ITEM, 50, SPEC).count("PR #50") == 1  # idempotent


def test_edit_spec_keeps_later_sections():
    text = "Status: ready\n\n## Shipped notes\nold\n\n## Round 2\nkeep me\n"
    assert jco.edit_spec(text, "2026-10-24", ["- new"]) == \
        "Status: shipped 2026-10-24\n\n## Shipped notes\n- new\n\n## Round 2\nkeep me\n"


@pytest.mark.parametrize("text, why", [("# x\n\n## Shipped notes\n", "no `Status:` line"),
                                       ("Status: ready\n", "0 `## Shipped notes` headings")])
def test_edit_spec_refuses_without_its_anchors(text, why):
    with pytest.raises(joey_common.Refused, match=why):
        jco.edit_spec(text, "2026-10-24", [])


def test_edit_hitlist_refuses_missing_row():
    with pytest.raises(joey_common.Refused, match="0 rows for JY-099"):
        jco.edit_hitlist(HITLIST_TEXT, "JY-099", 1, "docs/specs/x.md")


def test_mask_host(monkeypatch):
    monkeypatch.setenv("JOEY_NAS", "root@192.168.1.50")
    assert jco._mask_host("connect to root@192.168.1.50 / 192.168.1.50 failed") == "connect to <nas> / <nas> failed"


@pytest.mark.parametrize("line, ok", [
    ("2026-10-23T01:10:00Z PASS prev=aaaaaaa new=abcdef1 suite green, smoke ok tv=current", True),
    ("2026-10-23T01:10:00Z PASS prev=aaaaaaa new=abcdef9 suite green", False),
    ("2026-10-23T01:10:00Z ROLLED-BACK prev=aaaaaaa new=abcdef1 smoke failed", False),
    ("2026-10-23T01:10:00Z NOTHING-TO-DEPLOY prev=abcdef1 new=abcdef1 already", False),
    ("2026-10-24T05:00:00Z SKIPPED-LOW-MEMORY prev=aaaaaaa new=abcdef1 available 1500 MB < 1650 MB", False),
])
def test_history_ok(line, ok):
    assert jco.history_ok(line, "abcdef1" + "0" * 33) is ok


def test_container_cmd_and_judge():
    assert jco.CONTAINER_CMD == (
        "for c in joey-hub joey-media joey-swag; do s=$(docker inspect -f "
        "'{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{end}}' $c 2>/dev/null) "
        "|| s=absent; echo \"$c $s\"; done")
    assert jco.judge_containers("joey-hub running healthy\njoey-media running healthy\njoey-swag running")[0] == "ok"
    assert jco.judge_containers("joey-hub running healthy\njoey-media running starting\njoey-swag running")[0] == "wait"


def test_melbourne_fallback_matches_zoneinfo():
    zi = pytest.importorskip("zoneinfo")
    try:
        tz = zi.ZoneInfo("Australia/Melbourne")
    except Exception:  # noqa: BLE001
        pytest.skip("no tz database here")
    t = dt.datetime(2025, 1, 1, tzinfo=dt.timezone.utc)
    while t < dt.datetime(2028, 1, 1, tzinfo=dt.timezone.utc):
        assert jco.melbourne_fallback(t).utcoffset() == t.astimezone(tz).utcoffset(), t
        t += dt.timedelta(hours=7)
    for edge in (dt.datetime(2026, 10, 3, 15, 59, tzinfo=dt.timezone.utc),
                 dt.datetime(2026, 10, 3, 16, 0, tzinfo=dt.timezone.utc),
                 dt.datetime(2026, 4, 4, 15, 59, tzinfo=dt.timezone.utc),
                 dt.datetime(2026, 4, 4, 16, 0, tzinfo=dt.timezone.utc)):
        assert jco.melbourne_fallback(edge).utcoffset() == edge.astimezone(tz).utcoffset(), edge


def test_window_uses_the_fallback_without_a_tz_database(monkeypatch):
    import builtins
    real_import = builtins.__import__

    def no_zoneinfo(name, *a, **k):
        if name == "zoneinfo":
            raise ImportError("no zoneinfo")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", no_zoneinfo)
    assert jco.melbourne(NOON_AEDT).hour == 12
    assert jco.window_problem(NOON_AEDT) is None
    assert "21:31" in jco.window_problem(dt.datetime(2026, 10, 23, 10, 31, tzinfo=dt.timezone.utc))


def test_stale_accept_warning_uses_the_same_push_time():
    v = _v(headPush={"force": None, "suite": jco._ts("2026-10-23T05:40:00Z"), "errors": []})
    ok, _, warns, _ = jco.gate_accept(v, None, jco._ts("2026-10-23T05:30:00Z"))
    assert ok and len(warns) == 1 and "older than the last push (2026-10-23T05:40Z)" in warns[0], warns
