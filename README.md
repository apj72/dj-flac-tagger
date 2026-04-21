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

### Platinum Notes and file format

If you use **Extract → open in Platinum Notes → watch for processed output**, set Platinum Notes to **Match input format** (and choose an output location **other than** “Replace Original Files,” as Platinum Notes requires). Then the `*_PN` file keeps the **same extension** as the file this app wrote (e.g. both `.flac` or both `.mp3`), matching your **extract format** in Settings. If PN uses a **fixed** output type that does not match, automatic repair may look for the wrong filename.

## Why?

OBS Studio is primarily a video recorder — it often outputs `.mkv` files even when you only care about audio. If you use a **lossless encoder (e.g. FLAC)** in OBS, that audio sits inside a large container with an unnecessary video stream. This tool strips the audio, optionally normalises it, tags it, embeds artwork, and writes a **library-ready file** in your chosen format. You can also start from **lossy** source codecs and encode to MP3 or AAC when that fits your workflow.

## What It Does

Five pages, via tabs at the top:

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

Browse audio files (multiple formats), auto-search iTunes + Discogs, fetch from URLs, edit fields, **save tags and artwork**. The **URL field** is saved into the file and into the **processing log** (when you used a URL or artwork URL) so you can trace the source. **Saved metadata URL** appears on **Inspect** for FLAC/OGG/MP3 where supported.

### Inspect

Full tag table, artwork preview, **Fix artwork dimensions** for **FLAC** (Rekordbox-friendly; other formats unchanged here). Shows **Saved metadata URL** when present.

### Normalise

Pick a **supported audio file**, analyse levels, then **normalise** to your **Settings** LUFS target. Output uses **the same extract format as Settings** (FLAC, MP3, or AAC/M4A): **`{stem}{suffix}{extension}`** (default suffix `_LUFS14`). **Tags and artwork are copied** from the source.

- **FLAC:** Prefers the Xiph **`flac`** CLI when installed (`brew install flac`): **`flac --best -e -p`**. Otherwise FFmpeg’s FLAC encoder (`-compression_level 12`). **16-bit** at the source sample rate/layout. Normalised files are often **larger** than the original at the same rate/bit-depth because the waveform is harder to compress — that is normal and still lossless.
- **MP3 / AAC:** Encoded with FFmpeg after loudnorm (lossy).

**Sample rate and channel layout** follow the source where applicable so outputs stay e.g. **48 kHz**, not accidentally upsampled.

### Settings

- **Source / destination** folders  
- **Extract format** — global default for **Extract** output and **Normalise** re-encode  
- **Platinum Notes** app name and **`_PN` output suffix**  
- **Loudness target (LUFS)** and **true peak (dBTP)** — e.g. **-11.5** / **-1** to match Platinum Notes; **-14** / **-1** for streaming-style reference. You may enter **11.5** (positive); it is treated as **-11.5 LUFS**.

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
| **Fix page auto-search** | iTunes + Discogs |

## Supported formats

| Role | Formats |
|------|---------|
| **Extract** (from video) & **Normalise** (re-encode) | **FLAC**, **MP3**, **AAC (M4A)** — selected under **Settings → extract format** |
| **Fix** & **Inspect** (tags / artwork) | **FLAC** — Vorbis comments, pictures · **MP3** — ID3v2, APIC · **M4A / AAC / MP4** — iTunes atoms, `covr` · **OGG** — Vorbis comments, `metadata_block_picture` |

**Inspect: Fix artwork dimensions** applies to **FLAC** only (other formats skip this).

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

## Development / tests

```bash
source venv/bin/activate
pip install -r requirements-dev.txt
pytest tests/ -v
```

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
