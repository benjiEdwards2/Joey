Adopted 2026-10-06 for all of Joey (DECISIONS.md).
Source: Jack's MediaHub.
Joey implements it in Jinja + `hub/static/control-surface.css` tokens, not Tailwind.
Joey deviations (dated; details in `docs/hub-changelog.md`): Plex → Jellyfin (the "Open in Plex" button reads "Open in Jellyfin"); the page frame is a plain-CSS 72rem column (the guide's `max-w-6xl`) with 16 px side padding at every width, and form columns are 32rem (`.narrow`, `.logform`) where the guide says `max-w-2xl`; media-ux4 (2026-10-08) — the detail hero's coloured IMDb / TMDB /
Letterboxd link chips are neutral logo pills, and every score is one `.scorepill` (logo + name + score; Metacritic tinted
by its band); director / creators are headshot cards ("Directed by"); the Movies / TV lists default to a poster grid with
a Grid / List switch; the Trailer button opens an in-page player. awards-ui (2026-10-09) — brand gold gains one more
meaning, "won an award" (Awards pages, poster winner badges, Won pills), with silver / bronze only on the Most wins podium;
toast/textarea/live-dot recipes not carried (2026-10-09).
2026-10-13 (contrast, U15; phone tap targets and load bar, WP E2): `--text-5` is lightened from zinc-500 to about #82828b (about
5:1 on the page ground, was 4.1:1), inactive phone tab labels and `.btn-mini` sit on `--text-4`, and no text is under
10 px (`.fmt small` was 7.5 px); under 768 px the rating chips are 40 px, `.btn-mini` / section "All" links get a ~40 px hit
area and `.seg` / `.sectabs` links are 36 px; every boosted request shows a 2 px `--primary` load bar (`#loadbar`) after
150 ms; section labels are `h2.seclabel` headings.
2026-10-09 (B., awards-year): the tab label "To Rate" is Title Case on Movies, TV Shows and Diary, and since E3
(2026-10-13) so is the Diary section label under that tab; every other label and body copy stays sentence case.

# MediaHub style guide

The look, feel and writing of MediaHub, a personal films-and-TV app, written
so another AI coding assistant (Claude) can recreate it in a different app.
Apply it as a design system: copy the tokens and recipes as they are, then
build new screens only from them. When something here and a new screen
disagree, follow this file.

Stack it was built on: Next.js (App Router) + React 19, Tailwind CSS v4
(`@import "tailwindcss"` plus `@theme inline`, no config file), lucide-react
icons, the Geist and Geist Mono fonts (via `next/font/google`). Nothing else
draws the UI: no component library, no CSS-in-JS. Every class below is plain
Tailwind v4.

## 1. Principles

1. **One dark theme, chosen on purpose.** Near-black ground (`#09090b`),
   zinc greys, white text. No light mode. `color-scheme: dark`.
2. **The pictures are the colour.** Posters and backdrops carry the page. The
   UI around them is quiet greys; colour is kept for meaning (scores, states,
   the one primary action).
3. **Layers of white, not grey fills.** Surfaces are white at low alpha over
   the ground (`bg-white/[0.03]`, borders `border-white/[0.07]`), so they sit
   right over a backdrop or the plain page alike.
4. **Terse.** One line per state on screen; no explanatory paragraphs in the
   UI (the "why" goes in docs and code comments). See section 9.
5. **Phone first, desktop wide.** Every page works at 390 px with a bottom tab
   bar, and no page ever scrolls sideways. Desktop is one wide column
   (`max-w-6xl`).
6. **Numbers line up.** `tabular-nums` on every number that sits in a column.

## 2. Tokens

### Colours

Neutrals are Tailwind's **zinc** scale. Accents are Tailwind palette colours,
each with one job:

| Role | Value | Used for |
|---|---|---|
| Ground | `#09090b` (`zinc-950`) | `body` background, theme colour |
| Text | `#fafafa` / `zinc-100` | titles; `zinc-200` links; `zinc-300` body; `zinc-400` secondary; `zinc-500` labels/meta; `zinc-600` dim, "—" placeholders |
| Surface | `bg-white/[0.03]`, `border-white/[0.07]` | cards, the stats strip, panels |
| Hover | `bg-white/[0.04]` (rows), `bg-white/5` (buttons) | |
| Divider | `border-white/5`; controls `border-white/10`; hover `border-white/20–25` | |
| Primary action | `indigo-500` (bg), hover `indigo-400` | the one main button; active tab underline `indigo-400`; phone active tab `indigo-300`; ambient glow rgba(99,102,241,…) |
| Brand gold | `#f2c14e` | the logo's dot; a perfect 10's glow (`rgba(251,191,36,…)`) |
| Good / done | `emerald-400` (text), `emerald-300/90` lines | "In library", Complete, scores 9+ |
| Waiting / warning | `amber-400` (`/70–/90`) | "Wanted", counts badge, warnings |
| Watchlist / follow / info | `sky-300/400` | bookmark marks, the followed tick, links chips |
| In progress | `orange-400`, row tint `orange-500/[0.06]`, bar `#f97316` | "Watching" |
| New | `fuchsia-300`, tint `fuchsia-500/[0.06]`, bar `#d946ef` | "New season" |
| Upcoming | `teal-300`; chip `bg-teal-500/85 text-zinc-950` | release dates, "Announced" |
| Favourite / live | `rose-400/80` (heart, filled); `#f43f5e` live dot | |
| Danger | `red-300` on `border-red-500/30`, hover `bg-red-500/10` | destructive buttons |

Score colours (a 1–10 personal scale), exactly:

```ts
export function ratingColor(v: number | null): string {
  if (v == null) return "text-zinc-500";
  if (v >= 9) return "text-emerald-400"; // Superb / All Time Favourite
  if (v >= 8) return "text-green-400"; //   Great
  if (v >= 7) return "text-lime-400"; //    Good
  if (v >= 6) return "text-yellow-400"; //  Fair
  if (v >= 5) return "text-amber-400"; //   Meh
  if (v >= 4) return "text-orange-400"; //  Poor
  if (v >= 3) return "text-red-400"; //     Bad
  if (v >= 2) return "text-red-500"; //     Terrible
  return "text-red-600"; //                 Dreadful
}
// A small bordered score chip: same grade, border at /30 —
// e.g. 9+ "border-emerald-500/30 text-emerald-400"; empty "border-white/10 text-zinc-600".
```

Whole scores show no decimal ("8"), others one ("8.5"); a missing score is
"—" in `zinc-600`. A perfect 10 keeps its green and gains a gold glow (see 7).

### Type

- Font: Geist (sans) for everything; Geist Mono only for file names/paths.
  `-webkit-font-smoothing: antialiased`.
- Scale (Tailwind sizes): `text-[10px]`/`text-[11px]` micro labels and chip
  text · `text-xs` meta lines · `text-[13px]`/`text-sm` body and controls ·
  `text-[15px] font-semibold` a row's title · `text-lg`/`text-xl`/`text-2xl
  font-semibold` numbers · page titles `text-2xl font-semibold` (plain pages),
  `text-3xl md:text-5xl font-bold tracking-tight` (pages with a picture),
  `text-[22px] sm:text-3xl font-bold tracking-tight` (a film/show's title).
- Section label (the small caps over every group) — used everywhere:
  `text-xs font-semibold uppercase tracking-widest text-zinc-500`, written as
  `LABEL · count` ("WATCHED · 1,261").
- Micro label over a value: `text-[10px] uppercase tracking-wide text-zinc-500`.
- Headings get `[text-wrap:balance]`.

### Shape, space, depth

- Radii: `rounded-lg` controls; `rounded-xl` rows and posters in grids;
  `rounded-2xl` cards/panels; `rounded-full` chips, pills, badges; small
  posters `rounded` (4px).
- Spacing rhythm: gaps of 2/3/4 (8–16px); sections `mt-8`, groups
  `space-y-8`; rows `px-2 py-2`.
- Shadows only on posters and floating things: posters `shadow-lg
  shadow-black/40`; hero poster `shadow-2xl shadow-black/70 ring-1
  ring-white/10`; toasts/menus `shadow-xl shadow-black/60`.
- Glass (things over a picture): `border border-white/20 bg-black/30
  backdrop-blur`, hover `bg-black/50`.

## 3. Global CSS (copy as is)

```css
@import "tailwindcss";

:root {
  --background: #09090b;
  --foreground: #fafafa;
}

@theme inline {
  --color-background: var(--background);
  --color-foreground: var(--foreground);
  --font-sans: var(--font-geist-sans);
  --font-mono: var(--font-geist-mono);
}

/* No width jump between short and long pages. */
html { scrollbar-gutter: stable; }
/* Full-bleed headers use 100vw; clip the scrollbar's sliver (clip, not hidden,
   so sticky still works). */
body { overflow-x: clip; }
body {
  background: var(--background);
  color: var(--foreground);
  font-family: var(--font-sans), Arial, Helvetica, sans-serif;
  -webkit-font-smoothing: antialiased;
}
/* Ambient indigo glow, fixed to the window. */
body::before {
  content: "";
  position: fixed;
  inset: 0;
  z-index: -1;
  pointer-events: none;
  background: radial-gradient(55rem 40rem at 50% -10%, rgba(99, 102, 241, 0.1), transparent);
}

/* A perfect 10: a slow gold pulse on the poster, a gold halo on the number. */
@keyframes gold-glow-pulse {
  0%, 100% { box-shadow: 0 0 8px 0 rgba(251,191,36,.4), 0 0 20px 3px rgba(251,191,36,.2); }
  50% { box-shadow: 0 0 16px 3px rgba(251,191,36,.62), 0 0 34px 7px rgba(251,191,36,.34); }
}
.gold-glow { animation: gold-glow-pulse 2.4s ease-in-out infinite; }
@keyframes gold-glow-sm-pulse {
  0%, 100% { box-shadow: 0 0 5px 0 rgba(251,191,36,.45); }
  50% { box-shadow: 0 0 10px 2px rgba(251,191,36,.65); }
}
.gold-glow-sm { animation: gold-glow-sm-pulse 2.4s ease-in-out infinite; }
.gold-text-glow { text-shadow: 0 0 12px rgba(251,191,36,.75); }
@media (prefers-reduced-motion: reduce) {
  .gold-glow { animation: none; box-shadow: 0 0 14px 2px rgba(251,191,36,.5), 0 0 30px 6px rgba(251,191,36,.28); }
  .gold-glow-sm { animation: none; box-shadow: 0 0 8px 1px rgba(251,191,36,.55); }
}

/* Home's hero backdrop drifts slowly; a live stream's dot pulses. */
@keyframes hero-drift {
  from { transform: scale(1.08) translate3d(-1%, 0, 0); }
  to { transform: scale(1.02) translate3d(1%, -1%, 0); }
}
.hero-drift { animation: hero-drift 30s ease-in-out infinite alternate; will-change: transform; }
@keyframes live-dot {
  0% { box-shadow: 0 0 0 0 rgba(244,63,94,.65); }
  70% { box-shadow: 0 0 0 7px rgba(244,63,94,0); }
  100% { box-shadow: 0 0 0 0 rgba(244,63,94,0); }
}
.live-dot { animation: live-dot 1.8s ease-out infinite; }
@media (prefers-reduced-motion: reduce) { .hero-drift, .live-dot { animation: none; } }
```

Viewport: `colorScheme: "dark"`, `themeColor: "#09090b"`, `viewportFit:
"cover"` (the phone tab bar pads itself with `env(safe-area-inset-bottom)`).

## 4. Control recipes (copy as is)

Every button, chip, search box and row comes from these; never hand-roll a
variant.

```ts
export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger" | "glass";
export type ButtonSize = "md" | "sm";

const BUTTON_BASE =
  "inline-flex shrink-0 items-center justify-center gap-1.5 whitespace-nowrap rounded-lg font-medium transition-colors disabled:pointer-events-none disabled:opacity-60";
const BUTTON_VARIANT: Record<ButtonVariant, string> = {
  primary: "bg-indigo-500 text-white hover:bg-indigo-400",
  secondary: "border border-white/10 text-zinc-300 hover:bg-white/5 hover:text-zinc-100",
  ghost: "text-zinc-400 hover:bg-white/5 hover:text-zinc-200",
  danger: "border border-red-500/30 text-red-300 hover:bg-red-500/10",
  // On a picture: a light outline that reads on any backdrop.
  glass: "border border-white/20 bg-black/30 text-zinc-100 backdrop-blur hover:bg-black/50",
};
const BUTTON_SIZE: Record<ButtonSize, string> = {
  md: "h-9 px-3 text-sm",
  sm: "h-8 px-2.5 text-[13px]",
};
/** The icon inside takes h-4 w-4. */
export function buttonClass(variant: ButtonVariant = "secondary", size: ButtonSize = "md") {
  return `${BUTTON_BASE} ${BUTTON_VARIANT[variant]} ${BUTTON_SIZE[size]}`;
}

/** A filter chip: filled white while on. Icon h-3.5 w-3.5. */
export function chipClass(active: boolean) {
  return `inline-flex h-7 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full px-3 text-xs font-medium transition-colors ${
    active
      ? "bg-zinc-100 text-zinc-900"
      : "border border-white/10 text-zinc-400 hover:border-white/20 hover:text-zinc-200"
  }`;
}

/** Text/search box. A search box puts its icon at left-3 and adds pl-9. */
export const inputClass =
  "h-9 w-full rounded-lg border border-white/10 bg-white/[0.03] px-3 text-sm text-zinc-100 placeholder:text-zinc-600 focus:border-white/25 focus:outline-none";
export const textareaClass =
  "w-full rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 text-sm text-zinc-100 placeholder:text-zinc-600 focus:border-white/25 focus:outline-none";
export const labelClass = "mb-1 block text-xs font-medium text-zinc-400";
export const selectClass =
  "h-9 rounded-lg border border-white/10 bg-transparent px-3 text-sm text-zinc-300 focus:border-white/25 focus:outline-none [&>option]:bg-zinc-900 [&>option]:text-zinc-200";

/** "WATCHED · 1,248" over a group. */
export const sectionLabelClass = "text-xs font-semibold uppercase tracking-widest text-zinc-500";

/** Lists have no box round them: rows sit on the page. minmax(0,1fr) stops a
 *  long unbroken title widening the page on a phone. */
export const listBoxClass = "-mx-2 grid grid-cols-[minmax(0,1fr)] gap-0.5";
/** One row of any list: poster, title, numbers on the right. Add a hover
 *  (hover:bg-white/[0.04]) where it's a link. */
export const rowClass = "flex items-center gap-3.5 rounded-xl px-2 py-2 transition-colors md:gap-4";
export const rowPosterClass = "aspect-[2/3] w-11 shrink-0 shadow-md shadow-black/40";
export const rowTitleClass = "truncate text-[15px] font-semibold text-zinc-100";
export const rowScoreClass = "w-10 shrink-0 text-right text-xl font-bold tabular-nums";
```

Toolbar above a list (search · filters · sort · view), wrapping on a phone:

```tsx
<div className="mb-3 flex flex-wrap items-center gap-2">
  <div className="relative min-w-48 max-w-md flex-1">
    <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-500" />
    <input className={`${inputClass} pl-9`} placeholder="Search films, directors, franchises…" />
  </div>
  <button className={`${chipClass(on)} h-9`}>…</button>            {/* a big switch */}
  <button className={`${chipClass(open || picked > 0)} ml-auto h-9`}>Filters</button>
  <select className={selectClass}>…</select>
</div>
```

## 5. Layout

- **Page frame:** `<main className="mx-auto w-full max-w-6xl flex-1 px-4 pb-28
  pt-6 sm:px-6 md:pb-16 md:pt-8">` — one wide column on every page; `pb-28`
  clears the phone's tab bar. Forms keep to a narrower column inside it
  (`max-w-2xl`).
- **Top bar (≥ md):** `border-b border-white/5 bg-zinc-950/80 backdrop-blur
  md:sticky md:top-0 md:z-40`, inner `h-14 max-w-6xl` row: logo + name
  (`text-[15px] font-semibold tracking-tight`), section links as pills
  (`rounded-lg px-3 py-1.5 text-sm`; current `bg-white/[0.07] text-zinc-100`,
  others `text-zinc-400 hover:text-zinc-200`), settings gear at the right.
- **Phone tab bar (< md):** `fixed inset-x-0 bottom-0 z-40 border-t
  border-white/5 bg-zinc-950/95 pb-[env(safe-area-inset-bottom)]
  backdrop-blur`, a 5-column grid; each item icon (`h-5 w-5`) over an
  `text-[11px]` label; current `text-indigo-300`, others `text-zinc-500`.
  Exactly five sections fit; settings lives at the top right instead.
- **Section tabs** (the pages inside a section): pills that scroll sideways on
  a phone, underlined tabs on desktop:

```tsx
<nav className="-mx-4 overflow-x-auto px-4 [scrollbar-width:none] sm:mx-0 sm:px-0 [&::-webkit-scrollbar]:hidden mb-6">
  <div className="flex gap-2 md:gap-1 md:border-b md:border-white/5">
    <Link className={`inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap text-sm transition-colors
      max-md:rounded-full max-md:border max-md:px-3.5 max-md:py-1.5 md:-mb-px md:border-b-2 md:px-3 md:pb-2.5 md:pt-1 ${
      on ? "font-medium text-zinc-100 max-md:border-zinc-100 max-md:bg-zinc-100 max-md:text-zinc-900 md:border-indigo-400"
         : "text-zinc-400 hover:text-zinc-200 max-md:border-white/10 md:border-transparent"}`} />
  </div>
</nav>
```

- **Waiting count** (things needing attention, on tabs and sections): an amber
  pill `inline-flex h-4 min-w-4 items-center justify-center rounded-full
  bg-amber-400 px-1 text-[10px] font-semibold tabular-nums text-zinc-950`.
- **No sideways scrolling, ever.** Wide data is a CSS grid whose columns drop
  out as the screen narrows (what has no column is said in a line under the
  title); a phone gets stacked rows/cards. Only deliberate carousels scroll
  sideways (`snap-x`).

## 6. Signature components

**Page header with a picture** (list pages): a full-bleed backdrop
(`mx-[calc(50%-50vw)]`, tucked under the top bar with `-mt-6 md:-mt-8`), the
section tabs on it, then title/sub/actions at its foot. Gradient so text
reads: phone `linear-gradient(to top, #09090b 0%, rgba(9,9,11,.72) 45%,
rgba(9,9,11,.3) 100%)`; ≥ md `linear-gradient(90deg, rgba(9,9,11,.94) 0%,
rgba(9,9,11,.62) 45%, rgba(9,9,11,.14) 85%), linear-gradient(to top,
#09090b 0%, rgba(9,9,11,.55) 32%, rgba(9,9,11,0) 68%)`. No picture: a faint
indigo radial glow. Height `min-h-[170px] md:min-h-[220px]` (tall:
`230/300`). Title `text-3xl md:text-5xl font-bold tracking-tight text-white`
with `[text-shadow:0_1px_14px_rgba(0,0,0,0.6)]`; sub `text-sm text-zinc-200`;
an optional eyebrow `rounded-md bg-white/10 px-2 py-1 text-[10px]
font-semibold uppercase tracking-widest backdrop-blur`; buttons use the
`glass` variant.

**Detail hero** (one film or show): backdrop across the window, darkened
`linear-gradient(to bottom, rgba(9,9,11,.45), rgba(9,9,11,.55) 35%,
rgba(9,9,11,.9) 78%, #09090b)`; the **poster leads**: 360 px beside the title
on desktop (280 on a tablet), on a phone a large poster centred above a
centred title (`w-[62%] max-w-[260px]`). Under the title: tagline (italic
`text-sm text-zinc-300`), a facts line joined by " · ", credits with small
external-link chips (`rounded px-1.5 py-0.5 text-[11px] font-semibold` —
IMDb `bg-yellow-500/10 text-yellow-500/80`, TMDB `bg-sky-500/10
text-sky-400/80`, Letterboxd `bg-green-500/10 text-green-400/80`), a status
line with an icon (`HardDrive` "In library · 4K · 30.3 GB" in emerald), then
one row of buttons: one white primary ("Open in Plex": `bg-zinc-100
text-zinc-900`) and square icon buttons (`h-9 w-9 rounded-lg border
border-white/10 bg-zinc-950/40 backdrop-blur`; toggled ones tinted, e.g.
watchlist `bg-sky-500/15 text-sky-300`, favourite rose).

**Stats strip** (the numbers about one thing):

```ts
export const statsClass =
  "grid grid-cols-3 items-start gap-x-3 gap-y-3 rounded-2xl border border-white/[0.07] bg-white/[0.03] px-4 py-3 sm:flex sm:flex-wrap sm:gap-x-8 sm:px-5";
export const statNumberClass = "text-2xl font-semibold tabular-nums"; // a score, a rank
export const statWordClass = "text-lg font-semibold";                 // a word, a date
// Each stat: <div class="min-w-0"><div class="truncate text-[10px] uppercase tracking-wide text-zinc-500">LABEL</div>
//            <div class="flex min-h-8 flex-wrap items-center gap-x-2">value</div></div>
```

**Rows** (lists of films/shows): poster (`w-11`, 2:3), title + one meta line
(`mt-0.5 text-xs text-zinc-500`, parts joined by a `text-zinc-600` "·"), the
score big on the right (`rowScoreClass` + `ratingColor`). From a tablet up the
same row is a grid with sortable column headings (uppercase `text-xs
text-zinc-500`, the active one `text-zinc-300` with an arrow); off-screen rows
use `[content-visibility:auto] [contain-intrinsic-size:auto_82px]`, and long
lists render 60 at a time as they scroll.

**Poster grid / cards:** `grid grid-cols-3 gap-x-3 gap-y-5 sm:grid-cols-4
md:grid-cols-5 lg:grid-cols-6`; each card a 2:3 poster (`rounded-lg
shadow-lg shadow-black/40`, lifts on hover `group-hover:-translate-y-1
duration-300`), title under it (`text-xs font-medium text-zinc-200
truncate`), a meta line (`text-[11px] text-zinc-500`: year · state · score at
the right). Actions sit **beside the title, never over the picture** (an ×
`p-1 text-zinc-600 hover:text-zinc-300`). A score badge over a poster, where
needed: `absolute right-1.5 top-1.5 rounded-md bg-zinc-950/85 px-1.5 py-0.5
text-sm font-bold`; a coming-soon tag top-left in teal.

**Summary card** (a group of things, e.g. a franchise): `rounded-2xl border
border-white/10 p-3.5 hover:border-white/25`, its backdrop at `opacity-30`
under `linear-gradient(180deg, rgba(9,9,11,.55), rgba(9,9,11,.95))`, name +
badge, a row of 4 posters, a 1px-high progress bar (`h-1 rounded-full
bg-white/[0.08]` with `bg-indigo-400` fill), "4 of 6 seen · 8.2 average",
"Next: …".

**Badges / state chips:** outline pills `inline-flex items-center gap-1
rounded-full border px-2 py-0.5 text-[10px] font-medium` with an icon
(`h-3 w-3`): Watching `border-orange-700 text-orange-400` (Eye), New season
`border-fuchsia-700 text-fuchsia-300` (Sparkles), Complete
`border-emerald-700 text-emerald-400` (CircleCheck). A row in that state also
gets a faint tint and a 3px coloured inset bar
(`shadow-[inset_3px_0_0_#f97316]`). Status words (Returning / Airing / Ended /
Cancelled) are plain faded text: yellow / blue / emerald / red at `/70–/80`.

**Followed tick:** a `BadgeCheck` `h-3.5 w-3.5 text-sky-400` after a name you
follow. In a narrow cell each name truncates on its own and keeps its tick.

**Filter panel:** a `rounded-2xl border border-white/[0.07] bg-white/[0.02]
p-4` box; sections in a 1/2/3-column grid, each a section label over wrapped
chips (`chipClass`) with counts (`tabular-nums text-zinc-500`); when closed,
the picks show as filled chips with an × and "Clear".

**Confirmations:** never a browser dialog. An inline panel under the button
(`mt-3 rounded-xl border border-white/10 bg-zinc-950/90 p-3 text-sm
backdrop-blur`; destructive `border-red-500/30`), message, optional `text-xs
text-zinc-400` note, then `[Confirm (primary or danger, sm)] [Cancel (ghost,
sm)]`. On a phone it's a sheet above the tab bar.

**Toasts:** bottom-centre, above the phone tab bar
(`bottom-[calc(4.75rem+env(safe-area-inset-bottom))]`, `md:bottom-6`),
`rounded-xl border px-3.5 py-2.5 text-sm shadow-xl shadow-black/60
backdrop-blur bg-zinc-900`: error `border-red-500/30 text-red-200`, warning
`border-amber-500/30 text-amber-100`, info `border-white/10 text-zinc-200`.
Tap to dismiss; they leave by themselves.

**Ranking lists**: By-year rankings removed 2026-10-09 (decision 1).

**Spec sheet** (technical details): one card in three parts divided by
`border-t border-white/[0.06]`: format logos (white, `h-7`, drawn with
`[filter:brightness(0)_invert(1)]`), four numbers (label / big value / small
note), then short label–value lines (`grid-cols-[6.5rem_minmax(0,1fr)]`), and
the raw file name in `font-mono text-[11px] text-zinc-500` at the foot.

**Hover poster zoom:** in dense lists, resting on a small poster for 1 s shows
a larger copy beside it (`position: fixed`, `pointer-events: none`).

## 7. Motion

Sparing and slow. Transitions are `transition-colors` (and
`transition-transform duration-300` for the poster lift). The perfect-10 gold
pulse (2.4 s), the home hero's 30 s drift and the live dot are the only
ambient animations. Everything respects `prefers-reduced-motion`.

## 8. Icons and brand

- lucide-react, stroked; `h-4 w-4` in buttons, `h-3.5 w-3.5` in chips and
  meta lines, `h-5 w-5` in the tab bar.
- The mark: a white play triangle on an indigo (`#4f46e5`) rounded tile with a
  gold (`#f2c14e`) dot top-right, like a projectionist's cue mark:

```svg
<svg viewBox="0 0 64 64"><rect width="64" height="64" rx="15" fill="#4f46e5"/>
<path d="M25 19.5 L46 32 L25 44.5 Z" fill="#fff" stroke="#fff" stroke-width="5" stroke-linejoin="round"/>
<circle cx="47.5" cy="16.5" r="4.5" fill="#f2c14e"/></svg>
```

## 9. Writing on screen

- **One line per state.** "Read 5 h ago · next in 19 h", "Last backup 3 h ago
  · 1.5 MB", "4 of 6 seen · 8.2 average". No paragraphs explaining how
  things work; that goes in docs and code comments.
- **Say the outcome, not the mechanism.** "Wanted — Radarr is looking for it",
  not "monitored: true". A warning is one line and still lets the person act.
- **Join facts with " · "**, never commas or pipes.
- **Sentence case** for buttons and labels ("Add film", "Show as posters");
  section labels are uppercase only through CSS.
- **British/Australian spelling** (favourite, colour, catalogue). Dates
  `en-GB` short: "28 Feb 2026" (no year when it's this year: "3 Sep"); long
  "13 November 2002". Numbers `en-AU` with thousands commas. Lengths "2h 47m".
- **Missing values are "—"** in the dimmest grey, not "N/A" or "Unknown".
- **Empty states** are one sentence in a quiet bordered box: `rounded-xl
  border border-white/5 p-8 text-center text-sm text-zinc-500` — "Nothing on
  the watchlist."
  Joey's punctuation rule (2026-10-09): a state shown as a short phrase has no
  full stop ("Not connected", "Nothing playing", "Unavailable", "No page here");
  a full sentence has one ("Hourly and 7-day forecast arrive with the next refresh.").
  Page titles read "Page · Joey"; every "see everything" link in a section head says "All".
- No amber that never goes away: a permanent, unfixable state is a muted grey
  line; amber means "something to do".
- Every icon-only button has an `aria-label`; toggles use `aria-pressed`.
