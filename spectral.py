"""Spectral analysis for detecting lossy transcodes in lossless containers."""

__all__ = [
    'analyze_lossless_authenticity',
]

import json
import os
import subprocess

import numpy as np


_BITRATE_THRESHOLDS = [
    (15500, "~128 kbps"),
    (16500, "~160 kbps"),
    (17500, "~192 kbps"),
    (18500, "~224 kbps"),
    (19500, "~256 kbps"),
    (20500, "~320 kbps"),
]


def _estimate_bitrate(cutoff_hz):
    for threshold, label in _BITRATE_THRESHOLDS:
        if cutoff_hz < threshold:
            return label
    return "~320 kbps"


def analyze_lossless_authenticity(filepath):
    """Analyze a file's spectrum to detect lossy transcoding.

    Returns dict with verdict, cutoff_freq, estimated_bitrate, confidence,
    sample_rate, nyquist, and duration.
    """
    info = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_streams", "-select_streams", "a:0",
            "-show_entries",
            "stream=sample_rate,channels,duration",
            "-show_entries", "format=duration",
            "-of", "json",
            filepath,
        ],
        capture_output=True, text=True,
    )
    probe = json.loads(info.stdout)
    stream = probe["streams"][0] if probe.get("streams") else {}
    sr = int(float(stream.get("sample_rate", 44100)))
    dur_str = (
        stream.get("duration")
        or probe.get("format", {}).get("duration")
        or "0"
    )
    duration = float(dur_str) if dur_str != "N/A" else 0.0
    nyquist = sr / 2

    if nyquist < 18000:
        return {
            "verdict": "inconclusive",
            "reason": f"Sample rate {sr} Hz — Nyquist too low for reliable detection",
            "cutoff_freq": None,
            "estimated_bitrate": None,
            "confidence": None,
            "sample_rate": sr,
            "nyquist": nyquist,
            "duration": round(duration, 1),
        }

    segment_len = min(30, duration)
    start = max(0, (duration / 2) - (segment_len / 2))

    cmd = [
        "ffmpeg", "-v", "error",
        "-ss", str(start), "-t", str(segment_len),
        "-i", filepath,
        "-ac", "1", "-ar", str(sr),
        "-f", "f32le", "-acodec", "pcm_f32le",
        "pipe:1",
    ]
    proc = subprocess.run(cmd, capture_output=True)
    samples = np.frombuffer(proc.stdout, dtype=np.float32)

    if duration <= 0 and len(samples) > 0:
        duration = len(samples) / sr

    if len(samples) < 8192:
        return {
            "verdict": "error",
            "reason": "Not enough audio data to analyze",
            "cutoff_freq": None,
            "estimated_bitrate": None,
            "confidence": None,
            "sample_rate": sr,
            "nyquist": nyquist,
            "duration": round(duration, 1),
        }

    window_size = 8192
    hop = window_size // 2
    num_windows = (len(samples) - window_size) // hop
    if num_windows < 1:
        num_windows = 1

    avg_spectrum = np.zeros(window_size // 2 + 1)
    window = np.hanning(window_size)

    for i in range(num_windows):
        start_idx = i * hop
        segment = samples[start_idx:start_idx + window_size] * window
        fft = np.fft.rfft(segment)
        avg_spectrum += np.abs(fft) ** 2

    avg_spectrum /= num_windows
    avg_spectrum_db = 10.0 * np.log10(avg_spectrum + 1e-20)

    freqs = np.fft.rfftfreq(window_size, 1.0 / sr)

    kernel_size = 30
    kernel = np.ones(kernel_size) / kernel_size
    smoothed = np.convolve(avg_spectrum_db, kernel, mode="same")

    ref_mask = (freqs >= 8000) & (freqs < 14000)
    if not np.any(ref_mask):
        return {
            "verdict": "error",
            "reason": "Cannot compute reference energy band",
            "cutoff_freq": None,
            "estimated_bitrate": None,
            "confidence": None,
            "sample_rate": sr,
            "nyquist": nyquist,
            "duration": round(duration, 1),
        }

    ref_energy = np.mean(smoothed[ref_mask])

    cutoff_freq = None
    drop_db = 0

    for f in range(14000, int(nyquist), 500):
        band_mask = (freqs >= f) & (freqs < f + 500)
        if not np.any(band_mask):
            break
        band_energy = np.mean(smoothed[band_mask])
        drop = ref_energy - band_energy
        if drop > 30:
            cutoff_freq = f
            drop_db = round(drop, 1)
            break

    if cutoff_freq is None:
        next_mask = (freqs >= 14000) & (freqs <= nyquist)
        if np.any(next_mask):
            gradient = np.diff(smoothed[next_mask])
            gradient_freqs = freqs[next_mask][:-1]
            min_idx = np.argmin(gradient)
            steepest_drop = -gradient[min_idx]
            if steepest_drop > 3.0:
                candidate = float(gradient_freqs[min_idx])
                band_above = (freqs >= candidate + 500) & (freqs < candidate + 1500)
                if np.any(band_above):
                    energy_above = np.mean(smoothed[band_above])
                    local_drop = ref_energy - energy_above
                    if local_drop > 20:
                        cutoff_freq = int(candidate)
                        drop_db = round(local_drop, 1)

    if cutoff_freq is not None:
        # A cutoff alone does not prove a lossy transcode. A lossless hi-res
        # source that has been sample-rate-converted down to the capture device
        # rate (e.g. 96 kHz -> 44.1 kHz by CoreAudio) also shows a rolloff — but
        # its shape is different:
        #
        #   * Lossy transcode (AAC/MP3): energy is cut, then a FLAT silent
        #     plateau extends from the cutoff all the way up to Nyquist. The band
        #     between the cut and Nyquist is unused.
        #   * Sample-rate conversion: the anti-alias filter rides a STEEP
        #     transition band right up to Nyquist, only reaching the noise floor
        #     in the last ~1 kHz. The band is used all the way to the limit.
        #
        # So we find where the spectrum actually bottoms out (reaches the noise
        # floor) and compare that to Nyquist. If the floor is reached essentially
        # AT Nyquist, the rolloff is the device's sample-rate limit — the source
        # is lossless, just resampled. If there is a silent plateau well below
        # Nyquist, it is a genuine lossy cut.
        hf_region = smoothed[(freqs >= 14000) & (freqs <= nyquist)]
        if hf_region.size:
            floor_db = float(np.percentile(hf_region, 5))
        else:
            floor_db = ref_energy - 100.0
        reach_mask = (
            (freqs >= cutoff_freq) & (freqs <= nyquist)
            & (smoothed <= floor_db + 8.0)
        )
        if np.any(reach_mask):
            reach_floor_freq = float(freqs[reach_mask][0])
        else:
            reach_floor_freq = nyquist
        gap_ratio = (nyquist - reach_floor_freq) / nyquist if nyquist else 1.0

        if gap_ratio <= 0.06:
            # Band used all the way to Nyquist → sample-rate-conversion rolloff,
            # not a lossy encoder. Lossless source downsampled to the device rate.
            return {
                "verdict": "resampled",
                "reason": (
                    f"Rolloff rides to Nyquist (floor reached at "
                    f"{int(reach_floor_freq)} Hz of {int(nyquist)} Hz) — "
                    f"lossless source sample-rate-converted to {sr} Hz, "
                    f"not a lossy transcode"
                ),
                "cutoff_freq": cutoff_freq,
                "estimated_bitrate": None,
                "confidence": "high",
                "sample_rate": sr,
                "nyquist": nyquist,
                "duration": round(duration, 1),
            }

        estimated_bitrate = _estimate_bitrate(cutoff_freq)
        if drop_db > 35:
            confidence = "high"
        elif drop_db > 25:
            confidence = "medium"
        else:
            confidence = "low"
        return {
            "verdict": "transcode",
            "reason": (
                f"Sharp spectral cutoff at {cutoff_freq} Hz ({drop_db} dB drop) "
                f"with a silent plateau to Nyquist"
            ),
            "cutoff_freq": cutoff_freq,
            "estimated_bitrate": estimated_bitrate,
            "confidence": confidence,
            "sample_rate": sr,
            "nyquist": nyquist,
            "duration": round(duration, 1),
        }

    return {
        "verdict": "lossless",
        "reason": "Spectral energy extends to Nyquist with no sharp cutoff",
        "cutoff_freq": None,
        "estimated_bitrate": None,
        "confidence": "high",
        "sample_rate": sr,
        "nyquist": nyquist,
        "duration": round(duration, 1),
    }
