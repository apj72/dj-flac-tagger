"""Tests for AIFF metadata read/write via dedicated _apply_aiff / _read_aiff_tags."""

import struct

import pytest
from mutagen.aiff import AIFF


def _make_aiff(path):
    """Create a minimal valid AIFF file (44100 Hz mono, 10 samples of silence)."""
    num_samples = 10
    num_channels = 1
    sample_size = 16
    data = b"\x00\x00" * num_samples * num_channels

    # 44100 Hz as 80-bit IEEE 754 extended: exponent 16397, mantissa 0xAC44000000000000
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


class TestApplyAiff:
    def test_basic_tags(self, app_module, tmp_path):
        f = _make_aiff(tmp_path / "test.aiff")
        app_module._apply_aiff(str(f), {
            "title": "Test Title",
            "artist": "Test Artist",
            "album": "Test Album",
            "date": "2024",
            "genre": "House",
            "tracknumber": "3",
            "comment": "Nice track",
            "label": "Test Label",
            "catno": "TL001",
        }, None, None)

        tags = app_module._read_aiff_tags(str(f))
        assert tags["title"] == "Test Title"
        assert tags["artist"] == "Test Artist"
        assert tags["album"] == "Test Album"
        assert tags["date"] == "2024"
        assert tags["genre"] == "House"
        assert tags["tracknumber"] == "3"
        assert tags["comment"] == "Nice track"
        assert tags["label"] == "Test Label"
        assert tags["catno"] == "TL001"
        assert tags["format"] == "AIFF"

    def test_artwork(self, app_module, tmp_path):
        f = _make_aiff(tmp_path / "art.aiff")
        # 1x1 red JPEG
        jpeg = (
            b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
            b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t"
            b"\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a"
            b"\x1f\x1e\x1d\x1a\x1c\x1c $.\' \",#\x1c\x1c(7),01444\x1f\'9=82<.342"
            b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00"
            b"\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00"
            b"\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b"
            b"\xff\xda\x00\x08\x01\x01\x00\x00?\x00T\xdb\x9e\xa7(\xaf\xff\xd9"
        )
        app_module._apply_aiff(str(f), {"title": "Art"}, jpeg, "image/jpeg")

        tags = app_module._read_aiff_tags(str(f))
        assert tags["has_artwork"] is True

    def test_source_url(self, app_module, tmp_path):
        f = _make_aiff(tmp_path / "url.aiff")
        app_module._apply_aiff(str(f), {
            "title": "URL Test",
            "source_url": "https://example.com/track",
        }, None, None)

        tags = app_module._read_aiff_tags(str(f))
        assert tags["source_url"] == "https://example.com/track"

    def test_no_tags(self, app_module, tmp_path):
        f = _make_aiff(tmp_path / "empty.aiff")
        tags = app_module._read_aiff_tags(str(f))
        assert tags["format"] == "AIFF"
        assert tags["has_artwork"] is False

    def test_aif_extension(self, app_module, tmp_path):
        f = _make_aiff(tmp_path / "test.aif")
        app_module.apply_metadata(str(f), {"title": "AIF Ext"})
        tags = app_module._read_aiff_tags(str(f))
        assert tags["title"] == "AIF Ext"

    def test_albumartist(self, app_module, tmp_path):
        f = _make_aiff(tmp_path / "aa.aiff")
        app_module._apply_aiff(str(f), {
            "title": "AA",
            "albumartist": "Various Artists",
        }, None, None)
        tags = app_module._read_aiff_tags(str(f))
        assert tags["albumartist"] == "Various Artists"


class TestApplyMetadataRouting:
    def test_routes_aiff(self, app_module, tmp_path):
        f = _make_aiff(tmp_path / "route.aiff")
        app_module.apply_metadata(str(f), {"title": "Routed"})
        tags = app_module._read_aiff_tags(str(f))
        assert tags["title"] == "Routed"

    def test_routes_aif(self, app_module, tmp_path):
        f = _make_aiff(tmp_path / "route.aif")
        app_module.apply_metadata(str(f), {"title": "Routed AIF"})
        tags = app_module._read_aiff_tags(str(f))
        assert tags["title"] == "Routed AIF"


class TestReadTagsApi:
    def test_read_tags_aiff(self, app_module, client, tmp_path):
        f = _make_aiff(tmp_path / "api.aiff")
        app_module._apply_aiff(str(f), {"title": "API Test", "artist": "DJ"}, None, None)
        r = client.post("/api/read-tags", json={"filepath": str(f)})
        assert r.status_code == 200
        j = r.get_json()
        assert j["title"] == "API Test"
        assert j["format"] == "AIFF"

    def test_read_tags_full_aiff_with_artwork(self, app_module, client, tmp_path):
        f = _make_aiff(tmp_path / "full.aiff")
        jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 100 + b"\xff\xd9"
        app_module._apply_aiff(str(f), {"title": "Full"}, jpeg, "image/jpeg")
        r = client.post("/api/read-tags-full", json={"filepath": str(f)})
        assert r.status_code == 200
        j = r.get_json()
        assert j["format"] == "AIFF"
        assert "artwork_info" in j
        assert j["artwork_info"]["mime"] == "image/jpeg"

    def test_read_tags_full_aiff_no_artwork(self, app_module, client, tmp_path):
        f = _make_aiff(tmp_path / "noart.aiff")
        app_module._apply_aiff(str(f), {"title": "NoArt"}, None, None)
        r = client.post("/api/read-tags-full", json={"filepath": str(f)})
        assert r.status_code == 200
        j = r.get_json()
        assert "artwork_info" not in j
