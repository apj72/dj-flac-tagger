# Main tab icons

Icons are **masks** (SVG or **PNG**): opaque pixels define the shape; transparent areas are see-through. The UI tints them with `currentColor` via CSS `mask-image` + `background: currentColor`.

**Formats with transparency (common):**

| Format | Transparency | Notes |
|--------|----------------|--------|
| **PNG** | Yes (alpha channel) | Best default for raster icons; what `extract.png` uses. |
| **SVG** | Yes (no “background”) | Vector; also supported. |
| **WebP** | Yes (can have alpha) | Supported similarly to PNG in modern browsers. |
| **GIF** | 1-bit only | Poor for smooth icons; avoid for new assets. |
| **JPEG / JPG** | No | Do **not** use for icons that need a clear silhouette on the tab bar. |

To add more tabs from **`design/UI/icons/`**, copy into **`static/icons/tabs/`** and set `mask-image` in `static/style.css` under the matching `.tab-icon-*` rule (see **Extract** → `extract.png`).
