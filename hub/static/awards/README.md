# Ceremony logo overrides

The Awards pages, poster winner badges and the film / person Awards sections draw each ceremony as a simple
self-drawn mark in `hub/templates/_award_icons.html` (awards-ui, 2026-10-09; currentColor, not the official logos).
To use other artwork for a ceremony, drop an image here named for its id, `.svg`, `.png` or `.webp`. When the file
exists it replaces the drawing everywhere (the ceremony name stays as its alt text). Checked once per process, so
restart the hub after adding one. Joey ships no brand files; this folder is served at `/static/awards/`.

| id | ceremony |
|----|----------|
| `oscars` | Oscars |
| `globes` | Golden Globes |
| `bafta` | BAFTA |
| `critics` | Critics' Choice |
| `sag` | SAG |
| `dga` | DGA |
| `pga` | PGA |
| `wga` | WGA |
| `cannes` | Cannes |
| `emmys` | Emmys |
