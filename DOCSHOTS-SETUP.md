# Adding Documentation Screenshots to DJ MetaManager

This document tells Claude Code how to set up automated screenshot capture for DJ MetaManager using the shared `docshots` tool.

## What is docshots?

`docshots` is a reusable Playwright-based screenshot automation tool at `~/git-repos/docshots/`. It captures screenshots of web UIs by running through scripted scenarios — clicking buttons, selecting options, typing into inputs, waiting for elements — then saving PNGs.

Each project defines its own `screenshots.py` with scenarios. The runner is invoked from the project directory.

## Prerequisites

Playwright and Chromium must be installed (one-time setup):

```bash
cd ~/git-repos/docshots
./install.sh
```

## What to create

### 1. Create `screenshots.py` in the dj-meta-manager project root

This file defines a `config` dict and a `scenarios` list. DJ MetaManager runs on port **5123** and has 8 HTML pages.

```python
"""Screenshot scenarios for DJ MetaManager documentation."""

config = {
    "base_url": "http://127.0.0.1:5123",
    "output_dir": "docs/screenshots",
    "viewport": [1400, 900],
    "default_wait": "nav.tab-nav",
}
```

**Important notes for writing scenarios:**

- DJ MetaManager is a **multi-page app** (not SPA). Use `"url": "/fix"` etc. to navigate between pages, or use the `{"url": "/fix"}` action within a scenario.
- The `default_wait` should be `"nav.tab-nav"` since it appears on every page and confirms the page loaded.
- Pages that load file lists need extra waits — file lists are populated by JavaScript after page load.
- Some sections are hidden by default and revealed by user action (e.g. `#fix-search-section`, `#tracklist-section`).
- The app must be running: `./start.sh`

### 2. Scenario ideas for each page

Here are recommended scenarios with the selectors to use. Adapt based on what looks good.

**Extract page (`/`)**
```python
{
    "name": "extract-empty",
    "caption": "Extract page — source file selection",
    "url": "/",
    "wait": "#source-section",
},
```

**Fix Metadata (`/fix`)**
```python
{
    "name": "fix-metadata",
    "caption": "Fix Metadata page — file browser and tag editor",
    "url": "/fix",
    "wait": "#fix-dir",
},
```

**Inspect (`/inspect`)**
```python
{
    "name": "inspect",
    "caption": "Inspect page — view file metadata and artwork",
    "url": "/inspect",
    "wait": "#ins-dir",
},
```

**Normalise (`/normalise`)**
```python
{
    "name": "normalise",
    "caption": "Normalise page — EBU R128 loudness normalisation",
    "url": "/normalise",
    "wait": "#norm-dir",
},
```

**Convert (`/convert`)**
```python
{
    "name": "convert",
    "caption": "Convert page — WAV/AIFF to FLAC conversion",
    "url": "/convert",
    "wait": "#convert-dir",
},
```

**Bulk Fix (`/bulk-fix`)**
```python
{
    "name": "bulk-fix",
    "caption": "Bulk Fix page — batch metadata matching and correction",
    "url": "/bulk-fix",
    "wait": "#bf-dir",
},
```

**Fix List (`/fix-list`)**
```python
{
    "name": "fix-list",
    "caption": "Fix List page — process a CSV fix list from Rekordbox Library Manager",
    "url": "/fix-list",
    "wait": "#fl-csv-input",
},
```

**Settings (`/settings`)**
```python
{
    "name": "settings",
    "caption": "Settings page — configure paths, formats, and loudness targets",
    "url": "/settings",
    "wait": "#save-settings-btn",
},
```

### 3. Action reference

Use these in the `"actions"` list for each scenario:

| Action | Example | Description |
|--------|---------|-------------|
| click | `{"click": "#btn-id"}` | Click a button or element |
| dismiss | `{"dismiss": "#optional-el"}` | Click if exists, skip if not |
| select | `{"select": "#dropdown", "value": "opt"}` | Select dropdown value |
| type | `{"type": "#input", "text": "hello"}` | Type into a text field |
| check | `{"check": "#checkbox"}` | Check a checkbox |
| wait (ms) | `{"wait": 500}` | Pause for N milliseconds |
| wait (selector) | `{"wait": "#element"}` | Wait for element to appear |
| scroll | `{"scroll": "#element"}` | Scroll element into view |
| url | `{"url": "/fix"}` | Navigate to a different page |
| screenshot | `{"screenshot": "#el", "name": "detail"}` | Capture a specific element |

### 4. Key selectors reference

**Navigation:** `a.tab-link[href="/fix"]`, `a.tab-link[href="/inspect"]`, etc.

**Extract page:** `#source-section`, `#lookup-section`, `#metadata-section`, `#extract-section`, `#history-section`, `#file-list`, `#probe-info`, `#analysis-panel`, `#artwork-preview`, `#extract-btn`, `#fetch-btn`

**Fix Metadata:** `#fix-file-list`, `#fix-current-tags`, `#fix-artwork-preview`, `#fix-search-section`, `#fix-search-results`, `#fix-save-btn`, `#fix-artwork-lightbox`

**Inspect:** `#ins-file-list`, `#ins-details-layout`, `#ins-meta-table`, `#ins-art-preview`, `#ins-file-info`

**Normalise:** `#norm-file-list`, `#norm-analysis-panel`, `#norm-run-btn`, `#norm-bulk-progress-wrap`

**Convert:** `#convert-file-list`, `#convert-single-panel`, `#convert-bulk-panel`, `#convert-run-btn`

**Bulk Fix:** `#bf-table`, `#bf-tbody`, `#bf-load-batch-btn`, `#bf-fetch-matches-btn`, `#bf-apply-btn`, `#bf-confirm-modal`

**Fix List:** `#fl-csv-input`, `#fl-track-list`, `#fl-detail`, `#fl-summary`, `#fl-upload-btn`

**Settings:** `#cfg-theme`, `#cfg-extract-profile`, `#cfg-source`, `#cfg-dest`, `#cfg-target-lufs`, `#save-settings-btn`

### 5. Create the output directory

```bash
mkdir -p docs/screenshots
```

### 6. Run docshots

```bash
# Make sure the app is running
./start.sh

# Capture all screenshots
python ~/git-repos/docshots/docshots.py

# List available scenarios
python ~/git-repos/docshots/docshots.py --list

# Capture one scenario
python ~/git-repos/docshots/docshots.py -s fix-metadata

# Debug with visible browser
python ~/git-repos/docshots/docshots.py --headed --slow 500

# Generate markdown image references for README
python ~/git-repos/docshots/docshots.py --markdown
```

### 7. Add screenshots to README

Use the `--markdown` flag output, or manually add:

```markdown
![Extract page](docs/screenshots/extract-empty.png)
![Fix Metadata](docs/screenshots/fix-metadata.png)
```

### 8. Add to .gitignore (optional)

If you don't want to commit the PNGs (they can be regenerated):

```
docs/screenshots/
```

Or commit them so GitHub renders them in the README.

## How music_library uses docshots

For reference, `~/git-repos/music_library/screenshots.py` has 9 scenarios that capture the track table in various filter states, the activity log panel, and the fix playlists panel. The pattern is the same — `config` + `scenarios` list, run from the project directory.
