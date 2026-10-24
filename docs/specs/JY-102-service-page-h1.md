# JY-102 Service page H1 = service name

Status: shipped 2026-10-24
Size: S
Live risk: none
Area: `hub/templates/media_service.html`, `hub/static/control-surface.css` (the `.prov-title` rule only), `tests/hub/test_media_services.py`
Needs: none
Options page: none: follows an existing pattern (the person page already draws its own H1 under a tabs-only band)

## Problem
HITLIST: "Service page H1 = service name. Discover service page says 'Discover'." `/media/discover/service/<id>` took its H1 from the nav ("Discover") and showed the service name as an H2 below it.

## Acceptance criteria
1. The page has exactly one H1, and it is the service name (for example "Netflix"), beside the service logo at the head of the page body.
2. The header band above carries the section tabs only (no "Discover" title), as on the person page.
3. The name keeps the page-title size (24 px, semibold, as a plain `.pagehead h1`), not the old 20 px H2.
4. Shelves, 404 and "Not connected" behaviour are unchanged.
5. Tests: `test_service_page_h1_is_the_service_name` (new; failed on the old code) and `test_service_page_shelves_reuse_discover_cards` (pin changed 2026-10-24 from `<h2 class="prov-title">` to `<h1 class="prov-title">`, per HITLIST JY-102).

## Data
None.

## Performance budget
None affected (template only).

## Options and the pick
None: follows an existing pattern.

## Out of scope
The page `<title>` (already "<service> · Joey"); other pages' H1s.

## Accept checklist
Open a service from Discover > Services: the heading is the service name, once, at the page-title size.

## Questions for B.
None.

## Shipped notes
- Closed out with `scripts/joey.py close-out`.
- PR: #82, squash-merged as `2c7606d` (2c7606dc90483209540c698f82a2e56285122829).
- Deploy: skipped: --deploy no
- Accept: in chat: "B., orchestrator session, 2026-10-24: Approve all changes. If I dont need to review any directions of changes, etc. Just close it out and apply the acceptance."
- Follow-ups: none
