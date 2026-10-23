"""JY-010: scripts/joey.py worktree new / remove / list against a throwaway origin (bare repo) and clone in tmp_path.

gh is a fake script (JOEY_GH -> fake_gh.py, run with this Python): it answers `pr list` from a JSON file and logs every
call, so nothing touches the network. origin's URL is a github.com URL that `url.<bare>.insteadOf` maps onto the bare
repo, so repo_slug() and git fetch/push both work offline. The CLI runs as a subprocess, as a user would run it.
Skips when git is not on PATH. Runs on Windows (laptop) and Linux (CI, gate image as user joey)."""
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
JOEY = REPO_ROOT / "scripts" / "joey.py"
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import joey_common  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not on PATH")

GH_URL = "https://github.com/example/joey.git"
TOKEN = "ghp_FAKE0123456789abcdefABCDEF0123456789"

FAKE_GH = r'''
import json, os, sys
args = sys.argv[1:]
with open(os.environ["FAKE_GH_LOG"], "a", encoding="utf-8") as f:
    f.write(json.dumps(args) + "\n")
if os.environ.get("FAKE_GH_FAIL"):
    sys.stderr.write(os.environ["FAKE_GH_FAIL"] + "\n")
    sys.exit(1)
with open(os.environ["FAKE_GH_PRS"], encoding="utf-8") as f:
    prs = json.load(f)
if "--head" in args:
    head = args[args.index("--head") + 1]
    prs = [p for p in prs if p["headRefName"] == head]
fields = args[args.index("--json") + 1].split(",")
print(json.dumps([{k: p[k] for k in fields if k in p} for p in prs]))
'''


class Repo:
    """A bare origin + a clone of it, a fake gh, and a runner for the CLI."""

    def __init__(self, tmp_path, origin_url=GH_URL):
        self.root = tmp_path
        self.origin = tmp_path / "origin.git"
        self.clone = tmp_path / "life-dashboard"
        self.prs_file = tmp_path / "prs.json"
        self.gh_log = tmp_path / "gh_calls.log"
        fake = tmp_path / "fake_gh.py"
        fake.write_text(FAKE_GH, encoding="utf-8")
        gitconfig = tmp_path / "gitconfig"
        gitconfig.write_text("", encoding="utf-8")
        self.env = dict(os.environ)
        self.env.update({
            "GIT_AUTHOR_NAME": "Joey Test", "GIT_AUTHOR_EMAIL": "joey@example.invalid",
            "GIT_COMMITTER_NAME": "Joey Test", "GIT_COMMITTER_EMAIL": "joey@example.invalid",
            "GIT_CONFIG_GLOBAL": str(gitconfig), "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0",
            "JOEY_GH": str(fake), "FAKE_GH_PRS": str(self.prs_file), "FAKE_GH_LOG": str(self.gh_log),
        })
        for k in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "FAKE_GH_FAIL"):
            self.env.pop(k, None)
        self.set_prs([])
        self.git("init", "-q", "--bare", "-b", "main", str(self.origin), cwd=tmp_path)
        self.git("init", "-q", "-b", "main", str(self.clone), cwd=tmp_path)
        (self.clone / ".gitignore").write_text(".env\n/data/\n/.joey/\n", encoding="utf-8")
        (self.clone / "README.md").write_text("joey\n", encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "-q", "-m", "init")
        self.git("remote", "add", "origin", origin_url)
        self.git("config", f"url.{self.origin.as_posix()}.insteadOf", origin_url)
        self.git("push", "-q", "-u", "origin", "main")

    def git(self, *args, cwd=None):
        r = subprocess.run(["git", *args], cwd=cwd or self.clone, env=self.env, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        assert r.returncode == 0, f"git {args}: {r.stderr}"
        return r.stdout.strip()

    def joey(self, *args, cwd=None, **env):
        e = dict(self.env, **env)
        return subprocess.run([sys.executable, str(JOEY), *args], cwd=cwd or self.clone, env=e, capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=120)

    def set_prs(self, prs):
        self.prs_file.write_text(json.dumps(prs), encoding="utf-8")

    def gh_calls(self):
        if not self.gh_log.exists():
            return []
        return [json.loads(x) for x in self.gh_log.read_text(encoding="utf-8").splitlines()]

    def wt(self, item):
        return self.root / f"wt-{item}"

    def branches(self):
        return set(self.git("branch", "--format=%(refname:short)").split())

    def worktree_paths(self):
        out = self.git("worktree", "list", "--porcelain")
        return {os.path.normcase(os.path.realpath(x[9:])) for x in out.splitlines() if x.startswith("worktree ")}

    def has_worktree(self, path):
        return os.path.normcase(os.path.realpath(path)) in self.worktree_paths()

    def item(self, item, slug, commit=True, push=True):
        """A JY worktree made by the tool, with one commit on its branch (pushed). Returns (path, branch, tip)."""
        r = self.joey("worktree", "new", item, slug)
        assert r.returncode == 0, r.stdout + r.stderr
        path, branch = self.wt(item), f"feat/{item}-{slug}"
        if commit:
            (path / f"{slug}.txt").write_text("work\n", encoding="utf-8")
            self.git("add", f"{slug}.txt", cwd=path)
            self.git("commit", "-q", "-m", f"{item}: work", cwd=path)
        if push:
            self.git("push", "-q", "origin", branch, cwd=path)
        return path, branch, self.git("rev-parse", "HEAD", cwd=path)

    def log_text(self):
        logs = list((self.clone / ".joey" / "logs").glob("joey_*.log"))
        assert logs, "no log written"
        return "\n".join(p.read_text(encoding="utf-8") for p in logs)


@pytest.fixture
def repo(tmp_path):
    return Repo(tmp_path)


def pr(number, state, branch, oid, base="main"):
    return {"number": number, "state": state, "headRefName": branch, "headRefOid": oid, "baseRefName": base}


# ---------- new ----------
def test_new_makes_worktree_branch_and_env(repo):
    main_sha = repo.git("rev-parse", "origin/main")
    r = repo.joey("worktree", "new", "JY-010", "worktree")
    assert r.returncode == 0, r.stdout + r.stderr
    wt = repo.wt("JY-010")
    assert repo.has_worktree(wt)
    assert repo.git("rev-parse", "--abbrev-ref", "HEAD", cwd=wt) == "feat/JY-010-worktree"
    assert repo.git("rev-parse", "HEAD", cwd=wt) == main_sha
    env = dict(line.split("=", 1) for line in (wt / ".env").read_text(encoding="utf-8").splitlines())
    assert env["JOEY_ITEM"] == "JY-010"
    assert env["HUB_PORT"] == "9010"
    assert env["SNAPSHOT_DIR"] == "data/demo-snapshots"
    dev = os.path.normcase(os.path.realpath(wt / "data" / "dev"))
    for key in ("MEDIA_DB_PATH", "MEDIA_BACKUP_DIR", "META_CACHE_DIR"):
        assert os.path.normcase(os.path.realpath(env[key])).startswith(dev + os.sep), key
    assert (wt / "data" / "dev").is_dir()
    assert "--port 9010" in r.stdout and '$env:HUB_PORT="9010"' in r.stdout
    assert "PASS  git worktree add" in r.stdout
    assert repo.git("status", "--porcelain", cwd=wt) == ""  # .env and data/ stay ignored


def test_new_works_from_inside_another_worktree(repo):
    other, _, _ = repo.item("JY-001", "first", commit=False, push=False)
    r = repo.joey("worktree", "new", "JY-002", "second", cwd=other)
    assert r.returncode == 0, r.stdout + r.stderr
    assert repo.has_worktree(repo.wt("JY-002"))  # beside the main clone, not inside wt-JY-001
    assert not (other.parent / "wt-JY-001" / "wt-JY-002").exists()


@pytest.mark.parametrize("args, reason", [
    (("JY-12", "x"), "bad id"),
    (("jy-012", "x"), "bad id"),
    (("JY-0123", "x"), "bad id"),
    (("JY-012", "Bad_Slug"), "bad slug"),
    (("JY-012", "a b"), "bad slug"),
])
def test_new_refuses_bad_id_or_slug(repo, args, reason):
    before = (repo.branches(), repo.worktree_paths())
    r = repo.joey("worktree", "new", *args)
    assert r.returncode == 1
    assert f"REFUSED: {reason}" in r.stdout
    assert (repo.branches(), repo.worktree_paths()) == before


def test_new_refuses_existing_path(repo):
    repo.wt("JY-012").mkdir()
    before = (repo.branches(), repo.worktree_paths())
    r = repo.joey("worktree", "new", "JY-012", "x")
    assert r.returncode == 1 and "already exists" in r.stdout.splitlines()[-1]
    assert (repo.branches(), repo.worktree_paths()) == before


def test_new_refuses_local_branch(repo):
    repo.git("branch", "feat/JY-012-x")
    before = (repo.branches(), repo.worktree_paths())
    r = repo.joey("worktree", "new", "JY-012", "x")
    assert r.returncode == 1 and "exists locally" in r.stdout.splitlines()[-1]
    assert (repo.branches(), repo.worktree_paths()) == before
    assert not repo.wt("JY-012").exists()


def test_new_refuses_branch_on_origin(repo):
    repo.git("branch", "feat/JY-012-x")
    repo.git("push", "-q", "origin", "feat/JY-012-x")
    repo.git("branch", "-D", "feat/JY-012-x")
    before = (repo.branches(), repo.worktree_paths())
    r = repo.joey("worktree", "new", "JY-012", "x")
    assert r.returncode == 1 and "exists on origin" in r.stdout.splitlines()[-1]
    assert (repo.branches(), repo.worktree_paths()) == before
    assert not repo.wt("JY-012").exists()


def test_new_dry_run_changes_nothing(repo):
    before = (repo.branches(), repo.worktree_paths())
    r = repo.joey("worktree", "new", "JY-012", "x", "--dry-run")
    assert r.returncode == 0, r.stdout
    assert "DRY   git worktree add - would run: git worktree add" in r.stdout
    assert "DRY   write .env" in r.stdout
    assert (repo.branches(), repo.worktree_paths()) == before
    assert not repo.wt("JY-012").exists()


# ---------- remove ----------
def test_remove_on_merged_pr_at_tip_squash(repo):
    path, branch, tip = repo.item("JY-020", "squash")
    # squash merge on origin: main gets a new commit, the branch tip is NOT an ancestor of it
    repo.git("merge", "-q", "--squash", branch)
    repo.git("commit", "-q", "-m", "JY-020: squash (#5)")
    repo.git("push", "-q", "origin", "main")
    repo.set_prs([pr(5, "MERGED", branch, tip)])
    r = repo.joey("worktree", "remove", "JY-020")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS  merged proof - PR #5 MERGED into main at the local tip" in r.stdout
    assert not repo.has_worktree(path) and not path.exists()
    assert branch not in repo.branches()


def test_remove_path_on_ancestry_for_old_branch(repo):
    old = repo.root / "wt-old-thing"
    repo.git("worktree", "add", "-q", str(old), "-b", "old-thing", "origin/main")
    (old / "o.txt").write_text("o\n", encoding="utf-8")
    repo.git("add", "o.txt", cwd=old)
    repo.git("commit", "-q", "-m", "old work", cwd=old)
    repo.git("merge", "-q", "--no-ff", "-m", "merge old-thing", "old-thing")  # a plain merge
    repo.git("push", "-q", "origin", "main")
    r = repo.joey("worktree", "remove", "--path", str(old))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "is an ancestor of origin/main" in r.stdout
    assert not repo.has_worktree(old) and "old-thing" not in repo.branches()


@pytest.mark.parametrize("state", ["OPEN", "CLOSED"])
def test_remove_refuses_open_or_closed_pr(repo, state):
    path, branch, tip = repo.item("JY-021", "pr")
    repo.set_prs([pr(6, state, branch, tip)])
    r = repo.joey("worktree", "remove", "JY-021")
    assert r.returncode == 1
    assert f"REFUSED: PR #6 is {state}" in r.stdout
    assert repo.has_worktree(path) and branch in repo.branches()


def test_remove_refuses_closed_pr_even_when_ancestor(repo):
    path, branch, tip = repo.item("JY-021", "closed")
    repo.git("merge", "-q", "--ff-only", branch)
    repo.git("push", "-q", "origin", "main")
    repo.set_prs([pr(6, "CLOSED", branch, tip)])
    r = repo.joey("worktree", "remove", "JY-021")
    assert r.returncode == 1 and "REFUSED: PR #6 is CLOSED unmerged" in r.stdout
    assert repo.has_worktree(path) and branch in repo.branches()


def test_remove_refuses_merged_pr_at_another_sha(repo):
    path, branch, tip = repo.item("JY-022", "late")
    (path / "late2.txt").write_text("more\n", encoding="utf-8")
    repo.git("add", "late2.txt", cwd=path)
    repo.git("commit", "-q", "-m", "local only", cwd=path)
    repo.set_prs([pr(7, "MERGED", branch, tip)])  # the PR merged at the older tip
    r = repo.joey("worktree", "remove", "JY-022")
    assert r.returncode == 1 and "local commits never reached the PR" in r.stdout
    assert repo.has_worktree(path) and branch in repo.branches()


def test_remove_refuses_without_proof(repo):
    path, branch, _ = repo.item("JY-023", "noproof")
    r = repo.joey("worktree", "remove", "JY-023")
    assert r.returncode == 1 and "REFUSED: no merged PR" in r.stdout
    assert repo.has_worktree(path) and branch in repo.branches()


@pytest.mark.parametrize("kind", ["untracked", "modified"])
def test_remove_refuses_dirty_worktree(repo, kind):
    path, branch, tip = repo.item("JY-024", "dirty")
    repo.set_prs([pr(8, "MERGED", branch, tip)])
    if kind == "untracked":
        (path / "new.txt").write_text("x\n", encoding="utf-8")
    else:
        (path / "dirty.txt").write_text("changed\n", encoding="utf-8")
    r = repo.joey("worktree", "remove", "JY-024")
    assert r.returncode == 1 and "uncommitted or untracked changes" in r.stdout
    assert repo.has_worktree(path) and branch in repo.branches() and path.exists()


def test_remove_refuses_main_clone(repo):
    before = (repo.branches(), repo.worktree_paths())
    r = repo.joey("worktree", "remove", "--path", str(repo.clone))
    assert r.returncode == 1 and "REFUSED: that is the main clone" in r.stdout
    assert (repo.branches(), repo.worktree_paths()) == before


def test_remove_refuses_from_inside_the_worktree_after_the_proof(repo):
    path, branch, tip = repo.item("JY-027", "inside")
    repo.set_prs([pr(12, "MERGED", branch, tip)])
    r = repo.joey("worktree", "remove", "JY-027", cwd=path)
    assert r.returncode == 1 and "PASS  merged proof" in r.stdout and "REFUSED: you are inside that worktree" in r.stdout
    assert repo.has_worktree(path) and branch in repo.branches()


def test_remove_refuses_when_gh_fails_for_a_jy_branch(repo):
    path, branch, tip = repo.item("JY-025", "ghdown")
    repo.git("merge", "-q", "--ff-only", branch)
    repo.git("push", "-q", "origin", "main")  # ancestry alone would say merged
    r = repo.joey("worktree", "remove", "JY-025", FAKE_GH_FAIL="HTTP 401: Bad credentials")
    assert r.returncode == 1 and "a JY branch needs the gh check" in r.stdout
    assert repo.has_worktree(path) and branch in repo.branches()


def test_remove_dry_run_changes_nothing(repo):
    path, branch, tip = repo.item("JY-026", "dry")
    repo.set_prs([pr(9, "MERGED", branch, tip)])
    r = repo.joey("worktree", "remove", "JY-026", "--dry-run")
    assert r.returncode == 0, r.stdout
    assert "PASS  merged proof" in r.stdout
    assert "DRY   git worktree remove - would run: git worktree remove" in r.stdout
    assert f"DRY   git branch -D - would run: git branch -D {branch}" in r.stdout
    assert repo.has_worktree(path) and branch in repo.branches()


# ---------- list ----------
def test_list_one_gh_call_and_a_verdict_per_row(repo):
    merged, b_merged, tip_m = repo.item("JY-030", "merged")
    _, b_open, tip_o = repo.item("JY-031", "open")
    _, b_none, _ = repo.item("JY-032", "none")
    repo.git("worktree", "add", "-q", "--detach", str(repo.root / "wt-detached"), "origin/main")
    repo.set_prs([pr(10, "MERGED", b_merged, tip_m), pr(11, "OPEN", b_open, tip_o)])
    before_calls = len(repo.gh_calls())
    r = repo.joey("worktree", "list")
    assert r.returncode == 0, r.stdout + r.stderr
    calls = repo.gh_calls()[before_calls:]
    assert len(calls) == 1 and "--limit" in calls[0] and calls[0][calls[0].index("--limit") + 1] == "300"
    rows = {line.split()[0]: line for line in r.stdout.splitlines() if " removable " in line}
    assert rows["life-dashboard"].endswith("removable no (main clone)")
    assert "#10 MERGED" in rows["wt-JY-030"] and "removable yes (PR #10 MERGED" in rows["wt-JY-030"]
    assert "#11 OPEN" in rows["wt-JY-031"] and "removable no (PR #11 is OPEN)" in rows["wt-JY-031"]
    assert b_none in rows["wt-JY-032"] and "removable no (no merged PR" in rows["wt-JY-032"]
    assert "removable no (detached HEAD" in rows["wt-detached"]
    assert repo.has_worktree(merged)  # list removes nothing


def test_list_dry_run_changes_nothing(repo):
    repo.item("JY-033", "x")
    before = (repo.branches(), repo.worktree_paths(), repo.git("rev-parse", "origin/main"))
    r = repo.joey("worktree", "list", "--dry-run")
    assert r.returncode == 0, r.stdout
    assert "DRY   git fetch origin" in r.stdout and "wt-JY-033" in r.stdout
    assert (repo.branches(), repo.worktree_paths(), repo.git("rev-parse", "origin/main")) == before


# ---------- log and secrets ----------
TOKENISH = re.compile(r"gh[pousr]_[A-Za-z0-9]{8,}|github_pat_|://(?!<redacted>@)[^/\s]*@|Bearer\s+(?!<redacted>)\S|"
                      r"[\w.+-]+@[\w-]+\.[\w.-]+")


def test_log_lands_in_clone_and_never_holds_a_token(tmp_path):
    url = f"https://x-access-token:{TOKEN}@github.com/example/joey.git"
    repo = Repo(tmp_path, origin_url=url)
    path, branch, tip = repo.item("JY-040", "secret")
    repo.joey("worktree", "list")
    r = repo.joey("worktree", "remove", "JY-040",
                  FAKE_GH_FAIL=f"HTTP 401 for {url}: Bearer {TOKEN} X-Api-Key: abc123 user someone@example.com")
    assert r.returncode == 1
    log = repo.log_text()
    assert (repo.clone / ".joey" / "logs" / f"joey_{dt.date.today():%Y-%m-%d}.log").exists()
    assert "worktree new" in log and "worktree list" in log and "REFUSED" in log
    assert TOKEN not in log and "abc123" not in log
    assert not TOKENISH.search(log), TOKENISH.search(log).group(0)
    assert TOKEN not in r.stdout
    # the slug came from the credentialed URL without printing it
    assert any("example/joey" in c for c in repo.gh_calls()[-1])


def test_redact_masks_secrets():
    line = (f"Bearer abc.def X-Api-Key: k123 Token=\"t456\" {TOKEN} github_pat_ABC_123 "
            f"https://user:pw@github.com/o/r a.b@example.com api_key=zzz")
    out = joey_common.redact(line)
    for secret in ("abc.def", "k123", "t456", TOKEN, "github_pat_ABC", "user:pw", "a.b@example.com", "zzz"):
        assert secret not in out, secret


def test_redact_masks_home():
    home = os.path.expanduser("~")
    if not home or home in ("~", "/") or (os.name != "nt" and os.environ.get("HOME") in (None, "", "/")):
        pytest.skip("no real home folder (gate image)")
    assert joey_common.redact(f"at {home}{os.sep}Desktop") == f"at ~{os.sep}Desktop"


# ---------- the dispatcher and helpers ----------
def test_dispatcher_is_thin_and_import_does_no_work(monkeypatch):
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: calls.append(a))
    import importlib
    import joey
    importlib.reload(joey)
    # 2026-10-23 JY-012: re-pinned from {"worktree"}: the spec adds the preview command (still an exact set)
    assert set(joey.COMMANDS) == {"worktree", "preview"}
    assert joey.COMMANDS["worktree"].__name__ == "joey_worktree"
    assert calls == []


def test_ssh_uses_batchmode_key_and_utf8(monkeypatch):
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"], seen["kw"] = cmd, kw
        return subprocess.CompletedProcess(cmd, 0, stdout=" ok \n", stderr="")

    monkeypatch.setattr(joey_common.subprocess, "run", fake_run)
    monkeypatch.delenv("JOEY_NAS", raising=False)
    monkeypatch.delenv("JOEY_NAS_KEY", raising=False)
    assert joey_common.ssh("uptime", stdin="café") == "ok"
    cmd = seen["cmd"]
    assert cmd[0] == "ssh" and cmd[-2:] == ["root@nas.local", "uptime"]
    assert cmd[cmd.index("-i") + 1] == os.path.expanduser("~/.ssh/joey_nas")
    assert "BatchMode=yes" in cmd and "ConnectTimeout=10" in cmd
    assert seen["kw"]["encoding"] == "utf-8" and seen["kw"]["input"] == "café"
    monkeypatch.setenv("JOEY_NAS", "root@other")
    joey_common.ssh("true")
    assert seen["cmd"][-2] == "root@other"


def test_repo_slug_strips_credentials(tmp_path):
    repo = Repo(tmp_path, origin_url=f"https://x-access-token:{TOKEN}@github.com/example/joey.git")
    assert joey_common.repo_slug(repo.clone) == "example/joey"


# ---------- review fixes (2026-10-23) ----------
def test_remove_refuses_pr_merged_into_a_stacked_branch(repo):
    path, branch, tip = repo.item("JY-028", "stacked")
    repo.set_prs([pr(13, "MERGED", branch, tip, base="feat/JY-027-base")])
    r = repo.joey("worktree", "remove", "JY-028")
    assert r.returncode == 1 and "REFUSED: PR #13 MERGED into feat/JY-027-base, not main" in r.stdout
    assert repo.has_worktree(path) and branch in repo.branches()


def test_new_and_remove_with_spaces_in_the_path(tmp_path):
    root = tmp_path / "my repos"
    root.mkdir()
    repo = Repo(root)
    path, branch, tip = repo.item("JY-060", "spaces")
    assert " " in str(path) and (path / ".env").exists()
    repo.set_prs([pr(14, "MERGED", branch, tip)])
    r = repo.joey("worktree", "remove", "JY-060")
    assert r.returncode == 0, r.stdout + r.stderr
    assert not repo.has_worktree(path) and branch not in repo.branches()


def test_remove_refuses_detached_worktree(repo):
    det = repo.root / "wt-detached"
    repo.git("worktree", "add", "-q", "--detach", str(det), "origin/main")
    r = repo.joey("worktree", "remove", "--path", str(det))
    assert r.returncode == 1 and "REFUSED: wt-detached has no branch (detached HEAD)" in r.stdout
    assert repo.has_worktree(det)


def test_remove_gh_failure_on_a_non_jy_branch_falls_back_to_ancestry(repo):
    old = repo.root / "wt-older"
    repo.git("worktree", "add", "-q", str(old), "-b", "older", "origin/main")
    (old / "o.txt").write_text("o\n", encoding="utf-8")
    repo.git("add", "o.txt", cwd=old)
    repo.git("commit", "-q", "-m", "older work", cwd=old)
    repo.git("merge", "-q", "--no-ff", "-m", "merge older", "older")
    repo.git("push", "-q", "origin", "main")
    r = repo.joey("worktree", "remove", "--path", str(old), FAKE_GH_FAIL="HTTP 502")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "SKIP  gh pr list" in r.stdout and "is an ancestor of origin/main" in r.stdout
    assert not repo.has_worktree(old) and "older" not in repo.branches()


def test_missing_worktree_folder_gives_a_clear_refusal(repo):
    path, branch, tip = repo.item("JY-061", "gone")
    repo.set_prs([pr(15, "MERGED", branch, tip)])
    shutil.rmtree(path)
    r = repo.joey("worktree", "remove", "JY-061")
    assert r.returncode == 1 and "REFUSED: wt-JY-061: the folder is missing; run git worktree prune" in r.stdout
    assert branch in repo.branches()
    rows = [line for line in repo.joey("worktree", "list").stdout.splitlines() if line.startswith("wt-JY-061")]
    assert rows and rows[0].endswith("removable no (folder missing: git worktree prune)")


def test_new_says_clearly_when_env_write_fails_after_add(repo, monkeypatch, capsys):
    import joey_worktree
    for key in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL",
                "GIT_CONFIG_GLOBAL", "GIT_CONFIG_NOSYSTEM", "JOEY_GH"):
        monkeypatch.setenv(key, repo.env[key])
    monkeypatch.chdir(repo.clone)
    real = Path.write_text

    def boom(self, *a, **k):
        if self.name == ".env":
            raise OSError("disk full")
        return real(self, *a, **k)

    monkeypatch.setattr(Path, "write_text", boom)
    assert joey_worktree.main(["new", "JY-062", "x"]) == 1
    out = capsys.readouterr().out
    assert "wt-JY-062 and feat/JY-062-x WERE created, but writing .env failed (disk full)" in out
    assert repo.has_worktree(repo.wt("JY-062"))  # no auto-cleanup


def test_id_and_slug_must_match_fully(repo):
    for args in (("JY-012\n", "x"), ("JY-012", "x\n")):
        r = repo.joey("worktree", "new", *args)
        assert r.returncode == 1 and "REFUSED: bad" in r.stdout


class _FakeRun:
    def __init__(self, rc=0, exc=None):
        self.rc, self.exc, self.calls = rc, exc, []

    def __call__(self, cmd, **kw):
        self.calls.append((cmd, kw))
        if self.exc:
            raise self.exc
        return subprocess.CompletedProcess(cmd, self.rc, stdout="out\n", stderr="err line\n")


def test_ssh_run_returns_the_completed_process_and_raises_clearly(monkeypatch):
    fake = _FakeRun(rc=3)
    monkeypatch.setattr(joey_common.subprocess, "run", fake)
    r = joey_common.ssh_run("false")
    assert (r.returncode, r.stdout, r.stderr) == (3, "out\n", "err line\n")
    cmd, kw = fake.calls[-1]
    assert "BatchMode=yes" in cmd and "ConnectTimeout=10" in cmd and kw["encoding"] == "utf-8"
    assert kw["stdin"] is subprocess.DEVNULL and "input" not in kw
    joey_common.ssh_run("cat", stdin="x")
    assert fake.calls[-1][1]["input"] == "x" and "stdin" not in fake.calls[-1][1]
    monkeypatch.setattr(joey_common.subprocess, "run", _FakeRun(rc=255))
    with pytest.raises(RuntimeError, match="ssh to the NAS failed"):
        joey_common.ssh_run("true")
    monkeypatch.setattr(joey_common.subprocess, "run", _FakeRun(exc=FileNotFoundError("ssh")))
    for fn in (joey_common.ssh_run, joey_common.ssh):
        with pytest.raises(RuntimeError, match="ssh is not on PATH"):
            fn("true")


def test_runner_ssh_change_never_reaches_the_nas_in_a_dry_run(monkeypatch):
    fake = _FakeRun()
    monkeypatch.setattr(joey_common.subprocess, "run", fake)
    with pytest.raises(joey_common.DryRun, match="ssh NAS: docker restart x"):
        joey_common.Runner("t", dry_run=True).ssh_change("docker restart x")
    assert fake.calls == []
    assert joey_common.Runner("t").ssh_change("docker restart x").returncode == 0
    assert fake.calls[-1][0][-1] == "docker restart x"


def test_run_closes_stdin_and_disables_git_prompts(monkeypatch):
    fake = _FakeRun()
    monkeypatch.setattr(joey_common.subprocess, "run", fake)
    joey_common.run(["git", "fetch"])
    kw = fake.calls[-1][1]
    assert kw["stdin"] is subprocess.DEVNULL and kw["env"]["GIT_TERMINAL_PROMPT"] == "0"
    joey_common.run(["cat"], stdin="hi")
    assert fake.calls[-1][1]["input"] == "hi"
