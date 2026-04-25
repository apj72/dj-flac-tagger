#!/usr/bin/env python3
"""
Stand-alone loudness / loudnorm diagnostic (does not import the app).

Uses ffmpeg + ffprobe from PATH to:
  • Print ffprobe stream info (rate, layout, format)
  • First-pass EBU R128 (loudnorm print_format=json) — same as "Analyse" in the app
  • volumedetect max/mean
  • Optional: second pass to null (measured_* from a fresh first pass) — what the
    DJ MetaManager two-pass *should* report for output I / TP, given targets
  • Optional: compare a second file (e.g. "sounds over-amplified" output) and
    flag true-peak or integrated loudness red flags
  • Optional: stress-test stale first-pass: shift measured_I (simulates re-using
    analysis from the wrong or glitched file)

Requires: ffmpeg and ffprobe on PATH. Python 3.10+.

Example:
  python3 scripts/diagnose_loudness.py \\
    "/path/to/source.flac" \\
    --compare "/path/to/output_PN.flac" \\
    --target-lufs -11.5 --target-tp -1.0

Quick scan (first 90 s of each file, faster but not identical to full-track stats):
  python3 scripts/diagnose_loudness.py a.flac -c b.flac -t 90
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


def _ff_bin(name: str) -> str:
    p = shutil.which(name)
    if not p:
        print(f"error: {name} not found on PATH", file=sys.stderr)
        sys.exit(1)
    return p


def _input_prefix(duration_s: float | None) -> list[str]:
    if duration_s is None or duration_s <= 0:
        return []
    return ["-t", str(duration_s)]


def _extract_loudnorm_json(stderr: str) -> dict[str, Any]:
    """Last JSON object in stderr (loudnorm prints one)."""
    if not stderr:
        return {}
    a = stderr.rfind("{")
    b = stderr.rfind("}") + 1
    if a == -1 or b <= a:
        return {}
    try:
        return json.loads(stderr[a:b])
    except json.JSONDecodeError:
        return {}


def ffprobe_stream(path: str, duration_s: float | None) -> dict[str, Any]:
    ff = _ff_bin("ffprobe")
    cmd = [
        ff,
        "-v",
        "error",
        "-select_streams",
        "a:0",
        "-show_entries",
        "stream=sample_rate,channels,channel_layout,codec_name,sample_fmt",
        "-show_entries",
        "format=duration,format_name",
        "-of",
        "json",
        *_input_prefix(duration_s),
        path,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr, file=sys.stderr)
        print(f"ffprobe failed (exit {r.returncode}) for: {path}", file=sys.stderr)
        sys.exit(1)
    return json.loads(r.stdout)


def _aformat_tail(info: dict[str, Any]) -> tuple[int | None, str]:
    """Match app.py _loudnorm_tail_aformat_and_rate: sample rate and aformat=... string."""
    streams = info.get("streams") or []
    s0 = streams[0] if streams else {}
    sr = s0.get("sample_rate")
    ch = s0.get("channels")
    if not sr or ch is None:
        return None, "sample_fmts=s16"
    sr_i = int(float(sr))
    ch_i = int(ch)
    layout = s0.get("channel_layout")
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


def first_pass_loudnorm(path: str, duration_s: float | None) -> dict[str, Any]:
    ffmpeg = _ff_bin("ffmpeg")
    cmd = [
        ffmpeg,
        "-hide_banner",
        "-nostats",
        *_input_prefix(duration_s),
        "-i",
        path,
        "-af",
        "loudnorm=print_format=json",
        "-f",
        "null",
        "-",
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr, file=sys.stderr)
        print(f"ffmpeg (first pass) failed for: {path}", file=sys.stderr)
        sys.exit(1)
    return _extract_loudnorm_json(r.stderr)


def volumedetect(path: str, duration_s: float | None) -> dict[str, float | None]:
    ffmpeg = _ff_bin("ffmpeg")
    r = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-nostats",
            *_input_prefix(duration_s),
            "-i",
            path,
            "-af",
            "volumedetect",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        print(r.stderr, file=sys.stderr)
        return {}
    out: dict[str, float | None] = {"mean_volume_db": None, "max_volume_db": None}
    for line in r.stderr.splitlines():
        m = re.search(r"mean_volume:\s*([-\d.]+)\s*dB", line)
        if m:
            out["mean_volume_db"] = float(m.group(1))
        m = re.search(r"max_volume:\s*([-\d.]+)\s*dB", line)
        if m:
            out["max_volume_db"] = float(m.group(1))
    return out


def second_pass_loudnorm_json(
    path: str,
    measured: dict[str, float],
    target_lufs: float,
    target_tp: float,
    aformat_part: str,
    sample_rate: int | None,
    duration_s: float | None,
) -> dict[str, Any]:
    """
    App-style two-pass: linear=true, LRA=11, measured_I/TP/LRA/thresh, then aformat, -ar.
    """
    ffmpeg = _ff_bin("ffmpeg")
    m_i = measured.get("input_i", -24.0)
    m_tp = measured.get("input_tp", -2.0)
    m_lra = measured.get("input_lra", 7.0)
    m_th = measured.get("input_thresh", -34.0)
    af = (
        f"loudnorm=I={target_lufs}:TP={target_tp}:LRA=11"
        f":measured_I={m_i}:measured_TP={m_tp}:measured_LRA={m_lra}:measured_thresh={m_th}"
        f":linear=true:print_format=json"
        f",aformat={aformat_part}"
    )
    ar_args: list[str] = ["-ar", str(sample_rate)] if sample_rate is not None else []
    r = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-nostats",
            *_input_prefix(duration_s),
            "-i",
            path,
            "-map",
            "0:a:0",
            "-vn",
            "-af",
            af,
            *ar_args,
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        print(r.stderr, file=sys.stderr)
        print("ffmpeg (second pass) failed", file=sys.stderr)
        sys.exit(1)
    return _extract_loudnorm_json(r.stderr)


def _float_or(d: dict[str, Any], k: str, default: float = 0.0) -> float:
    v = d.get(k, default)
    if v is None:
        return default
    return float(v)


def _print_file_block(label: str, path: str) -> None:
    print()
    print("=" * 72)
    print(f"{label}")
    print(f"  path: {path}")


def main() -> int:
    try:
        sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        pass

    ap = argparse.ArgumentParser(
        description="Diagnose EBU R128 / loudnorm behaviour without the DJ MetaManager app."
    )
    ap.add_argument("source", type=str, help="Original audio file (e.g. pre-normalise)")
    ap.add_argument(
        "-c",
        "--compare",
        type=str,
        default=None,
        help="Optional second file (e.g. normalised output) to compare",
    )
    ap.add_argument(
        "-t",
        "--duration",
        type=float,
        default=None,
        metavar="SEC",
        help="Only decode first SEC seconds of each file (faster; stats differ from full track)",
    )
    ap.add_argument(
        "--target-lufs",
        type=float,
        default=-11.5,
        help="Second-pass I= target (default -11.5, common club / PN-style; app reads Settings)",
    )
    ap.add_argument(
        "--target-tp",
        type=float,
        default=-1.0,
        help="Second-pass TP= true-peak ceiling dBTP (default -1)",
    )
    ap.add_argument(
        "--skip-simulate",
        action="store_true",
        help="Do not run the two-pass (second pass) simulation on the source",
    )
    ap.add_argument(
        "--stale-mi-delta",
        type=float,
        default=None,
        metavar="dB",
        help=(
            "After a fresh first pass on the source, run a second two-pass to null where "
            "measured_I is offset by dB (e.g. -10 simulates a first pass that was 10 dB too quiet). "
            "Shows how a wrong / stale analysis can over-boost."
        ),
    )
    ap.add_argument(
        "--stale-compare-file",
        type=str,
        default=None,
        metavar="FILE",
        help=(
            "Run a first pass on this file and use *its* measured_* for the two-pass of SOURCE — "
            "proves 'wrong file' first-pass in the app would mis-normalise the source."
        ),
    )
    args = ap.parse_args()
    source = str(Path(args.source).expanduser())
    compare = str(Path(args.compare).expanduser()) if args.compare else None
    dur = args.duration

    _ff_bin("ffmpeg")
    _ff_bin("ffprobe")

    for p in (source, compare):
        if p and not Path(p).is_file():
            print(f"error: not a file: {p}", file=sys.stderr)
            return 1

    # --- source ---
    _print_file_block("SOURCE — ffprobe (audio stream 0)", source)
    info = ffprobe_stream(source, dur)
    print(json.dumps(info, indent=2))
    sr, aform = _aformat_tail(info)
    if dur:
        print(f"  (duration-limited: first {dur:g} s)")

    _print_file_block("SOURCE — first pass (loudnorm print_format=json)", source)
    l1 = first_pass_loudnorm(source, dur)
    print(json.dumps(l1, indent=2) if l1 else "{}")

    vol = volumedetect(source, dur)
    if vol:
        print("  volumedetect:", vol)

    sim = None
    if not args.skip_simulate and l1:
        _print_file_block("SIMULATION — app-style 2nd pass to null (matched measured_* from this run)", source)
        measured = {k: _float_or(l1, k) for k in ("input_i", "input_tp", "input_lra", "input_thresh")}
        # loudnorm output keys are strings; second_pass expects float fields named input_*
        sim = second_pass_loudnorm_json(
            source, measured, args.target_lufs, args.target_tp, aform, sr, dur
        )
        print(json.dumps(sim, indent=2) if sim else "{}")

    stale_sim: dict[str, Any] | None = None
    if args.stale_mi_delta is not None and l1:
        m = {k: _float_or(l1, k) for k in ("input_i", "input_tp", "input_lra", "input_thresh")}
        m["input_i"] = m["input_i"] + float(args.stale_mi_delta)
        _print_file_block(
            f'STALE first-pass test — 2nd pass with measured_I += {args.stale_mi_delta} dB (wrong analysis)',
            source,
        )
        stale_sim = second_pass_loudnorm_json(source, m, args.target_lufs, args.target_tp, aform, sr, dur)
        print(json.dumps(stale_sim, indent=2) if stale_sim else "{}")

    if args.stale_compare_file:
        other = str(Path(args.stale_compare_file).expanduser())
        if not Path(other).is_file():
            print(f"error: not a file: {other}", file=sys.stderr)
            return 1
        _print_file_block("WRONG file first pass (measured from this file) — then 2nd pass on SOURCE", other)
        l_wrong = first_pass_loudnorm(other, dur)
        print("First pass of wrong file:", json.dumps(l_wrong, indent=2) if l_wrong else "{}")
        m_wrong = {k: _float_or(l_wrong, k) for k in ("input_i", "input_tp", "input_lra", "input_thresh")}
        x_sim = second_pass_loudnorm_json(
            source, m_wrong, args.target_lufs, args.target_tp, aform, sr, dur
        )
        print("Second pass on SOURCE using wrong measured_*:", json.dumps(x_sim, indent=2) if x_sim else "{}")

    if compare:
        _print_file_block("COMPARE — first pass (loudnorm)", compare)
        l2 = first_pass_loudnorm(compare, dur)
        print(json.dumps(l2, indent=2) if l2 else "{}")
        vol2 = volumedetect(compare, dur)
        if vol2:
            print("  volumedetect:", vol2)

    # --- summary ---
    print()
    print("=" * 72)
    print("NOTES (read this)")
    print()
    if compare and l1 and l2:
        i1, i2 = _float_or(l1, "input_i"), _float_or(l2, "input_i")
        tp1, tp2 = _float_or(l1, "input_tp"), _float_or(l2, "input_tp")
        print(f"  Source integrated:    {i1:+.2f} LUFS, true peak: {tp1:+.2f} dBTP (first pass)")
        print(f"  Compare integrated:   {i2:+.2f} LUFS, true peak: {tp2:+.2f} dBTP (first pass)")
        if sim:
            oi = _float_or(sim, "output_i")
            otp = _float_or(sim, "output_tp")
            print(
                f"  Simulated 2nd pass (fresh measured_* on source):  output ~{oi:+.2f} LUFS, "
                f"true peak ~{otp:+.2f} dBTP"
            )
        if tp2 > 0.0:
            print()
            print(
                "  [!] Compare file’s true peak is ABOVE 0 dBTP — inter-sample overs / clipping risk."
            )
        elif tp2 > args.target_tp + 0.1:
            print()
            print(
                f"  [!] Compare file is hotter than target TP {args.target_tp:+.1f} dBTP; "
                "it may not be a clean loudnorm of this source with those targets."
            )
        if sim and l2:
            oi = _float_or(sim, "output_i")
            otp = _float_or(sim, "output_tp")
            ci2 = _float_or(l2, "input_i")
            ctp2 = _float_or(l2, "input_tp")
            if abs(ci2 - oi) < 1.5 and ctp2 > otp + 0.3:
                print()
                print(
                    "  [!!] Integrated loudness of the compare file is close to what a *correct* "
                    f"2nd pass reports (sim ~{oi:+.2f} LUFS vs compare {ci2:+.2f} LUFS), but true "
                    f"peak is not (sim ~{otp:+.2f} dBTP vs compare {ctp2:+.2f} dBTP). A proper "
                    "loudnorm pass should sit near the TP target; this pattern usually means the "
                    "compare file is not a straight, correct 2nd pass of this source — e.g. stale "
                    "or mismatched `loudnorm_params` in the app, a different file analysed first, "
                    "or another processor (Platinum Notes, DAW) after/before the encode."
                )
    print()
    print(
        "  • DJ MetaManager re-uses the first pass JSON from the **Analyse** step for the second pass. "
        "If that JSON was for another file, a tab from an old session, or a truncated analysis, the "
        "second pass can over- or under-shoot."
    )
    print(
        "  • In this app, filenames ending in `_PN` are often used for **Platinum Notes** or for a "
        "custom normalise suffix in Settings; confirm which tool produced the compare file."
    )
    if dur:
        print(
            f"  • You used -t {dur:g}s: for release decisions, re-run without --duration for full-track EBU."
        )
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
