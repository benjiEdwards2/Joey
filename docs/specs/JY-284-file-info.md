# JY-284 File information: a File chip in the hero (owner only) + a TV Files row

Status: building (B. 2026-11-06 picker: PUSH; rec B on defaults)
Size: M (S web chip, S TV row, S TV gate)
Live risk: none (templates, CSS and one page-data key; no store change, no new upstream call)
Area: `hub/templates/_title_file.html`, `hub/templates/media_film.html` (hero row; drawer calls removed), `hub/templates/_tv_title_extras.html` (Files row), `hub/media_film.py` (`tv_file_owner`, `tv_file_row`, `film.tv_file`), `hub/static/control-surface.css` (popover; `.filedrawer` rules removed), `hub/static/tv.css` (Files row), `tests/hub/`
Needs: stacked on PR #331 (JY-286, `jy-286-provider-logos`)
Options page: `JoeyTV/review/JY-284/options.md` (A drawer / B hero chip / C Files page); B. picked PUSH on the recommendation, all question defaults

## Problem
B., 2026-11-02: "Create a few different scenarios for where the file information could be found."; "maybe only those who want to find it could or only I can access similar features."; TV: "Repeat the scores and file choices similar to the movies section."

## Decision (the options page's defaults)
1. Who: owner only. No opt-in switch for friends.
2. Web: B, a "File" chip in the hero beside Rate; the closed drawer under the content goes away (one place).
3. TV: a Files row under Scores, shown only when B. is the signed-in person.
4. TV row content: badges, size, sound, subtitles. No file name, no release group.
5. Show and season pages: the same chip, the By episode list inside.

## Change
- Web (desktop, iPad, phone): `tf.chip(fp)` draws `<details class="tl-pop tl-file" id="file">` after the Rate popover (and before "…"), its summary a glass button "File", its popin the existing `tf.panel(fp)` (badges, Size / Bitrate / Picture / Added, Audio / Subtitles / Release, the file name; a show or season: By episode). Same pattern as Rate (`tl-pop` / `tl-popin`, id anchor). Film, show, season and episode pages (the episode page had the drawer too, so it moves with the rest). The `drawer(fp)` macro and its three call sites and `.filedrawer` CSS are removed.
- Popover CSS: `display: block`, `width: min(440px, 100vw - 32px)`, `max-height: min(70vh, 560px)` and `overflow-y: auto`, so a long episode list scrolls inside it; the panel loses its own border.
- TV: `_tv_title_extras.html` draws `<section class="sec tv-extras tv-files" aria-label="Files">` right after the Scores section: the `_file_strip.html` badges, then one line "Size · Sound · Subtitles" (microlabel + value). Film, show, season and episode title screens.
- Gate (server side, never CSS):
  - Web: unchanged, `media_film.file_owner(owner)` = "you" on the private front; anyone else gets `film.file = None`, so no chip.
  - TV: new `media_film.tv_file_owner(owner, request)` = owner "you" (the media front's signed-in identity, `shell.resolve_owner_view` → `media_db.owner_of`) and `media_front.tv_mode(request)`. Only then is `film.tv_file = tv_file_row(film.file)` set; otherwise it is None and the template draws nothing. `tv_file_row` copies the badges, the Size value and the Audio / Subtitles rows only, so the file name and the Release row never reach the TV's HTML.

## Platforms
Desktop, iPad, phone (web chip, private front); TV (Files row, media front, B.'s session).

## Acceptance criteria
1. Owner, private front: film, show, season and episode pages show a closed "File" chip in the hero after Rate; it opens the same File panel as the old drawer (a show / season: By episode). No drawer, no `filedrawer`, one `filepanel` on the page.
2. Her view (`owner_view=her`): no chip, no panel, no file text on film, show and episode pages.
3. Guest front, a friend, web and TV user agent: no chip, no Files row, no file name, size or release group.
4. Guest front, B. ("you") on the web (not TV mode): no chip, no Files row (the web chip stays private-front only).
5. B.'s TV session: a Files row after Scores on the film and show title screens, with badges, Size, Sound and Subtitles; the page has no file name, no "Release", no release group, no Bitrate, and no web chip or drawer.
6. tv.css: the new row's rules are pinned; every font size in the block is at least 18 design px; no `:hover`.
7. Web CSS: the popover scrolls a long list; no fixed width over 360 px outside media queries (the style test holds).
8. Tests: `tests/hub/test_file_chip_jy284.py` (gate units, episode chip, her view, friend web + TV, B. on the media-front web, B.'s TV row, CSS pins); the JY-280 / JY-281 / JY-317 drawer tests re-pointed to the chip.

## Data
No new upstream call and no store change: the TV row is built from the same `file_panel` output the page already computes (Jellyfin item / file summary, read server side). One new page-data key, `film.tv_file`.

## Out of scope
- An opt-in switch for friends (Q1 default: owner only).
- A full Files page (option C); revisit if episode lists get long.
- Episode-level rows on the TV Files row (the show total is shown).
