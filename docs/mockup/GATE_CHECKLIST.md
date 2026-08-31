# WP0 Mockup Gate Checklist (v3 — Cockpit × Bento)

Walk this against `mockup.html` open on your **phone** (http://<dev-machine-ip>:8080/mockup.html)
and **desktop**. Every line is a yes/no. Sign-off = a dated "Mockup gate passed" line in
`LifeDashboard/DECISIONS.md` with the 8 approved hexes and the chosen name.

## 1. Accent hues — approve each (or name a replacement)

| Area | Hex | Seen on rail + tile gradient + swatch table (Desk page) | Yes/No |
|---|---|---|---|
| Kitchen | `#5BE08C` | green | |
| Money | `#3FD9C0` | teal | |
| Desk | `#5B9CF6` | blue | |
| Calendar | `#A78BFA` | violet | |
| Media | `#FF5CA8` | pink | |
| House | `#FFB454` | amber | |
| Car | `#F87171` | red | |
| Garden | `#22D3EE` | cyan | |

## 2. One yes/no each

| # | Check | Where to look | Yes/No |
|---|---|---|---|
| 1 | **Cockpit status strip** answers "what's now" in one line: SYS/FEEDS health, stale alerts, NEXT UP, NEXT BILL, holiday T-minus | top of every page | |
| 2 | **Cockpit navigation**: icon rail on the left (desktop); on the phone it becomes the bottom bar with Hub + Kitchen + Money + Desk + "More" (More opens the full sheet) | desktop + phone | |
| 3 | **Weighted bento**: Money is the 2×2 hero, Calendar 2×1, the rest 1×1; Car + Garden fold into one slim "not set up" row. Tiles carry a soft per-area accent gradient | hub | |
| 4 | **Quiet freshness**: healthy tiles carry NO badge, only a faint "12 min ago"; badges appear only for `stale 5 h` / `not connected` | hub House tile vs others; Money page states strip | |
| 5 | **Hub tiles tap through** to their area page | hub → tap Money | |
| 6 | **Money page** leads with aimed-vs-actual per category (bars + words), bills tile follows | Money page | |
| 7 | **Holiday countdown** lives in Calendar as the big 2×2 "47 days until Fiji" tile (placeholder trip), plus a mention on Calendar's hub tile | Calendar page | |
| 8 | **Calendar weather tile**: weather is a normal EMBED tile inside Calendar — confirm you don't miss it on the hub (D18) | Calendar page | |
| 9 | **Owner switcher**: "You" hides Her-chipped tiles (Physio disappears), "Her" hides yours, shared always stays (Q9) | hub, top-right | |
| 10 | **Notion LINK tile**: launch button reads as "opens the real app", clearly different from data tiles | Desk page | |
| 11 | **SVG line icons** approved as the v1 icon set (consistent across Windows/Android/iOS) | rail + tiles, phone vs desktop | |
| 12 | **Phone layout**: bento goes 2-up, Money hero spans full width, no horizontal page scroll (the status strip scrolls within itself by design) | phone | |
| 13 | **Name**: ~~Hearth~~ ~~Jarvis~~ **Joey** — renamed by B. 2026-08-31 with the joeyhome.net purchase | header | ✔ |
| 14 | **TBD sixth module**: parked by B. 2026-08-28 — stays TBD until a later decision | — | ✔ |

## 3. On sign-off

- The 8 approved hexes (as amended) + chosen name → dated DECISIONS.md lines.
- "Mockup gate passed" + confirmed clone path (Q11) → dated DECISIONS.md line.
- Commit and push. **No other WP starts without that line.**

*Note: `shim_375.html` is screenshot tooling (true-375 viewport for goldens), not part of the mockup.*
