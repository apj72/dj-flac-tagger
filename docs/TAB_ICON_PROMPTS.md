# Tab icon prompts (image generation)

Use these with your image model (e.g. Google **Imagen / Gemini** image features). Export **square PNG or SVG**, **transparent background**, **single colour** silhouette or **monoline** stroke so the app can tint icons via CSS mask. Recommended export: **512×512** or **256×256**, centered, safe padding ~15%.

---

## A. App description (use verbatim in every prompt)

**DJ MetaManager** is a **local desktop-style web app for DJs and music librarians**. It runs in the browser on your own computer, connects to your audio folders on disk, and helps you **extract audio from video recordings** (e.g. OBS captures), **measure and normalise loudness** (EBU R128), **fetch metadata and cover art** from catalogues such as Discogs, Bandcamp, and Apple Music, **edit and save tags** for FLAC/MP3/M4A/OGG, **batch-convert WAV to FLAC**, and **bulk-fix metadata** for many files. The UI is **professional, calm, and technical**—not a consumer music streamer, not childish.

---

## B. Icon / button graphic characteristics (use verbatim in every prompt)

- **Style:** Minimal **monoline** (single stroke weight) **outline** icon, **flat 2D**, no gradients inside the glyph, no 3D, no photorealism, no text letters in the icon.
- **Weight:** Stroke thickness **medium** (clear at 24px), **rounded line caps and joins**.
- **Composition:** **One** readable symbol only, **centered** in the frame; generous margin; **symmetric** where possible.
- **Colour:** **Pure black (#000000)** lines on **fully transparent** background (or solid white silhouette if the tool cannot do strokes—then black on transparent preferred).
- **Framing:** **No** circle, **no** square plate, **no** drop shadow—**glyph only** (the app puts icons in tabs itself).
- **Mood:** **Precise, utility, audio engineering**—similar to **SF Symbols** or **Material Symbols** (outlined), not playful stickers.
- **Exception — WAV → FLAC (§5) only:** You may use a **playful, music-flavoured** line character (bouncier curves, a tiny note or waveform flourish) as described there—still **monoline**, still **no letters or words** in the glyph.

---

## C. One prompt per main tab (title + body)

Copy **A + B + the section below** into one generation request per icon.

### 1 — Extract

**Tab label:** Extract  
**Function:** User picks a **video file** (MKV/MP4/MOV); the app **extracts the audio** to a chosen format (FLAC/MP3/AAC), optionally **normalises loudness**, **fetches metadata**, and **writes a finished library file**.  
**Icon concept:** **Download / export from container**—e.g. a **simple tray or document** with a **downward arrow**, or **film frame + arrow down**, suggesting *pull audio out of a recording*. Do **not** use a generic “play” triangle alone.

---

### 2 — Fix Metadata

**Tab label:** Fix Metadata  
**Function:** User **browses audio files**, **searches** Discogs / Apple / Bandcamp or pastes a **URL**, then **edits tags and artwork** and **saves** to the file (optional **rename** to Artist–Title).  
**Icon concept:** **Tag, label, or metadata card**—e.g. a **price-tag** shape with a **small pencil** or **lines suggesting fields**, or a **document with a tag corner**. Must read as *edit identity of a track*, not *equalizer*.

---

### 3 — Inspect

**Tab label:** Inspect  
**Function:** User **lists files** in a folder and **inspects all embedded tags and artwork** read-only, with options to **fix artwork dimensions** (FLAC).  
**Icon concept:** **Magnifying glass** over a **simple document or list** (glass slightly overlapping a sheet), suggesting *examine details*.

---

### 4 — Normalise

**Tab label:** Normalise  
**Function:** User **analyses loudness** of a file, then **re-encodes** to a target **LUFS / true peak** so the library is **level-consistent**.  
**Icon concept:** **Audio level / balance**—e.g. **three or four vertical bars** of **different heights** in a **straight baseline** (mini spectrum or meter), or a **slider with a waveform**. Avoid a single generic “volume” speaker icon with no meter.

---

### 5 — WAV → FLAC

**Tab label:** WAV → FLAC  
**Function:** User converts **WAV files** to **lossless FLAC** (single file or **bulk** with folder options); source WAVs stay on disk.  
**Icon concept (music + playful, still pro):** This icon should feel **DJ- and studio-adjacent**—clearly about **sound**, not generic “files.” Use **playful expression**: lively curves, a slight **bounce** or **asymmetry**, maybe a **tiny eighth-note**, **headphone cup**, or **compact waveform** merged with a **directional arrow** or **two linked bubbles** (suggesting *raw capture → tidy lossless library*)—**without** spelling “W,” “F,” or any letters (see §B). Think **friendly boutique audio tool**, not corporate clip-art: **one bold readable silhouette**, **single stroke weight**, **rounded joins**, like a **mini party for your library** that still fits a technical app. The story in one glance: **music in, polished lossless audio out**.

---

### 6 — Bulk Fix

**Tab label:** Bulk Fix  
**Function:** User loads **many FLACs** from a folder; the app **fetches match suggestions** in batch and **applies metadata** to checked rows (optional rename).  
**Icon concept:** **Table or rows + magic / batch**—e.g. **three horizontal lines** (list) with a **sparkle** or **small wand**, or **stack of files** with **one checkmark**. Must suggest *many items at once*, not a single file.

---

### 7 — Settings

**Tab label:** Settings  
**Function:** User configures **source/destination paths**, **default extract format**, **LUFS targets**, **Platinum Notes** integration, and **appearance** (light/dark).  
**Icon concept:** **Gear / cog** with **six to eight teeth**, simple outline, centered—universal *settings*.

---

## After generation

1. Save into `static/icons/tabs/` as **`extract.png`**, **`fix-metadata.png`**, **`inspect.png`**, **`normalise.png`**, **`convert.png`** (WAV→FLAC), **`bulk-fix.png`**, **`settings.png`** — **PNG with alpha**. Resize large exports (e.g. `sips -Z 256`) before committing. `mask-image` URLs live in `static/style.css` under `.tab-icon-*`.
2. For **mask** compatibility, artwork should be **filled** or **closed strokes** that read as a **solid silhouette**; very thin hairlines may break when scaled down.

---

## Colour palettes (reference for other UI work, not necessarily embedded in icons)

- **Dark — Obsidian Flux:** background `#0F172A`, primary purple `#A855F7`, teal `#2DD4BF`, blue `#3B82F6`.  
- **Light — Luminous Glass:** background `#F8FAFC`, lavender `#A78BFA`, accent pink `#F472B6`, violet `#8B5CF6`.
