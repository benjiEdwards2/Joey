# JoeyV2 — decisions (append-only, dated)

## 2026-10-23 — plan questions answered (B.: "Go with all recommendations")
- Q1 A: JoeyV2 = the same Joey app and repo (`benjiEdwards2/life-dashboard`), run with the MediaHub operating model. No rebuild.
- Q2 A: ideas and accepts come through chat with the orchestrator, plus private Claude artifact pages for options and accept lists. GitHub mobile is not part of the flow.
- Q3 A: merge rules are enforced by `scripts/joey.py close-out` (green CI + review + B.'s accept). No GitHub Pro, no branch protection.
- Q4 A: Claude does every push, merge and deploy. B. adds the allow rules to `Documents\Claude\.claude\settings.local.json` and says "full permission" once in the orchestrator session.
- Q5 A: squash merge only, one commit per item.
- Q6 A: the performance budgets in JOEYV2_PLAN.md §3 are acceptance criteria.
- Q7 A: one `joey-preview` hub on the NAS at `preview.joeyhome.net` (Access-gated, live data read-only, sample data for connector changes).
- Q8 A: Joey TV's remaining work (W6 close, W7 TV sitting) moves into HITLIST as JY items after Phase 3; the W7 sitting stays one hands bundle.
- Q9 A: the orchestrator works while a laptop session is open; no cloud sessions.

## 2026-10-23 — input cadence
- B.: "I am okay with things not being in batches." B.'s input can come at any time. Batched morning/evening pages are optional, not a rule. Still kept: questions grouped per item at the end of its spec, the accept checklist walked in one go, and the deploy window 07:00–21:30 (NAS off 22:00–07:00).
- B. wants the work cut the MediaHub way: small items inside each phase, each one spec, one branch, one PR, one agent, sized, with its review tier. JOEYV2_PLAN.md §4 rewritten as JY-### items.

## 2026-10-23 — Media player phase (B.: "After pilot is fine")
- Joey gets its own media player on every device (web, phone, TV), replacing the hand-off to the Jellyfin app. No rush: it comes after the Pilot, as Phase 5. Steady state becomes Phase 6.
- Phase 3 (Clean slate) runs alongside Phase 2 (Tooling).
- B. wants the TV player options investigated before choosing; he has seen ffmpeg, Jellyfin and ExoPlayer → JY-051.
- B. will buy a computer to raise transcoding performance → JY-049 (requirements + shortlist before he buys) and JY-059 (move Jellyfin transcoding onto it).

## 2026-10-23 — interim hosting (B., after JY-049)
- The laptop stays powered on and running 24/7 for now. A cheap, value-focused PC will take over later (JY-049 budget tier: N150 class, Linux). An internet upgrade waits for the next home; current upload (32.5 Mbps) stays.
- Phone access: B. asked what Remote Control is. Recommended "Remote Control now, runner on the box later". Awaiting B.'s confirmation.
- Remote Control: B. confirmed it, but turning it on failed with "Remote Control is disabled by your organization's policy" (the Interroll org account). **Paused** at B.'s request: this session's switch is off, and the new-session default is back to Off. B. will set Remote Control up on his own desktop later, at a time of his choosing.
- B. needs to see everything on GitHub: the full JoeyV2 upload and recent edits. → JY-008 moves the JoeyV2 plan, decisions and research into the repo (`docs/joeyv2/`). JY-002 and JY-004 (HITLIST) are pulled forward. From then on, the repo copy is the one that gets edited.

## 2026-10-23 — Joey TV UI round added (B.: "add this into the joeyv2 addition … as a listed item to complete")
- JY-042 added to JOEYV2_PLAN.md Phase 5: the Joey TV UI round (TV_UI_PLAN.md U1–U11, incl. the row + card scale change from `JoeyTV\mockups\tv-v2\08-density.html`). JY-004's seed sources now name TV_UI_PLAN.md, so each U-item gets its own JY-1xx row. Blocked on B.'s Gate 1 picks (scale B/C + picks 1–6). Source session: "Joey TV — TV UI review".

## 2026-10-24 — JY-050 media player answers (B.: "Approve all changes. If I dont need to review any directions of changes, etc. Just close it out and apply the acceptance.")
- All recommended answers in `docs/specs/JY-050-player-spec.md`: devices PC browser → phone → household TCL TV (Joey TV shell); household only, friends after JY-057; direct play → remux → transcode, 20 Mbps remote cap for friend accounts; no offline downloads in v1; subtitle/audio defaults follow each Jellyfin user; Jellyfin is the single resume record (JY-055); TV shell gets a new signed release after JY-042 with the Jellyfin app kept one release as fallback; success = start within 5 s LAN / 10 s remote, cross-device resume, a week without the Jellyfin app.

