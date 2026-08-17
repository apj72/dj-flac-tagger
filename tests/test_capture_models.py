"""Tests for capture models and state machine."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest
from capture.models import (
    SessionStatus, TrackStatus, CaptureSession, PlannedTrack, PlaylistInfo,
    SavedMusicState, InvalidTransition,
    valid_session_transition, valid_track_transition,
    TERMINAL_SESSION, TERMINAL_TRACK,
)


# ---------------------------------------------------------------------------
# State machine transitions
# ---------------------------------------------------------------------------

class TestSessionTransitions:
    def test_draft_to_preflighting(self):
        assert valid_session_transition(SessionStatus.DRAFT, SessionStatus.PREFLIGHTING)

    def test_preflighting_to_ready(self):
        assert valid_session_transition(SessionStatus.PREFLIGHTING, SessionStatus.READY)

    def test_ready_to_running(self):
        assert valid_session_transition(SessionStatus.READY, SessionStatus.RUNNING)

    def test_running_to_paused(self):
        assert valid_session_transition(SessionStatus.RUNNING, SessionStatus.PAUSED)

    def test_running_to_stopping(self):
        assert valid_session_transition(SessionStatus.RUNNING, SessionStatus.STOPPING)

    def test_paused_to_running(self):
        assert valid_session_transition(SessionStatus.PAUSED, SessionStatus.RUNNING)

    def test_running_to_failed(self):
        assert valid_session_transition(SessionStatus.RUNNING, SessionStatus.FAILED)

    def test_completed_is_terminal(self):
        assert not valid_session_transition(SessionStatus.COMPLETED, SessionStatus.RUNNING)

    def test_cancelled_is_terminal(self):
        assert not valid_session_transition(SessionStatus.CANCELLED, SessionStatus.RUNNING)

    def test_invalid_draft_to_running(self):
        assert not valid_session_transition(SessionStatus.DRAFT, SessionStatus.RUNNING)

    def test_transition_method_raises(self):
        session = CaptureSession()
        assert session.status == SessionStatus.DRAFT
        with pytest.raises(InvalidTransition):
            session.transition(SessionStatus.RUNNING)

    def test_transition_method_succeeds(self):
        session = CaptureSession()
        session.transition(SessionStatus.PREFLIGHTING)
        assert session.status == SessionStatus.PREFLIGHTING
        session.transition(SessionStatus.READY)
        assert session.status == SessionStatus.READY
        session.transition(SessionStatus.RUNNING)
        assert session.status == SessionStatus.RUNNING

    def test_needs_attention_to_running(self):
        assert valid_session_transition(SessionStatus.NEEDS_ATTENTION, SessionStatus.RUNNING)

    def test_needs_attention_to_cancelled(self):
        assert valid_session_transition(SessionStatus.NEEDS_ATTENTION, SessionStatus.CANCELLED)


class TestTrackTransitions:
    def test_pending_to_arming(self):
        assert valid_track_transition(TrackStatus.PENDING, TrackStatus.ARMING)

    def test_arming_to_recording(self):
        assert valid_track_transition(TrackStatus.ARMING, TrackStatus.RECORDING)

    def test_recording_to_stopping(self):
        assert valid_track_transition(TrackStatus.RECORDING, TrackStatus.STOPPING)

    def test_stopping_to_converting(self):
        assert valid_track_transition(TrackStatus.STOPPING, TrackStatus.CONVERTING)

    def test_converting_to_verifying(self):
        assert valid_track_transition(TrackStatus.CONVERTING, TrackStatus.VERIFYING)

    def test_verifying_to_tagging(self):
        assert valid_track_transition(TrackStatus.VERIFYING, TrackStatus.TAGGING)

    def test_tagging_to_completed(self):
        assert valid_track_transition(TrackStatus.TAGGING, TrackStatus.COMPLETED)

    def test_completed_is_terminal(self):
        assert TrackStatus.COMPLETED in TERMINAL_TRACK

    def test_failed_to_pending_for_retry(self):
        assert valid_track_transition(TrackStatus.FAILED, TrackStatus.PENDING)

    def test_pending_to_skipped(self):
        assert valid_track_transition(TrackStatus.PENDING, TrackStatus.SKIPPED)

    def test_recording_to_failed(self):
        assert valid_track_transition(TrackStatus.RECORDING, TrackStatus.FAILED)

    def test_invalid_pending_to_completed(self):
        assert not valid_track_transition(TrackStatus.PENDING, TrackStatus.COMPLETED)

    def test_track_fail_method(self):
        t = PlannedTrack(ordinal=0, persistent_id="abc", database_id=1,
                         title="Test", artist="Artist", album="Album")
        t.transition(TrackStatus.ARMING)
        t.transition(TrackStatus.RECORDING)
        t.fail("Something broke")
        assert t.status == TrackStatus.FAILED
        assert t.error == "Something broke"
        assert "Something broke" in t.error_history

    def test_track_reset_for_retry(self):
        t = PlannedTrack(ordinal=0, persistent_id="abc", database_id=1,
                         title="Test", artist="Artist", album="Album")
        t.transition(TrackStatus.ARMING)
        t.fail("Broke")
        t.reset_for_retry()
        assert t.status == TrackStatus.PENDING
        assert t.attempts == 1
        assert t.error == ""


# ---------------------------------------------------------------------------
# Serialisation round-trip
# ---------------------------------------------------------------------------

class TestSerialisation:
    def test_track_round_trip(self):
        t = PlannedTrack(
            ordinal=2, persistent_id="ABCD1234", database_id=42,
            title="My Track", artist="DJ Test", album="Test Album",
            duration_seconds=312.5, year=2024, genre="House",
        )
        d = t.to_dict()
        t2 = PlannedTrack.from_dict(d)
        assert t2.ordinal == 2
        assert t2.persistent_id == "ABCD1234"
        assert t2.title == "My Track"
        assert t2.duration_seconds == 312.5
        assert t2.status == TrackStatus.PENDING

    def test_session_round_trip(self):
        s = CaptureSession()
        s.playlist = PlaylistInfo(name="Test Playlist", persistent_id="PL1",
                                  track_count=3, total_duration_seconds=600)
        s.tracks = [
            PlannedTrack(ordinal=i, persistent_id=f"T{i}", database_id=i,
                         title=f"Track {i}", artist="Artist", album="Album",
                         duration_seconds=200)
            for i in range(3)
        ]
        s.backend = "blackhole"
        s.output_dir = "/tmp/test"
        s.saved_music_state = SavedMusicState(shuffle=True, repeat="all")

        d = s.to_dict()
        s2 = CaptureSession.from_dict(d)
        assert s2.session_id == s.session_id
        assert s2.playlist.name == "Test Playlist"
        assert len(s2.tracks) == 3
        assert s2.tracks[1].title == "Track 1"
        assert s2.saved_music_state.shuffle is True
        assert s2.saved_music_state.repeat == "all"
        assert s2.backend == "blackhole"

    def test_unknown_fields_ignored(self):
        d = {
            "session_id": "test-123",
            "status": "draft",
            "future_field": "should be ignored",
            "tracks": [],
        }
        s = CaptureSession.from_dict(d)
        assert s.session_id == "test-123"

    def test_track_unknown_fields_ignored(self):
        d = {
            "ordinal": 0,
            "persistent_id": "abc",
            "database_id": 1,
            "title": "Test",
            "artist": "A",
            "album": "B",
            "future_thing": 42,
        }
        t = PlannedTrack.from_dict(d)
        assert t.title == "Test"


# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------

class TestSessionHelpers:
    def _make_session(self, n=3):
        s = CaptureSession()
        s.tracks = [
            PlannedTrack(ordinal=i, persistent_id=f"T{i}", database_id=i,
                         title=f"Track {i}", artist="A", album="B",
                         duration_seconds=120)
            for i in range(n)
        ]
        return s

    def test_next_pending(self):
        s = self._make_session()
        t = s.next_pending_track()
        assert t is not None
        assert t.ordinal == 0

    def test_next_pending_skips_completed(self):
        s = self._make_session()
        s.tracks[0].status = TrackStatus.COMPLETED
        t = s.next_pending_track()
        assert t.ordinal == 1

    def test_next_pending_none_when_all_done(self):
        s = self._make_session()
        for t in s.tracks:
            t.status = TrackStatus.COMPLETED
        assert s.next_pending_track() is None

    def test_counts(self):
        s = self._make_session()
        s.tracks[0].status = TrackStatus.COMPLETED
        s.tracks[1].status = TrackStatus.FAILED
        assert s.completed_count == 1
        assert s.failed_count == 1
        assert s.pending_count == 1

    def test_is_terminal(self):
        s = self._make_session()
        assert not s.is_terminal
        s.status = SessionStatus.COMPLETED
        assert s.is_terminal
