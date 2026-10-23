"""Joey TV WP-A6b (2026-10-20) — deploy/media_offsite.sh, the age-encrypted off-box push of media.db dumps.

The slice guarantee is the point: the script reads ONE file, the newest media-*.db.gz in exactly
/volume1/Docker/joey/backups/media/, encrypts it to a PUBLIC age key and pushes the ciphertext to the
dedicated private repo benjiEdwards2/joey-offsite-backup under media/, keeping the newest 14. The only
secrets path it names is the GitHub deploy key, mounted read-only; the age PRIVATE key is never named.
The NAS runs BusyBox sh, so the shell forms are pinned too. Behaviour tests run the script under the
local `sh`, or another POSIX shell with pipefail where `sh` lacks it (dry run / library mode only — never docker),
and skip where no such shell exists.
"""

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "deploy" / "media_offsite.sh"
SCRIPT = SCRIPT_PATH.read_text(encoding="utf-8")
SRC_LITERAL = "/volume1/Docker/joey/backups/media/"
AGE_PUBLIC_KEY = "age1eca287tm02jhu05j2dn9rka6kx262cdvpfd5mermd875uxrc5sqsq4274p"  # JoeyTV DECISIONS 2026-10-20


def _pipefail_sh():
    """The first local POSIX shell that, like the NAS's BusyBox sh, accepts `set -o pipefail`: `sh` on the laptop
    (Git Bash) and in the gate image (Debian dash >= 0.5.12-7), else BusyBox, else bash in POSIX mode. Ubuntu 24.04's
    dash (the GitHub runner's sh) predates pipefail and rejects the script at line 18 (JY-006, 2026-10-23)."""
    for argv in (["sh"], ["busybox", "sh"], ["bash", "--posix"]):
        exe = shutil.which(argv[0])
        if exe and subprocess.run([exe, *argv[1:], "-c", "set -o pipefail"],
                                  capture_output=True, timeout=30).returncode == 0:
            return [exe, *argv[1:]]
    return None


SH = _pipefail_sh()
needs_sh = pytest.mark.skipif(SH is None, reason="no POSIX sh with pipefail on this host")


def _code_lines():
    """Script lines with comments stripped (comments may explain; code must not reference)."""
    out = []
    for line in SCRIPT.splitlines():
        s = line.strip()
        if s.startswith("#"):
            continue
        out.append(line)
    return "\n".join(out)


CODE = _code_lines()


def _run(args, env_extra=None, script=None, cwd=None):
    env = dict(os.environ)
    env.update(env_extra or {})
    return subprocess.run(
        [*SH, str(script or SCRIPT_PATH), *args],
        capture_output=True, text=True, env=env, cwd=cwd, timeout=60,
    )


def _lib(call, *args):
    """Source the script in library mode (main not run) and call one function."""
    env = dict(os.environ, MEDIA_OFFSITE_LIB="1")
    return subprocess.run(
        [*SH, "-c", '. "$0"; ' + call, str(SCRIPT_PATH), *args],
        capture_output=True, text=True, env=env, timeout=60,
    )


def _touch(p: Path, data: bytes = b"x"):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)


# --- shell safety -------------------------------------------------------------------------------

def test_script_is_busybox_safe_and_strict():
    assert SCRIPT.startswith("#!/bin/sh\n")  # NAS has no bash (parent DECISIONS 2026-08-31)
    assert "\r" not in SCRIPT
    assert "set -eu" in SCRIPT
    assert "set -o pipefail" in SCRIPT
    assert not re.search(r"(^|[\s=(])\$'", CODE, re.M)  # no ANSI-C $'...' quoting
    assert not re.search(r"^\s*source\s", CODE, re.M)  # `.`, not `source`
    for bashism in ("[[", "<<<", "function ", "declare ", "flock", "head -n -", "${!", "echo -e"):
        assert bashism not in CODE, bashism
    assert not re.search(r"\{[A-Za-z0-9_.-]+,[A-Za-z0-9_.-]+\}", CODE)  # no brace expansion


@needs_sh
def test_sh_n_parses():
    r = subprocess.run([*SH, "-n", str(SCRIPT_PATH)], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr


# --- the slice ----------------------------------------------------------------------------------

def test_source_is_the_literal_media_backup_dir_and_nothing_else():
    assigns = re.findall(r"^SRC=(.*)$", SCRIPT, re.M)
    assert assigns == [SRC_LITERAL]  # one literal, no env override, no default-expansion
    assert 'newest_dump "$SRC"' in CODE
    assert '"$DUMP":/in/dump.db.gz:ro' in CODE  # the ONE plaintext input, read-only
    # no other /volume1 data path is read: only SRC, the deploy key and the ciphertext work dir
    vols = sorted(set(re.findall(r"/volume1/[A-Za-z0-9_./-]*", CODE)))
    assert vols == [
        "/volume1/Docker/joey/backups/media/",
        "/volume1/Docker/joey/offsite-work",
        "/volume1/Docker/joey/secrets/offsite_deploy_key",
    ]


def test_only_secret_referenced_is_the_deploy_key_read_only():
    assert SCRIPT.count("/volume1/Docker/joey/secrets") == 1
    assert "DEPLOY_KEY=/volume1/Docker/joey/secrets/offsite_deploy_key\n" in SCRIPT
    assert '-v "$DEPLOY_KEY":/key:ro' in CODE
    assert not re.search(r"-v\s+\S*secrets[^/]*:", CODE)  # never the secrets dir wholesale
    # $DEPLOY_KEY is only existence-checked and mounted — never read, copied or printed
    uses = [ln.strip() for ln in CODE.splitlines() if "$DEPLOY_KEY" in ln]
    assert len(uses) == 2, uses
    assert any(u.startswith('[ -f "$DEPLOY_KEY" ]') for u in uses)


def test_age_private_key_is_never_referenced():
    assert "media-offsite.agekey" not in SCRIPT
    assert ".agekey" not in SCRIPT
    assert "age-keygen" not in SCRIPT
    assert "--decrypt" not in CODE and "age -d" not in CODE and " -i /" not in CODE.replace("ssh -i /key", "")
    rec = re.findall(r"^AGE_RECIPIENT=(\S+)$", SCRIPT, re.M)
    assert rec == [AGE_PUBLIC_KEY]
    assert re.fullmatch(r"age1[0-9a-z]{58}", rec[0])
    assert 'age -r "$1"' in CODE  # encrypt to the recipient only


@needs_sh
def test_fake_tree_upload_list_excludes_secrets(tmp_path):
    media = tmp_path / "backups" / "media"
    _touch(media / "media-2026-10-18_2100.db.gz")
    _touch(media / "media-2026-10-19_2139.db.gz")
    _touch(media / ".media-abc.db.tmp")          # media_backup's in-flight temp file
    _touch(media / "stray.agekey")
    _touch(media / "notes.txt")
    _touch(tmp_path / "secrets" / "x.p12")
    _touch(tmp_path / "secrets" / "media-offsite.agekey")
    _touch(tmp_path / "secrets" / "offsite_deploy_key")
    fake_src = media.as_posix() + "/"
    script = tmp_path / "media_offsite.sh"
    script.write_text(SCRIPT.replace("SRC=" + SRC_LITERAL, "SRC=" + fake_src, 1), encoding="utf-8", newline="\n")

    r = _run(["--dry-run"], script=script)
    assert r.returncode == 0, r.stderr
    uploads = [ln for ln in r.stdout.splitlines() if " -> " in ln]
    assert uploads == [
        f"{fake_src}media-2026-10-19_2139.db.gz -> benjiEdwards2/joey-offsite-backup:media/media-2026-10-19_2139.db.gz.age"
    ]
    for banned in ("secrets", "x.p12", "agekey", "deploy_key", "notes.txt", "2026-10-18", ".tmp"):
        assert banned not in r.stdout + r.stderr, banned


@needs_sh
def test_dry_run_fails_cleanly_without_a_dump(tmp_path):
    media = tmp_path / "backups" / "media"
    _touch(media / "notes.txt")
    script = tmp_path / "media_offsite.sh"
    script.write_text(SCRIPT.replace("SRC=" + SRC_LITERAL, "SRC=" + media.as_posix() + "/", 1),
                      encoding="utf-8", newline="\n")
    r = _run(["--dry-run"], script=script)
    assert r.returncode != 0
    assert "no media-*.db.gz" in r.stderr


@needs_sh
def test_unknown_argument_is_refused():
    r = _run(["--bogus"])
    assert r.returncode == 64
    assert "usage" in r.stderr


def test_dump_name_matches_media_backup():
    """hub/media_backup.py names dumps media-YYYY-MM-DD_HHMM.db.gz; the script must select that shape."""
    hub = (REPO_ROOT / "hub" / "media_backup.py").read_text(encoding="utf-8")
    assert r'NAME_RE = re.compile(r"^media-(\d{4}-\d{2}-\d{2}_\d{4})\.db\.gz$")' in hub
    assert "NAME_RE='^media-[0-9]{4}-[0-9]{2}-[0-9]{2}_[0-9]{4}\\.db\\.gz$'" in SCRIPT


# --- target, retention, transport ----------------------------------------------------------------

def test_target_is_the_dedicated_repo_media_dir_keep_14():
    assert "REPO_SLUG=benjiEdwards2/joey-offsite-backup\n" in SCRIPT
    assert 'REPO_URL="git@github.com:$REPO_SLUG.git"' in SCRIPT
    assert "DEST=media\n" in SCRIPT
    assert "KEEP=14\n" in SCRIPT
    assert "push -q origin HEAD:refs/heads/main" in CODE
    assert "lifedash-offsite" not in SCRIPT  # superseded by the dedicated repo (2026-10-20)


@needs_sh
def test_prune_keeps_the_newest_14(tmp_path):
    d = tmp_path / "media"
    names = [f"media-2026-10-{day:02d}_0700.db.gz.age" for day in range(1, 17)]  # 16 dumps
    for n in names:
        _touch(d / n)
    _touch(d / "README.md")
    r = _lib('prune_list "$1" 14', d.as_posix())
    assert r.returncode == 0, r.stderr
    assert r.stdout.split() == names[:2]  # only the two oldest go; README untouched
    r = _lib('prune_list "$1" 20', d.as_posix())
    assert r.returncode == 0 and r.stdout.strip() == ""


@needs_sh
def test_key_shaped_guard_flags_key_files_but_ignores_git(tmp_path):
    repo = tmp_path / "repo"
    _touch(repo / "media" / "media-2026-10-19_2139.db.gz.age")
    _touch(repo / ".git" / "deploy_key")  # inside .git: not a tracked file, ignored
    r = _lib('key_shaped "$1"', repo.as_posix())
    assert r.returncode == 0 and r.stdout.strip() == ""
    for bad in ("x.p12", "store.jks", "media-offsite.age" + "key", "offsite_deploy_key", "id_ed25519"):
        _touch(repo / "media" / bad)
    r = _lib('key_shaped "$1"', repo.as_posix())
    flagged = r.stdout
    for bad in ("x.p12", "store.jks", "offsite_deploy_key", "id_ed25519"):
        assert bad in flagged, bad
    assert "age" + "key" in flagged


def test_guards_run_before_the_push():
    push = CODE.index("push -q origin")
    assert CODE.index("age-encryption.org/v1") < push   # ciphertext header proven first
    assert CODE.index('key_shaped "$WORK/repo"') < push  # no key-shaped name ever leaves
    assert CODE.index("prune_list") < push


def test_images_are_pinned_not_latest():
    assert "AGE_IMAGE=alpine:3.24.2\n" in SCRIPT
    assert "GIT_IMAGE=alpine/git:v2.54.0\n" in SCRIPT
    assert ":latest" not in SCRIPT
    assert '"$AGE_IMAGE"' in CODE and '"$GIT_IMAGE"' in CODE
    assert "apk add -q --no-cache age" in CODE


def test_git_is_shallow_and_github_host_key_is_pinned():
    assert "clone -q --depth 1" in CODE
    assert "github.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl" in SCRIPT
    ssh = re.search(r"GIT_SSH_COMMAND='([^']*)'", CODE).group(1)
    assert ssh.startswith("ssh -i /key ")
    for opt in ("IdentitiesOnly=yes", "StrictHostKeyChecking=accept-new", "UserKnownHostsFile=/work/known_hosts"):
        assert opt in ssh
    # the git container sees only the read-only key and the ciphertext work dir
    git_fn = CODE[CODE.index("GIT() {"):]
    git_fn = git_fn[:git_fn.index("\n}\n")]
    assert re.findall(r"-v (\S+)", git_fn) == ['"$DEPLOY_KEY":/key:ro', '"$WORK":/work']


def test_output_never_prints_key_material():
    assert "set -x" not in CODE
    assert "ssh -v" not in CODE and " -vv" not in CODE
    for ln in CODE.splitlines():
        if re.search(r"\b(echo|printf|cat|say)\b", ln):
            assert "DEPLOY_KEY" not in ln, ln
            assert "/key" not in ln, ln
