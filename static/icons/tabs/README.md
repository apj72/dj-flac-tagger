# Main tab icons

PNG **masks** in this folder power the nav tabs (`mask-image` + `background: currentColor` in `static/style.css`).

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

Opaque pixels define the shape; transparent background required. Icons tint with the tab text colour automatically.
