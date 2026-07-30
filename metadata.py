"""Mutagen tag read/write and artwork operations."""

__all__ = [
    '_source_url_from_vorbis', '_image_dimensions',
    '_ARTWORK_UPLOAD_MIMES', '_RETAG_ARTWORK_MAX_BYTES', '_mime_from_image_magic',
    '_decode_retag_artwork_base64', 'apply_metadata', '_apply_flac',
    '_apply_mp3', '_apply_mp4', '_apply_vorbis', '_apply_generic', '_apply_aiff',
    '_read_flac_tags', '_read_mp3_tags', '_read_mp4_tags', '_read_vorbis_tags',
    '_read_generic_tags', '_read_aiff_tags', 'read_embedded_artwork',
    '_metadata_dict_for_copy', '_copy_audio_tags_and_art',
    '_fix_artwork_flac', '_fix_artwork_id3', '_fix_artwork_mp4',
]

import base64
import binascii
import os
import struct
from pathlib import Path

import mutagen
from mutagen.flac import FLAC, Picture
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4, MP4Cover
from mutagen.id3 import ID3, APIC, TIT2, TPE1, TPE2, TALB, TDRC, TCON, COMM, TPUB, TRCK, TXXX
from mutagen.aiff import AIFF
from mutagen.oggvorbis import OggVorbis

from config import (
    SOURCE_URL_VORBIS,
    SOURCE_URL_VORBIS_LEGACY,
    SOURCE_URL_ID3_DESC,
    SOURCE_URL_ID3_DESC_LEGACY,
)


# ---------------------------------------------------------------------------
# Source URL helpers
# ---------------------------------------------------------------------------

def _source_url_from_vorbis(audio):
    for key in (SOURCE_URL_VORBIS, SOURCE_URL_VORBIS_LEGACY):
        vals = audio.get(key, [])
        if vals:
            return vals[0]
    return None


# ---------------------------------------------------------------------------
# Image dimension reading
# ---------------------------------------------------------------------------

def _image_dimensions(data):
    """Read width/height from JPEG or PNG binary data."""
    if data[:8] == b'\x89PNG\r\n\x1a\n' and len(data) >= 24:
        w, h = struct.unpack('>II', data[16:24])
        return w, h
    if data[:2] == b'\xff\xd8':
        i = 2
        while i < len(data) - 1:
            if data[i] != 0xff:
                break
            marker = data[i + 1]
            if marker in (0xc0, 0xc1, 0xc2):
                if i + 9 < len(data):
                    h, w = struct.unpack('>HH', data[i + 5:i + 9])
                    return w, h
                break
            if marker in (0xd0, 0xd1, 0xd2, 0xd3, 0xd4, 0xd5, 0xd6, 0xd7, 0xd8, 0xd9, 0x01):
                i += 2
                continue
            if i + 3 < len(data):
                seg_len = struct.unpack('>H', data[i + 2:i + 4])[0]
                i += 2 + seg_len
            else:
                break
    return 0, 0


# ---------------------------------------------------------------------------
# Artwork validation / decode
# ---------------------------------------------------------------------------

_ARTWORK_UPLOAD_MIMES = frozenset({"image/jpeg", "image/png", "image/webp", "image/gif"})
_RETAG_ARTWORK_MAX_BYTES = 10 * 1024 * 1024


def _mime_from_image_magic(head: bytes) -> str | None:
    """Best-effort image type from magic bytes (first ~32 bytes)."""
    if not head or len(head) < 3:
        return None
    if head[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return None


def _decode_retag_artwork_base64(raw: str, _mime_hint: str = "") -> tuple[bytes | None, str | None]:
    """
    Decode a base64 image from Fix Metadata (whole file or data-URL). Returns (bytes, mime) or
    (None, None) if invalid, wrong type, or too large.
    """
    s = (raw or "").strip()
    if not s:
        return None, None
    if s.startswith("data:") and "base64," in s:
        try:
            s = s.split("base64,", 1)[1].strip()
        except IndexError:
            return None, None
    try:
        data = base64.b64decode(s, validate=False)
    except (binascii.Error, ValueError):
        try:
            data = base64.urlsafe_b64decode(s + "===")
        except (binascii.Error, ValueError):
            return None, None
    except Exception:
        return None, None
    if not data or len(data) > _RETAG_ARTWORK_MAX_BYTES:
        return None, None
    magic = _mime_from_image_magic(data[:32])
    if magic is None:
        return None, None
    return data, magic


# ---------------------------------------------------------------------------
# Apply metadata (write tags)
# ---------------------------------------------------------------------------

def apply_metadata(filepath, metadata, artwork_bytes=None, artwork_mime=None):
    ext = os.path.splitext(filepath)[1].lower()

    if ext == ".flac":
        _apply_flac(filepath, metadata, artwork_bytes, artwork_mime)
    elif ext == ".mp3":
        _apply_mp3(filepath, metadata, artwork_bytes, artwork_mime)
    elif ext in (".m4a", ".mp4", ".aac"):
        _apply_mp4(filepath, metadata, artwork_bytes, artwork_mime)
    elif ext in (".aiff", ".aif"):
        _apply_aiff(filepath, metadata, artwork_bytes, artwork_mime)
    elif ext in (".ogg", ".oga"):
        _apply_vorbis(filepath, metadata, artwork_bytes, artwork_mime)
    else:
        _apply_generic(filepath, metadata, artwork_bytes, artwork_mime)


def _apply_flac(filepath, metadata, artwork_bytes, artwork_mime):
    audio = FLAC(filepath)
    vorbis_map = {
        "title": "title", "artist": "artist", "albumartist": "albumartist",
        "album": "album", "date": "date", "genre": "genre", "comment": "comment",
        "tracknumber": "tracknumber", "label": "organization", "catno": "catalognumber",
    }
    for key, vorbis_key in vorbis_map.items():
        val = metadata.get(key)
        if val:
            audio[vorbis_key] = [val]
    su = (metadata.get("source_url") or "").strip()
    if su:
        audio[SOURCE_URL_VORBIS] = [su]
        if SOURCE_URL_VORBIS_LEGACY in audio:
            del audio[SOURCE_URL_VORBIS_LEGACY]
    if artwork_bytes:
        pic = Picture()
        pic.type = 3
        pic.mime = artwork_mime or "image/jpeg"
        pic.desc = "Cover"
        pic.data = artwork_bytes
        pic.width, pic.height = _image_dimensions(artwork_bytes)
        audio.clear_pictures()
        audio.add_picture(pic)
    audio.save()


def _apply_mp3(filepath, metadata, artwork_bytes, artwork_mime):
    audio = MP3(filepath, ID3=ID3)
    try:
        audio.add_tags()
    except mutagen.id3.error:
        pass
    t = audio.tags
    id3_map = {
        "title": TIT2, "artist": TPE1, "albumartist": TPE2,
        "album": TALB, "genre": TCON,
    }
    for key, frame_cls in id3_map.items():
        val = metadata.get(key)
        if val:
            t.delall(frame_cls.__name__)
            t.add(frame_cls(encoding=3, text=[val]))
    if metadata.get("date"):
        t.delall("TDRC")
        t.add(TDRC(encoding=3, text=[metadata["date"]]))
    if metadata.get("tracknumber"):
        t.delall("TRCK")
        t.add(TRCK(encoding=3, text=[metadata["tracknumber"]]))
    if metadata.get("comment"):
        t.delall("COMM")
        t.add(COMM(encoding=3, lang="eng", desc="", text=[metadata["comment"]]))
    if metadata.get("label"):
        t.delall("TPUB")
        t.add(TPUB(encoding=3, text=[metadata["label"]]))
    if metadata.get("catno"):
        t.delall("TXXX:CATALOGNUMBER")
        t.add(TXXX(encoding=3, desc="CATALOGNUMBER", text=[metadata["catno"]]))
    su = (metadata.get("source_url") or "").strip()
    if su:
        t.delall(f"TXXX:{SOURCE_URL_ID3_DESC}")
        t.delall(f"TXXX:{SOURCE_URL_ID3_DESC_LEGACY}")
        t.add(TXXX(encoding=3, desc=SOURCE_URL_ID3_DESC, text=[su]))
    if artwork_bytes:
        t.delall("APIC")
        t.add(APIC(encoding=3, mime=artwork_mime or "image/jpeg", type=3, desc="Cover", data=artwork_bytes))
    audio.save(v2_version=3)


def _apply_aiff(filepath, metadata, artwork_bytes, artwork_mime):
    audio = AIFF(filepath)
    try:
        audio.add_tags()
    except mutagen.id3.error:
        pass
    t = audio.tags
    id3_map = {
        "title": TIT2, "artist": TPE1, "albumartist": TPE2,
        "album": TALB, "genre": TCON,
    }
    for key, frame_cls in id3_map.items():
        val = metadata.get(key)
        if val:
            t.delall(frame_cls.__name__)
            t.add(frame_cls(encoding=3, text=[val]))
    if metadata.get("date"):
        t.delall("TDRC")
        t.add(TDRC(encoding=3, text=[metadata["date"]]))
    if metadata.get("tracknumber"):
        t.delall("TRCK")
        t.add(TRCK(encoding=3, text=[metadata["tracknumber"]]))
    if metadata.get("comment"):
        t.delall("COMM")
        t.add(COMM(encoding=3, lang="eng", desc="", text=[metadata["comment"]]))
    if metadata.get("label"):
        t.delall("TPUB")
        t.add(TPUB(encoding=3, text=[metadata["label"]]))
    if metadata.get("catno"):
        t.delall("TXXX:CATALOGNUMBER")
        t.add(TXXX(encoding=3, desc="CATALOGNUMBER", text=[metadata["catno"]]))
    su = (metadata.get("source_url") or "").strip()
    if su:
        t.delall(f"TXXX:{SOURCE_URL_ID3_DESC}")
        t.delall(f"TXXX:{SOURCE_URL_ID3_DESC_LEGACY}")
        t.add(TXXX(encoding=3, desc=SOURCE_URL_ID3_DESC, text=[su]))
    if artwork_bytes:
        t.delall("APIC")
        t.add(APIC(encoding=3, mime=artwork_mime or "image/jpeg", type=3, desc="Cover", data=artwork_bytes))
    audio.save()


def _apply_mp4(filepath, metadata, artwork_bytes, artwork_mime):
    audio = MP4(filepath)
    if audio.tags is None:
        audio.add_tags()
    mp4_map = {
        "title": "\xa9nam", "artist": "\xa9ART", "albumartist": "aART",
        "album": "\xa9alb", "date": "\xa9day", "genre": "\xa9gen",
        "comment": "\xa9cmt",
    }
    for key, atom in mp4_map.items():
        val = metadata.get(key)
        if val:
            audio.tags[atom] = [val]
    if metadata.get("tracknumber"):
        try:
            tnum = int(metadata["tracknumber"])
            audio.tags["trkn"] = [(tnum, 0)]
        except ValueError:
            pass
    if artwork_bytes:
        fmt = MP4Cover.FORMAT_JPEG
        if artwork_mime and "png" in artwork_mime:
            fmt = MP4Cover.FORMAT_PNG
        audio.tags["covr"] = [MP4Cover(artwork_bytes, imageformat=fmt)]
    audio.save()


def _apply_vorbis(filepath, metadata, artwork_bytes, artwork_mime):
    audio = OggVorbis(filepath)
    vorbis_map = {
        "title": "title", "artist": "artist", "albumartist": "albumartist",
        "album": "album", "date": "date", "genre": "genre", "comment": "comment",
        "tracknumber": "tracknumber", "label": "organization", "catno": "catalognumber",
    }
    for key, vorbis_key in vorbis_map.items():
        val = metadata.get(key)
        if val:
            audio[vorbis_key] = [val]
    su = (metadata.get("source_url") or "").strip()
    if su:
        audio[SOURCE_URL_VORBIS] = [su]
        if SOURCE_URL_VORBIS_LEGACY in audio:
            del audio[SOURCE_URL_VORBIS_LEGACY]
    if artwork_bytes:
        pic = Picture()
        pic.type = 3
        pic.mime = artwork_mime or "image/jpeg"
        pic.desc = "Cover"
        pic.data = artwork_bytes
        pic.width, pic.height = _image_dimensions(artwork_bytes)
        audio["metadata_block_picture"] = [base64.b64encode(pic.write()).decode("ascii")]
    audio.save()


def _apply_generic(filepath, metadata, artwork_bytes, artwork_mime):
    """Fallback using mutagen.File for any other supported format."""
    audio = mutagen.File(filepath, easy=True)
    if audio is None:
        raise ValueError(f"Unsupported file format: {filepath}")
    if audio.tags is None:
        audio.add_tags()
    easy_map = {"title": "title", "artist": "artist", "albumartist": "albumartist",
                "album": "album", "date": "date", "genre": "genre"}
    for key, tag in easy_map.items():
        val = metadata.get(key)
        if val:
            try:
                audio[tag] = [val]
            except (KeyError, mutagen.MutagenError):
                pass
    audio.save()


# ---------------------------------------------------------------------------
# Read tags
# ---------------------------------------------------------------------------

def _read_flac_tags(filepath):
    audio = FLAC(filepath)
    vorbis_reverse = {
        "title": "title", "artist": "artist", "albumartist": "albumartist",
        "album": "album", "date": "date", "genre": "genre", "comment": "comment",
        "organization": "label", "catalognumber": "catno", "tracknumber": "tracknumber",
    }
    meta = {}
    for vorbis_key, field in vorbis_reverse.items():
        vals = audio.get(vorbis_key, [])
        if vals:
            meta[field] = vals[0]
    su = _source_url_from_vorbis(audio)
    if su:
        meta["source_url"] = su
    meta["has_artwork"] = len(audio.pictures) > 0
    meta["format"] = "FLAC"
    return meta


def _read_mp3_tags(filepath):
    audio = MP3(filepath, ID3=ID3)
    meta = {"format": "MP3"}
    if audio.tags is None:
        meta["has_artwork"] = False
        return meta
    t = audio.tags
    frame_map = {
        "TIT2": "title", "TPE1": "artist", "TPE2": "albumartist",
        "TALB": "album", "TDRC": "date", "TCON": "genre", "TPUB": "label",
        "TRCK": "tracknumber",
    }
    for frame_id, field in frame_map.items():
        frame = t.getall(frame_id)
        if frame:
            meta[field] = str(frame[0])
    comm = t.getall("COMM")
    if comm:
        meta["comment"] = str(comm[0])
    catno = t.getall("TXXX:CATALOGNUMBER")
    if catno:
        meta["catno"] = str(catno[0])
    su_new = su_legacy = None
    for frame in t.getall("TXXX"):
        desc = getattr(frame, "desc", "")
        if desc == SOURCE_URL_ID3_DESC and frame.text:
            su_new = str(frame.text[0])
        elif desc == SOURCE_URL_ID3_DESC_LEGACY and frame.text:
            su_legacy = str(frame.text[0])
    if su_new is not None:
        meta["source_url"] = su_new
    elif su_legacy is not None:
        meta["source_url"] = su_legacy
    meta["has_artwork"] = bool(t.getall("APIC"))
    return meta


def _read_aiff_tags(filepath):
    audio = AIFF(filepath)
    meta = {"format": "AIFF"}
    if audio.tags is None:
        meta["has_artwork"] = False
        return meta
    t = audio.tags
    frame_map = {
        "TIT2": "title", "TPE1": "artist", "TPE2": "albumartist",
        "TALB": "album", "TDRC": "date", "TCON": "genre", "TPUB": "label",
        "TRCK": "tracknumber",
    }
    for frame_id, field in frame_map.items():
        frame = t.getall(frame_id)
        if frame:
            meta[field] = str(frame[0])
    comm = t.getall("COMM")
    if comm:
        meta["comment"] = str(comm[0])
    catno = t.getall("TXXX:CATALOGNUMBER")
    if catno:
        meta["catno"] = str(catno[0])
    su_new = su_legacy = None
    for frame in t.getall("TXXX"):
        desc = getattr(frame, "desc", "")
        if desc == SOURCE_URL_ID3_DESC and frame.text:
            su_new = str(frame.text[0])
        elif desc == SOURCE_URL_ID3_DESC_LEGACY and frame.text:
            su_legacy = str(frame.text[0])
    if su_new is not None:
        meta["source_url"] = su_new
    elif su_legacy is not None:
        meta["source_url"] = su_legacy
    meta["has_artwork"] = bool(t.getall("APIC"))
    return meta


def _read_mp4_tags(filepath):
    audio = MP4(filepath)
    meta = {"format": "AAC/M4A"}
    if audio.tags is None:
        meta["has_artwork"] = False
        return meta
    mp4_reverse = {
        "\xa9nam": "title", "\xa9ART": "artist", "aART": "albumartist",
        "\xa9alb": "album", "\xa9day": "date", "\xa9gen": "genre",
        "\xa9cmt": "comment",
    }
    for atom, field in mp4_reverse.items():
        vals = audio.tags.get(atom)
        if vals:
            meta[field] = str(vals[0])
    trkn = audio.tags.get("trkn")
    if trkn:
        meta["tracknumber"] = str(trkn[0][0])
    meta["has_artwork"] = bool(audio.tags.get("covr"))
    return meta


def _read_vorbis_tags(filepath):
    audio = OggVorbis(filepath)
    vorbis_reverse = {
        "title": "title", "artist": "artist", "albumartist": "albumartist",
        "album": "album", "date": "date", "genre": "genre", "comment": "comment",
        "organization": "label", "catalognumber": "catno", "tracknumber": "tracknumber",
    }
    meta = {"format": "OGG"}
    for vorbis_key, field in vorbis_reverse.items():
        vals = audio.get(vorbis_key, [])
        if vals:
            meta[field] = vals[0]
    su = _source_url_from_vorbis(audio)
    if su:
        meta["source_url"] = su
    meta["has_artwork"] = bool(audio.get("metadata_block_picture"))
    return meta


def _read_generic_tags(filepath):
    audio = mutagen.File(filepath, easy=True)
    if audio is None:
        return {"error": "Unsupported format", "has_artwork": False}
    meta = {"format": type(audio).__name__}
    easy_map = {"title": "title", "artist": "artist", "albumartist": "albumartist",
                "album": "album", "date": "date", "genre": "genre"}
    for tag, field in easy_map.items():
        vals = audio.get(tag, [])
        if vals:
            meta[field] = vals[0]
    meta["has_artwork"] = False
    return meta


# ---------------------------------------------------------------------------
# Embedded artwork reading
# ---------------------------------------------------------------------------

def read_embedded_artwork(filepath):
    """Return (bytes, mime) for first embedded cover, or (None, None)."""
    ext = Path(filepath).suffix.lower()
    try:
        if ext == ".flac":
            audio = FLAC(filepath)
            if audio.pictures:
                pic = audio.pictures[0]
                return pic.data, pic.mime or "image/jpeg"
        elif ext == ".mp3":
            audio = MP3(filepath, ID3=ID3)
            if audio.tags:
                apics = audio.tags.getall("APIC")
                if apics:
                    a = apics[0]
                    return a.data, a.mime or "image/jpeg"
        elif ext in (".m4a", ".mp4", ".aac"):
            audio = MP4(filepath)
            if audio.tags and audio.tags.get("covr"):
                covr = audio.tags["covr"][0]
                mime = "image/jpeg" if covr.imageformat == MP4Cover.FORMAT_JPEG else "image/png"
                return bytes(covr), mime
        elif ext in (".aiff", ".aif"):
            audio = AIFF(filepath)
            if audio.tags:
                apics = audio.tags.getall("APIC")
                if apics:
                    a = apics[0]
                    return a.data, a.mime or "image/jpeg"
        elif ext in (".ogg", ".oga"):
            audio = OggVorbis(filepath)
            pics = audio.get("metadata_block_picture")
            if pics:
                pic = Picture()
                pic.load(base64.b64decode(pics[0]))
                return pic.data, pic.mime or "image/jpeg"
    except Exception:
        pass
    return None, None


# ---------------------------------------------------------------------------
# Copy tags & artwork between files
# ---------------------------------------------------------------------------

def _metadata_dict_for_copy(src_path):
    """Fields suitable for apply_metadata after transcoding."""
    ext = Path(src_path).suffix.lower()
    if ext == ".flac":
        meta = _read_flac_tags(src_path)
    elif ext == ".mp3":
        meta = _read_mp3_tags(src_path)
    elif ext in (".m4a", ".mp4", ".aac"):
        meta = _read_mp4_tags(src_path)
    elif ext in (".aiff", ".aif"):
        meta = _read_aiff_tags(src_path)
    elif ext in (".ogg", ".oga"):
        meta = _read_vorbis_tags(src_path)
    else:
        meta = _read_generic_tags(src_path)
    skip = {"format", "has_artwork", "error", "artwork_info"}
    return {k: v for k, v in meta.items() if k not in skip and v}


def _copy_audio_tags_and_art(src_path, dst_path):
    """Re-apply tags and embedded artwork from src onto dst (any supported apply_metadata type)."""
    meta = _metadata_dict_for_copy(src_path)
    art_bytes, art_mime = read_embedded_artwork(src_path)
    apply_metadata(dst_path, meta, art_bytes, art_mime)


# ---------------------------------------------------------------------------
# Fix artwork helpers
# ---------------------------------------------------------------------------

def _fix_artwork_flac(filepath):
    audio = FLAC(filepath)
    if not audio.pictures:
        return None, "No embedded artwork found"
    pic = audio.pictures[0]
    w, h = _image_dimensions(pic.data)
    if w and h and pic.width == w and pic.height == h:
        return {"status": "ok", "message": "Artwork dimensions already correct", "width": w, "height": h}, None
    if w and h:
        pic.width = w
        pic.height = h
    audio.clear_pictures()
    audio.add_picture(pic)
    audio.save()
    return {"status": "ok", "width": w or 0, "height": h or 0}, None


def _fix_artwork_id3(filepath, audio):
    if audio.tags is None:
        return None, "No embedded artwork found"
    apics = audio.tags.getall("APIC")
    if not apics:
        return None, "No embedded artwork found"
    art = apics[0]
    w, h = _image_dimensions(art.data)
    audio.tags.delall("APIC")
    audio.tags.add(APIC(encoding=3, mime=art.mime or "image/jpeg", type=3, desc="Cover", data=art.data))
    audio.save()
    return {"status": "ok", "width": w or 0, "height": h or 0}, None


def _fix_artwork_mp4(filepath):
    audio = MP4(filepath)
    if audio.tags is None or not audio.tags.get("covr"):
        return None, "No embedded artwork found"
    covr = audio.tags["covr"][0]
    w, h = _image_dimensions(bytes(covr))
    audio.tags["covr"] = [MP4Cover(bytes(covr), imageformat=covr.imageformat)]
    audio.save()
    return {"status": "ok", "width": w or 0, "height": h or 0}, None
