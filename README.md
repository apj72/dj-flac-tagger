# DJ MetaManager

A local web tool for DJs to turn recordings into a clean, tagged library in **multiple audio formats**. Record vinyl or other sources through OBS with BlackHole, then extract audio from video containers, auto-tag with metadata and artwork from Discogs, Bandcamp, Apple Music, or Spotify, and export to **FLAC (lossless)**, **MP3**, or **AAC (M4A)** — whatever you choose in Settings — ready for Rekordbox, Traktor, or any DJ software.

**Fix Metadata** and **Inspect** work across **FLAC, MP3, M4A/AAC, OGG**, and more for browsing and editing. **Normalise** applies **EBU R128** loudness to existing files and re-encodes using the same **system-wide format** as Extract. A **Settings** tab controls paths, output format, and loudness targets.

![Python](https://img.shields.io/badge/python-3.10+-blue)
![License](https://img.shields.io/badge/license-MIT-green)

## Version & branches

| Branch | Purpose |
|--------|---------|
| **`master`** | Stable release; multi-format extract, tag, and normalise as documented below. |
| **`v2`** | Active development; new features land here first, then merge to `master` when ready. |

**On branch `v2` today:** **Bulk Fix** (batch FLAC metadata, Bandcamp search, duplicate-name warnings, optional sibling `.wav` hints), batch **WAV → FLAC** with offsets, **Inspect** folder picker, last browsed folder remembered between **Fix Metadata** and **Inspect**, and **UTF-8–safe** HTML/JSON scraping so accented titles (e.g. Apple Music) write correctly to tags.

## Recording

This workflow assumes you capture mixes or vinyl rips as **video recordings** (often `.mkv`) using **[OBS Studio](https://obsproject.com/)** with a virtual audio device such as **[BlackHole](https://existential.audio/blackhole/)** on macOS. **OBS** is a practical choice because it is **free and open source**, can **record video** when you want a visual timeline or camera view, and supports **streaming** as well as local capture — one familiar tool for several setups.

OBS is still primarily a **video** app: even when you only care about audio, it often writes **`.mkv`** files. If you use a **lossless encoder (e.g. FLAC)** in OBS, that audio sits inside a large container alongside an unnecessary video stream. DJ MetaManager strips the audio, optionally normalises it, tags it, embeds artwork, and writes a **library-ready file** in your chosen format. You can also start from **lossy** source codecs and encode to MP3 or AAC when that fits your workflow.

## What It Does

Seven pages, via tabs at the top (order: **Extract → Fix Metadata → Inspect → Normalise → WAV → FLAC → Bulk Fix → Settings**):

### Extract (main workflow)

1. **Extracts audio** from MKV/MP4/MOV — output codec and container follow **Settings → extract format** (FLAC 16-bit, MP3 320 CBR, or AAC in M4A). When the source stream already matches the target, ffmpeg copies or transcodes as appropriate; video is discarded.
2. **Analyses audio levels** — integrated LUFS, true peak, mean volume with colour-coded meters.
3. **Normalises audio** (optional) — two-pass **EBU R128** `loudnorm` to the **LUFS target in Settings** (default **-14**; use **-11.5** to align with tools like Platinum Notes). Toggle on/off per extract.
4. **Fetches metadata** from Bandcamp, Discogs, Apple Music, Spotify, or generic URLs.
5. **Embeds artwork** and **stores the metadata source URL** in the file (`DJMETAMANAGER_SOURCE_URL` Vorbis comment / MP3 TXXX; older files may still use `DJFLACTAGGER_SOURCE_URL`, which is read for compatibility) and in the **processing log** for later re-fetch.
6. **Copies** the tagged file to your **destination** folder.
7. **Moves the source recording to Bin** (optional, macOS Finder).
8. **Platinum Notes (optional)** — in Settings, set the **exact app name** (e.g. `Platinum Notes 10`). On Extract you can **open the extracted file in Platinum Notes** and **watch for the `*_PN` output** (same base name and extension family); when it appears, tags and artwork are **re-applied** from the same log entry (and the PN file is **copied next to your library copy** when a destination copy exists).

Paths, loudness targets, and Platinum Notes options live on the **Settings** tab.

### Fix Metadata

Browse audio files (multiple formats), auto-search iTunes, Discogs, and Bandcamp, fetch from URLs, edit fields, **save tags and artwork**. The **URL field** is saved into the file and into the **processing log** (when you used a URL or artwork URL) so you can trace the source. **Saved metadata URL** appears on **Inspect** for FLAC/OGG/MP3 where supported.

When a file has no useful tags, the **suggested search** string is derived from the **filename** using the same rules as **WAV → FLAC** tags and **Bulk Fix** (see [Filename search and tags](#filename-search-and-tags) below).

**Folder path:** The last folder you successfully listed in **Fix** or **Inspect** is remembered in the browser (alongside **Default** from Settings), so switching between those tabs keeps the same directory.

### Inspect

Full tag table, artwork preview, **Fix artwork dimensions** for **FLAC** (Rekordbox-friendly; other formats unchanged here). Shows **Saved metadata URL** when present. Pick a folder with **Choose folder…** (server-side navigator), **Default** (Settings destination), then **List files** — useful for reviewing a flat **Converted WAVs** tree after bulk conversion. Deep link: **`/inspect?dir=/path/to/folder`**.

### Normalise

Pick a **supported audio file**, analyse levels, then **normalise** to your **Settings** LUFS target. Output uses **the same extract format as Settings** (FLAC, MP3, or AAC/M4A): **`{stem}{suffix}{extension}`** (default suffix `_LUFS14`). **Tags and artwork are copied** from the source.

- **FLAC:** Prefers the Xiph **`flac`** CLI when installed (`brew install flac`): **`flac --best -e -p`**. Otherwise FFmpeg’s FLAC encoder (`-compression_level 12`). **16-bit** at the source sample rate/layout. Normalised files are often **larger** than the original at the same rate/bit-depth because the waveform is harder to compress — that is normal and still lossless.
- **MP3 / AAC:** Encoded with FFmpeg after loudnorm (lossy).

**Sample rate and channel layout** follow the source where applicable so outputs stay e.g. **48 kHz**, not accidentally upsampled.

### Platinum Notes

**Platinum Notes** is optional: many DJs use it for loudness or “polish” passes on finished files. DJ MetaManager can **open an extracted file in Platinum Notes** from the Extract step and **watch for its processed output** (typically a sibling file with a configured suffix, e.g. `_PN`). When that file appears, the app can **re-apply the same tags and artwork** from your processing log, and optionally copy the result next to your library copy. Set the **exact macOS app name** and output suffix under **Settings**.

#### Platinum Notes and file format

If you use **Extract → open in Platinum Notes → watch for processed output**, set Platinum Notes to **Match input format** (and choose an output location **other than** “Replace Original Files,” as Platinum Notes requires). Then the `*_PN` file keeps the **same extension** as the file this app wrote (e.g. both `.flac` or both `.mp3`), matching your **extract format** in Settings. If PN uses a **fixed** output type that does not match, automatic repair may look for the wrong filename.

**Output folder:** The app looks for `<title><suffix>.<ext>` (e.g. `Song_PN.flac`) in this order: next to the **initial extract** (same folder as the recording), next to the **library copy** if Extract copied to **Settings → destination** (e.g. your FLACs tree), and **flat in the destination folder** itself. So you can point Platinum Notes at your **FLACs / destination** folder only — polling still finds the finished file as long as the **base name** matches (same stem as the extract, plus the configured suffix).

### Settings

- **Source / destination** folders  
- **Extract format** — global default for **Extract** output and **Normalise** re-encode  
- **Platinum Notes** app name and **`_PN` output suffix**  
- **Loudness target (LUFS)** and **true peak (dBTP)** — e.g. **-11.5** / **-1** to match Platinum Notes; **-14** / **-1** for streaming-style reference. You may enter **11.5** (positive); it is treated as **-11.5 LUFS**.

### WAV → FLAC

Convert **WAV** recordings to **FLAC** (ffmpeg, compression level 12). Source WAVs are never deleted.

- **Single file** — browse a folder for `.wav`, choose output next to the file or under **Settings → destination**.
- **Bulk (folder tree)** — convert every `.wav` under a root (optionally recursive). Output modes:
  - **Next to each WAV** — write `<name>.flac` beside the source.
  - **Mirror under destination** — preserve subfolders under your **Settings** destination (avoids name collisions across BPM folders).
  - **One flat folder** — e.g. all converted files into a single Rekordbox-style directory; filenames use **`Slot - BPM - Artist - Title`** when the WAV name matches that pattern; many DJ exports instead use a **flat** name with a lead slot and trailing key + BPM (see [Filename search and tags](#filename-search-and-tags)).
- **Tags from filename** — after each encode, **artist** and **title** Vorbis tags are set when the stem can be parsed (see below; aligned with **Fix Metadata** and **Bulk Fix**).
- **Batching (recommended for large trees)** — by default, each run only processes a **batch** of WAVs in **sorted path order** using **offset** and **limit** (e.g. 25 per run). Use **Next offset** to step through hundreds of files safely; keep **skip if FLAC exists** on to resume. Uncheck “limit each run” only if you intentionally want one run for the whole tree (you’ll get a stronger warning when the scan count is high).
- After a successful **flat-folder** run, the UI offers **Open Bulk Fix for this folder** (or use **Bulk Fix** with `?dir=/path/to/folder`).

### Bulk Fix (metadata in batches)

For a **folder of FLACs** (often the same flat folder as **WAV → FLAC** output), review and apply **Discogs, Apple Music, or Bandcamp** (and other) metadata without doing one file at a time on **Fix Metadata**.

1. **Scan & load** — choose root, **files per pass**, and **offset** (same idea as WAV batching: stable sorted list). If the same **filename** exists more than once (e.g. in different subfolders, or two copies in the same batch), the table flags **Duplicate in this batch** or **Same name elsewhere** and lists other paths; the apply step warns if you are about to tag multiple copies.
2. **Fetch online matches** — runs the same combined **iTunes + Discogs + Bandcamp** search as Fix, with gentle rate spacing between files. The **search query** for each file is built from the **filename stem** using [Filename search and tags](#filename-search-and-tags).
3. **Review** — per row, pick a search result or paste a **Bandcamp / Discogs / Apple / Spotify** URL. After **Fetch online matches**, each row lists **shortcuts (Apple / Discogs / Bandcamp)** and the **full URL** for every hit (same URL the dropdown uses), so you can open and validate in the browser before apply. The **Match** column uses high-contrast link colours on a slightly lighter cell background so URLs stay readable on dark mode.
4. **Apply** — fetches full metadata, matches **multi-track** Discogs releases using the **title hint** from the filename when possible, embeds tags and artwork; optional **rename to `Artist - Title.flac`**. Optional logging to the processing log.

**Optional same-name `.wav`:** If `SomeTrack.wav` sits in the **same folder** as `SomeTrack.flac`, the server reads **embedded WAV tags** (when mutagen can see them — e.g. some BWF/RIFF metadata). If **both** artist and title are present in the WAV, the **search query** uses that pair (often cleaner than the filename alone). If only one of those fields exists, it can still **fill title/artist hints** for track matching without replacing the whole query. Many exports have **no** useful WAV tags, so the filename rules above still do most of the work.

The **WAV → FLAC** tab links here after a flat-folder conversion; **Bulk Fix** also reads **`?dir=...`** from the URL to pre-fill the folder path.

#### Filename search and tags

DJs often export or convert tracks with **extra text in the filename** that is not part of the real artist/title. The app **does not** search on the raw stem; it normalizes first so Discogs, Apple, and Bandcamp get a useful query.

1. A **`_PN` suffix** (Platinum Notes) on the stem is removed, e.g. `Track_PN` → `Track` (case-insensitive).
2. **Classic Ableton / export pattern** (hyphen-separated): if the name looks like  
   `[slot] - [BPM] - [artist] - [title]`  
   (e.g. `A06 - 139 - Members Of Mayday - 10 In 01`), that pattern wins — **no** further stripping, so the hyphens in the real title are preserved.
3. Otherwise **Rekordbox-style flat names** are cleaned:
   - **Trailing** [Camelot key] + [BPM], e.g. ` 2A 120` or ` 12A 98` (number + A/B, space, 2–3 digit BPM) at the **end** of the stem.
   - **Leading** slot prefix, e.g. `A02 ` or `B12 ` (one letter + 1–2 digits + space).

**Examples after normalization:**

| Filename stem (no extension) | Search / tag string used |
|------------------------------|-------------------------|
| `A06 - 139 - Members Of Mayday - 10 In 01` | Artist + title from the hyphenated pattern (unchanged) |
| `A02 Christian Loeffler All Comes (Mind Against Remix) 2A 120` | `Christian Loeffler All Comes (Mind Against Remix)` |
| `A02 Ripperton Unfold 2A 119` | `Ripperton Unfold` |

These rules apply to **Bulk Fix** (scan query and title hint), **Fix Metadata** (suggested search from the filename), and **WAV → FLAC** embedding when a classic pattern does not match.

## Recording Setup

- **[BlackHole](https://existential.audio/blackhole/)** — virtual audio on macOS (16-channel version).
- **[OBS Studio](https://obsproject.com/)** — e.g. **FLAC** (or another) audio in an **MKV** container.

### Recommended OBS Settings (lossless capture)

1. **Settings > Output > Output Mode**: Advanced  
2. **Recording > Audio Encoder**: FFmpeg FLAC 16-bit (or your preferred encoder)  
3. **Recording > Recording Format**: MKV  
4. **Settings > Audio > Sample Rate**: 48 kHz  

## Requirements

- **macOS** (Finder trash integration for “move recording to Bin”)
- **Python 3.10+**
- **ffmpeg** and **ffprobe**:

```bash
brew install ffmpeg
```

**Optional (recommended for Normalise when output is FLAC — smaller files with the FLAC CLI):**

```bash
brew install flac
```

## Setup

```bash
git clone https://github.com/apj72/dj-meta-manager.git
cd dj-meta-manager
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp config.json.example config.json
```

Edit `config.json` or use the **Settings** tab in the UI.

## Usage

### Start / stop (background)

```bash
./start.sh    # logs to server.log, PID in .dj-meta-manager.pid
./stop.sh
```

### Foreground

```bash
source venv/bin/activate
python app.py
```

Open **http://127.0.0.1:5123** (or `http://localhost:5123`).

### Extract workflow (summary)

1. **Settings** — folders, extract format, LUFS target, Platinum Notes name/suffix.  
2. **Extract** — browse recordings, select a video file, review meters, fetch metadata (paste **Track URL** to log the source).  
3. Optionally **normalise**, **open in Platinum Notes**, **watch for PN output** to auto re-tag.  
4. **Extract** — tagged audio file in your chosen format, optional copy and trash source.

### Processing log

Entries include **`metadata_source_url`**, **`metadata_source_type`**, **`kind`** (`extract` vs `fix`), **`extract_profile`**, and normalisation targets when used. Use **Re-tag** to apply log entries to files in a folder (e.g. after Platinum Notes renamed the file).

## Audio / loudness notes

| Meter | Meaning | Typical healthy range |
|-------|---------|------------------------|
| **LUFS** | Integrated loudness | about -16 to -12 |
| **Peak** | True peak (dBTP) | about -3 to -1 |

Normalisation uses **two-pass EBU R128** with your configured **I** and **TP** targets.

## Metadata sources

| Source | What you get |
|--------|----------------|
| **Discogs** | Full release metadata, artwork, tracklist |
| **Bandcamp** | Track/album metadata, artwork |
| **Apple Music** | Metadata, artwork, album tracklists |
| **Spotify** | Metadata, artwork, album tracklists |
| **Any URL** | Open Graph title/image where available |
| **Fix page auto-search** | iTunes + Discogs + Bandcamp (Bandcamp via public site search) |

## Supported formats

| Role | Formats |
|------|---------|
| **Extract** (from video) & **Normalise** (re-encode) | **FLAC**, **MP3**, **AAC (M4A)** — selected under **Settings → extract format** |
| **Fix** & **Inspect** (tags / artwork) | **FLAC** — Vorbis comments, pictures · **MP3** — ID3v2, APIC · **M4A / AAC / MP4** — iTunes atoms, `covr` · **OGG** — Vorbis comments, `metadata_block_picture` |

**Inspect: Fix artwork dimensions** applies to **FLAC** only (other formats skip this).

**Unicode:** Metadata scraped from Apple Music, Bandcamp, Spotify, and generic pages is decoded as **UTF-8** so accented titles (e.g. **André**) are not mangled when written to tags.

## Configuration (`config.json`)

Example (see `config.json.example`):

```json
{
  "source_dir": "~/DJ-Mixes",
  "destination_dir": "~/Music/DJ-library",
  "extract_profile": "flac",
  "platinum_notes_app": "Platinum Notes 10",
  "pn_output_suffix": "_PN",
  "target_lufs": -11.5,
  "target_true_peak": -1.0
}
```

## API notes (selected)

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/browse-wav` | List `.wav` in a directory (WAV → FLAC). |
| `POST` | `/api/convert-wav-to-flac` | Single WAV → FLAC; optional `output` `same` / `destination`. |
| `POST` | `/api/convert-wav-bulk` | Bulk WAV → FLAC; `output` `same` / `destination` / `custom` + `target_dir` for flat output. Optional **`offset`**, **`limit`** for batch slices; response includes **`batch`** (`total_wavs`, `candidates_in_batch`, etc.). |
| `GET` | `/api/bulk-fix/scan` | Paginated `.flac` list with **query**, **title_hint**, optional **wav_sibling** + **wav_tags** when a same-name `.wav` exists, plus **duplicate_basename**, **same_basename_count**, **same_basename_other_paths**, **duplicate_in_batch** when the same filename appears more than once under the scanned tree. Response includes **duplicates_in_batch** (rows in this page that share a name with another row). Filename rules: [Filename search and tags](#filename-search-and-tags). |
| `POST` | `/api/bulk-fix/suggest` | Search results per file path (Apple + Discogs + Bandcamp). |
| `POST` | `/api/bulk-fix/apply` | Apply metadata from chosen URLs to many files. |
| `GET` | `/api/search` | iTunes + Discogs + Bandcamp search (used by Fix and Bulk Fix). |
| `POST` | `/api/fetch-metadata` | Full metadata from a URL; optional **`track_name`** / **`track_name_hint`** to pick a track on multi-track releases. |
| `POST` | `/api/retag` | Save tags/artwork/rename for one file (Fix Metadata). |
| `GET` | `/api/browse-folders` | Server-side folder picker for paths the browser cannot read. |

Routes **`/convert`**, **`/bulk-fix`**, etc. serve the static HTML shells; the app runs locally (default **http://127.0.0.1:5123**).

## Development / tests

```bash
source venv/bin/activate
pip install -r requirements-dev.txt
pytest tests/ -v
```

Coverage includes: browse/convert WAV, bulk convert (including **offset/limit** and **custom** flat output + tags), **retag** rename, **bulk-fix** scan (including duplicate detection and WAV tag hints), **Bandcamp search** parsing (mocked HTML), **fetch-metadata** track hints, normalise API, and shared helpers. Tests that invoke **ffmpeg** skip automatically if it is missing. Network calls to live Discogs, Apple, or Bandcamp are **not** required in automated tests; bulk **suggest**/**apply** against real services are left to manual checks.

## Project structure

```
dj-meta-manager/
├── app.py                 # Flask API — ffmpeg, scrapers, mutagen
├── config.json            # Local settings (not in repo)
├── config.json.example
├── processing_log.json    # Local log (not in repo)
├── requirements.txt
├── requirements-dev.txt   # pytest
├── start.sh / stop.sh     # Background server helpers
├── tests/                 # pytest
├── static/
│   ├── index.html / app.js          # Extract
│   ├── fix.html / fix.js            # Fix Metadata
│   ├── inspect.html / inspect.js    # Inspect
│   ├── normalise.html / normalise.js
│   ├── convert.html / convert.js   # WAV → FLAC
│   ├── bulk-fix.html / bulk-fix.js # Bulk Fix metadata
│   ├── path-persist.js             # Shared last folder (Fix + Inspect)
│   ├── settings.html / settings.js
│   └── style.css
└── README.md
```

## License

MIT
