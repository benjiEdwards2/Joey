# hub

FastAPI + Jinja/HTMX dashboard shell. Areas are config, not code — see `config/areas.yaml` (WP16).

**Media app frame (2026-10-06).** Every `/media/*` page and the Media shelves page render in
`templates/media_base.html` — no rail; a "← Return to Joey" bar, sections
**Home · Movies · TV Shows · Diary · Server · Discover** with sub-tabs, the You/Her switcher, a
phone bottom bar and amber waiting counts. The section map is one module, `media_nav.py`; Home is
the registry area with `layout: shelves`. Movies/TV "My films / My shows / Tonight" went live in F3 (below).

**Media library pages (F3, 2026-10-06).** `/media/movies`, `/media/movies/tonight`, `/media/tv`, `/media/tv/tonight` and `/media/years?kind=movie|tv`, built from the jellyfin `movies`/`shows` arrays by `media_library.py` (`film_rows`, `show_rows`, `deal_tonight`); "New this week" uses the arr `at` field. Absent arrays render "Library list not available yet".

Media modules: `media_discover.py` (live Jellyseerr search, shelves, title pages, Request),
`media_db.py` (ratings + diary, per owner), `media_backup.py` (nightly `media.db` dump),
`media_write.py` (same-origin write guard). The hub's Media card is the hero (`hub_rank: 1`,
`media_hero()`, `_hub_hero.html`) with a Jellyfin "Jump back in" deep link. A hx-boosted page that
carries a new `joey-asset-v` meta forces a full reload so new CSS is never mixed with old pages.
