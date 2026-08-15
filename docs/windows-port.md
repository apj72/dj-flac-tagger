# Windows Port — DJ MetaManager

Notes on what's needed to ship a Windows build. Written August 2026.

## Current state

Most of the codebase is already cross-platform. Flask, mutagen, all scrapers,
the entire HTML/CSS/JS frontend, and the metadata pipeline work unchanged on
Windows. The work is mostly around packaging, a few macOS-specific calls, and
testing.

## Estimated effort

**2-3 days** for someone with a Windows machine, assuming no major WebView
rendering surprises. The riskiest unknown is pywebview on Edge WebView2.

---

## What needs changing

### 1. trash_file() — will crash on Windows (HIGH)

`audio.py` lines 264-270 calls `osascript` to move files to Trash via Finder.
No platform guard — it will raise `FileNotFoundError` on Windows.

**Fix:** Add platform branching. Use the `send2trash` package on all platforms
(it handles macOS Trash and Windows Recycle Bin), or use `ctypes` to call
`SHFileOperationW` on Windows. Called from `app.py` lines 1453 and 1793.

### 2. Bundled ffmpeg path detection (HIGH)

`config.py` lines 189-203 (`_prepend_bundled_ffmpeg_to_path`) looks for:
- A directory called `ffmpeg-mac/bin` (macOS-specific name)
- An executable called `ffmpeg` (Windows needs `ffmpeg.exe`)
- Uses `os.access(path, os.X_OK)` which behaves differently on Windows

**Fix:**
- Add `ffmpeg-win/bin` as a search path alongside `ffmpeg-mac/bin`
- Check for both `ffmpeg` and `ffmpeg.exe`
- Bundle the Windows ffmpeg static build (from gyan.dev or BtbN GitHub releases)

### 3. PyInstaller spec file (HIGH)

`packaging/dj-mm.spec` uses `BUNDLE()` to create a `.app` — macOS only.

**Fix:** Create `packaging/dj-mm-win.spec` that produces an `.exe` via `EXE()`
only (no `BUNDLE`). Key differences:
- Replace `.icns` icon with `.ico` (create `DJMetaManager.ico`)
- Remove `bundle_identifier` and `codesign_identity`
- Adjust data file paths for Windows separators
- Include `ffmpeg.exe` and `ffprobe.exe` in the bundle

### 4. Build script (MEDIUM)

`build.sh` is bash-only, installs to `/Applications`, seeds
`~/Library/Application Support`. Not usable on Windows.

**Fix:** Create `build.bat` or `build.ps1` that:
- Activates the venv
- Runs PyInstaller with the Windows spec
- Optionally creates an installer (Inno Setup or NSIS — see section below)

### 5. Start/stop scripts (MEDIUM)

`start.sh` and `stop.sh` use `lsof`, `nohup`, `kill` — all Unix-only. These
are dev convenience scripts.

**Fix:** Create `start.bat` / `stop.bat` (or PowerShell equivalents):
- `start.bat`: activate venv, run `python app.py` (or `start /b python app.py`)
- `stop.bat`: `taskkill /f /im python.exe` or find the specific PID

### 6. post_extract_open_app() (MEDIUM)

`config.py` lines 476-484: the Windows branch uses `os.startfile()` which opens
the file's default handler but ignores the `app_name` parameter. So "open in
Platinum Notes" won't open Platinum Notes specifically — it'll open whatever
handles `.flac` files.

**Fix:** Use `subprocess.Popen([app_path, file_path])` on Windows if the user
has configured a specific app path. Could add a settings field for the full
executable path on Windows.

### 7. Windows installer (MEDIUM)

macOS has `build_macos_dmg.sh` for distribution. Windows needs an equivalent.

**Options (pick one):**
- **Inno Setup** — free, simple, widely used. Produces a `.exe` installer.
  Handles Start Menu shortcuts, uninstaller, file associations.
- **NSIS** — also free, more flexible but more verbose config.
- **MSIX** — modern Windows packaging, can be distributed via Microsoft Store.
  More complex to set up.

Recommendation: **Inno Setup** — simplest path, most documentation, good enough
for indie distribution.

### 8. Default directory paths (LOW)

`config.py` defaults to `~/DJ-Mixes` and `~/Music/DJ-library`. On Windows,
`os.path.expanduser("~")` resolves to `C:\Users\<name>` which works, but
`~/Music` maps to `C:\Users\<name>\Music` which is the correct Windows Music
folder. This is fine as-is — users can override in Settings.

### 9. Icon format (LOW)

The app uses `DJMetaManager.icns` (macOS format). Windows needs `.ico`.

**Fix:** Convert with ImageMagick or a tool like icoutils:
```bash
magick DJMetaManager.icns -resize 256x256 DJMetaManager.ico
```
Include multiple sizes (16, 32, 48, 256) in the `.ico` for best results.

---

## What already works (no changes needed)

- **Flask web app** — fully cross-platform
- **All scrapers** — Discogs, Apple Music, Bandcamp, SoundCloud, Beatport
- **mutagen** — audio tagging works on all platforms
- **All HTML/CSS/JS** — browser-rendered, platform-independent
- **pywebview** — supports Windows via Edge WebView2 (needs runtime installed;
  most Windows 10/11 machines have it)
- **writable_app_data_dir()** — already has Windows path logic using
  `LOCALAPPDATA` (`config.py` lines 159-161)
- **Path handling** — codebase uses `os.path.join()`, `Path()`, `os.path.normpath()`
  consistently
- **Apple Music capture** — macOS-only but correctly guarded with
  `sys.platform != "darwin"` checks. Simply won't appear on Windows. No crash.
- **subprocess calls to ffmpeg/ffprobe** — use bare command names which
  `shutil.which()` and PATH resolve correctly on Windows

---

## Suggested approach

1. **Start with `python app.py` in a browser on Windows** — validates 90% of
   functionality without touching packaging. Use a VM, Parallels, or a friend's
   PC.

2. **Fix the three HIGH items** (trash_file, ffmpeg paths, PyInstaller spec) —
   this gets a working `.exe` build.

3. **Test pywebview on Windows** — this is the biggest unknown. Edge WebView2
   rendering might have CSS/JS quirks vs Safari WebKit. Test all pages,
   especially dark mode, the player bar, and any CSS `backdrop-filter` usage.

4. **Create an Inno Setup installer** — gives users a proper install/uninstall
   experience with Start Menu integration.

5. **CI/CD (optional)** — GitHub Actions has Windows runners. Could automate the
   Windows build alongside the macOS build.

---

## Edge cases to test on Windows

- Long file paths (Windows 260-char limit vs macOS ~1024)
- Unicode filenames (accented characters, CJK in artist/title)
- Spaces in the install path (`C:\Program Files\DJ MetaManager`)
- File locking (Windows locks open files more aggressively than macOS)
- Firewall prompts (Flask binding to localhost may trigger Windows Defender)
- High-DPI displays (pywebview + Edge WebView2 scaling)
