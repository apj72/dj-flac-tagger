# DJ FLAC Tagger

A local web tool for DJs to create lossless digital copies of vinyl records and other audio sources. Record your vinyl through OBS with BlackHole, then use this tool to extract the FLAC audio, auto-tag it with metadata and artwork from Discogs, Bandcamp, or Apple Music, and have it ready for import into Rekordbox, Traktor, or any DJ software.

Also includes a standalone **Fix Metadata** tool for editing tags and artwork on existing audio files (FLAC, MP3, M4A/AAC, OGG) — with automatic search to find the right metadata for you.

![Python](https://img.shields.io/badge/python-3.10+-blue)
![License](https://img.shields.io/badge/license-MIT-green)

## Why?

OBS Studio is primarily a video recording tool — it outputs `.mkv` video files even when all you care about is the audio. If you configure OBS to use FLAC as the audio encoder, the lossless audio is trapped inside a large video container alongside an unnecessary video stream. This tool solves that by stripping out just the audio track, keeping it bit-for-bit lossless, and producing a properly tagged FLAC file with artwork — ready to drop straight into your DJ library.

## What It Does

The tool has two pages, accessible via tabs at the top:

### Extract (main workflow)

1. **Extracts audio** from MKV/MP4/MOV recordings — lossless stream copy when the source is already FLAC, otherwise converts to FLAC. The video track is discarded.
2. **Analyses audio levels** — displays integrated LUFS, true peak, and mean volume with colour-coded meters so you can see at a glance if your recording levels are healthy
3. **Normalises audio** (optional) — two-pass EBU R128 loudness normalisation to -14 LUFS, keeping the output as lossless FLAC. Auto-suggested when levels are too quiet, with an on/off toggle
4. **Fetches metadata** from Bandcamp, Discogs, Apple Music, or any URL — title, artist, album, year, genre, label, catalogue number
5. **Embeds cover artwork** directly into the FLAC file
6. **Copies the tagged FLAC** to a configurable destination folder (e.g. your Rekordbox library)
7. **Moves the source MKV to Bin** after extraction (optional, recoverable from macOS Trash)
8. **Logs every extraction** to a processing log so metadata and artwork can be re-applied later if needed

### Fix Metadata (standalone tag editor)

A separate page for fixing tags on existing audio files — no extraction or audio processing involved.

1. **Browse** any folder for audio files (FLAC, MP3, M4A/AAC, OGG, AIFF, and more)
2. **Auto-searches** iTunes and Discogs when you select a file, using the existing tags or filename to find matching releases
3. **Pick a result** to fetch full metadata and artwork, or paste a URL manually
4. **Supports album/compilation URLs** — Apple Music and Discogs album links show a full tracklist so you can select the right track (useful for DJ mix compilations where each track has a different artist)
5. **Save tags and artwork** directly to the file in the correct format for each file type

This is particularly useful for fixing files that have been processed by other tools (e.g. Platinum Notes) which can strip metadata and artwork.

## Recording Setup

This tool is designed around a recording workflow using:

- **[BlackHole](https://existential.audio/blackhole/)** — a virtual audio driver for macOS that routes system audio (e.g. from a DJ controller or browser) into OBS as a capture source. Use the 16-channel version.
- **[OBS Studio](https://obsproject.com/)** — open-source screen/audio recorder. Configure it to record with **FLAC audio** for lossless quality. OBS outputs `.mkv` video files — this tool extracts the lossless audio from those files.

### Recommended OBS Settings

1. **Settings > Output > Output Mode**: Advanced
2. **Recording tab > Audio Encoder**: FFmpeg FLAC 16-bit
3. **Recording tab > Recording Format**: MKV
4. **Settings > Audio > Sample Rate**: 48 kHz

This captures your audio losslessly. The video track is discarded during extraction.

## Requirements

- **macOS** (uses Finder for trash functionality)
- **Python 3.10+**
- **ffmpeg** and **ffprobe** — install via Homebrew:

```bash
brew install ffmpeg
```

## Setup

```bash
git clone https://github.com/apj72/dj-flac-tagger.git
cd dj-flac-tagger
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp config.json.example config.json
```

Edit `config.json` with your own folder paths, or configure them in the UI.

## Usage

```bash
source venv/bin/activate
python app.py
```

Open **http://localhost:5123** in your browser.

### Extract Workflow

1. **Settings** — configure your source folder (where OBS saves recordings) and destination folder (where tagged FLACs should be copied, e.g. your Rekordbox library)
2. **Select** an MKV file from the source folder — audio levels are automatically analysed and displayed with LUFS, peak, and mean meters
3. **Review levels** — if the recording is too quiet, the normalisation toggle auto-enables. Override it if you prefer the original levels
4. **Paste a URL** (Bandcamp, Discogs, Apple Music, or Spotify) or type the track name, then hit **Fetch Metadata**
5. **Pick a track** if the release has multiple tracks (Discogs EPs/albums, Apple Music/Spotify compilations)
6. **Review/edit** metadata and artwork
7. **Extract** — creates a tagged FLAC (with optional normalisation to -14 LUFS), copies it to your destination folder, and optionally trashes the source MKV

### Fix Metadata Workflow

1. Switch to the **Fix Metadata** tab
2. **Browse** to a folder containing your audio files
3. **Click a file** — the tool reads its current tags, then automatically searches iTunes and Discogs for matching releases
4. **Pick a search result** — or paste a Bandcamp / Discogs / Apple Music URL manually if the search doesn't find what you need
5. **Review/edit** the metadata fields and artwork preview
6. **Save Tags & Artwork** — writes everything to the file

### Audio Level Analysis

When you select a source file, the tool runs an ffmpeg loudness analysis and displays:

| Meter | What it measures | Ideal range |
|-------|-----------------|-------------|
| **LUFS** | Integrated loudness (perceived volume) | -16 to -12 |
| **Peak** | True peak level (dBTP) | -3 to -1 |
| **Mean** | Average volume (dB) | -18 to -12 |

If your recording is significantly below -14 LUFS, the normalisation toggle enables automatically. Normalisation uses **two-pass EBU R128 loudnorm** — the broadcast industry standard — targeting -14 LUFS with a -1 dBTP ceiling. The output remains lossless FLAC.

**Recording tip:** Set your OBS input levels so peaks occasionally touch the bottom of the red zone on the VU meter (around -10 dB). This typically produces recordings around -14 to -12 LUFS — ideal levels that won't need normalisation.

### Metadata Sources

| Source | What you get |
|--------|-------------|
| **Discogs** (master or release URL) | Artist, album, year, genre, styles, label, cat no., artwork, full tracklist |
| **Bandcamp** (track or album URL) | Artist, album, year, genre tags, artwork |
| **Apple Music** (song or album URL) | Artist, album, year, genre, track number, high-res artwork, full tracklist for albums/compilations with per-track artists |
| **Spotify** (track or album URL) | Artist, album, year, track number, artwork, full tracklist for albums/compilations |
| **Any URL** | Title, artwork (via Open Graph tags) |
| **Auto-search** (Fix Metadata page) | Searches iTunes + Discogs automatically from file tags or filename |

### Supported File Formats (Fix Metadata)

| Format | Tags | Artwork |
|--------|------|---------|
| **FLAC** | Vorbis comments | Embedded pictures |
| **MP3** | ID3v2 | APIC frames |
| **M4A / AAC / MP4** | iTunes atoms | `covr` atom |
| **OGG Vorbis** | Vorbis comments | metadata_block_picture |
| **Others** | Generic mutagen fallback | — |

### Processing Log

Every extraction is saved to `processing_log.json` with full metadata, artwork URL, and settings. If tags or artwork are lost (e.g. after processing through Platinum Notes), you can re-apply everything from the log via the Processing Log section on the Extract page.

## Configuration

Settings are stored in `config.json` and can be edited via the UI or directly:

```json
{
  "source_dir": "~/DJ-Mixes",
  "destination_dir": "~/Music/FLACs"
}
```

## Project Structure

```
dj-flac-tagger/
├── app.py              # Flask backend — extraction, scraping, tagging, search
├── config.json         # Persisted settings (source/destination folders)
├── processing_log.json # Extraction history for re-tagging
├── requirements.txt    # Python dependencies
├── static/
│   ├── index.html      # Extract page
│   ├── app.js          # Extract page logic
│   ├── fix.html        # Fix Metadata page
│   ├── fix.js          # Fix Metadata page logic
│   └── style.css       # Shared dark theme styles
└── README.md
```

## License

MIT
