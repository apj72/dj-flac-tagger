"""Deterministic orchestration tests for the capture manager.

Uses fake MusicController and RecorderBackend to test the capture loop
without real Music.app, BlackHole, or OBS.
"""

import os
import sys
import time
import threading
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest
from capture.models import (
    CaptureSession, PlannedTrack, PlaylistInfo, SavedMusicState,
    SessionStatus, TrackStatus,
)
from capture.storage import SessionStore
from capture.manager import CaptureManager
from capture.backends.base import (
    RecorderBackend, BackendStatus, RawRecording, SignalState,
)
from capture.music import MusicController, MusicError, PlaybackState


# ---------------------------------------------------------------------------
# Fake services
# ---------------------------------------------------------------------------

class FakeMusicController(MusicController):
    """Simulates Music.app without real AppleScript."""

    def __init__(self, default_play_duration=0.3):
        self._state = "stopped"
        self._position = 0.0
        self._current_pid = ""
        self._playing_track_duration = 0.0
        self._default_play_duration = default_play_duration
        self._play_start_time = 0.0
        self._shuffle = False
        self._repeat = "off"
        self._tracks_played: list[str] = []
        self._fail_play = False
        self._fail_resolve = False
        self._stall_at: float | None = None

    def check_permission(self) -> bool:
        return True

    def is_running(self) -> bool:
        return True

    def player_state(self) -> str:
        if self._state == "playing":
            elapsed = time.monotonic() - self._play_start_time
            if elapsed >= self._playing_track_duration:
                self._state = "stopped"
                self._position = self._playing_track_duration
        return self._state

    def get_playback(self) -> PlaybackState:
        state = self.player_state()
        if state == "playing":
            elapsed = time.monotonic() - self._play_start_time
            if self._stall_at is not None and elapsed > self._stall_at:
                self._position = self._stall_at
            else:
                self._position = elapsed
        return PlaybackState(
            state=state,
            position=self._position,
            current_track_pid=self._current_pid,
        )

    def list_playlists(self):
        return [PlaylistInfo(name="Fake", persistent_id="PL1",
                             track_count=3, total_duration_seconds=30)]

    def snapshot_playlist(self, playlist_persistent_id):
        return []

    def resolve_track(self, playlist_pid, track_pid) -> bool:
        if self._fail_resolve:
            return False
        return True

    def play_once(self, playlist_pid, track_pid):
        if self._fail_play:
            raise MusicError("Simulated play failure")
        self._state = "playing"
        self._current_pid = track_pid
        self._play_start_time = time.monotonic()
        self._playing_track_duration = self._default_play_duration
        self._tracks_played.append(track_pid)

    def stop(self):
        self._state = "stopped"

    def pause(self):
        self._state = "paused"

    def save_settings(self) -> SavedMusicState:
        return SavedMusicState(shuffle=self._shuffle, repeat=self._repeat)

    def apply_capture_settings(self):
        self._shuffle = False
        self._repeat = "off"

    def restore_settings(self, saved: SavedMusicState):
        self._shuffle = saved.shuffle
        self._repeat = saved.repeat


class FakeRecorderBackend(RecorderBackend):
    """Simulates a recording backend that creates real files."""

    def __init__(self):
        self._status = BackendStatus.IDLE
        self._output_path = ""
        self._fail_arm = False
        self._fail_stop = False

    def preflight(self, config):
        return True, []

    def arm(self, output_path, config) -> bool:
        if self._fail_arm:
            self._status = BackendStatus.FAILED
            return False
        self._output_path = output_path
        self._status = BackendStatus.ACTIVE
        # Create a minimal FLAC file (just enough to exist)
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(b"\x00" * 100)
        return True

    def status(self) -> BackendStatus:
        return self._status

    def signal(self) -> SignalState:
        if self._status == BackendStatus.ACTIVE:
            return SignalState(has_signal=True, left_db=-20, right_db=-20)
        return SignalState()

    def stop(self) -> RawRecording | None:
        if self._fail_stop:
            self._status = BackendStatus.FAILED
            return None
        self._status = BackendStatus.IDLE
        return RawRecording(
            path=self._output_path,
            duration_seconds=10.0,
            sample_rate=48000,
            channels=2,
            codec="flac",
        )

    def abort(self):
        self._status = BackendStatus.IDLE

    def cleanup(self):
        self._status = BackendStatus.IDLE


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tracks(n=3, duration=5.0):
    return [
        PlannedTrack(
            ordinal=i, persistent_id=f"T{i:04d}", database_id=i + 100,
            title=f"Track {i}", artist=f"Artist {i}", album="Test Album",
            duration_seconds=duration,
        )
        for i in range(n)
    ]


def _make_playlist():
    return PlaylistInfo(name="Test Playlist", persistent_id="PL1",
                        track_count=3, total_duration_seconds=15)


@pytest.fixture
def store(tmp_path):
    return SessionStore(str(tmp_path))


@pytest.fixture
def output_dir(tmp_path):
    d = tmp_path / "output"
    d.mkdir()
    return str(d)


# ---------------------------------------------------------------------------
# Orchestration tests
# ---------------------------------------------------------------------------

class TestNormalCompletion:
    """Phase 1 exit gate: normal three-track session completes."""

    def test_three_tracks_complete(self, store, output_dir):
        music = FakeMusicController()
        backend = FakeRecorderBackend()
        config = {"capture": {
            "pre_roll_ms": 10,
            "post_roll_ms": 10,
            "music_poll_ms": 50,
            "play_start_timeout_s": 5,
            "playback_stall_timeout_s": 5,
            "duration_grace_s": 10,
            "disk_reserve_gb": 0,
        }}
        manager = CaptureManager(store, music, backend, config)

        tracks = _make_tracks(3, duration=0.5)
        session = manager.create_session(
            _make_playlist(), tracks, output_dir=output_dir,
        )
        session.transition(SessionStatus.PREFLIGHTING)
        session.transition(SessionStatus.READY)
        store.save_atomic(session)

        # Mock verify and tagging since we don't have real FLAC files
        with patch("capture.processing.verify_flac24") as mock_verify, \
             patch("capture.processing.apply_capture_tags") as mock_tags, \
             patch("capture.processing.resolve_output_path") as mock_path:

            mock_verify.return_value = type("V", (), {
                "ok": True,
                "facts": type("F", (), {"duration": 0.5})(),
                "issues": [],
            })()

            call_count = [0]
            def fake_resolve(d, artist, title):
                call_count[0] += 1
                return os.path.join(d, f"{artist} - {title}.flac")
            mock_path.side_effect = fake_resolve

            sid = manager.start_session()
            # Wait for worker to finish
            manager._worker.join(timeout=30)

        loaded = store.load(sid)
        assert loaded.status == SessionStatus.COMPLETED
        assert loaded.completed_count == 3
        assert loaded.failed_count == 0
        assert len(music._tracks_played) == 3
        assert music._tracks_played == ["T0000", "T0001", "T0002"]

    def test_recorder_armed_before_play(self, store, output_dir):
        """Invariant: recorder must be active before Music plays."""
        music = FakeMusicController()
        backend = FakeRecorderBackend()
        config = {"capture": {
            "pre_roll_ms": 10,
            "post_roll_ms": 10,
            "music_poll_ms": 50,
            "play_start_timeout_s": 5,
            "playback_stall_timeout_s": 5,
            "duration_grace_s": 10,
            "disk_reserve_gb": 0,
        }}
        manager = CaptureManager(store, music, backend, config)

        arm_times = []
        play_times = []

        orig_arm = backend.arm
        def tracked_arm(path, cfg):
            arm_times.append(time.monotonic())
            return orig_arm(path, cfg)
        backend.arm = tracked_arm

        orig_play = music.play_once
        def tracked_play(plid, tpid):
            play_times.append(time.monotonic())
            return orig_play(plid, tpid)
        music.play_once = tracked_play

        tracks = _make_tracks(1, duration=0.3)
        session = manager.create_session(
            _make_playlist(), tracks, output_dir=output_dir,
        )
        session.transition(SessionStatus.PREFLIGHTING)
        session.transition(SessionStatus.READY)
        store.save_atomic(session)

        with patch("capture.processing.verify_flac24") as mock_v, \
             patch("capture.processing.apply_capture_tags"), \
             patch("capture.processing.resolve_output_path") as mock_p:
            mock_v.return_value = type("V", (), {
                "ok": True, "facts": None, "issues": []
            })()
            mock_p.side_effect = lambda d, a, t: os.path.join(d, f"{a}-{t}.flac")
            manager.start_session()
            manager._worker.join(timeout=15)

        assert len(arm_times) == 1
        assert len(play_times) == 1
        assert arm_times[0] < play_times[0], \
            "Recorder must be armed BEFORE Music plays"


class TestFailureAndRetry:

    def test_play_failure_marks_track_failed(self, store, output_dir):
        music = FakeMusicController()
        music._fail_play = True
        backend = FakeRecorderBackend()
        config = {"capture": {
            "pre_roll_ms": 10, "post_roll_ms": 10, "music_poll_ms": 50,
            "play_start_timeout_s": 2, "playback_stall_timeout_s": 2,
            "duration_grace_s": 5, "disk_reserve_gb": 0,
        }}
        manager = CaptureManager(store, music, backend, config)

        tracks = _make_tracks(1, duration=0.5)
        session = manager.create_session(
            _make_playlist(), tracks, output_dir=output_dir,
        )
        session.transition(SessionStatus.PREFLIGHTING)
        session.transition(SessionStatus.READY)
        store.save_atomic(session)

        with patch("capture.processing.verify_flac24"), \
             patch("capture.processing.apply_capture_tags"), \
             patch("capture.processing.resolve_output_path"):
            manager.start_session()
            manager._worker.join(timeout=15)

        loaded = store.load(session.session_id)
        assert loaded.tracks[0].status == TrackStatus.FAILED
        assert "play" in loaded.tracks[0].error.lower()

    def test_track_resolve_failure(self, store, output_dir):
        music = FakeMusicController()
        music._fail_resolve = True
        backend = FakeRecorderBackend()
        config = {"capture": {
            "pre_roll_ms": 10, "post_roll_ms": 10, "music_poll_ms": 50,
            "play_start_timeout_s": 2, "playback_stall_timeout_s": 2,
            "duration_grace_s": 5, "disk_reserve_gb": 0,
        }}
        manager = CaptureManager(store, music, backend, config)

        tracks = _make_tracks(1, duration=0.5)
        session = manager.create_session(
            _make_playlist(), tracks, output_dir=output_dir,
        )
        session.transition(SessionStatus.PREFLIGHTING)
        session.transition(SessionStatus.READY)
        store.save_atomic(session)

        with patch("capture.processing.verify_flac24"), \
             patch("capture.processing.apply_capture_tags"), \
             patch("capture.processing.resolve_output_path"):
            manager.start_session()
            manager._worker.join(timeout=15)

        loaded = store.load(session.session_id)
        assert loaded.tracks[0].status == TrackStatus.FAILED
        assert "not found" in loaded.tracks[0].error.lower()

    def test_arm_failure(self, store, output_dir):
        music = FakeMusicController()
        backend = FakeRecorderBackend()
        backend._fail_arm = True
        config = {"capture": {
            "pre_roll_ms": 10, "post_roll_ms": 10, "music_poll_ms": 50,
            "play_start_timeout_s": 2, "playback_stall_timeout_s": 2,
            "duration_grace_s": 5, "disk_reserve_gb": 0,
        }}
        manager = CaptureManager(store, music, backend, config)

        tracks = _make_tracks(1, duration=0.5)
        session = manager.create_session(
            _make_playlist(), tracks, output_dir=output_dir,
        )
        session.transition(SessionStatus.PREFLIGHTING)
        session.transition(SessionStatus.READY)
        store.save_atomic(session)

        with patch("capture.processing.verify_flac24"), \
             patch("capture.processing.apply_capture_tags"), \
             patch("capture.processing.resolve_output_path"):
            manager.start_session()
            manager._worker.join(timeout=15)

        loaded = store.load(session.session_id)
        assert loaded.tracks[0].status == TrackStatus.FAILED
        assert "arm" in loaded.tracks[0].error.lower()


class TestPauseAndStop:

    def test_pause_after_track(self, store, output_dir):
        music = FakeMusicController()
        backend = FakeRecorderBackend()
        config = {"capture": {
            "pre_roll_ms": 10, "post_roll_ms": 10, "music_poll_ms": 50,
            "play_start_timeout_s": 5, "playback_stall_timeout_s": 5,
            "duration_grace_s": 10, "disk_reserve_gb": 0,
        }}
        manager = CaptureManager(store, music, backend, config)

        tracks = _make_tracks(3, duration=0.3)
        session = manager.create_session(
            _make_playlist(), tracks, output_dir=output_dir,
        )
        session.transition(SessionStatus.PREFLIGHTING)
        session.transition(SessionStatus.READY)
        store.save_atomic(session)

        with patch("capture.processing.verify_flac24") as mock_v, \
             patch("capture.processing.apply_capture_tags"), \
             patch("capture.processing.resolve_output_path") as mock_p:
            mock_v.return_value = type("V", (), {
                "ok": True, "facts": None, "issues": []
            })()
            mock_p.side_effect = lambda d, a, t: os.path.join(d, f"{a}-{t}.flac")

            manager.start_session()
            # Signal pause after a short delay
            time.sleep(0.1)
            manager.pause_after_track()
            manager._worker.join(timeout=15)

        loaded = store.load(session.session_id)
        assert loaded.status == SessionStatus.PAUSED
        assert loaded.completed_count >= 1
        assert loaded.pending_count >= 1

    def test_stop_after_track(self, store, output_dir):
        music = FakeMusicController()
        backend = FakeRecorderBackend()
        config = {"capture": {
            "pre_roll_ms": 10, "post_roll_ms": 10, "music_poll_ms": 50,
            "play_start_timeout_s": 5, "playback_stall_timeout_s": 5,
            "duration_grace_s": 10, "disk_reserve_gb": 0,
        }}
        manager = CaptureManager(store, music, backend, config)

        tracks = _make_tracks(3, duration=0.3)
        session = manager.create_session(
            _make_playlist(), tracks, output_dir=output_dir,
        )
        session.transition(SessionStatus.PREFLIGHTING)
        session.transition(SessionStatus.READY)
        store.save_atomic(session)

        with patch("capture.processing.verify_flac24") as mock_v, \
             patch("capture.processing.apply_capture_tags"), \
             patch("capture.processing.resolve_output_path") as mock_p:
            mock_v.return_value = type("V", (), {
                "ok": True, "facts": None, "issues": []
            })()
            mock_p.side_effect = lambda d, a, t: os.path.join(d, f"{a}-{t}.flac")

            manager.start_session()
            time.sleep(0.1)
            manager.stop_after_track()
            manager._worker.join(timeout=15)

        loaded = store.load(session.session_id)
        assert loaded.status == SessionStatus.COMPLETED


class TestRecovery:

    def test_recover_interrupted_session(self, store, output_dir):
        """Simulate app restart: session was running, now we recover."""
        # Create a session that was "running" when the app crashed
        tracks = _make_tracks(3, duration=0.5)
        tracks[0].status = TrackStatus.COMPLETED
        tracks[1].status = TrackStatus.RECORDING  # was mid-capture
        session = CaptureSession()
        session.status = SessionStatus.RUNNING
        session.playlist = _make_playlist()
        session.tracks = tracks
        session.output_dir = output_dir
        session.config_snapshot = {
            "pre_roll_ms": 10, "post_roll_ms": 10, "music_poll_ms": 50,
            "play_start_timeout_s": 5, "playback_stall_timeout_s": 5,
            "duration_grace_s": 10, "disk_reserve_gb": 0,
        }
        store.create(session)

        # New manager on restart
        music = FakeMusicController()
        backend = FakeRecorderBackend()
        manager = CaptureManager(store, music, backend)

        # Should find the recoverable session
        recoverable = manager.load_recoverable()
        assert len(recoverable) == 1
        assert recoverable[0].session_id == session.session_id

        # Recover it
        manager.recover_session(session.session_id)
        loaded = manager.session
        assert loaded.status == SessionStatus.NEEDS_ATTENTION
        # The mid-capture track should be marked failed
        assert loaded.tracks[1].status == TrackStatus.FAILED
        assert "restart" in loaded.tracks[1].error.lower()

    def test_resume_after_recovery(self, store, output_dir):
        """After recovery, resume should complete remaining tracks."""
        tracks = _make_tracks(3, duration=0.3)
        tracks[0].status = TrackStatus.COMPLETED
        session = CaptureSession()
        session.status = SessionStatus.NEEDS_ATTENTION
        session.playlist = _make_playlist()
        session.tracks = tracks
        session.output_dir = output_dir
        session.config_snapshot = {
            "pre_roll_ms": 10, "post_roll_ms": 10, "music_poll_ms": 50,
            "play_start_timeout_s": 5, "playback_stall_timeout_s": 5,
            "duration_grace_s": 10, "disk_reserve_gb": 0,
        }
        store.create(session)

        music = FakeMusicController()
        backend = FakeRecorderBackend()
        manager = CaptureManager(store, music, backend)
        manager.recover_session(session.session_id)

        with patch("capture.processing.verify_flac24") as mock_v, \
             patch("capture.processing.apply_capture_tags"), \
             patch("capture.processing.resolve_output_path") as mock_p:
            mock_v.return_value = type("V", (), {
                "ok": True, "facts": None, "issues": []
            })()
            mock_p.side_effect = lambda d, a, t: os.path.join(d, f"{a}-{t}.flac")

            manager.resume()
            manager._worker.join(timeout=15)

        loaded = store.load(session.session_id)
        assert loaded.status == SessionStatus.COMPLETED
        assert loaded.completed_count == 3


class TestEmergencyStop:

    def test_emergency_stop(self, store, output_dir):
        music = FakeMusicController(default_play_duration=5.0)
        backend = FakeRecorderBackend()
        config = {"capture": {
            "pre_roll_ms": 10, "post_roll_ms": 10, "music_poll_ms": 50,
            "play_start_timeout_s": 5, "playback_stall_timeout_s": 5,
            "duration_grace_s": 10, "disk_reserve_gb": 0,
        }}
        manager = CaptureManager(store, music, backend, config)

        tracks = _make_tracks(3, duration=2.0)
        session = manager.create_session(
            _make_playlist(), tracks, output_dir=output_dir,
        )
        session.transition(SessionStatus.PREFLIGHTING)
        session.transition(SessionStatus.READY)
        store.save_atomic(session)

        with patch("capture.processing.verify_flac24") as mock_v, \
             patch("capture.processing.apply_capture_tags"), \
             patch("capture.processing.resolve_output_path") as mock_p:
            mock_v.return_value = type("V", (), {
                "ok": True, "facts": None, "issues": []
            })()
            mock_p.side_effect = lambda d, a, t: os.path.join(d, f"{a}-{t}.flac")

            manager.start_session()
            time.sleep(0.2)
            manager.emergency_stop()
            manager._worker.join(timeout=15)

        loaded = store.load(session.session_id)
        assert loaded.status == SessionStatus.NEEDS_ATTENTION


class TestSkipTrack:

    def test_skip_pending_track(self, store, output_dir):
        music = FakeMusicController()
        backend = FakeRecorderBackend()
        manager = CaptureManager(store, music, backend)

        tracks = _make_tracks(3, duration=0.5)
        session = manager.create_session(
            _make_playlist(), tracks, output_dir=output_dir,
        )
        manager.skip_track(1)

        loaded = store.load(session.session_id)
        assert loaded.tracks[1].status == TrackStatus.SKIPPED
        assert loaded.tracks[0].status == TrackStatus.PENDING
