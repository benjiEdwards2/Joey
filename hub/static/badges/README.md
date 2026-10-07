# Quality-badge override images

The film page's File panel draws format badges as TEXT (film-quality, 2026-10-07): a bold main word over a
small uppercase sub-label (1080p / FULL HD, H.265 / HEVC, 5.1 / SURROUND). To use official artwork instead,
drop an image here named for the badge id, `.svg` or `.png`. When the file exists the page shows the image in
place of the badge (the word stays as the image's alt text).
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

Every other badge's id is its word slugged: `4k`, `1080p`, `hevc`, `h-264`, `aac`, `5-1`, `7-1`, `stereo`,
`blu-ray`, `web-dl`, `remux`, ...
