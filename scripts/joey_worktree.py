"""joey.py worktree new / remove / list (JY-010).

  python scripts/joey.py worktree new JY-### slug        worktree <clone>/../wt-JY-### on feat/JY-###-slug from origin/main
  python scripts/joey.py worktree remove JY-###          remove it and its branch, only when proven merged
  python scripts/joey.py worktree remove --path <dir>    the same for an older non-JY worktree
  python scripts/joey.py worktree list                   every worktree: branch, PR, removable yes/no (why)
  Every subcommand takes --dry-run (prints each step and the command it would run; changes nothing).

Merged proof (remove and list): (a) `gh pr list --head <branch> --state all` has a MERGED PR whose head SHA equals the
local branch tip (squash merges); or (b) the tip is an ancestor of origin/main (plain merges, older branches). An OPEN
PR, a CLOSED unmerged PR or a MERGED PR at another SHA refuses, whatever the ancestry says. JY branches always need the
gh check to run. Removal is `git worktree remove` (never --force), then `git branch -D`.
"""
import argparse
import os
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import joey_common as jc

ID_RE = re.compile(r"JY-([0-9]{3})")  # used with fullmatch
SLUG_RE = re.compile(r"[a-z0-9-]+")  # used with fullmatch
JY_BRANCH_RE = re.compile(r"^feat/JY-[0-9]{3}-")
PR_FIELDS = "number,state,headRefName,headRefOid,baseRefName"
LIST_LIMIT = 300


def norm(p):
    return os.path.normcase(os.path.realpath(str(p)))


def show(path, clone):
    """A worktree path for printing: the folder name for siblings of the clone, else the (redacted) full path."""
    p = Path(path)
    return p.name if norm(p.parent) == norm(Path(clone).parent) else str(p)


def worktrees(clone):
    """`git worktree list --porcelain` as dicts: path, head, branch (short name or None), bare, locked, prunable.
    The first entry is the main clone."""
    out, cur = [], None
    for line in jc.git("worktree", "list", "--porcelain", cwd=clone).splitlines() + [""]:
        if not line:
            if cur:
                out.append(cur)
            cur = None
            continue
        key, _, val = line.partition(" ")
        if key == "worktree":
            cur = {"path": val, "head": "", "branch": None, "bare": False, "locked": False, "prunable": False}
        elif cur is None:
            continue
        elif key == "HEAD":
            cur["head"] = val
        elif key == "branch":
            cur["branch"] = val.removeprefix("refs/heads/")
        elif key in ("bare", "locked", "prunable"):
            cur[key] = True
    return out


def dirty_count(path):
    return len(jc.git("status", "--porcelain", cwd=path).splitlines())


def is_ancestor(clone, tip):
    r = jc.run(["git", "merge-base", "--is-ancestor", tip, "origin/main"], cwd=clone)
    if r.returncode not in (0, 1):
        raise RuntimeError(f"git merge-base exited {r.returncode}")
    return r.returncode == 0


def pr_label(prs):
    if not prs:
        return "-"
    p = max(prs, key=lambda x: x["number"])
    return f"#{p['number']} {p['state']}"


def pr_verdict(branch, tip, prs):
    """(True|False|None, why) from the PRs whose head is `branch`. None = no PR, look at ancestry."""
    mine = [p for p in prs if p.get("headRefName", branch) == branch]
    for p in mine:
        if p["state"] == "MERGED" and p["headRefOid"] == tip and p.get("baseRefName") == "main":
            return True, f"PR #{p['number']} MERGED into main at the local tip {tip[:7]}"
    for p in mine:
        if p["state"] == "OPEN":
            return False, f"PR #{p['number']} is OPEN"
    for p in mine:
        if p["state"] == "MERGED" and p.get("baseRefName") != "main":
            return False, f"PR #{p['number']} MERGED into {p.get('baseRefName') or '?'}, not main (stacked branch)"
    for p in mine:
        if p["state"] == "MERGED":
            return False, (f"PR #{p['number']} MERGED at {p['headRefOid'][:7]} but the local tip is {tip[:7]} "
                           "(local commits never reached the PR)")
    for p in mine:
        return False, f"PR #{p['number']} is {p['state']} unmerged"
    return None, "no PR"


def proof(clone, branch, tip, prs, gh_error, jy):
    """(removable, why) for a clean branch worktree."""
    ok, why = pr_verdict(branch, tip, prs)
    if ok is not None:
        return ok, why
    if gh_error and jy:
        return False, "gh pr list failed; a JY branch needs the gh check"
    if is_ancestor(clone, tip):
        return True, f"tip {tip[:7]} is an ancestor of origin/main"
    return False, "no merged PR at the local tip and the tip is not in origin/main"


# ---------- new ----------
def cmd_new(r, a):
    m = ID_RE.fullmatch(a.id)
    branch = f"feat/{a.id}-{a.slug}"
    st = {}

    def check_args():
        if not m:
            raise jc.Refused(f"bad id {a.id!r}: want JY- and 3 digits, e.g. JY-010")
        if not SLUG_RE.fullmatch(a.slug):
            raise jc.Refused(f"bad slug {a.slug!r}: want lower-case letters, digits and dashes")
        return f"{a.id}, branch {branch}"

    def find_clone():
        st["clone"] = jc.clone_root()
        st["wt"] = st["clone"].parent / f"wt-{a.id}"
        return f"main clone {st['clone'].name}, worktree {st['wt'].name}"

    def path_free():
        wt = st["wt"]
        if wt.exists() or any(norm(w["path"]) == norm(wt) for w in worktrees(st["clone"])):
            raise jc.Refused(f"{wt.name} already exists")
        return f"{wt.name} is free"

    def branch_not_local():
        if jc.run(["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"], cwd=st["clone"]).returncode == 0:
            raise jc.Refused(f"branch {branch} already exists locally")
        return "not a local branch"

    def branch_not_on_origin():
        out = jc.git("ls-remote", "--heads", "origin", f"refs/heads/{branch}", cwd=st["clone"])
        if out:
            raise jc.Refused(f"branch {branch} already exists on origin")
        return "not on origin"

    def fetch():
        r.change(["git", "fetch", "origin"], cwd=st["clone"])
        return "origin fetched"

    def add():
        r.change(["git", "worktree", "add", str(st["wt"]), "-b", branch, "origin/main"], cwd=st["clone"])
        return f"{st['wt'].name} on {branch} from origin/main"

    port = 9000 + int(m.group(1)) if m else 0

    def env_values():
        dev = st["wt"] / "data" / "dev"
        return {
            "JOEY_ITEM": a.id,
            "HUB_PORT": str(port),
            "SNAPSHOT_DIR": "data/demo-snapshots",
            "MEDIA_DB_PATH": str(dev / "media.db"),
            "MEDIA_BACKUP_DIR": str(dev / "backups"),
            "META_CACHE_DIR": str(dev / "meta-cache"),
        }

    def write_env():
        env = env_values()
        r.write_guard(f"write {st['wt'].name}/.env (HUB_PORT={port}) and create data/dev/")
        try:
            for key in ("MEDIA_BACKUP_DIR", "META_CACHE_DIR"):
                Path(env[key]).mkdir(parents=True, exist_ok=True)
            (st["wt"] / ".env").write_text("".join(f"{k}={v}\n" for k, v in env.items()), encoding="utf-8")
        except OSError as e:
            raise RuntimeError(f"{st['wt'].name} and {branch} WERE created, but writing .env failed ({e}); "
                               "write .env by hand, or remove the worktree and branch") from None
        return f".env written, HUB_PORT={port}"

    def start_line():
        env = env_values()
        parts = [f'Set-Location "{st["wt"]}"', "python -m hub.seed_demo"]
        parts += [f'$env:{k}="{v}"' for k, v in env.items()]
        parts.append(f"python -m uvicorn hub.main:app --port {port}")
        # printed as is (the user needs the real paths); the log gets only the port
        print("Start the dev hub (PowerShell):\n" + "; ".join(parts), flush=True)
        return f"dev hub line printed, port {port}"

    r.step("check id and slug", check_args)
    r.step("find main clone", find_clone)
    r.step("worktree path free", path_free)
    r.step("branch not local", branch_not_local)
    r.step("branch not on origin", branch_not_on_origin)
    r.step("git fetch origin", fetch)
    r.step("git worktree add", add)
    r.step("write .env", write_env)
    r.step("dev hub start line", start_line)


# ---------- remove ----------
def cmd_remove(r, a):
    st = {}

    def find_clone():
        if a.id and not ID_RE.fullmatch(a.id):
            raise jc.Refused(f"bad id {a.id!r}: want JY- and 3 digits, e.g. JY-010")
        st["clone"] = jc.clone_root()
        return f"main clone {st['clone'].name}"

    def find_worktree():
        clone = st["clone"]
        target = Path(a.path) if a.path else clone.parent / f"wt-{a.id}"
        entries = worktrees(clone)
        hit = next((w for w in entries if norm(w["path"]) == norm(target)), None)
        if hit is None:
            raise jc.Refused(f"no worktree at {show(target, clone)}")
        if norm(hit["path"]) == norm(clone) or hit is entries[0]:
            raise jc.Refused("that is the main clone; it is never removed")
        if hit["bare"] or not hit["branch"]:
            raise jc.Refused(f"{show(hit['path'], clone)} has no branch (detached HEAD)")
        if hit["locked"]:
            raise jc.Refused(f"{show(hit['path'], clone)} is locked")
        if hit["prunable"] or not os.path.isdir(hit["path"]):
            raise jc.Refused(f"{show(hit['path'], clone)}: the folder is missing; run git worktree prune")
        st["path"], st["branch"] = hit["path"], hit["branch"]
        st["tip"] = jc.git("rev-parse", f"refs/heads/{hit['branch']}", cwd=clone)
        st["jy"] = bool(a.id) or bool(JY_BRANCH_RE.match(hit["branch"]))
        return f"{show(hit['path'], clone)} on {hit['branch']} at {st['tip'][:7]}"

    def clean():
        n = dirty_count(st["path"])
        if n:
            raise jc.Refused(f"{show(st['path'], st['clone'])} has uncommitted or untracked changes ({n} files)")
        return "no uncommitted or untracked changes"

    def fetch():
        r.change(["git", "fetch", "origin"], cwd=st["clone"])
        return "origin fetched"

    def gh():
        st["prs"], st["gh_error"] = [], None
        try:
            slug = jc.repo_slug(st["clone"])
            st["prs"] = jc.gh_json(["pr", "list", "--repo", slug, "--head", st["branch"], "--state", "all",
                                    "--limit", "50", "--json", PR_FIELDS], cwd=st["clone"])
        except Exception as e:  # noqa: BLE001
            st["gh_error"] = str(e)
            if st["jy"]:
                raise jc.Refused(f"gh pr list failed ({e}); a JY branch needs the gh check") from None
            return "SKIP", f"gh pr list failed ({e}); ancestry only"
        return f"{len(st['prs'])} PR(s) for {st['branch']}: {pr_label(st['prs'])}"

    def merged():
        ok, why = proof(st["clone"], st["branch"], st["tip"], st["prs"], st["gh_error"], st["jy"])
        if not ok:
            raise jc.Refused(why)
        return why

    def not_inside():
        here, there = norm(os.getcwd()), norm(st["path"])
        if here == there or here.startswith(there + os.sep):
            raise jc.Refused("you are inside that worktree: run this from the main clone or another worktree")
        return "run from outside the worktree"

    def remove_wt():
        r.change(["git", "worktree", "remove", st["path"]], cwd=st["clone"])
        return f"{show(st['path'], st['clone'])} removed"

    def delete_branch():
        r.change(["git", "branch", "-D", st["branch"]], cwd=st["clone"])
        return f"{st['branch']} deleted"

    r.step("find main clone", find_clone)
    r.step("find worktree", find_worktree)
    r.step("worktree clean", clean)
    r.step("git fetch origin", fetch)
    r.step("gh pr list", gh)
    r.step("merged proof", merged)
    r.step("not run from inside it", not_inside)
    r.step("git worktree remove", remove_wt)
    r.step("git branch -D", delete_branch)


# ---------- list ----------
def assess(w, main, clone, prs, gh_error):
    """(pr label, removable yes/no (why)) for one worktree."""
    if norm(w["path"]) == norm(main):
        return "-", "no (main clone)"
    if w["bare"] or not w["branch"]:
        return "-", "no (detached HEAD, no branch)"
    mine = [p for p in prs if p["headRefName"] == w["branch"]]
    label = pr_label(mine)
    if w["locked"]:
        return label, "no (locked)"
    if w["prunable"] or not os.path.isdir(w["path"]):
        return label, "no (folder missing: git worktree prune)"
    try:
        if dirty_count(w["path"]):
            return label, "no (uncommitted or untracked changes)"
        ok, why = proof(clone, w["branch"], w["head"], mine, gh_error, bool(JY_BRANCH_RE.match(w["branch"])))
    except Exception as e:  # noqa: BLE001
        return label, f"no ({e})"
    return label, f"{'yes' if ok else 'no'} ({why})"


def cmd_list(r, a):
    st = {}

    def find_clone():
        st["clone"] = jc.clone_root()
        st["entries"] = worktrees(st["clone"])
        return f"main clone {st['clone'].name}, {len(st['entries'])} worktrees"

    def fetch():
        try:
            r.change(["git", "fetch", "origin"], cwd=st["clone"])
        except jc.DryRun:
            raise
        except Exception as e:  # noqa: BLE001 - list is read-only: report and go on
            return "FAIL", f"{e}; ancestry uses origin/main as last fetched"
        return "origin fetched"

    def gh():
        st["prs"], st["gh_error"] = [], None
        try:
            slug = jc.repo_slug(st["clone"])
            st["prs"] = jc.gh_json(["pr", "list", "--repo", slug, "--state", "all", "--limit", str(LIST_LIMIT),
                                    "--json", PR_FIELDS], cwd=st["clone"])
        except Exception as e:  # noqa: BLE001
            st["gh_error"] = str(e)
            return "FAIL", f"gh pr list failed ({e}); JY branches show removable no"
        return f"{len(st['prs'])} PRs in one call"

    def rows():
        clone, entries = st["clone"], st["entries"]
        main = entries[0]["path"] if entries else clone
        with ThreadPoolExecutor(max_workers=8) as pool:
            verdicts = list(pool.map(lambda w: assess(w, main, clone, st["prs"], st["gh_error"]), entries))
        table = [(show(w["path"], clone), w["branch"] or "(detached)", lab, rem)
                 for w, (lab, rem) in zip(entries, verdicts)]
        widths = [max(len(t[i]) for t in table + [("path", "branch", "PR", "")]) for i in range(3)]
        r.log(f"{'path':<{widths[0]}}  {'branch':<{widths[1]}}  {'PR':<{widths[2]}}  removable")
        for t in table:
            r.log(f"{t[0]:<{widths[0]}}  {t[1]:<{widths[1]}}  {t[2]:<{widths[2]}}  removable {t[3]}")
        yes = sum(1 for t in table if t[3].startswith("yes"))
        return f"{len(table)} worktrees, {yes} removable"

    r.step("find main clone", find_clone)
    r.step("git fetch origin", fetch)
    r.step("gh pr list", gh)
    r.step("assess worktrees", rows)


# ---------- entry ----------
def build_parser():
    p = argparse.ArgumentParser(prog="joey.py worktree", description="One worktree per Joey item: new, remove, list.")
    sub = p.add_subparsers(dest="action", required=True)
    n = sub.add_parser("new", help="new worktree + branch from origin/main, with its own .env")
    n.add_argument("id", help="JY-###")
    n.add_argument("slug", help="lower-case words with dashes, e.g. worktree")
    rm = sub.add_parser("remove", help="remove a merged worktree and its branch")
    rm.add_argument("id", nargs="?", help="JY-###")
    rm.add_argument("--path", help="an older non-JY worktree folder")
    sub.add_parser("list", help="every worktree with its PR and a removable verdict")
    for s in (n, rm, sub.choices["list"]):
        s.add_argument("--dry-run", action="store_true", help="print each step and command; change nothing")
    return p


def main(argv):
    p = build_parser()
    a = p.parse_args(argv)
    if a.action == "remove" and bool(a.id) == bool(a.path):
        p.error("remove takes JY-### or --path <worktree>, not both")
    try:
        logs = jc.log_dir(jc.clone_root())
    except Exception:  # noqa: BLE001 - not in a git repo: the first step reports it
        logs = None
    r = jc.Runner(f"worktree {a.action}", dry_run=a.dry_run, log_dir=logs)
    body = {"new": cmd_new, "remove": cmd_remove, "list": cmd_list}[a.action]
    title = " ".join(x for x in ("worktree", a.action, getattr(a, "id", None) or getattr(a, "path", None)) if x)
    return r.execute(title, lambda runner: body(runner, a))
