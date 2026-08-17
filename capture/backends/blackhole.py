"""BlackHole + FFmpeg direct capture backend.

Records audio from BlackHole via AVFoundation as FLAC24 directly —
no OBS, no video container.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import signal
import threading
import time
from pathlib import Path

from capture.backends.base import (
    RecorderBackend, BackendStatus, RawRecording, SignalState,
)

log = logging.getLogger(__name__)

SILENCE_THRESHOLD_DB = -50.0
STOP_TIMEOUT_S = 5


def list_avfoundation_audio_devices() -> list[tuple[int, str]]:
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-f", "avfoundation",
         "-list_devices", "true", "-i", ""],
        capture_output=True, text=True, timeout=10,
    )
    output = result.stderr
    audio_section = False
    devices = []
    for line in output.split("\n"):
        if "AVFoundation audio devices:" in line:
            audio_section = True
            continue
        if audio_section and "AVFoundation video devices:" in line:
            break
        if audio_section:
            m = re.search(r'\[(\d+)\]\s+(.+)$', line)
            if m:
                devices.append((int(m.group(1)), m.group(2).strip()))
    return devices


def find_blackhole_device(device_name: str = "BlackHole 16ch") -> tuple[int, str] | None:
    devices = list_avfoundation_audio_devices()
    target = device_name.lower()
    for idx, name in devices:
        if name.lower() == target:
            return idx, name
    for idx, name in devices:
        if "blackhole" in name.lower() and "16ch" in name.lower():
            return idx, name
    for idx, name in devices:
        if "blackhole" in name.lower():
            return idx, name
    return None


def _pan_filter(channels: list[int]) -> str:
    """Build an FFmpeg pan filter to extract a stereo pair from a multi-channel input.

    channels: 1-indexed pair, e.g. [3, 4] extracts the 3rd and 4th input channels.
    """
    left = channels[0] - 1   # convert to 0-indexed
    right = channels[1] - 1
    return f"pan=stereo|FL=c{left}|FR=c{right}"


def probe_signal(device_index: int, duration: float = 2.0,
                 channels: list[int] | None = None) -> SignalState:
    """Run a short capture and check for signal on the selected channel pair."""
    import tempfile
    channels = channels or [3, 4]
    with tempfile.NamedTemporaryFile(suffix=".flac", delete=False) as f:
        tmp = f.name
    try:
        cmd = [
            "ffmpeg", "-hide_banner", "-y",
            "-thread_queue_size", "4096",
            "-f", "avfoundation", "-i", f":{device_index}",
            "-t", str(duration),
            "-af", _pan_filter(channels),
            "-c:a", "flac", "-f", "flac", tmp,
        ]
        subprocess.run(cmd, capture_output=True, text=True,
                       timeout=duration + 10)
        return _analyse_signal(tmp)
    except Exception as e:
        log.warning("Signal probe failed: %s", e)
        return SignalState()
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def _analyse_signal(filepath: str) -> SignalState:
    left_db = _channel_volume(filepath, 0)
    right_db = _channel_volume(filepath, 1)
    max_db = _max_volume(filepath)

    has_left = left_db > SILENCE_THRESHOLD_DB if left_db is not None else False
    has_right = right_db > SILENCE_THRESHOLD_DB if right_db is not None else False

    return SignalState(
        has_signal=has_left or has_right,
        left_db=left_db if left_db is not None else -100.0,
        right_db=right_db if right_db is not None else -100.0,
        clipping=max_db is not None and max_db >= -0.1,
        one_channel_missing=(has_left != has_right),
    )


def _channel_volume(filepath: str, channel: int) -> float | None:
    try:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-i", filepath,
             "-af", f"pan=mono|c0=c{channel},volumedetect",
             "-f", "null", "-"],
            capture_output=True, text=True, timeout=30,
        )
        m = re.search(r'mean_volume:\s*([-\d.]+)\s*dB', result.stderr)
        return float(m.group(1)) if m else None
    except Exception:
        return None


def _max_volume(filepath: str) -> float | None:
    try:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-i", filepath,
             "-af", "volumedetect", "-f", "null", "-"],
            capture_output=True, text=True, timeout=30,
        )
        m = re.search(r'max_volume:\s*([-\d.]+)\s*dB', result.stderr)
        return float(m.group(1)) if m else None
    except Exception:
        return None


class BlackHoleBackend(RecorderBackend):
    """Records from BlackHole via FFmpeg AVFoundation as FLAC24."""

    def __init__(self):
        self._status = BackendStatus.IDLE
        self._process: subprocess.Popen | None = None
        self._output_path = ""
        self._part_path = ""
        self._device_index: int | None = None
        self._device_name = ""
        self._stderr_lines: list[str] = []
        self._reader_thread: threading.Thread | None = None
        self._start_time = 0.0

    def preflight(self, config: dict) -> tuple[bool, list[str]]:
        issues = []

        try:
            subprocess.run(["ffmpeg", "-version"],
                           capture_output=True, timeout=5)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            issues.append("FFmpeg not found. Install: brew install ffmpeg")

        try:
            subprocess.run(["ffprobe", "-version"],
                           capture_output=True, timeout=5)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            issues.append("FFprobe not found. Install: brew install ffmpeg")

        device_name = config.get("blackhole_device_name", "BlackHole 16ch")
        result = find_blackhole_device(device_name)
        if result is None:
            issues.append(
                f"Audio device '{device_name}' not found. "
                "Install BlackHole: https://existential.audio/blackhole/"
            )
        else:
            self._device_index, self._device_name = result

        channels = config.get("blackhole_channels", [3, 4])
        if not isinstance(channels, list) or len(channels) != 2:
            issues.append("blackhole_channels must be a list of two channel numbers")
        elif any(c < 1 or c > 16 for c in channels):
            issues.append("blackhole_channels values must be between 1 and 16")

        return len(issues) == 0, issues

    def arm(self, output_path: str, config: dict) -> bool:
        if self._process is not None:
            log.warning("arm() called while a process is running")
            return False

        if self._device_index is None:
            device_name = config.get("blackhole_device_name", "BlackHole 16ch")
            result = find_blackhole_device(device_name)
            if result is None:
                self._status = BackendStatus.FAILED
                return False
            self._device_index, self._device_name = result

        self._output_path = output_path
        self._part_path = output_path + ".part"
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        channels = config.get("blackhole_channels", [3, 4])
        needs_pan = channels != [1, 2] or "16ch" in self._device_name.lower()

        cmd = [
            "ffmpeg", "-hide_banner", "-y",
            "-thread_queue_size", "4096",
            "-f", "avfoundation",
            "-i", f":{self._device_index}",
            "-map", "0:a:0", "-vn",
        ]
        if needs_pan:
            cmd += ["-af", _pan_filter(channels)]
        cmd += [
            "-c:a", "flac",
            "-compression_level", "12",
            "-sample_fmt", "s32",
            "-bits_per_raw_sample", "24",
            "-f", "flac",
            self._part_path,
        ]

        self._status = BackendStatus.ARMING
        self._stderr_lines = []

        try:
            self._process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
            )
        except Exception as e:
            log.error("Failed to start FFmpeg: %s", e)
            self._status = BackendStatus.FAILED
            return False

        self._reader_thread = threading.Thread(
            target=self._read_stderr, daemon=True,
            name="ffmpeg-stderr-reader",
        )
        self._reader_thread.start()

        # Wait briefly for FFmpeg to start up
        time.sleep(0.3)
        if self._process.poll() is not None:
            log.error("FFmpeg exited immediately: %s",
                      "\n".join(self._stderr_lines[-5:]))
            self._status = BackendStatus.FAILED
            self._process = None
            return False

        self._status = BackendStatus.ACTIVE
        self._start_time = time.monotonic()
        return True

    def status(self) -> BackendStatus:
        if self._process is not None and self._process.poll() is not None:
            if self._status == BackendStatus.ACTIVE:
                self._status = BackendStatus.FAILED
        return self._status

    def signal(self) -> SignalState:
        if self._status != BackendStatus.ACTIVE:
            return SignalState()
        if self._part_path and os.path.exists(self._part_path):
            size = os.path.getsize(self._part_path)
            elapsed = time.monotonic() - self._start_time
            if elapsed > 1.0:
                bytes_per_sec = size / elapsed
                has_signal = bytes_per_sec > 5000
                return SignalState(has_signal=has_signal)
        return SignalState(has_signal=True)

    def stop(self) -> RawRecording | None:
        if self._process is None:
            self._status = BackendStatus.IDLE
            return None

        self._status = BackendStatus.STOPPING

        # Send 'q' to gracefully stop FFmpeg
        try:
            self._process.stdin.write("q")
            self._process.stdin.flush()
        except (BrokenPipeError, OSError):
            pass

        try:
            self._process.wait(timeout=STOP_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            log.warning("FFmpeg did not exit after 'q', sending SIGTERM")
            self._process.terminate()
            try:
                self._process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                log.warning("FFmpeg did not exit after SIGTERM, sending SIGKILL")
                self._process.kill()
                self._process.wait(timeout=3)

        self._process = None
        if self._reader_thread:
            self._reader_thread.join(timeout=2)
            self._reader_thread = None

        if not os.path.exists(self._part_path):
            log.error("No output file: %s", self._part_path)
            self._status = BackendStatus.FAILED
            return None

        os.replace(self._part_path, self._output_path)

        duration = time.monotonic() - self._start_time
        self._status = BackendStatus.IDLE

        return RawRecording(
            path=self._output_path,
            duration_seconds=duration,
            sample_rate=0,
            channels=2,
            codec="flac",
        )

    def abort(self):
        if self._process is not None:
            try:
                self._process.kill()
            except OSError:
                pass
            try:
                self._process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                pass
            self._process = None
        if self._reader_thread:
            self._reader_thread.join(timeout=2)
            self._reader_thread = None
        self._status = BackendStatus.IDLE

    def cleanup(self):
        self.abort()
        self._device_index = None

    def _read_stderr(self):
        proc = self._process
        if proc is None or proc.stderr is None:
            return
        try:
            for line in proc.stderr:
                stripped = line.rstrip()
                if stripped:
                    self._stderr_lines.append(stripped)
                    if len(self._stderr_lines) > 200:
                        self._stderr_lines = self._stderr_lines[-100:]
        except (ValueError, OSError):
            pass
