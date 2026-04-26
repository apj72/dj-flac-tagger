# Main tab icons

Icons are **SVG masks**: black shapes on transparent background. The UI colours them with `currentColor` via CSS (`mask-image`).

To replace with assets from **TAB_ICON_PROMPTS.md** (e.g. generated PNG):

1. Export with **transparent** background and a **single-colour** glyph (black on transparent is ideal).
2. Overwrite the matching file name, or add `.png` and update `mask-image` URLs in `static/style.css` (search for `tab-icon-`).
