# Main tab icons

PNG **masks** here power nav tabs (`mask-image` + `background: currentColor` in `static/style.css`). Source art often has a light plate behind the glyph — run `python3 scripts/strip_tab_icon_plates.py` after copying new PNGs from `design/UI/icons/`.

Some exports **bake in a gray/white checkerboard** (or leave plate pixels around **RGB ~200–220**). The script’s second pass drops those by **luminance** so the mask stays clean. If a glyph looks clipped, lower `--lum-cutoff` slightly (see `scripts/strip_tab_icon_plates.py --help`).

| File | Tab |
|------|-----|
| `extract.png` | Extract |
| `fix-metadata.png` | Fix Metadata |
| `inspect.png` | Inspect |
| `normalise.png` | Normalise |
| `convert.png` | WAV → FLAC (source in `design/UI/icons` may be named `WAV2FLAC.png`) |
| `bulk-fix.png` | Bulk Fix |
| `settings.png` | Settings |

**Updating from design assets:** Copy from `design/UI/icons/`, then resize for the repo (original exports are often huge):

```bash
sips -s format png -Z 256 design/UI/icons/your_icon.png --out static/icons/tabs/name.png
```

Icons must end up with a **transparent** surround and **opaque** glyph (alpha) so the mask reads correctly.
