# HTML user guide (modular)

Professional, **static** documentation for DJ MetaManager. Open **`index.html`** in a browser (file or HTTP). All chapters live alongside **`assets/guide.css`** (shared layout) and **`assets/images/`** (your screenshots).

## Files

| File | Purpose |
|------|---------|
| `index.html` | Overview, audience, modular editing instructions |
| `install-and-setup.html` | Requirements, install, start/stop, Settings intro |
| `workflow-extract.html` | Extract / recording / Platinum Notes |
| `workflow-fix-and-inspect.html` | Fix Metadata + Inspect |
| `workflow-normalise.html` | Loudness normalisation |
| `workflow-wav-to-flac.html` | Single + bulk WAV conversion, handoff |
| `workflow-bulk-fix.html` | Batch metadata |
| `reference-config-and-formats.html` | Filename rules, formats, API sketch, UI state (incl. preview: `stream-audio`, `retag-artwork`) |
| `partials/nav.inc.html` | **Copy-paste** nav snippet when adding pages |
| `assets/guide.css` | Shared typography and components |
| `assets/images/README.md` | **Screenshot checklist** (filenames and what to capture) |

## Adding a chapter

1. Copy an existing chapter HTML file.
2. Update `<title>`, `<h1>`, and body content.
3. Paste the nav from `partials/nav.inc.html` into **every** chapter’s `.guide-nav` and set `aria-current="page"` on the new link only.
4. Add a card on `index.html` in `.toc-grid` if the chapter is top-level.

## Screenshots

See **`assets/images/README.md`** for the numbered list of images to create. Until images exist, figures show alt text and broken-image icons in some browsers.
