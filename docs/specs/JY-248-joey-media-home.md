# JY-248 Joey Media title goes Home; no Overview pill

Status: shipped 2026-10-25
Size: M
Live risk: none
Area: `hub/media_nav.py`, `hub/templates/base.html` (guest brand only), `hub/static/tv.js` (the B2/B3 Up rule), `hub/static/tv.css` (a "JY-248 nav" block), `hub/static/control-surface.css` (a "JY-248 nav" block, no token change), tests in `tests/hub/`
Needs: none (U2 JY-188 and U6 JY-192 build in parallel; this item keeps its CSS in commented "JY-248 nav" blocks)
Options page: none: a nav removal that follows the existing pattern (the brand already links Home)

## Problem
B., 2026-10-25 in chat: "Can you also remove the overview section, use the Joey Media as a way of going back to the home. Expecially on the TV."

Interpretation (the orchestrator's, stated to B.):
- Remove the "Overview" pill from the friends' media-front section row.
- The "Joey Media" title in the top bar is the link to Home (the friends' home page, `guest_home()`, today's Overview URL `/a/<shelves id>`).
- The home page itself stays. It is the landing page; U9 gives it shelves (B.'s pick 4A).
- On the TV the "Joey Media" title is a real focus stop: Up from the page on Home reaches it; OK goes Home.
- Desktop, iPad and phone: the same nav change, with a visible focus and hover state on the title.

## Acceptance criteria
1. Media front: the section table (`media_nav.sections()`) is Movies, TV shows, Diary, Discover. No "Overview" / `home` entry. Every place drawn from it loses Overview: the top-bar row (`.toplinks`, desktop / iPad / TV), the in-page row (`.sectabs-page`, phone) and the phone tab bar (4 slots).
2. The "Joey Media" brand links to `guest_home()` (unchanged) and carries class `brand-home`. On Home it carries `aria-current="page"` (the "you are here" state the Overview pill gave); elsewhere it does not.
3. On Home no section pill and no sub-tab row is current (there is no Overview section).
4. Desktop / iPad: the brand has a hover state (title colour) and the existing `:focus-visible` ring. Phone: the guest top bar stays at the top (sticky, as the private Media "‹ Joey" bar does), so Home is always one tap away.
5. TV: the brand is a pill-shaped focus stop with the 4 px ring (`.tv-focus` / `:focus-visible`). On Home it shows the same filled state as a current pill.
6. TV, JY-187 rules kept:
   - B2/B3: Up from the page into the top bar lands on `.toplinks a[aria-current]`; when there is none (Home), on the brand.
   - G3: first focus on an empty tab is the current sub-tab (unchanged).
   - Back memory (B1): unchanged; a top-bar focus is never remembered.
   - J8: presses from a Home poster to the sign-out pill: Up (brand) + Right x5 (Movies, TV shows, Diary, Discover, sign-out) = **6**. Not worse than 6 (it was 6 before: Up to the Overview pill + 5 Rights).
7. Household (private front): unchanged. See "Household nav decision".

## Household nav decision
The private Media front draws its section row from the same macro (`_media_tabs.html` `media_bar()`), but from a different table: `media_nav.SECTIONS`, not the guest table `_guest_sections()`. Its brand reads "‹ Joey" and goes to the household hub (`/`), not to Media home, so there the Overview pill is the only top-bar way back to Media home. The change is made in the guest table only; the household nav keeps its Overview pill. `test_private_front_sections_are_unchanged` pins it.

## Device journey (for the grouped TV session)
On the TCL, signed in as a friend:
1. Home (the shelves page), focus on a poster. Up: focus on "Joey Media" (filled, ringed). Right x5: Movies, TV shows, Diary, Discover, sign-out pill (J8 = 6 presses).
2. Movies, focus on a poster. Up: the Movies pill. Left: "Joey Media". OK: Home loads, first focus on the first poster.
3. Up from the page on Movies / TV / Diary / Discover still lands on that section's pill (B2/B3).

## Data
None.

## Performance budget
Hub page render, warm, p95 <= 50 ms: one fewer section in the nav; no new reads.

## Options and the pick
None: B.'s instruction above is the pick (2026-10-25).

## Out of scope
- The Home page's own content and heading (U9, pick 4A). The non-TV Home page head still reads "Overview".
- The household front's nav.

## Test changes (dated)
- 2026-10-25: `tests/hub/test_guest_nav.py`: the guest section ids / labels lose `home` / "Overview"; the in-page row loses "Overview"; the phone tab bar loses `/a/media` (4 slots). Reason: this item removes the Overview section (B., quoted above).
- 2026-10-25: `tests/hub/test_guest_nav.py` `test_branding_title_home_meta_manifest_and_user_chip`: the brand regex reads `class="brand brand-home"` (the new class). Every assertion on it is kept.
- 2026-10-25: `tests/hub/test_tv_mode.py` fake TV pages (`TV_PAGES.shell`): the top bar has no Overview pill, matching the real markup. `test_back_restores...`: Up from the Home page now ends on the brand (was `pill-overview`). `test_up_from_the_page...`: the J8 walk from Home is brand, Movies, TV, Diary, Discover, sign-out (6 presses, as before). `test_the_tv_pages_carry_what_the_jy187_rules_read` also looks for `'.topbar .brand'` in tv.js.

## Accept checklist
- Desktop and iPad, friend signed in: no Overview pill; hover "Joey Media" changes its colour; click it: Home.
- Phone: no Overview tab; scroll Home down, the "Joey Media" bar stays; tap it: Home.
- TV: the device journey above.
- Household front: Media still shows its Overview pill.

## Questions for B.
None.

## Shipped notes
- Closed out with `scripts/joey.py close-out`.
- PR: #163, squash-merged as `42f9dd8` (42f9dd82da3b6fbb369abe2ad8df7ea57eb18fff).
- Deploy: `2026-10-25T02:20:12Z PASS prev=37bac74 new=42f9dd8 suite green, smoke ok tv=current gate=-n1 avail=1617 end=2026-10-25T02:29:16Z dur=544s`
- Accept: in chat: "B., orchestrator session, 2026-10-24: Approve all changes. If I dont need to review any directions of changes, etc. Just close it out and apply the acceptance."
- Follow-ups: none
