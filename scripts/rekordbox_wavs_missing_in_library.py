#!/usr/bin/env python3
"""
List .wav files under a tree (e.g. Ableton-oriented exports also used with Rekordbox) that
have no clearly matching .flac in a flat processed library, using the same filename rules
as app.parse_ableton_style_wav_stem and a normalized stem comparison fallback.

  python3 scripts/rekordbox_wavs_missing_in_library.py
  python3 scripts/rekordbox_wavs_missing_in_library.py --source ~/path/to/wavs --dest ~/path/to/flacs
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import (  # noqa: E402
    _basename_from_artist_title_for_rename,
    parse_ableton_style_wav_stem,
)

_RE_CAMELOT_BPM = re.compile(r"\s+\d{1,2}[ABaAbB]\s+\d{2,3}\s*$", re.IGNORECASE)


def norm_stem(s: str) -> str:
    s = s.lower()
    s = re.sub(r"\s*-\s*\d{1,2}[ABa-b]\s*-\s*\d{2,3}\s*$", "", s, flags=re.IGNORECASE)
    s = _RE_CAMELOT_BPM.sub("", s)
    s = s.replace(" - ", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def index_library(dest_dir: Path) -> tuple[set[str], set[str]]:
    """Lower basenames, and norm_stem of each .flac stem (for loose matching)."""
    basenames: set[str] = set()
    norms: set[str] = set()
    for p in dest_dir.iterdir():
        if not p.is_file() or p.suffix.lower() != ".flac":
            continue
        basenames.add(p.name.lower())
        norms.add(norm_stem(p.stem))
    return basenames, norms


def has_match(stem: str, basenames: set[str], norms: set[str]) -> bool:
    p = parse_ableton_style_wav_stem(stem)
    if p.get("matched") and p.get("artist") and p.get("title"):
        b = _basename_from_artist_title_for_rename(
            p["artist"], p["title"], ".flac"
        )
        if b and b.lower() in basenames:
            return True
        n = norm_stem(f"{p['artist']} - {p['title']}")
        if n in norms:
            return True
    loose = (p.get("loose") or p.get("title") or "").strip()
    if loose and norm_stem(loose) in norms:
        return True
    return norm_stem(stem) in norms


def main() -> None:
    ap = argparse.ArgumentParser(
        description="List WAVs under --source with no matching FLAC in --dest"
    )
    ap.add_argument(
        "--source",
        type=Path,
        default=Path.home() / "Documents" / "Rekordbox-music" / "Underground",
        help="Root folder to scan for .wav (recursive)",
    )
    ap.add_argument(
        "--dest",
        type=Path,
        default=Path.home() / "Music" / "FLACs" / "Underground",
        help="Folder of processed .flac (non-recursive; flat library)",
    )
    ap.add_argument(
        "--count-only",
        action="store_true",
        help="Print only counts",
    )
    args = ap.parse_args()

    src = args.source.expanduser().resolve()
    dst = args.dest.expanduser().resolve()
    if not src.is_dir():
        raise SystemExit(f"Source not found: {src}")
    if not dst.is_dir():
        raise SystemExit(f"Dest not found: {dst}")

    basenames, norms = index_library(dst)
    wavs = sorted(p for p in src.rglob("*.wav") if p.is_file() and p.name != ".DS_Store")

    missing: list[Path] = []
    for w in wavs:
        if not has_match(w.stem, basenames, norms):
            missing.append(w)

    if args.count_only:
        print(
            f"WAVs under source: {len(wavs)}\n"
            f"FLACs in dest:     {len(basenames)}\n"
            f"Unmatched WAVs:    {len(missing)}"
        )
        return

    print(f"Source: {src}  ({len(wavs)} .wav files)")
    print(f"Dest:   {dst}  ({len(basenames)} .flac files)")
    print(f"Not matched to any dest FLAC: {len(missing)}\n")
    for w in missing:
        print(w)


if __name__ == "__main__":
    main()
