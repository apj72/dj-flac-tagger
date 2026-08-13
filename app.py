import base64
import csv
import difflib
import io
import json
from collections import defaultdict
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime
from pathlib import Path

from flask import Flask, Response, jsonify, request, send_file
import requests  # needed so tests can monkeypatch app_module.requests
import mutagen
from mutagen.flac import FLAC, Picture
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4, MP4Cover
from mutagen.id3 import ID3
from mutagen.oggvorbis import OggVorbis

# ---------------------------------------------------------------------------
# Import all names from submodules for backward compatibility.
# Tests use ``app_module.XXX`` to access functions / constants.
# ---------------------------------------------------------------------------
import config as _config_mod
from config import *      # noqa: F401,F403
from scrapers import *    # noqa: F401,F403
from metadata import *    # noqa: F401,F403
from audio import *       # noqa: F401,F403

# ---------------------------------------------------------------------------
# Redirect config path lookups so test monkeypatching of
# ``app.CONFIG_PATH`` / ``app.LOG_PATH`` / ``app.LOGGED_TRACKS_PATH``
# is seen by functions defined in config.py.
# ---------------------------------------------------------------------------
_config_mod._get_config_path = lambda: CONFIG_PATH      # noqa: F405
_config_mod._get_log_path = lambda: LOG_PATH             # noqa: F405
_config_mod._get_logged_tracks_path = lambda: LOGGED_TRACKS_PATH  # noqa: F405

# ---------------------------------------------------------------------------
# Flask application
# ---------------------------------------------------------------------------
app = Flask(__name__, static_folder=str(bundle_base_path() / "static"))  # noqa: F405


# ---------------------------------------------------------------------------
# Apple Music Now Playing capture
# ---------------------------------------------------------------------------

def _run_osascript(script, timeout=10):
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True, text=True, timeout=timeout,
    )
    return result.stdout.strip(), result.stderr.strip(), result.returncode


_APPLE_MUSIC_APPLESCRIPT = '''\
on escJSON(s)
    set o to ""
    set q to ASCII character 34
    repeat with c in characters of (s as text)
        set ch to contents of c
        if ch is "\\\\" then
            set o to o & "\\\\\\\\"
        else if ch is q then
            set o to o & "\\\\" & q
        else if ch is (ASCII character 10) then
            set o to o & "\\\\n"
        else if ch is (ASCII character 13) then
            set o to o & "\\\\r"
        else if ch is (ASCII character 9) then
            set o to o & "\\\\t"
        else
            set o to o & ch
        end if
    end repeat
    return o
end escJSON

tell application "Music"
    if not running then
        return "{\\"error\\": \\"not_running\\"}"
    end if
    set ps to (player state as text)
    if ps is "stopped" then
        return "{\\"error\\": \\"nothing_playing\\", \\"playbackState\\": \\"stopped\\"}"
    end if
    set pp to player position
    set ct to current track
    set tTitle to my escJSON(name of ct)
    set tArtist to my escJSON(artist of ct)
    set tAlbum to my escJSON(album of ct)
    try
        set tAlbumArtist to my escJSON(album artist of ct)
    on error
        set tAlbumArtist to ""
    end try
    try
        set tDuration to duration of ct
    on error
        set tDuration to 0
    end try
    try
        set tTrackNum to track number of ct
    on error
        set tTrackNum to 0
    end try
    try
        set tDiscNum to disc number of ct
    on error
        set tDiscNum to 0
    end try
    try
        set tGenre to my escJSON(genre of ct)
    on error
        set tGenre to ""
    end try
    try
        set tYear to (year of ct) as text
    on error
        set tYear to ""
    end try
    try
        set tComposer to my escJSON(composer of ct)
    on error
        set tComposer to ""
    end try
    try
        set tPersistentId to persistent ID of ct
    on error
        set tPersistentId to ""
    end try
    return "{\\"playbackState\\": \\"" & ps & "\\", \\"playerPosition\\": " & pp & ", \\"persistentId\\": \\"" & tPersistentId & "\\", \\"title\\": \\"" & tTitle & "\\", \\"artist\\": \\"" & tArtist & "\\", \\"album\\": \\"" & tAlbum & "\\", \\"albumArtist\\": \\"" & tAlbumArtist & "\\", \\"genre\\": \\"" & tGenre & "\\", \\"year\\": \\"" & tYear & "\\", \\"composer\\": \\"" & tComposer & "\\", \\"duration\\": " & tDuration & ", \\"trackNumber\\": " & tTrackNum & ", \\"discNumber\\": " & tDiscNum & "}"
end tell
'''


def capture_apple_music_now_playing():
    if sys.platform != "darwin":
        raise RuntimeError("Apple Music capture is only available on macOS")

    try:
        stdout, stderr, rc = _run_osascript(_APPLE_MUSIC_APPLESCRIPT, timeout=10)
    except subprocess.TimeoutExpired:
        raise RuntimeError("Timed out communicating with Music.app")
    except FileNotFoundError:
        raise RuntimeError("osascript not found — is this macOS?")

    if rc != 0:
        if "-1743" in stderr:
            raise PermissionError(
                "DJ MetaManager needs permission to read the current track from Music. "
                "Enable access in System Settings → Privacy & Security → Automation."
            )
        raise RuntimeError(f"AppleScript error: {stderr}")

    if not stdout:
        raise RuntimeError("No response from Music.app")

    try:
        raw = json.loads(stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"Unexpected response from Music.app: {stdout[:200]}")

    if "error" in raw:
        err = raw["error"]
        if err == "not_running":
            raise RuntimeError("Music is not running.")
        if err == "nothing_playing":
            raise RuntimeError("Nothing is currently playing in Music.")
        raise RuntimeError(f"Music error: {err}")

    title = raw.get("title", "")
    if not title:
        raise RuntimeError("Music returned a track with no title.")

    return {
        "id": str(uuid.uuid4()),
        "source": "apple_music_now_playing",
        "capturedAt": datetime.now().isoformat(),
        "appleMusicPersistentId": raw.get("persistentId") or None,
        "playbackState": raw.get("playbackState", "unknown"),
        "playerPosition": raw.get("playerPosition", 0),
        "metadata": {
            "title": title,
            "artist": raw.get("artist", ""),
            "album": raw.get("album", ""),
            "albumArtist": raw.get("albumArtist", ""),
            "genre": raw.get("genre", ""),
            "year": raw.get("year", ""),
            "composer": raw.get("composer", ""),
            "duration": raw.get("duration", 0),
            "trackNumber": raw.get("trackNumber") or None,
            "discNumber": raw.get("discNumber") or None,
        },
    }


# ---------------------------------------------------------------------------
# Helpers tightly coupled to Flask or multiple modules
# ---------------------------------------------------------------------------

def _read_wav_embedded_tags(path: str) -> dict:
    """
    Best-effort title / artist / album from a .wav (RIFF/BWF, ID3-in-WAV, etc.).
    """
    out = {"title": "", "artist": "", "album": ""}
    if not path or not os.path.isfile(path):
        return out
    if Path(path).suffix.lower() != ".wav":
        return out
    try:
        audio = mutagen.File(path, easy=True)
    except (OSError, mutagen.MutagenError, KeyError, TypeError, ValueError):
        return out
    if audio is None:
        return out
    for vkey, outkey in (("title", "title"), ("artist", "artist"), ("album", "album")):
        try:
            vals = audio.get(vkey, [])
        except (AttributeError, KeyError, TypeError):
            continue
        if vals and str(vals[0]).strip():
            out[outkey] = str(vals[0]).strip()
    return out


def bulk_fix_search_info_for_flac(flac_path: str) -> dict:
    """
    Search query and hints for bulk fix: same filename rules as search_query_from_ableton_stem,
    optionally refined when a same-name .wav exists beside the FLAC with both artist+title in tags
    (typical when the DAW or recorder wrote metadata). Sibling with only one field can fill
    title_hint/artist_hint without replacing the main filename-based query.
    """
    p = os.path.realpath((flac_path or "").strip())
    stem = Path(p).stem
    base = search_query_from_ableton_stem(stem)  # noqa: F405
    wav_sibling = str(Path(p).with_suffix(".wav"))
    wt = _read_wav_embedded_tags(wav_sibling) if os.path.isfile(wav_sibling) else {
        "title": "", "artist": "", "album": ""
    }
    wa = (wt.get("artist") or "").strip()
    wti = (wt.get("title") or "").strip()
    wal = (wt.get("album") or "").strip()
    merged = {**base}
    cfg_bf = load_config()  # noqa: F405
    peel_lines = normalize_fix_retain_filename_suffixes(  # noqa: F405
        cfg_bf.get("fix_retain_filename_suffixes"),
    )
    merged["wav_sibling"] = wav_sibling if os.path.isfile(wav_sibling) else ""
    tag_blob = {k: v for k, v in {"artist": wa, "title": wti, "album": wal}.items() if v}
    merged["wav_tags"] = tag_blob or None
    if wa and wti:
        q = re.sub(r"\s+", " ", f"{wa} {wti}").strip()
        qp, _ = peel_fix_retain_suffixes(q, peel_lines)  # noqa: F405
        merged["query"] = qp.strip()
        wtp, _ = peel_fix_retain_suffixes(wti, peel_lines)  # noqa: F405
        wap, _ = peel_fix_retain_suffixes(wa, peel_lines)  # noqa: F405
        merged["title_hint"] = wtp.strip()
        merged["artist_hint"] = wap.strip()
    else:
        if wti and not (merged.get("title_hint") or "").strip():
            wtp, _ = peel_fix_retain_suffixes(wti, peel_lines)  # noqa: F405
            merged["title_hint"] = wtp.strip()
        if wa and not (merged.get("artist_hint") or "").strip():
            wap, _ = peel_fix_retain_suffixes(wa, peel_lines)  # noqa: F405
            merged["artist_hint"] = wap.strip()
    return _scrub_bulk_search_hints_dict(merged, filename_stem=stem)  # noqa: F405


def _best_track_in_list(tracklist: list, title_hint: str) -> dict:
    if not tracklist:
        return None
    hint = re.sub(r"\s+", " ", (title_hint or "").lower().strip())
    if not hint:
        return tracklist[0]
    best = None
    best_score = 0.0
    for tr in tracklist:
        tt = re.sub(r"\s+", " ", (tr.get("title") or "").lower().strip())
        if not tt:
            continue
        s = difflib.SequenceMatcher(None, hint, tt).ratio()
        if hint in tt or tt in hint:
            s = max(s, 0.88)
        if s > best_score:
            best_score = s
            best = tr
    if best and best_score >= 0.32:
        return best
    return tracklist[0]


def _resolve_metadata_track_hint(meta: dict, track_name: str) -> None:
    """Use filename-derived track title to pick a track on multi-track releases (mutates meta)."""
    if not meta or not (track_name or "").strip():
        return
    track_name = track_name.strip()
    tl = meta.get("tracklist") or []
    if len(tl) > 1:
        best = _best_track_in_list(tl, track_name)
        if best:
            meta["title"] = (best.get("title") or "").strip()
            pos = (best.get("position") or "").strip()
            alb = (meta.get("album") or "").strip()
            if pos and alb:
                meta["comment"] = f"{pos} — {alb}"
    elif len(tl) == 1 and not (meta.get("title") or "").strip():
        meta["title"] = (tl[0].get("title") or "").strip()
    if not (meta.get("title") or "").strip():
        meta["title"] = track_name


def _metadata_from_url(url: str) -> dict:
    meta = {}
    if not (url or "").strip():
        return meta
    try:
        if "bandcamp.com" in url:
            meta = scrape_bandcamp(url)  # noqa: F405
        elif "discogs.com" in url:
            meta = fetch_discogs(url)  # noqa: F405
        elif "music.apple.com" in url:
            meta = scrape_apple_music(url)  # noqa: F405
        elif "spotify.com" in url or "spotify.link" in url:
            meta = scrape_spotify(url)  # noqa: F405
        elif "soundcloud.com" in url.lower():
            meta = scrape_soundcloud(url)  # noqa: F405
        elif "beatport.com" in url.lower() and "/track/" in url.lower():
            meta = scrape_beatport(url)  # noqa: F405
        else:
            meta = scrape_generic(url)  # noqa: F405
    except Exception as e:
        meta = {"_warning": f"Scrape failed: {e}"}
    return meta


def _retag_file_from_source_url(
    filepath: str,
    source_url: str,
    title_hint: str,
    rename_to_tags: bool,
    record_in_log: bool,
) -> dict:
    meta = _metadata_from_url(source_url)
    th = (title_hint or "").strip()
    if th:
        _resolve_metadata_track_hint(meta, th)
    if not (meta.get("title") or "").strip() and th:
        meta["title"] = th

    mcopy = {k: v for k, v in meta.items() if not k.startswith("_") and k != "tracklist" and k != "source"}
    for drop in ("artwork_url",):
        mcopy.pop(drop, None)
    for key, val in list(mcopy.items()):
        if val is None or val == "":
            del mcopy[key]
    if not mcopy.get("title") and not mcopy.get("artist") and not mcopy.get("album"):
        err = (meta.get("_warning") or "No usable metadata (title, artist, or album) from URL.").strip()
        return {"status": "error", "reason": err}

    artwork_url = (meta.get("artwork_url") or "").strip()
    artwork_bytes, artwork_mime = None, None
    if artwork_url:
        try:
            artwork_bytes, artwork_mime = fetch_artwork(artwork_url)  # noqa: F405
        except Exception as e:
            return {"status": "error", "reason": f"artwork: {e}"}

    su = (source_url or "").strip()
    if su:
        mcopy["source_url"] = su

    planned_new_name = None
    if rename_to_tags:
        ext = Path(filepath).suffix.lower() or ".flac"
        retained = _retained_suffix_from_filepath(filepath)  # noqa: F405
        planned_new_name = _basename_from_artist_title_for_rename(  # noqa: F405
            mcopy.get("artist", ""),
            mcopy.get("title", ""),
            ext,
            retained_suffix=retained,
        )
        if not planned_new_name:
            return {
                "status": "error",
                "reason": "Rename: need a title or artist in fetched metadata, or turn off rename.",
            }
        dest_dir = os.path.dirname(filepath)
        candidate = os.path.join(dest_dir, planned_new_name)
        if os.path.basename(filepath) != planned_new_name and os.path.exists(candidate):
            try:
                if not os.path.samefile(filepath, candidate):
                    return {
                        "status": "error",
                        "reason": f"Target filename exists: {planned_new_name}",
                    }
            except (OSError, FileNotFoundError):
                return {"status": "error", "reason": f"Target filename exists: {planned_new_name}"}

    try:
        apply_metadata(filepath, mcopy, artwork_bytes, artwork_mime)  # noqa: F405
    except Exception as e:
        return {"status": "error", "reason": str(e)}

    out_path = filepath
    renamed = False
    if rename_to_tags and planned_new_name:
        dest_dir = os.path.dirname(filepath)
        candidate = os.path.join(dest_dir, planned_new_name)
        if os.path.basename(filepath) != planned_new_name:
            try:
                os.rename(filepath, candidate)
                out_path = candidate
                renamed = True
            except OSError as e:
                return {
                    "status": "error",
                    "reason": f"Tags saved, rename failed: {e}",
                }

    if record_in_log and su:
        log_extraction({  # noqa: F405
            "kind": "fix",
            "filename": os.path.basename(out_path),
            "output_path": out_path,
            "target_path": out_path,
            "metadata": {k: v for k, v in mcopy.items() if k != "source_url"},
            "artwork_url": artwork_url,
            "metadata_source_url": su,
            "metadata_source_type": infer_metadata_source_type(su),  # noqa: F405
        })
    return {"status": "ok", "filepath": out_path, "renamed": renamed}


def _iter_flac_paths(root_resolved: str, recursive: bool):
    if not os.path.isdir(root_resolved):
        return
    if recursive:
        for dirpath, _dirnames, filenames in os.walk(root_resolved):
            for fn in sorted(filenames):
                if fn.startswith("."):
                    continue
                if not fn.lower().endswith(".flac"):
                    continue
                p = os.path.join(dirpath, fn)
                try:
                    if os.path.isfile(p):
                        yield p
                except OSError:
                    continue
    else:
        try:
            for f in sorted(Path(root_resolved).iterdir()):
                if f.is_file() and not f.name.startswith(".") and f.suffix.lower() == ".flac":
                    yield str(f)
        except OSError:
            return


def _iter_audio_paths(root_resolved: str, recursive: bool):
    if not os.path.isdir(root_resolved):
        return
    exts = AUDIO_EXTENSIONS  # noqa: F405
    if recursive:
        for dirpath, _dirnames, filenames in os.walk(root_resolved):
            for fn in sorted(filenames):
                if fn.startswith("."):
                    continue
                if not any(fn.lower().endswith(ext) for ext in exts):
                    continue
                p = os.path.join(dirpath, fn)
                try:
                    if os.path.isfile(p):
                        yield p
                except OSError:
                    continue
    else:
        try:
            for f in sorted(Path(root_resolved).iterdir()):
                if f.is_file() and not f.name.startswith(".") and f.suffix.lower() in exts:
                    yield str(f)
        except OSError:
            return


def _normalize_search_source(raw: str) -> str:
    """Return apple_music | discogs | bandcamp | soundcloud | beatport, or '' for combined search."""
    s = (raw or "").strip().lower()
    if s in ("apple", "apple_music", "itunes"):
        return "apple_music"
    if s == "discogs":
        return "discogs"
    if s == "bandcamp":
        return "bandcamp"
    if s in ("soundcloud", "sc"):
        return "soundcloud"
    if s in ("beatport", "bp"):
        return "beatport"
    return ""


def _normalize_resolved_path(p):
    return os.path.normpath(os.path.abspath(resolve(p)))  # noqa: F405


def _assert_browse_dir_video_file(filepath, base_dir):
    """Ensure filepath is a real video recording sitting directly in base_dir (same rules as /api/browse)."""
    if not filepath or not base_dir:
        return False, "Missing path or folder"
    try:
        fp = _normalize_resolved_path(filepath)
        bd = _normalize_resolved_path(base_dir)
    except (OSError, TypeError, ValueError):
        return False, "Invalid path"
    if not os.path.isdir(bd):
        return False, "Folder not found"
    if not os.path.isfile(fp):
        return False, "File not found"
    if os.path.dirname(fp) != bd:
        return False, "File must be in the listed folder"
    if Path(fp).suffix.lower() not in VIDEO_SOURCE_EXTENSIONS:  # noqa: F405
        return False, "Not a supported video recording type"
    return True, None


_LOSSLESS_CONVERT_EXTS = (".wav", ".aiff", ".aif")


def _iter_lossless_paths(root_resolved: str, recursive: bool):
    """Yield every .wav / .aiff / .aif file under root (non-hidden)."""
    if not os.path.isdir(root_resolved):
        return
    if recursive:
        for dirpath, _dirnames, filenames in os.walk(root_resolved):
            for fn in sorted(filenames):
                if fn.startswith("."):
                    continue
                if not any(fn.lower().endswith(e) for e in _LOSSLESS_CONVERT_EXTS):
                    continue
                p = os.path.join(dirpath, fn)
                try:
                    if os.path.isfile(p):
                        yield p
                except OSError:
                    continue
    else:
        try:
            for f in sorted(Path(root_resolved).iterdir()):
                if f.is_file() and not f.name.startswith(".") and f.suffix.lower() in _LOSSLESS_CONVERT_EXTS:
                    yield str(f)
        except OSError:
            return


def _iter_wav_paths(root_resolved: str, recursive: bool):
    """Yield every .wav file under root (non-hidden). root_resolved must be real. """
    if not os.path.isdir(root_resolved):
        return
    if recursive:
        for dirpath, _dirnames, filenames in os.walk(root_resolved):
            for fn in sorted(filenames):
                if fn.startswith("."):
                    continue
                if not fn.lower().endswith(".wav"):
                    continue
                p = os.path.join(dirpath, fn)
                try:
                    if os.path.isfile(p):
                        yield p
                except OSError:
                    continue
    else:
        try:
            for f in sorted(Path(root_resolved).iterdir()):
                if f.is_file() and not f.name.startswith(".") and f.suffix.lower() == ".wav":
                    yield str(f)
        except OSError:
            return


def _list_lossless_paths_sorted(root_resolved: str, recursive: bool) -> list:
    """Stable sorted list of all .wav/.aiff paths (for batch offset/limit)."""
    return sorted((p for p in _iter_lossless_paths(root_resolved, recursive)), key=lambda p: p.lower())


def _list_wav_paths_sorted(root_resolved: str, recursive: bool) -> list:
    """Stable sorted list of all .wav paths (for batch offset/limit)."""
    return sorted((p for p in _iter_wav_paths(root_resolved, recursive)), key=lambda p: p.lower())


def _bulk_flac_output_path(wav_path: str, root_resolved: str, output_mode: str, dest_resolved) -> str:
    """For destination, mirror the folder tree under dest (rel. to root) so names don't collide."""
    if output_mode == "same":
        return str(Path(wav_path).with_suffix(".flac"))
    if not dest_resolved:
        return str(Path(wav_path).with_suffix(".flac"))
    try:
        rel = os.path.relpath(wav_path, start=root_resolved)
    except ValueError:
        rel = os.path.basename(wav_path)
    if rel.startswith(".."):
        rel = os.path.basename(wav_path)
    out = os.path.join(dest_resolved, os.path.splitext(rel)[0] + ".flac")
    return os.path.normpath(out)


def _serve_embedded_artwork(filepath):
    if not filepath or not os.path.isfile(filepath):
        return jsonify({"error": "File not found"}), 404

    try:
        filepath = _validate_path_in_allowed_dirs(filepath)  # noqa: F405
    except ValueError as e:
        return jsonify({"error": str(e)}), 403

    ext = os.path.splitext(filepath)[1].lower()

    try:
        if ext == ".flac":
            audio = FLAC(filepath)
            if audio.pictures:
                pic = audio.pictures[0]
                return app.response_class(pic.data, mimetype=pic.mime)
        elif ext == ".mp3":
            audio = MP3(filepath, ID3=ID3)
            if audio.tags:
                apics = audio.tags.getall("APIC")
                if apics:
                    return app.response_class(apics[0].data, mimetype=apics[0].mime)
        elif ext in (".m4a", ".mp4", ".aac"):
            audio = MP4(filepath)
            if audio.tags and audio.tags.get("covr"):
                covr = audio.tags["covr"][0]
                mime = "image/jpeg" if covr.imageformat == MP4Cover.FORMAT_JPEG else "image/png"
                return app.response_class(bytes(covr), mimetype=mime)
        elif ext in (".aiff", ".aif"):
            from mutagen.aiff import AIFF as _AIFF
            audio = _AIFF(filepath)
            if audio.tags:
                apics = audio.tags.getall("APIC")
                if apics:
                    return app.response_class(apics[0].data, mimetype=apics[0].mime)
        elif ext in (".ogg", ".oga"):
            audio = OggVorbis(filepath)
            pics = audio.get("metadata_block_picture", [])
            if pics:
                pic = Picture(base64.b64decode(pics[0]))
                return app.response_class(pic.data, mimetype=pic.mime)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify({"error": "No embedded artwork"}), 404


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return app.send_static_file("index.html")


@app.route("/fix")
def fix_page():
    return app.send_static_file("fix.html")


@app.route("/normalise")
def normalise_page():
    return app.send_static_file("normalise.html")


@app.route("/settings")
def settings_page():
    return app.send_static_file("settings.html")


@app.route("/convert")
def convert_wav_page():
    return app.send_static_file("convert.html")


@app.route("/api/search")
def search():
    """Search iTunes, Discogs, Bandcamp, SoundCloud, and Beatport for a track by query string.

    Query params:
      q — search text (required for non-empty results)
      source — optional: apple_music (aliases: apple, itunes), discogs, bandcamp, soundcloud (sc), beatport.
               When set, only that catalogue is queried.
      limit — optional max hits per source (default 3 when source is set, else ignored for combined)
    """
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"results": []})

    source_key = _normalize_search_source(request.args.get("source", ""))
    if source_key:
        try:
            lim = int(request.args.get("limit", 3))
        except (TypeError, ValueError):
            lim = 3
        lim = max(1, min(lim, 25))
        if source_key == "apple_music":
            results = search_itunes(q, limit=lim)  # noqa: F405
        elif source_key == "discogs":
            results = search_discogs(q, limit=lim)  # noqa: F405
        elif source_key == "soundcloud":
            results = search_soundcloud(q, limit=lim)  # noqa: F405
        elif source_key == "beatport":
            results = search_beatport(q, limit=lim)  # noqa: F405
        else:
            results = search_bandcamp(q, limit=lim)  # noqa: F405
        return jsonify({"results": results})

    itunes = search_itunes(q, limit=8)  # noqa: F405
    discogs = search_discogs(q, limit=5)  # noqa: F405
    bandcamp = search_bandcamp(q, limit=6)  # noqa: F405
    soundcloud = search_soundcloud(q, limit=6)  # noqa: F405
    beatport = search_beatport(q, limit=5)  # noqa: F405

    # De-dupe by title + artist (or album for Discogs) + source so the same work can appear
    # on Apple, Discogs, Bandcamp, and SoundCloud for validation.
    seen = set()
    combined = []
    for r in itunes + discogs + bandcamp + soundcloud + beatport:
        key = (
            (r.get("title", "") or "").lower().strip(),
            (r.get("artist") or r.get("album") or "").lower().strip(),
            (r.get("source") or "").lower().strip(),
        )
        if key in seen:
            continue
        seen.add(key)
        combined.append(r)

    return jsonify({"results": combined})


@app.route("/bulk-fix")
def bulk_fix_page():
    return app.send_static_file("bulk-fix.html")


@app.route("/api/bulk-fix/scan", methods=["GET"])
def bulk_fix_scan():
    """List a slice of .flac files with parsed search query from each filename (for batch metadata)."""
    root = (request.args.get("path") or request.args.get("dir") or "").strip()
    if not root:
        return jsonify({"error": "path or dir query parameter required"}), 400
    try:
        off = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        off = 0
    try:
        lim = int(request.args.get("limit", 25))
    except (TypeError, ValueError):
        lim = 25
    lim = max(1, min(lim, 200))
    recursive = request.args.get("recursive", "1").lower() in ("1", "true", "yes", "on")
    try:
        root_r = os.path.realpath(resolve(root))  # noqa: F405
    except (OSError, TypeError) as e:
        return jsonify({"error": str(e)}), 400
    if not os.path.isdir(root_r):
        return jsonify({"error": f"Not a directory: {root_r}"}), 404
    all_paths = list(_iter_flac_paths(root_r, recursive))
    # Deduplicate exact paths (defensive) while preserving order
    all_paths = list(dict.fromkeys(all_paths))
    by_basename = defaultdict(list)
    for p in all_paths:
        by_basename[os.path.basename(p)].append(p)
    total = len(all_paths)
    if off < 0:
        off = 0
    batch = all_paths[off : off + lim]
    batch_basenames = [os.path.basename(p) for p in batch]
    _bc = {}
    for b in batch_basenames:
        _bc[b] = _bc.get(b, 0) + 1
    in_batch_dups = {b for b, c in _bc.items() if c > 1}
    dup_row_count = sum(1 for b in batch_basenames if _bc.get(b, 0) > 1)
    items = []
    for p in batch:
        base = os.path.basename(p)
        sibs = by_basename.get(base) or []
        n = len(sibs)
        other_paths = [x for x in sibs if x != p]
        info = bulk_fix_search_info_for_flac(p)
        items.append({
            "filepath": p,
            "basename": base,
            "query": info["query"],
            "title_hint": info.get("title_hint") or "",
            "artist_hint": info.get("artist_hint") or "",
            "pattern_matched": info.get("pattern_matched", False),
            "wav_sibling": info.get("wav_sibling") or "",
            "wav_tags": info.get("wav_tags"),
            "duplicate_basename": n > 1,
            "same_basename_count": n,
            "same_basename_other_paths": other_paths[:12],
            "duplicate_in_batch": base in in_batch_dups,
        })
    return jsonify({
        "root": root_r,
        "total": total,
        "offset": off,
        "limit": lim,
        "items": items,
        "duplicates_in_batch": dup_row_count,
    })


@app.route("/api/bulk-fix/suggest", methods=["POST"])
def bulk_fix_suggest():
    """For each file path, run the same iTunes + Discogs + Bandcamp + SoundCloud search as /api/search (rate-limited)."""
    data = request.get_json() or {}
    paths = data.get("paths") or data.get("filepaths") or []
    if not isinstance(paths, list):
        return jsonify({"error": "paths must be a list"}), 400
    paths = [p for p in paths if (p or "").strip()]
    if len(paths) > 60:
        return jsonify({"error": "Maximum 60 paths per suggest request (use multiple batches)."}), 400
    delay = 0.12
    items = []
    for p in paths:
        p = p.strip()
        if not p or not os.path.isfile(p):
            items.append({
                "filepath": p,
                "query": "",
                "results": [],
                "error": "File not found",
            })
            time.sleep(delay)
            continue
        info = bulk_fix_search_info_for_flac(p)
        q = (info.get("query") or "").strip()
        if not q:
            items.append({
                "filepath": p,
                "query": "",
                "results": [],
                "error": "Empty search query from filename",
            })
            time.sleep(delay)
            continue
        itunes = search_itunes(q, limit=6)  # noqa: F405
        time.sleep(delay)
        discogs = search_discogs(q, limit=4)  # noqa: F405
        time.sleep(delay)
        bandcamp = search_bandcamp(q, limit=5)  # noqa: F405
        time.sleep(delay)
        soundcloud = search_soundcloud(q, limit=6)  # noqa: F405
        time.sleep(delay)
        beatport = search_beatport(q, limit=5)  # noqa: F405
        time.sleep(delay)
        seen = set()
        combined = []
        for r in itunes + discogs + bandcamp + soundcloud + beatport:
            u = (r.get("url") or "").strip()
            key = (
                (r.get("title", "") or "").lower().strip(),
                (r.get("artist") or r.get("album") or "").lower().strip(),
                (r.get("source") or "").lower().strip(),
            )
            if key in seen:
                continue
            seen.add(key)
            out = {**r, "url": u}
            combined.append(out)
        items.append({
            "filepath": p,
            "query": q,
            "title_hint": info.get("title_hint") or "",
            "results": combined,
            "error": None,
        })
    return jsonify({"items": items})


@app.route("/api/bulk-fix/apply", methods=["POST"])
def bulk_fix_apply():
    """
    For each item with source_url, fetch remote metadata, match track when possible,
    and write tags (same as Fix Metadata + Save).
    """
    data = request.get_json() or {}
    items = data.get("items") or []
    if not isinstance(items, list) or not items:
        return jsonify({"error": "items (non-empty list) required"}), 400
    if len(items) > 40:
        return jsonify({"error": "Maximum 40 items per apply request."}), 400
    rename_to_tags = bool(data.get("rename_to_tags", False))
    record_in_log = data.get("record_in_log", True)
    if isinstance(record_in_log, str):
        record_in_log = record_in_log.lower() in ("1", "true", "yes", "on")
    results = []
    for raw in items:
        filepath = (raw.get("filepath") or "").strip()
        source_url = (raw.get("source_url") or raw.get("url") or "").strip()
        if raw.get("skip"):
            results.append({
                "filepath": filepath,
                "status": "skipped",
            })
            continue
        if not filepath or not source_url:
            results.append({
                "filepath": filepath,
                "status": "error",
                "reason": "filepath and source_url required",
            })
            continue
        if not os.path.isfile(filepath):
            results.append({
                "filepath": filepath,
                "status": "error",
                "reason": "File not found",
            })
            continue
        th = (raw.get("title_hint") or "").strip()
        if not th:
            stem = Path(filepath).stem
            th = (search_query_from_ableton_stem(stem).get("title_hint") or "").strip()  # noqa: F405
        r = _retag_file_from_source_url(
            filepath, source_url, th, rename_to_tags, record_in_log
        )
        r["filepath"] = r.get("filepath", filepath)
        results.append(r)
    n_ok = sum(1 for r in results if r.get("status") == "ok")
    n_err = sum(1 for r in results if r.get("status") == "error")
    n_sk = sum(1 for r in results if r.get("status") == "skipped")
    return jsonify({
        "summary": {"ok": n_ok, "errors": n_err, "skipped": n_sk},
        "results": results,
    })


# ---------------------------------------------------------------------------
# Fix List — CSV-driven batch metadata fix (integration with music_library)
# ---------------------------------------------------------------------------

@app.route("/fix-list")
def fix_list_page():
    return app.send_static_file("fix-list.html")


def _read_tags_for_path(filepath):
    """Read tags from any supported audio file, returning a dict. No path validation."""
    ext = os.path.splitext(filepath)[1].lower()
    try:
        if ext == ".flac":
            return _read_flac_tags(filepath)  # noqa: F405
        elif ext == ".mp3":
            return _read_mp3_tags(filepath)  # noqa: F405
        elif ext in (".m4a", ".mp4", ".aac"):
            return _read_mp4_tags(filepath)  # noqa: F405
        elif ext in (".aiff", ".aif"):
            return _read_aiff_tags(filepath)  # noqa: F405
        elif ext in (".ogg", ".oga"):
            return _read_vorbis_tags(filepath)  # noqa: F405
        else:
            return _read_generic_tags(filepath)  # noqa: F405
    except Exception as e:
        return {"error": str(e), "has_artwork": False}


@app.route("/api/fix-list/upload", methods=["POST"])
def fix_list_upload():
    """Parse an uploaded CSV fix list, verify files exist, read actual tags."""
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    f = request.files["file"]
    text = f.read().decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames or "full_path" not in reader.fieldnames:
        return jsonify({"error": "CSV must have a 'full_path' column"}), 400

    rows = []
    for row in reader:
        if len(rows) >= 500:
            break
        rows.append(row)
    if not rows:
        return jsonify({"error": "CSV is empty"}), 400

    def to_bool(v):
        return str(v).strip().lower() in ("true", "1", "yes")

    items = []
    n_found = 0
    n_missing_file = 0
    n_needs_tags = 0
    n_needs_artwork = 0
    for row in rows:
        fp = (row.get("full_path") or "").strip()
        exists = bool(fp) and os.path.isfile(fp)
        if exists:
            n_found += 1
        else:
            n_missing_file += 1

        csv_missing = {
            "title": to_bool(row.get("missing_title", "")),
            "artist": to_bool(row.get("missing_artist", "")),
            "bpm": to_bool(row.get("missing_bpm", "")),
            "key": to_bool(row.get("missing_key", "")),
        }
        csv_has_artwork = to_bool(row.get("has_artwork", "true"))

        actual_tags = {}
        query = ""
        if exists:
            actual_tags = _read_tags_for_path(fp)
            art_bytes, _ = read_embedded_artwork(fp)  # noqa: F405
            actual_tags["has_artwork"] = art_bytes is not None

            at = (actual_tags.get("artist") or "").strip()
            tt = (actual_tags.get("title") or "").strip()
            if at and tt:
                query = f"{at} {tt}"
            elif at or tt:
                query = at or tt
            else:
                stem = Path(fp).stem
                info = search_query_from_ableton_stem(stem)  # noqa: F405
                query = (info.get("query") or stem).strip()

            if not (actual_tags.get("title") or "").strip() or not (actual_tags.get("artist") or "").strip():
                n_needs_tags += 1
            if not actual_tags.get("has_artwork"):
                n_needs_artwork += 1

        items.append({
            "full_path": fp,
            "file_name": row.get("file_name", os.path.basename(fp)),
            "file_type": row.get("file_type", Path(fp).suffix.lstrip(".").upper() if fp else ""),
            "file_exists": exists,
            "csv_missing": csv_missing,
            "csv_has_artwork": csv_has_artwork,
            "actual_tags": actual_tags,
            "query": query,
            "title_hint": (actual_tags.get("title") or "").strip(),
            "artist_hint": (actual_tags.get("artist") or "").strip(),
        })

    return jsonify({
        "total": len(items),
        "items": items,
        "summary": {
            "total": len(items),
            "files_found": n_found,
            "files_missing": n_missing_file,
            "needs_tags": n_needs_tags,
            "needs_artwork": n_needs_artwork,
        },
    })


@app.route("/api/fix-list/suggest", methods=["POST"])
def fix_list_suggest():
    """Search online sources for each item using provided query and title_hint."""
    data = request.get_json() or {}
    items_in = data.get("items") or []
    if not isinstance(items_in, list):
        return jsonify({"error": "items must be a list"}), 400
    if len(items_in) > 60:
        return jsonify({"error": "Maximum 60 items per suggest request."}), 400

    delay = 0.12
    items_out = []
    for raw in items_in:
        fp = (raw.get("filepath") or "").strip()
        q = (raw.get("query") or "").strip()
        if not q:
            items_out.append({
                "filepath": fp,
                "query": "",
                "results": [],
                "error": "Empty search query",
            })
            time.sleep(delay)
            continue
        if not os.path.isfile(fp):
            items_out.append({
                "filepath": fp,
                "query": q,
                "results": [],
                "error": "File not found",
            })
            time.sleep(delay)
            continue

        itunes = search_itunes(q, limit=6)  # noqa: F405
        time.sleep(delay)
        discogs = search_discogs(q, limit=4)  # noqa: F405
        time.sleep(delay)
        bandcamp = search_bandcamp(q, limit=5)  # noqa: F405
        time.sleep(delay)
        soundcloud = search_soundcloud(q, limit=6)  # noqa: F405
        time.sleep(delay)
        beatport = search_beatport(q, limit=5)  # noqa: F405
        time.sleep(delay)

        seen = set()
        combined = []
        for r in itunes + discogs + bandcamp + soundcloud + beatport:
            u = (r.get("url") or "").strip()
            key = (
                (r.get("title", "") or "").lower().strip(),
                (r.get("artist") or r.get("album") or "").lower().strip(),
                (r.get("source") or "").lower().strip(),
            )
            if key in seen:
                continue
            seen.add(key)
            combined.append({**r, "url": u})

        items_out.append({
            "filepath": fp,
            "query": q,
            "title_hint": (raw.get("title_hint") or "").strip(),
            "results": combined,
            "error": None,
        })

    return jsonify({"items": items_out})


@app.route("/api/fix-list/export-completed", methods=["POST"])
def fix_list_export_completed():
    """Write a CSV of completed file paths to the logs directory."""
    data = request.get_json() or {}
    paths = data.get("paths") or []
    if not isinstance(paths, list) or not paths:
        return jsonify({"error": "paths (non-empty list) required"}), 400

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = (data.get("filename") or "").strip() or f"completed_fixes_{ts}.csv"
    if not fname.endswith(".csv"):
        fname += ".csv"
    fname = re.sub(r"[^\w.\-]", "_", fname)
    log_dir = os.path.dirname(os.path.abspath(__file__))
    out_path = os.path.join(log_dir, fname)

    output = io.StringIO()
    w = csv.writer(output)
    w.writerow(["full_path"])
    for p in paths:
        w.writerow([p])

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(output.getvalue())

    return jsonify({"filepath": out_path, "count": len(paths)})


@app.route("/api/settings", methods=["GET"])
def get_settings():
    cfg = dict(load_config())  # noqa: F405
    cfg["extract_profile"] = resolve_extract_profile_key(cfg)  # noqa: F405
    cfg["extract_profiles"] = extract_profile_options(cfg)  # noqa: F405
    cfg["source_dir_resolved"] = resolve(cfg["source_dir"])  # noqa: F405
    cfg["destination_dir_resolved"] = resolve(cfg["destination_dir"])  # noqa: F405
    cfg["fix_retain_filename_suffixes"] = normalize_fix_retain_filename_suffixes(  # noqa: F405
        cfg.get("fix_retain_filename_suffixes"),
    )
    cfg["mp3_bitrate_options"] = MP3_BITRATE_OPTIONS  # noqa: F405
    cfg["aac_bitrate_options"] = AAC_BITRATE_OPTIONS  # noqa: F405
    return jsonify(cfg)


@app.route("/api/settings", methods=["POST"])
def update_settings():
    data = request.get_json()
    cfg = load_config()  # noqa: F405

    if "source_dir" in data:
        cfg["source_dir"] = data["source_dir"]
    if "destination_dir" in data:
        cfg["destination_dir"] = data["destination_dir"]
    if "fix_metadata_default_dir" in data:
        cfg["fix_metadata_default_dir"] = (data["fix_metadata_default_dir"] or "").strip()
    if "inspect_default_dir" in data:
        cfg["inspect_default_dir"] = (data["inspect_default_dir"] or "").strip()
    if "platinum_notes_app" in data:
        cfg["platinum_notes_app"] = (data["platinum_notes_app"] or "").strip()
    if "pn_output_suffix" in data:
        cfg["pn_output_suffix"] = (data["pn_output_suffix"] or "_PN").strip() or "_PN"
    if "target_lufs" in data and data["target_lufs"] is not None and data["target_lufs"] != "":
        try:
            cfg["target_lufs"] = float(data["target_lufs"])
        except (TypeError, ValueError):
            pass
    if "target_true_peak" in data and data["target_true_peak"] is not None and data["target_true_peak"] != "":
        try:
            cfg["target_true_peak"] = float(data["target_true_peak"])
        except (TypeError, ValueError):
            pass
    if "extract_profile" in data:
        pk = (data["extract_profile"] or "flac").strip().lower()
        pk = _PROFILE_KEY_MIGRATION.get(pk, pk)  # noqa: F405
        if pk in EXTRACT_PROFILES:  # noqa: F405
            cfg["extract_profile"] = pk
    if "mp3_bitrate" in data:
        br = str(data["mp3_bitrate"]).strip()
        if br in MP3_BITRATE_OPTIONS:  # noqa: F405
            cfg["mp3_bitrate"] = br
    if "aac_bitrate" in data:
        br = str(data["aac_bitrate"]).strip()
        if br in AAC_BITRATE_OPTIONS:  # noqa: F405
            cfg["aac_bitrate"] = br
    if "loudness_verify_enabled" in data:
        cfg["loudness_verify_enabled"] = bool(data["loudness_verify_enabled"])
    if "extract_mkv_audio_analysis_enabled" in data:
        cfg["extract_mkv_audio_analysis_enabled"] = bool(data["extract_mkv_audio_analysis_enabled"])
    if "loudness_verify_tolerance_lufs" in data and data["loudness_verify_tolerance_lufs"] not in (None, ""):
        try:
            v = float(data["loudness_verify_tolerance_lufs"])
            if 0.5 <= v <= 6.0:
                cfg["loudness_verify_tolerance_lufs"] = v
        except (TypeError, ValueError):
            pass
    if "loudness_verify_tolerance_tp" in data and data["loudness_verify_tolerance_tp"] not in (None, ""):
        try:
            v = float(data["loudness_verify_tolerance_tp"])
            if 0.1 <= v <= 2.0:
                cfg["loudness_verify_tolerance_tp"] = v
        except (TypeError, ValueError):
            pass
    if "fix_retain_filename_suffixes" in data:
        lines = normalize_fix_retain_filename_suffixes(data["fix_retain_filename_suffixes"])  # noqa: F405
        for line in lines:
            if line.lower().startswith("regex:"):
                pat = line[6:].strip()
                try:
                    re.compile(pat)
                except re.error as e:
                    return jsonify({"error": f"Invalid regex in fix filename suffixes: {pat} ({e})"}), 400
        cfg["fix_retain_filename_suffixes"] = lines

    save_config(cfg)  # noqa: F405

    cfg = dict(load_config())  # noqa: F405
    cfg["extract_profile"] = resolve_extract_profile_key(cfg)  # noqa: F405
    cfg["extract_profiles"] = extract_profile_options(cfg)  # noqa: F405
    cfg["source_dir_resolved"] = resolve(cfg["source_dir"])  # noqa: F405
    cfg["destination_dir_resolved"] = resolve(cfg["destination_dir"])  # noqa: F405
    cfg["fix_retain_filename_suffixes"] = normalize_fix_retain_filename_suffixes(  # noqa: F405
        cfg.get("fix_retain_filename_suffixes"),
    )
    cfg["mp3_bitrate_options"] = MP3_BITRATE_OPTIONS  # noqa: F405
    cfg["aac_bitrate_options"] = AAC_BITRATE_OPTIONS  # noqa: F405
    return jsonify(cfg)


@app.route("/api/browse")
def browse():
    cfg = load_config()  # noqa: F405
    directory = request.args.get("dir", cfg["source_dir"])
    directory = resolve(directory)  # noqa: F405
    if not os.path.isdir(directory):
        return jsonify({"error": f"Directory not found: {directory}"}), 404

    files = []
    for f in sorted(Path(directory).iterdir()):
        if f.suffix.lower() in VIDEO_SOURCE_EXTENSIONS:  # noqa: F405
            files.append({
                "name": f.name,
                "path": str(f),
                "size_mb": round(f.stat().st_size / (1024 * 1024), 1),
            })
    return jsonify({"directory": directory, "files": files})


@app.route("/api/source-recording/rename", methods=["POST"])
def rename_source_recording():
    """Rename a recording in the Extract file list (same directory only)."""
    data = request.get_json() or {}
    filepath = data.get("filepath")
    base_dir = data.get("base_dir")
    new_stem = (data.get("new_stem") or "").strip()
    ok, err = _assert_browse_dir_video_file(filepath, base_dir)
    if not ok:
        return jsonify({"error": err}), 400
    safe_stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", new_stem).strip()
    if not safe_stem or safe_stem in (".", ".."):
        return jsonify({"error": "Invalid name"}), 400
    old = Path(filepath)
    new_name = f"{safe_stem}{old.suffix.lower()}"
    fp_norm = os.path.normpath(os.path.abspath(str(old)))
    new_path = os.path.normpath(os.path.abspath(str(old.parent / new_name)))
    if new_path == fp_norm:
        return jsonify({"path": new_path, "name": new_name})
    if os.path.exists(new_path):
        return jsonify({"error": f"A file named {new_name} already exists"}), 409
    try:
        os.rename(fp_norm, new_path)
    except OSError as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"path": new_path, "name": new_name})


@app.route("/api/source-recording/delete", methods=["POST"])
def delete_source_recording():
    """Move a recording to the system Trash (macOS Finder), same as optional post-extract delete."""
    data = request.get_json() or {}
    filepath = data.get("filepath")
    base_dir = data.get("base_dir")
    ok, err = _assert_browse_dir_video_file(filepath, base_dir)
    if not ok:
        return jsonify({"error": err}), 400
    try:
        trash_file(filepath)  # noqa: F405
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"ok": True})


@app.route("/api/probe", methods=["POST"])
def probe():
    data = request.get_json()
    filepath = data.get("filepath")
    if not filepath or not os.path.isfile(filepath):
        return jsonify({"error": "File not found"}), 404
    try:
        filepath = _validate_path_in_allowed_dirs(filepath)  # noqa: F405
    except ValueError as e:
        return jsonify({"error": str(e)}), 403

    info = run_ffprobe(filepath)  # noqa: F405
    stream = info["streams"][0] if info.get("streams") else {}
    fmt = info.get("format", {})
    return jsonify({
        "codec": stream.get("codec_name"),
        "sample_rate": stream.get("sample_rate"),
        "channels": stream.get("channels"),
        "duration": stream.get("duration") or fmt.get("duration"),
    })


@app.route("/api/analyse", methods=["POST"])
def analyse():
    data = request.get_json()
    filepath = data.get("filepath")
    if not filepath or not os.path.isfile(filepath):
        return jsonify({"error": "File not found"}), 404
    try:
        filepath = _validate_path_in_allowed_dirs(filepath)  # noqa: F405
    except ValueError as e:
        return jsonify({"error": str(e)}), 403

    try:
        result = analyse_loudness(filepath)  # noqa: F405
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/normalise", methods=["POST"])
@app.route("/api/normalise-flac", methods=["POST"])
def normalise_audio_route():
    """EBU R128 loudnorm to configured LUFS; encodes to Settings extract profile; copies tags and artwork."""
    data = request.get_json()
    filepath = data.get("filepath")
    loudnorm_params = data.get("loudnorm_params")
    output_suffix = (data.get("output_suffix") or "_LUFS14").strip() or "_LUFS14"
    if not output_suffix.startswith("_"):
        output_suffix = "_" + output_suffix

    if not filepath or not os.path.isfile(filepath):
        return jsonify({"error": "File not found"}), 404
    try:
        filepath = _validate_path_in_allowed_dirs(filepath)  # noqa: F405
    except ValueError as e:
        return jsonify({"error": str(e)}), 403
    ext_in = Path(filepath).suffix.lower()
    if ext_in not in AUDIO_EXTENSIONS:  # noqa: F405
        return jsonify({"error": "Unsupported audio file type for normalise"}), 400
    if not loudnorm_params or not isinstance(loudnorm_params, dict):
        return jsonify({"error": "Run level analysis first (loudnorm_params missing)"}), 400

    cfg = load_config()  # noqa: F405
    profile_key = resolve_extract_profile_key(cfg)  # noqa: F405
    prof = _resolve_profile(profile_key, cfg)  # noqa: F405
    parent = Path(filepath).parent
    stem = Path(filepath).stem
    out_path = str(parent / f"{stem}{output_suffix}{prof['ext']}")

    if os.path.normpath(os.path.abspath(out_path)) == os.path.normpath(os.path.abspath(filepath)):
        return jsonify({"error": "Output path cannot be the same as input"}), 400
    if os.path.exists(out_path):
        return jsonify({"error": f"Output already exists: {out_path}"}), 409

    try:
        _ffmpeg_loudnorm_encode(filepath, out_path, loudnorm_params, profile_key)  # noqa: F405
        _copy_audio_tags_and_art(filepath, out_path)  # noqa: F405
    except subprocess.CalledProcessError as e:
        if os.path.isfile(out_path):
            try:
                os.remove(out_path)
            except OSError:
                pass
        return jsonify({"error": f"ffmpeg failed: {e.stderr}"}), 500
    except Exception as e:
        if os.path.isfile(out_path):
            try:
                os.remove(out_path)
            except OSError:
                pass
        return jsonify({"error": str(e)}), 500

    stat = os.stat(out_path)
    return jsonify({
        "output_path": out_path,
        "size_mb": round(stat.st_size / (1024 * 1024), 1),
        "extract_profile": profile_key,
        "extract_profile_label": prof["label"],
    })


@app.route("/api/fetch-metadata", methods=["POST"])
def fetch_metadata():
    data = request.get_json() or {}
    url = (data.get("url") or "").strip()
    track_name = (data.get("track_name") or data.get("track_name_hint") or "").strip()
    meta = _metadata_from_url(url)
    if track_name:
        _resolve_metadata_track_hint(meta, track_name)
    return jsonify(meta)


@app.route("/api/fetch-artwork")
def fetch_artwork_route():
    url = request.args.get("url", "")
    if not url:
        return jsonify({"error": "No URL"}), 400
    try:
        img_bytes, content_type = fetch_artwork(url)  # noqa: F405
        return app.response_class(img_bytes, mimetype=content_type)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# Apple Music Now Playing & Logged Tracks API
# ---------------------------------------------------------------------------

@app.route("/api/platform")
def get_platform():
    return jsonify({"platform": sys.platform})


@app.route("/api/apple-music/now-playing", methods=["POST"])
def apple_music_now_playing():
    if sys.platform != "darwin":
        return jsonify({"error": "Apple Music capture requires macOS"}), 501
    try:
        entry = capture_apple_music_now_playing()
    except PermissionError as e:
        return jsonify({"error": str(e)}), 403
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 400

    data = load_logged_tracks()  # noqa: F405
    pid = entry.get("appleMusicPersistentId")
    if pid:
        for existing in data["tracks"]:
            if existing.get("appleMusicPersistentId") == pid:
                try:
                    delta = (
                        datetime.fromisoformat(entry["capturedAt"])
                        - datetime.fromisoformat(existing["capturedAt"])
                    ).total_seconds()
                    if abs(delta) < 30:
                        return jsonify({"track": existing, "duplicate": True})
                except (ValueError, TypeError):
                    pass

    data["tracks"].append(entry)
    save_logged_tracks(data)  # noqa: F405
    return jsonify({"track": entry})


@app.route("/api/logged-tracks")
def get_logged_tracks():
    return jsonify(load_logged_tracks())  # noqa: F405


@app.route("/api/logged-tracks/<track_id>", methods=["DELETE"])
def delete_logged_track(track_id):
    data = load_logged_tracks()  # noqa: F405
    before = len(data["tracks"])
    data["tracks"] = [t for t in data["tracks"] if t.get("id") != track_id]
    if len(data["tracks"]) == before:
        return jsonify({"error": "Track not found"}), 404
    save_logged_tracks(data)  # noqa: F405
    return jsonify({"ok": True})


@app.route("/api/logged-tracks", methods=["DELETE"])
def clear_logged_tracks():
    save_logged_tracks({"schema_version": 1, "tracks": []})  # noqa: F405
    return jsonify({"ok": True})


@app.route("/api/extract", methods=["POST"])
def extract():
    data = request.get_json()
    cfg = load_config()  # noqa: F405

    filepath = data.get("filepath")
    metadata = data.get("metadata", {})
    artwork_url = data.get("artwork_url", "")
    metadata_source_url = (data.get("metadata_source_url") or "").strip()
    logged_track_id = (data.get("logged_track_id") or "").strip() or None

    if not filepath or not os.path.isfile(filepath):
        return jsonify({"error": "Source file not found"}), 404
    try:
        filepath = _validate_path_in_allowed_dirs(filepath)  # noqa: F405
    except ValueError as e:
        return jsonify({"error": str(e)}), 403

    profile_key = resolve_extract_profile_key(cfg)  # noqa: F405
    prof = _resolve_profile(profile_key, cfg)  # noqa: F405

    title = metadata.get("title", Path(filepath).stem)
    safe_title = re.sub(r'[<>:"/\\|?*]', '', title).strip()
    filename = f"{safe_title}{prof['ext']}"

    output_dir = os.path.dirname(filepath)
    output_path = os.path.join(output_dir, filename)

    if os.path.exists(output_path):
        return jsonify({"error": f"Output file already exists: {output_path}"}), 409

    normalise = data.get("normalise", False)
    # Always measure the source in this request; client loudnorm JSON can be from another file/session.
    loudnorm_params = data.get("loudnorm_params")
    loudness_retried = False
    loudness_verify_warning = None
    tgt_lufs, tgt_tp = get_normalisation_targets()  # noqa: F405

    if normalise:
        an_src = analyse_loudness(filepath)  # noqa: F405
        lp = an_src.get("loudnorm_params") or {}
        if not _loudnorm_params_usable(lp):  # noqa: F405
            return jsonify({
                "error": "Loudness analysis of the source failed (ffmpeg did not return loudnorm measurements). "
                "Is ffmpeg installed? Try the level meters (Analyse) on this file, then extract again.",
            }), 500
        loudnorm_params = lp

    try:
        source_codec = extract_audio(filepath, output_path, profile_key, normalise, loudnorm_params)  # noqa: F405
    except subprocess.CalledProcessError as e:
        return jsonify({"error": f"ffmpeg failed: {e.stderr}"}), 500

    if (
        normalise
        and cfg.get("loudness_verify_enabled", True)
    ):
        try:
            tol_lufs = float(cfg.get("loudness_verify_tolerance_lufs", 2.0))
        except (TypeError, ValueError):
            tol_lufs = 2.0
        try:
            tol_tp = float(cfg.get("loudness_verify_tolerance_tp", 0.35))
        except (TypeError, ValueError):
            tol_tp = 0.35
        post = analyse_loudness(output_path)  # noqa: F405
        pparams = post.get("loudnorm_params") or {}
        ok, reasons = normalised_output_meets_targets(pparams, tgt_lufs, tgt_tp, tol_lufs, tol_tp)  # noqa: F405
        if not ok:
            # One retry: fresh source pass + re-encode; fixes stale client params and odd ffmpeg runs.
            an2 = analyse_loudness(filepath)  # noqa: F405
            flp = an2.get("loudnorm_params") or {}
            if not _loudnorm_params_usable(flp):  # noqa: F405
                loudness_verify_warning = (
                    "Loudness check failed: " + "; ".join(reasons) + " — could not re-analyse the source for a retry."
                )
            else:
                tmp_fd, tmp_path = tempfile.mkstemp(
                    prefix=".loudness_retry_",
                    suffix=prof["ext"],
                    dir=output_dir,
                )
                os.close(tmp_fd)
                loudness_retried = True
                try:
                    _ffmpeg_loudnorm_encode(  # noqa: F405
                        filepath, tmp_path, flp, profile_key, target_lufs=tgt_lufs, target_tp=tgt_tp
                    )
                    os.replace(tmp_path, output_path)
                except subprocess.CalledProcessError as re_err:
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass
                    loudness_verify_warning = f"Loudness re-encode failed: {re_err.stderr or re_err}"
                else:
                    post2 = analyse_loudness(output_path)  # noqa: F405
                    p2 = post2.get("loudnorm_params") or {}
                    ok2, reasons2 = normalised_output_meets_targets(  # noqa: F405
                        p2, tgt_lufs, tgt_tp, tol_lufs, tol_tp
                    )
                    if not ok2:
                        loudness_verify_warning = (
                            "Loudness check still failing after a server re-encode: " + "; ".join(reasons2)
                        )
                    else:
                        loudness_verify_warning = None

    artwork_bytes, artwork_mime = None, None
    raw_b64 = (data.get("artwork_base64") or "").strip()
    if raw_b64:
        artwork_bytes, artwork_mime = _decode_retag_artwork_base64(  # noqa: F405
            raw_b64, data.get("artwork_mime", "")
        )
    if not artwork_bytes and artwork_url:
        try:
            artwork_bytes, artwork_mime = fetch_artwork(artwork_url)  # noqa: F405
        except Exception:
            pass

    meta_for_file = dict(metadata)
    if metadata_source_url:
        meta_for_file["source_url"] = metadata_source_url

    apply_metadata(output_path, meta_for_file, artwork_bytes, artwork_mime)  # noqa: F405

    # Copy to destination folder
    dest_dir = resolve(cfg["destination_dir"])  # noqa: F405
    copied_to = None
    copy_error = None

    if dest_dir:
        try:
            os.makedirs(dest_dir, exist_ok=True)
            dest_path = os.path.join(dest_dir, filename)
            shutil.copy2(output_path, dest_path)
            copied_to = dest_path
        except Exception as e:
            copy_error = str(e)

    # Optionally trash source
    delete_source = data.get("delete_source", False)
    source_trashed = False
    source_trash_error = None

    if delete_source:
        try:
            trash_file(filepath)  # noqa: F405
            source_trashed = True
        except Exception as e:
            source_trash_error = str(e)

    stat = os.stat(output_path)

    suffix = cfg.get("pn_output_suffix", "_PN")
    expected_pn_path = str(pn_derivative_path(output_path, suffix))  # noqa: F405

    log_index = log_extraction({  # noqa: F405
        "kind": "extract",
        "filename": filename,
        "extract_profile": profile_key,
        "source_file": filepath,
        "output_path": output_path,
        "copied_to": copied_to,
        "metadata": metadata,
        "artwork_url": artwork_url,
        "metadata_source_url": metadata_source_url,
        "metadata_source_type": infer_metadata_source_type(metadata_source_url),  # noqa: F405
        "normalised": normalise,
        "normalise_target_lufs": tgt_lufs if normalise else None,
        "normalise_target_tp": tgt_tp if normalise else None,
        "loudness_retried": loudness_retried if normalise else None,
        "loudness_verify_warning": loudness_verify_warning if normalise else None,
        "source_codec": source_codec,
        "pn_output_suffix": suffix,
    })

    open_pn = bool(data.get("open_platinum_notes"))
    pn_app = (cfg.get("platinum_notes_app") or "").strip()
    if open_pn and pn_app:
        post_extract_open_app(pn_app, output_path)  # noqa: F405

    logged_track_removed = False
    if logged_track_id:
        try:
            lt_data = load_logged_tracks()  # noqa: F405
            before = len(lt_data["tracks"])
            lt_data["tracks"] = [t for t in lt_data["tracks"] if t.get("id") != logged_track_id]
            if len(lt_data["tracks"]) < before:
                save_logged_tracks(lt_data)  # noqa: F405
                logged_track_removed = True
        except Exception:
            pass

    result = {
        "output_path": output_path,
        "filename": filename,
        "size_mb": round(stat.st_size / (1024 * 1024), 1),
        "source_codec": source_codec,
        "title": safe_title,
        "extract_profile": profile_key,
        "extract_profile_label": prof["label"],
        "is_lossless_output": prof["lossless"],
        "source_trashed": source_trashed,
        "normalised": normalise,
        "log_index": log_index,
        "expected_pn_path": expected_pn_path,
        "expected_pn_flac_path": expected_pn_path,
        "logged_track_removed": logged_track_removed,
    }
    if normalise:
        result["target_lufs"] = tgt_lufs
        result["target_tp"] = tgt_tp
        result["loudness_retried"] = loudness_retried
        if loudness_verify_warning:
            result["loudness_verify_warning"] = loudness_verify_warning
    if copied_to:
        result["copied_to"] = copied_to
    if copy_error:
        result["copy_error"] = copy_error
    if source_trash_error:
        result["source_trash_error"] = source_trash_error

    return jsonify(result)


@app.route("/api/poll-pn-derivative", methods=["POST"])
def poll_pn_derivative():
    """
    Return whether <stem><pn_suffix>.<ext> exists. Checks: beside the extract, beside the
    library copy (copied_to from the same run), and flat in Settings destination -- so PN
    can be configured to write only to the FLACs / destination folder.
    """
    data = request.get_json() or {}
    cfg = load_config()  # noqa: F405
    base_flac_path = (data.get("base_flac_path") or "").strip()
    copied_to = (data.get("copied_to") or "").strip() or None
    suffix = (data.get("pn_output_suffix") or cfg.get("pn_output_suffix") or "_PN").strip()
    if not base_flac_path:
        return jsonify({"error": "base_flac_path required"}), 400
    if not os.path.isfile(base_flac_path):
        return jsonify({"error": "Base audio file not found", "ready": False}), 404

    dest = (cfg.get("destination_dir") or "").strip()
    candidates = _pn_output_candidate_paths(  # noqa: F405
        base_flac_path, suffix, copied_to=copied_to, destination_dir=dest
    )
    try:
        base_mt = os.path.getmtime(base_flac_path)
    except OSError:
        base_mt = 0.0

    ready = False
    pn_path = str(pn_derivative_path(base_flac_path, suffix))  # noqa: F405
    for cand in candidates:
        if not os.path.isfile(cand):
            continue
        try:
            if os.path.getmtime(cand) < base_mt:
                continue
        except OSError:
            continue
        ready = True
        pn_path = cand
        break

    return jsonify({
        "ready": ready,
        "pn_path": pn_path,
        "pn_flac_path": pn_path,
        "pn_output_suffix": suffix,
        "candidates": candidates,
    })


@app.route("/api/repair-pn-derivative", methods=["POST"])
def repair_pn_derivative():
    """Re-apply metadata and artwork from the processing log onto a Platinum Notes output file."""
    data = request.get_json() or {}
    cfg = load_config()  # noqa: F405
    base_flac_path = data.get("base_flac_path")
    pn_flac_path = data.get("pn_flac_path")
    log_index = data.get("log_index")
    suffix = (data.get("pn_output_suffix") or cfg.get("pn_output_suffix") or "_PN").strip()

    if not base_flac_path:
        return jsonify({"error": "base_flac_path required"}), 400
    if not os.path.isfile(base_flac_path):
        return jsonify({"error": f"Base audio file not found: {base_flac_path}"}), 404

    entry, idx = find_log_entry_for_output_path(base_flac_path, log_index)  # noqa: F405
    if not entry:
        return jsonify({
            "error": "No processing log entry matches this extract. Expand Processing Log and use a row from the same run, or re-fetch metadata manually.",
        }), 404

    pn_path = pn_flac_path or str(pn_derivative_path(base_flac_path, suffix))  # noqa: F405
    if not os.path.isfile(pn_path):
        return jsonify({
            "error": f"File not found: {pn_path}",
            "pn_flac_path": pn_path,
            "waiting": True,
        }), 404

    metadata = dict(entry.get("metadata") or {})
    artwork_url = entry.get("artwork_url", "")
    msu = (entry.get("metadata_source_url") or "").strip()
    if msu:
        metadata["source_url"] = msu

    artwork_bytes, artwork_mime = None, None
    if artwork_url:
        try:
            artwork_bytes, artwork_mime = fetch_artwork(artwork_url)  # noqa: F405
        except Exception as e:
            return jsonify({"error": f"Artwork fetch failed: {e}"}), 500

    try:
        apply_metadata(pn_path, metadata, artwork_bytes, artwork_mime)  # noqa: F405
    except Exception as e:
        return jsonify({"error": f"Tagging failed: {e}"}), 500

    copied_pn = None
    copy_err = None
    copied_orig = entry.get("copied_to")
    if copied_orig:
        dest_pn = os.path.join(os.path.dirname(copied_orig), os.path.basename(pn_path))
        try:
            os.makedirs(os.path.dirname(copied_orig), exist_ok=True)
            if os.path.isfile(pn_path) and os.path.isfile(dest_pn):
                try:
                    if os.path.samefile(pn_path, dest_pn):
                        copied_pn = dest_pn
                    else:
                        shutil.copy2(pn_path, dest_pn)
                        copied_pn = dest_pn
                except (OSError, FileNotFoundError):
                    shutil.copy2(pn_path, dest_pn)
                    copied_pn = dest_pn
            else:
                shutil.copy2(pn_path, dest_pn)
                copied_pn = dest_pn
        except OSError as e:
            copy_err = str(e)

    return jsonify({
        "status": "ok",
        "pn_path": pn_path,
        "pn_flac_path": pn_path,
        "log_index": idx,
        "copied_pn_to_destination": copied_pn,
        "copy_error": copy_err,
    })


@app.route("/api/log")
def get_log():
    return jsonify(load_log())  # noqa: F405


@app.route("/api/fix-artwork", methods=["POST"])
def fix_artwork():
    """Re-embed existing artwork with correct dimensions."""
    data = request.get_json()
    filepath = data.get("filepath")
    if not filepath or not os.path.isfile(filepath):
        return jsonify({"error": "File not found"}), 404
    try:
        filepath = _validate_path_in_allowed_dirs(filepath)  # noqa: F405
    except ValueError as e:
        return jsonify({"error": str(e)}), 403

    ext = os.path.splitext(filepath)[1].lower()
    try:
        if ext == ".flac":
            result, err = _fix_artwork_flac(filepath)  # noqa: F405
        elif ext in (".mp3",):
            audio = MP3(filepath, ID3=ID3)
            result, err = _fix_artwork_id3(filepath, audio)  # noqa: F405
        elif ext in (".aiff", ".aif"):
            from mutagen.aiff import AIFF as _AIFF
            audio = _AIFF(filepath)
            result, err = _fix_artwork_id3(filepath, audio)  # noqa: F405
        elif ext in (".m4a", ".mp4", ".aac"):
            result, err = _fix_artwork_mp4(filepath)  # noqa: F405
        else:
            return jsonify({"error": f"Format {ext} not supported for artwork fix"}), 400

        if result is None:
            return jsonify({"error": err or "No artwork to fix"}), 400
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/retag", methods=["POST"])
def retag():
    """Re-apply metadata and artwork to an existing audio file.

    JSON body may include ``artwork_base64`` (+ optional ``artwork_mime``) to embed a cover from
    the browser (Fix Metadata: local file / drag-and-drop). That takes precedence over
    ``artwork_url`` when both are sent.
    """
    data = request.get_json()
    filepath = data.get("filepath")
    metadata = dict(data.get("metadata") or {})
    artwork_url = data.get("artwork_url", "")
    metadata_source_url = (data.get("metadata_source_url") or "").strip()
    record_in_log = data.get("record_in_log", True)
    rename_to_tags = bool(data.get("rename_to_tags"))

    if not filepath or not os.path.isfile(filepath):
        return jsonify({"error": f"File not found: {filepath}"}), 404
    try:
        filepath = _validate_path_in_allowed_dirs(filepath)  # noqa: F405
    except ValueError as e:
        return jsonify({"error": str(e)}), 403

    meta_for_file = dict(metadata)
    if metadata_source_url:
        meta_for_file["source_url"] = metadata_source_url

    planned_new_name = None
    if rename_to_tags:
        ext = Path(filepath).suffix.lower() or ".flac"
        retained = _retained_suffix_from_filepath(filepath)  # noqa: F405
        planned_new_name = _basename_from_artist_title_for_rename(  # noqa: F405
            metadata.get("artist", ""),
            metadata.get("title", ""),
            ext,
            retained_suffix=retained,
        )
        if not planned_new_name:
            return jsonify({
                "error": "Rename: enter at least a title or artist so a new filename can be built.",
            }), 400
        dest_dir = os.path.dirname(filepath)
        candidate = os.path.join(dest_dir, planned_new_name)
        if os.path.basename(filepath) != planned_new_name and os.path.exists(candidate):
            try:
                if not os.path.samefile(filepath, candidate):
                    return jsonify({
                        "error": f"That filename is already in use: {planned_new_name}. Change title/artist or remove the other file first.",
                    }), 409
            except (OSError, FileNotFoundError):
                return jsonify({
                    "error": f"That filename is already in use: {planned_new_name}.",
                }), 409

    artwork_uploaded = False
    artwork_raw_b64 = (data.get("artwork_base64") or "").strip()
    artwork_bytes, artwork_mime = None, None
    if artwork_raw_b64:
        artwork_bytes, artwork_mime = _decode_retag_artwork_base64(  # noqa: F405
            artwork_raw_b64,
            (data.get("artwork_mime") or "").strip(),
        )
        if not artwork_bytes:
            return jsonify({
                "error": "Invalid cover image: use JPEG, PNG, WebP, or GIF (max 10 MB).",
            }), 400
        artwork_uploaded = True
    elif artwork_url:
        try:
            artwork_bytes, artwork_mime = fetch_artwork(artwork_url)  # noqa: F405
        except Exception as e:
            return jsonify({"error": f"Artwork fetch failed: {e}"}), 500

    try:
        apply_metadata(filepath, meta_for_file, artwork_bytes, artwork_mime)  # noqa: F405
    except Exception as e:
        return jsonify({"error": f"Tagging failed: {e}"}), 500

    out_path = filepath
    renamed = False
    if rename_to_tags and planned_new_name:
        dest_dir = os.path.dirname(filepath)
        candidate = os.path.join(dest_dir, planned_new_name)
        if os.path.basename(filepath) != planned_new_name:
            try:
                os.rename(filepath, candidate)
                out_path = candidate
                renamed = True
            except OSError as e:
                return jsonify({
                    "error": f"Tags were saved, but rename failed: {e}",
                }), 500

    if record_in_log and (metadata_source_url or artwork_url or artwork_uploaded):
        log_extraction({  # noqa: F405
            "kind": "fix",
            "filename": os.path.basename(out_path),
            "output_path": out_path,
            "target_path": out_path,
            "metadata": metadata,
            "artwork_url": artwork_url,
            "local_artwork": artwork_uploaded,
            "metadata_source_url": metadata_source_url,
            "metadata_source_type": infer_metadata_source_type(metadata_source_url),  # noqa: F405
        })

    return jsonify({
        "status": "ok",
        "filepath": out_path,
        "renamed": renamed,
    })


@app.route("/api/retag-artwork", methods=["POST"])
def retag_artwork():
    """Embed cover art only; does not change text tags or rename the file."""
    data = request.get_json()
    filepath = data.get("filepath")
    if not filepath or not os.path.isfile(filepath):
        return jsonify({"error": f"File not found: {filepath}"}), 404
    try:
        filepath = _validate_path_in_allowed_dirs(filepath)  # noqa: F405
    except ValueError as e:
        return jsonify({"error": str(e)}), 403

    artwork_raw_b64 = (data.get("artwork_base64") or "").strip()
    artwork_url = (data.get("artwork_url") or "").strip()
    artwork_bytes, artwork_mime = None, None
    artwork_uploaded = False

    if artwork_raw_b64:
        artwork_bytes, artwork_mime = _decode_retag_artwork_base64(  # noqa: F405
            artwork_raw_b64,
            (data.get("artwork_mime") or "").strip(),
        )
        if not artwork_bytes:
            return jsonify({
                "error": "Invalid cover image: use JPEG, PNG, WebP, or GIF (max 10 MB).",
            }), 400
        artwork_uploaded = True
    elif artwork_url:
        try:
            artwork_bytes, artwork_mime = fetch_artwork(artwork_url)  # noqa: F405
        except Exception as e:
            return jsonify({"error": f"Artwork fetch failed: {e}"}), 500
    else:
        return jsonify({
            "error": "Provide artwork_base64 (and optional artwork_mime) or artwork_url.",
        }), 400

    if not artwork_bytes:
        return jsonify({"error": "No artwork data to embed."}), 400

    try:
        apply_metadata(filepath, {}, artwork_bytes, artwork_mime)  # noqa: F405
    except Exception as e:
        return jsonify({"error": f"Tagging failed: {e}"}), 500

    if data.get("record_in_log", False) and (artwork_url or artwork_uploaded):
        log_extraction({  # noqa: F405
            "kind": "fix_artwork",
            "filename": os.path.basename(filepath),
            "output_path": filepath,
            "target_path": filepath,
            "metadata": {},
            "artwork_url": artwork_url,
            "local_artwork": artwork_uploaded,
            "metadata_source_url": "",
            "metadata_source_type": infer_metadata_source_type(artwork_url),  # noqa: F405
        })

    return jsonify({"status": "ok", "filepath": filepath})


@app.route("/api/retag-batch", methods=["POST"])
def retag_batch():
    """Re-apply metadata+artwork to multiple files from the processing log."""
    data = request.get_json()
    target_dir = data.get("target_dir", "")
    entry_indices = data.get("entries")  # list of log indices, or None for all

    if not target_dir:
        return jsonify({"error": "No target directory"}), 400
    target_dir = resolve(target_dir)  # noqa: F405
    if not os.path.isdir(target_dir):
        return jsonify({"error": f"Directory not found: {target_dir}"}), 404

    entries = load_log()  # noqa: F405
    if entry_indices is not None:
        entries = [entries[i] for i in entry_indices if i < len(entries)]

    results = []
    for entry in entries:
        filename = entry.get("filename", "")
        filepath = os.path.join(target_dir, filename)

        if not os.path.isfile(filepath):
            results.append({"filename": filename, "status": "skipped", "reason": "not found"})
            continue

        metadata = dict(entry.get("metadata") or {})
        msu = (entry.get("metadata_source_url") or "").strip()
        if msu:
            metadata["source_url"] = msu
        artwork_url = entry.get("artwork_url", "")

        artwork_bytes, artwork_mime = None, None
        if artwork_url:
            try:
                artwork_bytes, artwork_mime = fetch_artwork(artwork_url)  # noqa: F405
            except Exception:
                pass

        try:
            apply_metadata(filepath, metadata, artwork_bytes, artwork_mime)  # noqa: F405
            results.append({"filename": filename, "status": "ok"})
        except Exception as e:
            results.append({"filename": filename, "status": "error", "reason": str(e)})

    return jsonify({"results": results})


@app.route("/api/browse-folders")
def browse_folders():
    """
    List subdirectories for a server-side folder picker (Fix Metadata).
    The browser cannot obtain full disk paths from a native dialog; navigation is in-app.
    """
    raw = (request.args.get("path") or "").strip()
    if not raw:
        return jsonify({"error": "path query parameter required"}), 400
    try:
        path = os.path.realpath(resolve(raw))  # noqa: F405
    except (OSError, TypeError) as e:
        return jsonify({"error": str(e)}), 400
    if not os.path.isdir(path):
        return jsonify({"error": f"Not a directory: {path}"}), 404
    par = os.path.dirname(path)
    if par == path:
        parent_path = None
    else:
        parent_path = par
    dirs = []
    try:
        for entry in sorted(Path(path).iterdir()):
            if not entry.is_dir():
                continue
            if entry.name.startswith("."):
                continue
            try:
                dirs.append({"name": entry.name, "path": str(entry.resolve())})
            except OSError:
                continue
    except OSError as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"path": path, "parent": parent_path, "directories": dirs})


@app.route("/api/browse-audio")
def browse_audio():
    cfg = load_config()  # noqa: F405
    directory = request.args.get("dir", cfg["destination_dir"])
    directory = resolve(directory)  # noqa: F405
    if not os.path.isdir(directory):
        return jsonify({"error": f"Directory not found: {directory}"}), 404

    files = []
    for f in sorted(Path(directory).iterdir()):
        if f.suffix.lower() in AUDIO_EXTENSIONS:  # noqa: F405
            files.append({
                "name": f.name,
                "path": str(f),
                "size_mb": round(f.stat().st_size / (1024 * 1024), 1),
            })
    return jsonify({"directory": directory, "files": files})


@app.route("/api/browse-wav")
def browse_wav():
    """List .wav and .aiff/.aif files in a directory (WAV/AIFF → FLAC tab)."""
    cfg = load_config()  # noqa: F405
    directory = request.args.get("dir", cfg.get("destination_dir") or cfg.get("source_dir", ""))
    directory = resolve(directory)  # noqa: F405
    if not os.path.isdir(directory):
        return jsonify({"error": f"Directory not found: {directory}"}), 404

    files = []
    for f in sorted(Path(directory).iterdir()):
        if f.suffix.lower() not in _LOSSLESS_CONVERT_EXTS or not f.is_file():
            continue
        try:
            files.append({
                "name": f.name,
                "path": str(f),
                "size_mb": round(f.stat().st_size / (1024 * 1024), 1),
            })
        except OSError:
            continue
    return jsonify({"directory": directory, "files": files})


@app.route("/api/scan-normalise-bulk")
def scan_normalise_bulk():
    """Count audio files under a root (for bulk normalise UI)."""
    root = (request.args.get("dir") or "").strip()
    if not root:
        return jsonify({"error": "dir query parameter required"}), 400
    recursive = request.args.get("recursive", "0").lower() in ("1", "true", "yes", "on")
    try:
        root_r = os.path.realpath(resolve(root))  # noqa: F405
    except (OSError, TypeError) as e:
        return jsonify({"error": str(e)}), 400
    if not os.path.isdir(root_r):
        return jsonify({"error": f"Not a directory: {root_r}"}), 404
    n = 0
    for _p in _iter_audio_paths(root_r, recursive):  # noqa: F405
        n += 1
    return jsonify({"root": root_r, "count": n, "recursive": recursive})


@app.route("/api/normalise-bulk", methods=["POST"])
def normalise_bulk():
    """Batch normalise audio files under a directory."""
    data = request.get_json() or {}
    files = data.get("files")
    root_dir = (data.get("root_dir") or "").strip()
    recursive = bool(data.get("recursive", False))
    suffix = (data.get("suffix") or "_norm").strip()
    if not suffix.startswith("_"):
        suffix = "_" + suffix
    stream = bool(data.get("stream", False))

    if files:
        paths = [str(f) for f in files if os.path.isfile(str(f))]
    elif root_dir:
        root_r = os.path.realpath(resolve(root_dir))  # noqa: F405
        if not os.path.isdir(root_r):
            return jsonify({"error": f"Not a directory: {root_r}"}), 404
        paths = sorted(_iter_audio_paths(root_r, recursive))  # noqa: F405
    else:
        return jsonify({"error": "Provide files or root_dir"}), 400

    if not paths:
        return jsonify({"error": "No audio files found"}), 400

    cfg = load_config()  # noqa: F405
    profile_key = resolve_extract_profile_key(cfg)  # noqa: F405
    tgt_lufs, tgt_tp = get_normalisation_targets()  # noqa: F405

    def _process():
        normalised = 0
        skipped = 0
        errors = []
        total = len(paths)
        for i, fp in enumerate(paths, 1):
            name = os.path.basename(fp)
            try:
                result = analyse_loudness(fp)  # noqa: F405
                lp = result.get("loudnorm_params")
                if not lp or not _loudnorm_params_usable(lp):  # noqa: F405
                    skipped += 1
                    if stream:
                        yield json.dumps({"type": "progress", "current": i, "total": total,
                                          "file": name, "status": "skipped"}) + "\n"
                    continue
                parent = Path(fp).parent
                stem = Path(fp).stem
                ext = Path(fp).suffix
                out_path = str(parent / f"{stem}{suffix}{ext}")
                _ffmpeg_loudnorm_encode(fp, out_path, lp, profile_key,  # noqa: F405
                                        target_lufs=tgt_lufs, target_tp=tgt_tp)
                _copy_audio_tags_and_art(fp, out_path)  # noqa: F405
                normalised += 1
                if stream:
                    yield json.dumps({"type": "progress", "current": i, "total": total,
                                      "file": name, "status": "ok"}) + "\n"
            except Exception as e:
                errors.append({"file": name, "error": str(e)})
                if stream:
                    yield json.dumps({"type": "progress", "current": i, "total": total,
                                      "file": name, "status": "error", "error": str(e)}) + "\n"
        summary = {"normalised": normalised, "skipped": skipped, "errors": errors, "total": total}
        if stream:
            yield json.dumps({"type": "complete", "summary": summary}) + "\n"
        else:
            yield json.dumps({"summary": summary})

    if stream:
        return Response(_process(), mimetype="application/x-ndjson")
    result_text = "".join(_process())
    return jsonify(json.loads(result_text))


@app.route("/api/scan-wav-bulk")
def scan_wav_bulk():
    """Count .wav and .aiff/.aif files under a root (for bulk convert UI)."""
    root = (request.args.get("path") or request.args.get("root") or "").strip()
    if not root:
        return jsonify({"error": "path or root query parameter required"}), 400
    recursive = request.args.get("recursive", "1").lower() in ("1", "true", "yes", "on")
    try:
        root_r = os.path.realpath(resolve(root))  # noqa: F405
    except (OSError, TypeError) as e:
        return jsonify({"error": str(e)}), 400
    if not os.path.isdir(root_r):
        return jsonify({"error": f"Not a directory: {root_r}"}), 404
    n = 0
    for _p in _iter_lossless_paths(root_r, recursive):
        n += 1
    return jsonify({
        "root": root_r,
        "count": n,
        "recursive": recursive,
    })


@app.route("/api/convert-wav-bulk", methods=["POST"])
def convert_wav_bulk():
    """
    Recursively convert every .wav/.aiff under a root. Sources are not deleted.
    output=same: each .flac next to its source. output=destination: mirroring subpaths under
    Settings destination. output=custom: all FLACs into target_dir, named from parsed
    slot-BPM-artist-title when possible (flat Rekordbox-style library folder).
    """
    data = request.get_json() or {}
    root = (data.get("root_dir") or data.get("path") or data.get("root") or "").strip()
    output_mode = (data.get("output") or "same").strip().lower()
    if output_mode not in ("same", "destination", "custom"):
        output_mode = "same"
    target_dir = (data.get("target_dir") or "").strip()
    rec = data.get("recursive", True)
    if isinstance(rec, str):
        rec = rec.lower() in ("1", "true", "yes", "on")
    skip = data.get("skip_if_flac_exists", True)
    if isinstance(skip, str):
        skip = skip.lower() in ("1", "true", "yes", "on")
    stream = bool(data.get("stream", False))

    raw_off = data.get("offset", 0)
    raw_lim = data.get("limit")
    try:
        offset = int(raw_off)
    except (TypeError, ValueError):
        offset = 0
    offset = max(0, offset)
    limit = None
    if raw_lim is not None and raw_lim != "":
        try:
            limit = int(raw_lim)
        except (TypeError, ValueError):
            limit = None
        if limit is not None:
            limit = max(1, min(limit, 5000))

    if not root:
        return jsonify({"error": "root_dir (or path) required"}), 400
    if output_mode == "custom" and not target_dir:
        return jsonify({
            "error": "Set a target folder (target_dir) when using single-folder output, or change output mode.",
        }), 400
    try:
        root_r = os.path.realpath(resolve(root))  # noqa: F405
    except (OSError, TypeError) as e:
        return jsonify({"error": str(e)}), 400
    if not os.path.isdir(root_r):
        return jsonify({"error": f"Not a directory: {root_r}"}), 404

    target_r = None
    if output_mode == "custom":
        try:
            tpath = resolve(target_dir)  # noqa: F405
            target_r = os.path.realpath(tpath)
            os.makedirs(target_r, exist_ok=True)
        except (OSError, TypeError) as e:
            return jsonify({"error": f"Target folder: {e}"}), 400

    cfg = load_config()  # noqa: F405
    dest_resolved = None
    if output_mode == "destination":
        d = (cfg.get("destination_dir") or "").strip()
        if not d:
            return jsonify({
                "error": "Set a destination folder in Settings, or use “same as each WAV” for output.",
            }), 400
        dpath = resolve(d)  # noqa: F405
        if not os.path.isdir(dpath):
            return jsonify({
                "error": f"Destination folder does not exist: {dpath}",
            }), 400
        dest_resolved = os.path.realpath(dpath)

    all_wavs = _list_lossless_paths_sorted(root_r, rec)
    total_wavs = len(all_wavs)
    if limit is not None:
        wav_queue = all_wavs[offset : offset + limit]
    else:
        wav_queue = all_wavs[offset:]

    def _do_convert():
        ok = 0
        skipped = 0
        errors = []
        err_n = 0
        err_cap = 100
        batch_flac_paths = []
        total = len(wav_queue)
        for i, wav in enumerate(wav_queue, 1):
            stem = Path(wav).stem
            name = os.path.basename(wav)
            if output_mode == "custom" and target_r is not None:
                parsed = parse_ableton_style_wav_stem(stem)  # noqa: F405
                base_fname = _flat_flac_filename_from_parsed(parsed, stem)  # noqa: F405
                candidate = os.path.join(target_r, base_fname)
                if skip and os.path.isfile(candidate):
                    skipped += 1
                    batch_flac_paths.append(os.path.normpath(candidate))
                    if stream:
                        yield json.dumps({"type": "progress", "current": i, "total": total,
                                          "file": name, "status": "skipped"}) + "\n"
                    continue
                if os.path.isfile(candidate):
                    out = _unique_path_in_dir(target_r, base_fname)  # noqa: F405
                else:
                    out = candidate
            else:
                out = _bulk_flac_output_path(wav, root_r, output_mode, dest_resolved)
                if skip and os.path.isfile(out):
                    skipped += 1
                    batch_flac_paths.append(os.path.normpath(out))
                    if stream:
                        yield json.dumps({"type": "progress", "current": i, "total": total,
                                          "file": name, "status": "skipped"}) + "\n"
                    continue
            try:
                _ffmpeg_wav_to_flac_file(wav, out)  # noqa: F405
            except (subprocess.CalledProcessError, OSError) as e:
                err_n += 1
                msg = e.stderr if isinstance(e, subprocess.CalledProcessError) and getattr(e, "stderr", None) else str(e)
                if len(errors) < err_cap:
                    errors.append({"source": wav, "error": (msg or str(e))[:500]})
                if stream:
                    yield json.dumps({"type": "progress", "current": i, "total": total,
                                      "file": name, "status": "error"}) + "\n"
                continue
            try:
                src_ext = Path(wav).suffix.lower()
                if src_ext in (".aiff", ".aif"):
                    _copy_audio_tags_and_art(wav, out)  # noqa: F405
                else:
                    _embed_artist_title_tags_from_wav_stem(out, stem)  # noqa: F405
            except Exception as te:
                err_n += 1
                if len(errors) < err_cap:
                    errors.append({"source": wav, "error": f"Tags: {te}"[:500]})
                if stream:
                    yield json.dumps({"type": "progress", "current": i, "total": total,
                                      "file": name, "status": "error"}) + "\n"
                continue
            ok += 1
            batch_flac_paths.append(os.path.normpath(out))
            if stream:
                yield json.dumps({"type": "progress", "current": i, "total": total,
                                  "file": name, "status": "ok"}) + "\n"
        summary = {"converted": ok, "skipped": skipped, "errors": err_n}
        j = {
            "root": root_r,
            "output": output_mode,
            "summary": summary,
            "errors": errors,
            "batch": {
                "offset": offset,
                "limit": limit,
                "total_wavs": total_wavs,
                "candidates_in_batch": len(wav_queue),
            },
        }
        if target_r is not None:
            j["target_dir"] = target_r
        if batch_flac_paths:
            j["batch_flac_paths"] = batch_flac_paths
        if stream:
            yield json.dumps({"type": "complete", "summary": summary}) + "\n"
        else:
            yield json.dumps(j)

    if stream:
        return Response(_do_convert(), mimetype="application/x-ndjson")
    result_text = "".join(_do_convert())
    return jsonify(json.loads(result_text))


@app.route("/api/bulk-fix/scan-paths", methods=["POST"])
def bulk_fix_scan_paths():
    """
    Build the same scan payload as GET /api/bulk-fix/scan but for an explicit ordered list
    of .flac paths (e.g. output order from a WAV->FLAC bulk run, which may differ from
    folder listing order when flat renaming is used).
    """
    data = request.get_json() or {}
    paths = data.get("paths") or []
    if not isinstance(paths, list):
        return jsonify({"error": "paths must be a list"}), 400
    raw_list = [str(p).strip() for p in paths if (p or "").strip()]
    if not raw_list:
        return jsonify({"error": "paths must be a non-empty list"}), 400
    if len(raw_list) > 200:
        return jsonify({"error": "Maximum 200 paths per scan-paths request."}), 400
    resolved = []
    for p in raw_list:
        try:
            p_r = os.path.realpath(resolve(p))  # noqa: F405
        except (OSError, TypeError):
            continue
        if not os.path.isfile(p_r) or not p_r.lower().endswith(".flac"):
            continue
        resolved.append(p_r)
    resolved = list(dict.fromkeys(resolved))
    if not resolved:
        return jsonify({"error": "No valid .flac files found for the given paths."}), 404
    by_basename = defaultdict(list)
    for p in resolved:
        by_basename[os.path.basename(p)].append(p)
    batch_basenames = [os.path.basename(p) for p in resolved]
    _bc = {}
    for b in batch_basenames:
        _bc[b] = _bc.get(b, 0) + 1
    in_batch_dups = {b for b, c in _bc.items() if c > 1}
    dup_row_count = sum(1 for b in batch_basenames if _bc.get(b, 0) > 1)
    items = []
    for p in resolved:
        base = os.path.basename(p)
        sibs = by_basename.get(base) or []
        n = len(sibs)
        other_paths = [x for x in sibs if x != p]
        info = bulk_fix_search_info_for_flac(p)
        items.append({
            "filepath": p,
            "basename": base,
            "query": info["query"],
            "title_hint": info.get("title_hint") or "",
            "artist_hint": info.get("artist_hint") or "",
            "pattern_matched": info.get("pattern_matched", False),
            "wav_sibling": info.get("wav_sibling") or "",
            "wav_tags": info.get("wav_tags"),
            "duplicate_basename": n > 1,
            "same_basename_count": n,
            "same_basename_other_paths": other_paths[:12],
            "duplicate_in_batch": base in in_batch_dups,
        })
    try:
        root_hint = os.path.commonpath(resolved)
    except ValueError:
        root_hint = os.path.dirname(resolved[0])
    return jsonify({
        "root": root_hint,
        "total": len(resolved),
        "offset": 0,
        "limit": len(resolved),
        "items": items,
        "duplicates_in_batch": dup_row_count,
        "order": "explicit_paths",
    })


@app.route("/api/convert-wav-to-flac", methods=["POST"])
def convert_wav_to_flac():
    """Encode a WAV or AIFF to FLAC with ffmpeg; does not remove or alter the source."""
    data = request.get_json() or {}
    filepath = (data.get("filepath") or "").strip()
    output_mode = (data.get("output") or "same").strip().lower()
    if output_mode not in ("same", "destination"):
        output_mode = "same"
    if not filepath or not os.path.isfile(filepath):
        return jsonify({"error": "File not found"}), 404
    filepath = os.path.realpath(filepath)
    if Path(filepath).suffix.lower() not in _LOSSLESS_CONVERT_EXTS:
        return jsonify({"error": "Only .wav and .aiff source files are supported"}), 400

    cfg = load_config()  # noqa: F405
    stem = Path(filepath).stem
    out_name = f"{stem}.flac"

    if output_mode == "destination":
        dest = (cfg.get("destination_dir") or "").strip()
        if not dest:
            return jsonify({
                "error": "Destination folder is not set. Open Settings and set the destination folder, or choose “Same folder as the WAV file”.",
            }), 400
        dest_dir = resolve(dest)  # noqa: F405
        if not os.path.isdir(dest_dir):
            return jsonify({
                "error": f"Destination folder does not exist: {dest_dir}. Create it or update Settings.",
            }), 400
        output_path = os.path.join(dest_dir, out_name)
    else:
        output_path = str(Path(filepath).with_suffix(".flac"))

    if os.path.exists(output_path):
        return jsonify({"error": f"Output file already exists: {output_path}"}), 409

    try:
        _ffmpeg_wav_to_flac_file(filepath, output_path)  # noqa: F405
    except subprocess.CalledProcessError as e:
        return jsonify({"error": f"ffmpeg failed: {e.stderr or e}"}), 500

    tag_error = None
    try:
        src_ext = Path(filepath).suffix.lower()
        if src_ext in (".aiff", ".aif"):
            _copy_audio_tags_and_art(filepath, output_path)  # noqa: F405
        else:
            _embed_artist_title_tags_from_wav_stem(output_path, stem)  # noqa: F405
    except Exception as e:
        tag_error = str(e)

    try:
        stat = os.stat(output_path)
    except OSError:
        stat = None
    j = {
        "output_path": output_path,
        "source_path": filepath,
        "size_mb": round(stat.st_size / (1024 * 1024), 1) if stat else None,
    }
    if tag_error:
        j["tag_error"] = tag_error
    return jsonify(j)


# Keep old endpoint as alias for backwards compatibility
app.add_url_rule("/api/browse-flacs", endpoint="browse_flacs_compat", view_func=browse_audio)


@app.route("/api/stream-audio")
def stream_audio():
    """Stream a local audio file for the in-browser preview player (HTML5 audio; Range-aware)."""
    raw = (request.args.get("path") or "").strip()
    if not raw:
        return jsonify({"error": "path query parameter required"}), 400
    try:
        path = os.path.realpath(resolve(raw))  # noqa: F405
    except (OSError, TypeError) as e:
        return jsonify({"error": str(e)}), 400
    if not os.path.isfile(path):
        return jsonify({"error": "File not found"}), 404
    try:
        path = _validate_path_in_allowed_dirs(path)  # noqa: F405
    except ValueError as e:
        return jsonify({"error": str(e)}), 403
    ext = Path(path).suffix.lower()
    if ext not in STREAM_AUDIO_EXTENSIONS:  # noqa: F405
        return jsonify({"error": "Unsupported type for streaming"}), 415
    mt = _mime_type_for_stream(ext)  # noqa: F405
    return send_file(path, mimetype=mt, conditional=True, max_age=0)


@app.route("/api/stream-preview")
def stream_preview():
    """Transcode video audio to AAC and stream for browser preview."""
    raw = (request.args.get("path") or "").strip()
    if not raw:
        return jsonify({"error": "path query parameter required"}), 400
    try:
        path = os.path.realpath(resolve(raw))  # noqa: F405
    except (OSError, TypeError) as e:
        return jsonify({"error": str(e)}), 400
    if not os.path.isfile(path):
        return jsonify({"error": "File not found"}), 404
    try:
        path = _validate_path_in_allowed_dirs(path)  # noqa: F405
    except ValueError as e:
        return jsonify({"error": str(e)}), 403
    ext = Path(path).suffix.lower()
    if ext not in VIDEO_SOURCE_EXTENSIONS:  # noqa: F405
        return jsonify({"error": "Unsupported type for preview"}), 415

    cache = _preview_cache_path(path)  # noqa: F405
    if not os.path.isfile(cache):
        fd, tmp = tempfile.mkstemp(suffix=".m4a", dir=_PREVIEW_CACHE_DIR)  # noqa: F405
        os.close(fd)
        try:
            subprocess.run(
                [
                    "ffmpeg", "-hide_banner", "-y",
                    "-i", path,
                    "-vn", "-map", "0:a:0",
                    "-c:a", "aac", "-b:a", "128k",
                    tmp,
                ],
                capture_output=True, text=True, check=True, timeout=300,
            )
            os.replace(tmp, cache)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            msg = getattr(e, "stderr", "") or str(e)
            return jsonify({"error": f"Transcode failed: {msg[:300]}"}), 500

    return send_file(cache, mimetype="audio/mp4", conditional=True, max_age=0)


@app.route("/api/read-tags", methods=["POST"])
def read_tags():
    """Read metadata from any supported audio file."""
    data = request.get_json()
    filepath = data.get("filepath")
    if not filepath or not os.path.isfile(filepath):
        return jsonify({"error": "File not found"}), 404
    try:
        filepath = _validate_path_in_allowed_dirs(filepath)  # noqa: F405
    except ValueError as e:
        return jsonify({"error": str(e)}), 403

    ext = os.path.splitext(filepath)[1].lower()

    try:
        if ext == ".flac":
            return jsonify(_read_flac_tags(filepath))  # noqa: F405
        elif ext == ".mp3":
            return jsonify(_read_mp3_tags(filepath))  # noqa: F405
        elif ext in (".m4a", ".mp4", ".aac"):
            return jsonify(_read_mp4_tags(filepath))  # noqa: F405
        elif ext in (".aiff", ".aif"):
            return jsonify(_read_aiff_tags(filepath))  # noqa: F405
        elif ext in (".ogg", ".oga"):
            return jsonify(_read_vorbis_tags(filepath))  # noqa: F405
        else:
            return jsonify(_read_generic_tags(filepath))  # noqa: F405
    except Exception as e:
        return jsonify({"error": f"Cannot read tags: {e}"}), 400


@app.route("/inspect")
def inspect_page():
    return app.send_static_file("inspect.html")


@app.route("/api/read-tags-full", methods=["POST"])
def read_tags_full():
    """Read all metadata from an audio file including artwork details."""
    data = request.get_json()
    filepath = data.get("filepath")
    if not filepath or not os.path.isfile(filepath):
        return jsonify({"error": "File not found"}), 404
    try:
        filepath = _validate_path_in_allowed_dirs(filepath)  # noqa: F405
    except ValueError as e:
        return jsonify({"error": str(e)}), 403

    ext = os.path.splitext(filepath)[1].lower()
    stat = os.stat(filepath)

    try:
        if ext == ".flac":
            meta = _read_flac_tags(filepath)  # noqa: F405
            audio = FLAC(filepath)
            if audio.pictures:
                pic = audio.pictures[0]
                meta["artwork_info"] = {
                    "mime": pic.mime,
                    "size_bytes": len(pic.data),
                    "width": pic.width,
                    "height": pic.height,
                    "type": pic.type,
                }
        elif ext == ".mp3":
            meta = _read_mp3_tags(filepath)  # noqa: F405
            audio = MP3(filepath, ID3=ID3)
            if audio.tags:
                apics = audio.tags.getall("APIC")
                if apics:
                    pic = apics[0]
                    meta["artwork_info"] = {
                        "mime": pic.mime,
                        "size_bytes": len(pic.data),
                        "type": pic.type,
                    }
        elif ext in (".m4a", ".mp4", ".aac"):
            meta = _read_mp4_tags(filepath)  # noqa: F405
            audio = MP4(filepath)
            if audio.tags and audio.tags.get("covr"):
                covr = audio.tags["covr"][0]
                fmt_name = "JPEG" if covr.imageformat == MP4Cover.FORMAT_JPEG else "PNG"
                meta["artwork_info"] = {
                    "mime": f"image/{'jpeg' if fmt_name == 'JPEG' else 'png'}",
                    "size_bytes": len(bytes(covr)),
                    "format": fmt_name,
                }
        elif ext in (".aiff", ".aif"):
            meta = _read_aiff_tags(filepath)  # noqa: F405
            from mutagen.aiff import AIFF as _AIFF
            audio = _AIFF(filepath)
            if audio.tags:
                apics = audio.tags.getall("APIC")
                if apics:
                    pic = apics[0]
                    meta["artwork_info"] = {
                        "mime": pic.mime,
                        "size_bytes": len(pic.data),
                        "type": pic.type,
                    }
        elif ext in (".ogg", ".oga"):
            meta = _read_vorbis_tags(filepath)  # noqa: F405
        else:
            meta = _read_generic_tags(filepath)  # noqa: F405
    except Exception as e:
        return jsonify({"error": f"Cannot read tags: {e}"}), 400

    meta["file_info"] = {
        "path": filepath,
        "name": os.path.basename(filepath),
        "size_mb": round(stat.st_size / (1024 * 1024), 1),
        "extension": ext,
    }

    return jsonify(meta)


@app.route("/api/embedded-artwork-img")
def embedded_artwork_img():
    """GET endpoint to serve embedded artwork (for img src)."""
    filepath = request.args.get("path", "")
    return _serve_embedded_artwork(filepath)


@app.route("/api/embedded-artwork", methods=["POST"])
def embedded_artwork():
    """POST endpoint to serve embedded artwork."""
    data = request.get_json()
    filepath = data.get("filepath", "")
    return _serve_embedded_artwork(filepath)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5123, debug=True)
