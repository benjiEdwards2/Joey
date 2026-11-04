# JY-319 Remove the separate Health tab

Status: shipped (live 91c73ab 2026-11-04)
Size: S
Live risk: low (owner-only pages)
Area: `hub/media_nav.py`, `hub/media_pages.py` (`/media/apps`), `hub/templates/_live_health.html`, `config/areas.yaml`, tests
Needs: none

## Problem
Health now lives in the Live page's right rail (JY-296/297, PR 315), so the Activity > Health tab duplicates it.
B., 2026-11-04: "REmove it."

## What it builds
- Drop the Health tab and the `/media/apps` nav prefix.
- `GET /media/apps` becomes a 302 to `/media/playing` for the owner; it stays PRIVATE in `hub/guest.py`, so friends still get 404.
- `media_apps.html` deleted (nothing else rendered it). The `media_status` and `uptime_kuma` readers and `server.service_card` stay (the rail uses them).
- The rail gains what only the tab showed: the "LAN" word after Up/Down on LAN-only apps, and the backup size (and the Off note).
- The Media apps hub tile now opens `/media/playing`.

## Acceptance criteria
1. No Health tab in any nav; Activity has Live, History, Library, Downloads, Requests.
2. `GET /media/apps` returns 302 to `/media/playing` for the owner and 404 for a friend.
3. The rail shows every app Up/Down with its note (and "LAN"), and the backup line with age and size.
4. No template left that nothing renders; full test tree passes with the tab's tests moved to the rail.
