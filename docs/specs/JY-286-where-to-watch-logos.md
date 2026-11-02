# JY-286 Where to watch: logos only

Status: spec
Size: M (the page data has names only, no logos; see Data)
Live risk: none
Area: `hub/templates/_film_providers.html`, `_tv_title_extras.html`, `media_film.html` (cast / providers placement), `hub/media_film.py` (`_providers`), `hub/static/control-surface.css` (reuse `.prov-logo`), `tests/hub/`
Needs: none
Options page: yes, 2 options at desktop / iPad / phone / TV (placement)

## Problem
B., 2026-11-02: "show the logos below the film or next to the cast about where the film also airs but only by showing the logo. I don't need to see the text of it."
TV: "Similar with the where to watch, etc."

## What the code does today
- `_film_providers.html` draws a "Where to watch" section: web = one chip per name (linked to JustWatch), TV = words only, grouped by label.
- It sits after the cast (`media_film.html` includes cast, then providers; on TV via `_tv_title_extras.html`).
- `media_film.py` `_providers()` keeps only the `name` of each Jellyseerr provider; no logo is kept. The Discover Services shelf (`media_discover.providers`, `_services.html`) already reads `logoPath` and draws `/img/tmdb:...` logos with `.prov-logo` (56 px). Whether the title body's provider entries carry `logoPath` has not been checked here; the builder confirms first.

## Acceptance criteria
1. Each provider shows as a logo only (no visible name) on desktop, phone and TV.
2. Each logo has an accessible name (alt / aria-label = provider name).
3. Placement follows the pick (Options). The old text section is gone, with no empty heading when there are no providers.
4. Web and phone: a logo still links to JustWatch as the chip did. TV: no link (JY-270, no off-site links).
5. Group labels (Stream / Rent / Buy): kept as a small marker or dropped, per Question 2; never colour-only.
6. A provider with no logo falls back to the existing `img_letters` tile (as `_services.html` does), not a broken image.
7. No new upstream call: logos come from the body the page already fetches (the deferred `providers` part); guest pages keep the `href: None` rule in `media_film.py`.
8. Tests: logo markup present, no provider name as visible text, alt text present, no-logo fallback, TV has no link.

## Options (page to build)
- A. Under the film: a row of small logos directly beneath the button row and facts.
- B. Beside the cast: a logo strip at the end of (or above) the Cast row.

## Data
Provider entries: `name`, plus `logoPath` if present (to confirm). Add `logo` (a `tmdb:` ref, same pattern as `media_discover._ref`) to the `_providers()` output. Images through `/img/`. No store change.

## Performance budget
Media item page warm p95 <= 150 ms; the deferred part must not delay first paint. Logos 40-56 px, lazy, `?h=120` like the Services shelf. Measured on the preview.

## Out of scope
Discover > Services shelf. The JustWatch link target. Showing prices or quality.

## Accept checklist
- [ ] Film and show with providers: logos only, the right services, nothing else.
- [ ] Title with no providers: no heading, no gap.
- [ ] TV page shows the logos below or beside the cast as picked.

## Questions for B.
1. Where do the logos go?
   A. Under the film, near the buttons (recommended: seen without scrolling).
   B. Next to the cast.
2. Stream / Rent / Buy: A. show only streaming (recommended), B. show all three with a tiny marker, C. no distinction.

## Shipped notes
