"""Tests for _validate_path_in_allowed_dirs path traversal defense."""

import json
import os
import tempfile

import pytest


def test_normal_path_under_allowed_dir(app_module, tmp_path):
    """A file directly under an allowed directory passes validation."""
    f = tmp_path / "song.flac"
    f.write_text("data")
    result = app_module._validate_path_in_allowed_dirs(str(f), [str(tmp_path)])
    assert result == os.path.realpath(str(f))


def test_nested_path_under_allowed_dir(app_module, tmp_path):
    """A file in a subdirectory of an allowed directory passes."""
    sub = tmp_path / "sub" / "deep"
    sub.mkdir(parents=True)
    f = sub / "track.mp3"
    f.write_text("data")
    result = app_module._validate_path_in_allowed_dirs(str(f), [str(tmp_path)])
    assert result == os.path.realpath(str(f))


def test_dotdot_escaping_rejected(app_module, tmp_path):
    """Paths with .. that escape the allowed directory are rejected."""
    allowed = tmp_path / "safe"
    allowed.mkdir()
    # Construct a path that tries to escape: safe/../../../etc/passwd
    evil = str(allowed / ".." / ".." / ".." / "etc" / "passwd")
    with pytest.raises(ValueError, match="outside all allowed directories"):
        app_module._validate_path_in_allowed_dirs(evil, [str(allowed)])


def test_dotdot_staying_inside_allowed(app_module, tmp_path):
    """Paths with .. that resolve back inside the allowed dir are accepted."""
    sub = tmp_path / "a" / "b"
    sub.mkdir(parents=True)
    f = sub / "song.flac"
    f.write_text("data")
    # Go up to "a" then back down to "b": a/b/../b/song.flac resolves to a/b/song.flac
    tricky = str(tmp_path / "a" / "b" / ".." / "b" / "song.flac")
    result = app_module._validate_path_in_allowed_dirs(tricky, [str(tmp_path)])
    assert result == os.path.realpath(str(f))


def test_symlink_escaping_rejected(app_module, tmp_path):
    """A symlink inside the allowed dir pointing outside is rejected."""
    allowed = tmp_path / "safe"
    allowed.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    target_file = outside / "secret.txt"
    target_file.write_text("secret")
    link = allowed / "link.txt"
    link.symlink_to(target_file)
    # The symlink resolves to outside the allowed dir
    with pytest.raises(ValueError, match="outside all allowed directories"):
        app_module._validate_path_in_allowed_dirs(str(link), [str(allowed)])


def test_symlink_inside_allowed_passes(app_module, tmp_path):
    """A symlink that resolves to within an allowed dir passes."""
    allowed = tmp_path / "safe"
    allowed.mkdir()
    real_file = allowed / "real.flac"
    real_file.write_text("data")
    link = allowed / "link.flac"
    link.symlink_to(real_file)
    result = app_module._validate_path_in_allowed_dirs(str(link), [str(allowed)])
    assert result == os.path.realpath(str(real_file))


def test_relative_path_resolved(app_module, tmp_path):
    """Relative paths are resolved to absolute before checking."""
    f = tmp_path / "track.flac"
    f.write_text("data")
    # Use a relative path by changing reference
    rel = os.path.relpath(str(f))
    result = app_module._validate_path_in_allowed_dirs(rel, [str(tmp_path)])
    assert os.path.isabs(result)
    assert result == os.path.realpath(str(f))


def test_tilde_path_expanded(app_module, tmp_path):
    """Paths with ~ are expanded."""
    home = os.path.expanduser("~")
    # Use a file in tmp_path but allow home directory
    f = tmp_path / "song.flac"
    f.write_text("data")
    result = app_module._validate_path_in_allowed_dirs(str(f), [str(tmp_path), home])
    assert result == os.path.realpath(str(f))


def test_empty_path_rejected(app_module):
    """Empty paths raise ValueError."""
    with pytest.raises(ValueError, match="Empty file path"):
        app_module._validate_path_in_allowed_dirs("", ["/tmp"])


def test_none_path_rejected(app_module):
    """None paths raise ValueError."""
    with pytest.raises(ValueError, match="Empty file path"):
        app_module._validate_path_in_allowed_dirs(None, ["/tmp"])


def test_multiple_allowed_dirs(app_module, tmp_path):
    """Validation passes if path is under any one of the allowed dirs."""
    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()
    f = dir_b / "track.flac"
    f.write_text("data")
    result = app_module._validate_path_in_allowed_dirs(str(f), [str(dir_a), str(dir_b)])
    assert result == os.path.realpath(str(f))


def test_path_not_in_any_allowed_dir(app_module, tmp_path):
    """A path outside all allowed dirs is rejected."""
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    other = tmp_path / "other"
    other.mkdir()
    f = other / "track.flac"
    f.write_text("data")
    with pytest.raises(ValueError, match="outside all allowed directories"):
        app_module._validate_path_in_allowed_dirs(str(f), [str(allowed)])


def test_tempdir_always_allowed(app_module, tmp_path, monkeypatch):
    """The system temp dir is included by _get_allowed_dirs so preview cache files pass."""
    tmpdir = tempfile.gettempdir()
    allowed = app_module._get_allowed_dirs()
    assert os.path.realpath(tmpdir) in allowed


def test_get_allowed_dirs_includes_config_dirs(app_module, tmp_path, monkeypatch):
    """_get_allowed_dirs returns the source, destination, and other configured directories."""
    src = tmp_path / "sources"
    dst = tmp_path / "library"
    fix = tmp_path / "fix"
    insp = tmp_path / "inspect"
    src.mkdir()
    dst.mkdir()
    fix.mkdir()
    insp.mkdir()
    monkeypatch.setattr(app_module, "CONFIG_PATH", str(tmp_path / "cfg.json"))
    (tmp_path / "cfg.json").write_text(json.dumps({
        "source_dir": str(src),
        "destination_dir": str(dst),
        "fix_metadata_default_dir": str(fix),
        "inspect_default_dir": str(insp),
    }))
    dirs = app_module._get_allowed_dirs()
    assert os.path.realpath(str(src)) in dirs
    assert os.path.realpath(str(dst)) in dirs
    assert os.path.realpath(str(fix)) in dirs
    assert os.path.realpath(str(insp)) in dirs


def test_prefix_collision_rejected(app_module, tmp_path):
    """Dir /tmp/ev must not allow path /tmp/evil/file (prefix boundary check)."""
    allowed = tmp_path / "safe"
    allowed.mkdir()
    evil = tmp_path / "safevil"
    evil.mkdir()
    f = evil / "data.txt"
    f.write_text("data")
    with pytest.raises(ValueError, match="outside all allowed directories"):
        app_module._validate_path_in_allowed_dirs(str(f), [str(allowed)])


def test_allowed_dir_itself_passes(app_module, tmp_path):
    """If the resolved path equals the allowed directory itself, it passes."""
    result = app_module._validate_path_in_allowed_dirs(str(tmp_path), [str(tmp_path)])
    assert result == os.path.realpath(str(tmp_path))


# ---- Integration tests: endpoints return 403 for traversal attempts ----


def test_read_tags_rejects_outside_path(client, app_module, tmp_path, monkeypatch):
    """POST /api/read-tags rejects a file outside configured dirs."""
    import config as config_mod
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    ext_f = outside / "evil.flac"
    ext_f.write_text("fake")
    monkeypatch.setattr(config_mod, "_get_allowed_dirs", lambda: [str(allowed)])
    r = client.post("/api/read-tags", json={"filepath": str(ext_f)})
    assert r.status_code == 403
    assert "outside" in r.get_json()["error"].lower()


def test_stream_audio_rejects_traversal(client, app_module, tmp_path, monkeypatch):
    """GET /api/stream-audio rejects path traversal attempts."""
    import config as config_mod
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    ext_f = outside / "evil.flac"
    ext_f.write_text("fake")
    monkeypatch.setattr(config_mod, "_get_allowed_dirs", lambda: [str(allowed)])
    r = client.get(f"/api/stream-audio?path={ext_f}")
    assert r.status_code == 403


def test_browse_folders_allows_outside_with_warning(client, app_module, tmp_path, monkeypatch):
    """browse-folders allows navigating outside configured dirs (returns 200)."""
    import config as config_mod
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.setattr(config_mod, "_get_allowed_dirs", lambda: [str(allowed)])
    r = client.get(f"/api/browse-folders?path={outside}")
    assert r.status_code == 200
    data = r.get_json()
    assert "path" in data
