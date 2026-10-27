# JY-257 Player tokens script

Status: building
Size: M
Live risk: secrets
Area: `scripts/player_tokens.py`, `tests/scripts/test_player_tokens.py`, this spec
Needs: none (JY-053's `hub/player_api.py` reads the keys; already on main)
Options page: none: a script with no screen

Live risk sets the review tier (see `docs/PROCESS.md`). `secrets` is reviewed as L.

## Problem
JY-053 Q1 A: each household member plays with their own Jellyfin token, `JELLYFIN_PLAYER_TOKEN_YOU` / `_HER` in the NAS
env. API keys are admin-only, so the token has to come from a real sign-in. JY-054 Q1 A split the script that makes
them into this item. B., 2026-10-27: "1A 2a 3a 4a, ready" (2a = JY-054 Q1 A, a separate small item for the script).

## Acceptance criteria
1. `scripts/player_tokens.py` signs a "Joey player" device (DeviceId `joey-player-you` / `-her`) in with Quick Connect:
   it starts Quick Connect, prints only the six-digit code and where to approve it, and polls every 3 s until approved
   or `--timeout` (default 300 s). On a timeout nothing is written and the Quick Connect secret is dropped.
2. The token's own user (`GET /Users/Me`) must be that member's Jellyfin user, by the hub's rule (`hub.identity`:
   `JELLYFIN_USER` / `_ALIASES` for `you`, `JELLYFIN_USER_HER` for `her`). A wrong user is a FAIL: the token is signed
   out (`POST /Sessions/Logout`) and nothing is written. Only the first letter of the user name is printed.
3. The token goes into the NAS `deploy/.env` with the `append_env.sh` pattern: backup first (`.env.bak-<date>-<HHMMSS>`,
   mode 600), CRs stripped, trailing-newline guard, any old line for the key replaced (one line per key), mode 600.
4. The token is never printed, logged, echoed or put on a command line. Output shows "token set (len N)". By design it
   never reaches Windows: every Jellyfin call runs inside joey-hub, the secret and the token sit in the container's
   `/tmp` (mode 600) and pass from there into the `.env` on the NAS.
5. Idempotent: a valid token for the right user already in `.env` is a SKIP ("already set and valid"), nothing changes,
   unless `--rotate`. A token Jellyfin refuses, or one for the wrong user, is replaced without `--rotate`.
6. `her` is skipped cleanly (SKIP, exit 0) when `JELLYFIN_USER_HER` is unset or not a Jellyfin user.
7. Only joey-hub is recreated (`docker compose up -d --no-deps --force-recreate hub`), once for both members, and only
   when a token changed. Why only it: compose `hub` reads `.env` and only `hub/player_api.py` uses the keys; joey-media
   reads `media.env` only; joey-connectors reads `.env` but never the keys (pinned by a test). After it is healthy the
   script checks the recreated hub holds a valid token for the right user.
8. One Python script, run from Windows over ssh (`joey_common.ssh_run`: `JOEY_NAS`, `JOEY_NAS_KEY`), PASS / FAIL / SKIP
   per step, log at `<main clone>/.joey/logs/joey_<date>.log` with no secrets.
9. Tests with a fake Jellyfin and a fake ssh: happy path, timeout, wrong user, an existing token (and `--rotate`),
   her missing, and no token or secret in the output, the log or any ssh command line.

## Data
NAS `deploy/.env`: `JELLYFIN_PLAYER_TOKEN_YOU`, `JELLYFIN_PLAYER_TOKEN_HER` (already in `deploy/.env.example`).
Container `/tmp/joey_qc_<who>`, `/tmp/joey_pt_<who>`, `/tmp/joey_player_tokens.py` (gone on the recreate).

## Performance budget
None apply: a one-off script. The hub recreate is one container, as a deploy restarts it.

## Options and the pick
No screen. B., 2026-10-27: "1A 2a 3a 4a, ready".

## Out of scope
Turning `PLAYER_API` on; writing the tokens into `media.env` for joey-media (see question 1); any Jellyfin setting.

## How to run it (Claude runs it; B. holds the phone)
Window: 07:00-21:30 Melbourne, NAS on, on the home LAN. From the repo root on Windows:

    python scripts/player_tokens.py

(`--who you` or `--who her` for one member, `--rotate` to replace a valid token, `--timeout 600` for more time.)

B.'s phone steps, once per code the script shows:
1. Open the Jellyfin app, signed in as yourself (for `her`: on her phone, or signed in as her).
2. Settings (the person icon) > Quick Connect.
3. Type the six-digit code the script printed, tap Authorize. Within 5 minutes.

If the script says Quick Connect is off: Jellyfin Dashboard > General > tick "Enable Quick Connect" > Save, then run it
again.

## Accept checklist
- In the PR: the test output.
- The live run (B.'s phone): every row PASS (or SKIP for `her`), "token set (len N)" with no token anywhere on screen,
  `grep -c '^JELLYFIN_PLAYER_TOKEN_YOU=' deploy/.env` on the NAS answers 1, and a second run says "already set and valid".

## Questions for B.
**1. Does the TV session also need the tokens in `media.env`?** JY-057's device checklist says "`PLAYER_API=on` with the
two player tokens on the joey-media front". joey-media never reads `.env`, and JY-057 plays on the media front with the
signed-in member's own session token, so as built these tokens serve the private front (joeyhome.net) only.
A) No: `.env` only, as built. B) Add `--media-env` to also write `deploy/media.env` and recreate joey-media.
*Recommend A, unless the JY-057 session shows the media front needs them.*
Checked 2026-10-27, against `hub/player_api.py` on main and on JY-057's branch: on the media front the hub plays with the
signed-in member's own session token (`ident.jf_token`, `if guest.is_media():`); `TOKEN_ENV` is read only on the
private front. So `media.env` copies would never be read, and they would put household tokens on the friends' container.
Kept to `.env` only.

## Shipped notes
PR, commit, backup name, measured numbers, anything left for a follow-up.
