# Joey TV: releasing the Android TV app

Joey TV WP-B8 (2026-10-21). How a change to `tv/` becomes an APK on `https://media.joeyhome.net/app/`, how friends get it,
and how the signing key and the NAS token are looked after. Pipeline in one line:

```
merge tv/ change with a higher versionCode -> Actions builds + signs -> GitHub Release tv-<versionCode>
  -> deploy.sh (tv_publish.py) pulls it into the NAS tv-app dir -> joey-media serves /app -> the app offers it on next launch
```

Parts: `tv/VERSION` + `tv/NOTES.txt` (the inputs), `.github/workflows/tv.yml` (build + `release` job), `deploy/tv_version.py`
(rules, `version.json`, APK secret scan), `deploy/tv_publish.py` (NAS side), `hub/tv_app.py` (the `/app` routes), `tv/README.md`
(the app itself).

**State at 2026-10-22: the release half is live.** WP-B9 created the release keystore (NAS secrets dir + password manager),
set the two GitHub secrets and committed `tv/SIGNING_CERT_SHA256`; 1.0.0 (`2026102201`) is the first signed release.
(Before that, 2026-10-21: dormant until the signing key existed and the two GitHub secrets were set.)
Until then no signed APK, no GitHub Release; each deploy shows `tv=skipped:no-token` or `tv=pending:<code>` (see "History tokens").
Everything marked "UNTESTED" below is proven at WP-B9 (or W5, the first friend install), not before.

Conventions: PowerShell 5.1 (no `&&`, full paths). NAS lines are ssh-wrapped. The merge and the deploy are run by Claude
(JoeyTV project rule 6); the lines are here for when a run is blocked and B. runs it.

## Cut a release

1. **Bump `tv/VERSION`.** Three lines: `versionName` (semver, shown to people), `versionCode`, `minVersionCode`.
   - `versionCode` = the **Australia/Sydney** date you cut it, `YYYYMMDD`, plus a two-digit `nn` (01-99): the second cut on
     21 Oct 2026 is `2026102102`. It must be **higher** than every earlier release. A guard in CI refuses a code dated more than one
     day after the run's UTC date (a typo guard; Sydney is ahead of UTC).
   - `minVersionCode` stays as it is. Raise it to the new `versionCode` **only** on a MAJOR / forced bump: every TV below it is
     then forced to update (no "Later").
2. **Edit `tv/NOTES.txt`** (plain text, at most 500 characters). It is the text on the update prompt and on `/app`.
3. **Every `tv/` change that reaches `main` needs a higher `versionCode`**, even a README or code-comment edit. Merged without one, the
   `release` job fails by design ("release tv-<code> already exists - bump tv/VERSION"), and `main` shows a red run.
   `python deploy/tv_version.py check` checks the file locally; `python -m pytest -q tests/tv/ tests/deploy/test_tv_version.py` checks the rules.
4. **Merge** (a normal merge commit; the PR's own CI run must be green first):
   ```powershell
   gh pr ready <n> -R benjiEdwards2/Joey
   gh pr merge <n> -R benjiEdwards2/Joey --merge
   ```
5. **Watch the Actions run on `main` until the `release` job is green.** The release only exists then.
   ```powershell
   gh run watch $(gh run list -R benjiEdwards2/Joey -w tv.yml -b main -L 1 --json databaseId -q '.[0].databaseId') -R benjiEdwards2/Joey
   ```
   **Verify:** `gh release view tv-<versionCode> -R benjiEdwards2/Joey` lists the APK `joey-media-<versionName>-<versionCode>.apk`
   and `version.json`.
6. **Only then deploy.** A release reaches `/app` only when `deploy.sh` runs **after** the `release` job finished. Run before it, the
   history line says `tv=pending:<code>`; just deploy again later.
   ```powershell
   ssh -i $env:USERPROFILE\.ssh\joey_nas root@192.168.68.59 "/volume1/Docker/joey/life-dashboard/deploy/deploy.sh"
   ```
   (`deploy/push.sh` does the same from the laptop; Claude runs the deploy, B. only if it is blocked.)
   `deploy.sh --force` is not needed: a tree whose SHA is already deployed still runs the TV step (`NOTHING-TO-DEPLOY`).
7. **Verify on the NAS:**
   ```powershell
   ssh -i $env:USERPROFILE\.ssh\joey_nas root@192.168.68.59 "tail -1 /volume1/Docker/joey/life-dashboard/deploy/history.log"
   ```
   The line ends `tv=published:<versionCode>`, and `curl -s https://media.joeyhome.net/app/version.json` shows the same `versionCode`.

**Edge blip:** a deploy force-recreates `joey-swag` only when the deploy changed a file under `deploy/swag/` (PR #9). A TV release
alone does not touch swag, so no stream drops. If the same deploy also carries a `deploy/swag/**` change, follow
[runbook R4](public-edge.md) first (`JfSessions`, no remote stream playing).

## Roll forward, never back

Android refuses to install a lower `versionCode` over a higher one, so a bad release is never "rolled back".

1. Revert the faulty code change in a new PR.
2. In the same PR set a **higher** `versionCode` than the bad release (and a new `NOTES.txt`). Cut it as above.

`tv_publish.py` also refuses a tree whose `versionCode` is below the one already published on the NAS (`tv=FAIL:downgrade`), and the
`release` job refuses a code at or below the highest existing `tv-*` release. To stop friends being offered a bad build before the
fix is ready, there is no switch: ship the fixed higher code quickly. A friend who installed the bad build keeps it until the fix lands.

## First install - ADB

**UNTESTED - proven at WP-B9 / W5.** For B.'s own TV and for friends whose TV can be reached over Wi-Fi debugging. adb lives at
`%LOCALAPPDATA%\Android\platform-tools` (on the user PATH). The release package id is `net.joeyhome.media` (the debug build is
`net.joeyhome.media.debug` and installs next to it; a debug build cannot be updated in place by a release because the signature differs).

```powershell
gh release download tv-<versionCode> -R benjiEdwards2/Joey -p "joey-media-*.apk" -D C:\Users\b.edwards\Desktop\jm
adb pair <tv-address>:<pair-port>
adb connect <tv-address>:<port>
adb install -r C:\Users\b.edwards\Desktop\jm\joey-media-<versionName>-<versionCode>.apk
adb shell am start -n net.joeyhome.media/net.joeyhome.media.MainActivity
```

Full steps (TV developer-options wording, what to say to a friend) are filled in at WP-B9.

## First install - Downloader

**Proven W5, 2026-10-23** (a real install from `/app` with no adb: `originatingPackageName=com.esaba.downloader`, version 1.0.1, then Quick Connect
sign-in). For a friend at their own TV, no computer needed. Needs the `media` compose profile on and at least one published release
(otherwise `/app` says "No build published yet"). Friend-facing steps, in plain words:

1. On the TV open the **Play Store** and install **Downloader** (by AFTVnews). Then open it.
2. If the TV asks whether Downloader may install unknown apps, choose **Allow** (or **Settings**, then switch it on for Downloader).
3. In Downloader's home bar ("Click here to enter a URL, Short Code, or Search Term...") type `media.joeyhome.net/app` exactly, then choose **Go**.
4. Choose **Install** (and **Install** again if asked), then **Open**. Joey Media is now in your apps row.
5. Open **Joey Media** and sign in with **Quick Connect**: a code shows on the TV, you approve it on your phone.

**Some launchers hide the Play Store.** Launchers such as Projectivy show only app icons, so there is no Play Store icon to press. The friend gets to the
store from the TV's **Settings, then Apps** (or by searching for "Downloader" with the remote's voice or search button), and installs Downloader from there.
(Seen on B.'s own TCL TV, 2026-10-23.)

After the first install the app updates itself (see "Updater behaviour").

## Signing key

- **What:** a PKCS12 keystore, RSA 4096, alias `joeytv` (D-P10), created in a throwaway `eclipse-temurin:17-jdk` container on the NAS
  (no local JDK). The committed `tv/app/debug-signing/joeytv-debug.p12` is a public, labelled **debug** key and is not this one.
- **Where it lives:** two copies of the `.p12` plus its password, **never in a repo or in `Desktop\Claude`** (that folder syncs to
  GitHub): B.'s password manager, and the NAS `/volume1/Docker/joey/secrets/` (root-only, `chmod 600`). CI guards that git tracks
  only the debug key.
- **GitHub secrets** (repo `benjiEdwards2/Joey`, names only): `TV_KEYSTORE_B64` (the `.p12`, base64) and
  `TV_KEYSTORE_PASSWORD`. Set through the secrets routine (MASTER_PLAN rule 11): values are never typed into chat or a file in the repo.
  With either one missing the release half stays dormant.
- **`tv/SIGNING_CERT_SHA256`** is the certificate's SHA-256, 64 lowercase hex characters, no colons. It is public and
  **must be committed together with the secrets** (same WP-B9 change): CI checks the keystore's fingerprint against it before
  Gradle, then checks the built APK's signer against it again. A missing file fails the release build.
- **Loss = every friend reinstalls.** Android only installs an update signed by the same key. A new key means a new first install
  on every TV (uninstall, then install; cookies and sign-in are lost). Back up before the first friend gets the app.
- **Restore drill (outline, UNTESTED - run it once at WP-B9 before the key is relied on):**
  1. Get the `.p12` from the password manager, copy it to the NAS secrets dir, and confirm it matches the repo with `keytool -list -v`
     in a throwaway `eclipse-temurin:17-jdk` container: the printed `SHA256:` (colons removed, lowercase) must equal `tv/SIGNING_CERT_SHA256`.
  2. Compare it with the NAS copy (`sha256sum` of both files equal).
  3. Re-set the two GitHub secrets from the restored file (base64 for `TV_KEYSTORE_B64`; `gh secret set TV_KEYSTORE_PASSWORD` prompts for
     the value so it never lands in shell history).
  4. Run `tv.yml` by hand (`workflow_dispatch`) on a branch: the fingerprint step passes.
  5. Delete any temp copy only after step 1's comparison passed.
- **Never rotate casually.** A rotation is a decision (dated DECISIONS line) and a re-install for every friend.

## NAS token renewal

`deploy/tv.env` on the NAS (NAS-only, `chmod 600`, never in git or the Docker build context; template `deploy/tv.env.example`)
holds one key, `GH_TV_TOKEN`: a **fine-grained** GitHub token, resource owner `benjiEdwards2`, repository `life-dashboard` only,
permission **Contents: Read-only**, **1-year expiry**. `tv_publish.py` uses it to read the release and download its two files; it
is never printed and never sent to the storage redirect.

- **When to renew:** `tail -1 deploy/history.log` shows `tv=FAIL:auth` (GitHub answered 401/403), or the calendar reminder for
  the expiry date (set one when the token is made).
- **How:** make a new token with the settings above on GitHub (Settings, Developer settings, Fine-grained tokens), save the
  `GH_TV_TOKEN=<value>` line through the secrets routine (MASTER_PLAN rule 11: a txt outside `Desktop\Claude`, B. copies it to the NAS
  `/tmp` himself, `nas_scripts/append_env.sh`, count-only verify, delete the txt, trailing-newline guard). Replace the old
  `GH_TV_TOKEN` line, do not add a second. Revoke the old token on GitHub.
- **Verify:** the next deploy (or `deploy.sh --force`) shows `tv=current`, `tv=pending:<code>` or `tv=published:<code>`, not `FAIL:auth`.
  No restart is needed: `tv.env` is read fresh on each deploy.

## History tokens

Every deploy's history line ends with `tv=<token>` (`tail -1 deploy/history.log`). The TV step never fails a deploy and never runs
inside a rollback; the token is the only signal.

| Token | Meaning | What to do |
|---|---|---|
| `published:<code>` | The release `tv-<code>` was downloaded, verified and is now served at `/app`. | Nothing. Check `https://media.joeyhome.net/app/version.json` if you want to see it. |
| `current` | The NAS already serves this tree's `versionCode`. | Nothing. This is the normal weekly state ([R4](public-edge.md)). |
| `pending:<code>` | No complete release `tv-<code>` exists yet: the Actions `release` job has not finished (or is still uploading), or this tree's `versionCode` was never released (release half dormant, or `tv/VERSION` bumped without a release run). | Check `gh release view tv-<code> -R benjiEdwards2/Joey` and the `tv.yml` run on `main`. When the release exists, deploy again. A `pending` that lingers after a release means a deploy was missed. |
| `skipped:no-token` | No `deploy/tv.env` (or `GH_TV_TOKEN` empty) on the NAS. | Expected until WP-B9. Then: make `tv.env` (see "NAS token renewal"). |
| `FAIL:auth` | GitHub rejected the token (401/403): expired, revoked or wrong scope. | Renew `GH_TV_TOKEN` (above). |
| `FAIL:downgrade` | The tree's `versionCode` is below the one served. | Never go back: ship a higher `versionCode` ("Roll forward"). |
| `FAIL:version-file` | `tv/VERSION` in the tree is invalid. | Fix it (`python deploy/tv_version.py check`); the gate normally catches this first. |
| `FAIL:network` | GitHub could not be reached from the NAS. | Re-deploy later; check the NAS's internet. |
| `FAIL:github-<http>` / `FAIL:download-<http>` | GitHub answered `<http>` to the release lookup / an asset download (e.g. 5xx, rate limit). | Re-deploy later; if it persists, read the deploy log (`deploy/logs/`). |
| `FAIL:verify-json`, `verify-code`, `verify-url`, `verify-sha256`, `verify-size` | The downloaded files failed a check (bad `version.json`, wrong versionCode or APK name, hash or size mismatch). Nothing was published; the served release is unchanged. | Treat the release as bad: do not hand-edit anything on the NAS. Roll forward with a new, higher `versionCode`. |
| `FAIL:tv-app-dir` | `deploy.sh` could not create or chown `/volume1/Docker/joey/data/tv-app`. | Check the NAS volume and permissions (the dir must be owned by uid 1000). |
| `FAIL:no-status` / `FAIL:<ExceptionName>` | The `tv_publish.py` container printed nothing, or crashed. | Read the deploy log under `deploy/logs/`; tell Claude. |

Until WP-B9 expect `skipped:no-token`, and once `tv.env` exists but no release does, `pending:2026102101`.

## Updater behaviour

The `sideload` flavor only (the `store` flavor has no updater and no install permission). Detail and tests: `tv/README.md`, the JVM
tests in `tv/app/src/test/java/net/joeyhome/media/update/`.

- **When:** on launch, at most once a day (24 h since the last successful check, or if the clock moved backwards), in parallel with the
  page load. A failure is silent. Settings, "Check for update now" skips the throttle.
- **What it reads:** `<UI host>/app/version.json` (5 s timeout). The UI host is the baked public host, or a LAN / adb-reverse override,
  so an override also redirects updates: the `url` field is **relative** (a bare `joey-media-<semver>-<code>.apk` name).
- **Optional vs forced:** only a strictly newer `versionCode` is offered (equal, or an older server after a roll-back, offers nothing).
  Installed code below `min_version` = **forced**: no "Later", Back exits the app. Otherwise the prompt shows the notes with
  Update / Later.
- **Safety:** the APK streams to `cacheDir/updates` with a SHA-256 check against `version.json`; a mismatch deletes the file, shows
  "Update failed - try again later" and never installs. The install goes through a PackageInstaller session; the TV asks the viewer
  to confirm, and to allow installs from this app the first time. The next launch clears `cacheDir/updates`.

## What the NAS and the web serve

`joey-media` mounts `/volume1/Docker/joey/data/tv-app` read-only at `/data/tv-app` (`TV_APP_DIR`). `tv_publish.py` writes the APK first and
`version.json` last, and keeps the newest 3 APKs. Public (no sign-in), **media front only**: `/app` (page), `/app/version.json`
(`no-cache`), `/app/latest.apk` (302 to the versioned APK, `no-store`), `/app/<joey-media-...apk>` (immutable). Everything else under
`/app`, and all of `/app` on the private front, is the ordinary 404. `/app` is reachable only once the `media` profile is on (WP-B5).
Route and header detail: `hub/tv_app.py`, `hub/README.md` "Guest front".
