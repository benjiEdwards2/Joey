# JY-292 + JY-294 Person page: awards carousel and "you may like" shelf

Status: shipped (#332 9304298, live 1c8b37e 2026-11-07; Sweep 38 Accept)
Size: M
Live risk: none (no write; JY-292 adds cached Seerr reads in a deferred part, never on the page render)
Area: `hub/media_person.py`, `hub/media_awards_pages.py`, `hub/templates/media_person.html`, `hub/templates/_person_like.html`, `hub/static/control-surface.css`, `hub/guest.py` (one allowlist line for the new part route), `tests/hub/`
Needs: none
Options page: `JoeyTV/review/JY-292-294/options.md` (B.'s workspace)

## Problem
JY-294: awards on the person page are a grouped text list; B. wants them shown better, "a carousel of their films and what they won".
JY-292: "if you like them you may like" other actors.

## Options and the pick
B. 2026-11-06 ticked both "push"; the options page recommendations and question defaults apply.
- JY-294 = A: a carousel of the works that carry awards, a gold "N won" / grey "N nom" ribbon on each poster and the
  awards as lines under it; most wins first. Today's grouped list stays, folded under "All awards by ceremony" (Q2 yes).
- JY-292 = C: one shelf "If you like them you may like" of person tiles, each with a one-line reason. First slice:
  data source A, "often cast together" (the reason line names how many titles they share and which). Source B (similar
  by genre and era) is a later slice on the same shelf.
- Q3 default: the TV keeps its person page as is (`html.tv #awards` stays hidden; JY-193 keeps the friends' TV to the
  On server shelf). The you-may-like shelf is not drawn for friends on the TV; an owner on the TV gets it as TV person tiles.
- Q5 default: about 10 extra cached Seerr title reads on a person's first visit, paced. Q6 default: hide when empty.

## Acceptance criteria
### JY-294 (awards carousel)
1. When the person has award rows, the Awards section opens with the "N wins · N nominations" line and a carousel: one
   card per work that has awards (rows with no work title are left to the full list).
2. Each card: the work's poster (the stored `award_entity.poster`, else the poster of the same TMDB title in their
   credits, else the letter fallback), the title, a ribbon "N won" (gold) when any award was won, else "N nom" (neutral);
   then up to 3 lines "Ceremony year · Category" each marked Won / Nominated in words, "+N more" past 3.
3. Order: most wins first, then most nominations, then newest year, then title.
4. A card links to the film / show page when the work matched a TMDB id; plain otherwise.
5. The grouped list (per ceremony, unchanged markup) is folded under a `details` "All awards by ceremony".
6. No awards: no section (as today). TV: `#awards` still hidden (tv.css pin kept).
7. No new upstream call: media.db and the credits the page already read.

### JY-292 (you may like)
8. The person page (web and phone; owner on the TV) carries a deferred part that loads
   `/media/person/{id}/like` after the page draws; the page render itself makes no new upstream call.
9. The part reads the cast of the person's top acting titles (at most 10, by vote count; talk, news and reality shows
   and "Self" roles skipped) through the long meta cache (`md.meta_get`), paced only when a read is not cached.
10. Co-stars from the top 15 billed of each title (not the person) shared on 2+ titles are ranked by titles shared,
    then billing, then name; at most 12 tiles.
11. Each tile: a 2:3 photo (initials without one), the name, and a reason line, e.g. "In 3 films with Ada" over the
    shared titles ("Harbour Lights, Old Film"); it links to that person's page.
12. Nothing found, Seerr unset or down: the part returns nothing and the placeholder goes (Q6: hide).
13. Friends on the TV: no part, no shelf (JY-193). Owner on the TV: TV person tiles (`tvt.person`, `tvt-row-person`).
14. Friends on web / phone can load the part (guest allowlist, GET only).

## Data
Reads only: `media_awards_db.person_awards()` (media.db), the page's `combined_credits` (already read), Seerr
`/api/v1/{movie|tv}/{id}` through `md.meta_get` (6 h, restart-proof) in the deferred part. No table, no migration.

## Performance budget
Page render: unchanged (no new call). Deferred part: 0 calls when cached; at most 10 paced reads when cold.

## Out of scope
Source B (similar by genre and era) and taste data; awards on the TV; a badge row in the hero.

## Accept checklist
Open a well-awarded actor on desktop and phone: carousel cards with ribbons, list folded underneath. Scroll down:
the you-may-like shelf appears after a moment with reasons. Open the same person on the TV: unchanged.

## Questions for B.
None blocking; defaults applied.

## Shipped notes
