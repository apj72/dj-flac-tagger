"""Parse rekordbox-style .cue sheets and embed mix metadata into the mix audio file.

A rekordbox recording produces a mix audio file (e.g. a .wav) plus a sibling .cue
sheet describing the mix and each track:

    REM DATE 2026-08-23 10:03 AM
    REM RECORDED_BY "rekordbox-dj"
    TITLE "REC-2026-08-23"
    PERFORMER "DJ Tony T"
    FILE "01 REC-2026-08-23.wav" WAVE
        TRACK 01 AUDIO
            TITLE "Cali Soul (Qubiko Remix)"
            PERFORMER "Crazibiza"
            FILE "/path/to/source.flac" WAVE
            INDEX 01 00:00:00

Track INDEX times are MM:SS:FF where FF is CDDA frames (75 per second), measured
from the start of the mix. This module turns that into:

  * ID3 chapter markers (CHAP + a CTOC table of contents) at each track boundary
  * a timestamped tracklist in the Comment tag
  * mix Title / Artist / Album / Date tags

Chapters need an ID3 container, which WAV, MP3 and AIFF provide. For FLAC/M4A the
tags and comment are still written but chapters are skipped (reported back).
"""

from __future__ import annotations

import re

# Audio containers a recorded mix might use. WAV is the rekordbox default.
MIX_AUDIO_EXTS = (".wav", ".aiff", ".aif", ".flac", ".mp3", ".m4a")

# CDDA frames per second used by .cue INDEX times.
_FRAMES_PER_SECOND = 75


def _tokenize(line: str) -> list[str]:
    """Split a cue line into tokens, treating a double-quoted run as one token."""
    tokens: list[str] = []
    s = line.strip()
    i = 0
    n = len(s)
    while i < n:
        ch = s[i]
        if ch == '"':
            j = s.find('"', i + 1)
            if j == -1:
                tokens.append(s[i + 1:])
                break
            tokens.append(s[i + 1:j])
            i = j + 1
        elif ch.isspace():
            i += 1
        else:
            j = i
            while j < n and not s[j].isspace():
                j += 1
            tokens.append(s[i:j])
            i = j
    return tokens


def _split_index(value: str):
    """Split an INDEX time "A:B:C" into a tuple of three ints, or None."""
    parts = value.split(":")
    if len(parts) != 3:
        return None
    try:
        return (int(parts[0]), int(parts[1]), int(parts[2]))
    except ValueError:
        return None


def _as_msf(fields) -> float:
    """Interpret (A, B, C) as MM:SS:FF (CUE standard; frames = 1/75s)."""
    return fields[0] * 60 + fields[1] + fields[2] / _FRAMES_PER_SECOND


def _as_hms(fields) -> float:
    """Interpret (A, B, C) as HH:MM:SS (what rekordbox writes for long mixes)."""
    return fields[0] * 3600 + fields[1] * 60 + fields[2]


def _choose_time_mode(fields_list: list, audio_length: float | None) -> str:
    """Pick "msf" (MM:SS:FF) or "hms" (HH:MM:SS) for the INDEX times.

    The two are structurally ambiguous (every field is <= 59 here), so we resolve
    by fitting against the real audio length: the correct reading spans close to
    the whole file. rekordbox writes HH:MM:SS for a long mix, which under the CUE
    standard MM:SS:FF reading would collapse all tracks into the first minute.
    Falls back to the standard MM:SS:FF when the audio length is unknown.
    """
    if not fields_list:
        return "msf"
    if not audio_length or audio_length <= 0:
        return "msf"
    msf_max = max(_as_msf(f) for f in fields_list)
    hms_max = max(_as_hms(f) for f in fields_list)
    tol = audio_length * 1.05
    # _as_hms >= _as_msf always, so prefer HH:MM:SS whenever it still fits.
    if hms_max <= tol:
        return "hms"
    if msf_max <= tol:
        return "msf"
    return "msf" if msf_max <= hms_max else "hms"


def parse_cue(text: str, audio_length: float | None = None) -> dict:
    """Parse cue-sheet text into {"mix": {...}, "tracks": [...], "time_mode": ...}.

    Mix keys: title, performer, date, recorded_by, file.
    Track keys: number, title, performer, file, start_seconds, start_str.
    ``audio_length`` (seconds), when known, disambiguates the INDEX time format.
    """
    mix = {"title": "", "performer": "", "date": "", "recorded_by": "", "file": ""}
    tracks: list[dict] = []
    cur: dict | None = None
    in_track = False

    for raw in text.splitlines():
        toks = _tokenize(raw)
        if not toks:
            continue
        kw = toks[0].upper()

        if kw == "REM":
            if len(toks) >= 2 and toks[1].upper() == "DATE":
                mix["date"] = " ".join(toks[2:]).strip()
            elif len(toks) >= 2 and toks[1].upper() in ("RECORDED_BY", "RECORDEDBY"):
                mix["recorded_by"] = " ".join(toks[2:]).strip()
            continue

        if kw == "TRACK":
            in_track = True
            number = int(toks[1]) if len(toks) > 1 and toks[1].isdigit() else len(tracks) + 1
            cur = {
                "number": number,
                "title": "",
                "performer": "",
                "file": "",
                "start_seconds": 0.0,
                "start_str": "",
                "_idx": None,
            }
            tracks.append(cur)
            continue

        if kw == "TITLE":
            val = toks[1] if len(toks) > 1 else ""
            if in_track and cur is not None:
                cur["title"] = val
            else:
                mix["title"] = val
            continue

        if kw == "PERFORMER":
            val = toks[1] if len(toks) > 1 else ""
            if in_track and cur is not None:
                cur["performer"] = val
            else:
                mix["performer"] = val
            continue

        if kw == "FILE":
            val = toks[1] if len(toks) > 1 else ""
            if in_track and cur is not None:
                cur["file"] = val
            else:
                mix["file"] = val
            continue

        if kw == "INDEX" and in_track and cur is not None and len(toks) >= 3:
            # Use INDEX 01 (the audible start); ignore INDEX 00 pre-gaps.
            if toks[1] in ("01", "1"):
                fields = _split_index(toks[2])
                if fields is not None:
                    cur["_idx"] = fields
                    cur["start_str"] = toks[2]
            continue

    # Resolve INDEX times now that all tracks are known.
    fields_list = [t["_idx"] for t in tracks if t.get("_idx") is not None]
    mode = _choose_time_mode(fields_list, audio_length)
    for t in tracks:
        fields = t.pop("_idx", None)
        if fields is None:
            continue
        t["start_seconds"] = _as_hms(fields) if mode == "hms" else _as_msf(fields)

    return {"mix": mix, "tracks": tracks, "time_mode": mode}


def format_hms(seconds: float) -> str:
    """Format seconds as H:MM:SS (hours only when needed), else M:SS."""
    total = int(round(seconds or 0))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def build_tracklist_text(tracks: list[dict]) -> str:
    """A timestamped tracklist suitable for a Comment tag / video description."""
    lines: list[str] = []
    for t in tracks:
        ts = format_hms(float(t.get("start_seconds") or 0))
        who = (t.get("performer") or "").strip()
        title = (t.get("title") or "").strip()
        name = f"{who} - {title}" if who else title
        lines.append(f"{ts}  {name}".rstrip())
    return "\n".join(lines)


def _date_for_id3(value: str) -> str:
    """Extract an ID3-friendly timestamp (YYYY-MM-DD or YYYY) from a REM DATE string."""
    if not value:
        return ""
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", value)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.search(r"\b(\d{4})\b", value)
    return m.group(1) if m else ""


def read_audio_summary(audio_path: str) -> dict:
    """Length (seconds) and a summary of any existing tags/chapters on the file."""
    import mutagen

    summary = {
        "length_seconds": 0.0,
        "format": "",
        "has_chapters": False,
        "chapter_count": 0,
        "title": "",
        "artist": "",
        "album": "",
        "comment": "",
        "has_tags": False,
    }
    f = mutagen.File(audio_path)
    if f is None:
        return summary
    summary["format"] = type(f).__name__
    info = getattr(f, "info", None)
    summary["length_seconds"] = float(getattr(info, "length", 0.0) or 0.0)

    tags = f.tags
    if tags is None:
        return summary
    summary["has_tags"] = True

    try:
        from mutagen.id3 import ID3
        is_id3 = isinstance(tags, ID3)
    except Exception:
        is_id3 = False

    if is_id3:
        chaps = [k for k in tags.keys() if k.startswith("CHAP")]
        summary["has_chapters"] = bool(chaps)
        summary["chapter_count"] = len(chaps)
        if tags.get("TIT2"):
            summary["title"] = str(tags.get("TIT2"))
        if tags.get("TPE1"):
            summary["artist"] = str(tags.get("TPE1"))
        if tags.get("TALB"):
            summary["album"] = str(tags.get("TALB"))
        comms = tags.getall("COMM")
        if comms:
            summary["comment"] = str(comms[0])
    else:
        def first(key):
            try:
                v = tags.get(key)
                if isinstance(v, list):
                    return str(v[0]) if v else ""
                return str(v) if v is not None else ""
            except Exception:
                return ""
        summary["title"] = first("title") or first("\xa9nam")
        summary["artist"] = first("artist") or first("\xa9ART")
        summary["album"] = first("album") or first("\xa9alb")
        summary["comment"] = first("comment") or first("\xa9cmt")

    return summary


def embed_mix_metadata(
    audio_path: str,
    mix: dict,
    tracks: list[dict],
    *,
    write_chapters: bool = True,
    write_comment: bool = True,
    write_tags: bool = True,
    total_seconds: float | None = None,
) -> dict:
    """Write chapters, a tracklist comment, and mix tags into ``audio_path``.

    Returns a summary describing what was written. Raises ValueError on failure.
    """
    import mutagen

    mix = mix or {}
    tracks = tracks or []

    f = mutagen.File(audio_path)
    if f is None:
        raise ValueError(f"Unrecognised audio file: {audio_path}")

    if total_seconds is None:
        info = getattr(f, "info", None)
        total_seconds = float(getattr(info, "length", 0.0) or 0.0)

    if f.tags is None:
        try:
            f.add_tags()
        except Exception:
            pass
    tags = f.tags

    try:
        from mutagen.id3 import ID3
        is_id3 = isinstance(tags, ID3)
    except Exception:
        is_id3 = False

    tracklist_text = build_tracklist_text(tracks)
    chapters_written = 0
    chapters_supported = is_id3

    if is_id3:
        from mutagen.id3 import (
            CHAP,
            CTOC,
            CTOCFlags,
            TIT2,
            TPE1,
            TALB,
            TDRC,
            COMM,
        )

        if write_tags:
            title = (mix.get("title") or "").strip()
            performer = (mix.get("performer") or "").strip()
            album = (mix.get("album") or mix.get("title") or "").strip()
            date = _date_for_id3(mix.get("date") or "")
            if title:
                tags.setall("TIT2", [TIT2(encoding=3, text=[title])])
            if performer:
                tags.setall("TPE1", [TPE1(encoding=3, text=[performer])])
            if album:
                tags.setall("TALB", [TALB(encoding=3, text=[album])])
            if date:
                tags.setall("TDRC", [TDRC(encoding=3, text=[date])])

        if write_comment:
            tags.delall("COMM")
            tags.add(COMM(encoding=3, lang="eng", desc="", text=[tracklist_text]))

        if write_chapters:
            tags.delall("CHAP")
            tags.delall("CTOC")
            child_ids: list[str] = []
            count = len(tracks)
            for i, t in enumerate(tracks):
                start_ms = int(round(float(t.get("start_seconds") or 0) * 1000))
                if i + 1 < count:
                    end_ms = int(round(float(tracks[i + 1].get("start_seconds") or 0) * 1000))
                else:
                    end_ms = int(round((total_seconds or float(t.get("start_seconds") or 0)) * 1000))
                if end_ms <= start_ms:
                    end_ms = start_ms + 1000
                eid = f"chp{i}"
                child_ids.append(eid)
                who = (t.get("performer") or "").strip()
                title = (t.get("title") or "").strip()
                label = f"{who} - {title}" if who else title
                tags.add(
                    CHAP(
                        element_id=eid,
                        start_time=start_ms,
                        end_time=end_ms,
                        start_offset=0xFFFFFFFF,
                        end_offset=0xFFFFFFFF,
                        sub_frames=[TIT2(encoding=3, text=[label or eid])],
                    )
                )
            if child_ids:
                tags.add(
                    CTOC(
                        element_id="toc",
                        flags=CTOCFlags.TOP_LEVEL | CTOCFlags.ORDERED,
                        child_element_ids=child_ids,
                        sub_frames=[TIT2(encoding=3, text=["Tracklist"])],
                    )
                )
                chapters_written = len(child_ids)
    else:
        # Vorbis (FLAC) / MP4 (M4A): write tags + comment, no chapter support.
        is_mp4 = type(f).__name__ == "MP4"
        if write_tags:
            title = (mix.get("title") or "").strip()
            performer = (mix.get("performer") or "").strip()
            album = (mix.get("album") or mix.get("title") or "").strip()
            date = _date_for_id3(mix.get("date") or "")
            if is_mp4:
                if title:
                    f["\xa9nam"] = [title]
                if performer:
                    f["\xa9ART"] = [performer]
                if album:
                    f["\xa9alb"] = [album]
                if date:
                    f["\xa9day"] = [date]
            else:
                if title:
                    f["title"] = [title]
                if performer:
                    f["artist"] = [performer]
                if album:
                    f["album"] = [album]
                if date:
                    f["date"] = [date]
        if write_comment:
            if is_mp4:
                f["\xa9cmt"] = [tracklist_text]
            else:
                f["comment"] = [tracklist_text]

    f.save()

    return {
        "chapters_written": chapters_written,
        "chapters_supported": chapters_supported,
        "comment_written": bool(write_comment),
        "tags_written": bool(write_tags),
        "tracklist": tracklist_text,
        "format": type(f).__name__,
        "track_count": len(tracks),
    }
