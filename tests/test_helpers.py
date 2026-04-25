"""Unit tests for small pure helpers (no ffmpeg)."""

import os
import subprocess
from pathlib import Path

import pytest


def test_infer_metadata_source_type(app_module):
    assert app_module.infer_metadata_source_type("") == ""
    assert app_module.infer_metadata_source_type("https://bandcamp.com/track/x") == "bandcamp"
    assert app_module.infer_metadata_source_type("https://www.discogs.com/release/1") == "discogs"
    assert app_module.infer_metadata_source_type("https://music.apple.com/us/album/x") == "apple_music"
    assert app_module.infer_metadata_source_type("https://open.spotify.com/track/x") == "spotify"


def test_pn_derivative_path(app_module):
    p = app_module.pn_derivative_path("/Volumes/Music/My Track.flac", "_PN")
    assert p.name == "My Track_PN.flac"
    p2 = app_module.pn_derivative_path("/a/b/c.flac", "_norm")
    assert p2.name == "c_norm.flac"
    p3 = app_module.pn_derivative_path("/a/b/track.mp3", "_PN")
    assert p3.name == "track_PN.mp3"


def test_pn_output_candidate_paths_includes_dest_and_library_copy(
    app_module, tmp_path, monkeypatch
):
    """PN may write only to FLACs (Settings destination) — same stem_PN beside library copy or flat in dest."""
    monkeypatch.setattr(
        app_module, "resolve", lambda p: os.path.normpath(os.path.expanduser(str(p)))
    )
    rec = tmp_path / "rec"
    rec.mkdir()
    flacs = tmp_path / "FLACs"
    flacs.mkdir()
    base = str(rec / "Song.flac")
    copied = str(flacs / "Song.flac")
    paths = app_module._pn_output_candidate_paths(
        base, "_PN", copied_to=copied, destination_dir=str(flacs)
    )
    want_extract = str(rec / "Song_PN.flac")
    want_flacs = str(flacs / "Song_PN.flac")
    assert want_extract in paths
    assert want_flacs in paths
    # copied_to parent + name and destination_dir + name are the same file in this layout
    assert len(paths) == 2


def test_resolve_extract_profile_key(app_module):
    assert app_module.resolve_extract_profile_key({"extract_profile": "mp3_320"}) == "mp3_320"
    assert app_module.resolve_extract_profile_key({"extract_profile": "bogus"}) == "flac"


def test_find_log_entry_for_output_path(app_module, tmp_path):
    a = tmp_path / "song.flac"
    a.write_bytes(b"x")
    entries = [
        {"output_path": str(a), "metadata": {"title": "A"}},
        {"output_path": str(tmp_path / "other.flac"), "metadata": {}},
    ]
    app_module.save_log(entries)

    found, idx = app_module.find_log_entry_for_output_path(str(a))
    assert found is not None
    assert found["metadata"]["title"] == "A"
    assert idx == 0

    by_index, i2 = app_module.find_log_entry_for_output_path(str(a), log_index=1)
    assert by_index["output_path"] == str(tmp_path / "other.flac")
    assert i2 == 1

    missing, _ = app_module.find_log_entry_for_output_path(str(tmp_path / "nope.flac"))
    assert missing is None


def test_get_normalisation_targets_default(app_module):
    lufs, tp = app_module.get_normalisation_targets()
    assert lufs == -14.0
    assert tp == -1.0


def test_get_normalisation_targets_platinum_style_magnitude(app_module):
    cfg = app_module.load_config()
    cfg["target_lufs"] = 11.5
    cfg["target_true_peak"] = 1.0
    app_module.save_config(cfg)
    lufs, tp = app_module.get_normalisation_targets()
    assert lufs == -11.5
    assert tp == -1.0


def test_get_normalisation_targets_explicit_negative(app_module):
    cfg = app_module.load_config()
    cfg["target_lufs"] = -11.5
    app_module.save_config(cfg)
    assert app_module.get_normalisation_targets()[0] == -11.5


def test_aformat_opts_preserve_stream(app_module, tmp_path):
    p = tmp_path / "t.flac"
    try:
        subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "sine=f=440:d=0.05",
                "-c:a", "flac", str(p),
            ],
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        pytest.skip("ffmpeg not available")
    s = app_module._aformat_opts_preserve_stream(str(p))
    assert "sample_fmts=s16" in s
    assert "sample_rates=" in s


def test_loudnorm_params_usable(app_module):
    assert app_module._loudnorm_params_usable({"input_i": "-20"}) is True
    assert app_module._loudnorm_params_usable({}) is False


def test_normalised_output_meets_targets_ok(app_module):
    p = {"input_i": "-11.5", "input_tp": "-1.1"}
    ok, reasons = app_module.normalised_output_meets_targets(p, -11.5, -1.0, 2.0, 0.35)
    assert ok is True
    assert not reasons


def test_normalised_output_meets_targets_hot_true_peak(app_module):
    p = {"input_i": "-11.54", "input_tp": "0.36"}
    ok, reasons = app_module.normalised_output_meets_targets(p, -11.5, -1.0, 2.0, 0.35)
    assert ok is False
    assert any("true peak" in r for r in reasons)
