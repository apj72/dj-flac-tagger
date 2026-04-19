"""API tests for /api/normalise-flac with ffmpeg stubbed."""

import shutil
import subprocess
from pathlib import Path

import pytest


def _make_minimal_flac(path: Path) -> None:
    """Tiny valid FLAC via ffmpeg (requires ffmpeg in CI/dev)."""
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=f=440:d=0.05",
            "-c:a",
            "flac",
            str(path),
        ],
        check=True,
    )
    from mutagen.flac import FLAC, Picture

    audio = FLAC(str(path))
    audio["TITLE"] = ["NormTest"]
    audio["ARTIST"] = ["Tester"]
    pic = Picture()
    pic.type = 3
    pic.mime = "image/png"
    pic.desc = "Cover"
    pic.data = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05"
        b"\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    pic.width, pic.height = 1, 1
    audio.add_picture(pic)
    audio.save()


@pytest.fixture
def flac_src(tmp_path):
    p = tmp_path / "source.flac"
    try:
        _make_minimal_flac(p)
    except (subprocess.CalledProcessError, FileNotFoundError):
        pytest.skip("ffmpeg not available")
    return p


def test_normalise_flac_copies_tags(client, app_module, flac_src, monkeypatch, tmp_path):
    loudnorm_params = {
        "input_i": -20.0,
        "input_tp": -1.0,
        "input_lra": 5.0,
        "input_thresh": -30.0,
    }

    real_run = subprocess.run

    def fake_run(cmd, **kwargs):
        if cmd and cmd[0] == "ffmpeg":
            out = cmd[-1]
            shutil.copy(str(flac_src), out)
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return real_run(cmd, **kwargs)

    monkeypatch.setattr(subprocess, "run", fake_run)

    out_path = tmp_path / "source_LUFS14.flac"
    resp = client.post(
        "/api/normalise-flac",
        json={
            "filepath": str(flac_src),
            "loudnorm_params": loudnorm_params,
            "output_suffix": "_LUFS14",
        },
    )
    assert resp.status_code == 200, resp.get_json()
    data = resp.get_json()
    assert data["output_path"] == str(out_path)
    assert Path(data["output_path"]).is_file()

    from mutagen.flac import FLAC

    dst = FLAC(data["output_path"])
    assert dst["TITLE"] == ["NormTest"]
    assert dst["ARTIST"] == ["Tester"]
    assert len(dst.pictures) == 1


def test_normalise_rejects_non_audio(client, app_module, tmp_path):
    junk = tmp_path / "x.txt"
    junk.write_text("nope")
    resp = client.post(
        "/api/normalise",
        json={"filepath": str(junk), "loudnorm_params": {"input_i": -20}},
    )
    assert resp.status_code == 400


def test_normalise_accepts_mp3_source(client, app_module, flac_src, tmp_path, monkeypatch):
    """Non-FLC input is allowed; output follows extract profile (default FLAC)."""
    mp3 = tmp_path / "source.mp3"
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                "sine=f=440:d=0.05",
                "-c:a",
                "libmp3lame",
                str(mp3),
            ],
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        pytest.skip("ffmpeg not available")

    loudnorm_params = {
        "input_i": -20.0,
        "input_tp": -1.0,
        "input_lra": 5.0,
        "input_thresh": -30.0,
    }
    real_run = subprocess.run

    def fake_run(cmd, **kwargs):
        if cmd and cmd[0] == "ffmpeg":
            out = cmd[-1]
            # Stub encoder output must be a valid FLAC for mutagen in _copy_audio_tags_and_art.
            shutil.copy(str(flac_src), out)
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return real_run(cmd, **kwargs)

    monkeypatch.setattr(subprocess, "run", fake_run)

    out_path = tmp_path / "source_LUFS14.flac"
    resp = client.post(
        "/api/normalise",
        json={
            "filepath": str(mp3),
            "loudnorm_params": loudnorm_params,
            "output_suffix": "_LUFS14",
        },
    )
    assert resp.status_code == 200, resp.get_json()
    data = resp.get_json()
    assert data["output_path"] == str(out_path)
    assert Path(data["output_path"]).is_file()


def test_normalise_flac_requires_params(client, app_module, flac_src):
    resp = client.post(
        "/api/normalise-flac",
        json={"filepath": str(flac_src)},
    )
    assert resp.status_code == 400
