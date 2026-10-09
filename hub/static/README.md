# static

Everything the hub serves under `/static` (mounted in `hub/main.py`). Every URL carries `?v={{ static_v }}`, a hash of this
whole tree (`hub/shell.py`), so a changed file is never painted from a browser's year-long cache.

| Path | What |
|---|---|
| `control-surface.css` | The one stylesheet (filename is historical; it holds the MediaHub recipes, see `docs/style-guide.md`) |
| `htmx.min.js` | htmx 2.0.4, vendored, no CDN. Licence: BSD (2-clause); the upstream `LICENSE` at https://github.com/bigskysoftware/htmx is authoritative |
| `fonts/` | Geist and Geist Mono, SIL OFL 1.1: `fonts/OFL.txt`, source and version in `fonts/README.md` |
| `svc/` | Server-area service logos; Apache-2.0 from dashboard-icons: `svc/LICENSE-dashboard-icons.txt`, per-file source in `svc/README.md` |
| `logos/`, `awards/`, `badges/` | Joey's own score and site marks; override folders for award and badge art (each has a README) |
| `icon-192.png`, `icon-512.png`, `icon_source.jpg` | PWA and tab icons, generated from the source photo |
| `brand-joey.jpg`, `manifest*.webmanifest` | Top-bar mark; the two web app manifests (Joey, Joey Media) |

Regenerating the icons: from the repo root run `python scripts/make_icons.py` (needs Pillow), then bump the icons' `?v=` in
`hub/templates/base.html` and both manifests. `icon_source.jpg` must stay: it is the generator's input and `tests/hub/test_pwa.py`
asserts it.
