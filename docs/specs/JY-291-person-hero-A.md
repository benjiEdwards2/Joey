# JY-291 Person page: large portrait hero over a backdrop photo (Option A)

Status: building
Size: S
Live risk: none (no key on the NAS today; the fallback needs no new call)
Area: `hub/media_person.py`, `hub/media_person_photo.py` (new), `hub/templates/media_person.html`, `hub/static/control-surface.css` (person block), `deploy/.env.example`, `deploy/media.env.example`, `docs/setup.md`, `hub/README.md`, `tests/hub/test_person_hero_jy291.py`, `tests/hub/test_media_person.py`
Needs: none
Options page: `JoeyTV/review/JY-291-person/options.md`; B. picked A on 2026-11-04 (hero only)

## Problem
B.: a better photo of the person and a backdrop photo of them. Today the page shows a 160 px round crop (`?h=240`) and no backdrop.

## Build
- Portrait: 2:3, `/img/<profile>?h=600` (TMDB w780). Phone 50 % (max 200 px), 640 px+ 220 px, 1024 px+ 280 px, beside the name/bio.
- Backdrop: full-width `hero-detail-bd` layer (title-hero scrims), `?h=1280`, `?h=600` on a phone.
  - `TMDB_API_KEY` set: TMDB `person/{id}/tagged_images`, highest vote average (then votes, width) with aspect >= 1.5; cached 7 days on disk (failure 10 min). Runs beside the Seerr reads.
  - Unset, none tagged, or failure: backdrop of the most-voted credit in the already-loaded Seerr credits. No credit backdrop: no backdrop layer (portrait on the page background).
- Phone bug: the text column gets `min-width: 0`, the bio `overflow-wrap: anywhere`.
- TV (`tv_mode`): unchanged round crop, no backdrop (JY-193).

## Acceptance criteria
1. Desktop 1440: portrait 280 px beside name/bio, backdrop full width, hero `min(56vh, 640px)`.
2. iPad 1024: same layout, portrait 280 px; no horizontal overflow.
3. Phone 390: portrait stacked above text, bio wraps, no horizontal overflow.
4. TV person page unchanged per JY-193.
5. Without a key no new upstream call; with a key one call per person per 7 days; key never in HTML or logs.
6. Performance: person page warm p95 <= 150 ms.
7. Tests: larger profile size, fallback without key, tagged image with key (mocked HTTP), phone wrap rule, TV unchanged.

## Out of scope
JY-292 (similar people), JY-294 (awards strip).

## Shipped notes
