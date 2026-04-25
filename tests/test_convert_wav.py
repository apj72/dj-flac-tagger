"""Tests for /api/browse-wav and /api/convert-wav-to-flac."""

import subprocess
from pathlib import Path

import pytest
from mutagen.flac import FLAC


def _write_minimal_wav(path: Path) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=f=440:d=0.1",
            "-c:a",
            "pcm_s16le",
            str(path),
        ],
        check=True,
    )


@pytest.fixture
def minimal_wav(tmp_path):
    w = tmp_path / "a.wav"
    try:
        _write_minimal_wav(w)
    except (FileNotFoundError, subprocess.CalledProcessError):
        pytest.skip("ffmpeg not available")
    return w


def test_browse_wav_lists_only_wav(client, app_module, tmp_path):
    d = tmp_path / "d"
    d.mkdir()
    (d / "x.wav").write_bytes(b"")
    (d / "y.flac").write_bytes(b"")
    (d / "z.txt").write_bytes(b"")

    r = client.get(f"/api/browse-wav?dir={d}")
    assert r.status_code == 200
    data = r.get_json()
    assert len(data["files"]) == 1
    assert data["files"][0]["name"] == "x.wav"


def test_convert_wav_to_flac_same_folder(client, app_module, minimal_wav, tmp_path):
    r = client.post(
        "/api/convert-wav-to-flac",
        json={"filepath": str(minimal_wav), "output": "same"},
    )
    assert r.status_code == 200
    out = Path(minimal_wav).with_suffix(".flac")
    assert out.is_file()
    j = r.get_json()
    assert "output_path" in j
    out.unlink(missing_ok=True)


def test_convert_wav_to_flac_destination(
    client, app_module, minimal_wav, tmp_path, monkeypatch
):
    dest = tmp_path / "outlib"
    dest.mkdir()
    real_load = app_module.load_config

    def load_dest():
        c = real_load()
        c["destination_dir"] = str(dest)
        return c

    monkeypatch.setattr(app_module, "load_config", load_dest)
    r = client.post(
        "/api/convert-wav-to-flac",
        json={"filepath": str(minimal_wav), "output": "destination"},
    )
    assert r.status_code == 200
    flac = dest / f"{Path(minimal_wav).stem}.flac"
    assert flac.is_file()
    flac.unlink(missing_ok=True)
    # source folder should not get a flac
    assert not (Path(minimal_wav).with_suffix(".flac")).exists()


def test_convert_rejects_non_wav(client, app_module, tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("x")
    r = client.post(
        "/api/convert-wav-to-flac",
        json={"filepath": str(p), "output": "same"},
    )
    assert r.status_code == 400


def test_scan_wav_bulk(client, app_module, tmp_path):
    (tmp_path / "a.wav").write_bytes(b"")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "b.wav").write_bytes(b"")
    r = client.get(f"/api/scan-wav-bulk?path={tmp_path}&recursive=1")
    assert r.status_code == 200
    assert r.get_json()["count"] == 2
    r0 = client.get(f"/api/scan-wav-bulk?path={tmp_path}&recursive=0")
    assert r0.get_json()["count"] == 1


def test_convert_wav_bulk_same_tree(client, app_module, tmp_path):
    try:
        _write_minimal_wav(tmp_path / "a.wav")
        d = tmp_path / "bpm"
        d.mkdir()
        _write_minimal_wav(d / "b.wav")
    except (FileNotFoundError, subprocess.CalledProcessError):
        pytest.skip("ffmpeg not available")

    r = client.post(
        "/api/convert-wav-bulk",
        json={
            "root_dir": str(tmp_path),
            "output": "same",
            "recursive": True,
            "skip_if_flac_exists": True,
        },
    )
    assert r.status_code == 200
    j = r.get_json()
    s = j["summary"]
    b = j.get("batch") or {}
    assert b.get("total_wavs") == 2
    assert s["converted"] == 2
    assert s["errors"] == 0
    assert (tmp_path / "a.flac").is_file()
    assert (d / "b.flac").is_file()

    r2 = client.post(
        "/api/convert-wav-bulk",
        json={
            "root_dir": str(tmp_path),
            "output": "same",
            "recursive": True,
            "skip_if_flac_exists": True,
        },
    )
    s2 = r2.get_json()["summary"]
    assert s2["converted"] == 0
    assert s2["skipped"] == 2


def test_parse_ableton_wav_stem(app_module):
    p = app_module.parse_ableton_style_wav_stem("A06 - 139 - Members Of Mayday - 10 In 01")
    assert p["matched"] is True
    assert p["artist"] == "Members Of Mayday"
    assert p["title"] == "10 In 01"


def test_parse_ableton_rekordbox_slot_key_bpm_strips(app_module):
    """Rekordbox flat exports: lead slot and trailing Camelot + BPM, not the hyphenated Ableton form."""
    s = "A02 Christian Loeffler All Comes (Mind Against Remix) 2A 120"
    p = app_module.parse_ableton_style_wav_stem(s)
    assert p["matched"] is False
    want = "Christian Loeffler All Comes (Mind Against Remix)"
    assert p["title"] == want
    assert p["loose"] == want

    s2 = "A02 Ripperton Unfold 2A 119"
    p2 = app_module.parse_ableton_style_wav_stem(s2)
    assert p2["title"] == "Ripperton Unfold"
    assert p2["loose"] == p2["title"]


def test_convert_wav_bulk_custom_flat_target(client, app_module, tmp_path):
    """All FLACs land in one folder; filename from Artist - Title when pattern matches."""
    try:
        src = tmp_path / "src"
        src.mkdir()
        w1 = src / "A01 - 128 - Test Artist - Test Title.wav"
        w2 = src / "B02 - 130 - Other - Another Song.wav"
        _write_minimal_wav(w1)
        _write_minimal_wav(w2)
    except (FileNotFoundError, subprocess.CalledProcessError):
        pytest.skip("ffmpeg not available")

    flat = tmp_path / "flat_out"
    flat.mkdir()

    r = client.post(
        "/api/convert-wav-bulk",
        json={
            "root_dir": str(src),
            "output": "custom",
            "target_dir": str(flat),
            "recursive": False,
            "skip_if_flac_exists": True,
        },
    )
    assert r.status_code == 200
    j = r.get_json()
    assert j.get("output") == "custom"
    assert j.get("target_dir")
    assert j["summary"]["converted"] == 2
    assert j["summary"]["errors"] == 0
    f1 = flat / "Test Artist - Test Title.flac"
    f2 = flat / "Other - Another Song.flac"
    assert f1.is_file()
    assert f2.is_file()
    t1 = FLAC(str(f1))
    t2 = FLAC(str(f2))
    assert t1["artist"] == ["Test Artist"]
    assert t1["title"] == ["Test Title"]
    assert t2["artist"] == ["Other"]
    assert t2["title"] == ["Another Song"]


def test_convert_wav_to_flac_embeds_tags_from_filename(client, app_module, tmp_path):
    try:
        wav = tmp_path / "A01 - 128 - Zip Kid - My Track.wav"
        _write_minimal_wav(wav)
    except (FileNotFoundError, subprocess.CalledProcessError):
        pytest.skip("ffmpeg not available")

    r = client.post(
        "/api/convert-wav-to-flac",
        json={"filepath": str(wav), "output": "same"},
    )
    assert r.status_code == 200
    flac_p = wav.with_suffix(".flac")
    assert flac_p.is_file()
    t = FLAC(str(flac_p))
    assert t["artist"] == ["Zip Kid"]
    assert t["title"] == ["My Track"]
    flac_p.unlink(missing_ok=True)


def test_convert_wav_bulk_respects_offset_limit(client, app_module, tmp_path):
    try:
        _write_minimal_wav(tmp_path / "z.wav")
        _write_minimal_wav(tmp_path / "a.wav")
    except (FileNotFoundError, subprocess.CalledProcessError):
        pytest.skip("ffmpeg not available")
    r = client.post(
        "/api/convert-wav-bulk",
        json={
            "root_dir": str(tmp_path),
            "output": "same",
            "recursive": False,
            "skip_if_flac_exists": False,
            "offset": 0,
            "limit": 1,
        },
    )
    assert r.status_code == 200
    j = r.get_json()
    assert (j.get("batch") or {}).get("total_wavs") == 2
    assert (j.get("batch") or {}).get("candidates_in_batch") == 1
    assert j["summary"]["converted"] == 1
    have_flac = sum(1 for p in tmp_path.iterdir() if p.suffix.lower() == ".flac")
    assert have_flac == 1


def test_convert_wav_bulk_requires_target_for_custom(client, app_module, tmp_path):
    r = client.post(
        "/api/convert-wav-bulk",
        json={
            "root_dir": str(tmp_path),
            "output": "custom",
            "skip_if_flac_exists": True,
        },
    )
    assert r.status_code == 400
    assert "target" in r.get_json().get("error", "").lower()
