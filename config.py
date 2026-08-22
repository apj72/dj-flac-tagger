"""Constants, configuration, paths, and filename helpers for DJ MetaManager."""

__all__ = [
    'AUDIO_EXTENSIONS', 'STREAM_AUDIO_EXTENSIONS', 'VIDEO_SOURCE_EXTENSIONS',
    '_mime_type_for_stream', 'EXTRACT_PROFILES', 'MP3_BITRATE_OPTIONS',
    'AAC_BITRATE_OPTIONS', '_PROFILE_KEY_MIGRATION', '_resolve_profile',
    'resolve_extract_profile_key', 'extract_profile_options',
    'bundle_base_path', 'writable_app_data_dir',
    '_default_config_path', '_default_log_path', '_default_logged_tracks_path',
    '_prepend_bundled_ffmpeg_to_path', 'CONFIG_PATH', 'LOG_PATH',
    'LOGGED_TRACKS_PATH', '_get_config_path', '_get_log_path',
    '_get_logged_tracks_path', 'load_config', 'save_config', 'resolve',
    'get_normalisation_targets', '_loudnorm_params_usable',
    'normalised_output_meets_targets', 'load_log', 'save_log', 'log_extraction',
    'load_logged_tracks', 'save_logged_tracks', 'SOURCE_URL_VORBIS',
    'SOURCE_URL_VORBIS_LEGACY', 'SOURCE_URL_ID3_DESC',
    'SOURCE_URL_ID3_DESC_LEGACY', 'infer_metadata_source_type',
    'find_log_entry_for_output_path', 'post_extract_open_app',
    'pn_derivative_path', '_pn_output_candidate_paths',
    'normalize_fix_retain_filename_suffixes',
    'scrub_ableton_warp_marker_from_search_text',
    '_scrub_bulk_search_hints_dict', 'peel_fix_retain_suffixes',
    'strip_rekordbox_style_filename_affixes', '_normalize_track_filename_stem',
    '_parse_ableton_performance_sample_stem', 'parse_ableton_style_wav_stem',
    '_sanitize_basename', '_flat_flac_filename_from_parsed',
    '_unique_path_in_dir', '_basename_from_artist_title_for_rename',
    '_retained_suffix_from_filepath', 'search_query_from_ableton_stem',
    '_get_allowed_dirs', '_validate_path_in_allowed_dirs',
]

import json
import os
import re
import subprocess
import sys
import tempfile
import unicodedata
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Audio / video extension sets
# ---------------------------------------------------------------------------

AUDIO_EXTENSIONS = (".flac", ".mp3", ".m4a", ".mp4", ".aac", ".ogg", ".oga", ".wma", ".aiff", ".aif")

# Streamed in the in-browser preview bar (.wav from WAV -> FLAC is not listed with browse-audio).
STREAM_AUDIO_EXTENSIONS = frozenset(
    (*AUDIO_EXTENSIONS, ".wav"),
)

# Video files listed on Extract (step 1); rename/delete must stay in the browsed folder.
VIDEO_SOURCE_EXTENSIONS = (".mkv", ".mp4", ".mov", ".avi", ".webm")


def _mime_type_for_stream(ext: str) -> str:
    return {
        ".flac": "audio/flac",
        ".mp3": "audio/mpeg",
        ".m4a": "audio/mp4",
        ".mp4": "audio/mp4",
        ".aac": "audio/mp4",
        ".ogg": "audio/ogg",
        ".oga": "audio/ogg",
        ".wav": "audio/wav",
        ".aiff": "audio/aiff",
        ".aif": "audio/aiff",
        ".wma": "audio/x-ms-wma",
    }.get(ext, "application/octet-stream")


# ---------------------------------------------------------------------------
# Extract profiles
# ---------------------------------------------------------------------------

# System-wide extract / normalise output format (see Settings: extract_profile).
EXTRACT_PROFILES = {
    "flac": {
        "label": "FLAC (lossless)",
        "ext": ".flac",
        "lossless": True,
        "ffmpeg_encode": ["-c:a", "flac", "-compression_level", "12", "-sample_fmt", "s16"],
    },
    "mp3": {
        "label": "MP3 320 kbps CBR",
        "ext": ".mp3",
        "lossless": False,
        "ffmpeg_encode": ["-c:a", "libmp3lame", "-b:a", "320k"],
    },
    "aac": {
        "label": "AAC 256 kbps (M4A)",
        "ext": ".m4a",
        "lossless": False,
        "ffmpeg_encode": ["-c:a", "aac", "-b:a", "256k"],
    },
}

MP3_BITRATE_OPTIONS = ["128", "192", "256", "320"]
AAC_BITRATE_OPTIONS = ["96", "128", "192", "256"]

_PROFILE_KEY_MIGRATION = {"mp3_320": "mp3", "aac_256": "aac"}


def _resolve_profile(profile_key, cfg=None):
    base = EXTRACT_PROFILES.get(profile_key)
    if base is None:
        base = EXTRACT_PROFILES["flac"]
    prof = dict(base)
    if cfg is None:
        cfg = load_config()
    if profile_key == "mp3":
        br = cfg.get("mp3_bitrate", "320")
        if br not in MP3_BITRATE_OPTIONS:
            br = "320"
        prof["ffmpeg_encode"] = ["-c:a", "libmp3lame", "-b:a", f"{br}k"]
        prof["label"] = f"MP3 {br} kbps CBR"
    elif profile_key == "aac":
        br = cfg.get("aac_bitrate", "256")
        if br not in AAC_BITRATE_OPTIONS:
            br = "256"
        prof["ffmpeg_encode"] = ["-c:a", "aac", "-b:a", f"{br}k"]
        prof["label"] = f"AAC {br} kbps (M4A)"
    return prof


def resolve_extract_profile_key(cfg=None):
    if cfg is None:
        cfg = load_config()
    k = (cfg.get("extract_profile") or "flac").strip().lower()
    k = _PROFILE_KEY_MIGRATION.get(k, k)
    if k in EXTRACT_PROFILES:
        return k
    return "flac"


def extract_profile_options(cfg=None):
    return [{"key": key, "label": _resolve_profile(key, cfg)["label"]} for key in EXTRACT_PROFILES]


# ---------------------------------------------------------------------------
# App paths (bundled / development)
# ---------------------------------------------------------------------------

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


def _default_logged_tracks_path():
    if getattr(sys, "frozen", False):
        return str(writable_app_data_dir() / "logged_tracks.json")
    return str(Path(__file__).resolve().parent / "logged_tracks.json")


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


# ---------------------------------------------------------------------------
# Module-level path variables & accessors
# ---------------------------------------------------------------------------
# These are overridden at runtime by app.py so that test monkeypatching of
# ``app.CONFIG_PATH`` etc. is seen by functions in this module.

CONFIG_PATH = _default_config_path()
LOG_PATH = _default_log_path()
LOGGED_TRACKS_PATH = _default_logged_tracks_path()


def _get_config_path():
    return CONFIG_PATH


def _get_log_path():
    return LOG_PATH


def _get_logged_tracks_path():
    return LOGGED_TRACKS_PATH


# ---------------------------------------------------------------------------
# Config load / save
# ---------------------------------------------------------------------------

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
        # extract_profile: flac | mp3 | aac
        "extract_profile": "flac",
        "mp3_bitrate": "320",
        "aac_bitrate": "256",
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
        "capture": {
            "backend": "obs",
            "pre_roll_ms": 750,
            "post_roll_ms": 750,
            "music_poll_ms": 250,
            "play_start_timeout_s": 15,
            "playback_stall_timeout_s": 12,
            "duration_grace_s": 15,
            "disk_reserve_gb": 5,
            "output_dir": "~/Music/playlist_recordings",
            "blackhole_device_name": "BlackHole 2ch",
            "blackhole_channels": [1, 2],
            "obs": {
                "host": "127.0.0.1",
                "port": 4455,
                "password": "",
            },
        },
    }
    try:
        with open(_get_config_path()) as f:
            cfg = json.load(f)
        defaults.update(cfg)
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return defaults


def save_config(cfg):
    with open(_get_config_path(), "w") as f:
        json.dump(cfg, f, indent=2)
        f.write("\n")


def resolve(path):
    return os.path.expanduser(path)


# ---------------------------------------------------------------------------
# Normalisation targets & checks
# ---------------------------------------------------------------------------

def get_normalisation_targets():
    """LUFS / dBTP targets from config (defaults -14 / -1). Positive LUFS values are treated as negative (e.g. 11.5 -> -11.5)."""
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


# ---------------------------------------------------------------------------
# Processing log
# ---------------------------------------------------------------------------

def load_log():
    try:
        with open(_get_log_path()) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_log(entries):
    with open(_get_log_path(), "w") as f:
        json.dump(entries, f, indent=2)
        f.write("\n")


def log_extraction(entry):
    entries = load_log()
    entry["timestamp"] = datetime.now().isoformat()
    entries.append(entry)
    save_log(entries)
    return len(entries) - 1


# ---------------------------------------------------------------------------
# Logged tracks (Apple Music Now Playing captures)
# ---------------------------------------------------------------------------

def load_logged_tracks():
    try:
        with open(_get_logged_tracks_path()) as f:
            data = json.load(f)
        if not isinstance(data, dict) or "tracks" not in data:
            return {"schema_version": 1, "tracks": []}
        return data
    except (FileNotFoundError, json.JSONDecodeError):
        return {"schema_version": 1, "tracks": []}


def save_logged_tracks(data):
    ltp = _get_logged_tracks_path()
    dir_path = os.path.dirname(ltp) or "."
    fd, tmp = tempfile.mkstemp(dir=dir_path, prefix=".logged_tracks_", suffix=".json")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        os.replace(tmp, ltp)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Source URL tag constants
# ---------------------------------------------------------------------------

SOURCE_URL_VORBIS = "DJMETAMANAGER_SOURCE_URL"
SOURCE_URL_VORBIS_LEGACY = "DJFLACTAGGER_SOURCE_URL"
SOURCE_URL_ID3_DESC = "DJMETAMANAGER_SOURCE_URL"
SOURCE_URL_ID3_DESC_LEGACY = "DJFLACTAGGER_SOURCE_URL"


# ---------------------------------------------------------------------------
# Metadata source inference & log lookup
# ---------------------------------------------------------------------------

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
        from urllib.parse import urlparse
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
            os.startfile(file_path)  # noqa: S606 -- opens default handler; PN may still be manual
            pass
        else:
            subprocess.Popen(["xdg-open", file_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Platinum Notes helpers
# ---------------------------------------------------------------------------

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
# Filename suffix peeling & search query building
# ---------------------------------------------------------------------------

def normalize_fix_retain_filename_suffixes(raw) -> list[str]:
    """
    Coerce config value to a list of rule lines.

    If `config.json` stores a single string (e.g. `_warped`) by mistake, iterating that
    string would match one character at a time and never strip `_warped` as a whole.
    """
    if raw is None:
        return []
    if isinstance(raw, list):
        out: list[str] = []
        for x in raw:
            s = str(x).strip()
            if s and not s.startswith("#"):
                out.append(s)
        return out
    if isinstance(raw, str):
        return [ln.strip() for ln in raw.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    return []


def scrub_ableton_warp_marker_from_search_text(
    s: str,
    *,
    filename_stem: str | None = None,
) -> str:
    """
    Remove Ableton Live **Warp** export noise from catalogue search strings.

    Runs regardless of Settings: many users skip configuring ``fix_retain_filename_suffixes``,
    and loose parsing turns ``..._warped`` into ``... warped`` (no underscore), which literal
    ``_warped`` rules never match.

    When *filename_stem* ends with ``_warped``, we also peel a lone trailing `` warped``
    (Ableton spaced form after loose parsing). That is gated so arbitrary tracks legitimately
    titled ``... warped`` are not rewritten when the underlying file stem had no Ableton warp
    marker suffix.
    """
    if not (s or "").strip():
        return (s or "").strip()
    t = unicodedata.normalize("NFC", (s or "").strip())
    t = t.replace("（", "(").replace("）", ")")
    t = re.sub(r"(?i)_warped\s*$", "", t).rstrip()
    t = re.sub(r"(?i)\)warped\s*$", ")", t).rstrip()
    t = re.sub(r"(?i)\)(?:[-–—_\s])+warped\s*$", ")", t).rstrip()
    st = (filename_stem or "").strip()
    if st and re.search(r"(?i)_warped\s*$", st):
        t = re.sub(r"(?i)\s+warped\s*$", "", t).rstrip()
    return t


def _scrub_bulk_search_hints_dict(
    d: dict,
    *,
    filename_stem: str | None = None,
) -> dict:
    """Strip Ableton warp export noise from values used only for catalogue search."""
    out = dict(d)
    stem = (filename_stem or "").strip() or None
    for key in ("query", "title_hint", "artist_hint"):
        val = out.get(key) or ""
        if val.strip():
            out[key] = scrub_ableton_warp_marker_from_search_text(val, filename_stem=stem)
    return out


def peel_fix_retain_suffixes(stem: str, lines: list | str | None) -> tuple[str, str]:
    """
    Repeatedly peel configured suffix patterns from the **end** of stem for search parsing.
    Returns (core_stem, retained_concat) where retained is pieces left-to-right after the core
    (e.g. core ``Track``, retained ``_bpm(120)_warped``).
    """
    cur = (stem or "").strip()
    lines = normalize_fix_retain_filename_suffixes(lines)
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
                lowline = line.lower()
                n = len(line)
                matched_piece_l: str | None = None
                if n <= len(cur) and cur[-n:].lower() == lowline:
                    matched_piece_l = cur[-n:]
                elif lowline == "_warped":
                    # WAV / store tags often use ") warped" while the FLAC filename uses ")_warped".
                    wm = re.search(r"(?<=\))(?:_\s*|\s+)?warped\s*$", cur, flags=re.I)
                    if wm is not None:
                        matched_piece_l = wm.group(0)
                if matched_piece_l is not None:
                    matched_piece = matched_piece_l
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
    or collecting **samples for a set**--hyphens separate fields for quick visual scanning
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


# ---------------------------------------------------------------------------
# Filename stem parsing (Ableton / DAW conventions)
# ---------------------------------------------------------------------------

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
       ``A06 - 139 - Members Of Mayday - 10 In 01`` -> artist + title.

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
    _c, retained = peel_fix_retain_suffixes(
        stem, cfg.get("fix_retain_filename_suffixes"),
    )
    return retained


def search_query_from_ableton_stem(stem: str) -> dict:
    """
    Build an online search query from a file stem (matches Fix Metadata / fix.js intent).
    """
    cfg = load_config()
    core, _ret = peel_fix_retain_suffixes(
        stem, cfg.get("fix_retain_filename_suffixes"),
    )
    p = parse_ableton_style_wav_stem(core)
    if p.get("matched") and (p.get("artist") or "").strip() and (p.get("title") or "").strip():
        a = p["artist"].strip()
        t = p["title"].strip()
        q = f"{a} {t}"
        out = {
            "query": re.sub(r"\s+", " ", q).strip(),
            "title_hint": t,
            "artist_hint": a,
            "pattern_matched": True,
        }
    elif (p.get("title") or "").strip() and not p.get("matched"):
        loose = p["title"].strip()
        out = {
            "query": loose,
            "title_hint": loose,
            "artist_hint": "",
            "pattern_matched": False,
        }
    elif p.get("loose"):
        out = {
            "query": p["loose"],
            "title_hint": "",
            "artist_hint": "",
            "pattern_matched": False,
        }
    else:
        tail = _normalize_track_filename_stem(core)
        t = re.sub(r"\s+", " ", tail.replace("_", " ")).strip()
        out = {
            "query": t,
            "title_hint": "",
            "artist_hint": "",
            "pattern_matched": False,
        }
    return _scrub_bulk_search_hints_dict(out, filename_stem=stem)


# ---------------------------------------------------------------------------
# Path traversal defense
# ---------------------------------------------------------------------------

def _get_allowed_dirs():
    cfg = load_config()
    dirs = []
    for key in ("source_dir", "destination_dir", "fix_metadata_default_dir", "inspect_default_dir"):
        val = cfg.get(key, "")
        if val:
            dirs.append(os.path.realpath(resolve(val)))
    extra = cfg.get("allowed_extra_dirs", [])
    if isinstance(extra, str):
        extra = [extra]
    if isinstance(extra, (list, tuple)):
        for val in extra:
            if val and isinstance(val, str):
                dirs.append(os.path.realpath(resolve(val)))
    dirs.append(os.path.realpath(tempfile.gettempdir()))
    return dirs


def _validate_path_in_allowed_dirs(filepath, allowed_dirs=None):
    if not filepath:
        raise ValueError("Empty file path")
    resolved = os.path.realpath(resolve(filepath))
    if allowed_dirs is None:
        allowed_dirs = _get_allowed_dirs()
    for d in allowed_dirs:
        prefix = d if d.endswith(os.sep) else d + os.sep
        if resolved == d or resolved.startswith(prefix):
            return resolved
    raise ValueError(f"Path is outside all allowed directories: {resolved}")
