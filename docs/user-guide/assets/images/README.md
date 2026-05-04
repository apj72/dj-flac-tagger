# User guide screenshots

Place exported PNG (or WebP) files in this folder using the **exact filenames** below. The HTML references these paths; if a file is missing, the browser shows a broken image until you add it.

**Tips**

- Capture at a comfortable window width (e.g. 1200–1400 px) for readability.
- Use the same browser zoom (100%) across shots for a consistent look.
- Prefer **PNG** for UI; **WebP** is fine if you update the `src` in the HTML.
- Trim sensitive paths if needed; blur folder names if you must.

## Required images (checklist)

| # | Filename | What to show |
|---|----------|----------------|
| 1 | `01-nav-all-tabs.png` | Full header with **wordmark/logo** plus **all eight tabs** visible: Extract, Fix Metadata, Inspect, Normalise, WAV → FLAC, Bulk Fix, Settings. |
| 2 | `02-settings-full-page.png` | **Settings** page: source/destination, extract format, LUFS / true peak, Platinum Notes fields. |
| 3 | `03-extract-file-list-meters.png` | **Extract**: folder path, video file list, one file selected, **LUFS / peak meters** visible. |
| 4 | `04-extract-metadata-url.png` | **Extract**: track URL field, fetch metadata, normalise toggle, extract button area. |
| 5 | `05-extract-processing-log.png` | **Extract**: **Processing Log** expanded with at least one row (if your build shows it on this tab). |
| 6 | `06-fix-step1-folder-files.png` | **Fix Metadata**: step 1 folder bar, file list, optional “current tags” summary. |
| 7 | `07-fix-step2-combined-results.png` | **Fix Metadata** step 2: **combined** search results (Apple + Discogs + Bandcamp) with several rows. |
| 8 | `08-fix-step2-manual-site-search.png` | **Fix Metadata** step 2: **fallback** UI — site dropdown (Apple default), query field, Search, **top 3** results (trigger with a query that returns no combined hits, then manual search). |
| 9 | `09-fix-step3-metadata-artwork.png` | **Fix Metadata** step 3: metadata fields + artwork preview filled or partially filled. |
| 10 | `10-fix-step4-save-rename.png` | **Fix Metadata** step 4: save button, **rename to tags** checkbox, rename preview line. |
| 11 | `11-inspect-folder-list.png` | **Inspect**: directory field, **Choose folder** / Default / List files, file list. |
| 12 | `12-inspect-tag-table-artwork.png` | **Inspect**: full tag table + artwork panel + **Saved metadata URL** if present. |
| 13 | `13-normalise-analyse.png` | **Normalise**: file picked, **analyse** / level readout before normalise. |
| 14 | `14-normalise-suffix-output.png` | **Normalise**: suffix field, normalise button, optional success message. |
| 15 | `15-wav-flac-single.png` | **WAV → FLAC**: single-file mode — browse, output option, convert. |
| 16 | `16-wav-flac-bulk-options.png` | **WAV → FLAC**: bulk mode — root path, recursive, output mode (next to / mirror / flat), offset/limit, skip existing. |
| 17 | `17-wav-flac-confirm-modal.png` | **WAV → FLAC**: **in-page confirmation** modal before a large bulk run (if you can trigger it safely on a small test folder, or mock). |
| 18 | `18-wav-flac-open-bulk-fix.png` | **WAV → FLAC**: success area with **Open Bulk Fix** (or handoff) after a flat-folder batch, if available. |
| 19 | `19-bulk-fix-step1-load.png` | **Bulk Fix**: load batch — path, offset, limit, **Load batch** / scan table header. |
| 20 | `20-bulk-fix-step3-suggest.png` | **Bulk Fix**: after **Fetch online matches** — rows with Match dropdown, shortcuts, duplicate warning if you have one. |
| 21 | `21-bulk-fix-apply.png` | **Bulk Fix**: **Apply** section, checkboxes, optional rename — ready to apply. |
| 22 | `22-terminal-start-script.png` | (Optional) Terminal showing `./start.sh` or `python app.py` and the local URL. |
| 23 | `23-config-json-example.png` | (Optional) Editor showing `config.json` with non-secret example paths. |

## Updating the guide

- **New feature:** add a subsection in the relevant chapter HTML under `docs/user-guide/`, add a row here, drop a new image, and reference it with `<figure class="guide-figure">` in that chapter.
- **Renaming files:** search the `docs/user-guide/` folder for the old filename and replace.
