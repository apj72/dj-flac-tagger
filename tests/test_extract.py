"""Tests for /api/extract route with all external calls stubbed."""

import json
import os
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FAKE_LOUDNORM_PARAMS = {
    "input_i": "-20.00",
    "input_tp": "-1.50",
    "input_lra": "5.00",
    "input_thresh": "-30.00",
}

GOOD_POST_LOUDNORM = {
    "input_i": "-14.00",
    "input_tp": "-1.00",
    "input_lra": "5.00",
    "input_thresh": "-24.00",
}

BAD_POST_LOUDNORM = {
    "input_i": "-25.00",
    "input_tp": "0.50",
    "input_lra": "5.00",
    "input_thresh": "-35.00",
}

SAMPLE_METADATA = {
    "title": "Test Track",
    "artist": "Test Artist",
    "album": "Test Album",
    "genre": "Electronic",
}


def _stub_source(tmp_path, name="source.mkv"):
    """Create a tiny file that acts as the source recording."""
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"\x00" * 64)
    return p


def _patch_extract_deps(monkeypatch, app_module, tmp_path,
                         analyse_side_effects=None):
    """Monkeypatch all heavy functions used by /api/extract.

    Returns a dict of call-tracking lists so tests can inspect what was called.
    """
    calls = {
        "extract_audio": [],
        "apply_metadata": [],
        "analyse_loudness": [],
        "run_ffprobe": [],
        "ffmpeg_loudnorm_encode": [],
        "fetch_artwork": [],
    }
    analyse_iter = iter(analyse_side_effects or [])

    def fake_extract_audio(src, out, profile, normalise=False, loudnorm_params=None):
        calls["extract_audio"].append({
            "src": src, "out": out, "profile": profile,
            "normalise": normalise, "loudnorm_params": loudnorm_params,
        })
        # Create the output file so downstream os.stat works
        Path(out).write_bytes(b"\x00" * 128)
        return "aac"

    def fake_apply_metadata(filepath, metadata, artwork_bytes=None, artwork_mime=None):
        calls["apply_metadata"].append({
            "filepath": filepath, "metadata": metadata,
            "artwork_bytes": artwork_bytes, "artwork_mime": artwork_mime,
        })

    def fake_analyse_loudness(filepath):
        result = next(analyse_iter, {
            "integrated_lufs": -14.0,
            "true_peak": -1.0,
            "lra": 5.0,
            "threshold": -24.0,
            "mean_volume": -16.0,
            "max_volume": -1.0,
            "target_lufs": -14.0,
            "target_tp": -1.0,
            "loudnorm_params": GOOD_POST_LOUDNORM,
        })
        calls["analyse_loudness"].append({"filepath": filepath, "result": result})
        return result

    def fake_run_ffprobe(filepath):
        calls["run_ffprobe"].append(filepath)
        return {"streams": [{"codec_name": "aac", "sample_rate": "44100", "channels": 2}]}

    def fake_ffmpeg_loudnorm_encode(input_path, output_path, lp, profile_key,
                                     target_lufs=None, target_tp=None):
        calls["ffmpeg_loudnorm_encode"].append({
            "input": input_path, "output": output_path,
        })
        # Write a file so os.replace succeeds
        Path(output_path).write_bytes(b"\x00" * 128)

    def fake_fetch_artwork(url):
        calls["fetch_artwork"].append(url)
        return (b"\xff\xd8\xff\xe0" + b"\x00" * 60, "image/jpeg")

    monkeypatch.setattr(app_module, "extract_audio", fake_extract_audio)
    monkeypatch.setattr(app_module, "apply_metadata", fake_apply_metadata)
    monkeypatch.setattr(app_module, "analyse_loudness", fake_analyse_loudness)
    monkeypatch.setattr(app_module, "run_ffprobe", fake_run_ffprobe)
    monkeypatch.setattr(app_module, "_ffmpeg_loudnorm_encode", fake_ffmpeg_loudnorm_encode)
    monkeypatch.setattr(app_module, "fetch_artwork", fake_fetch_artwork)

    return calls


# ---------------------------------------------------------------------------
# 1. Basic extract without normalise
# ---------------------------------------------------------------------------

class TestBasicExtract:

    def test_extract_returns_expected_fields(self, client, app_module, monkeypatch, tmp_path):
        src = _stub_source(tmp_path)
        calls = _patch_extract_deps(monkeypatch, app_module, tmp_path)

        resp = client.post("/api/extract", json={
            "filepath": str(src),
            "metadata": SAMPLE_METADATA,
            "artwork_url": "",
        })

        assert resp.status_code == 200, resp.get_json()
        data = resp.get_json()

        # Core fields are present
        assert data["filename"] == "Test Track.flac"
        assert data["title"] == "Test Track"
        assert data["extract_profile"] == "flac"
        assert data["extract_profile_label"] == "FLAC (lossless)"
        assert data["is_lossless_output"] is True
        assert data["source_codec"] == "aac"
        assert data["normalised"] is False
        assert "output_path" in data
        assert "size_mb" in data
        assert "log_index" in data

    def test_extract_calls_extract_audio_without_normalise(self, client, app_module, monkeypatch, tmp_path):
        src = _stub_source(tmp_path)
        calls = _patch_extract_deps(monkeypatch, app_module, tmp_path)

        resp = client.post("/api/extract", json={
            "filepath": str(src),
            "metadata": SAMPLE_METADATA,
        })
        assert resp.status_code == 200

        assert len(calls["extract_audio"]) == 1
        ea = calls["extract_audio"][0]
        assert ea["normalise"] is False
        assert ea["loudnorm_params"] is None

    def test_extract_updates_processing_log(self, client, app_module, monkeypatch, tmp_path):
        src = _stub_source(tmp_path)
        _patch_extract_deps(monkeypatch, app_module, tmp_path)

        resp = client.post("/api/extract", json={
            "filepath": str(src),
            "metadata": SAMPLE_METADATA,
        })
        assert resp.status_code == 200
        data = resp.get_json()

        log = app_module.load_log()
        assert len(log) == 1
        assert log[0]["kind"] == "extract"
        assert log[0]["filename"] == "Test Track.flac"
        assert log[0]["source_file"] == str(src)
        assert data["log_index"] == 0


# ---------------------------------------------------------------------------
# 2. Extract with normalise
# ---------------------------------------------------------------------------

class TestExtractWithNormalise:

    def test_normalise_analyses_source_and_passes_params(self, client, app_module, monkeypatch, tmp_path):
        src = _stub_source(tmp_path)

        source_analysis = {
            "integrated_lufs": -20.0,
            "true_peak": -1.5,
            "lra": 5.0,
            "threshold": -30.0,
            "loudnorm_params": FAKE_LOUDNORM_PARAMS,
        }
        # analyse_loudness is called: once for the source, once for post-verify
        post_analysis = {
            "integrated_lufs": -14.0,
            "true_peak": -1.0,
            "lra": 5.0,
            "threshold": -24.0,
            "loudnorm_params": GOOD_POST_LOUDNORM,
        }
        calls = _patch_extract_deps(
            monkeypatch, app_module, tmp_path,
            analyse_side_effects=[source_analysis, post_analysis],
        )

        resp = client.post("/api/extract", json={
            "filepath": str(src),
            "metadata": SAMPLE_METADATA,
            "normalise": True,
        })
        assert resp.status_code == 200, resp.get_json()
        data = resp.get_json()

        assert data["normalised"] is True
        assert "target_lufs" in data
        assert "target_tp" in data

        # extract_audio was called with normalise=True and the measured params
        ea = calls["extract_audio"][0]
        assert ea["normalise"] is True
        assert ea["loudnorm_params"] == FAKE_LOUDNORM_PARAMS

    def test_normalise_response_includes_targets(self, client, app_module, monkeypatch, tmp_path):
        src = _stub_source(tmp_path)

        source_analysis = {
            "loudnorm_params": FAKE_LOUDNORM_PARAMS,
        }
        post_analysis = {
            "loudnorm_params": GOOD_POST_LOUDNORM,
        }
        _patch_extract_deps(
            monkeypatch, app_module, tmp_path,
            analyse_side_effects=[source_analysis, post_analysis],
        )

        resp = client.post("/api/extract", json={
            "filepath": str(src),
            "metadata": SAMPLE_METADATA,
            "normalise": True,
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["target_lufs"] == -14.0
        assert data["target_tp"] == -1.0


# ---------------------------------------------------------------------------
# 3. Loudness verification retry
# ---------------------------------------------------------------------------

class TestLoudnessVerifyRetry:

    def test_retry_on_out_of_tolerance(self, client, app_module, monkeypatch, tmp_path):
        """When post-extract loudness is out of tolerance, the route retries
        with a fresh source analysis and re-encode. Verify the retry is
        triggered and succeeds on the second pass."""
        src = _stub_source(tmp_path)

        source_analysis = {
            "loudnorm_params": FAKE_LOUDNORM_PARAMS,
        }
        # Post-verify: out of tolerance (LUFS way off)
        bad_post = {
            "loudnorm_params": BAD_POST_LOUDNORM,
        }
        # Retry source re-analysis
        retry_source = {
            "loudnorm_params": FAKE_LOUDNORM_PARAMS,
        }
        # After retry re-encode, the output passes
        good_post = {
            "loudnorm_params": GOOD_POST_LOUDNORM,
        }

        calls = _patch_extract_deps(
            monkeypatch, app_module, tmp_path,
            analyse_side_effects=[source_analysis, bad_post, retry_source, good_post],
        )

        resp = client.post("/api/extract", json={
            "filepath": str(src),
            "metadata": SAMPLE_METADATA,
            "normalise": True,
        })
        assert resp.status_code == 200, resp.get_json()
        data = resp.get_json()

        assert data["normalised"] is True
        assert data["loudness_retried"] is True
        # No warning because the retry succeeded
        assert "loudness_verify_warning" not in data

        # _ffmpeg_loudnorm_encode was called for the retry
        assert len(calls["ffmpeg_loudnorm_encode"]) == 1

    def test_retry_still_failing_produces_warning(self, client, app_module, monkeypatch, tmp_path):
        """When the retry also fails tolerance, a warning is included."""
        src = _stub_source(tmp_path)

        source_analysis = {
            "loudnorm_params": FAKE_LOUDNORM_PARAMS,
        }
        bad_post = {
            "loudnorm_params": BAD_POST_LOUDNORM,
        }
        retry_source = {
            "loudnorm_params": FAKE_LOUDNORM_PARAMS,
        }
        # Still bad after retry
        still_bad = {
            "loudnorm_params": BAD_POST_LOUDNORM,
        }

        calls = _patch_extract_deps(
            monkeypatch, app_module, tmp_path,
            analyse_side_effects=[source_analysis, bad_post, retry_source, still_bad],
        )

        resp = client.post("/api/extract", json={
            "filepath": str(src),
            "metadata": SAMPLE_METADATA,
            "normalise": True,
        })
        assert resp.status_code == 200, resp.get_json()
        data = resp.get_json()

        assert data["loudness_retried"] is True
        assert "loudness_verify_warning" in data
        assert "still failing" in data["loudness_verify_warning"].lower()

    def test_no_retry_when_verify_disabled(self, client, app_module, monkeypatch, tmp_path):
        """When loudness_verify_enabled is false in config, no post-verify happens."""
        src = _stub_source(tmp_path)

        # Update config to disable verification
        cfg_path = Path(app_module.CONFIG_PATH)
        cfg = json.loads(cfg_path.read_text())
        cfg["loudness_verify_enabled"] = False
        cfg_path.write_text(json.dumps(cfg))

        source_analysis = {
            "loudnorm_params": FAKE_LOUDNORM_PARAMS,
        }
        # Only one analysis call expected (source), no post-verify
        calls = _patch_extract_deps(
            monkeypatch, app_module, tmp_path,
            analyse_side_effects=[source_analysis],
        )

        resp = client.post("/api/extract", json={
            "filepath": str(src),
            "metadata": SAMPLE_METADATA,
            "normalise": True,
        })
        assert resp.status_code == 200, resp.get_json()
        data = resp.get_json()

        # Only one analyse_loudness call (for the source), no post-verify
        assert len(calls["analyse_loudness"]) == 1
        assert data["normalised"] is True
        assert data.get("loudness_retried") is False


# ---------------------------------------------------------------------------
# 4. Copy to destination
# ---------------------------------------------------------------------------

class TestCopyToDestination:

    def test_file_copied_to_destination_dir(self, client, app_module, monkeypatch, tmp_path):
        (tmp_path / "recordings").mkdir(exist_ok=True)
        src = _stub_source(tmp_path / "recordings", "source.mkv")

        dest_dir = tmp_path / "library"
        dest_dir.mkdir()

        # Update config with distinct destination
        cfg_path = Path(app_module.CONFIG_PATH)
        cfg = json.loads(cfg_path.read_text())
        cfg["destination_dir"] = str(dest_dir)
        cfg_path.write_text(json.dumps(cfg))

        _patch_extract_deps(monkeypatch, app_module, tmp_path)

        resp = client.post("/api/extract", json={
            "filepath": str(src),
            "metadata": SAMPLE_METADATA,
        })
        assert resp.status_code == 200, resp.get_json()
        data = resp.get_json()

        assert "copied_to" in data
        assert data["copied_to"] == str(dest_dir / "Test Track.flac")
        assert (dest_dir / "Test Track.flac").is_file()

    def test_no_copy_when_destination_empty(self, client, app_module, monkeypatch, tmp_path):
        src = _stub_source(tmp_path)

        cfg_path = Path(app_module.CONFIG_PATH)
        cfg = json.loads(cfg_path.read_text())
        cfg["destination_dir"] = ""
        cfg_path.write_text(json.dumps(cfg))

        _patch_extract_deps(monkeypatch, app_module, tmp_path)

        resp = client.post("/api/extract", json={
            "filepath": str(src),
            "metadata": SAMPLE_METADATA,
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert "copied_to" not in data


# ---------------------------------------------------------------------------
# 5. Error handling
# ---------------------------------------------------------------------------

class TestExtractErrors:

    def test_missing_source_returns_404(self, client, app_module, monkeypatch, tmp_path):
        _patch_extract_deps(monkeypatch, app_module, tmp_path)

        resp = client.post("/api/extract", json={
            "filepath": str(tmp_path / "nonexistent.mkv"),
            "metadata": SAMPLE_METADATA,
        })
        assert resp.status_code == 404
        data = resp.get_json()
        assert "error" in data
        assert "not found" in data["error"].lower()

    def test_no_filepath_returns_404(self, client, app_module, monkeypatch, tmp_path):
        _patch_extract_deps(monkeypatch, app_module, tmp_path)

        resp = client.post("/api/extract", json={
            "metadata": SAMPLE_METADATA,
        })
        assert resp.status_code == 404

    def test_output_already_exists_returns_409(self, client, app_module, monkeypatch, tmp_path):
        src = _stub_source(tmp_path)
        # Pre-create the output file to trigger the conflict
        (tmp_path / "Test Track.flac").write_bytes(b"\x00")

        _patch_extract_deps(monkeypatch, app_module, tmp_path)

        resp = client.post("/api/extract", json={
            "filepath": str(src),
            "metadata": SAMPLE_METADATA,
        })
        assert resp.status_code == 409
        data = resp.get_json()
        assert "already exists" in data["error"].lower()

    def test_normalise_with_unusable_loudnorm_returns_500(self, client, app_module, monkeypatch, tmp_path):
        """If source analysis returns no usable loudnorm params, return 500."""
        src = _stub_source(tmp_path)

        bad_analysis = {
            "loudnorm_params": {},  # missing input_i
        }
        _patch_extract_deps(
            monkeypatch, app_module, tmp_path,
            analyse_side_effects=[bad_analysis],
        )

        resp = client.post("/api/extract", json={
            "filepath": str(src),
            "metadata": SAMPLE_METADATA,
            "normalise": True,
        })
        assert resp.status_code == 500
        data = resp.get_json()
        assert "loudness analysis" in data["error"].lower()


# ---------------------------------------------------------------------------
# 6. Metadata applied correctly
# ---------------------------------------------------------------------------

class TestMetadataApplied:

    def test_metadata_passed_to_apply_metadata(self, client, app_module, monkeypatch, tmp_path):
        src = _stub_source(tmp_path)
        calls = _patch_extract_deps(monkeypatch, app_module, tmp_path)

        metadata = {
            "title": "Acid Rain",
            "artist": "DJ Test",
            "album": "Warehouse Sessions",
            "genre": "Techno",
            "label": "Underground Records",
            "catno": "UG-001",
        }

        resp = client.post("/api/extract", json={
            "filepath": str(src),
            "metadata": metadata,
            "artwork_url": "",
        })
        assert resp.status_code == 200

        assert len(calls["apply_metadata"]) == 1
        am = calls["apply_metadata"][0]
        assert am["metadata"]["title"] == "Acid Rain"
        assert am["metadata"]["artist"] == "DJ Test"
        assert am["metadata"]["album"] == "Warehouse Sessions"
        assert am["metadata"]["genre"] == "Techno"
        assert am["metadata"]["label"] == "Underground Records"

    def test_metadata_source_url_stored(self, client, app_module, monkeypatch, tmp_path):
        src = _stub_source(tmp_path)
        calls = _patch_extract_deps(monkeypatch, app_module, tmp_path)

        resp = client.post("/api/extract", json={
            "filepath": str(src),
            "metadata": SAMPLE_METADATA,
            "metadata_source_url": "https://bandcamp.com/track/123",
        })
        assert resp.status_code == 200

        am = calls["apply_metadata"][0]
        assert am["metadata"]["source_url"] == "https://bandcamp.com/track/123"

        log = app_module.load_log()
        assert log[0]["metadata_source_url"] == "https://bandcamp.com/track/123"
        assert log[0]["metadata_source_type"] == "bandcamp"

    def test_artwork_url_fetched_and_embedded(self, client, app_module, monkeypatch, tmp_path):
        src = _stub_source(tmp_path)
        calls = _patch_extract_deps(monkeypatch, app_module, tmp_path)

        resp = client.post("/api/extract", json={
            "filepath": str(src),
            "metadata": SAMPLE_METADATA,
            "artwork_url": "https://example.com/cover.jpg",
        })
        assert resp.status_code == 200

        # fetch_artwork was called
        assert len(calls["fetch_artwork"]) == 1
        assert calls["fetch_artwork"][0] == "https://example.com/cover.jpg"

        # The fetched artwork was passed to apply_metadata
        am = calls["apply_metadata"][0]
        assert am["artwork_bytes"] is not None
        assert am["artwork_mime"] == "image/jpeg"

    def test_artwork_base64_preferred_over_url(self, client, app_module, monkeypatch, tmp_path):
        """When artwork_base64 is supplied, it should be used and artwork_url
        should NOT be fetched."""
        src = _stub_source(tmp_path)
        calls = _patch_extract_deps(monkeypatch, app_module, tmp_path)

        # 1x1 PNG base64
        png_b64 = (
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4"
            "2mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
        )

        resp = client.post("/api/extract", json={
            "filepath": str(src),
            "metadata": SAMPLE_METADATA,
            "artwork_url": "https://example.com/cover.jpg",
            "artwork_base64": png_b64,
            "artwork_mime": "image/png",
        })
        assert resp.status_code == 200

        # artwork_url should NOT have been fetched
        assert len(calls["fetch_artwork"]) == 0

        # The decoded base64 bytes were passed to apply_metadata
        am = calls["apply_metadata"][0]
        assert am["artwork_bytes"] is not None
        assert am["artwork_mime"] == "image/png"

    def test_log_entry_records_normalisation_state(self, client, app_module, monkeypatch, tmp_path):
        src = _stub_source(tmp_path)

        source_analysis = {"loudnorm_params": FAKE_LOUDNORM_PARAMS}
        post_analysis = {"loudnorm_params": GOOD_POST_LOUDNORM}
        _patch_extract_deps(
            monkeypatch, app_module, tmp_path,
            analyse_side_effects=[source_analysis, post_analysis],
        )

        resp = client.post("/api/extract", json={
            "filepath": str(src),
            "metadata": SAMPLE_METADATA,
            "normalise": True,
        })
        assert resp.status_code == 200

        log = app_module.load_log()
        entry = log[0]
        assert entry["normalised"] is True
        assert entry["normalise_target_lufs"] == -14.0
        assert entry["normalise_target_tp"] == -1.0
