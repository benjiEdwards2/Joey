# JY-228 Preview slot hardening

Status: spec
Size: S
Live risk: NAS write (the preview slot only; reviewed as L)
Area: `scripts/joey_preview.py`, `deploy/preview/`, `tests/scripts/test_joey_preview.py`, `tests/deploy/test_preview_compose.py`
Needs: JY-012 (shipped)
Options page: none: no screen

Source: the JY-012 Opus verifier's should-fixes (PR #51), 2026-10-23.

## Problem
Three small gaps in the preview slot: a deploy that starts while the preview image builds runs two `docker build`s at once on a 3.7 GB NAS; the preview hub does not pin its front, so a stray `JOEY_FRONT` could turn it into the guest front; and the env allow-list's reason for `JELLYFIN_URL` says every Jellyfin call is refused, which is not true (guest sign-in works without a key).

## Acceptance criteria
1. While `preview up` checks out, builds and starts the slot, it holds the deploy lock (`/tmp/joey-deploy.lock`, the same lock `deploy.sh` takes, with its own pid), so a `deploy.sh` started meanwhile exits 2 ("another deploy is running") and `joey.py close-out` waits. The lock is released on success, on failure and on teardown; a stale lock (dead pid) is never left behind. Tested with the fake ssh.
2. If the lock is already held by a live deploy, `preview up` refuses as today.
3. `deploy/preview/docker-compose.yml` pins `JOEY_FRONT: ""` (the private front) in `environment`; the compose test asserts it.
4. The `JELLYFIN_URL` reason in the allow-list reads accurately (it is in the env; with no key, Jellyfin-backed reads fail visibly and guest sign-in is off because the preview runs the private front).
5. `deploy.sh` is not changed. Live check (orchestrator, inside the window): `preview up main`, a `deploy.sh` attempt during the build exits 2, `preview down`; numbers in the PR.

## Data
None.

## Performance budget
NAS available memory ≥ 1,200 MB (unchanged; one build at a time is the point).

## Options and the pick
None: no screen.

## Out of scope
A preview timer or auto-teardown. Connector previews.

## Accept checklist
- CI green; reviews posted; the live check output in the PR.

## Questions for B.
None.

## Shipped notes
(filled at close-out)
