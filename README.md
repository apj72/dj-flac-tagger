# DJ FLAC Tagger

A local web tool for DJs to create lossless digital copies of vinyl records and other audio sources. Record your vinyl through OBS with BlackHole, then use this tool to extract the FLAC audio, auto-tag it with metadata and artwork from Discogs, Bandcamp, or Apple Music, and have it ready for import into Rekordbox, Traktor, or any DJ software.

Also includes **Fix Metadata** (tag editor), **Inspect** (metadata diagnostics), **Normalise** (standalone EBU R128 loudness on existing FLACs), and a dedicated **Settings** tab.

![Python](https://img.shields.io/badge/python-3.10+-blue)
![License](https://img.shields.io/badge/license-MIT-green)

## Why?

OBS Studio is primarily a video recording tool — it outputs `.mkv` video files even when all you care about is the audio. If you configure OBS to use FLAC as the audio encoder, the lossless audio is trapped inside a large video container alongside an unnecessary video stream. This tool strips out the audio track, keeps it lossless, and produces a properly tagged FLAC with artwork — ready for your DJ library.

## What It Does

Five pages, via tabs at the top:

### Extract (main workflow)

1. **Extracts audio** from MKV/MP4/MOV — lossless copy when the source is already FLAC, otherwise converts to FLAC (16-bit). Video is discarded.
2. **Analyses audio levels** — integrated LUFS, true peak, mean volume with colour-coded meters.
3. **Normalises audio** (optional) — two-pass **EBU R128** `loudnorm` to the **LUFS target in Settings** (default **-14**; use **-11.5** to align with tools like Platinum Notes). Toggle on/off per extract.
4. **Fetches metadata** from Bandcamp, Discogs, Apple Music, Spotify, or generic URLs.
5. **Embeds artwork** and **stores the metadata source URL** in the file (`DJFLACTAGGER_SOURCE_URL` Vorbis comment / MP3 TXXX) and in the **processing log** for later re-fetch.
6. **Copies** the tagged FLAC to your **destination** folder.
7. **Moves the source MKV to Bin** (optional, macOS Finder).
8. **Platinum Notes (optional)** — in Settings, set the **exact app name** (e.g. `Platinum Notes 10`). On Extract you can **open the FLAC in Platinum Notes** and **watch for the `*_PN.flac` output**; when it appears, tags and artwork are **re-applied** from the same log entry (and the PN file is **copied next to your library copy** when a destination copy exists).

Paths, loudness targets, and Platinum Notes options live on the **Settings** tab.

### Fix Metadata

Browse audio files, auto-search iTunes + Discogs, fetch from URLs, edit fields, **save tags and artwork**. The **URL field** is saved into the file and into the **processing log** (when you used a URL or artwork URL) so you can trace the source. **Saved metadata URL** appears on **Inspect** for FLAC/OGG/MP3 where supported.

### Inspect

Full tag table, artwork preview, **Fix artwork dimensions** for FLAC (Rekordbox-friendly). Shows **Saved metadata URL** when present.

### Normalise

Pick a **FLAC**, analyse levels, then **normalise** to your **Settings** LUFS target. Writes **`{stem}{suffix}.flac`** (default suffix `_LUFS14`) beside the original. **Tags and artwork are copied** from the source. Encoding:

- Prefers the Xiph **`flac`** CLI when installed (`brew install flac`): **`flac --best -e -p`** (slower, tighter compression).
- Otherwise uses FFmpeg’s FLAC encoder (`-compression_level 12`).

**Sample rate and channel layout** are taken from the source (and **`-ar`** is set) so outputs stay e.g. **48 kHz**, not accidentally upsampled. **Normalised files are often larger than the original FLAC** at the same rate/bit-depth: the waveform is harder for FLAC to compress — that is normal and still lossless.

### Settings

- **Source / destination** folders  
- **Platinum Notes** app name and **`_PN` output suffix**  
- **Loudness target (LUFS)** and **true peak (dBTP)** — e.g. **-11.5** / **-1** to match Platinum Notes; **-14** / **-1** for streaming-style reference. You may enter **11.5** (positive); it is treated as **-11.5 LUFS**.

## Recording Setup

- **[BlackHole](https://existential.audio/blackhole/)** — virtual audio on macOS (16-channel version).
- **[OBS Studio](https://obsproject.com/)** — record with **FLAC** audio, **MKV** container.

### Recommended OBS Settings

1. **Settings > Output > Output Mode**: Advanced  
2. **Recording > Audio Encoder**: FFmpeg FLAC 16-bit  
3. **Recording > Recording Format**: MKV  
4. **Settings > Audio > Sample Rate**: 48 kHz  

## Requirements

- **macOS** (Finder trash integration for “move MKV to Bin”)
- **Python 3.10+**
- **ffmpeg** and **ffprobe**:

```bash
brew install ffmpeg
```

**Optional (recommended for Normalise / smaller FLAC re-encodes):**

```bash
brew install flac
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

Edit `config.json` or use the **Settings** tab in the UI.

## Usage

### Start / stop (background)

```bash
./start.sh    # logs to server.log, PID in .dj-flac-tagger.pid
./stop.sh
```

### Foreground

```bash
source venv/bin/activate
python app.py
```

Open **http://127.0.0.1:5123** (or `http://localhost:5123`).

### Extract workflow (summary)

1. **Settings** — folders, LUFS target, Platinum Notes name/suffix.  
2. **Extract** — browse recordings, select MKV, review meters, fetch metadata (paste **Track URL** to log the source).  
3. Optionally **normalise**, **open in Platinum Notes**, **watch for PN output** to auto re-tag.  
4. **Extract** — tagged FLAC, optional copy and trash source.

### Processing log

Entries include **`metadata_source_url`**, **`metadata_source_type`**, **`kind`** (`extract` vs `fix`), and normalisation targets when used. Use **Re-tag** to apply log entries to files in a folder (e.g. after Platinum Notes renamed the file).

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
| **Fix page auto-search** | iTunes + Discogs |

## Supported formats (Fix / Inspect / Normalise)

| Format | Tags | Artwork |
|--------|------|---------|
| **FLAC** | Vorbis comments | Pictures |
| **MP3** | ID3v2 | APIC |
| **M4A / AAC / MP4** | iTunes atoms | `covr` |
| **OGG** | Vorbis comments | `metadata_block_picture` |

**Normalise** is **FLAC-only**.

## Configuration (`config.json`)

Example (see `config.json.example`):

```json
{
  "source_dir": "~/DJ-Mixes",
  "destination_dir": "~/Music/FLACs",
  "platinum_notes_app": "Platinum Notes 10",
  "pn_output_suffix": "_PN",
  "target_lufs": -11.5,
  "target_true_peak": -1.0
}
```

## Development / tests

```bash
source venv/bin/activate
pip install -r requirements-dev.txt
pytest tests/ -v
```

## Project structure

```
dj-flac-tagger/
├── app.py                 # Flask API — ffmpeg, scrapers, mutagen
├── config.json            # Local settings (not in repo)
├── config.json.example
├── processing_log.json    # Local log (not in repo)
├── requirements.txt
├── requirements-dev.txt   # pytest
├── start.sh / stop.sh     # Background server helpers
├── tests/                 # pytest
├── static/
│   ├── index.html / app.js       # Extract
│   ├── fix.html / fix.js         # Fix Metadata
│   ├── inspect.html / inspect.js # Inspect
│   ├── normalise.html / normalise.js
│   ├── settings.html / settings.js
│   └── style.css
└── README.md
```

## License

MIT
