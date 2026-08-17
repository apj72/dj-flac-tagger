#!/usr/bin/env python3
"""
Phase 0 Spike — OBS WebSocket v5 control

Tests:
1. Can we connect and authenticate to OBS WebSocket?
2. Can we get OBS version and recording status?
3. Can we start and stop a short recording?
4. Do we get the output path back from StopRecord?
5. Can we convert ALAC24/MKV to FLAC24 and verify sample preservation?

Requires: obsws-python (pip install obsws-python)
Requires: OBS Studio 28+ running with WebSocket server enabled

Usage:
    python capture/spikes/spike_obs.py [--host HOST] [--port PORT] [--password PASS]
    python capture/spikes/spike_obs.py --record   # also tests start/stop recording
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time


def check_obsws_available():
    """Check if obsws-python is installed."""
    try:
        import obsws_python
        print(f"  obsws-python version: {obsws_python.__version__}")
        return True
    except ImportError:
        print("  FAIL: obsws-python not installed")
        print("  Install: pip install obsws-python")
        return False


def test_connection(host, port, password):
    """Test OBS WebSocket connection and authentication."""
    print(f"\n=== Test 1: Connect to OBS at {host}:{port} ===")

    import obsws_python as obs

    try:
        cl = obs.ReqClient(host=host, port=port, password=password, timeout=5)
        version = cl.get_version()
        print(f"  OBS version: {version.obs_version}")
        print(f"  WebSocket version: {version.obs_web_socket_version}")
        print(f"  Platform: {version.platform}")
        print("  PASS: Connected and authenticated")
        return cl
    except Exception as e:
        print(f"  FAIL: {e}")
        if "authentication" in str(e).lower():
            print("  Check your OBS WebSocket password.")
        elif "refused" in str(e).lower() or "connect" in str(e).lower():
            print("  Is OBS running? Is WebSocket server enabled?")
            print("  OBS > Tools > WebSocket Server Settings > Enable WebSocket server")
        return None


def test_record_status(cl):
    """Check current recording status."""
    print("\n=== Test 2: Recording status ===")
    try:
        status = cl.get_record_status()
        active = status.output_active
        paused = status.output_paused
        print(f"  Recording active: {active}")
        print(f"  Recording paused: {paused}")
        if hasattr(status, 'output_duration'):
            print(f"  Duration: {status.output_duration}")
        if hasattr(status, 'output_bytes'):
            print(f"  Bytes: {status.output_bytes}")
        if active:
            print("  WARNING: OBS is currently recording. Stop it before testing.")
            return False
        print("  PASS: OBS is idle and ready")
        return True
    except Exception as e:
        print(f"  FAIL: {e}")
        return False


def test_start_stop_record(cl, duration=3):
    """Start and stop a short recording, capture the output path."""
    print(f"\n=== Test 3: Start/stop {duration}s recording ===")

    try:
        # Start recording
        print("  Starting recording...")
        cl.start_record()
        time.sleep(1)

        # Verify it's active
        status = cl.get_record_status()
        if not status.output_active:
            print("  FAIL: Recording did not become active")
            return None

        print(f"  Recording active: {status.output_active}")
        time.sleep(duration)

        # Stop recording
        print("  Stopping recording...")
        result = cl.stop_record()

        # Get output path
        output_path = result.output_path if hasattr(result, 'output_path') else None
        print(f"  Output path from StopRecord: {output_path}")

        if output_path and os.path.exists(output_path):
            file_size = os.path.getsize(output_path)
            print(f"  File exists: {output_path}")
            print(f"  File size: {file_size:,} bytes")
            print("  PASS: Recording start/stop works, output path returned")
            return output_path
        elif output_path:
            # OBS may take a moment to finalise the file
            print("  Waiting for file to appear...")
            for _ in range(10):
                time.sleep(0.5)
                if os.path.exists(output_path):
                    file_size = os.path.getsize(output_path)
                    print(f"  File appeared: {file_size:,} bytes")
                    print("  PASS: Recording works (file appeared after brief delay)")
                    return output_path
            print(f"  FAIL: Output path returned but file not found: {output_path}")
            return None
        else:
            print("  FAIL: No output path returned from StopRecord")
            return None

    except Exception as e:
        print(f"  FAIL: {e}")
        import traceback; traceback.print_exc()
        try:
            cl.stop_record()
        except Exception:
            pass
        return None


def test_probe_obs_recording(filepath):
    """FFprobe the OBS recording to check codec, sample rate, channels, bit depth."""
    print(f"\n=== Test 4: FFprobe OBS recording ===")

    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_streams",
            "-show_entries",
            "stream=codec_type,codec_name,sample_rate,channels,channel_layout,"
            "bits_per_raw_sample,sample_fmt,bit_rate,duration",
            "-show_entries", "format=format_name,duration,size",
            "-of", "json",
            filepath,
        ],
        capture_output=True, text=True,
    )

    data = json.loads(result.stdout)
    streams = data.get("streams", [])
    fmt = data.get("format", {})

    print(f"  Container: {fmt.get('format_name', '?')}")
    print(f"  Streams: {len(streams)}")

    audio_stream = None
    for s in streams:
        stype = s.get("codec_type", "?")
        codec = s.get("codec_name", "?")
        print(f"    {stype}: {codec}", end="")
        if stype == "audio":
            audio_stream = s
            sr = s.get("sample_rate", "?")
            ch = s.get("channels", "?")
            bits = s.get("bits_per_raw_sample", "?")
            sfmt = s.get("sample_fmt", "?")
            print(f" sr={sr} ch={ch} bits_raw={bits} fmt={sfmt}")
        else:
            print()

    if audio_stream:
        codec = audio_stream.get("codec_name", "?")
        is_alac = codec == "alac"
        bits = str(audio_stream.get("bits_per_raw_sample", "?"))
        print(f"\n  Audio codec is ALAC: {'YES' if is_alac else 'NO (' + codec + ')'}")
        print(f"  24-bit: {'YES' if bits == '24' else 'NO (' + bits + ')'}")
        if is_alac and bits == "24":
            print("  PASS: OBS produced ALAC 24-bit as expected")
        elif is_alac:
            print(f"  WARNING: ALAC but {bits}-bit, not 24-bit. Check OBS encoder settings.")
        else:
            print(f"  WARNING: Codec is {codec}, not ALAC. Check OBS recording settings.")
    else:
        print("  FAIL: No audio stream found")

    return audio_stream


def test_alac_to_flac_conversion(input_mkv):
    """Convert ALAC24/MKV to FLAC24 and verify."""
    print(f"\n=== Test 5: ALAC24 -> FLAC24 conversion ===")

    with tempfile.NamedTemporaryFile(suffix=".flac", delete=False) as f:
        flac_path = f.name

    cmd = [
        "ffmpeg", "-hide_banner", "-y",
        "-i", input_mkv,
        "-map", "0:a:0",
        "-vn",
        "-c:a", "flac",
        "-compression_level", "12",
        "-sample_fmt", "s32",
        "-bits_per_raw_sample", "24",
        "-f", "flac",
        flac_path,
    ]

    print(f"  Converting...")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"  FAIL: FFmpeg conversion failed")
        print(f"  stderr: {result.stderr[-500:]}")
        return None

    # Verify the output
    probe = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_streams", "-select_streams", "a:0",
            "-show_entries",
            "stream=codec_name,sample_rate,channels,bits_per_raw_sample,sample_fmt",
            "-of", "json",
            flac_path,
        ],
        capture_output=True, text=True,
    )

    data = json.loads(probe.stdout)
    stream = data.get("streams", [{}])[0]

    codec = stream.get("codec_name", "?")
    sr = stream.get("sample_rate", "?")
    ch = stream.get("channels", "?")
    bits = stream.get("bits_per_raw_sample", "?")

    print(f"  Output: codec={codec} sr={sr} ch={ch} bits_raw={bits}")

    checks = {
        "FLAC codec": codec == "flac",
        "24-bit": str(bits) == "24",
        "stereo": str(ch) == "2",
    }

    all_pass = True
    for label, ok in checks.items():
        print(f"  {'PASS' if ok else 'FAIL'}: {label}")
        if not ok:
            all_pass = False

    # Sample-level hash comparison
    if all_pass:
        print("\n  Comparing decoded samples (SHA-256 of pcm_s24le)...")
        src_hash = _decode_hash(input_mkv)
        dst_hash = _decode_hash(flac_path)
        if src_hash and dst_hash:
            if src_hash == dst_hash:
                print(f"  PASS: Decoded samples are identical ({src_hash[:16]}...)")
            else:
                print(f"  FAIL: Sample mismatch! Source={src_hash[:16]}... Output={dst_hash[:16]}...")
                all_pass = False
        else:
            print("  WARNING: Could not compute decode hashes")

    print(f"\n  FLAC output retained at: {flac_path}")
    return flac_path if all_pass else None


def _decode_hash(filepath):
    """Decode audio to pcm_s24le and return SHA-256 hash of the raw samples."""
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-hide_banner",
                "-i", filepath,
                "-map", "0:a:0",
                "-f", "s24le",
                "-acodec", "pcm_s24le",
                "pipe:1",
            ],
            capture_output=True,
            timeout=60,
        )
        if result.returncode != 0:
            return None
        return hashlib.sha256(result.stdout).hexdigest()
    except Exception:
        return None


def main():
    parser = argparse.ArgumentParser(description="OBS WebSocket spike")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=4455)
    parser.add_argument("--password", default="")
    parser.add_argument("--record", action="store_true",
                        help="Test start/stop recording (will create a file in OBS output dir)")
    args = parser.parse_args()

    print("DJ MetaManager — Phase 0 Spike: OBS WebSocket")
    print("=" * 48)

    # Check dependency
    print("\n=== Dependency check ===")
    if not check_obsws_available():
        sys.exit(1)

    # Test 1: Connection
    cl = test_connection(args.host, args.port, args.password)
    if not cl:
        sys.exit(1)

    # Test 2: Status
    idle = test_record_status(cl)

    if args.record and idle:
        # Test 3: Start/stop
        output_path = test_start_stop_record(cl, duration=3)
        if output_path:
            # Test 4: Probe
            audio = test_probe_obs_recording(output_path)
            if audio and audio.get("codec_name") == "alac":
                # Test 5: Convert
                test_alac_to_flac_conversion(output_path)
            elif audio:
                print(f"\n  Skipping conversion test — OBS codec is '{audio.get('codec_name')}', not ALAC.")
                print("  To test ALAC24 conversion, set OBS audio encoder to FFmpeg ALAC 24-bit.")
    elif not args.record:
        print("\n  Recording test skipped. Use --record to test start/stop.")

    print("\n" + "=" * 48)
    print("Spike complete. Review the results above.")


if __name__ == "__main__":
    main()
