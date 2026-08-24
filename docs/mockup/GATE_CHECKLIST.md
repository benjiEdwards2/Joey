# WP0 Mockup Gate Checklist

Walk this against `mockup.html` open on your **phone** (http://<dev-machine-ip>:8080/mockup.html)
and **desktop**. Every line is a yes/no. Sign-off = a dated "Mockup gate passed" line in
`LifeDashboard/DECISIONS.md` with the 8 approved hexes.

## 1. Accent hues — approve each (or name a replacement)

| Area | Emoji | Hex | Seen on tab + tile + swatch table (Desk page) | Yes/No |
|---|---|---|---|---|
| Kitchen | 🍳 | `#5BE08C` | green | |
| Money | 💰 | `#3FD9C0` | teal | |
| Desk | 🖥️ | `#5B9CF6` | blue | |
| Calendar | 📅 | `#A78BFA` | violet | |
| Media | 🎬 | `#FF5CA8` | pink | |
| House | 🏠 | `#FFB454` | amber | |
| Car | 🚗 | `#F87171` | red | |
| Garden | 🌱 | `#22D3EE` | cyan | |

## 2. One yes/no each

| # | Check | Where to look | Yes/No |
|---|---|---|---|
| 1 | **Tile anatomy** reads right: emoji + accent area name, big tabular value, dim sub-line, ownership chip + state badge in the footer | any hub tile | |
| 2 | **Tab-bar collapse**: on the phone the bottom bar shows Hub + Kitchen + Money + Desk + "More"; More opens a sheet with all areas | phone, bottom bar | |
| 3 | **Phone grid density**: cards wrap to 2 columns at phone width, 1 column never feels forced, no horizontal scroll anywhere | phone, hub | |
| 4 | **Three tile states** are distinct at a glance AND in words: `fresh` / `stale 5 h` / `not connected` | Money page, "Tile states" strip | |
| 5 | **Secondary line** on the Money hub tile ("Next bill: …") earns its place — one composed summary, not clutter (D17) | hub, Money tile | |
| 6 | **Calendar weather tile**: weather lives as a normal EMBED tile inside Calendar — confirm you don't miss a hub-level weather pill (D18) | Calendar page | |
| 7 | **Owner switcher**: "You" hides Her-chipped tiles (Physio disappears), "Her" hides yours, shared always stays (Q9 semantics) | hub, top-right | |
| 8 | **Notion LINK tile**: launch button reads as "opens the real app", clearly different from data tiles | Desk page | |
| 9 | **Emoji icons accepted knowingly**: emoji render differently across Windows/Android/iOS — you approve emoji as the v1 icon set anyway | compare phone vs desktop | |

## 3. On sign-off

- The 8 approved hexes (as amended) → dated DECISIONS.md line.
- "Mockup gate passed" + confirmed clone path (Q11) → dated DECISIONS.md line.
- Commit and push. **No other WP starts without that line.**
