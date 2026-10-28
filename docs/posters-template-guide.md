# Joey posters: refining the template in Canva

For B. This guide covers changing how the Joey posters look (JY-260) with no code change: you design in Canva, export a few files, drop them in one NAS folder, and Joey re-renders every poster on its next pass. The spec is `docs/specs/JY-260-posters.md`.

## What a template is

A template is a folder, the **template kit**:

| File | What it is | Needed? |
|---|---|---|
| `template.json` | Where the text goes, its size, font, colour and shadow, and the scrim settings | Yes |
| `scrim.png` | The dark fade behind the text, exported from Canva | No: without it, Joey draws the fade from the `scrim_band` numbers |
| `frame.png` | Anything drawn on top of everything else, such as a border, a logo or a corner mark | No |
| a font file (`.ttf`, `.otf` or `.woff2`) | The font named in `template.json` | Only for a font other than Geist |
| `guide.png` | The safe-area overlay (below). Joey ignores it | No |

**Layers, bottom to top:** the TMDB poster art (full bleed, cropped to fill) → `scrim.png` → title → sub-line → `frame.png`.

Joey draws the title and the sub-line itself, because the words change per film. Canva supplies everything else.

**Where it lives:** on the NAS at `/volume1/Docker/joey/posters/template/` (File Station: `Docker` → `joey` → `posters` → `template`). If the folder is empty or missing, Joey uses the **starter kit** shipped in the hub, `hub/posters_template/`: layout 2 "Clear" in Geist, with the title at 74 % and the sub-line at 88 %.

## Step by step in Canva

1. **Create the design.** Canva → Create a design → Custom size → **1000 × 1500 px**. Any 2:3 size works, from 600 × 900 to 2000 × 3000, as long as `canvas` in `template.json` matches it.
2. **Add the safe-area guide.** Upload `guide.png` from the starter kit (or from your folder) and place it at full size. It shows:
   - the **title area** (pink): a one-line title sits on the inner pink line at 74 %. Longer titles grow upward from the bottom of the box, which stops 2.5 % above the sub-line, up to the top of the box at 62 %. Side margins are 6 %;
   - the **sub-line box** (yellow): top at 88 %;
   - the **scrim band** (blue): the fade starts at 56 %.

   Put a sample poster image underneath as a stand-in for the TMDB art. Keep any artwork you add out of the pink and yellow boxes unless it is meant to sit behind the text.
3. **Design the scrim** (optional). Add a rectangle over the bottom of the canvas, filled with a gradient from transparent at the top to dark at the bottom. Canva: Elements → Shapes → square, stretch it, then Color → Gradient. Its top edge should sit near the blue line.
4. **Design a frame** (optional): borders, a corner mark, a small "Joey" badge. Keep it out of the title and sub-line boxes.
5. **Export each layer on its own.** Hide everything else first: the stand-in poster, `guide.png`, and any sample text you typed. Then Share → Download → **PNG**, size ×1, tick **Transparent background** (this needs Canva Pro), and download.
   - the scrim on its own → rename it `scrim.png`;
   - the frame on its own → rename it `frame.png`.

   Each PNG must be exactly the canvas size, with a transparent background. Joey refuses anything else and says why.

   **No Canva Pro?** Skip the scrim export. Instead, tune `scrim_band` in `template.json` (below); Joey draws that fade itself.
6. **Do not export the title text.** Type sample titles in Canva only to judge the look, then copy the numbers into `template.json` (next section).

## `template.json`, field by field

```json
{
  "version": 1,
  "name": "anything you like",
  "canvas": [1000, 1500],
  "font": {"family": "Geist", "file": "GeistVF.woff2"},
  "scrim": null,
  "scrim_band": {"top": 0.56, "solid": 1.2, "opacity": 0.9, "colour": "#000000"},
  "frame": null,
  "title": {
    "title_anchor": 0.74, "title_anchor_mode": "bottom", "title_gap": 0.025, "title_top_limit": 0.62,
    "margin_x": 0.06,
    "max_size": 95, "wrap_at": 60, "min_size": 40, "max_lines": 3, "line_height": 1.05,
    "uppercase": true, "tracking": 0.01, "weight": 800, "colour": "#FFFFFF",
    "shadow": {"colour": "#000000", "opacity": 0.8, "blur": 14, "dy": 2}
  },
  "sub": {
    "sub_anchor": 0.88, "size": 50, "weight": 500, "colour": "#FFFFFF", "opacity": 0.82, "tracking": 0.04,
    "shadow": {"colour": "#000000", "opacity": 0.6, "blur": 10, "dy": 2}
  }
}
```

- **Positions are fractions of the height.** `title_anchor: 0.74` puts the top of the title 74 % of the way down; `sub_anchor` does the same for the sub-line. `margin_x: 0.06` keeps 6 % clear on each side, and both lines centre between the margins.
  - To move the text, change these numbers. In Canva, read a box's Y position and divide by the canvas height: Y 1110 ÷ 1500 = 0.74.
- **`title_anchor_mode`** decides which way a title grows.
  - `"bottom"` (the starter): a title starts at `title_anchor`. If its lines would come closer to the sub-line than `title_gap` (2.5 % of the height), the whole block moves up, but never above `title_top_limit`. The title can never touch the sub-line.
  - `"top"`: the block hangs from `title_anchor` and shrinks to fit above the gap.
- **Sizes are pixels on the canvas.** The title's lines always fit between their top limit and the gap above the sub-line.
  - A title starts at `max_size` on one line and shrinks to `wrap_at` if it is too wide.
  - If it still does not fit, it wraps to two balanced lines, and then to three (`max_lines`, up to 3), each time starting from the largest size that fits.
  - The last line count may shrink down to `min_size`, the hard floor.
  - Only a title too long even at the floor is cut with "…". The review page marks it "Title cut short".
  - Joey refuses a kit where `max_lines` lines at `min_size` cannot fit above the sub-line, and says so.
- **`scrim` / `frame`:** a file name in the folder (`"scrim.png"`), or `null` for none. When `scrim` is `null`, `scrim_band` draws the fade:
  - `top`: where it starts, fully transparent;
  - `solid`: where it reaches full strength. A value past 1.0 (the starter uses 1.2) means it never goes flat: it keeps darkening right to the bottom edge, with no solid band;
  - `opacity`: how dark it gets (0 to 1);
  - `colour`: the fade's colour.

  Set `scrim_band` to `null` for no fade at all.
- **Colours** are `#RRGGBB`. `opacity` and the shadow `opacity` run from 0 to 1. `blur` is the shadow softness in pixels, and `dy` moves the shadow down.
- **`tracking`** is letter spacing as a fraction of the font size: 0.04 = 4 %, the same as Canva's letter spacing 40.
- **`weight`** is 100 to 900. It works with variable fonts such as Geist; a static font file ignores it.
- **The sub-line** for a film is its year. For a series, "Seasons 1–5 · 2019–2024" arrives with phase 2; until then a series has no sub-line.

## Changing the font

Joey can use any font you have as a file. Google Fonts are the easy route: they are free, the licence allows this, and Canva has most of them.

1. Choose the font in Canva and note its name, for example "Bebas Neue".
2. Go to fonts.google.com, search for that name, then **Get font** → **Download all**. Unzip it.
3. Copy one `.ttf` file into the template folder, for example `BebasNeue-Regular.ttf`. For a family with weights, pick the variable file (the name contains `[wght]`) and set `weight`, or pick the static weight you want.
4. In `template.json`, set `"font": {"family": "Bebas Neue", "file": "BebasNeue-Regular.ttf"}`.

`family` is the Google Font name, kept for your reference. `file` is what Joey loads. Canva-only fonts (not on Google Fonts) cannot be used, because Canva does not let you download them.

## Previewing before anything is applied

Phase 1 never touches Jellyfin, so every change is a preview. There are two ways to look:

**A. On the laptop, before the NAS** (fastest while iterating). From the Joey repo folder:

```powershell
python -m hub.media_posters_render --template "C:\path\to\your\kit" --title "The Assassination of Jesse James" --sub "2007" --out preview.jpg
python -m hub.media_posters_render --template "C:\path\to\your\kit" --art "C:\path\to\a\poster.jpg" --title "Up" --sub "2009" --out up.jpg
python scripts/posters_samples.py --template "C:\path\to\your\kit" --out "C:\path\to\samples"
```

The first line renders over a grey placeholder. `--art` uses a real poster file. The last line renders 6 test titles (2 short, 2 long, 2 series) plus a contact sheet. A bad kit prints `FAIL Template not used: …` with every problem named.

**B. On the review page.** Copy the files into the NAS template folder. Within the hour, the next pass re-renders every poster with the new kit, up to 30 a pass, newest first. Open **Joey → Media → `/media/posters`** to see each title's current poster beside the new one.
- A row still on the old kit says "Old template".
- A refused kit shows **"Template not used"** at the top with the reasons. The last good posters stay until you fix it.

Nothing is written to Jellyfin from either view. Writing approved posters back is phase 2, and it needs your poster API key.
