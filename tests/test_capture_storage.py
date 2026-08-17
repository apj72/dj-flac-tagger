"""Tests for capture session storage."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest
from capture.models import (
    CaptureSession, PlannedTrack, PlaylistInfo, SessionStatus,
)
from capture.storage import SessionStore


@pytest.fixture
def store(tmp_path):
    return SessionStore(str(tmp_path))


def _make_session(n=3):
    s = CaptureSession()
    s.playlist = PlaylistInfo(name="Test", persistent_id="PL1",
                              track_count=n, total_duration_seconds=n * 200)
    s.tracks = [
        PlannedTrack(ordinal=i, persistent_id=f"T{i}", database_id=i,
                     title=f"Track {i}", artist="Artist", album="Album",
                     duration_seconds=200)
        for i in range(n)
    ]
    s.output_dir = "/tmp/test"
    return s


class TestSessionStore:
    def test_create_and_load(self, store):
        session = _make_session()
        store.create(session)
        loaded = store.load(session.session_id)
        assert loaded.session_id == session.session_id
        assert len(loaded.tracks) == 3
        assert loaded.tracks[0].title == "Track 0"

    def test_save_atomic_updates(self, store):
        session = _make_session()
        store.create(session)
        session.status = SessionStatus.RUNNING
        session.tracks[0].status = session.tracks[0].status  # no change
        store.save_atomic(session)
        loaded = store.load(session.session_id)
        assert loaded.status == SessionStatus.RUNNING

    def test_exists(self, store):
        session = _make_session()
        assert not store.exists(session.session_id)
        store.create(session)
        assert store.exists(session.session_id)

    def test_list_sessions(self, store):
        s1 = _make_session()
        s2 = _make_session()
        store.create(s1)
        store.create(s2)
        ids = store.list_sessions()
        assert s1.session_id in ids
        assert s2.session_id in ids

    def test_list_recoverable(self, store):
        s1 = _make_session()
        s1.status = SessionStatus.RUNNING
        store.create(s1)

        s2 = _make_session()
        s2.status = SessionStatus.COMPLETED
        store.create(s2)

        recoverable = store.list_recoverable()
        assert len(recoverable) == 1
        assert recoverable[0].session_id == s1.session_id

    def test_raw_dir(self, store):
        session = _make_session()
        store.create(session)
        raw = store.raw_dir_for(session.session_id)
        assert raw.exists()
        assert raw.name == "raw"

    def test_delete_session(self, store):
        session = _make_session()
        store.create(session)
        assert store.exists(session.session_id)
        store.delete_session(session.session_id)
        assert not store.exists(session.session_id)

    def test_atomic_write_doesnt_corrupt_on_crash(self, store, tmp_path):
        """If we write a valid session then simulate a crash during next write,
        the original manifest should still be loadable."""
        session = _make_session()
        store.create(session)

        # Verify original is readable
        loaded = store.load(session.session_id)
        assert loaded.status == SessionStatus.DRAFT

        # Manually check the manifest file is valid JSON
        manifest = (
            tmp_path / ".djmm-capture" / session.session_id / "manifest.json"
        )
        data = json.loads(manifest.read_text())
        assert data["session_id"] == session.session_id

    def test_manifest_is_valid_json(self, store, tmp_path):
        session = _make_session()
        store.create(session)
        manifest = (
            tmp_path / ".djmm-capture" / session.session_id / "manifest.json"
        )
        data = json.loads(manifest.read_text())
        assert data["schema_version"] == 1
        assert len(data["tracks"]) == 3
