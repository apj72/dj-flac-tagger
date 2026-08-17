"""FLAC24 conversion, FFprobe validation, and tagging for capture."""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from capture.models import PlannedTrack


@dataclass
class AudioFacts:
    codec: str = ""
    sample_rate: int = 0
    channels: int = 0
    bits_per_raw_sample: int = 0
    sample_fmt: str = ""
    duration: float = 0.0
    file_size: int = 0


@dataclass
class VerifyResult:
    ok: bool
    facts: AudioFacts
    issues: list[str]


# ---------------------------------------------------------------------------
# FLAC24 encode args (separate from existing Extract s16 profile)
# ---------------------------------------------------------------------------

FLAC24_ENCODE_ARGS = [
    "-c:a", "flac",
    "-compression_level", "12",
    "-sample_fmt", "s32",
    "-bits_per_raw_sample", "24",
]


def ffprobe_audio(filepath: str) -> AudioFacts:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_streams", "-select_streams", "a:0",
            "-show_entries",
            "stream=codec_name,sample_rate,channels,duration,"
            "bits_per_raw_sample,sample_fmt",
            "-show_entries", "format=duration,size",
            "-of", "json",
            filepath,
        ],
        capture_output=True, text=True, timeout=30,
    )
    data = json.loads(result.stdout)
    stream = (data.get("streams") or [{}])[0]
    fmt = data.get("format", {})

    sr = stream.get("sample_rate", "0")
    try:
        sr_int = int(sr)
    except (ValueError, TypeError):
        sr_int = 0

    ch = stream.get("channels", 0)
    try:
        ch_int = int(ch)
    except (ValueError, TypeError):
        ch_int = 0

    bits = stream.get("bits_per_raw_sample", "0")
    try:
        bits_int = int(bits)
    except (ValueError, TypeError):
        bits_int = 0

    dur_str = stream.get("duration") or fmt.get("duration", "0")
    try:
        dur = float(dur_str)
    except (ValueError, TypeError):
        dur = 0.0

    size_str = fmt.get("size", "0")
    try:
        file_size = int(size_str)
    except (ValueError, TypeError):
        file_size = 0

    return AudioFacts(
        codec=stream.get("codec_name", ""),
        sample_rate=sr_int,
        channels=ch_int,
        bits_per_raw_sample=bits_int,
        sample_fmt=stream.get("sample_fmt", ""),
        duration=dur,
        file_size=file_size,
    )


def verify_flac24(filepath: str, expected_duration: float = 0.0,
                  duration_tolerance: float = 15.0) -> VerifyResult:
    facts = ffprobe_audio(filepath)
    issues = []

    if facts.codec != "flac":
        issues.append(f"Codec is '{facts.codec}', expected 'flac'")
    if facts.channels != 2:
        issues.append(f"Channels: {facts.channels}, expected 2")
    if facts.bits_per_raw_sample != 24:
        issues.append(
            f"Bits per raw sample: {facts.bits_per_raw_sample}, expected 24"
        )
    if expected_duration > 0 and facts.duration > 0:
        diff = abs(facts.duration - expected_duration)
        if diff > duration_tolerance:
            issues.append(
                f"Duration {facts.duration:.1f}s vs expected "
                f"{expected_duration:.1f}s (diff {diff:.1f}s)"
            )

    return VerifyResult(ok=len(issues) == 0, facts=facts, issues=issues)


def convert_alac_to_flac24(input_path: str, output_path: str) -> str:
    """Convert an ALAC/MKV to FLAC24. Returns the final output path."""
    part_path = output_path + ".part"
    cmd = [
        "ffmpeg", "-hide_banner", "-y",
        "-i", input_path,
        "-map", "0:a:0",
        "-vn",
        *FLAC24_ENCODE_ARGS,
        "-f", "flac",
        part_path,
    ]
    result = subprocess.run(
        cmd, capture_output=True, text=True, check=True, timeout=300,
    )
    os.replace(part_path, output_path)
    return output_path


def apply_capture_tags(filepath: str, track: PlannedTrack,
                       session_id: str, backend: str):
    """Apply metadata from the planned track to the output file."""
    from metadata import apply_metadata

    meta = {}
    if track.title:
        meta["title"] = track.title
    if track.artist:
        meta["artist"] = track.artist
    if track.album_artist:
        meta["albumartist"] = track.album_artist
    if track.album:
        meta["album"] = track.album
    if track.year:
        meta["date"] = str(track.year)
    if track.genre:
        meta["genre"] = track.genre
    if track.track_number:
        meta["tracknumber"] = str(track.track_number)
    if track.store_url:
        meta["source_url"] = track.store_url

    meta["comment"] = f"Captured by DJ MetaManager (session {session_id})"

    apply_metadata(filepath, meta)


def safe_filename(artist: str, title: str, ext: str = ".flac") -> str:
    """Build a filesystem-safe 'Artist - Title.ext' filename."""
    name = f"{artist} - {title}" if artist and title else (title or artist or "Unknown")
    forbidden = r'[<>:"/\\|?*\x00-\x1f]'
    name = re.sub(forbidden, "_", name).strip(". ")
    if not name:
        name = "Unknown"
    if len(name) > 200:
        name = name[:200].rstrip(". ")
    return name + ext


def resolve_output_path(output_dir: str, artist: str, title: str,
                        ext: str = ".flac") -> str:
    """Build a collision-safe output path."""
    name = safe_filename(artist, title, ext)
    path = os.path.join(output_dir, name)
    if not os.path.exists(path):
        return path
    base, ext_part = os.path.splitext(name)
    n = 2
    while True:
        candidate = os.path.join(output_dir, f"{base} ({n}){ext_part}")
        if not os.path.exists(candidate):
            return candidate
        n += 1
