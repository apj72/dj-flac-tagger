"""Tests for configurable MP3/AAC bitrate in extract profiles."""

import pytest


class TestResolveProfile:
    def test_flac_profile(self, app_module):
        prof = app_module._resolve_profile("flac")
        assert prof["ext"] == ".flac"
        assert prof["lossless"] is True
        assert "flac" in prof["ffmpeg_encode"]

    def test_mp3_default_bitrate(self, app_module):
        prof = app_module._resolve_profile("mp3")
        assert prof["ext"] == ".mp3"
        assert "320k" in prof["ffmpeg_encode"]
        assert "320" in prof["label"]

    def test_mp3_custom_bitrate(self, app_module):
        prof = app_module._resolve_profile("mp3", {"mp3_bitrate": "192"})
        assert "192k" in prof["ffmpeg_encode"]
        assert "192" in prof["label"]

    def test_mp3_invalid_bitrate_falls_back(self, app_module):
        prof = app_module._resolve_profile("mp3", {"mp3_bitrate": "999"})
        assert "320k" in prof["ffmpeg_encode"]

    def test_aac_default_bitrate(self, app_module):
        prof = app_module._resolve_profile("aac")
        assert prof["ext"] == ".m4a"
        assert "256k" in prof["ffmpeg_encode"]

    def test_aac_custom_bitrate(self, app_module):
        prof = app_module._resolve_profile("aac", {"aac_bitrate": "128"})
        assert "128k" in prof["ffmpeg_encode"]
        assert "128" in prof["label"]

    def test_aac_invalid_bitrate_falls_back(self, app_module):
        prof = app_module._resolve_profile("aac", {"aac_bitrate": "abc"})
        assert "256k" in prof["ffmpeg_encode"]

    def test_unknown_profile_falls_back_to_flac(self, app_module):
        prof = app_module._resolve_profile("nonexistent")
        assert prof["ext"] == ".flac"


class TestProfileKeyMigration:
    def test_mp3_320_migrates(self, app_module):
        assert app_module.resolve_extract_profile_key({"extract_profile": "mp3_320"}) == "mp3"

    def test_aac_256_migrates(self, app_module):
        assert app_module.resolve_extract_profile_key({"extract_profile": "aac_256"}) == "aac"

    def test_new_keys_work(self, app_module):
        assert app_module.resolve_extract_profile_key({"extract_profile": "mp3"}) == "mp3"
        assert app_module.resolve_extract_profile_key({"extract_profile": "aac"}) == "aac"
        assert app_module.resolve_extract_profile_key({"extract_profile": "flac"}) == "flac"


class TestProfileOptions:
    def test_returns_all_profiles(self, app_module):
        opts = app_module.extract_profile_options()
        keys = [o["key"] for o in opts]
        assert "flac" in keys
        assert "mp3" in keys
        assert "aac" in keys

    def test_labels_reflect_config_bitrate(self, app_module):
        opts = app_module.extract_profile_options({"mp3_bitrate": "192", "aac_bitrate": "128"})
        mp3_opt = next(o for o in opts if o["key"] == "mp3")
        aac_opt = next(o for o in opts if o["key"] == "aac")
        assert "192" in mp3_opt["label"]
        assert "128" in aac_opt["label"]


class TestSettingsApiBitrate:
    def test_get_settings_includes_bitrate(self, client, app_module):
        r = client.get("/api/settings")
        assert r.status_code == 200
        j = r.get_json()
        assert "mp3_bitrate" in j
        assert "aac_bitrate" in j
        assert "mp3_bitrate_options" in j
        assert "aac_bitrate_options" in j

    def test_post_settings_updates_bitrate(self, client, app_module):
        r = client.post("/api/settings", json={
            "mp3_bitrate": "192",
            "aac_bitrate": "128",
        }, content_type="application/json")
        assert r.status_code == 200
        j = r.get_json()
        assert j["mp3_bitrate"] == "192"
        assert j["aac_bitrate"] == "128"

    def test_post_settings_rejects_invalid_bitrate(self, client, app_module):
        r = client.post("/api/settings", json={
            "mp3_bitrate": "999",
        }, content_type="application/json")
        assert r.status_code == 200
        j = r.get_json()
        assert j["mp3_bitrate"] != "999"

    def test_post_settings_migrates_old_profile_key(self, client, app_module):
        r = client.post("/api/settings", json={
            "extract_profile": "mp3_320",
        }, content_type="application/json")
        assert r.status_code == 200
        j = r.get_json()
        assert j["extract_profile"] == "mp3"
