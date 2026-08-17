"""Capture subsystem data models and state machine."""

from __future__ import annotations

import enum
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class SessionStatus(str, enum.Enum):
    DRAFT = "draft"
    PREFLIGHTING = "preflighting"
    READY = "ready"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPING = "stopping"
    FINALISING = "finalising"
    COMPLETED = "completed"
    NEEDS_ATTENTION = "needs_attention"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TrackStatus(str, enum.Enum):
    PENDING = "pending"
    ARMING = "arming"
    RECORDING = "recording"
    STOPPING = "stopping"
    CONVERTING = "converting"
    VERIFYING = "verifying"
    TAGGING = "tagging"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    NEEDS_REVIEW = "needs_review"


# ---------------------------------------------------------------------------
# State machine transitions
# ---------------------------------------------------------------------------

_SESSION_TRANSITIONS: dict[SessionStatus, set[SessionStatus]] = {
    SessionStatus.DRAFT: {SessionStatus.PREFLIGHTING, SessionStatus.CANCELLED},
    SessionStatus.PREFLIGHTING: {SessionStatus.READY, SessionStatus.FAILED, SessionStatus.CANCELLED},
    SessionStatus.READY: {SessionStatus.RUNNING, SessionStatus.CANCELLED},
    SessionStatus.RUNNING: {
        SessionStatus.PAUSED,
        SessionStatus.STOPPING,
        SessionStatus.FINALISING,
        SessionStatus.NEEDS_ATTENTION,
        SessionStatus.FAILED,
        SessionStatus.CANCELLED,
    },
    SessionStatus.PAUSED: {
        SessionStatus.RUNNING,
        SessionStatus.CANCELLED,
        SessionStatus.FINALISING,
    },
    SessionStatus.STOPPING: {SessionStatus.FINALISING, SessionStatus.FAILED},
    SessionStatus.FINALISING: {SessionStatus.COMPLETED, SessionStatus.FAILED},
    SessionStatus.NEEDS_ATTENTION: {
        SessionStatus.RUNNING,
        SessionStatus.PAUSED,
        SessionStatus.CANCELLED,
        SessionStatus.FAILED,
    },
}

_TRACK_TRANSITIONS: dict[TrackStatus, set[TrackStatus]] = {
    TrackStatus.PENDING: {TrackStatus.ARMING, TrackStatus.SKIPPED},
    TrackStatus.ARMING: {TrackStatus.RECORDING, TrackStatus.FAILED},
    TrackStatus.RECORDING: {TrackStatus.STOPPING, TrackStatus.FAILED, TrackStatus.NEEDS_REVIEW},
    TrackStatus.STOPPING: {TrackStatus.CONVERTING, TrackStatus.COMPLETED, TrackStatus.FAILED},
    TrackStatus.CONVERTING: {TrackStatus.VERIFYING, TrackStatus.FAILED},
    TrackStatus.VERIFYING: {TrackStatus.TAGGING, TrackStatus.FAILED, TrackStatus.NEEDS_REVIEW},
    TrackStatus.TAGGING: {TrackStatus.COMPLETED, TrackStatus.FAILED},
    TrackStatus.FAILED: {TrackStatus.PENDING, TrackStatus.SKIPPED},
    TrackStatus.NEEDS_REVIEW: {TrackStatus.PENDING, TrackStatus.SKIPPED},
}

TERMINAL_SESSION = {SessionStatus.COMPLETED, SessionStatus.FAILED, SessionStatus.CANCELLED}
TERMINAL_TRACK = {TrackStatus.COMPLETED, TrackStatus.SKIPPED}
ACTIVE_TRACK = {TrackStatus.ARMING, TrackStatus.RECORDING, TrackStatus.STOPPING}


def valid_session_transition(old: SessionStatus, new: SessionStatus) -> bool:
    allowed = _SESSION_TRANSITIONS.get(old, set())
    return new in allowed


def valid_track_transition(old: TrackStatus, new: TrackStatus) -> bool:
    allowed = _TRACK_TRANSITIONS.get(old, set())
    return new in allowed


class InvalidTransition(Exception):
    def __init__(self, entity: str, old, new):
        super().__init__(f"Invalid {entity} transition: {old} -> {new}")
        self.old = old
        self.new = new


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class PlannedTrack:
    ordinal: int
    persistent_id: str
    database_id: int
    title: str
    artist: str
    album: str
    album_artist: str = ""
    duration_seconds: float = 0.0
    year: int = 0
    genre: str = ""
    track_number: int = 0
    disc_number: int = 0
    sample_rate: int = 0
    store_url: str = ""

    status: TrackStatus = TrackStatus.PENDING
    attempts: int = 0
    raw_path: str = ""
    final_path: str = ""
    error: str = ""
    error_history: list[str] = field(default_factory=list)

    armed_at: float = 0.0
    play_requested_at: float = 0.0
    playing_at: float = 0.0
    playback_ended_at: float = 0.0
    recorder_stopped_at: float = 0.0
    completed_at: float = 0.0

    def transition(self, new_status: TrackStatus):
        if not valid_track_transition(self.status, new_status):
            raise InvalidTransition("track", self.status, new_status)
        self.status = new_status

    def fail(self, error_msg: str):
        self.error_history.append(error_msg)
        self.error = error_msg
        if self.status in _TRACK_TRANSITIONS and TrackStatus.FAILED in _TRACK_TRANSITIONS.get(self.status, set()):
            self.status = TrackStatus.FAILED
        else:
            self.status = TrackStatus.FAILED

    def reset_for_retry(self):
        if self.status not in (TrackStatus.FAILED, TrackStatus.NEEDS_REVIEW):
            raise InvalidTransition("track", self.status, TrackStatus.PENDING)
        self.status = TrackStatus.PENDING
        self.attempts += 1
        self.error = ""
        self.raw_path = ""
        self.final_path = ""
        self.armed_at = 0.0
        self.play_requested_at = 0.0
        self.playing_at = 0.0
        self.playback_ended_at = 0.0
        self.recorder_stopped_at = 0.0
        self.completed_at = 0.0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> PlannedTrack:
        d = dict(d)
        d["status"] = TrackStatus(d.get("status", "pending"))
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class PlaylistInfo:
    name: str
    persistent_id: str
    track_count: int
    total_duration_seconds: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> PlaylistInfo:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class SavedMusicState:
    shuffle: bool = False
    repeat: str = "off"
    volume: int = -1

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> SavedMusicState:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


def _generate_session_id() -> str:
    ts = time.strftime("%Y%m%d-%H%M%S")
    short = uuid.uuid4().hex[:8]
    return f"{ts}-{short}"


@dataclass
class CaptureSession:
    session_id: str = field(default_factory=_generate_session_id)
    schema_version: int = 1
    status: SessionStatus = SessionStatus.DRAFT
    created_at: str = ""
    updated_at: str = ""
    playlist: PlaylistInfo | None = None
    backend: str = "blackhole"
    config_snapshot: dict = field(default_factory=dict)
    saved_music_state: SavedMusicState = field(default_factory=SavedMusicState)
    current_ordinal: int = -1
    tracks: list[PlannedTrack] = field(default_factory=list)
    last_error: str = ""
    output_dir: str = ""

    def transition(self, new_status: SessionStatus):
        if not valid_session_transition(self.status, new_status):
            raise InvalidTransition("session", self.status, new_status)
        self.status = new_status
        self.updated_at = _utc_now()

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_SESSION

    @property
    def completed_count(self) -> int:
        return sum(1 for t in self.tracks if t.status == TrackStatus.COMPLETED)

    @property
    def failed_count(self) -> int:
        return sum(1 for t in self.tracks if t.status == TrackStatus.FAILED)

    @property
    def pending_count(self) -> int:
        return sum(1 for t in self.tracks if t.status == TrackStatus.PENDING)

    @property
    def skipped_count(self) -> int:
        return sum(1 for t in self.tracks if t.status == TrackStatus.SKIPPED)

    def next_pending_track(self) -> PlannedTrack | None:
        for t in self.tracks:
            if t.status == TrackStatus.PENDING:
                return t
        return None

    def active_track(self) -> PlannedTrack | None:
        for t in self.tracks:
            if t.status in ACTIVE_TRACK:
                return t
        return None

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "session_id": self.session_id,
            "status": self.status.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "playlist": self.playlist.to_dict() if self.playlist else None,
            "backend": self.backend,
            "config_snapshot": self.config_snapshot,
            "saved_music_state": self.saved_music_state.to_dict(),
            "current_ordinal": self.current_ordinal,
            "tracks": [t.to_dict() for t in self.tracks],
            "last_error": self.last_error,
            "output_dir": self.output_dir,
        }

    @classmethod
    def from_dict(cls, d: dict) -> CaptureSession:
        session = cls()
        session.schema_version = d.get("schema_version", 1)
        session.session_id = d.get("session_id", session.session_id)
        session.status = SessionStatus(d.get("status", "draft"))
        session.created_at = d.get("created_at", "")
        session.updated_at = d.get("updated_at", "")
        pi = d.get("playlist")
        session.playlist = PlaylistInfo.from_dict(pi) if pi else None
        session.backend = d.get("backend", "blackhole")
        session.config_snapshot = d.get("config_snapshot", {})
        sms = d.get("saved_music_state")
        session.saved_music_state = SavedMusicState.from_dict(sms) if sms else SavedMusicState()
        session.current_ordinal = d.get("current_ordinal", -1)
        session.tracks = [PlannedTrack.from_dict(t) for t in d.get("tracks", [])]
        session.last_error = d.get("last_error", "")
        session.output_dir = d.get("output_dir", "")
        return session


def _utc_now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")
