"""Tests for fix-artwork endpoint across FLAC, MP3, M4A, and AIFF formats."""

import struct

import pytest
from mutagen.flac import FLAC, Picture
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, APIC
from mutagen.mp4 import MP4, MP4Cover
from mutagen.aiff import AIFF


# Minimal 1x1 JPEG (enough for _image_dimensions to extract w/h)
TINY_JPEG = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t"
    b"\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a"
    b"\x1f\x1e\x1d\x1a\x1c\x1c $.\' \",#\x1c\x1c(7),01444\x1f\'9=82<.342"
    b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00"
    b"\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b"
    b"\xff\xda\x00\x08\x01\x01\x00\x00?\x00T\xdb\x9e\xa7(\xaf\xff\xd9"
)


def _make_silent_flac(path):
    """Create a minimal FLAC via ffmpeg-free mutagen approach: write empty FLAC."""
    import subprocess
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-y", "-f", "lavfi", "-i", "anullsrc=r=8000:cl=mono",
         "-t", "0.01", "-c:a", "flac", str(path)],
        capture_output=True, check=True,
    )
    return path


def _make_silent_mp3(path):
    import subprocess
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-y", "-f", "lavfi", "-i", "anullsrc=r=8000:cl=mono",
         "-t", "0.01", "-c:a", "libmp3lame", "-b:a", "128k", str(path)],
        capture_output=True, check=True,
    )
    return path


def _make_silent_m4a(path):
    import subprocess
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-y", "-f", "lavfi", "-i", "anullsrc=r=8000:cl=mono",
         "-t", "0.01", "-c:a", "aac", "-b:a", "128k", str(path)],
        capture_output=True, check=True,
    )
    return path


def _make_aiff(path):
    num_samples = 10
    num_channels = 1
    sample_size = 16
    data = b"\x00\x00" * num_samples * num_channels
    sample_rate_extended = b"\x40\x0D\xAC\x44\x00\x00\x00\x00\x00\x00"
    comm_data = struct.pack(">hIh", num_channels, num_samples, sample_size) + sample_rate_extended
    comm_chunk = b"COMM" + struct.pack(">I", len(comm_data)) + comm_data
    ssnd_payload = struct.pack(">II", 0, 0) + data
    ssnd_chunk = b"SSND" + struct.pack(">I", len(ssnd_payload)) + ssnd_payload
    form_data = b"AIFF" + comm_chunk + ssnd_chunk
    form = b"FORM" + struct.pack(">I", len(form_data)) + form_data
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(form)
    return path


class TestFixArtworkFlac:
    def test_fix_flac_bad_dimensions(self, client, app_module, tmp_path):
        f = _make_silent_flac(tmp_path / "test.flac")
        audio = FLAC(str(f))
        pic = Picture()
        pic.type = 3
        pic.mime = "image/jpeg"
        pic.data = TINY_JPEG
        pic.width = 0
        pic.height = 0
        audio.clear_pictures()
        audio.add_picture(pic)
        audio.save()

        r = client.post("/api/fix-artwork", json={"filepath": str(f)})
        assert r.status_code == 200
        j = r.get_json()
        assert j["status"] == "ok"
        assert j["width"] == 1
        assert j["height"] == 1

    def test_fix_flac_already_correct(self, client, app_module, tmp_path):
        f = _make_silent_flac(tmp_path / "ok.flac")
        audio = FLAC(str(f))
        pic = Picture()
        pic.type = 3
        pic.mime = "image/jpeg"
        pic.data = TINY_JPEG
        pic.width = 1
        pic.height = 1
        audio.clear_pictures()
        audio.add_picture(pic)
        audio.save()

        r = client.post("/api/fix-artwork", json={"filepath": str(f)})
        assert r.status_code == 200
        assert "already correct" in r.get_json()["message"].lower()

    def test_fix_flac_no_artwork(self, client, app_module, tmp_path):
        f = _make_silent_flac(tmp_path / "noart.flac")
        r = client.post("/api/fix-artwork", json={"filepath": str(f)})
        assert r.status_code == 400


class TestFixArtworkMp3:
    def test_fix_mp3_reembed(self, client, app_module, tmp_path):
        f = _make_silent_mp3(tmp_path / "test.mp3")
        audio = MP3(str(f), ID3=ID3)
        try:
            audio.add_tags()
        except Exception:
            pass
        audio.tags.delall("APIC")
        audio.tags.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=TINY_JPEG))
        audio.save(v2_version=3)

        r = client.post("/api/fix-artwork", json={"filepath": str(f)})
        assert r.status_code == 200
        j = r.get_json()
        assert j["status"] == "ok"
        assert j["width"] == 1

    def test_fix_mp3_no_artwork(self, client, app_module, tmp_path):
        f = _make_silent_mp3(tmp_path / "noart.mp3")
        audio = MP3(str(f), ID3=ID3)
        if audio.tags:
            audio.tags.delall("APIC")
            audio.save(v2_version=3)
        r = client.post("/api/fix-artwork", json={"filepath": str(f)})
        assert r.status_code == 400


class TestFixArtworkM4a:
    def test_fix_m4a_reembed(self, client, app_module, tmp_path):
        f = _make_silent_m4a(tmp_path / "test.m4a")
        audio = MP4(str(f))
        if audio.tags is None:
            audio.add_tags()
        audio.tags["covr"] = [MP4Cover(TINY_JPEG, imageformat=MP4Cover.FORMAT_JPEG)]
        audio.save()

        r = client.post("/api/fix-artwork", json={"filepath": str(f)})
        assert r.status_code == 200
        j = r.get_json()
        assert j["status"] == "ok"
        assert j["width"] == 1

    def test_fix_m4a_no_artwork(self, client, app_module, tmp_path):
        f = _make_silent_m4a(tmp_path / "noart.m4a")
        r = client.post("/api/fix-artwork", json={"filepath": str(f)})
        assert r.status_code == 400


class TestFixArtworkAiff:
    def test_fix_aiff_reembed(self, client, app_module, tmp_path):
        f = _make_aiff(tmp_path / "test.aiff")
        audio = AIFF(str(f))
        try:
            audio.add_tags()
        except Exception:
            pass
        audio.tags.delall("APIC")
        audio.tags.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=TINY_JPEG))
        audio.save()

        r = client.post("/api/fix-artwork", json={"filepath": str(f)})
        assert r.status_code == 200
        j = r.get_json()
        assert j["status"] == "ok"
        assert j["width"] == 1

    def test_fix_aiff_no_artwork(self, client, app_module, tmp_path):
        f = _make_aiff(tmp_path / "noart.aiff")
        r = client.post("/api/fix-artwork", json={"filepath": str(f)})
        assert r.status_code == 400


class TestFixArtworkEdgeCases:
    def test_file_not_found(self, client, app_module):
        r = client.post("/api/fix-artwork", json={"filepath": "/nonexistent/file.flac"})
        assert r.status_code == 404

    def test_unsupported_format(self, client, app_module, tmp_path):
        f = tmp_path / "test.ogg"
        f.write_bytes(b"dummy")
        r = client.post("/api/fix-artwork", json={"filepath": str(f)})
        assert r.status_code == 400
        assert "not supported" in r.get_json()["error"].lower()
