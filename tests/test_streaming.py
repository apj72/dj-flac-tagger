"""Tests for NDJSON streaming progress on batch endpoints."""

import json

import pytest


class TestNormaliseBulkStream:
    def test_non_stream_still_works(self, client, app_module, tmp_path, monkeypatch):
        monkeypatch.setattr(app_module, "analyse_loudness", lambda fp: {"loudnorm_params": {
            "input_i": -20, "input_tp": -1, "input_lra": 7, "input_thresh": -30,
        }})
        monkeypatch.setattr(app_module, "_ffmpeg_loudnorm_encode", lambda *a, **kw: None)
        monkeypatch.setattr(app_module, "_copy_audio_tags_and_art", lambda *a: None)

        f = tmp_path / "test.flac"
        f.write_bytes(b"fake")

        r = client.post("/api/normalise-bulk", json={
            "files": [str(f)],
            "suffix": "_norm",
        }, content_type="application/json")
        assert r.status_code == 200
        j = r.get_json()
        assert "summary" in j

    def test_stream_returns_ndjson(self, client, app_module, tmp_path, monkeypatch):
        out_created = []

        def fake_encode(inp, outp, params, pk, **kw):
            import pathlib
            pathlib.Path(outp).write_bytes(b"fake output")
            out_created.append(outp)

        monkeypatch.setattr(app_module, "analyse_loudness", lambda fp: {"loudnorm_params": {
            "input_i": -20, "input_tp": -1, "input_lra": 7, "input_thresh": -30,
        }})
        monkeypatch.setattr(app_module, "_ffmpeg_loudnorm_encode", fake_encode)
        monkeypatch.setattr(app_module, "_copy_audio_tags_and_art", lambda *a: None)

        f = tmp_path / "test.flac"
        f.write_bytes(b"fake")

        r = client.post("/api/normalise-bulk", json={
            "files": [str(f)],
            "suffix": "_norm",
            "stream": True,
        }, content_type="application/json")
        assert r.status_code == 200
        assert r.content_type.startswith("application/x-ndjson")

        lines = [ln for ln in r.data.decode().strip().split("\n") if ln.strip()]
        assert len(lines) >= 2

        progress_msgs = [json.loads(ln) for ln in lines if json.loads(ln).get("type") == "progress"]
        assert len(progress_msgs) >= 1
        assert progress_msgs[0]["current"] == 1

        final = json.loads(lines[-1])
        assert final["type"] == "complete"
        assert final["summary"]["normalised"] == 1


class TestConvertWavBulkStream:
    def test_stream_returns_ndjson(self, client, app_module, tmp_path, monkeypatch):
        wav_dir = tmp_path / "wavs"
        wav_dir.mkdir()
        (wav_dir / "test.wav").write_bytes(b"RIFF" + b"\x00" * 100)

        def fake_convert(wav, flac):
            import pathlib
            pathlib.Path(flac).write_bytes(b"fLaC" + b"\x00" * 100)

        monkeypatch.setattr(app_module, "_ffmpeg_wav_to_flac_file", fake_convert)
        monkeypatch.setattr(app_module, "_embed_artist_title_tags_from_wav_stem", lambda *a: None)

        r = client.post("/api/convert-wav-bulk", json={
            "root_dir": str(wav_dir),
            "output": "same",
            "recursive": False,
            "stream": True,
        }, content_type="application/json")
        assert r.status_code == 200
        assert r.content_type.startswith("application/x-ndjson")

        lines = [ln for ln in r.data.decode().strip().split("\n") if ln.strip()]
        assert len(lines) >= 2

        final = json.loads(lines[-1])
        assert final["type"] == "complete"
        assert final["summary"]["converted"] == 1
