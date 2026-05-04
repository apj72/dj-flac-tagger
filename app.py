import base64
import difflib
import json
from collections import defaultdict
import os
import re
import time
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus, urlunparse, urlparse

import requests
from bs4 import BeautifulSoup
from flask import Flask, jsonify, request
import mutagen
from mutagen.flac import FLAC, Picture
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4, MP4Cover
from mutagen.id3 import ID3, APIC, TIT2, TPE1, TPE2, TALB, TDRC, TCON, COMM, TPUB, TRCK, TXXX
from mutagen.oggvorbis import OggVorbis

AUDIO_EXTENSIONS = (".flac", ".mp3", ".m4a", ".mp4", ".aac", ".ogg", ".oga", ".wma", ".aiff", ".aif")

# System-wide extract / normalise output format (see Settings: extract_profile).
EXTRACT_PROFILES = {
    "flac": {
        "label": "FLAC (lossless)",
        "ext": ".flac",
        "lossless": True,
        "ffmpeg_encode": ["-c:a", "flac", "-compression_level", "12", "-sample_fmt", "s16"],
    },
    "mp3_320": {
        "label": "MP3 320 kbps CBR",
        "ext": ".mp3",
        "lossless": False,
        "ffmpeg_encode": ["-c:a", "libmp3lame", "-b:a", "320k"],
    },
    "aac_256": {
        "label": "AAC 256 kbps (M4A)",
        "ext": ".m4a",
        "lossless": False,
        "ffmpeg_encode": ["-c:a", "aac", "-b:a", "256k"],
    },
}


def resolve_extract_profile_key(cfg=None):
    if cfg is None:
        cfg = load_config()
    k = (cfg.get("extract_profile") or "flac").strip().lower()
    if k in EXTRACT_PROFILES:
        return k
    return "flac"


def extract_profile_options():
    return [{"key": key, "label": val["label"]} for key, val in EXTRACT_PROFILES.items()]


def bundle_base_path():
    """Root directory containing bundled `static/` and `config.json.example` (PyInstaller: `sys._MEIPASS`)."""
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
        # Fallback: sibling of launcher executable inside an .app bundle
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def writable_app_data_dir():
    """Per-user directory for settings and logs when bundled (writable path outside code signature)."""
    if sys.platform == "darwin":
        p = Path.home() / "Library" / "Application Support" / "DJ MetaManager"
    elif os.name == "nt":
        local = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        p = Path(local) / "DJ MetaManager"
    else:
        p = Path.home() / ".config" / "dj-meta-manager"
    try:
        p.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return p


def _default_config_path():
    if getattr(sys, "frozen", False):
        return str(writable_app_data_dir() / "config.json")
    return str(Path(__file__).resolve().parent / "config.json")


def _default_log_path():
    if getattr(sys, "frozen", False):
        return str(writable_app_data_dir() / "processing_log.json")
    return str(Path(__file__).resolve().parent / "processing_log.json")


def _prepend_bundled_ffmpeg_to_path():
    """If FFmpeg was shipped beside the frozen build, use it instead of relying on PATH."""
    base = bundle_base_path()
    for tools_dir in (
        base / "ffmpeg-mac" / "bin",
        base / "ffmpeg" / "bin",
        base / "bin",
        base,
    ):
        ffmpeg = tools_dir / "ffmpeg"
        if ffmpeg.is_file() and os.access(ffmpeg, os.X_OK):
            os.environ["PATH"] = str(tools_dir) + os.pathsep + os.environ.get("PATH", "")


_prepend_bundled_ffmpeg_to_path()

app = Flask(__name__, static_folder=str(bundle_base_path() / "static"))

CONFIG_PATH = _default_config_path()


def load_config():
    defaults = {
        "source_dir": "~/DJ-Mixes",
        "destination_dir": "~/Music/DJ-library",
        # Default folder when opening Fix Metadata / Inspect (empty = use destination_dir)
        "fix_metadata_default_dir": "",
        "inspect_default_dir": "",
        # Exact app name as shown by macOS "open -a" (e.g. "Platinum Notes")
        "platinum_notes_app": "",
        # Platinum Notes default output: <stem>_PN.<ext> (same extension family as input)
        "pn_output_suffix": "_PN",
        # EBU R128 loudnorm targets (integrated LUFS, true-peak ceiling dBTP).
        # Platinum Notes is often around -11.5 LUFS; streaming reference is -14.
        "target_lufs": -14.0,
        "target_true_peak": -1.0,
        # extract_profile: flac | mp3_320 | aac_256
        "extract_profile": "flac",
        # When normalised extract finishes, re-measure the output; if I/TP miss Settings, re-encode once
        # from a fresh source analysis (stale client loudnorm params caused rare over-boost; PN gets a good base).
        "loudness_verify_enabled": True,
        "loudness_verify_tolerance_lufs": 2.0,
        "loudness_verify_tolerance_tp": 0.35,
        # When False, selecting a .mkv on Extract skips client-side LUFS / volumedetect (faster; meters hidden).
        "extract_mkv_audio_analysis_enabled": True,
        # Fix Metadata / Bulk Fix: peel these from the end of the filename stem before building search queries.
        # Use a list of strings: literal suffixes (matched with endswith), or "regex:..." with a Python regex
        # that must match the end of the stem (typically end your pattern with $). Peeled segments are appended
        # back when renaming to Artist - Title. Example: ["_warped", "regex:_bpm\\([A-Za-z0-9]{3}\\)$"]
        "fix_retain_filename_suffixes": [],
    }
    try:
        with open(CONFIG_PATH) as f:
            cfg = json.load(f)
        defaults.update(cfg)
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return defaults


def save_config(cfg):
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)
        f.write("\n")


def resolve(path):
    return os.path.expanduser(path)


def get_normalisation_targets():
    """LUFS / dBTP targets from config (defaults -14 / -1). Positive LUFS values are treated as negative (e.g. 11.5 → -11.5)."""
    cfg = load_config()
    try:
        lufs = float(cfg.get("target_lufs", -14.0))
    except (TypeError, ValueError):
        lufs = -14.0
    if lufs > 0:
        lufs = -abs(lufs)
    lufs = max(-24.0, min(-3.0, lufs))

    try:
        tp = float(cfg.get("target_true_peak", -1.0))
    except (TypeError, ValueError):
        tp = -1.0
    if tp > 0:
        tp = -abs(tp)
    tp = max(-3.0, min(0.0, tp))

    return lufs, tp


LOG_PATH = _default_log_path()


def load_log():
    try:
        with open(LOG_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_log(entries):
    with open(LOG_PATH, "w") as f:
        json.dump(entries, f, indent=2)
        f.write("\n")


def log_extraction(entry):
    entries = load_log()
    entry["timestamp"] = datetime.now().isoformat()
    entries.append(entry)
    save_log(entries)
    return len(entries) - 1


SOURCE_URL_VORBIS = "DJMETAMANAGER_SOURCE_URL"
SOURCE_URL_VORBIS_LEGACY = "DJFLACTAGGER_SOURCE_URL"
SOURCE_URL_ID3_DESC = "DJMETAMANAGER_SOURCE_URL"
SOURCE_URL_ID3_DESC_LEGACY = "DJFLACTAGGER_SOURCE_URL"


def _source_url_from_vorbis(audio):
    for key in (SOURCE_URL_VORBIS, SOURCE_URL_VORBIS_LEGACY):
        vals = audio.get(key, [])
        if vals:
            return vals[0]
    return None


def infer_metadata_source_type(url):
    if not url:
        return ""
    u = url.lower()
    if "bandcamp.com" in u:
        return "bandcamp"
    if "discogs.com" in u:
        return "discogs"
    if "music.apple.com" in u or "itunes.apple.com" in u:
        return "apple_music"
    if "spotify.com" in u or "spotify.link" in u:
        return "spotify"
    if "soundcloud.com" in u:
        return "soundcloud"
    if "beatport.com" in u:
        return "beatport"
    try:
        host = urlparse(url).netloc.lower()
        if host:
            return host.split(":")[0]
    except Exception:
        pass
    return "url"


def find_log_entry_for_output_path(base_path, log_index=None):
    """Match a processing-log entry to an extracted audio path (or explicit index)."""
    entries = load_log()
    if log_index is not None:
        if 0 <= log_index < len(entries):
            return entries[log_index], log_index
        return None, None
    if not base_path:
        return None, None
    base_norm = os.path.normpath(os.path.abspath(base_path))
    for i in range(len(entries) - 1, -1, -1):
        e = entries[i]
        op = e.get("output_path") or e.get("target_path") or ""
        if not op:
            continue
        try:
            if os.path.normpath(os.path.abspath(op)) == base_norm:
                return e, i
        except OSError:
            continue
    return None, None


def post_extract_open_app(app_name, file_path):
    """Launch a GUI app with a file (e.g. Platinum Notes). No public CLI; this uses OS hooks."""
    if not app_name or not file_path or not os.path.isfile(file_path):
        return
    try:
        if sys.platform == "darwin":
            subprocess.Popen(
                ["open", "-n", "-a", app_name, file_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        elif sys.platform == "win32":
            os.startfile(file_path)  # noqa: S606 — opens default handler; PN may still be manual
        else:
            subprocess.Popen(["xdg-open", file_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def pn_derivative_path(base_audio_path, suffix):
    """Platinum Notes-style sibling: <stem><suffix>.<same ext as base>."""
    p = Path(base_audio_path)
    return p.parent / f"{p.stem}{suffix}{p.suffix}"


def _pn_output_candidate_paths(
    base_flac_path: str,
    suffix: str,
    *,
    copied_to: str = None,
    destination_dir: str = None,
) -> list:
    """
    Where a PN output file might live: beside the extract, beside the library copy,
    or flat in Settings destination (e.g. user configures Platinum Notes to write to FLACs).
    """
    p = Path(base_flac_path)
    name = f"{p.stem}{suffix}{p.suffix}"
    seen = set()
    out = []

    def add(path_str: str) -> None:
        try:
            n = os.path.normpath(path_str)
        except (OSError, TypeError, ValueError):
            n = path_str
        if n and n not in seen:
            seen.add(n)
            out.append(n)

    add(str(pn_derivative_path(base_flac_path, suffix)))
    if (copied_to or "").strip():
        try:
            add(str(Path((copied_to or "").strip()).parent / name))
        except (OSError, ValueError):
            pass
    d = (destination_dir or "").strip()
    if d:
        try:
            dpath = resolve(d)
            add(os.path.join(dpath, name))
        except (OSError, TypeError):
            pass
    return out


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run_ffprobe(filepath):
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_streams", "-select_streams", "a:0",
            "-show_entries",
            "stream=codec_name,sample_rate,channels,duration,channel_layout,bits_per_raw_sample",
            "-show_entries", "format=duration",
            "-of", "json",
            filepath,
        ],
        capture_output=True, text=True,
    )
    return json.loads(result.stdout)


def _loudnorm_tail_aformat_and_rate(input_path):
    """Sample rate (int or None) and aformat=… string matching source layout (keeps 48 kHz vs accidental 192 kHz bloat)."""
    info = run_ffprobe(input_path)
    stream = info["streams"][0] if info.get("streams") else {}
    sr = stream.get("sample_rate")
    ch = stream.get("channels")
    if not sr or ch is None:
        return None, "sample_fmts=s16"
    sr_i = int(float(sr))
    ch_i = int(ch)
    layout = stream.get("channel_layout")
    if isinstance(layout, str):
        layout = layout.strip()
    else:
        layout = ""
    if layout.lower() in ("", "unknown"):
        layout = "mono" if ch_i == 1 else "stereo" if ch_i == 2 else ""
    parts = ["sample_fmts=s16", f"sample_rates={sr_i}"]
    if layout:
        parts.append(f"channel_layouts={layout}")
    return sr_i, ":".join(parts)


def _aformat_opts_preserve_stream(input_path):
    """Backward-compatible: aformat options only (tests / callers)."""
    _, opts = _loudnorm_tail_aformat_and_rate(input_path)
    return opts


def analyse_loudness(filepath):
    """Run ffmpeg loudnorm + volumedetect analysis on an audio/video file."""
    result = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-i", filepath,
            "-af", "loudnorm=print_format=json",
            "-f", "null", "-",
        ],
        capture_output=True, text=True,
    )
    stderr = result.stderr

    loudnorm = {}
    json_start = stderr.rfind("{")
    json_end = stderr.rfind("}") + 1
    if json_start != -1 and json_end > json_start:
        try:
            loudnorm = json.loads(stderr[json_start:json_end])
        except json.JSONDecodeError:
            pass

    vol_result = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-i", filepath,
            "-af", "volumedetect",
            "-f", "null", "-",
        ],
        capture_output=True, text=True,
    )
    vol_stderr = vol_result.stderr

    mean_vol = None
    max_vol = None
    for line in vol_stderr.splitlines():
        if "mean_volume" in line:
            m = re.search(r"mean_volume:\s*([-\d.]+)", line)
            if m:
                mean_vol = float(m.group(1))
        if "max_volume" in line:
            m = re.search(r"max_volume:\s*([-\d.]+)", line)
            if m:
                max_vol = float(m.group(1))

    tl, ttp = get_normalisation_targets()
    return {
        "integrated_lufs": float(loudnorm.get("input_i", 0)),
        "true_peak": float(loudnorm.get("input_tp", 0)),
        "lra": float(loudnorm.get("input_lra", 0)),
        "threshold": float(loudnorm.get("input_thresh", 0)),
        "mean_volume": mean_vol,
        "max_volume": max_vol,
        "target_lufs": tl,
        "target_tp": ttp,
        "loudnorm_params": loudnorm,
    }


def _loudnorm_params_usable(loudnorm_params):
    """True if ffmpeg returned measured input_* for two-pass EBU R128."""
    if not loudnorm_params or "input_i" not in loudnorm_params:
        return False
    return True


def normalised_output_meets_targets(
    loudnorm_params,
    target_lufs,
    target_tp,
    tol_lufs=2.0,
    tol_tp=0.35,
):
    """
    Check first-pass I/TP of a *rendered* file against Settings (same as diagnostic script).
    Fails e.g. when true peak is above the configured ceiling.
    """
    if not _loudnorm_params_usable(loudnorm_params):
        return False, ["loudnorm measurement missing or empty (ffmpeg)"]
    try:
        i = float(loudnorm_params.get("input_i", -99))
        tp = float(loudnorm_params.get("input_tp", 99))
    except (TypeError, ValueError):
        return False, ["invalid input_i or input_tp in loudnorm result"]
    reasons = []
    ok = True
    if abs(i - target_lufs) > tol_lufs:
        ok = False
        reasons.append(
            f"integrated {i:+.2f} LUFS vs target {target_lufs:+.2f} (±{tol_lufs} LUFS allowed)"
        )
    if tp > target_tp + tol_tp:
        ok = False
        reasons.append(
            f"true peak {tp:+.2f} dBTP vs ceiling {target_tp:+.2f} (max +{tol_tp} dB over ceiling)"
        )
    return ok, reasons


def _ffmpeg_loudnorm_encode(input_path, output_path, loudnorm_params, profile_key, target_lufs=None, target_tp=None):
    """Two-pass EBU R128 loudnorm — measured_* from analyse_loudness (first pass); encode per extract profile."""
    if not loudnorm_params:
        raise ValueError("loudnorm_params required")
    prof = EXTRACT_PROFILES.get(profile_key) or EXTRACT_PROFILES["flac"]
    if target_lufs is None or target_tp is None:
        target_lufs, target_tp = get_normalisation_targets()
    loudnorm = (
        f"loudnorm=I={target_lufs}:TP={target_tp}:LRA=11"
        f":measured_I={loudnorm_params.get('input_i', -24)}"
        f":measured_TP={loudnorm_params.get('input_tp', -2)}"
        f":measured_LRA={loudnorm_params.get('input_lra', 7)}"
        f":measured_thresh={loudnorm_params.get('input_thresh', -34)}"
        f":linear=true:print_format=json"
    )
    sr_i, aformat_opts = _loudnorm_tail_aformat_and_rate(input_path)
    af = f"{loudnorm},aformat={aformat_opts}"
    ar_args = ["-ar", str(sr_i)] if sr_i is not None else []
    out_suffix = Path(output_path).suffix.lower()
    flac_bin = shutil.which("flac")
    if prof.get("lossless") and out_suffix == ".flac" and flac_bin:
        fd, wav_path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        try:
            subprocess.run(
                [
                    "ffmpeg", "-hide_banner", "-y", "-i", input_path,
                    "-map", "0:a:0", "-vn", "-af", af,
                    *ar_args,
                    "-f", "wav", wav_path,
                ],
                capture_output=True, text=True, check=True,
            )
            subprocess.run(
                [
                    flac_bin, "-f", "--best", "-e", "-p",
                    "-o", output_path, wav_path,
                ],
                capture_output=True, text=True, check=True,
            )
        finally:
            try:
                os.unlink(wav_path)
            except OSError:
                pass
    else:
        cmd = [
            "ffmpeg", "-hide_banner", "-y", "-i", input_path,
            "-map", "0:a:0", "-vn", "-af", af,
            *ar_args,
            *prof["ffmpeg_encode"],
            output_path,
        ]
        subprocess.run(cmd, capture_output=True, text=True, check=True)


def read_embedded_artwork(filepath):
    """Return (bytes, mime) for first embedded cover, or (None, None)."""
    ext = Path(filepath).suffix.lower()
    try:
        if ext == ".flac":
            audio = FLAC(filepath)
            if audio.pictures:
                pic = audio.pictures[0]
                return pic.data, pic.mime or "image/jpeg"
        elif ext == ".mp3":
            audio = MP3(filepath, ID3=ID3)
            if audio.tags:
                apics = audio.tags.getall("APIC")
                if apics:
                    a = apics[0]
                    return a.data, a.mime or "image/jpeg"
        elif ext in (".m4a", ".mp4", ".aac"):
            audio = MP4(filepath)
            if audio.tags and audio.tags.get("covr"):
                covr = audio.tags["covr"][0]
                mime = "image/jpeg" if covr.imageformat == MP4Cover.FORMAT_JPEG else "image/png"
                return bytes(covr), mime
        elif ext in (".ogg", ".oga"):
            audio = OggVorbis(filepath)
            pics = audio.get("metadata_block_picture")
            if pics:
                pic = Picture()
                pic.load(base64.b64decode(pics[0]))
                return pic.data, pic.mime or "image/jpeg"
    except Exception:
        pass
    return None, None


def _metadata_dict_for_copy(src_path):
    """Fields suitable for apply_metadata after transcoding."""
    ext = Path(src_path).suffix.lower()
    if ext == ".flac":
        meta = _read_flac_tags(src_path)
    elif ext == ".mp3":
        meta = _read_mp3_tags(src_path)
    elif ext in (".m4a", ".mp4", ".aac"):
        meta = _read_mp4_tags(src_path)
    elif ext in (".ogg", ".oga"):
        meta = _read_vorbis_tags(src_path)
    else:
        meta = _read_generic_tags(src_path)
    skip = {"format", "has_artwork", "error", "artwork_info"}
    return {k: v for k, v in meta.items() if k not in skip and v}


def _copy_audio_tags_and_art(src_path, dst_path):
    """Re-apply tags and embedded artwork from src onto dst (any supported apply_metadata type)."""
    meta = _metadata_dict_for_copy(src_path)
    art_bytes, art_mime = read_embedded_artwork(src_path)
    apply_metadata(dst_path, meta, art_bytes, art_mime)


def extract_audio(src_path, output_path, profile_key, normalise=False, loudnorm_params=None):
    prof = EXTRACT_PROFILES.get(profile_key) or EXTRACT_PROFILES["flac"]
    info = run_ffprobe(src_path)
    codec = info["streams"][0]["codec_name"] if info.get("streams") else "unknown"

    if normalise and loudnorm_params:
        _ffmpeg_loudnorm_encode(src_path, output_path, loudnorm_params, profile_key)
        return codec
    if prof["ext"] == ".flac" and codec == "flac":
        cmd = ["ffmpeg", "-hide_banner", "-y", "-i", src_path, "-vn", "-c:a", "copy", output_path]
    else:
        cmd = [
            "ffmpeg", "-hide_banner", "-y", "-i", src_path,
            "-vn", "-map", "0:a:0",
            *prof["ffmpeg_encode"],
            output_path,
        ]
    subprocess.run(cmd, capture_output=True, text=True, check=True)
    return codec


def trash_file(filepath):
    """Move a file to macOS Bin via Finder (recoverable)."""
    script = (
        f'tell application "Finder" to delete '
        f'(POSIX file "{filepath}" as alias)'
    )
    subprocess.run(["osascript", "-e", script], capture_output=True, text=True, check=True)


def apply_metadata(filepath, metadata, artwork_bytes=None, artwork_mime=None):
    ext = os.path.splitext(filepath)[1].lower()

    if ext == ".flac":
        _apply_flac(filepath, metadata, artwork_bytes, artwork_mime)
    elif ext == ".mp3":
        _apply_mp3(filepath, metadata, artwork_bytes, artwork_mime)
    elif ext in (".m4a", ".mp4", ".aac"):
        _apply_mp4(filepath, metadata, artwork_bytes, artwork_mime)
    elif ext in (".ogg", ".oga"):
        _apply_vorbis(filepath, metadata, artwork_bytes, artwork_mime)
    else:
        _apply_generic(filepath, metadata, artwork_bytes, artwork_mime)


def _image_dimensions(data):
    """Read width/height from JPEG or PNG binary data."""
    import struct
    if data[:8] == b'\x89PNG\r\n\x1a\n' and len(data) >= 24:
        w, h = struct.unpack('>II', data[16:24])
        return w, h
    if data[:2] == b'\xff\xd8':
        i = 2
        while i < len(data) - 1:
            if data[i] != 0xff:
                break
            marker = data[i + 1]
            if marker in (0xc0, 0xc1, 0xc2):
                if i + 9 < len(data):
                    h, w = struct.unpack('>HH', data[i + 5:i + 9])
                    return w, h
                break
            if marker in (0xd0, 0xd1, 0xd2, 0xd3, 0xd4, 0xd5, 0xd6, 0xd7, 0xd8, 0xd9, 0x01):
                i += 2
                continue
            if i + 3 < len(data):
                seg_len = struct.unpack('>H', data[i + 2:i + 4])[0]
                i += 2 + seg_len
            else:
                break
    return 0, 0


def _apply_flac(filepath, metadata, artwork_bytes, artwork_mime):
    audio = FLAC(filepath)
    vorbis_map = {
        "title": "title", "artist": "artist", "albumartist": "albumartist",
        "album": "album", "date": "date", "genre": "genre", "comment": "comment",
        "tracknumber": "tracknumber", "label": "organization", "catno": "catalognumber",
    }
    for key, vorbis_key in vorbis_map.items():
        val = metadata.get(key)
        if val:
            audio[vorbis_key] = [val]
    su = (metadata.get("source_url") or "").strip()
    if su:
        audio[SOURCE_URL_VORBIS] = [su]
        if SOURCE_URL_VORBIS_LEGACY in audio:
            del audio[SOURCE_URL_VORBIS_LEGACY]
    if artwork_bytes:
        pic = Picture()
        pic.type = 3
        pic.mime = artwork_mime or "image/jpeg"
        pic.desc = "Cover"
        pic.data = artwork_bytes
        pic.width, pic.height = _image_dimensions(artwork_bytes)
        audio.clear_pictures()
        audio.add_picture(pic)
    audio.save()


def _apply_mp3(filepath, metadata, artwork_bytes, artwork_mime):
    audio = MP3(filepath, ID3=ID3)
    try:
        audio.add_tags()
    except mutagen.id3.error:
        pass
    t = audio.tags
    id3_map = {
        "title": TIT2, "artist": TPE1, "albumartist": TPE2,
        "album": TALB, "genre": TCON,
    }
    for key, frame_cls in id3_map.items():
        val = metadata.get(key)
        if val:
            t.delall(frame_cls.__name__)
            t.add(frame_cls(encoding=3, text=[val]))
    if metadata.get("date"):
        t.delall("TDRC")
        t.add(TDRC(encoding=3, text=[metadata["date"]]))
    if metadata.get("tracknumber"):
        t.delall("TRCK")
        t.add(TRCK(encoding=3, text=[metadata["tracknumber"]]))
    if metadata.get("comment"):
        t.delall("COMM")
        t.add(COMM(encoding=3, lang="eng", desc="", text=[metadata["comment"]]))
    if metadata.get("label"):
        t.delall("TPUB")
        t.add(TPUB(encoding=3, text=[metadata["label"]]))
    if metadata.get("catno"):
        t.delall("TXXX:CATALOGNUMBER")
        t.add(TXXX(encoding=3, desc="CATALOGNUMBER", text=[metadata["catno"]]))
    su = (metadata.get("source_url") or "").strip()
    if su:
        t.delall(f"TXXX:{SOURCE_URL_ID3_DESC}")
        t.delall(f"TXXX:{SOURCE_URL_ID3_DESC_LEGACY}")
        t.add(TXXX(encoding=3, desc=SOURCE_URL_ID3_DESC, text=[su]))
    if artwork_bytes:
        t.delall("APIC")
        t.add(APIC(encoding=3, mime=artwork_mime or "image/jpeg", type=3, desc="Cover", data=artwork_bytes))
    audio.save(v2_version=3)


def _apply_mp4(filepath, metadata, artwork_bytes, artwork_mime):
    audio = MP4(filepath)
    if audio.tags is None:
        audio.add_tags()
    mp4_map = {
        "title": "\xa9nam", "artist": "\xa9ART", "albumartist": "aART",
        "album": "\xa9alb", "date": "\xa9day", "genre": "\xa9gen",
        "comment": "\xa9cmt",
    }
    for key, atom in mp4_map.items():
        val = metadata.get(key)
        if val:
            audio.tags[atom] = [val]
    if metadata.get("tracknumber"):
        try:
            tnum = int(metadata["tracknumber"])
            audio.tags["trkn"] = [(tnum, 0)]
        except ValueError:
            pass
    if artwork_bytes:
        fmt = MP4Cover.FORMAT_JPEG
        if artwork_mime and "png" in artwork_mime:
            fmt = MP4Cover.FORMAT_PNG
        audio.tags["covr"] = [MP4Cover(artwork_bytes, imageformat=fmt)]
    audio.save()


def _apply_vorbis(filepath, metadata, artwork_bytes, artwork_mime):
    audio = OggVorbis(filepath)
    vorbis_map = {
        "title": "title", "artist": "artist", "albumartist": "albumartist",
        "album": "album", "date": "date", "genre": "genre", "comment": "comment",
        "tracknumber": "tracknumber", "label": "organization", "catno": "catalognumber",
    }
    for key, vorbis_key in vorbis_map.items():
        val = metadata.get(key)
        if val:
            audio[vorbis_key] = [val]
    su = (metadata.get("source_url") or "").strip()
    if su:
        audio[SOURCE_URL_VORBIS] = [su]
        if SOURCE_URL_VORBIS_LEGACY in audio:
            del audio[SOURCE_URL_VORBIS_LEGACY]
    if artwork_bytes:
        import base64
        pic = Picture()
        pic.type = 3
        pic.mime = artwork_mime or "image/jpeg"
        pic.desc = "Cover"
        pic.data = artwork_bytes
        pic.width, pic.height = _image_dimensions(artwork_bytes)
        audio["metadata_block_picture"] = [base64.b64encode(pic.write()).decode("ascii")]
    audio.save()


def _apply_generic(filepath, metadata, artwork_bytes, artwork_mime):
    """Fallback using mutagen.File for any other supported format."""
    audio = mutagen.File(filepath, easy=True)
    if audio is None:
        raise ValueError(f"Unsupported file format: {filepath}")
    if audio.tags is None:
        audio.add_tags()
    easy_map = {"title": "title", "artist": "artist", "albumartist": "albumartist",
                "album": "album", "date": "date", "genre": "genre"}
    for key, tag in easy_map.items():
        val = metadata.get(key)
        if val:
            try:
                audio[tag] = [val]
            except (KeyError, mutagen.MutagenError):
                pass
    audio.save()


# ---------------------------------------------------------------------------
# Scrapers
# ---------------------------------------------------------------------------

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

DISCOGS_HEADERS = {"User-Agent": "DJMetaManager/1.0 +https://github.com/apj72/dj-meta-manager"}


def _response_text_utf8(resp: requests.Response) -> str:
    """
    Decode HTML (or other text) body as UTF-8. Many sites omit charset or default to
    ISO-8859-1 in requests, which mojibakes non-ASCII (e.g. André → AndrÃ©).
    """
    return (resp.content or b"").decode("utf-8", errors="replace")


def _ld_json_script_text(tag) -> str:
    """Raw JSON-LD string from a script tag (BeautifulSoup .string can be None on some trees)."""
    if tag is None:
        return ""
    s = tag.string
    if s is not None and str(s).strip():
        return str(s).strip()
    return (tag.get_text() or "").strip()


def scrape_bandcamp(url):
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(_response_text_utf8(resp), "lxml")

    meta = {}

    ld_json = soup.find("script", type="application/ld+json")
    if ld_json:
        try:
            data = json.loads(_ld_json_script_text(ld_json))
            if isinstance(data, list):
                data = data[0]

            meta["title"] = data.get("name", "")

            if "inAlbum" in data:
                album = data["inAlbum"]
                meta["album"] = album.get("name", "")
                if "byArtist" in album:
                    meta["albumartist"] = album["byArtist"].get("name", "")

            if "byArtist" in data:
                meta["artist"] = data["byArtist"].get("name", "")

            if "datePublished" in data:
                year_match = re.search(r"(\d{4})", data["datePublished"])
                if year_match:
                    meta["date"] = year_match.group(1)

            if "image" in data:
                meta["artwork_url"] = data["image"]

        except (json.JSONDecodeError, KeyError):
            pass

    if not meta.get("title"):
        name_section = soup.find("h2", class_="trackTitle")
        if name_section:
            meta["title"] = name_section.get_text(strip=True)

    if not meta.get("artist"):
        artist_span = soup.find("span", itemprop="byArtist")
        if artist_span:
            meta["artist"] = artist_span.get_text(strip=True)

    if not meta.get("artwork_url"):
        og_image = soup.find("meta", property="og:image")
        if og_image:
            meta["artwork_url"] = og_image.get("content", "")

    tag_els = soup.select(".tralbumData.tralbum-tags a.tag")
    if tag_els:
        tags = [t.get_text(strip=True) for t in tag_els]
        meta["genre"] = " / ".join(tags[:3])

    return meta


def apple_music_hires_artwork(url):
    """Convert any Apple Music artwork URL to 1200x1200."""
    if not url:
        return ""
    return re.sub(r"/\d+x\d+[^/]*\.\w+$", "/1200x1200bb.jpg", url)


def scrape_apple_music(url):
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(_response_text_utf8(resp), "lxml")

    meta = {}
    is_album = "/album/" in url

    # --- LD+JSON (works for songs, partial for albums) ---
    ld_json = soup.find("script", type="application/ld+json")
    if ld_json:
        try:
            data = json.loads(_ld_json_script_text(ld_json))
            meta["title"] = data.get("name", "")

            if "datePublished" in data:
                year_match = re.search(r"(\d{4})", data["datePublished"])
                if year_match:
                    meta["date"] = year_match.group(1)

            audio = data.get("audio", {})

            if audio.get("byArtist"):
                meta["artist"] = " / ".join(
                    a.get("name", "") for a in audio["byArtist"]
                )

            album_info = audio.get("inAlbum", {})
            if album_info:
                meta["album"] = album_info.get("name", "")
                if album_info.get("byArtist"):
                    meta["albumartist"] = " / ".join(
                        a.get("name", "") for a in album_info["byArtist"]
                    )
                meta["artwork_url"] = apple_music_hires_artwork(
                    album_info.get("image", "")
                )

            if not meta.get("artwork_url"):
                meta["artwork_url"] = apple_music_hires_artwork(
                    data.get("image", "")
                )

            genres = audio.get("genre", [])
            if isinstance(genres, list):
                genres = [g for g in genres if g.lower() != "music"]
                if genres:
                    meta["genre"] = " / ".join(genres)

        except (json.JSONDecodeError, KeyError):
            pass

    # --- OG tag fallbacks ---
    if not meta.get("title"):
        og_title = soup.find("meta", property="og:title")
        if og_title:
            title_text = og_title.get("content", "")
            by_split = title_text.split(" by ")
            if by_split:
                meta["title"] = by_split[0].strip()

    if not meta.get("artwork_url"):
        og_image = soup.find("meta", property="og:image")
        if og_image:
            meta["artwork_url"] = apple_music_hires_artwork(
                og_image.get("content", "")
            )

    if not meta.get("genre"):
        og_desc = soup.find("meta", property="og:description")
        if og_desc:
            desc = og_desc.get("content", "")
            meta["_description"] = desc

    if not meta.get("date"):
        rel = soup.find("meta", property="music:release_date")
        if rel:
            ym = re.search(r"(\d{4})", rel.get("content", ""))
            if ym:
                meta["date"] = ym.group(1)

    # --- Extract artist name from og:title ("Album by Artist on Apple Music") ---
    if not meta.get("artist"):
        og_title = soup.find("meta", property="og:title")
        if og_title:
            parts = og_title.get("content", "").split(" by ")
            if len(parts) >= 2:
                artist_part = parts[-1].replace(" on Apple\xa0Music", "").replace(" on Apple Music", "").strip()
                meta["artist"] = artist_part

    # --- Album: build tracklist from music:song meta tags + iTunes API ---
    if is_album:
        content_tag = (
            soup.find("meta", attrs={"name": "apple:content_id"})
            or soup.find("meta", property="apple:content_id")
        )
        album_id = content_tag.get("content", "") if content_tag else ""
        if not album_id:
            m = re.search(r"/(\d+)(?:\?|$)", url)
            if m:
                album_id = m.group(1)

        # Get album-level metadata from iTunes API
        if album_id:
            album_meta = _itunes_lookup_album(album_id)
            if album_meta:
                meta["albumartist"] = album_meta.get("artistName", "")
                if not meta.get("artist"):
                    meta["artist"] = meta["albumartist"]
                if not meta.get("genre"):
                    meta["genre"] = album_meta.get("primaryGenreName", "")
                if not meta.get("artwork_url"):
                    art = album_meta.get("artworkUrl100", "")
                    meta["artwork_url"] = apple_music_hires_artwork(art)

        song_tags = soup.find_all("meta", property="music:song")
        song_ids = []
        for tag in song_tags:
            song_url = tag.get("content", "")
            m = re.search(r"/(\d+)$", song_url)
            if m:
                song_ids.append(m.group(1))

        if song_ids:
            tracklist = _itunes_lookup_songs(song_ids)
            if tracklist:
                meta["tracklist"] = tracklist

        meta["album"] = meta.get("title", "")

    else:
        # Single song — track number
        track_meta = soup.find("meta", property="music:album:track")
        if track_meta:
            meta["tracknumber"] = track_meta.get("content", "")

    meta["source"] = "apple_music"
    return meta


def _itunes_lookup_album(album_id):
    """Fetch album metadata from the iTunes Search API."""
    try:
        resp = requests.get(
            f"https://itunes.apple.com/lookup?id={album_id}&country=us",
            timeout=10,
        )
        resp.raise_for_status()
        data = json.loads(resp.content.decode("utf-8", errors="replace"))
        for r in data.get("results", []):
            if r.get("wrapperType") == "collection":
                return r
    except Exception:
        pass
    return None


def _itunes_lookup_songs(song_ids):
    """Batch-lookup song titles/artists from the iTunes Search API."""
    tracklist = []
    # iTunes API accepts up to 200 comma-separated IDs
    ids_str = ",".join(song_ids)
    try:
        resp = requests.get(
            f"https://itunes.apple.com/lookup?id={ids_str}&country=us",
            timeout=15,
        )
        resp.raise_for_status()
        data = json.loads(resp.content.decode("utf-8", errors="replace"))
        for r in data.get("results", []):
            if r.get("wrapperType") == "track":
                dur_ms = r.get("trackTimeMillis", 0)
                mins = dur_ms // 60000
                secs = (dur_ms % 60000) // 1000
                tracklist.append({
                    "position": str(r.get("trackNumber", "")),
                    "title": r.get("trackName", ""),
                    "artist": r.get("artistName", ""),
                    "duration": f"{mins}:{secs:02d}",
                })
    except Exception:
        pass
    return tracklist


SPOTIFY_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
}


def scrape_spotify(url):
    """Scrape metadata from a Spotify track or album URL."""
    resp = requests.get(url, headers=SPOTIFY_HEADERS, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(_response_text_utf8(resp), "lxml")

    meta = {}
    is_album = "/album/" in url

    # og:title — "Track Name" or "Album Name - Type by Artist | Spotify"
    og_title = soup.find("meta", property="og:title")
    if og_title:
        raw_title = og_title.get("content", "")
        # Album titles: "Album - compilation by Artist | Spotify"
        # Track titles: "Track Name"
        cleaned = raw_title.split(" | Spotify")[0].strip()
        if is_album:
            # "Anokha - Soundz... - Compilation by Various Artists"
            by_split = cleaned.rsplit(" by ", 1)
            if len(by_split) == 2:
                album_part = by_split[0].strip()
                # Remove trailing " - compilation", " - Album", etc.
                album_part = re.sub(r"\s*-\s*(compilation|album|single|ep)\s*$", "", album_part, flags=re.I)
                meta["album"] = album_part
                meta["albumartist"] = by_split[1].strip()
                meta["artist"] = meta["albumartist"]
            else:
                meta["album"] = cleaned
        else:
            meta["title"] = cleaned

    # og:description — "Artist · Album · Song · Year"
    og_desc = soup.find("meta", property="og:description")
    if og_desc:
        desc = og_desc.get("content", "")
        parts = [p.strip() for p in desc.split("·")]
        if not is_album and len(parts) >= 2:
            meta["artist"] = parts[0]
            meta["album"] = parts[1]

    # og:image — high-res artwork
    og_image = soup.find("meta", property="og:image")
    if og_image:
        meta["artwork_url"] = og_image.get("content", "")

    def spot_meta(name):
        return (soup.find("meta", property=name) or soup.find("meta", attrs={"name": name}))

    rel = spot_meta("music:release_date")
    if rel:
        ym = re.search(r"(\d{4})", rel.get("content", ""))
        if ym:
            meta["date"] = ym.group(1)

    mus_desc = spot_meta("music:musician_description")
    if mus_desc and not is_album:
        meta["artist"] = mus_desc.get("content", "")

    track_tag = spot_meta("music:album:track")
    if track_tag:
        meta["tracknumber"] = track_tag.get("content", "")

    # Album: build tracklist from music:song tags + oEmbed
    if is_album:
        song_tags = (
            soup.find_all("meta", property="music:song")
            or soup.find_all("meta", attrs={"name": "music:song"})
        )
        song_urls = []
        for tag in song_tags:
            song_url = tag.get("content", "")
            if song_url and "/track/" in song_url:
                song_urls.append(song_url)

        if song_urls:
            tracklist = _spotify_oembed_tracklist(song_urls)
            if tracklist:
                meta["tracklist"] = tracklist

        if not meta.get("title"):
            meta["title"] = meta.get("album", "")

    meta["source"] = "spotify"
    return meta


def _spotify_oembed_tracklist(song_urls):
    """Fetch track titles from Spotify oEmbed for a list of song URLs."""
    tracklist = []
    for i, url in enumerate(song_urls, 1):
        try:
            resp = requests.get(
                "https://open.spotify.com/oembed",
                params={"url": url},
                timeout=8,
            )
            data = resp.json()
            tracklist.append({
                "position": str(i),
                "title": data.get("title", f"Track {i}"),
                "artist": "",
                "duration": "",
                "url": url,
            })
        except Exception:
            tracklist.append({"position": str(i), "title": f"Track {i}", "artist": "", "duration": ""})
    return tracklist


def _soundcloud_hydration_list(html: str):
    """Parse ``window.__sc_hydration = [...]`` from a SoundCloud track page."""
    marker = "window.__sc_hydration = "
    i = html.find(marker)
    if i < 0:
        return None
    j = i + len(marker)
    while j < len(html) and html[j] in " \t\r\n":
        j += 1
    try:
        data, _end = json.JSONDecoder().raw_decode(html, j)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, list) else None


def _soundcloud_artwork_hires(url: str) -> str:
    if not url:
        return ""
    return re.sub(r"-large\.(jpg|jpeg|png)(\?[^#]*)?$", r"-t500x500.\1", url, flags=re.I)


def scrape_soundcloud(url: str) -> dict:
    """Metadata from a public SoundCloud track URL (embedded ``__sc_hydration`` JSON)."""
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    html = _response_text_utf8(resp)
    blob = _soundcloud_hydration_list(html)
    meta: dict = {"source": "soundcloud"}
    sound = None
    if blob:
        for item in blob:
            if not isinstance(item, dict) or item.get("hydratable") != "sound":
                continue
            d = item.get("data")
            if isinstance(d, dict) and (d.get("title") or "").strip():
                sound = d
                break
    if not sound:
        soup = BeautifulSoup(html, "lxml")
        tw = soup.find("meta", attrs={"property": "twitter:title"})
        if tw and tw.get("content"):
            meta["title"] = tw["content"].strip()
        og = soup.find("meta", property="og:image")
        if og and og.get("content"):
            meta["artwork_url"] = _soundcloud_artwork_hires(og["content"].strip())
        return meta

    meta["title"] = (sound.get("title") or "").strip()
    pm = sound.get("publisher_metadata") if isinstance(sound.get("publisher_metadata"), dict) else {}
    user = sound.get("user") if isinstance(sound.get("user"), dict) else {}
    meta["artist"] = (
        (pm.get("artist") or user.get("username") or user.get("full_name") or "")
    ).strip()
    album_title = pm.get("album_title")
    if album_title:
        meta["album"] = str(album_title).strip()
    g = (sound.get("genre") or "").strip()
    if not g:
        tl = sound.get("tag_list")
        if isinstance(tl, str) and tl.strip():
            g = tl.strip()
    if g:
        meta["genre"] = g
    rd = sound.get("release_date") or sound.get("created_at") or ""
    ym = re.search(r"(\d{4})", str(rd))
    if ym:
        meta["date"] = ym.group(1)
    au = sound.get("artwork_url") or ""
    if au:
        meta["artwork_url"] = _soundcloud_artwork_hires(str(au).strip())
    return meta


def _beatport_next_track(html: str):
    m = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
        html,
        re.DOTALL,
    )
    if not m:
        return None
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError:
        return None
    tr = (data.get("props") or {}).get("pageProps") or {}
    tr = tr.get("track")
    return tr if isinstance(tr, dict) else None


def scrape_beatport(url: str) -> dict:
    """Metadata from a Beatport track page (Next.js ``__NEXT_DATA__``)."""
    if "/track/" not in url.lower():
        return {}
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    html = _response_text_utf8(resp)
    tr = _beatport_next_track(html)
    meta: dict = {"source": "beatport"}
    if not tr:
        return meta

    name = (tr.get("name") or "").strip()
    mix = (tr.get("mix_name") or "").strip()
    if mix and mix.lower() not in ("original mix", "original"):
        meta["title"] = f"{name} ({mix})"
    else:
        meta["title"] = name

    artists = tr.get("artists") or []
    names = []
    if isinstance(artists, list):
        for a in artists:
            if isinstance(a, dict) and (a.get("name") or "").strip():
                names.append(a["name"].strip())
    meta["artist"] = " / ".join(names)

    rel = tr.get("release") if isinstance(tr.get("release"), dict) else {}
    if rel.get("name"):
        meta["album"] = str(rel["name"]).strip()
    lab = rel.get("label") if isinstance(rel.get("label"), dict) else {}
    if lab.get("name"):
        meta["label"] = str(lab["name"]).strip()

    art_url = ""
    rim = rel.get("image") if isinstance(rel.get("image"), dict) else {}
    if rim.get("dynamic_uri"):
        art_url = str(rim["dynamic_uri"]).replace("{w}x{h}", "1400x1400")
    elif rim.get("uri"):
        art_url = str(rim["uri"])
    if not art_url:
        img = tr.get("image") if isinstance(tr.get("image"), dict) else {}
        if img.get("dynamic_uri"):
            art_url = str(img["dynamic_uri"]).replace("{w}x{h}", "1400x1400")
        elif img.get("uri"):
            art_url = str(img["uri"])
    if art_url:
        meta["artwork_url"] = art_url

    g = tr.get("genre") if isinstance(tr.get("genre"), dict) else {}
    if g.get("name"):
        meta["genre"] = str(g["name"]).strip()
    pd = tr.get("publish_date") or ""
    ym = re.search(r"(\d{4})", str(pd))
    if ym:
        meta["date"] = ym.group(1)
    return meta


def parse_discogs_url(url):
    m = re.search(r"discogs\.com/(master|release)/(\d+)", url)
    if m:
        return m.group(1), m.group(2)
    return None, None


def fetch_discogs(url):
    rtype, rid = parse_discogs_url(url)
    if not rtype or not rid:
        return {}

    api_url = f"https://api.discogs.com/{'masters' if rtype == 'master' else 'releases'}/{rid}"
    resp = requests.get(api_url, headers=DISCOGS_HEADERS, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    artists = " / ".join(a["name"] for a in data.get("artists", []))
    album_title = data.get("title", "")
    year = str(data.get("year", ""))

    genres = data.get("genres", [])
    styles = data.get("styles", [])
    genre_str = " / ".join(genres + styles)

    images = data.get("images", [])
    artwork_url = ""
    if images:
        primary = next((i for i in images if i.get("type") == "primary"), images[0])
        artwork_url = primary.get("uri", "")

    tracklist = []
    for t in data.get("tracklist", []):
        if t.get("type_") == "track":
            tracklist.append({
                "position": t.get("position", ""),
                "title": t.get("title", ""),
                "duration": t.get("duration", ""),
            })

    label = ""
    catno = ""
    if rtype == "release":
        labels = data.get("labels", [])
        if labels:
            label = labels[0].get("name", "")
            catno = labels[0].get("catno", "")
    elif data.get("main_release_url"):
        try:
            rel_resp = requests.get(data["main_release_url"], headers=DISCOGS_HEADERS, timeout=10)
            rel_data = rel_resp.json()
            labels = rel_data.get("labels", [])
            if labels:
                label = labels[0].get("name", "")
                catno = labels[0].get("catno", "")
        except Exception:
            pass

    meta = {
        "artist": artists,
        "albumartist": artists,
        "album": album_title,
        "date": year,
        "genre": genre_str,
        "artwork_url": artwork_url,
        "tracklist": tracklist,
        "source": "discogs",
    }
    if label:
        meta["label"] = label
    if catno:
        meta["catno"] = catno
    if len(tracklist) == 1:
        meta["title"] = tracklist[0]["title"]

    return meta


def scrape_generic(url):
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(_response_text_utf8(resp), "lxml")

    meta = {}
    for prop, key in [("og:title", "title"), ("og:image", "artwork_url"),
                       ("og:description", "comment"), ("music:musician", "artist")]:
        tag = soup.find("meta", property=prop) or soup.find("meta", attrs={"name": prop})
        if tag:
            meta[key] = tag.get("content", "")

    if not meta.get("title"):
        title_tag = soup.find("title")
        if title_tag:
            meta["title"] = title_tag.get_text(strip=True)

    return meta


def fetch_artwork(url):
    if not url:
        return None, None
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    content_type = resp.headers.get("Content-Type", "image/jpeg").split(";")[0]
    return resp.content, content_type


def search_itunes(query, limit=8):
    """Search the iTunes/Apple Music catalogue."""
    results = []
    try:
        resp = requests.get(
            "https://itunes.apple.com/search",
            params={"term": query, "entity": "song", "limit": limit, "country": "us"},
            timeout=10,
        )
        data = resp.json()
        for r in data.get("results", []):
            art_url = r.get("artworkUrl100", "")
            web = (r.get("trackViewUrl") or r.get("collectionViewUrl") or "").strip()
            if not web:
                an = r.get("artistName") or ""
                tn = r.get("trackName") or ""
                t_a = f"{an} {tn}".strip()
                if t_a:
                    web = f"https://music.apple.com/search?term={quote_plus(t_a)}"
            results.append({
                "title": r.get("trackName", ""),
                "artist": r.get("artistName", ""),
                "album": r.get("collectionName", ""),
                "year": str(r.get("releaseDate", ""))[:4],
                "artwork_thumb": art_url,
                "url": web,
                "source": "apple_music",
            })
    except Exception:
        pass
    return results


def search_discogs(query, limit=5):
    """Search the Discogs catalogue."""
    results = []
    try:
        resp = requests.get(
            "https://api.discogs.com/database/search",
            params={"q": query, "type": "release", "per_page": limit},
            headers=DISCOGS_HEADERS,
            timeout=10,
        )
        data = resp.json()
        for r in data.get("results", []):
            labels = r.get("label", [])
            uri = (r.get("uri") or "").strip()
            if uri.startswith("http://") or uri.startswith("https://"):
                discogs_url = uri
            elif uri:
                discogs_url = f"https://www.discogs.com{uri}" if uri.startswith("/") else f"https://www.discogs.com/{uri}"
            else:
                rid, rty = r.get("id"), (r.get("type") or "").lower()
                if rty == "release" and rid is not None:
                    discogs_url = f"https://www.discogs.com/release/{rid}"
                else:
                    discogs_url = ""
            results.append({
                "title": r.get("title", ""),
                "artist": "",
                "album": r.get("title", ""),
                "year": str(r.get("year", "")),
                "artwork_thumb": r.get("thumb", ""),
                "url": discogs_url,
                "source": "discogs",
                "label": labels[0] if labels else "",
            })
    except Exception:
        pass
    return results


def _bandcamp_clean_result_url(href: str) -> str:
    """Normalize a Bandcamp search link to a stable https URL (no tracking query)."""
    if not (href or "").strip():
        return ""
    p = urlparse(href.strip())
    netloc = (p.netloc or "").lower()
    if "bandcamp.com" not in netloc:
        return ""
    path = (p.path or "").rstrip("/")
    if "/track/" not in path and "/album/" not in path:
        return ""
    return urlunparse(("https", p.netloc, path, "", "", ""))


def search_bandcamp(query, limit=6):
    """
    Search bandcamp.com (public search page). Returns track hits with clean URLs suitable
    for scrape_bandcamp / apply metadata.
    """
    results = []
    q = (query or "").strip()
    if not q or limit < 1:
        return results
    try:
        resp = requests.get(
            "https://bandcamp.com/search",
            params={"q": q},
            headers=HEADERS,
            timeout=18,
        )
        resp.raise_for_status()
        soup = BeautifulSoup(_response_text_utf8(resp), "lxml")
        for li in soup.find_all("li"):
            if len(results) >= limit:
                break
            classes = li.get("class") or []
            if "searchresult" not in classes:
                continue
            artcont = li.find("a", class_="artcont")
            if not artcont or not artcont.get("href"):
                continue
            href = artcont["href"]
            if "/track/" not in href:
                continue
            clean = _bandcamp_clean_result_url(href)
            if not clean:
                continue
            heading = li.find("div", class_="heading")
            title = ""
            if heading:
                ha = heading.find("a")
                if ha:
                    title = ha.get_text(" ", strip=True)
            if not title:
                continue
            subhead = li.find("div", class_="subhead")
            artist, album = "", ""
            if subhead:
                text = re.sub(r"\s+", " ", subhead.get_text(" ", strip=True))
                m = re.search(r"from\s+(.+?)\s+by\s+(.+)$", text, re.I)
                if m:
                    album, artist = m.group(1).strip(), m.group(2).strip()
                else:
                    m2 = re.search(r"\bby\s+(.+)$", text, re.I)
                    if m2:
                        artist = m2.group(1).strip()
            thumb = ""
            art = li.find("div", class_="art")
            if art:
                im = art.find("img")
                if im and (im.get("src") or im.get("data-src")):
                    thumb = (im.get("src") or im.get("data-src") or "").strip()
            year = ""
            rel = li.find("div", class_="released")
            if rel:
                y = re.search(r"(\d{4})", rel.get_text())
                if y:
                    year = y.group(1)
            results.append({
                "title": title,
                "artist": artist,
                "album": album,
                "year": year,
                "artwork_thumb": thumb,
                "url": clean,
                "source": "bandcamp",
            })
    except Exception:
        pass
    return results


def peel_fix_retain_suffixes(stem: str, lines: list | None) -> tuple[str, str]:
    """
    Repeatedly peel configured suffix patterns from the **end** of stem for search parsing.
    Returns (core_stem, retained_concat) where retained is pieces left-to-right after the core
    (e.g. core ``Track``, retained ``_bpm(120)_warped``).
    """
    cur = (stem or "").strip()
    if not cur or not lines:
        return cur, ""
    peeled_right_to_left: list[str] = []
    safety = 0
    while cur and safety < 32:
        safety += 1
        matched_piece: str | None = None
        for raw in lines:
            if raw is None:
                continue
            line = str(raw).strip()
            if not line or line.startswith("#"):
                continue
            low = line.lower()
            if low.startswith("regex:"):
                pat_s = line[6:].strip()
                try:
                    rx = re.compile(pat_s)
                except re.error:
                    continue
                m = rx.search(cur)
                if m is not None and m.start() >= 0 and m.end() == len(cur):
                    matched_piece = m.group(0)
                    break
            else:
                if cur.endswith(line):
                    matched_piece = line
                    break
        if not matched_piece:
            break
        peeled_right_to_left.append(matched_piece)
        cur = cur[: len(cur) - len(matched_piece)]
    retained = "".join(reversed(peeled_right_to_left))
    return cur, retained


def strip_rekordbox_style_filename_affixes(stem: str) -> str:
    """
    Remove common noise from an **Ableton / DAW export** stem so search uses artist/title only.

    **Rekordbox** itself does not define a filename scheme: it keys tracks on embedded
    metadata and its internal database. Filenames like ``A01 - Artist - Title - 1A - 126``
    are a **convention people use with Ableton Live** (and similar tools) when exporting
    or collecting **samples for a set**—hyphens separate fields for quick visual scanning
    in the browser. Those files are often **also** present in a Rekordbox collection, but
    the pattern is Ableton-oriented, not Rekordbox-native.

    Strips:
    - Trailing Camelot key + BPM (e.g. ``2A 120``, ``12A 98``)
    - Leading key/slot token (e.g. ``A02``, ``B12``)
    """
    t = (stem or "").strip()
    if not t:
        return t
    # e.g. " - 8A - 118" (hyphens between key and BPM) as well as " 8A 118"
    t = re.sub(r"(?i)\s*-\s*\d{1,2}[AB]\s*-\s*\d{2,3}\s*$", "", t).strip()
    t = re.sub(r"(?i)\s+\d{1,2}[AB]\s+\d{2,3}$", "", t).strip()
    t = re.sub(r"(?i)^[A-Za-z]\d{1,2}\s+", "", t).strip()
    return t


def _normalize_track_filename_stem(stem: str) -> str:
    """_PN strip + Rekordbox-style slot / key / BPM affixes (shared by parse and search)."""
    t = re.sub(r"_PN$", "", (stem or ""), flags=re.I).strip()
    return strip_rekordbox_style_filename_affixes(t)


def search_query_from_ableton_stem(stem: str) -> dict:
    """
    Build an online search query from a file stem (matches Fix Metadata / fix.js intent).
    """
    cfg = load_config()
    core, _ret = peel_fix_retain_suffixes(stem, cfg.get("fix_retain_filename_suffixes") or [])
    p = parse_ableton_style_wav_stem(core)
    if p.get("matched") and (p.get("artist") or "").strip() and (p.get("title") or "").strip():
        a = p["artist"].strip()
        t = p["title"].strip()
        q = f"{a} {t}"
        return {
            "query": re.sub(r"\s+", " ", q).strip(),
            "title_hint": t,
            "artist_hint": a,
            "pattern_matched": True,
        }
    if (p.get("title") or "").strip() and not p.get("matched"):
        loose = p["title"].strip()
        return {
            "query": loose,
            "title_hint": loose,
            "artist_hint": "",
            "pattern_matched": False,
        }
    if p.get("loose"):
        return {
            "query": p["loose"],
            "title_hint": "",
            "artist_hint": "",
            "pattern_matched": False,
        }
    tail = _normalize_track_filename_stem(core)
    t = re.sub(r"\s+", " ", tail.replace("_", " ")).strip()
    return {
        "query": t,
        "title_hint": "",
        "artist_hint": "",
        "pattern_matched": False,
    }


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
    base = search_query_from_ableton_stem(stem)
    wav_sibling = str(Path(p).with_suffix(".wav"))
    wt = _read_wav_embedded_tags(wav_sibling) if os.path.isfile(wav_sibling) else {
        "title": "", "artist": "", "album": ""
    }
    wa = (wt.get("artist") or "").strip()
    wti = (wt.get("title") or "").strip()
    wal = (wt.get("album") or "").strip()
    merged = {**base}
    merged["wav_sibling"] = wav_sibling if os.path.isfile(wav_sibling) else ""
    tag_blob = {k: v for k, v in {"artist": wa, "title": wti, "album": wal}.items() if v}
    merged["wav_tags"] = tag_blob or None
    if wa and wti:
        q = f"{wa} {wti}"
        merged["query"] = re.sub(r"\s+", " ", q).strip()
        merged["title_hint"] = wti
        merged["artist_hint"] = wa
    else:
        if wti and not (merged.get("title_hint") or "").strip():
            merged["title_hint"] = wti
        if wa and not (merged.get("artist_hint") or "").strip():
            merged["artist_hint"] = wa
    return merged


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
            meta = scrape_bandcamp(url)
        elif "discogs.com" in url:
            meta = fetch_discogs(url)
        elif "music.apple.com" in url:
            meta = scrape_apple_music(url)
        elif "spotify.com" in url or "spotify.link" in url:
            meta = scrape_spotify(url)
        elif "soundcloud.com" in url.lower():
            meta = scrape_soundcloud(url)
        elif "beatport.com" in url.lower() and "/track/" in url.lower():
            meta = scrape_beatport(url)
        else:
            meta = scrape_generic(url)
    except Exception as e:
        meta = {"_warning": f"Scrape failed: {e}"}
    return meta


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


def _normalize_search_source(raw: str) -> str:
    """Return apple_music | discogs | bandcamp, or '' for combined search."""
    s = (raw or "").strip().lower()
    if s in ("apple", "apple_music", "itunes"):
        return "apple_music"
    if s == "discogs":
        return "discogs"
    if s == "bandcamp":
        return "bandcamp"
    return ""


@app.route("/api/search")
def search():
    """Search iTunes, Discogs, and Bandcamp for a track by query string.

    Query params:
      q — search text (required for non-empty results)
      source — optional: apple_music (aliases: apple, itunes), discogs, bandcamp.
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
            results = search_itunes(q, limit=lim)
        elif source_key == "discogs":
            results = search_discogs(q, limit=lim)
        else:
            results = search_bandcamp(q, limit=lim)
        return jsonify({"results": results})

    itunes = search_itunes(q, limit=8)
    discogs = search_discogs(q, limit=5)
    bandcamp = search_bandcamp(q, limit=6)

    # De-dupe by title + artist (or album for Discogs) + source so the same work can appear
    # on Apple, Discogs, and Bandcamp for validation.
    seen = set()
    combined = []
    for r in itunes + discogs + bandcamp:
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
        root_r = os.path.realpath(resolve(root))
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
    """For each file path, run the same iTunes + Discogs + Bandcamp search as /api/search (rate-limited)."""
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
        itunes = search_itunes(q, limit=6)
        time.sleep(delay)
        discogs = search_discogs(q, limit=4)
        time.sleep(delay)
        bandcamp = search_bandcamp(q, limit=5)
        time.sleep(delay)
        seen = set()
        combined = []
        for r in itunes + discogs + bandcamp:
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
            artwork_bytes, artwork_mime = fetch_artwork(artwork_url)
        except Exception as e:
            return {"status": "error", "reason": f"artwork: {e}"}

    su = (source_url or "").strip()
    if su:
        mcopy["source_url"] = su

    planned_new_name = None
    if rename_to_tags:
        ext = Path(filepath).suffix.lower() or ".flac"
        retained = _retained_suffix_from_filepath(filepath)
        planned_new_name = _basename_from_artist_title_for_rename(
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
        apply_metadata(filepath, mcopy, artwork_bytes, artwork_mime)
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
        log_extraction({
            "kind": "fix",
            "filename": os.path.basename(out_path),
            "output_path": out_path,
            "target_path": out_path,
            "metadata": {k: v for k, v in mcopy.items() if k != "source_url"},
            "artwork_url": artwork_url,
            "metadata_source_url": su,
            "metadata_source_type": infer_metadata_source_type(su),
        })
    return {"status": "ok", "filepath": out_path, "renamed": renamed}


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
            th = (search_query_from_ableton_stem(stem).get("title_hint") or "").strip()
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


@app.route("/api/settings", methods=["GET"])
def get_settings():
    cfg = dict(load_config())
    cfg["extract_profile"] = resolve_extract_profile_key(cfg)
    cfg["extract_profiles"] = extract_profile_options()
    cfg["source_dir_resolved"] = resolve(cfg["source_dir"])
    cfg["destination_dir_resolved"] = resolve(cfg["destination_dir"])
    return jsonify(cfg)


@app.route("/api/settings", methods=["POST"])
def update_settings():
    data = request.get_json()
    cfg = load_config()

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
        if pk in EXTRACT_PROFILES:
            cfg["extract_profile"] = pk
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
        raw = data["fix_retain_filename_suffixes"]
        lines: list[str] = []
        if isinstance(raw, list):
            for x in raw:
                if isinstance(x, str):
                    s = x.strip()
                    if s and not s.startswith("#"):
                        lines.append(s)
        elif isinstance(raw, str):
            for ln in raw.splitlines():
                s = ln.strip()
                if s and not s.startswith("#"):
                    lines.append(s)
        for line in lines:
            if line.lower().startswith("regex:"):
                pat = line[6:].strip()
                try:
                    re.compile(pat)
                except re.error as e:
                    return jsonify({"error": f"Invalid regex in fix filename suffixes: {pat} ({e})"}), 400
        cfg["fix_retain_filename_suffixes"] = lines

    save_config(cfg)

    cfg = dict(load_config())
    cfg["extract_profile"] = resolve_extract_profile_key(cfg)
    cfg["extract_profiles"] = extract_profile_options()
    cfg["source_dir_resolved"] = resolve(cfg["source_dir"])
    cfg["destination_dir_resolved"] = resolve(cfg["destination_dir"])
    return jsonify(cfg)


# Video files listed on Extract (step 1); rename/delete must stay in the browsed folder.
VIDEO_SOURCE_EXTENSIONS = (".mkv", ".mp4", ".mov", ".avi", ".webm")


def _normalize_resolved_path(p):
    return os.path.normpath(os.path.abspath(resolve(p)))


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
    if Path(fp).suffix.lower() not in VIDEO_SOURCE_EXTENSIONS:
        return False, "Not a supported video recording type"
    return True, None


@app.route("/api/browse")
def browse():
    cfg = load_config()
    directory = request.args.get("dir", cfg["source_dir"])
    directory = resolve(directory)
    if not os.path.isdir(directory):
        return jsonify({"error": f"Directory not found: {directory}"}), 404

    files = []
    for f in sorted(Path(directory).iterdir()):
        if f.suffix.lower() in VIDEO_SOURCE_EXTENSIONS:
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
        trash_file(filepath)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"ok": True})


@app.route("/api/probe", methods=["POST"])
def probe():
    data = request.get_json()
    filepath = data.get("filepath")
    if not filepath or not os.path.isfile(filepath):
        return jsonify({"error": "File not found"}), 404

    info = run_ffprobe(filepath)
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
        result = analyse_loudness(filepath)
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
    ext_in = Path(filepath).suffix.lower()
    if ext_in not in AUDIO_EXTENSIONS:
        return jsonify({"error": "Unsupported audio file type for normalise"}), 400
    if not loudnorm_params or not isinstance(loudnorm_params, dict):
        return jsonify({"error": "Run level analysis first (loudnorm_params missing)"}), 400

    cfg = load_config()
    profile_key = resolve_extract_profile_key(cfg)
    prof = EXTRACT_PROFILES[profile_key]
    parent = Path(filepath).parent
    stem = Path(filepath).stem
    out_path = str(parent / f"{stem}{output_suffix}{prof['ext']}")

    if os.path.normpath(os.path.abspath(out_path)) == os.path.normpath(os.path.abspath(filepath)):
        return jsonify({"error": "Output path cannot be the same as input"}), 400
    if os.path.exists(out_path):
        return jsonify({"error": f"Output already exists: {out_path}"}), 409

    try:
        _ffmpeg_loudnorm_encode(filepath, out_path, loudnorm_params, profile_key)
        _copy_audio_tags_and_art(filepath, out_path)
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
        img_bytes, content_type = fetch_artwork(url)
        return app.response_class(img_bytes, mimetype=content_type)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/extract", methods=["POST"])
def extract():
    data = request.get_json()
    cfg = load_config()

    filepath = data.get("filepath")
    metadata = data.get("metadata", {})
    artwork_url = data.get("artwork_url", "")
    metadata_source_url = (data.get("metadata_source_url") or "").strip()

    if not filepath or not os.path.isfile(filepath):
        return jsonify({"error": "Source file not found"}), 404

    profile_key = resolve_extract_profile_key(cfg)
    prof = EXTRACT_PROFILES[profile_key]

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
    tgt_lufs, tgt_tp = get_normalisation_targets()

    if normalise:
        an_src = analyse_loudness(filepath)
        lp = an_src.get("loudnorm_params") or {}
        if not _loudnorm_params_usable(lp):
            return jsonify({
                "error": "Loudness analysis of the source failed (ffmpeg did not return loudnorm measurements). "
                "Is ffmpeg installed? Try the level meters (Analyse) on this file, then extract again.",
            }), 500
        loudnorm_params = lp

    try:
        source_codec = extract_audio(filepath, output_path, profile_key, normalise, loudnorm_params)
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
        post = analyse_loudness(output_path)
        pparams = post.get("loudnorm_params") or {}
        ok, reasons = normalised_output_meets_targets(pparams, tgt_lufs, tgt_tp, tol_lufs, tol_tp)
        if not ok:
            # One retry: fresh source pass + re-encode; fixes stale client params and odd ffmpeg runs.
            an2 = analyse_loudness(filepath)
            flp = an2.get("loudnorm_params") or {}
            if not _loudnorm_params_usable(flp):
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
                    _ffmpeg_loudnorm_encode(
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
                    post2 = analyse_loudness(output_path)
                    p2 = post2.get("loudnorm_params") or {}
                    ok2, reasons2 = normalised_output_meets_targets(
                        p2, tgt_lufs, tgt_tp, tol_lufs, tol_tp
                    )
                    if not ok2:
                        loudness_verify_warning = (
                            "Loudness check still failing after a server re-encode: " + "; ".join(reasons2)
                        )
                    else:
                        loudness_verify_warning = None

    artwork_bytes, artwork_mime = None, None
    if artwork_url:
        try:
            artwork_bytes, artwork_mime = fetch_artwork(artwork_url)
        except Exception:
            pass

    meta_for_file = dict(metadata)
    if metadata_source_url:
        meta_for_file["source_url"] = metadata_source_url

    apply_metadata(output_path, meta_for_file, artwork_bytes, artwork_mime)

    # Copy to destination folder
    dest_dir = resolve(cfg["destination_dir"])
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
            trash_file(filepath)
            source_trashed = True
        except Exception as e:
            source_trash_error = str(e)

    stat = os.stat(output_path)

    suffix = cfg.get("pn_output_suffix", "_PN")
    expected_pn_path = str(pn_derivative_path(output_path, suffix))

    log_index = log_extraction({
        "kind": "extract",
        "filename": filename,
        "extract_profile": profile_key,
        "source_file": filepath,
        "output_path": output_path,
        "copied_to": copied_to,
        "metadata": metadata,
        "artwork_url": artwork_url,
        "metadata_source_url": metadata_source_url,
        "metadata_source_type": infer_metadata_source_type(metadata_source_url),
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
        post_extract_open_app(pn_app, output_path)

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
    library copy (copied_to from the same run), and flat in Settings destination — so PN
    can be configured to write only to the FLACs / destination folder.
    """
    data = request.get_json() or {}
    cfg = load_config()
    base_flac_path = (data.get("base_flac_path") or "").strip()
    copied_to = (data.get("copied_to") or "").strip() or None
    suffix = (data.get("pn_output_suffix") or cfg.get("pn_output_suffix") or "_PN").strip()
    if not base_flac_path:
        return jsonify({"error": "base_flac_path required"}), 400
    if not os.path.isfile(base_flac_path):
        return jsonify({"error": "Base audio file not found", "ready": False}), 404

    dest = (cfg.get("destination_dir") or "").strip()
    candidates = _pn_output_candidate_paths(
        base_flac_path, suffix, copied_to=copied_to, destination_dir=dest
    )
    try:
        base_mt = os.path.getmtime(base_flac_path)
    except OSError:
        base_mt = 0.0

    ready = False
    pn_path = str(pn_derivative_path(base_flac_path, suffix))
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
    cfg = load_config()
    base_flac_path = data.get("base_flac_path")
    pn_flac_path = data.get("pn_flac_path")
    log_index = data.get("log_index")
    suffix = (data.get("pn_output_suffix") or cfg.get("pn_output_suffix") or "_PN").strip()

    if not base_flac_path:
        return jsonify({"error": "base_flac_path required"}), 400
    if not os.path.isfile(base_flac_path):
        return jsonify({"error": f"Base audio file not found: {base_flac_path}"}), 404

    entry, idx = find_log_entry_for_output_path(base_flac_path, log_index)
    if not entry:
        return jsonify({
            "error": "No processing log entry matches this extract. Expand Processing Log and use a row from the same run, or re-fetch metadata manually.",
        }), 404

    pn_path = pn_flac_path or str(pn_derivative_path(base_flac_path, suffix))
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
            artwork_bytes, artwork_mime = fetch_artwork(artwork_url)
        except Exception as e:
            return jsonify({"error": f"Artwork fetch failed: {e}"}), 500

    try:
        apply_metadata(pn_path, metadata, artwork_bytes, artwork_mime)
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
    return jsonify(load_log())


@app.route("/api/fix-artwork", methods=["POST"])
def fix_artwork():
    """Re-embed existing artwork with correct dimensions."""
    data = request.get_json()
    filepath = data.get("filepath")
    if not filepath or not os.path.isfile(filepath):
        return jsonify({"error": "File not found"}), 404

    ext = os.path.splitext(filepath)[1].lower()
    if ext != ".flac":
        return jsonify({"error": "Only FLAC files supported for artwork fix"}), 400

    try:
        audio = FLAC(filepath)
        if not audio.pictures:
            return jsonify({"error": "No artwork to fix"}), 400

        pic = audio.pictures[0]
        w, h = _image_dimensions(pic.data)
        if w == pic.width and h == pic.height and w > 0:
            return jsonify({"status": "ok", "message": "Dimensions already correct", "width": w, "height": h})

        pic.width = w
        pic.height = h
        audio.clear_pictures()
        audio.add_picture(pic)
        audio.save()
        return jsonify({"status": "ok", "message": f"Fixed artwork dimensions to {w}x{h}", "width": w, "height": h})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _basename_from_artist_title_for_rename(artist: str, title: str, ext: str, retained_suffix: str = "") -> str | None:
    """Build a safe filename (basename) from tag fields; ext must be like .flac.
    retained_suffix is peeled from the original stem (e.g. _warped) and appended before ext.
    """
    if not ext.startswith("."):
        ext = "." + ext
    rs = (retained_suffix or "").strip()
    if rs:
        rs = re.sub(r'[<>:"/\\|?*]', "", rs)
    a = (artist or "").strip()
    t = (title or "").strip()
    if not t and not a:
        return None
    if t and a:
        base = f"{a} - {t}"
    else:
        base = t or a
    base = re.sub(r'[<>:"/\\|?*]', "", base)
    base = re.sub(r"\s+", " ", base).strip(" .")
    if not base:
        return None
    if len(base) > 200:
        base = base[:200].rstrip(" .")
    return f"{base}{rs}{ext}"


def _retained_suffix_from_filepath(filepath: str) -> str:
    stem = Path(filepath or "").stem
    if not stem:
        return ""
    cfg = load_config()
    _c, retained = peel_fix_retain_suffixes(stem, cfg.get("fix_retain_filename_suffixes") or [])
    return retained


@app.route("/api/retag", methods=["POST"])
def retag():
    """Re-apply metadata and artwork to an existing audio file from a log entry."""
    data = request.get_json()
    filepath = data.get("filepath")
    metadata = dict(data.get("metadata") or {})
    artwork_url = data.get("artwork_url", "")
    metadata_source_url = (data.get("metadata_source_url") or "").strip()
    record_in_log = data.get("record_in_log", True)
    rename_to_tags = bool(data.get("rename_to_tags"))

    if not filepath or not os.path.isfile(filepath):
        return jsonify({"error": f"File not found: {filepath}"}), 404

    meta_for_file = dict(metadata)
    if metadata_source_url:
        meta_for_file["source_url"] = metadata_source_url

    planned_new_name = None
    if rename_to_tags:
        ext = Path(filepath).suffix.lower() or ".flac"
        retained = _retained_suffix_from_filepath(filepath)
        planned_new_name = _basename_from_artist_title_for_rename(
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

    artwork_bytes, artwork_mime = None, None
    if artwork_url:
        try:
            artwork_bytes, artwork_mime = fetch_artwork(artwork_url)
        except Exception as e:
            return jsonify({"error": f"Artwork fetch failed: {e}"}), 500

    try:
        apply_metadata(filepath, meta_for_file, artwork_bytes, artwork_mime)
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

    if record_in_log and (metadata_source_url or artwork_url):
        log_extraction({
            "kind": "fix",
            "filename": os.path.basename(out_path),
            "output_path": out_path,
            "target_path": out_path,
            "metadata": metadata,
            "artwork_url": artwork_url,
            "metadata_source_url": metadata_source_url,
            "metadata_source_type": infer_metadata_source_type(metadata_source_url),
        })

    return jsonify({
        "status": "ok",
        "filepath": out_path,
        "renamed": renamed,
    })


@app.route("/api/retag-batch", methods=["POST"])
def retag_batch():
    """Re-apply metadata+artwork to multiple files from the processing log."""
    data = request.get_json()
    target_dir = data.get("target_dir", "")
    entry_indices = data.get("entries")  # list of log indices, or None for all

    if not target_dir:
        return jsonify({"error": "No target directory"}), 400
    target_dir = resolve(target_dir)
    if not os.path.isdir(target_dir):
        return jsonify({"error": f"Directory not found: {target_dir}"}), 404

    entries = load_log()
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
                artwork_bytes, artwork_mime = fetch_artwork(artwork_url)
            except Exception:
                pass

        try:
            apply_metadata(filepath, metadata, artwork_bytes, artwork_mime)
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
        path = os.path.realpath(resolve(raw))
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
    cfg = load_config()
    directory = request.args.get("dir", cfg["destination_dir"])
    directory = resolve(directory)
    if not os.path.isdir(directory):
        return jsonify({"error": f"Directory not found: {directory}"}), 404

    files = []
    for f in sorted(Path(directory).iterdir()):
        if f.suffix.lower() in AUDIO_EXTENSIONS:
            files.append({
                "name": f.name,
                "path": str(f),
                "size_mb": round(f.stat().st_size / (1024 * 1024), 1),
            })
    return jsonify({"directory": directory, "files": files})


@app.route("/api/browse-wav")
def browse_wav():
    """List .wav files in a directory (WAV → FLAC tab)."""
    cfg = load_config()
    directory = request.args.get("dir", cfg.get("destination_dir") or cfg.get("source_dir", ""))
    directory = resolve(directory)
    if not os.path.isdir(directory):
        return jsonify({"error": f"Directory not found: {directory}"}), 404

    files = []
    for f in sorted(Path(directory).iterdir()):
        if f.suffix.lower() != ".wav" or not f.is_file():
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


def _ffmpeg_wav_to_flac_file(wav_path: str, flac_path: str) -> None:
    d = os.path.dirname(flac_path)
    if d:
        os.makedirs(d, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-y", "-i", wav_path,
            "-c:a", "flac", "-compression_level", "12",
            flac_path,
        ],
        capture_output=True, text=True, check=True,
    )


def _parse_ableton_performance_sample_stem(t0: str) -> dict | None:
    """
    Ableton-style **performance / sample** layout (hyphens separate fields in the browser):

        {leading key} - {artist} - {title} - {Camelot key} - {BPM}

    Example::

        A01 - Pleasurekraft - One Last High (Tiger Stripes Remix) - 1A - 126

    The first token is a Camelot-style code; the last two fields repeat key + BPM.
    This is **not** the same as the alternate pattern where **BPM** appears in the
    second field (see the m4 match in parse_ableton_style_wav_stem).
    """
    m = re.search(
        r"^(.+)\s*-\s*([0-9]{1,2}[ABa-b])\s*-\s*([0-9]{2,3})\s*$",
        t0,
        re.I,
    )
    if not m:
        return None
    body = m.group(1).strip()
    m2 = re.match(
        r"^([A-Za-z]?\d{1,2})\s*-\s*(.+)$",
        body,
        re.I,
    )
    if not m2:
        return None
    rest = m2.group(2).strip()
    sep = " - "
    i = rest.find(sep)
    if i >= 0:
        artist = rest[:i].strip().strip(" ,")
        artist = re.sub(r",\s*$", "", artist).strip()
        title = rest[i + len(sep) :].strip()
    else:
        # e.g. "Pleasurekraft,- One Last High ..." (comma or ",-" instead of " - " after artist)
        msep = re.match(r"^(.+?),\s*-\s*(.+)$", rest) or re.match(
            r"^(.+?),\s+(.+)$", rest
        )
        if not msep:
            return None
        artist = msep.group(1).strip().strip(" ,")
        title = msep.group(2).strip()
    if not artist or not title:
        return None
    return {
        "artist": artist,
        "title": title,
        "matched": True,
        "loose": "",
    }


def parse_ableton_style_wav_stem(stem: str) -> dict:
    """
    Parse DJ / Ableton-style stems for search and tag hints. Aligns with static/fix.js
    ``parseAbletonStyleFilename``.

    Supported forms include:

    1. **BPM in the second field** (common export): e.g.
       ``A06 - 139 - Members Of Mayday - 10 In 01`` → artist + title.

    2. **Ableton performance / sample** layout: leading key, artist, title, key, BPM
       (see ``_parse_ableton_performance_sample_stem``).

    3. Otherwise strip leading key/slot and trailing key+BPM (spaces or ``-`` between
       key and BPM where present) and build a **loose** search string.
    """
    t0 = re.sub(r"_PN$", "", stem, flags=re.I).strip()
    # Embedded _PN before " - 1A - 126" (some Platinum Notes exports)
    t0 = re.sub(r"(?i)_pn(?=\s*-)", "", t0).strip()
    if not t0:
        return {"artist": "", "title": "", "matched": False, "loose": ""}
    m4 = re.match(
        r"^(?:[A-Za-z]?\d+|Track\s*\d+|\d+)\s*-\s*\d{2,3}\s*-\s*(.+?)\s*-\s*(.+)$",
        t0,
        re.I,
    )
    if m4:
        return {
            "artist": m4.group(1).strip(),
            "title": m4.group(2).strip(),
            "matched": True,
            "loose": "",
        }
    perf = _parse_ableton_performance_sample_stem(t0)
    if perf:
        return perf
    t = strip_rekordbox_style_filename_affixes(t0)
    if not t:
        return {"artist": "", "title": "", "matched": False, "loose": ""}
    stripped = re.sub(
        r"^(?:[A-Za-z]?\d+|Track\s*\d+|\d+)\s*-\s*\d{2,3}\s*-\s*",
        "",
        t,
        flags=re.I,
    ).strip()
    rest = stripped or t
    rest = re.sub(r"\s*-\s*", " ", rest).replace("_", " ")
    rest = re.sub(r"\s+", " ", rest).strip()
    return {"artist": "", "title": rest, "matched": False, "loose": rest}


def _sanitize_basename(s: str) -> str:
    s = re.sub(r'[<>:"/\\|?*]', "", s)
    s = re.sub(r"\s+", " ", s).strip(" .")
    if len(s) > 200:
        s = s[:200].rstrip(" .")
    return s or "track"


def _flat_flac_filename_from_parsed(parsed: dict, stem_fallback: str) -> str:
    if parsed.get("matched") and parsed.get("artist") and parsed.get("title"):
        base = f"{parsed['artist']} - {parsed['title']}"
    elif parsed.get("matched") and parsed.get("title"):
        base = parsed["title"]
    elif parsed.get("loose") or (not parsed.get("matched") and (parsed.get("title") or "").strip()):
        base = (parsed.get("loose") or parsed.get("title") or stem_fallback).strip()
    else:
        base = stem_fallback
    return _sanitize_basename(base) + ".flac"


def _unique_path_in_dir(directory: str, filename: str) -> str:
    path = os.path.join(directory, filename)
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(filename)
    n = 2
    while n < 5000:
        cand = os.path.join(directory, f"{base} {n}{ext}")
        if not os.path.exists(cand):
            return cand
        n += 1
    return os.path.join(directory, f"{base} {n}{ext}")


def _embed_artist_title_tags_from_wav_stem(flac_path: str, wav_stem: str) -> None:
    p = parse_ableton_style_wav_stem(wav_stem)
    artist = (p.get("artist") or "").strip()
    title = (p.get("title") or "").strip()
    if not title and p.get("loose"):
        title = p["loose"].strip()
    if not artist and not title:
        return
    audio = FLAC(flac_path)
    if artist:
        audio["artist"] = [artist]
    if title:
        audio["title"] = [title]
    audio.save()


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


def _list_wav_paths_sorted(root_resolved: str, recursive: bool) -> list:
    """Stable sorted list of all .wav paths (for batch offset/limit)."""
    return sorted((p for p in _iter_wav_paths(root_resolved, recursive)), key=lambda p: p.lower())


def _bulk_flac_output_path(wav_path: str, root_resolved: str, output_mode: str, dest_resolved) -> str:
    """For destination, mirror the folder tree under dest (rel. to root) so names don’t collide."""
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


@app.route("/api/scan-wav-bulk")
def scan_wav_bulk():
    """Count .wav files under a root (for bulk convert UI)."""
    root = (request.args.get("path") or request.args.get("root") or "").strip()
    if not root:
        return jsonify({"error": "path or root query parameter required"}), 400
    recursive = request.args.get("recursive", "1").lower() in ("1", "true", "yes", "on")
    try:
        root_r = os.path.realpath(resolve(root))
    except (OSError, TypeError) as e:
        return jsonify({"error": str(e)}), 400
    if not os.path.isdir(root_r):
        return jsonify({"error": f"Not a directory: {root_r}"}), 404
    n = 0
    for _p in _iter_wav_paths(root_r, recursive):
        n += 1
    return jsonify({
        "root": root_r,
        "count": n,
        "recursive": recursive,
    })


@app.route("/api/convert-wav-bulk", methods=["POST"])
def convert_wav_bulk():
    """
    Recursively convert every .wav under a root. WAVs are not deleted.
    output=same: each .flac next to its .wav. output=destination: mirroring subpaths under
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
        root_r = os.path.realpath(resolve(root))
    except (OSError, TypeError) as e:
        return jsonify({"error": str(e)}), 400
    if not os.path.isdir(root_r):
        return jsonify({"error": f"Not a directory: {root_r}"}), 404

    target_r = None
    if output_mode == "custom":
        try:
            tpath = resolve(target_dir)
            target_r = os.path.realpath(tpath)
            os.makedirs(target_r, exist_ok=True)
        except (OSError, TypeError) as e:
            return jsonify({"error": f"Target folder: {e}"}), 400

    cfg = load_config()
    dest_resolved = None
    if output_mode == "destination":
        d = (cfg.get("destination_dir") or "").strip()
        if not d:
            return jsonify({
                "error": "Set a destination folder in Settings, or use “same as each WAV” for output.",
            }), 400
        dpath = resolve(d)
        if not os.path.isdir(dpath):
            return jsonify({
                "error": f"Destination folder does not exist: {dpath}",
            }), 400
        dest_resolved = os.path.realpath(dpath)

    all_wavs = _list_wav_paths_sorted(root_r, rec)
    total_wavs = len(all_wavs)
    if limit is not None:
        wav_queue = all_wavs[offset : offset + limit]
    else:
        wav_queue = all_wavs[offset:]

    ok = 0
    skipped = 0
    errors = []  # sample details; "errors" in summary = total count
    err_n = 0
    err_cap = 100
    batch_flac_paths = []
    for wav in wav_queue:
        stem = Path(wav).stem
        if output_mode == "custom" and target_r is not None:
            parsed = parse_ableton_style_wav_stem(stem)
            base_fname = _flat_flac_filename_from_parsed(parsed, stem)
            candidate = os.path.join(target_r, base_fname)
            if skip and os.path.isfile(candidate):
                skipped += 1
                batch_flac_paths.append(os.path.normpath(candidate))
                continue
            if os.path.isfile(candidate):
                out = _unique_path_in_dir(target_r, base_fname)
            else:
                out = candidate
        else:
            out = _bulk_flac_output_path(wav, root_r, output_mode, dest_resolved)
            if skip and os.path.isfile(out):
                skipped += 1
                batch_flac_paths.append(os.path.normpath(out))
                continue
        try:
            _ffmpeg_wav_to_flac_file(wav, out)
        except (subprocess.CalledProcessError, OSError) as e:
            err_n += 1
            msg = e.stderr if isinstance(e, subprocess.CalledProcessError) and getattr(e, "stderr", None) else str(e)
            if len(errors) < err_cap:
                errors.append({"source": wav, "error": (msg or str(e))[:500]})
            continue
        try:
            _embed_artist_title_tags_from_wav_stem(out, stem)
        except Exception as te:
            err_n += 1
            if len(errors) < err_cap:
                errors.append({"source": wav, "error": f"Tags: {te}"[:500]})
            continue
        ok += 1
        batch_flac_paths.append(os.path.normpath(out))
    j = {
        "root": root_r,
        "output": output_mode,
        "summary": {
            "converted": ok,
            "skipped": skipped,
            "errors": err_n,
        },
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
    return jsonify(j)


@app.route("/api/bulk-fix/scan-paths", methods=["POST"])
def bulk_fix_scan_paths():
    """
    Build the same scan payload as GET /api/bulk-fix/scan but for an explicit ordered list
    of .flac paths (e.g. output order from a WAV→FLAC bulk run, which may differ from
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
            p_r = os.path.realpath(resolve(p))
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
    """Encode a WAV to FLAC with ffmpeg; does not remove or alter the source WAV."""
    data = request.get_json() or {}
    filepath = (data.get("filepath") or "").strip()
    output_mode = (data.get("output") or "same").strip().lower()
    if output_mode not in ("same", "destination"):
        output_mode = "same"
    if not filepath or not os.path.isfile(filepath):
        return jsonify({"error": "File not found"}), 404
    if Path(filepath).suffix.lower() != ".wav":
        return jsonify({"error": "Only .wav source files are supported"}), 400

    cfg = load_config()
    stem = Path(filepath).stem
    out_name = f"{stem}.flac"

    if output_mode == "destination":
        dest = (cfg.get("destination_dir") or "").strip()
        if not dest:
            return jsonify({
                "error": "Destination folder is not set. Open Settings and set the destination folder, or choose “Same folder as the WAV file”.",
            }), 400
        dest_dir = resolve(dest)
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
        _ffmpeg_wav_to_flac_file(filepath, output_path)
    except subprocess.CalledProcessError as e:
        return jsonify({"error": f"ffmpeg failed: {e.stderr or e}"}), 500

    tag_error = None
    try:
        _embed_artist_title_tags_from_wav_stem(output_path, stem)
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


@app.route("/api/read-tags", methods=["POST"])
def read_tags():
    """Read metadata from any supported audio file."""
    data = request.get_json()
    filepath = data.get("filepath")
    if not filepath or not os.path.isfile(filepath):
        return jsonify({"error": "File not found"}), 404

    ext = os.path.splitext(filepath)[1].lower()

    try:
        if ext == ".flac":
            return jsonify(_read_flac_tags(filepath))
        elif ext == ".mp3":
            return jsonify(_read_mp3_tags(filepath))
        elif ext in (".m4a", ".mp4", ".aac"):
            return jsonify(_read_mp4_tags(filepath))
        elif ext in (".ogg", ".oga"):
            return jsonify(_read_vorbis_tags(filepath))
        else:
            return jsonify(_read_generic_tags(filepath))
    except Exception as e:
        return jsonify({"error": f"Cannot read tags: {e}"}), 400


def _read_flac_tags(filepath):
    audio = FLAC(filepath)
    vorbis_reverse = {
        "title": "title", "artist": "artist", "albumartist": "albumartist",
        "album": "album", "date": "date", "genre": "genre", "comment": "comment",
        "organization": "label", "catalognumber": "catno", "tracknumber": "tracknumber",
    }
    meta = {}
    for vorbis_key, field in vorbis_reverse.items():
        vals = audio.get(vorbis_key, [])
        if vals:
            meta[field] = vals[0]
    su = _source_url_from_vorbis(audio)
    if su:
        meta["source_url"] = su
    meta["has_artwork"] = len(audio.pictures) > 0
    meta["format"] = "FLAC"
    return meta


def _read_mp3_tags(filepath):
    audio = MP3(filepath, ID3=ID3)
    meta = {"format": "MP3"}
    if audio.tags is None:
        meta["has_artwork"] = False
        return meta
    t = audio.tags
    frame_map = {
        "TIT2": "title", "TPE1": "artist", "TPE2": "albumartist",
        "TALB": "album", "TDRC": "date", "TCON": "genre", "TPUB": "label",
        "TRCK": "tracknumber",
    }
    for frame_id, field in frame_map.items():
        frame = t.getall(frame_id)
        if frame:
            meta[field] = str(frame[0])
    comm = t.getall("COMM")
    if comm:
        meta["comment"] = str(comm[0])
    catno = t.getall("TXXX:CATALOGNUMBER")
    if catno:
        meta["catno"] = str(catno[0])
    su_new = su_legacy = None
    for frame in t.getall("TXXX"):
        desc = getattr(frame, "desc", "")
        if desc == SOURCE_URL_ID3_DESC and frame.text:
            su_new = str(frame.text[0])
        elif desc == SOURCE_URL_ID3_DESC_LEGACY and frame.text:
            su_legacy = str(frame.text[0])
    if su_new is not None:
        meta["source_url"] = su_new
    elif su_legacy is not None:
        meta["source_url"] = su_legacy
    meta["has_artwork"] = bool(t.getall("APIC"))
    return meta


def _read_mp4_tags(filepath):
    audio = MP4(filepath)
    meta = {"format": "AAC/M4A"}
    if audio.tags is None:
        meta["has_artwork"] = False
        return meta
    mp4_reverse = {
        "\xa9nam": "title", "\xa9ART": "artist", "aART": "albumartist",
        "\xa9alb": "album", "\xa9day": "date", "\xa9gen": "genre",
        "\xa9cmt": "comment",
    }
    for atom, field in mp4_reverse.items():
        vals = audio.tags.get(atom)
        if vals:
            meta[field] = str(vals[0])
    trkn = audio.tags.get("trkn")
    if trkn:
        meta["tracknumber"] = str(trkn[0][0])
    meta["has_artwork"] = bool(audio.tags.get("covr"))
    return meta


def _read_vorbis_tags(filepath):
    audio = OggVorbis(filepath)
    vorbis_reverse = {
        "title": "title", "artist": "artist", "albumartist": "albumartist",
        "album": "album", "date": "date", "genre": "genre", "comment": "comment",
        "organization": "label", "catalognumber": "catno", "tracknumber": "tracknumber",
    }
    meta = {"format": "OGG"}
    for vorbis_key, field in vorbis_reverse.items():
        vals = audio.get(vorbis_key, [])
        if vals:
            meta[field] = vals[0]
    su = _source_url_from_vorbis(audio)
    if su:
        meta["source_url"] = su
    meta["has_artwork"] = bool(audio.get("metadata_block_picture"))
    return meta


def _read_generic_tags(filepath):
    audio = mutagen.File(filepath, easy=True)
    if audio is None:
        return {"error": "Unsupported format", "has_artwork": False}
    meta = {"format": type(audio).__name__}
    easy_map = {"title": "title", "artist": "artist", "albumartist": "albumartist",
                "album": "album", "date": "date", "genre": "genre"}
    for tag, field in easy_map.items():
        vals = audio.get(tag, [])
        if vals:
            meta[field] = vals[0]
    meta["has_artwork"] = False
    return meta


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

    ext = os.path.splitext(filepath)[1].lower()
    stat = os.stat(filepath)

    try:
        if ext == ".flac":
            meta = _read_flac_tags(filepath)
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
            meta = _read_mp3_tags(filepath)
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
            meta = _read_mp4_tags(filepath)
            audio = MP4(filepath)
            if audio.tags and audio.tags.get("covr"):
                covr = audio.tags["covr"][0]
                fmt_name = "JPEG" if covr.imageformat == MP4Cover.FORMAT_JPEG else "PNG"
                meta["artwork_info"] = {
                    "mime": f"image/{'jpeg' if fmt_name == 'JPEG' else 'png'}",
                    "size_bytes": len(bytes(covr)),
                    "format": fmt_name,
                }
        elif ext in (".ogg", ".oga"):
            meta = _read_vorbis_tags(filepath)
        else:
            meta = _read_generic_tags(filepath)
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


def _serve_embedded_artwork(filepath):
    if not filepath or not os.path.isfile(filepath):
        return jsonify({"error": "File not found"}), 404

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
        elif ext in (".ogg", ".oga"):
            import base64
            audio = OggVorbis(filepath)
            pics = audio.get("metadata_block_picture", [])
            if pics:
                pic = Picture(base64.b64decode(pics[0]))
                return app.response_class(pic.data, mimetype=pic.mime)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify({"error": "No embedded artwork"}), 404


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5123, debug=True)
