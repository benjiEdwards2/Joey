# JY-191 Joey TV shell: Back on sign-in exits, Offline wording for a page error

Status: shipped 2026-10-25
Size: M
Live risk: none
Area: `tv/` (shell: `policy/BackPolicy.kt`, new `policy/OfflinePolicy.kt`, `MainActivity.kt`, `Screens.kt`, `res/layout/screen_offline.xml`, `res/values/strings.xml`, JVM tests, `tv/VERSION`, `tv/NOTES.txt`)
Needs: none
Options page: none: tiny change that follows an existing pattern (the mockup already says Back on sign-in exits; the Offline screen keeps its layout)

Source: `JoeyTV\TV_UI_PLAN.md` row U5; findings B4 / L2 and V2 in `JoeyTV\review\TV_UI_EVALUATION_2026-10-23.md`.

## Problem
B4: after sign-out (`POST /signout` → 303 `/signin`) the WebView history still holds Overview. Back on the sign-in page does `goBack()` → `/a/media` → 303 back to `/signin?next=…` with a **new** Quick Connect code. The code the friend is typing is burnt, and the mockup says Back on sign-in exits the app.

V2: the Offline screen also appears for a plain bad URL or a main-frame error while Joey is up, and its body says "Check that this TV is online", which sends the viewer to the wrong fix.

Back on Overview was re-checked on the TCL (2026-10-23 09:58): it exits. No change there.

## Acceptance criteria
1. `BackPolicy.decide` returns `EXIT` on `/signin` (any query, trailing slash ignored) once the page has not handled Back, with or without WebView history. A native overlay still closes first, and the page is still asked first.
2. Other paths are unchanged: home exits, off-home with history goes back, off-home without history loads home, unknown home without history exits. A path that only starts with `/signin` (e.g. `/signin-help`, `/signinx`) is not treated as sign-in.
3. After a main-frame load error or a main-frame 5xx, the shell shows the Splash ("Connecting…") while it re-probes `/healthz`, then the Offline screen:
   - `/healthz` reachable → page wording: title "Couldn't open this page", body "Joey Media is up, but this page didn't load. Choose Retry to try it again."
   - `/healthz` unreachable → today's wording ("Can't reach Joey Media" / "Check that this TV is online, then try again.").
   The Splash probe failing at launch keeps today's wording. `OfflinePolicy.kind` holds the choice and is JVM-tested.
4. Offline buttons and Back are unchanged: Retry, "Open Jellyfin anyway", Back exits.
5. `tv/VERSION` → `versionName=1.0.2`, a new `versionCode` (2026102501), `minVersionCode` unchanged; `tv/NOTES.txt` describes 1.0.2. `deploy/tv_version.py check` passes.
6. CI (`.github/workflows/tv.yml`: lint, `testSideloadDebugUnitTest`, debug APKs, APK checks) is green on the branch.

## Data
None. No hub, database or snapshot change.

## Performance budget
None of the hub budgets apply (shell-only change). The page-error path adds one `/healthz` probe (5 s timeouts) before the Offline screen.

## Options and the pick
None: B4's fix is the one the evaluation names ("treat `/signin` like home (EXIT)"); V2 is wording.

## Out of scope
- Clearing WebView history on sign-out (the alternative B4 fix).
- L3 (password form below the fold), L4 (two-device cap): hub / policy items.
- What Retry loads after a page error (it re-runs the Splash and reloads the failed URL, as today).
- Publishing 1.0.2: no tag, no release upload, no `release_check.py` publish step, no update push to TVs. That happens in a TV session with B.

## Accept checklist
In the TV session with B., after release 1.0.2 is published:
- [ ] Release 1.0.2 via `scripts/joey.py close-out` + `JoeyTV\scripts\release_check.py`; the TV updates to 1.0.2.
- [ ] `wp_b9_device.py back` cases (a)–(d) PASS (unchanged Back behaviour).
- [ ] New case (f) (to be added to `JoeyTV\scripts\wp_b9_device.py`, which today has (a)–(e)): sign out, then Back on `/signin` exits the app, and reopening shows the same flow without a second code burnt by Back.
- [ ] Optional: open a bad URL with Joey up → the Offline screen says "Couldn't open this page", not "Check that this TV is online".

## Questions for B.
None.

## Shipped notes
- Closed out with `scripts/joey.py close-out`.
- PR: #151, squash-merged as `18c0d86` (18c0d86003662948aff8e5c136bff31add478735).
- Deploy: `2026-10-25T05:20:05Z PASS prev=417ef98 new=18c0d86 suite green, smoke ok tv=published:2026102501 gate=-n2 avail=1898 end=2026-10-25T05:26:09Z dur=364s`
- Accept: in chat: "B., orchestrator session, 2026-10-25: The TV is free now: run the grouped TV session (merge and release JY-191 first, then the 40 checks)."
- Follow-ups: none
