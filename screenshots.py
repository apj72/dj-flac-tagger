config = {
    "base_url": "http://127.0.0.1:5123",
    "output_dir": "docs/user-guide/assets/images",
    "viewport": [1280, 800],
    "default_wait": ".app",
    "init_js": "localStorage.setItem('djmm.themePreference','dark'); localStorage.setItem('djmm.pageBackgroundEnabled','1');",
}

scenarios = [
    {
        "name": "01-nav-all-tabs",
        "caption": "Main navigation header with all tab icons",
        "actions": [{"wait": ".tab-nav"}, {"wait": 400}],
    },
    {
        "name": "02-settings-full-page",
        "caption": "Settings page with paths, format, loudness targets, and Platinum Notes",
        "url": "/settings",
        "actions": [{"wait": "#save-settings-btn"}, {"wait": 500}],
    },
    {
        "name": "03-extract-file-list-meters",
        "caption": "Extract tab showing video file list and audio level meters",
        "actions": [{"wait": ".tab-nav"}, {"wait": 500}],
    },
    {
        "name": "04-extract-metadata-url",
        "caption": "Extract tab track URL field and fetch metadata area",
        "actions": [
            {"wait": ".tab-nav"},
            {"scroll": "#lookup-section"},
            {"wait": 300},
        ],
    },
    {
        "name": "05-extract-processing-log",
        "caption": "Extract tab processing log section",
        "actions": [
            {"wait": ".tab-nav"},
            {"scroll": "#history-section"},
            {"wait": 300},
        ],
    },
    {
        "name": "06-fix-step1-folder-files",
        "caption": "Fix Metadata step 1: folder bar and file list",
        "url": "/fix",
        "actions": [{"wait": ".tab-nav"}, {"wait": 500}],
    },
    {
        "name": "07-fix-step2-combined-results",
        "caption": "Fix Metadata step 2: combined search results",
        "url": "/fix",
        "actions": [
            {"wait": ".tab-nav"},
            {"js": "document.getElementById('fix-search-section').classList.remove('hidden')"},
            {"scroll": "#fix-search-section"},
            {"wait": 500},
        ],
    },
    {
        "name": "08-fix-step2-manual-site-search",
        "caption": "Fix Metadata step 2: per-site fallback search",
        "url": "/fix",
        "actions": [
            {"wait": ".tab-nav"},
            {"js": "document.getElementById('fix-search-section').classList.remove('hidden'); document.getElementById('fix-search-fallback').classList.remove('hidden')"},
            {"scroll": "#fix-search-fallback"},
            {"wait": 500},
        ],
    },
    {
        "name": "09-fix-step3-metadata-artwork",
        "caption": "Fix Metadata step 3: metadata fields and artwork preview",
        "url": "/fix",
        "actions": [
            {"wait": ".tab-nav"},
            {"scroll": "#fix-artwork-zone"},
            {"wait": 500},
        ],
    },
    {
        "name": "10-fix-step4-save-rename",
        "caption": "Fix Metadata step 4: save button and rename to tags",
        "url": "/fix",
        "actions": [
            {"wait": ".tab-nav"},
            {"scroll": "#fix-save-btn"},
            {"wait": 500},
        ],
    },
    {
        "name": "11-inspect-folder-list",
        "caption": "Inspect tab with folder field and file listing",
        "url": "/inspect",
        "actions": [{"wait": ".tab-nav"}, {"wait": 500}],
    },
    {
        "name": "12-inspect-tag-table-artwork",
        "caption": "Inspect tab tag table and artwork preview",
        "url": "/inspect",
        "actions": [
            {"wait": ".tab-nav"},
            {"js": "document.getElementById('ins-details-layout').classList.remove('hidden')"},
            {"scroll": "#ins-details-layout"},
            {"wait": 500},
        ],
    },
    {
        "name": "13-normalise-analyse",
        "caption": "Normalise tab with file picker and analysis controls",
        "url": "/normalise",
        "actions": [{"wait": ".tab-nav"}, {"wait": 500}],
    },
    {
        "name": "14-normalise-suffix-output",
        "caption": "Normalise tab suffix field and normalise button",
        "url": "/normalise",
        "actions": [
            {"wait": ".tab-nav"},
            {"scroll": "#norm-run-btn"},
            {"wait": 500},
        ],
    },
    {
        "name": "15-wav-flac-single",
        "caption": "WAV/AIFF to FLAC single file conversion mode",
        "url": "/convert",
        "actions": [{"wait": ".tab-nav"}, {"wait": 500}],
    },
    {
        "name": "16-wav-flac-bulk-options",
        "caption": "WAV/AIFF to FLAC bulk conversion options",
        "url": "/convert",
        "actions": [
            {"wait": ".tab-nav"},
            {"click": "#convert-toggle-bulk"},
            {"wait": 300},
            {"scroll": "#convert-bulk-panel"},
            {"wait": 500},
        ],
    },
    {
        "name": "17-wav-flac-confirm-modal",
        "caption": "WAV/AIFF to FLAC bulk confirmation modal",
        "url": "/convert",
        "actions": [
            {"wait": ".tab-nav"},
            {"wait": 500},
        ],
    },
    {
        "name": "18-wav-flac-open-bulk-fix",
        "caption": "WAV/AIFF to FLAC success with Open Bulk Fix handoff",
        "url": "/convert",
        "actions": [
            {"wait": ".tab-nav"},
            {"wait": 500},
        ],
    },
    {
        "name": "19-bulk-fix-step1-load",
        "caption": "Bulk Fix step 1: load batch with path, offset, and limit",
        "url": "/bulk-fix",
        "actions": [{"wait": ".tab-nav"}, {"wait": 500}],
    },
    {
        "name": "20-bulk-fix-step3-suggest",
        "caption": "Bulk Fix after Fetch online matches with dropdowns",
        "url": "/bulk-fix",
        "actions": [
            {"wait": ".tab-nav"},
            {"scroll": "#bf-table"},
            {"wait": 500},
        ],
    },
    {
        "name": "21-bulk-fix-apply",
        "caption": "Bulk Fix apply section with checkboxes",
        "url": "/bulk-fix",
        "actions": [
            {"wait": ".tab-nav"},
            {"scroll": "#bf-apply-btn"},
            {"wait": 500},
        ],
    },
    {
        "name": "24-fix-list-import",
        "caption": "Fix List tab: CSV import from Rekordbox Library Manager",
        "url": "/fix-list",
        "actions": [{"wait": 2500}],
    },
    {
        "name": "25-fix-list-track-list",
        "caption": "Fix List track list showing status indicators",
        "url": "/fix-list",
        "actions": [{"wait": 2500}],
    },
    {
        "name": "26-fix-list-detail-results",
        "caption": "Fix List detail panel with artwork thumbnails and source badges",
        "url": "/fix-list",
        "actions": [
            {"wait": 2500},
            {"scroll": "#fl-detail"},
        ],
    },
    {
        "name": "27-fix-list-export",
        "caption": "Fix List export section for completed track paths",
        "url": "/fix-list",
        "actions": [
            {"wait": 2500},
            {"scroll": "#fl-apply-card"},
        ],
    },
    {
        "name": "28-mix-cue-load",
        "caption": "Mix Tags: recorded mixes listed with a cue badge, ready to load",
        "url": "/mix-cue",
        "actions": [
            {"wait": "#mc-file-list .file-item"},
            {"wait": 600},
        ],
    },
    {
        "name": "29-mix-cue-editor",
        "caption": "Mix Tags: editable mix details and tracklist with per-track times, plus write options",
        "url": "/mix-cue",
        "actions": [
            {"wait": "#mc-file-list .file-item"},
            {"js": "([...document.querySelectorAll('#mc-file-list .file-item')].find(e=>e.textContent.toLowerCase().includes('.wav'))||document.querySelector('#mc-file-list .file-item')).click()"},
            {"wait": "#mc-tracks .mc-track-row"},
            {"scroll": "#mc-editor"},
            {"wait": 800},
        ],
    },
    {
        "name": "30-mix-cue-share",
        "caption": "Mix Tags: copy-ready SoundCloud / Mixcloud / YouTube description and tracklist",
        "url": "/mix-cue",
        "actions": [
            {"wait": "#mc-file-list .file-item"},
            {"js": "([...document.querySelectorAll('#mc-file-list .file-item')].find(e=>e.textContent.toLowerCase().includes('.wav'))||document.querySelector('#mc-file-list .file-item')).click()"},
            {"wait": "#mc-tracks .mc-track-row"},
            {"scroll": "#mc-share"},
            {"wait": 800},
        ],
    },
]
