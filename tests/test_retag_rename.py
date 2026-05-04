"""Tests for retag with rename_to_tags."""

import json
import subprocess

import pytest


def _minimal_flac(path):
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "sine=f=440:d=0.05",
            "-c:a", "flac",
            str(path),
        ],
        check=True,
    )


def test_basename_from_artist_title(app_module):
    fn = app_module._basename_from_artist_title_for_rename
    assert fn("A", "B", ".flac") == "A - B.flac"
    assert fn("", "Solo", ".mp3") == "Solo.mp3"
    assert fn("X", "", ".flac") == "X.flac"
    assert fn("", "", ".flac") is None
    t = fn('Bad<name>', "T", ".flac")
    assert t == "Badname - T.flac"
    assert fn("A", "B", ".flac", "_warped") == "A - B_warped.flac"


def test_retag_rename_flac(tmp_path, client, app_module, monkeypatch):
    import app as app_mod

    monkeypatch.setattr(app_mod, "CONFIG_PATH", str(tmp_path / "config.json"))
    monkeypatch.setattr(app_mod, "LOG_PATH", str(tmp_path / "log.json"))
    p = tmp_path / "A06 - 139 - X - Y.flac"
    try:
        _minimal_flac(p)
    except (FileNotFoundError, subprocess.CalledProcessError):
        import pytest

        pytest.skip("ffmpeg not available")

    r = client.post(
        "/api/retag",
        json={
            "filepath": str(p),
            "metadata": {"title": "Y", "artist": "X", "comment": "c"},
            "artwork_url": "",
            "metadata_source_url": "",
            "record_in_log": False,
            "rename_to_tags": True,
        },
    )
    assert r.status_code == 200
    j = r.get_json()
    assert j.get("renamed") is True
    newp = tmp_path / "X - Y.flac"
    assert newp.is_file()
    assert not p.exists()


def test_retag_rename_collision_409(tmp_path, client, app_module, monkeypatch):
    import app as app_mod
    import pytest

    monkeypatch.setattr(app_mod, "CONFIG_PATH", str(tmp_path / "config.json"))
    blocker = tmp_path / "A - B.flac"
    longf = tmp_path / "01 - 130 - A - B.flac"
    try:
        _minimal_flac(blocker)
        _minimal_flac(longf)
    except (FileNotFoundError, subprocess.CalledProcessError):
        pytest.skip("ffmpeg not available")

    r = client.post(
        "/api/retag",
        json={
            "filepath": str(longf),
            "metadata": {"title": "B", "artist": "A", "comment": "c"},
            "artwork_url": "",
            "metadata_source_url": "",
            "record_in_log": False,
            "rename_to_tags": True,
        },
    )
    assert r.status_code == 409
    assert longf.is_file()
    j = r.get_json()
    assert "error" in j


def test_retag_rename_keeps_configured_warped_suffix(tmp_path, client, monkeypatch):
    import app as app_mod

    monkeypatch.setattr(app_mod, "CONFIG_PATH", str(tmp_path / "config.json"))
    monkeypatch.setattr(app_mod, "LOG_PATH", str(tmp_path / "log.json"))
    (tmp_path / "config.json").write_text(
        json.dumps({
            "source_dir": str(tmp_path),
            "destination_dir": str(tmp_path),
            "fix_retain_filename_suffixes": ["_warped"],
        }),
        encoding="utf-8",
    )

    p = tmp_path / "01 - 130 - A - B_warped.flac"
    try:
        _minimal_flac(p)
    except (FileNotFoundError, subprocess.CalledProcessError):
        pytest.skip("ffmpeg not available")

    r = client.post(
        "/api/retag",
        json={
            "filepath": str(p),
            "metadata": {"title": "B", "artist": "A", "comment": "c"},
            "artwork_url": "",
            "metadata_source_url": "",
            "record_in_log": False,
            "rename_to_tags": True,
        },
    )
    assert r.status_code == 200
    newp = tmp_path / "A - B_warped.flac"
    assert newp.is_file()
    assert not p.exists()
