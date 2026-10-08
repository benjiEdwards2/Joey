# Score and site logos (media-ux4, 2026-10-08)

Small self-made monogram marks (not brand artwork) drawn beside the film page's score pills — IMDb 8.0 · RT 90% ·
Metacritic 74 · TMDB 8.1 · Yours 8 — and the IMDb / TMDB / Letterboxd site-link pills. The word always sits beside the
mark. Served at `/static/logos/<id>.svg`.

| id | used for |
|----|----------|
| `imdb` | IMDb score + site link |
| `rt` | Rotten Tomatoes score |
| `mc` | Metacritic score (OMDb) |
| `tmdb` | TMDB / community score + site link |
| `lbxd` | Letterboxd site link |
| `you` | Your rating |

To use official artwork instead, drop `logo-<id>.svg` or `.png` into `hub/static/badges/` (the same override folder the
file badges use); when it exists the page draws it in place of the monogram.
