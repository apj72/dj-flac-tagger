"""Tests for /api/stream-audio preview playback."""

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


def test_stream_audio_200_and_range(tmp_path, client, monkeypatch):
    import app as app_mod

    monkeypatch.setattr(app_mod, "CONFIG_PATH", str(tmp_path / "config.json"))
    p = tmp_path / "preview.flac"
    try:
        _minimal_flac(p)
    except (FileNotFoundError, subprocess.CalledProcessError):
        pytest.skip("ffmpeg not available")

    r = client.get(f"/api/stream-audio?path={p}", follow_redirects=False)
    assert r.status_code == 200
    assert "audio" in (r.headers.get("Content-Type") or "")
    assert len(r.data) > 10

    full_len = len(r.data)
    r2 = client.get(
        f"/api/stream-audio?path={p}",
        headers={"Range": "bytes=0-99"},
    )
    assert r2.status_code == 206
    assert len(r2.data) <= 100
    assert len(r2.data) < full_len


def test_stream_audio_rejects_txt(tmp_path, client, monkeypatch):
    import app as app_mod

    monkeypatch.setattr(app_mod, "CONFIG_PATH", str(tmp_path / "config.json"))
    junk = tmp_path / "note.txt"
    junk.write_text("nope")
    r = client.get(f"/api/stream-audio?path={junk}")
    assert r.status_code == 415
