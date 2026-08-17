"""Recorder backend protocol."""

from __future__ import annotations

import enum
from dataclasses import dataclass
from abc import ABC, abstractmethod


class BackendStatus(str, enum.Enum):
    DISCONNECTED = "disconnected"
    IDLE = "idle"
    ARMING = "arming"
    ACTIVE = "active"
    STOPPING = "stopping"
    FINALISED = "finalised"
    FAILED = "failed"


@dataclass
class RawRecording:
    path: str
    duration_seconds: float = 0.0
    sample_rate: int = 0
    channels: int = 0
    codec: str = ""


@dataclass
class SignalState:
    has_signal: bool = False
    left_db: float = -100.0
    right_db: float = -100.0
    clipping: bool = False
    one_channel_missing: bool = False


class RecorderBackend(ABC):
    """Common interface for BlackHole direct and OBS recording backends."""

    @abstractmethod
    def preflight(self, config: dict) -> tuple[bool, list[str]]:
        """Check backend readiness. Returns (ok, list of issues)."""

    @abstractmethod
    def arm(self, output_path: str, config: dict) -> bool:
        """Start recording to output_path. Returns True when confirmed active."""

    @abstractmethod
    def status(self) -> BackendStatus:
        """Current recorder status."""

    @abstractmethod
    def signal(self) -> SignalState:
        """Latest signal indicator."""

    @abstractmethod
    def stop(self) -> RawRecording | None:
        """Stop recording gracefully. Returns the raw recording info, or None on failure."""

    @abstractmethod
    def abort(self):
        """Force-stop immediately (emergency stop)."""

    @abstractmethod
    def cleanup(self):
        """Release any resources (processes, connections)."""
