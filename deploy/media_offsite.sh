#!/bin/sh
# Joey TV WP-A6b (2026-10-20) — age-encrypted off-box copy of the newest media.db dump.
#
# Reads ONE file: the newest media-YYYY-MM-DD_HHMM.db.gz in exactly /volume1/Docker/joey/backups/media/
# (written by hub/media_backup.py). Encrypts it to the PUBLIC age key below and pushes the ciphertext to
# the dedicated private repo benjiEdwards2/joey-offsite-backup under media/, keeping the newest 14.
# The age private key lives NAS-only and in B.'s password manager ("Joey media.db offsite key"); this
# script never names it. The only secret it uses is the GitHub deploy key, mounted read-only into a
# throwaway git container. The plaintext dump is mounted read-only into a separate throwaway age
# container; the git container only ever sees ciphertext. Nothing is copied in plaintext.
#
# Runs ON the NAS host as root (BusyBox sh; no age or git binaries on the host, so both run in
# containers). Idempotent: if the newest dump is already in the repo it pushes nothing.
#   sh /volume1/Docker/joey/life-dashboard/deploy/media_offsite.sh            # push
#   sh /volume1/Docker/joey/life-dashboard/deploy/media_offsite.sh --dry-run  # show the upload list only
# Restore: docs/public-edge.md "Restore media.db". Daily schedule: nas_scripts/media_offsite_cron.sh.
set -eu
set -o pipefail
PATH=/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH   # cron's PATH is minimal on ADM
umask 077

SRC=/volume1/Docker/joey/backups/media/
DEPLOY_KEY=/volume1/Docker/joey/secrets/offsite_deploy_key
REPO_SLUG=benjiEdwards2/joey-offsite-backup
REPO_URL="git@github.com:$REPO_SLUG.git"
DEST=media
KEEP=14
AGE_RECIPIENT=age1eca287tm02jhu05j2dn9rka6kx262cdvpfd5mermd875uxrc5sqsq4274p
AGE_IMAGE=alpine:3.24.2
GIT_IMAGE=alpine/git:v2.54.0
WORK_PARENT=/volume1/Docker/joey/offsite-work
# GitHub's published ed25519 host key (api.github.com/meta, 2026-10-20): a changed key fails the push.
GITHUB_HOST_KEY='github.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl'
NAME_RE='^media-[0-9]{4}-[0-9]{2}-[0-9]{2}_[0-9]{4}\.db\.gz$'
AGE_RE='^media-[0-9]{4}-[0-9]{2}-[0-9]{2}_[0-9]{4}\.db\.gz\.age$'

say() { echo "media_offsite: $*"; }
die() { echo "media_offsite: FAIL $*" >&2; exit 1; }

# newest_dump DIR -> the newest dump's file name (names sort chronologically); empty if none
newest_dump() {
    ls -1 "$1" 2>/dev/null | grep -E "$NAME_RE" | sort | tail -n 1 || true
}

# prune_list DIR KEEP -> ciphertext names beyond the newest KEEP, oldest first
prune_list() {
    _all=$(ls -1 "$1" 2>/dev/null | grep -E "$AGE_RE" | sort || true)
    [ -n "$_all" ] || return 0
    _n=$(printf '%s\n' "$_all" | wc -l | tr -d ' ')
    [ "$_n" -gt "$2" ] || return 0
    printf '%s\n' "$_all" | head -n $((_n - $2))
}

# key_shaped DIR -> any file outside .git whose name looks like key material
key_shaped() {
    find "$1" -path "$1/.git" -prune -o -type f -print \
        | grep -E -i '\.p12$|\.pfx$|\.jks$|\.pem$|\.key$|agekey|deploy_key|id_rsa|id_ed25519|id_ecdsa' || true
}

GIT() {
    docker run --rm --dns-opt attempts:3 --dns-opt timeout:2 \
        -v "$DEPLOY_KEY":/key:ro -v "$WORK":/work -w /work \
        -e GIT_SSH_COMMAND='ssh -i /key -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/work/known_hosts -o LogLevel=ERROR' \
        "$GIT_IMAGE" "$@"
}

main() {
    DRY=0
    case "${1:-}" in
        --dry-run) DRY=1 ;;
        "") ;;
        *) echo "usage: media_offsite.sh [--dry-run]" >&2; exit 64 ;;
    esac

    [ -d "$SRC" ] || die "source dir $SRC missing"
    NEWEST=$(newest_dump "$SRC")
    [ -n "$NEWEST" ] || die "no media-*.db.gz in $SRC"
    DUMP=$SRC$NEWEST
    if [ ! -f "$DUMP" ] || [ -L "$DUMP" ]; then die "$DUMP is not a regular file"; fi
    TARGET=$DEST/$NEWEST.age

    if [ "$DRY" = 1 ]; then
        say "dry run, upload list (one file):"
        echo "$DUMP -> $REPO_SLUG:$TARGET"
        exit 0
    fi

    [ "$(id -u)" = 0 ] || die "run as root (docker)"
    [ -f "$DEPLOY_KEY" ] || die "deploy key missing (see docs/public-edge.md)"
    mkdir -p "$WORK_PARENT"
    chmod 700 "$WORK_PARENT"
    WORK=$(mktemp -d "$WORK_PARENT/run.XXXXXX")
    trap 'rm -rf "$WORK"' EXIT
    printf '%s\n' "$GITHUB_HOST_KEY" > "$WORK/known_hosts"

    say "clone $REPO_SLUG (shallow)"
    GIT clone -q --depth 1 "$REPO_URL" /work/repo
    mkdir -p "$WORK/repo/$DEST"

    if [ -e "$WORK/repo/$TARGET" ]; then
        say "already in the repo: $TARGET"
    else
        say "encrypt $NEWEST"
        docker run --rm --dns-opt attempts:3 --dns-opt timeout:2 \
            -v "$DUMP":/in/dump.db.gz:ro -v "$WORK/repo/$DEST":/out \
            "$AGE_IMAGE" sh -c 'apk add -q --no-cache age >/dev/null && age -r "$1" -o "/out/$2" /in/dump.db.gz' \
            sh "$AGE_RECIPIENT" "$NEWEST.age"
        HDR=
        IFS= read -r HDR < "$WORK/repo/$TARGET" || true
        [ "$HDR" = "age-encryption.org/v1" ] || die "ciphertext header check failed; nothing pushed"
    fi

    for OLD in $(prune_list "$WORK/repo/$DEST" "$KEEP"); do
        rm -f "$WORK/repo/$DEST/$OLD"
        say "prune $DEST/$OLD"
    done

    [ -z "$(key_shaped "$WORK/repo")" ] || die "key-shaped file name in the repo tree; nothing pushed"

    GIT -C /work/repo add -A "$DEST"
    if GIT -C /work/repo diff --cached --quiet; then
        say "nothing to push"
        exit 0
    fi
    GIT -C /work/repo -c user.name=joey-nas -c user.email=joey-nas@localhost \
        commit -q -m "media: $NEWEST.age (keep $KEEP)"
    GIT -C /work/repo push -q origin HEAD:refs/heads/main
    COUNT=$(ls -1 "$WORK/repo/$DEST" | grep -E -c "$AGE_RE" || true)
    say "OK pushed $TARGET ($COUNT in $DEST/)"
}

[ "${MEDIA_OFFSITE_LIB:-0}" = 1 ] || main "$@"
