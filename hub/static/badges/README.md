# Quality-badge override images

The film page draws quality badges as pills (Dolby-style black pills, DTS and HDR pills, plain pills).
To use official artwork instead, drop an image here named for the badge id, `.svg` or `.png`. When the
file exists the page shows the image in place of the pill (the word stays as the image's alt text).
Joey ships no brand files; this folder is served at `/static/badges/`.

| id | badge |
|----|-------|
| `dolby-vision` | Dolby Vision |
| `dolby-atmos` | Dolby Atmos |
| `dolby-digital-plus` | Dolby Digital Plus |
| `dolby-digital` | Dolby Digital |
| `dolby-truehd` | Dolby TrueHD |
| `dts-hd` | DTS-HD (and DTS-HD MA) |
| `dts` | DTS |
| `hdr10` | HDR10 |
| `hdr10plus` | HDR10+ |
| `hlg` | HLG |

Resolution, codec, container, channels and size badges are always plain pills.
