"""OBS WebSocket recording backend.

Controls OBS Studio via WebSocket v5 to start/stop recordings,
producing one MKV per track with ALAC 24-bit audio.
"""

from __future__ import annotations

import logging
import os
import time

from capture.backends.base import (
    RecorderBackend, BackendStatus, RawRecording, SignalState,
)

log = logging.getLogger(__name__)

STOP_WAIT_TIMEOUT_S = 10
FILE_SETTLE_TIMEOUT_S = 5


class OBSBackend(RecorderBackend):
    """Records via OBS WebSocket v5 — one MKV recording per track."""

    def __init__(self):
        self._status = BackendStatus.DISCONNECTED
        self._client = None
        self._output_path = ""
        self._start_time = 0.0
        self._host = "127.0.0.1"
        self._port = 4455
        self._password = ""

    def _connect(self, config: dict) -> bool:
        obs_cfg = config.get("obs", {})
        self._host = obs_cfg.get("host", "127.0.0.1")
        self._port = obs_cfg.get("port", 4455)
        self._password = obs_cfg.get("password", "") or config.get("obs_password", "")

        try:
            import obsws_python as obs
            self._client = obs.ReqClient(
                host=self._host,
                port=self._port,
                password=self._password,
                timeout=10,
            )
            self._status = BackendStatus.IDLE
            return True
        except ConnectionRefusedError:
            log.error("OBS WebSocket connection refused at %s:%s", self._host, self._port)
            self._status = BackendStatus.DISCONNECTED
            return False
        except Exception as e:
            log.error("OBS WebSocket connection failed: %s", e)
            self._status = BackendStatus.DISCONNECTED
            return False

    def _ensure_connected(self, config: dict) -> bool:
        if self._client is not None:
            try:
                self._client.get_version()
                return True
            except Exception:
                self._client = None
                self._status = BackendStatus.DISCONNECTED
        return self._connect(config)

    def preflight(self, config: dict) -> tuple[bool, list[str]]:
        issues = []

        try:
            import obsws_python  # noqa: F401
        except ImportError:
            issues.append("obsws-python not installed. Run: pip install obsws-python")
            return False, issues

        if not self._connect(config):
            issues.append(
                f"Cannot connect to OBS WebSocket at "
                f"{self._host}:{self._port}. "
                "Ensure OBS is running and WebSocket server is enabled "
                "(Tools → obs-websocket Settings)."
            )
            return False, issues

        try:
            version = self._client.get_version()
            log.info("OBS version: %s, WebSocket: %s",
                     getattr(version, 'obs_version', '?'),
                     getattr(version, 'obs_web_socket_version', '?'))
        except Exception as e:
            issues.append(f"Failed to get OBS version: {e}")

        try:
            rec_status = self._client.get_record_status()
            if getattr(rec_status, 'output_active', False):
                issues.append(
                    "OBS is currently recording. Stop the recording "
                    "before starting a capture session."
                )
        except Exception as e:
            issues.append(f"Failed to check OBS recording status: {e}")

        try:
            import subprocess
            subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=5)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            issues.append("FFmpeg not found (needed for ALAC→FLAC conversion)")

        try:
            import subprocess
            subprocess.run(["ffprobe", "-version"], capture_output=True, timeout=5)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            issues.append("FFprobe not found (needed for output verification)")

        return len(issues) == 0, issues

    def arm(self, output_path: str, config: dict) -> bool:
        if not self._ensure_connected(config):
            self._status = BackendStatus.FAILED
            return False

        try:
            rec_status = self._client.get_record_status()
            if getattr(rec_status, 'output_active', False):
                log.error("OBS is already recording — refusing to start")
                self._status = BackendStatus.FAILED
                return False
        except Exception as e:
            log.error("Failed to check OBS status before arm: %s", e)
            self._status = BackendStatus.FAILED
            return False

        self._output_path = output_path
        self._status = BackendStatus.ARMING

        try:
            self._client.start_record()
        except Exception as e:
            log.error("Failed to start OBS recording: %s", e)
            self._status = BackendStatus.FAILED
            return False

        time.sleep(0.5)

        try:
            rec_status = self._client.get_record_status()
            if not getattr(rec_status, 'output_active', False):
                log.error("OBS recording did not become active")
                self._status = BackendStatus.FAILED
                return False
        except Exception as e:
            log.error("Failed to confirm OBS recording active: %s", e)
            self._status = BackendStatus.FAILED
            return False

        self._status = BackendStatus.ACTIVE
        self._start_time = time.monotonic()
        return True

    def status(self) -> BackendStatus:
        if self._status == BackendStatus.ACTIVE and self._client:
            try:
                rec_status = self._client.get_record_status()
                if not getattr(rec_status, 'output_active', False):
                    self._status = BackendStatus.FAILED
            except Exception:
                pass
        return self._status

    def signal(self) -> SignalState:
        if self._status == BackendStatus.ACTIVE:
            return SignalState(has_signal=True)
        return SignalState()

    def stop(self) -> RawRecording | None:
        if self._client is None:
            self._status = BackendStatus.IDLE
            return None

        self._status = BackendStatus.STOPPING

        try:
            result = self._client.stop_record()
            obs_path = getattr(result, 'output_path', '')
        except Exception as e:
            log.error("Failed to stop OBS recording: %s", e)
            self._status = BackendStatus.FAILED
            return None

        if not obs_path:
            log.error("OBS did not return an output path")
            self._status = BackendStatus.FAILED
            return None

        t0 = time.monotonic()
        while time.monotonic() - t0 < FILE_SETTLE_TIMEOUT_S:
            if os.path.exists(obs_path):
                time.sleep(0.5)
                size1 = os.path.getsize(obs_path)
                time.sleep(0.3)
                size2 = os.path.getsize(obs_path)
                if size2 == size1:
                    break
            time.sleep(0.3)

        if not os.path.exists(obs_path):
            log.error("OBS output file not found: %s", obs_path)
            self._status = BackendStatus.FAILED
            return None

        duration = time.monotonic() - self._start_time
        self._status = BackendStatus.IDLE

        codec = "alac"
        if obs_path.lower().endswith(('.flac',)):
            codec = "flac"

        return RawRecording(
            path=obs_path,
            duration_seconds=duration,
            sample_rate=0,
            channels=2,
            codec=codec,
        )

    def abort(self):
        if self._client is not None:
            try:
                rec_status = self._client.get_record_status()
                if getattr(rec_status, 'output_active', False):
                    self._client.stop_record()
            except Exception:
                pass
        self._status = BackendStatus.IDLE

    def cleanup(self):
        self.abort()
        self._client = None
        self._status = BackendStatus.DISCONNECTED
