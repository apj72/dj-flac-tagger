# Stitch design briefs — DJ MetaManager

Use these sections with [Stitch](https://stitch.withgoogle.com/): one screen per page, or merge **Global** into every prompt. Copy the block under each heading.

---

## Global (include in every page or as project context)

**Product:** “DJ MetaManager” — pro-sumer DJ library tool. **Tagline / subtitle under title:** `Multi-format audio · Tag · Artwork`.  
**Layout:** Centered app column (~780px most pages; **Inspect** is wider, ~max 1320px) on a **very dark** background. **Card** sections with rounded corners, subtle border, raised surface. **Top header:** app title (gradient: purple → mint/teal on dark), subtitle, then **horizontal tab bar** in a **pill** container: **Extract** | **Fix Metadata** | **Inspect** | **Normalise** | **Settings** (one active, clear selected state).  
**Aesthetic direction:** **Dark mode**, confident and calm — control-room / studio, not a generic admin UI. **Typography:** system UI sans (-apple-system / Segoe / Roboto). **Accent pattern:** **Primary actions** = mint/teal; **Secondary** = muted blue-gray; **Emphasis/Extract** = purple or accent variant. Meters and progress = horizontal bars with numeric readouts. **Density:** comfortable for long sessions; clear hierarchy: numbered steps, hint text in smaller muted color. **Accessibility:** sufficient contrast, focus states on tabs and buttons, labels tied to fields.

**User:** A DJ or collector who values **clarity, meters (LUFS/peak), and traceability** of metadata sources.

---

## Page 1 — Extract (default home, main workflow)

**Goal:** Turn a **video recording** (MKV/MP4/MOV) into a **tagged audio file** in the user’s chosen format, with optional loudness normalisation, Platinum Notes handoff, and optional trash of the source.

**Structure (vertical cards, top to bottom):**

1. **Step 1 — Source file**  
   - Short hint: folders / extract format / Platinum Notes live on **Settings** (link).  
   - **Path row:** text field (placeholder e.g. `~/DJ-Mixes`) + **Browse** (secondary).  
   - **File list** area (clickable files; video extensions implied).  
   - After selection: **probe** strip (file info summary).  
   - **“Audio levels”** panel: heading “Audio Levels”; three **meter rows** — **LUFS**, **Peak**, **Mean** — each: label, **horizontal bar** (fill shows level), **numeric value** on the right.  
   - **Verdict** line (short colour-coded or muted text, e.g. “healthy / hot / quiet” style summary).

2. **Step 2 — Track info**  
   - Label: combined music services + URL.  
   - **URL** field (full width) — Bandcamp, Discogs, Apple Music, Spotify, generic URL.  
   - **“Or track name”** text field.  
   - **Primary button:** “Fetch Metadata”.  
   - **Status** area (inline message, success/warning after fetch — hidden when idle).

3. **Optional block — “Select track”** (for multi-track releases)  
   - Card with **music note** icon in title.  
   - Scrollable or stacked **track list** (radio or selectable cards for each track title).

4. **Step 3 — Metadata**  
   - Section title + small **“Clear all”** secondary.  
   - **Two columns on desktop, stacked on mobile:**  
     - **Left / top:** **Artwork** — large **square** placeholder (300×300 feel) with “No artwork” state; under it **Artwork URL** + **“Load Artwork”** (secondary, small).  
     - **Right / bottom:** form fields: **Title, Artist, Album Artist, Album**; then **Year** and **Genre** in one row; **Label** and **Cat No.** in one row; **Comment** (multiline, 2 rows).

5. **Step 4 — Extract & tag**  
   - Hint about **Settings → extract format** and **Platinum Notes “Match input format”** (inline code for `_PN`).  
   - **Checkboxes:**  
     - Normalise (EBU R128, LUFS from Settings)  
     - Move source video to Bin (default **on**)  
     - Open in Platinum Notes (requires app name in Settings)  
     - Watch for PN output and re-apply tags (up to 3 min)  
   - **Primary CTA (accent):** “Extract & Apply Tags” — **disabled** until flow allows.  
   - **Result** panel: success path with paths, or errors (expandable, calm styling).

6. **Processing log (collapsible)**  
   - Header: **“Processing log”** + book icon + **chevron** (expand/collapse).  
   - When open: short hint (re-tag, metadata URL, folder selection).  
   - **Actions:** “Re-tag selected”, “Re-tag all in folder” (secondary/primary sm), **Target folder** field.  
   - **List:** rows = past jobs (title, source URL snippet, kind, checkboxes for selection).  
   - **Re-tag status** message area.

**Wireframe notes for Stitch:** Emphasize **step numbers**, **meters** as key visuals, and **artwork** as a hero tile in the metadata step. Distinguish **primary** (Fetch, Extract) from **secondary** (Browse, Clear, Load Artwork).

---

## Page 2 — Fix Metadata

**Goal:** **Browse** existing audio in a folder, **search** (iTunes + Discogs) or **paste a URL**, edit tags and artwork, **save** to the file (multi-format).

**Structure:**

1. **Step 1 — Select audio file**  
   - Path + **Browse**; file list; below, optional **“current tags”** summary (compact, when file selected).

2. **Step 2 — Search results** (conditional visibility)  
   - Title “Search results”.  
   - Status line.  
   - **Result cards** (album art thumbnail, title, artist, year, “use this” or select affordance).  
   - Hint: “Not what you’re looking for? Paste a URL below.”

3. **Fetch from URL** (always or prominent)  
   - Same services label as Extract.  
   - URL field + **“Fetch metadata”** primary.

4. **Select track** (same pattern as Extract — for multi-disc).

5. **Step 3 — Metadata & artwork**  
   - Same field set as Extract metadata **but** artwork from fetch; **artwork preview** on left, fields on right; **Clear all**.

6. **Step 4 — Save**  
   - **Accent CTA:** “Save tags & artwork” (disabled until valid).  
   - Result / status message.

**Wireframe notes:** Slightly **simpler** than Extract (no video/bin/Platinum). Highlight **search results grid** and **read-only current tags** as optional strip.

---

## Page 3 — Inspect (wider layout)

**Goal:** **Read-only deep view** of one audio file: full tag table, embedded artwork, technical file details, **saved metadata URL** if present, and **“Fix artwork dimensions”** (FLAC only — button + status that may appear in artwork area).

**Structure:**

1. **Select audio file** (same path + Browse + file list; label “Select audio file”).

2. **When a file is selected** — two-column top section (wider page):  
   - **Left card — Metadata:** **Key/value table** (all tags, scrollable; include row “Saved metadata URL” when present, monospace or subtle link style).  
   - **Right card — Artwork:** heading “Artwork”; **large** embedded cover preview; **info** lines (type, size in KB); **“Fix artwork dimensions”** small **primary** button (FLAC) + “Saved / Fixing…” state; empty state: “No artwork embedded”.

3. **Below (full width card) — File details**  
   - Technical block: format, bit depth, sample rate, channels, duration, path, etc. (label/value grid).

**Wireframe notes:** This page should feel like a **diagnostic / lab** view — more **tabular data**, **less** heavy CTA. **Aspect ratio** for cover ~ 1:1 in aside column.

---

## Page 4 — Normalise

**Goal:** **Loudness-normalise** an existing file to EBU R128; output format from Settings; new file next to source with suffix.

**Structure:**

1. **Step 1 — Select audio**  
   - Long **educational** hint (two-pass, tags copied, FLAC 16-bit note, `flac` CLI, MP3/AAC path, output naming `{stem}{suffix}{ext}`) — **visually secondary** (smaller text; optional “learn more” in real UI).  
   - Path + Browse + file list.  
   - Probe / file info strip.  
   - **Same three meters** (LUFS, Peak, Mean) + verdict as **Extract** (reuse visual language).

2. **Step 2 — Normalise**  
   - **Output filename suffix** (default `_LUFS14`, text field, label above).  
   - **CTA (accent):** “Normalise (EBU R128)” — disabled until file ready.  
   - Result / status area.

**Wireframe notes:** **Nearly identical** meters to Extract for consistency. Less total content than Extract — should feel **focused** and a bit more **serious/technical** (loudness engineering).

---

## Page 5 — Settings

**Goal:** System-wide **paths**, **export codec**, **Platinum Notes** integration, **loudness targets** — single save action.

**Structure (single long card):**

- Intro hint: “Paths, extract format, and loudness targets apply across… Save after changes.”
- **Extract & normalise output format** — **dropdown** (FLAC, MP3, AAC/M4A) + sub-hint.  
- **Source folder (OBS recordings)** — text.  
- **Destination folder** (copy of extracted audio) — text.  
- **Platinum Notes — app name** + hint (exact name as in `/Applications`, `open -a`).  
- **Platinum Notes output suffix** (e.g. `_PN`) + hint.  
- **Loudness target (LUFS)** and **True peak (dBTP)** — **side by side** in one row.  
- Paragraph hint (EBU R128, -11.5 vs -14, positive entry ok).  
- **Primary “Save settings”** + **“Saved”** text badge (fades in) beside or after button.

**Wireframe notes:** **Form-heavy**; use clear **grouping** and optional **dividers** between “Format & paths” vs “Platinum Notes” vs “Loudness.” No file lists.

---

## Optional mood line (for Stitch)

> Dark studio UI for a Mac-first DJ app: **purple–teal gradient logotype**, **mint** primary actions, **cards** and **tab pill nav**, **horizontal LUFS/peak meters**, **square artwork**, and **numbered workflow steps** — precise, low-noise, professional.

---

## License

This document is part of the DJ MetaManager project (MIT).
