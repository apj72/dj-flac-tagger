config = {
    "base_url": "http://127.0.0.1:5123",
    "output_dir": "docs/user-guide/assets/images",
    "viewport": [1280, 800],
    "default_wait": ".app",
}

scenarios = [
    # 1. Navigation bar — all tabs visible
    {
        "name": "01-nav-all-tabs",
        "caption": "Main navigation header with all eight tab icons",
        "actions": [
            {"wait": ".tab-nav"},
            {"wait": 400},
        ],
    },
    # 2. Settings page
    {
        "name": "02-settings-full-page",
        "caption": "Settings page with paths, format, loudness targets, and Platinum Notes",
        "actions": [
            {"url": "/settings"},
            {"wait": "#save-settings-btn"},
            {"wait": 500},
        ],
    },
    # 3. Extract — file list and meters
    {
        "name": "03-extract-file-list-meters",
        "caption": "Extract tab showing video file list and audio level meters",
        "actions": [
            {"url": "/"},
            {"wait": ".tab-nav"},
            {"wait": 500},
        ],
    },
    # 6. Fix Metadata — step 1 folder and files
    {
        "name": "06-fix-step1-folder-files",
        "caption": "Fix Metadata step 1: folder bar and file list",
        "actions": [
            {"url": "/fix"},
            {"wait": ".tab-nav"},
            {"wait": 500},
        ],
    },
    # 11. Inspect — folder and file list
    {
        "name": "11-inspect-folder-list",
        "caption": "Inspect tab with folder field and file listing",
        "actions": [
            {"url": "/inspect"},
            {"wait": ".tab-nav"},
            {"wait": 500},
        ],
    },
    # 13. Normalise — analyse
    {
        "name": "13-normalise-analyse",
        "caption": "Normalise tab with file picker and analysis controls",
        "actions": [
            {"url": "/normalise"},
            {"wait": ".tab-nav"},
            {"wait": 500},
        ],
    },
    # 15. WAV/AIFF to FLAC — single file
    {
        "name": "15-wav-flac-single",
        "caption": "WAV/AIFF to FLAC single file conversion mode",
        "actions": [
            {"url": "/convert"},
            {"wait": ".tab-nav"},
            {"wait": 500},
        ],
    },
    # 19. Bulk Fix — step 1 load
    {
        "name": "19-bulk-fix-step1-load",
        "caption": "Bulk Fix step 1: load batch with path, offset, and limit",
        "actions": [
            {"url": "/bulk-fix"},
            {"wait": ".tab-nav"},
            {"wait": 500},
        ],
    },
    # 24. Fix List — import step
    {
        "name": "24-fix-list-import",
        "caption": "Fix List tab: CSV import from Rekordbox Library Manager",
        "actions": [
            {"url": "/fix-list"},
            {"wait": ".tab-nav"},
            {"wait": 500},
        ],
    },
    # 25. Fix List — track list with status indicators
    {
        "name": "25-fix-list-track-list",
        "caption": "Fix List track list showing status indicators (ticks, dots, badges)",
        "actions": [
            {"url": "/fix-list"},
            {"wait": 2500},
        ],
    },
    # 26. Fix List — detail panel with search results
    {
        "name": "26-fix-list-detail-results",
        "caption": "Fix List detail panel with artwork thumbnails and search results",
        "actions": [
            {"url": "/fix-list"},
            {"wait": 1500},
            {"scroll": "#fl-detail"},
        ],
    },
    # 27. Fix List — export completed
    {
        "name": "27-fix-list-export",
        "caption": "Fix List export section for completed track paths",
        "actions": [
            {"url": "/fix-list"},
            {"wait": "#fl-apply-card"},
            {"wait": 500},
            {"scroll": "#fl-apply-card"},
        ],
    },
]
