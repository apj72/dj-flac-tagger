# DJ FLAC Tagger

A local web tool for DJs to create lossless digital copies of vinyl records and other audio sources. Record your vinyl through OBS with BlackHole, then use this tool to extract the FLAC audio, auto-tag it with metadata and artwork from Discogs, Bandcamp, or Apple Music, and have it ready for import into Rekordbox, Traktor, or any DJ software.

![Python](https://img.shields.io/badge/python-3.10+-blue)
![License](https://img.shields.io/badge/license-MIT-green)

## Why?

OBS Studio is primarily a video recording tool — it outputs `.mkv` video files even when all you care about is the audio. If you configure OBS to use FLAC as the audio encoder, the lossless audio is trapped inside a large video container alongside an unnecessary video stream. This tool solves that by stripping out just the audio track, keeping it bit-for-bit lossless, and producing a properly tagged FLAC file with artwork — ready to drop straight into your DJ library.

## What It Does

1. **Extracts audio** from MKV/MP4/MOV recordings — lossless stream copy when the source is already FLAC, otherwise converts to FLAC. The video track is discarded.
2. **Analyses audio levels** — displays integrated LUFS, true peak, and mean volume with colour-coded meters so you can see at a glance if your recording levels are healthy
3. **Normalises audio** (optional) — two-pass EBU R128 loudness normalisation to -14 LUFS, keeping the output as lossless FLAC. Auto-suggested when levels are too quiet, with an on/off toggle
4. **Fetches metadata** from Bandcamp, Discogs, Apple Music, or any URL — title, artist, album, year, genre, label, catalogue number
5. **Embeds cover artwork** directly into the FLAC file
6. **Copies the tagged FLAC** to a configurable destination folder (e.g. your Rekordbox library)
7. **Moves the source MKV to Bin** after extraction (optional, recoverable from macOS Trash)

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

### Workflow

1. **Settings** — configure your source folder (where OBS saves recordings) and destination folder (where tagged FLACs should be copied, e.g. your Rekordbox library)
2. **Select** an MKV file from the source folder — audio levels are automatically analysed and displayed with LUFS, peak, and mean meters
3. **Review levels** — if the recording is too quiet, the normalisation toggle auto-enables. Override it if you prefer the original levels
4. **Paste a URL** (Bandcamp, Discogs, or Apple Music) or type the track name, then hit **Fetch Metadata**
5. **Pick a track** if the release has multiple tracks (Discogs EPs/albums)
6. **Review/edit** metadata and artwork
7. **Extract** — creates a tagged FLAC (with optional normalisation to -14 LUFS), copies it to your destination folder, and optionally trashes the source MKV

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
| **Apple Music** (song URL) | Artist, album, year, genre, track number, high-res artwork |
| **Any URL** | Title, artwork (via Open Graph tags) |
| **Manual** | Type everything yourself |

## Configuration

Settings are stored in `config.json` and can be edited via the UI or directly:

```json
{
  "source_dir": "~/DJ-Mixes",
  "destination_dir": "~/Documents/Rekordbox-music/FLACs"
}
```

## Project Structure

```
dj-flac-tagger/
├── app.py              # Flask backend — extraction, scraping, tagging
├── config.json         # Persisted settings (source/destination folders)
├── requirements.txt    # Python dependencies
├── static/
│   ├── index.html      # Single-page UI
│   ├── style.css       # Dark theme styles
│   └── app.js          # Frontend logic
└── README.md
```

## License

MIT
