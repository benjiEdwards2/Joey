# JY-187 U1 Back memory (focus + scroll)

Status: shipped 2026-10-25
Size: M
Live risk: none
Area: `hub/static/tv.js`, `tests/hub/test_tv_mode.py`
Needs: none
Options page: none: no new screen or visual. Focus rules inside the existing TV focus engine (`tv.js`), following its patterns (rule 2 does not apply).

Source: `Desktop\Claude\JoeyTV\TV_UI_PLAN.md` row U1; findings B1, B2, B3, G3, P5 and journeys J3, J4, J5, J8, J9 in `Desktop\Claude\JoeyTV\review\TV_UI_EVALUATION_2026-10-23.md`. Not blocked by the Gate 1 picks (those block U2 and U6 to U10).

## Problem
On the TV, Back never puts the friend back where they were. `base.html` sets `historyCacheSize 0` + `refreshOnHistoryMiss`, so Back reloads the page and `tv.js` focuses the first poster at scroll 0 (J3, J4 FAIL). Up from the page lands on the brand logo, not the current section pill (J5), so the sign-out pill is 7 presses away (J8). On an empty Watchlist / To rate tab the first focus is "My films", not the open tab (G3). Down from the title buttons lands on the nearest rating chip (8), not chip 1 (P5, J9).

## Acceptance criteria
1. **B1 focus + scroll memory.** For each page URL (path + query) `tv.js` keeps the last focused link inside `<main>` (its `href` and which of the same-`href` links it was) and the scroll offset, in `sessionStorage`. It saves only moves made with a remote key, never a focus in the top bar or in a dialog. A new page in the document (full load and Back's reload, a boosted swap, `pageshow` from the back-forward cache) gets that link focused and the scroll restored; after a boosted swap the scroll is applied again after htmx's own scroll to the top. The shell's hand-off reopen is a reload, so it takes the load path. When the remembered link is not on the page the WP-M first-focus rule applies as before. A WebView focus on the top bar before the first key goes to the remembered link.
2. **B2/B3 Up to the current pill.** Up from anywhere outside the top bar that would land in the top bar lands on `.toplinks a[aria-current]` (the open section), when it is shown.
3. **G3 current sub-tab.** With no Play button and no poster on the page, first focus is the current sub-tab (`.sectabs.sub [aria-current]`), before the first focusable.
4. **P5 chip 1.** Down from the title buttons (`.hero-detail-btns`) that lands in the rating row (`.tv-rate`) lands on its first control (chip 1, or Undo when rated).
5. Tests: each rule is red on the old `tv.js` and green after, in the node fake-DOM harness (skips without node, like the existing one), plus a gate-run test that the rendered TV pages carry the markup the rules read. No existing test is weakened.

## Data
`sessionStorage` key `joeyTV.back` in the TV WebView only: `{url: {h: href, n: index, y: scrollY}}`, at most 40 URLs. Nothing on the server.

## Performance budget
None apply (client-side focus only; no server change).

## Options and the pick
None needed: rules from the plan, no visual choice.

J8 (question 1): **A**, B. 2026-10-24 in chat: "JY-187: accept 6". The sign-out pill stays 6 presses from Overview (2 to 6 elsewhere); no shortcut.

## Out of scope
P6 and X1 (other `tv.js` geometry items in the evaluation), U8 Discover search, the shell (`tv/`), any CSS.

## Accept checklist
Device run by the orchestrator (`JoeyTV\scripts\tv_ui_capture.py journeys`): J3 and J4 PASS (focus and scroll restored after Back), J5 Up lands on the current pill, J8 presses to the sign-out pill (see question 1), J9 Down from the title buttons lands on chip 1.

## Questions for B.
None open (question 1 answered: A, see Options and the pick).

## Shipped notes
- Closed out with `scripts/joey.py close-out`.
- PR: #125, squash-merged as `35c5217` (35c521776ea139697e0957adf2861ebb9a5d67cc).
- Deploy: `2026-10-24T22:40:54Z PASS prev=7a4e1da new=35c5217 suite green, smoke ok tv=current gate=-n2 avail=2027 end=2026-10-24T22:48:36Z dur=462s`
- Accept: in chat: "B., orchestrator session, 2026-10-24: Approve all changes. If I dont need to review any directions of changes, etc. Just close it out and apply the acceptance."
- Follow-ups: none
