# JY-268 Remove the gold glow on 10/10 titles

Status: **review** (2026-10-29). Size: **S**. Area: `hub/templates/_rate.html` and its callers, `hub/static/control-surface.css`, tests.

B., 2026-10-29: "Remove golf glow." [sic] He had asked why American Hostage had a gold glow on the web Continue watching row. It is the perfect-10 glow from the 2026-10-06 media restyle.

## Goal
No gold glow on web or phone for a rating of 10. The score badge (the "10" and its grade colour) stays exactly as it is. TV grids drop the glow in JY-259 phase 3 (PR #267); `tv.css` is not touched here.

## What changed
- `_rate.html`: removed the `glow`, `keyglow`, `rowglow` macros; `score`, `pscore`, the title-page "Yours" pill and the rated stat no longer add `gold-text-glow` at 10.
- All callers (11 templates) stop passing a glow class to `poster(...)`.
- `control-surface.css`: removed `.gold-glow`, `.gold-glow-sm`, `.gold-text-glow`, both pulse keyframes, the reduced-motion overrides, `.poster.gold-glow` and the `--gold-pulse-*`, `--gold-sm-*`, `--gold-text` tokens. `--gold` and `--gold-glow` stay (award frame uses them).

## Tests
Glow assertions flipped to "not present" in the diary, film, library cards, rate, wrapped, film-scores and style-foundation tests. `test_cards_are_whole_links_with_the_score_badge` now pins that a 10/10 poster card has no `gold-glow` and still shows the `poster-score score-9` "10" badge.

## Accept checklist
- [ ] A 10/10 title on Continue watching, Library and the title page shows the green "10" and no gold glow.
