"""Rename / delete source recordings on the Extract tab."""

import os

import pytest


def test_rename_source_recording_ok(client, tmp_path):
    (tmp_path / "obs.mkv").write_bytes(b"\x00")
    r = client.post(
        "/api/source-recording/rename",
        json={
            "filepath": str(tmp_path / "obs.mkv"),
            "base_dir": str(tmp_path),
            "new_stem": "Warmup 2024-03-01",
        },
    )
    assert r.status_code == 200
    data = r.get_json()
    assert data.get("name") == "Warmup 2024-03-01.mkv"
    assert os.path.isfile(data["path"])
    assert not (tmp_path / "obs.mkv").exists()


def test_rename_source_recording_conflict(client, tmp_path):
    (tmp_path / "a.mkv").write_bytes(b"a")
    (tmp_path / "b.mkv").write_bytes(b"b")
    r = client.post(
        "/api/source-recording/rename",
        json={
            "filepath": str(tmp_path / "a.mkv"),
            "base_dir": str(tmp_path),
            "new_stem": "b",
        },
    )
    assert r.status_code == 409


def test_rename_rejects_wrong_folder(client, tmp_path):
    sub = tmp_path / "inner"
    sub.mkdir()
    (sub / "x.mkv").write_bytes(b"x")
    r = client.post(
        "/api/source-recording/rename",
        json={
            "filepath": str(sub / "x.mkv"),
            "base_dir": str(tmp_path),
            "new_stem": "y",
        },
    )
    assert r.status_code == 400


def test_delete_source_recording_ok(client, app_module, tmp_path, monkeypatch):
    p = tmp_path / "bad.mkv"
    p.write_bytes(b"x")

    monkeypatch.setattr(app_module, "trash_file", lambda fp: os.remove(fp))

    r = client.post(
        "/api/source-recording/delete",
        json={"filepath": str(p), "base_dir": str(tmp_path)},
    )
    assert r.status_code == 200
    assert r.get_json().get("ok") is True
    assert not p.exists()
