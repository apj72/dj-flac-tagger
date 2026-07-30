"""FFmpeg/ffprobe operations and audio processing."""

__all__ = [
    'run_ffprobe', '_loudnorm_tail_aformat_and_rate',
    '_aformat_opts_preserve_stream', 'analyse_loudness',
    '_ffmpeg_loudnorm_encode', 'extract_audio', '_ffmpeg_wav_to_flac_file',
    '_embed_artist_title_tags_from_wav_stem', 'trash_file',
    '_PREVIEW_CACHE_DIR', '_preview_cache_path', '_cleanup_preview_cache',
]

import atexit
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from mutagen.flac import FLAC

from config import (
    EXTRACT_PROFILES,
    get_normalisation_targets,
    parse_ableton_style_wav_stem,
)


# ---------------------------------------------------------------------------
# FFprobe
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


# ---------------------------------------------------------------------------
# Loudnorm helpers
# ---------------------------------------------------------------------------

def _loudnorm_tail_aformat_and_rate(input_path):
    """Sample rate (int or None) and aformat=... string matching source layout (keeps 48 kHz vs accidental 192 kHz bloat)."""
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


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Encoding
# ---------------------------------------------------------------------------

def _ffmpeg_loudnorm_encode(input_path, output_path, loudnorm_params, profile_key, target_lufs=None, target_tp=None):
    """Two-pass EBU R128 loudnorm -- measured_* from analyse_loudness (first pass); encode per extract profile."""
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


# ---------------------------------------------------------------------------
# WAV -> FLAC
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Trash
# ---------------------------------------------------------------------------

def trash_file(filepath):
    """Move a file to macOS Bin via Finder (recoverable)."""
    script = (
        f'tell application "Finder" to delete '
        f'(POSIX file "{filepath}" as alias)'
    )
    subprocess.run(["osascript", "-e", script], capture_output=True, text=True, check=True)


# ---------------------------------------------------------------------------
# Preview cache
# ---------------------------------------------------------------------------

_PREVIEW_CACHE_DIR = os.path.join(tempfile.gettempdir(), "djmm_preview_cache")


def _preview_cache_path(src_path: str) -> str:
    """Return a deterministic cache path for a transcoded preview of *src_path*."""
    mtime = os.path.getmtime(src_path)
    key = f"{os.path.realpath(src_path)}\0{mtime}"
    h = hashlib.sha256(key.encode()).hexdigest()[:16]
    os.makedirs(_PREVIEW_CACHE_DIR, exist_ok=True)
    return os.path.join(_PREVIEW_CACHE_DIR, f"{h}.m4a")


def _cleanup_preview_cache(max_age_secs: int = 86400) -> None:
    try:
        if not os.path.isdir(_PREVIEW_CACHE_DIR):
            return
        now = time.time()
        for name in os.listdir(_PREVIEW_CACHE_DIR):
            fp = os.path.join(_PREVIEW_CACHE_DIR, name)
            try:
                if now - os.path.getmtime(fp) > max_age_secs:
                    os.unlink(fp)
            except OSError:
                pass
    except OSError:
        pass


atexit.register(_cleanup_preview_cache)
