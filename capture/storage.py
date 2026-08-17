"""Atomic JSON manifest persistence for capture sessions."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from capture.models import CaptureSession, TERMINAL_SESSION, SessionStatus


class SessionStore:
    """Manages session manifests on disk.

    Layout:
        <base_dir>/
          .djmm-capture/
            <session-id>/
              manifest.json
              raw/
    """

    CAPTURE_DIR = ".djmm-capture"
    MANIFEST_NAME = "manifest.json"

    def __init__(self, base_dir: str):
        self._base = Path(os.path.expanduser(base_dir))

    def _session_dir(self, session_id: str) -> Path:
        return self._base / self.CAPTURE_DIR / session_id

    def _manifest_path(self, session_id: str) -> Path:
        return self._session_dir(session_id) / self.MANIFEST_NAME

    def _raw_dir(self, session_id: str) -> Path:
        return self._session_dir(session_id) / "raw"

    def create(self, session: CaptureSession) -> Path:
        sdir = self._session_dir(session.session_id)
        sdir.mkdir(parents=True, exist_ok=True)
        self._raw_dir(session.session_id).mkdir(exist_ok=True)
        self.save_atomic(session)
        return sdir

    def save_atomic(self, session: CaptureSession):
        manifest = self._manifest_path(session.session_id)
        manifest.parent.mkdir(parents=True, exist_ok=True)
        data = json.dumps(session.to_dict(), indent=2) + "\n"
        fd, tmp = tempfile.mkstemp(
            dir=str(manifest.parent), suffix=".tmp", prefix="manifest_"
        )
        try:
            with os.fdopen(fd, "w") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, str(manifest))
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def load(self, session_id: str) -> CaptureSession:
        manifest = self._manifest_path(session_id)
        with open(manifest) as f:
            data = json.load(f)
        return CaptureSession.from_dict(data)

    def exists(self, session_id: str) -> bool:
        return self._manifest_path(session_id).exists()

    def list_sessions(self) -> list[str]:
        capture_dir = self._base / self.CAPTURE_DIR
        if not capture_dir.exists():
            return []
        return sorted(
            d.name
            for d in capture_dir.iterdir()
            if d.is_dir() and (d / self.MANIFEST_NAME).exists()
        )

    def list_recoverable(self) -> list[CaptureSession]:
        result = []
        for sid in self.list_sessions():
            try:
                session = self.load(sid)
                if session.status not in TERMINAL_SESSION:
                    result.append(session)
            except (json.JSONDecodeError, KeyError, OSError):
                pass
        return result

    def raw_dir_for(self, session_id: str) -> Path:
        d = self._raw_dir(session_id)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def delete_session(self, session_id: str):
        import shutil
        sdir = self._session_dir(session_id)
        if sdir.exists():
            shutil.rmtree(sdir)
