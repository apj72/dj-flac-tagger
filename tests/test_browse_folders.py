"""Tests for /api/browse-folders (Fix Metadata folder picker)."""

import os

import pytest


def test_browse_folders_root_subdirs(client, app_module, tmp_path):
    (tmp_path / "Music").mkdir()
    (tmp_path / "FLACs").mkdir()
    (tmp_path / "hidden").mkdir()

    r = client.get(
        f"/api/browse-folders?path={str(tmp_path)}"
    )
    assert r.status_code == 200
    data = r.get_json()
    assert data["path"] == os.path.realpath(str(tmp_path))
    assert data.get("parent") is not None
    names = {x["name"] for x in data["directories"]}
    assert "Music" in names
    assert "FLACs" in names


def test_browse_folders_no_parent_at_filesystem_root(client, app_module):
    r = client.get("/api/browse-folders?path=/")
    if r.status_code != 200:
        pytest.skip("cannot list / in test environment")
    data = r.get_json()
    assert "path" in data
    assert data.get("parent") is None


def test_browse_folders_rejects_file(client, app_module, tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("x")
    r = client.get(f"/api/browse-folders?path={f}")
    assert r.status_code == 404


def test_browse_folders_missing_param(client, app_module):
    r = client.get("/api/browse-folders")
    assert r.status_code == 400
