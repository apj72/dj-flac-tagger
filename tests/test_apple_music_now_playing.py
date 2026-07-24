import json
import subprocess
import sys
from datetime import datetime, timedelta

import pytest


# ---------------------------------------------------------------------------
# Helper: valid AppleScript JSON output
# ---------------------------------------------------------------------------

def _osascript_playing(
    title="Pump Up the Jam",
    artist="Technotronic",
    album="Pump Up the Jam: The Album",
    album_artist="Technotronic",
    genre="Dance",
    year="1989",
    composer="",
    duration=303.5,
    track_number=1,
    disc_number=1,
    persistent_id="ABCD1234",
    player_position=145.2,
    playback_state="playing",
):
    obj = {
        "playbackState": playback_state,
        "playerPosition": player_position,
        "persistentId": persistent_id,
        "title": title,
        "artist": artist,
        "album": album,
        "albumArtist": album_artist,
        "genre": genre,
        "year": year,
        "composer": composer,
        "duration": duration,
        "trackNumber": track_number,
        "discNumber": disc_number,
    }
    return json.dumps(obj)


# ---------------------------------------------------------------------------
# Persistence tests
# ---------------------------------------------------------------------------


def test_load_logged_tracks_empty(app_module):
    data = app_module.load_logged_tracks()
    assert data == {"schema_version": 1, "tracks": []}


def test_save_and_load_roundtrip(app_module):
    entry = {
        "id": "test-uuid-1",
        "source": "apple_music_now_playing",
        "capturedAt": "2026-07-14T20:00:00",
        "appleMusicPersistentId": "XYZ",
        "playbackState": "playing",
        "playerPosition": 10.0,
        "metadata": {"title": "Test", "artist": "Artist"},
    }
    data = {"schema_version": 1, "tracks": [entry]}
    app_module.save_logged_tracks(data)
    loaded = app_module.load_logged_tracks()
    assert loaded["schema_version"] == 1
    assert len(loaded["tracks"]) == 1
    assert loaded["tracks"][0]["id"] == "test-uuid-1"
    assert loaded["tracks"][0]["metadata"]["title"] == "Test"


def test_save_logged_tracks_atomic_cleanup(app_module, tmp_path):
    """On success the temp file should not linger."""
    import glob

    data = {"schema_version": 1, "tracks": []}
    app_module.save_logged_tracks(data)
    leftover = glob.glob(str(tmp_path / ".logged_tracks_*"))
    assert leftover == []


def test_load_logged_tracks_corrupt_file(app_module):
    with open(app_module.LOGGED_TRACKS_PATH, "w") as f:
        f.write("not json!")
    data = app_module.load_logged_tracks()
    assert data == {"schema_version": 1, "tracks": []}


def test_load_logged_tracks_missing_tracks_key(app_module):
    with open(app_module.LOGGED_TRACKS_PATH, "w") as f:
        json.dump({"schema_version": 1}, f)
    data = app_module.load_logged_tracks()
    assert data == {"schema_version": 1, "tracks": []}


# ---------------------------------------------------------------------------
# Capture function tests (monkeypatch _run_osascript)
# ---------------------------------------------------------------------------


def test_capture_playing_track(app_module, monkeypatch):
    monkeypatch.setattr(app_module, "sys", type(sys)("fakesys"))
    app_module.sys.platform = "darwin"
    stdout = _osascript_playing()
    monkeypatch.setattr(app_module, "_run_osascript", lambda s, timeout=10: (stdout, "", 0))

    entry = app_module.capture_apple_music_now_playing()
    assert entry["source"] == "apple_music_now_playing"
    assert entry["playbackState"] == "playing"
    assert entry["appleMusicPersistentId"] == "ABCD1234"
    assert entry["metadata"]["title"] == "Pump Up the Jam"
    assert entry["metadata"]["artist"] == "Technotronic"
    assert entry["metadata"]["album"] == "Pump Up the Jam: The Album"
    assert entry["metadata"]["duration"] == 303.5
    assert entry["metadata"]["trackNumber"] == 1
    assert entry["metadata"]["discNumber"] == 1
    assert entry["metadata"]["genre"] == "Dance"
    assert entry["metadata"]["year"] == "1989"
    assert entry["playerPosition"] == 145.2
    assert entry["id"]  # uuid present


def test_capture_paused_track(app_module, monkeypatch):
    monkeypatch.setattr(app_module, "sys", type(sys)("fakesys"))
    app_module.sys.platform = "darwin"
    stdout = _osascript_playing(playback_state="paused")
    monkeypatch.setattr(app_module, "_run_osascript", lambda s, timeout=10: (stdout, "", 0))

    entry = app_module.capture_apple_music_now_playing()
    assert entry["playbackState"] == "paused"
    assert entry["metadata"]["title"] == "Pump Up the Jam"


def test_capture_not_running(app_module, monkeypatch):
    monkeypatch.setattr(app_module, "sys", type(sys)("fakesys"))
    app_module.sys.platform = "darwin"
    monkeypatch.setattr(
        app_module, "_run_osascript",
        lambda s, timeout=10: ('{"error": "not_running"}', "", 0),
    )
    with pytest.raises(RuntimeError, match="not running"):
        app_module.capture_apple_music_now_playing()


def test_capture_nothing_playing(app_module, monkeypatch):
    monkeypatch.setattr(app_module, "sys", type(sys)("fakesys"))
    app_module.sys.platform = "darwin"
    monkeypatch.setattr(
        app_module, "_run_osascript",
        lambda s, timeout=10: ('{"error": "nothing_playing", "playbackState": "stopped"}', "", 0),
    )
    with pytest.raises(RuntimeError, match="Nothing is currently playing"):
        app_module.capture_apple_music_now_playing()


def test_capture_permission_denied(app_module, monkeypatch):
    monkeypatch.setattr(app_module, "sys", type(sys)("fakesys"))
    app_module.sys.platform = "darwin"
    monkeypatch.setattr(
        app_module, "_run_osascript",
        lambda s, timeout=10: ("", "execution error: Not authorized. (-1743)", 1),
    )
    with pytest.raises(PermissionError, match="Privacy & Security"):
        app_module.capture_apple_music_now_playing()


def test_capture_timeout(app_module, monkeypatch):
    monkeypatch.setattr(app_module, "sys", type(sys)("fakesys"))
    app_module.sys.platform = "darwin"

    def raise_timeout(s, timeout=10):
        raise subprocess.TimeoutExpired(cmd="osascript", timeout=timeout)

    monkeypatch.setattr(app_module, "_run_osascript", raise_timeout)
    with pytest.raises(RuntimeError, match="Timed out"):
        app_module.capture_apple_music_now_playing()


def test_capture_malformed_json(app_module, monkeypatch):
    monkeypatch.setattr(app_module, "sys", type(sys)("fakesys"))
    app_module.sys.platform = "darwin"
    monkeypatch.setattr(
        app_module, "_run_osascript",
        lambda s, timeout=10: ("this is not json", "", 0),
    )
    with pytest.raises(RuntimeError, match="Unexpected response"):
        app_module.capture_apple_music_now_playing()


def test_capture_empty_response(app_module, monkeypatch):
    monkeypatch.setattr(app_module, "sys", type(sys)("fakesys"))
    app_module.sys.platform = "darwin"
    monkeypatch.setattr(
        app_module, "_run_osascript",
        lambda s, timeout=10: ("", "", 0),
    )
    with pytest.raises(RuntimeError, match="No response"):
        app_module.capture_apple_music_now_playing()


def test_capture_missing_optional_fields(app_module, monkeypatch):
    monkeypatch.setattr(app_module, "sys", type(sys)("fakesys"))
    app_module.sys.platform = "darwin"
    minimal = json.dumps({
        "playbackState": "playing",
        "playerPosition": 0,
        "persistentId": "",
        "title": "Minimal Track",
        "artist": "",
        "album": "",
        "albumArtist": "",
        "genre": "",
        "year": "",
        "composer": "",
        "duration": 0,
        "trackNumber": 0,
        "discNumber": 0,
    })
    monkeypatch.setattr(app_module, "_run_osascript", lambda s, timeout=10: (minimal, "", 0))
    entry = app_module.capture_apple_music_now_playing()
    assert entry["metadata"]["title"] == "Minimal Track"
    assert entry["appleMusicPersistentId"] is None
    assert entry["metadata"]["trackNumber"] is None
    assert entry["metadata"]["discNumber"] is None


def test_capture_no_title_raises(app_module, monkeypatch):
    monkeypatch.setattr(app_module, "sys", type(sys)("fakesys"))
    app_module.sys.platform = "darwin"
    bad = json.dumps({
        "playbackState": "playing", "playerPosition": 0, "persistentId": "",
        "title": "", "artist": "", "album": "", "albumArtist": "",
        "genre": "", "year": "", "composer": "", "duration": 0,
        "trackNumber": 0, "discNumber": 0,
    })
    monkeypatch.setattr(app_module, "_run_osascript", lambda s, timeout=10: (bad, "", 0))
    with pytest.raises(RuntimeError, match="no title"):
        app_module.capture_apple_music_now_playing()


def test_capture_unicode_metadata(app_module, monkeypatch):
    monkeypatch.setattr(app_module, "sys", type(sys)("fakesys"))
    app_module.sys.platform = "darwin"
    stdout = _osascript_playing(
        title='Déjà Vu "Remix"',
        artist="Björk & René",
        album="Ålbum\twith\ttabs",
    )
    monkeypatch.setattr(app_module, "_run_osascript", lambda s, timeout=10: (stdout, "", 0))
    entry = app_module.capture_apple_music_now_playing()
    assert entry["metadata"]["title"] == 'Déjà Vu "Remix"'
    assert entry["metadata"]["artist"] == "Björk & René"
    assert "tabs" in entry["metadata"]["album"]


def test_capture_non_macos(app_module, monkeypatch):
    monkeypatch.setattr(app_module, "sys", type(sys)("fakesys"))
    app_module.sys.platform = "linux"
    with pytest.raises(RuntimeError, match="only available on macOS"):
        app_module.capture_apple_music_now_playing()


def test_capture_osascript_generic_error(app_module, monkeypatch):
    monkeypatch.setattr(app_module, "sys", type(sys)("fakesys"))
    app_module.sys.platform = "darwin"
    monkeypatch.setattr(
        app_module, "_run_osascript",
        lambda s, timeout=10: ("", "some weird error", 1),
    )
    with pytest.raises(RuntimeError, match="AppleScript error"):
        app_module.capture_apple_music_now_playing()


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------


def test_api_platform(client):
    r = client.get("/api/platform")
    assert r.status_code == 200
    data = r.get_json()
    assert "platform" in data


def test_api_now_playing_success(client, app_module, monkeypatch):
    stdout = _osascript_playing()
    monkeypatch.setattr(app_module, "_run_osascript", lambda s, timeout=10: (stdout, "", 0))

    r = client.post("/api/apple-music/now-playing")
    assert r.status_code == 200
    data = r.get_json()
    assert "track" in data
    assert data["track"]["metadata"]["title"] == "Pump Up the Jam"
    assert data.get("duplicate") is None

    # Verify it was persisted
    loaded = app_module.load_logged_tracks()
    assert len(loaded["tracks"]) == 1
    assert loaded["tracks"][0]["id"] == data["track"]["id"]


def test_api_now_playing_duplicate_detection(client, app_module, monkeypatch):
    stdout = _osascript_playing()
    monkeypatch.setattr(app_module, "_run_osascript", lambda s, timeout=10: (stdout, "", 0))

    r1 = client.post("/api/apple-music/now-playing")
    assert r1.status_code == 200

    r2 = client.post("/api/apple-music/now-playing")
    assert r2.status_code == 200
    data2 = r2.get_json()
    assert data2.get("duplicate") is True

    loaded = app_module.load_logged_tracks()
    assert len(loaded["tracks"]) == 1


def test_api_now_playing_different_tracks_not_duplicate(client, app_module, monkeypatch):
    call_count = [0]

    def mock_osascript(s, timeout=10):
        call_count[0] += 1
        if call_count[0] == 1:
            return (_osascript_playing(persistent_id="AAA"), "", 0)
        return (_osascript_playing(persistent_id="BBB", title="Other Track"), "", 0)

    monkeypatch.setattr(app_module, "_run_osascript", mock_osascript)

    r1 = client.post("/api/apple-music/now-playing")
    assert r1.status_code == 200

    r2 = client.post("/api/apple-music/now-playing")
    assert r2.status_code == 200
    assert r2.get_json().get("duplicate") is None

    loaded = app_module.load_logged_tracks()
    assert len(loaded["tracks"]) == 2


def test_api_now_playing_error_returns_400(client, app_module, monkeypatch):
    monkeypatch.setattr(
        app_module, "_run_osascript",
        lambda s, timeout=10: ('{"error": "not_running"}', "", 0),
    )
    r = client.post("/api/apple-music/now-playing")
    assert r.status_code == 400
    assert "error" in r.get_json()


def test_api_now_playing_permission_returns_403(client, app_module, monkeypatch):
    monkeypatch.setattr(
        app_module, "_run_osascript",
        lambda s, timeout=10: ("", "(-1743)", 1),
    )
    r = client.post("/api/apple-music/now-playing")
    assert r.status_code == 403
    assert "Privacy" in r.get_json()["error"]


def test_api_now_playing_non_macos_returns_501(client, app_module, monkeypatch):
    monkeypatch.setattr(app_module, "sys", type(sys)("fakesys"))
    app_module.sys.platform = "linux"
    r = client.post("/api/apple-music/now-playing")
    assert r.status_code == 501


def test_api_get_logged_tracks_empty(client):
    r = client.get("/api/logged-tracks")
    assert r.status_code == 200
    data = r.get_json()
    assert data["tracks"] == []


def test_api_get_logged_tracks_with_entries(client, app_module):
    entry = {
        "id": "uuid-1",
        "source": "apple_music_now_playing",
        "capturedAt": datetime.now().isoformat(),
        "metadata": {"title": "Test", "artist": "A"},
    }
    app_module.save_logged_tracks({"schema_version": 1, "tracks": [entry]})

    r = client.get("/api/logged-tracks")
    data = r.get_json()
    assert len(data["tracks"]) == 1
    assert data["tracks"][0]["id"] == "uuid-1"


def test_api_delete_logged_track(client, app_module):
    entries = [
        {"id": "uuid-1", "metadata": {"title": "A"}},
        {"id": "uuid-2", "metadata": {"title": "B"}},
    ]
    app_module.save_logged_tracks({"schema_version": 1, "tracks": entries})

    r = client.delete("/api/logged-tracks/uuid-1")
    assert r.status_code == 200
    assert r.get_json()["ok"] is True

    loaded = app_module.load_logged_tracks()
    assert len(loaded["tracks"]) == 1
    assert loaded["tracks"][0]["id"] == "uuid-2"


def test_api_delete_logged_track_not_found(client, app_module):
    app_module.save_logged_tracks({"schema_version": 1, "tracks": []})
    r = client.delete("/api/logged-tracks/nonexistent")
    assert r.status_code == 404


def test_api_clear_logged_tracks(client, app_module):
    entries = [
        {"id": "uuid-1", "metadata": {"title": "A"}},
        {"id": "uuid-2", "metadata": {"title": "B"}},
    ]
    app_module.save_logged_tracks({"schema_version": 1, "tracks": entries})

    r = client.delete("/api/logged-tracks")
    assert r.status_code == 200

    loaded = app_module.load_logged_tracks()
    assert loaded["tracks"] == []


# ---------------------------------------------------------------------------
# Same persistent ID captured more than once
# ---------------------------------------------------------------------------


def test_two_captures_same_persistent_id_different_times(client, app_module, monkeypatch):
    """Captures >30s apart with the same persistent ID should both be stored."""
    first_entry = {
        "id": "old-uuid",
        "source": "apple_music_now_playing",
        "capturedAt": (datetime.now() - timedelta(minutes=5)).isoformat(),
        "appleMusicPersistentId": "ABCD1234",
        "metadata": {"title": "Track"},
    }
    app_module.save_logged_tracks({"schema_version": 1, "tracks": [first_entry]})

    stdout = _osascript_playing(persistent_id="ABCD1234")
    monkeypatch.setattr(app_module, "_run_osascript", lambda s, timeout=10: (stdout, "", 0))

    r = client.post("/api/apple-music/now-playing")
    assert r.status_code == 200
    assert r.get_json().get("duplicate") is None

    loaded = app_module.load_logged_tracks()
    assert len(loaded["tracks"]) == 2
    ids = [t["id"] for t in loaded["tracks"]]
    assert "old-uuid" in ids


# ---------------------------------------------------------------------------
# Extract integration tests
# ---------------------------------------------------------------------------


@pytest.fixture
def _stub_extract(app_module, monkeypatch, tmp_path):
    """Minimal stubs so /api/extract succeeds without real ffmpeg."""
    import shutil as sh

    # Create a tiny valid FLAC via ffmpeg (skip if unavailable)
    src = tmp_path / "test.mkv"
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=0.05",
             "-c:a", "flac", str(src)],
            capture_output=True, check=True, timeout=10,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        pytest.skip("ffmpeg not available")

    # Point config at tmp_path
    cfg = app_module.load_config()
    cfg["source_dir"] = str(tmp_path)
    cfg["destination_dir"] = str(tmp_path / "dest")
    app_module.save_config(cfg)

    return str(src)


def test_extract_with_logged_track_id_removes_entry(client, app_module, _stub_extract):
    entry = {
        "id": "lt-to-remove",
        "source": "apple_music_now_playing",
        "capturedAt": datetime.now().isoformat(),
        "appleMusicPersistentId": "X",
        "metadata": {"title": "Track"},
    }
    app_module.save_logged_tracks({"schema_version": 1, "tracks": [entry]})

    r = client.post("/api/extract", json={
        "filepath": _stub_extract,
        "metadata": {"title": "ExtractTest"},
        "artwork_url": "",
        "metadata_source_url": "",
        "logged_track_id": "lt-to-remove",
    })
    assert r.status_code == 200
    data = r.get_json()
    assert data.get("error") is None
    assert data["logged_track_removed"] is True

    loaded = app_module.load_logged_tracks()
    assert len(loaded["tracks"]) == 0


def test_extract_without_logged_track_id_leaves_file(client, app_module, _stub_extract):
    entry = {
        "id": "lt-stays",
        "source": "apple_music_now_playing",
        "capturedAt": datetime.now().isoformat(),
        "metadata": {"title": "Stays"},
    }
    app_module.save_logged_tracks({"schema_version": 1, "tracks": [entry]})

    r = client.post("/api/extract", json={
        "filepath": _stub_extract,
        "metadata": {"title": "ExtractTest2"},
        "artwork_url": "",
        "metadata_source_url": "",
    })
    assert r.status_code == 200
    data = r.get_json()
    assert data["logged_track_removed"] is False

    loaded = app_module.load_logged_tracks()
    assert len(loaded["tracks"]) == 1


def test_extract_failure_retains_logged_track(client, app_module, tmp_path):
    entry = {
        "id": "lt-keep",
        "source": "apple_music_now_playing",
        "capturedAt": datetime.now().isoformat(),
        "metadata": {"title": "Keep"},
    }
    app_module.save_logged_tracks({"schema_version": 1, "tracks": [entry]})

    r = client.post("/api/extract", json={
        "filepath": str(tmp_path / "nonexistent.mkv"),
        "metadata": {"title": "Fail"},
        "artwork_url": "",
        "metadata_source_url": "",
        "logged_track_id": "lt-keep",
    })
    assert r.status_code == 404

    loaded = app_module.load_logged_tracks()
    assert len(loaded["tracks"]) == 1
    assert loaded["tracks"][0]["id"] == "lt-keep"


def test_extract_removes_correct_entry_among_duplicates(client, app_module, _stub_extract):
    """Two entries with the same persistent ID — only the one matched by UUID is removed."""
    entries = [
        {
            "id": "lt-1",
            "source": "apple_music_now_playing",
            "capturedAt": datetime.now().isoformat(),
            "appleMusicPersistentId": "SAME",
            "metadata": {"title": "First capture"},
        },
        {
            "id": "lt-2",
            "source": "apple_music_now_playing",
            "capturedAt": datetime.now().isoformat(),
            "appleMusicPersistentId": "SAME",
            "metadata": {"title": "Second capture"},
        },
    ]
    app_module.save_logged_tracks({"schema_version": 1, "tracks": entries})

    r = client.post("/api/extract", json={
        "filepath": _stub_extract,
        "metadata": {"title": "ExtractDup"},
        "artwork_url": "",
        "metadata_source_url": "",
        "logged_track_id": "lt-1",
    })
    assert r.status_code == 200
    assert r.get_json()["logged_track_removed"] is True

    loaded = app_module.load_logged_tracks()
    assert len(loaded["tracks"]) == 1
    assert loaded["tracks"][0]["id"] == "lt-2"
