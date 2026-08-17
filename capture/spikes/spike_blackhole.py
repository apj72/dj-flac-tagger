#!/usr/bin/env python3
"""
Phase 0 Spike — BlackHole direct FFmpeg capture

Tests:
1. Can FFmpeg list AVFoundation audio devices?
2. Is BlackHole 2ch present?
3. Can we capture a short FLAC24 recording from BlackHole?
4. Does FFprobe confirm FLAC, stereo, 24-bit, correct sample rate?
5. Signal detection: is there audio present or silence?

Usage:
    python capture/spikes/spike_blackhole.py

    Play audio through BlackHole before running (e.g. play something in Music
    routed to BlackHole or a Multi-Output Device containing BlackHole).
"""

import subprocess
import json
import os
import re
import sys
import tempfile
import time


def find_blackhole_device():
    """List AVFoundation audio devices and find BlackHole 2ch."""
    print("\n=== Test 1: AVFoundation audio device discovery ===")

    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-f", "avfoundation", "-list_devices", "true", "-i", ""],
        capture_output=True, text=True,
    )
    # Device list is on stderr (ffmpeg exits non-zero for -list_devices)
    output = result.stderr
    print("  Raw device output:")
    for line in output.split("\n"):
        if "AVFoundation" in line:
            print(f"    {line.strip()}")

    # Parse audio devices — they appear after "AVFoundation audio devices:"
    audio_section = False
    devices = []
    for line in output.split("\n"):
        if "AVFoundation audio devices:" in line:
            audio_section = True
            continue
        if audio_section and "AVFoundation video devices:" in line:
            break
        if audio_section:
            # Pattern: [AVFoundation indev @ ...] [index] Device Name
            m = re.search(r'\[(\d+)\]\s+(.+)$', line)
            if m:
                devices.append((int(m.group(1)), m.group(2).strip()))

    print(f"\n  Audio devices found: {len(devices)}")
    for idx, name in devices:
        marker = " <-- BlackHole" if "blackhole" in name.lower() else ""
        print(f"    [{idx}] {name}{marker}")

    # Find BlackHole 2ch
    blackhole = [(idx, name) for idx, name in devices if "blackhole 2ch" in name.lower()]
    if not blackhole:
        blackhole = [(idx, name) for idx, name in devices if "blackhole" in name.lower()]

    if blackhole:
        bh_idx, bh_name = blackhole[0]
        print(f"\n  PASS: Found '{bh_name}' at index {bh_idx}")
        return bh_idx, bh_name
    else:
        print("\n  FAIL: BlackHole not found in audio devices")
        print("  Install BlackHole: https://existential.audio/blackhole/")
        return None, None


def test_capture(device_index, duration=3):
    """Capture a short FLAC24 recording from BlackHole."""
    print(f"\n=== Test 2: Capture {duration}s FLAC24 from device :{device_index} ===")

    with tempfile.NamedTemporaryFile(suffix=".flac", delete=False) as f:
        output_path = f.name

    cmd = [
        "ffmpeg", "-hide_banner", "-y",
        "-thread_queue_size", "4096",
        "-f", "avfoundation",
        "-i", f":{device_index}",
        "-map", "0:a:0",
        "-vn",
        "-t", str(duration),
        "-c:a", "flac",
        "-compression_level", "12",
        "-sample_fmt", "s32",
        "-bits_per_raw_sample", "24",
        "-f", "flac",
        output_path,
    ]

    print(f"  Command: {' '.join(cmd)}")
    print(f"  Recording {duration} seconds...")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True, text=True,
            timeout=duration + 15,
        )

        if result.returncode != 0:
            print(f"  FAIL: FFmpeg exited {result.returncode}")
            print(f"  stderr: {result.stderr[-500:]}")
            return None

        file_size = os.path.getsize(output_path)
        print(f"  Output: {output_path}")
        print(f"  File size: {file_size:,} bytes")

        if file_size < 100:
            print("  FAIL: Output file is suspiciously small")
            return None

        print("  PASS: FLAC capture completed")
        return output_path

    except subprocess.TimeoutExpired:
        print("  FAIL: FFmpeg timed out")
        return None
    except Exception as e:
        print(f"  FAIL: {e}")
        return None


def test_ffprobe(filepath):
    """Verify the captured file is FLAC, stereo, 24-bit."""
    print(f"\n=== Test 3: FFprobe verification ===")

    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_streams", "-select_streams", "a:0",
            "-show_entries",
            "stream=codec_name,sample_rate,channels,duration,channel_layout,"
            "bits_per_raw_sample,sample_fmt,bit_rate",
            "-show_entries", "format=duration,size",
            "-of", "json",
            filepath,
        ],
        capture_output=True, text=True,
    )

    data = json.loads(result.stdout)

    stream = data.get("streams", [{}])[0] if data.get("streams") else {}
    fmt = data.get("format", {})

    codec = stream.get("codec_name", "?")
    sample_rate = stream.get("sample_rate", "?")
    channels = stream.get("channels", "?")
    bits_raw = stream.get("bits_per_raw_sample", "?")
    sample_fmt = stream.get("sample_fmt", "?")
    duration = fmt.get("duration", stream.get("duration", "?"))
    layout = stream.get("channel_layout", "?")

    print(f"  Codec:              {codec}")
    print(f"  Sample rate:        {sample_rate} Hz")
    print(f"  Channels:           {channels} ({layout})")
    print(f"  Sample format:      {sample_fmt}")
    print(f"  Bits per raw sample: {bits_raw}")
    print(f"  Duration:           {duration}s")

    checks = {
        "codec is FLAC": codec == "flac",
        "stereo (2 channels)": str(channels) == "2",
        "24-bit raw": str(bits_raw) == "24",
        "sample_fmt is s32": sample_fmt == "s32",
    }

    all_pass = True
    for check, ok in checks.items():
        status = "PASS" if ok else "FAIL"
        print(f"  {status}: {check}")
        if not ok:
            all_pass = False

    return all_pass, {
        "codec": codec,
        "sample_rate": sample_rate,
        "channels": channels,
        "bits_per_raw_sample": bits_raw,
        "sample_fmt": sample_fmt,
        "duration": duration,
    }


def test_signal_detection(filepath):
    """Check if the captured audio has signal or is silence."""
    print(f"\n=== Test 4: Signal detection ===")

    # Use ffmpeg volumedetect to get mean and max volume
    result = subprocess.run(
        [
            "ffmpeg", "-hide_banner",
            "-i", filepath,
            "-af", "volumedetect",
            "-f", "null", "-",
        ],
        capture_output=True, text=True,
    )

    stderr = result.stderr
    mean_match = re.search(r'mean_volume:\s*([-\d.]+)\s*dB', stderr)
    max_match = re.search(r'max_volume:\s*([-\d.]+)\s*dB', stderr)

    mean_vol = float(mean_match.group(1)) if mean_match else None
    max_vol = float(max_match.group(1)) if max_match else None

    print(f"  Mean volume: {mean_vol} dB" if mean_vol else "  Mean volume: unknown")
    print(f"  Max volume:  {max_vol} dB" if max_vol else "  Max volume:  unknown")

    SILENCE_THRESHOLD = -50.0  # dBFS

    if mean_vol is not None:
        if mean_vol > SILENCE_THRESHOLD:
            print(f"  PASS: Audio signal detected (mean {mean_vol:.1f} dB > {SILENCE_THRESHOLD} dB)")
            return True
        else:
            print(f"  WARNING: Audio is very quiet or silent (mean {mean_vol:.1f} dB)")
            print("  Make sure audio is routed through BlackHole and something is playing.")
            return False
    else:
        print("  WARNING: Could not determine volume levels")
        return False


def test_per_channel_signal(filepath):
    """Check each channel separately for signal."""
    print(f"\n=== Test 5: Per-channel signal check ===")

    for ch, label in [(0, "Left"), (1, "Right")]:
        result = subprocess.run(
            [
                "ffmpeg", "-hide_banner",
                "-i", filepath,
                "-af", f"pan=mono|c0=c{ch},volumedetect",
                "-f", "null", "-",
            ],
            capture_output=True, text=True,
        )
        mean_match = re.search(r'mean_volume:\s*([-\d.]+)\s*dB', result.stderr)
        max_match = re.search(r'max_volume:\s*([-\d.]+)\s*dB', result.stderr)
        mean_vol = float(mean_match.group(1)) if mean_match else None
        max_vol = float(max_match.group(1)) if max_match else None

        has_signal = mean_vol is not None and mean_vol > -50.0
        status = "SIGNAL" if has_signal else "SILENT/LOW"
        print(f"  {label}: mean={mean_vol:.1f} dB, max={max_vol:.1f} dB — {status}"
              if mean_vol is not None else f"  {label}: unknown")


def main():
    print("DJ MetaManager — Phase 0 Spike: BlackHole Direct Capture")
    print("=" * 58)
    print()
    print("Before running, ensure:")
    print("  1. BlackHole 2ch is installed")
    print("  2. Music (or another source) is routed to BlackHole")
    print("  3. Something is playing through BlackHole (for signal test)")
    print()

    # Check FFmpeg available
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=5)
    except FileNotFoundError:
        print("FAIL: ffmpeg not found. Install: brew install ffmpeg")
        sys.exit(1)

    # Test 1: Find BlackHole
    bh_idx, bh_name = find_blackhole_device()
    if bh_idx is None:
        sys.exit(1)

    # Test 2: Capture
    filepath = test_capture(bh_idx, duration=3)
    if not filepath:
        sys.exit(1)

    # Test 3: Verify
    probe_ok, facts = test_ffprobe(filepath)

    # Test 4-5: Signal
    test_signal_detection(filepath)
    test_per_channel_signal(filepath)

    # Cleanup
    print(f"\n  Test file retained at: {filepath}")
    print("  Delete it manually when done reviewing.\n")

    print("=" * 58)
    print("Spike complete. Review the results above.")
    if probe_ok:
        print("FLAC24 capture: VERIFIED")
    else:
        print("FLAC24 capture: ISSUES FOUND — review above")


if __name__ == "__main__":
    main()
