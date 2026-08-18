"""Single-session capture coordinator with background worker."""

from __future__ import annotations

import logging
import os
import shutil
import threading
import time
from pathlib import Path

from capture.models import (
    CaptureSession, PlannedTrack, PlaylistInfo, SavedMusicState,
    SessionStatus, TrackStatus, InvalidTransition,
    ACTIVE_TRACK, TERMINAL_SESSION, _utc_now,
)
from capture.storage import SessionStore
from capture.backends.base import RecorderBackend, BackendStatus, RawRecording
from capture.music import MusicController, MusicError, MusicTrackNotFound

log = logging.getLogger(__name__)


class CaptureError(Exception):
    pass


class CaptureManager:
    """Coordinates a single capture session with a background worker thread."""

    def __init__(self, store: SessionStore, music: MusicController,
                 backend: RecorderBackend, config: dict | None = None):
        self._store = store
        self._music = music
        self._backend = backend
        self._config = config or {}
        self._session: CaptureSession | None = None
        self._worker: threading.Thread | None = None
        self._lock = threading.Lock()
        self._stop_flag = threading.Event()   # graceful: finish current track, then stop
        self._abort_flag = threading.Event()  # immediate: abort the in-progress track now
        self._pause_flag = threading.Event()
        self._artwork_lock = threading.Lock()
        self._artwork_job: dict | None = None

    @property
    def session(self) -> CaptureSession | None:
        return self._session

    def has_active_session(self) -> bool:
        return self._session is not None and not self._session.is_terminal

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    def create_session(self, playlist: PlaylistInfo,
                       tracks: list[PlannedTrack],
                       backend_name: str = "blackhole",
                       output_dir: str = "") -> CaptureSession:
        with self._lock:
            if self.has_active_session():
                raise CaptureError("A capture session is already active")

            session = CaptureSession()
            session.created_at = _utc_now()
            session.updated_at = _utc_now()
            session.playlist = playlist
            session.tracks = tracks
            session.backend = backend_name
            session.output_dir = os.path.expanduser(
                output_dir
                or self._config.get("capture", {}).get("output_dir", "")
                or self._config.get("destination_dir", "")
            )
            session.config_snapshot = {
                k: v for k, v in self._config.get("capture", {}).items()
                if k != "obs_password"
            }

            self._store.create(session)
            self._session = session
            return session

    def start_session(self) -> str:
        with self._lock:
            if self._session is None:
                raise CaptureError("No session to start")
            self._session.transition(SessionStatus.RUNNING)
            self._store.save_atomic(self._session)
            self._stop_flag.clear()
            self._abort_flag.clear()
            self._pause_flag.clear()

            self._worker = threading.Thread(
                target=self._run_loop, daemon=True,
                name="capture-worker",
            )
            self._worker.start()
            return self._session.session_id

    def pause_after_track(self):
        self._pause_flag.set()

    def stop_after_track(self):
        self._stop_flag.set()

    def emergency_stop(self):
        with self._lock:
            self._stop_flag.set()
            self._abort_flag.set()
            try:
                self._music.stop()
            except Exception:
                pass
            try:
                self._backend.abort()
            except Exception:
                pass
            if self._session and not self._session.is_terminal:
                active = self._session.active_track()
                if active and active.status in ACTIVE_TRACK:
                    active.fail("Emergency stop")
                try:
                    self._session.transition(SessionStatus.NEEDS_ATTENTION)
                except InvalidTransition:
                    pass
                self._store.save_atomic(self._session)

    def resume(self):
        with self._lock:
            if self._session is None:
                raise CaptureError("No session to resume")
            if self._session.status not in (
                SessionStatus.PAUSED, SessionStatus.NEEDS_ATTENTION
            ):
                raise CaptureError(
                    f"Cannot resume from {self._session.status}"
                )
            self._session.transition(SessionStatus.RUNNING)
            self._store.save_atomic(self._session)
            self._stop_flag.clear()
            self._abort_flag.clear()
            self._pause_flag.clear()

            self._worker = threading.Thread(
                target=self._run_loop, daemon=True,
                name="capture-worker",
            )
            self._worker.start()

    def cancel(self):
        with self._lock:
            self._stop_flag.set()
            self._abort_flag.set()
            try:
                self._music.stop()
            except Exception:
                pass
            try:
                self._backend.abort()
            except Exception:
                pass
            if self._session and not self._session.is_terminal:
                try:
                    self._session.transition(SessionStatus.CANCELLED)
                except InvalidTransition:
                    pass
                self._store.save_atomic(self._session)

    def retry_track(self, ordinal: int):
        with self._lock:
            if self._session is None:
                raise CaptureError("No session")
            if ordinal < 0 or ordinal >= len(self._session.tracks):
                raise CaptureError(f"Invalid ordinal: {ordinal}")
            track = self._session.tracks[ordinal]
            track.reset_for_retry()
            self._store.save_atomic(self._session)
            # If the session already drained (needs_attention) or is paused and no
            # worker is running, kick it off so the retried track is actually
            # processed instead of sitting at "pending" forever.
            self._maybe_restart_worker_locked()

    def _worker_alive(self) -> bool:
        return self._worker is not None and self._worker.is_alive()

    def _maybe_restart_worker_locked(self):
        """Restart the background worker if the session is idle but resumable.

        Caller must hold self._lock.
        """
        if self._worker_alive():
            return
        session = self._session
        if session is None:
            return
        if session.status not in (
            SessionStatus.PAUSED, SessionStatus.NEEDS_ATTENTION
        ):
            return
        try:
            session.transition(SessionStatus.RUNNING)
        except InvalidTransition:
            return
        self._store.save_atomic(session)
        self._stop_flag.clear()
        self._abort_flag.clear()
        self._pause_flag.clear()
        self._worker = threading.Thread(
            target=self._run_loop, daemon=True, name="capture-worker",
        )
        self._worker.start()

    def skip_track(self, ordinal: int):
        with self._lock:
            if self._session is None:
                raise CaptureError("No session")
            if ordinal < 0 or ordinal >= len(self._session.tracks):
                raise CaptureError(f"Invalid ordinal: {ordinal}")
            track = self._session.tracks[ordinal]
            if track.status in (TrackStatus.PENDING, TrackStatus.FAILED,
                                TrackStatus.NEEDS_REVIEW):
                track.status = TrackStatus.SKIPPED
                self._store.save_atomic(self._session)
            else:
                raise CaptureError(
                    f"Cannot skip track in state {track.status}"
                )

    def start_fix_artwork(self, session: CaptureSession) -> dict:
        """Start a background job that re-applies album artwork to a session's
        completed output files.

        External mastering (e.g. Platinum Notes) strips embedded art. The worker
        re-fetches each track's artwork from Music and re-embeds it into the
        current file at ``track.final_path`` (where Platinum Notes writes the
        processed file, reusing the original location/filename). Only the
        picture is touched — textual tags written by Platinum Notes are left
        intact. Poll :meth:`artwork_status` for live progress.
        """
        with self._artwork_lock:
            if self._artwork_job and self._artwork_job.get("running"):
                raise CaptureError("Artwork fix already in progress")
            candidates = [t for t in session.tracks
                          if t.status == TrackStatus.COMPLETED]
            self._artwork_job = {
                "running": True,
                "total": len(candidates),
                "done": 0,
                "current": "",
                "fixed": [], "skipped": [], "failed": [],
                "error": None,
            }
            total = len(candidates)

        worker = threading.Thread(
            target=self._fix_artwork_worker, args=(session,),
            daemon=True, name="fix-artwork",
        )
        worker.start()
        return {"total": total}

    def _artwork_record(self, bucket: str, track: PlannedTrack,
                        label: str, reason: str | None):
        entry = {"ordinal": track.ordinal, "track": label}
        if reason:
            entry["reason"] = reason
        with self._artwork_lock:
            self._artwork_job[bucket].append(entry)
            self._artwork_job["done"] += 1

    def _fix_artwork_worker(self, session: CaptureSession):
        from metadata import apply_metadata  # top-level module, import lazily

        playlist_pid = session.playlist.persistent_id if session.playlist else ""
        try:
            for track in session.tracks:
                if track.status != TrackStatus.COMPLETED:
                    continue
                label = f"{track.artist} - {track.title}"
                with self._artwork_lock:
                    self._artwork_job["current"] = label
                path = track.final_path
                if not path or not os.path.exists(path):
                    self._artwork_record("skipped", track, label,
                                         "output file not found")
                    continue
                try:
                    artwork = self._music.get_artwork(playlist_pid,
                                                      track.persistent_id)
                except Exception as e:  # AppleScript / Music errors
                    log.warning("fix_artwork: get_artwork failed for %s: %s",
                                label, e)
                    artwork = None
                if not artwork:
                    self._artwork_record("failed", track, label,
                                         "no artwork available from Music")
                    continue
                try:
                    art_bytes, art_mime = artwork
                    apply_metadata(path, {}, artwork_bytes=art_bytes,
                                   artwork_mime=art_mime)
                    self._artwork_record("fixed", track, label, None)
                except Exception as e:
                    log.warning("fix_artwork: embed failed for %s: %s", label, e)
                    self._artwork_record("failed", track, label, str(e))
        except Exception as e:
            log.exception("fix_artwork worker crashed")
            with self._artwork_lock:
                self._artwork_job["error"] = str(e)
        finally:
            with self._artwork_lock:
                job = self._artwork_job
                job["running"] = False
                job["current"] = ""
                log.info("fix_artwork: %d fixed, %d skipped, %d failed",
                         len(job["fixed"]), len(job["skipped"]),
                         len(job["failed"]))

    def artwork_status(self) -> dict | None:
        with self._artwork_lock:
            j = self._artwork_job
            if j is None:
                return None
            return {
                "running": j["running"],
                "total": j["total"],
                "done": j["done"],
                "current": j["current"],
                "fixed": list(j["fixed"]),
                "skipped": list(j["skipped"]),
                "failed": list(j["failed"]),
                "error": j["error"],
            }

    def load_recoverable(self) -> list[CaptureSession]:
        return self._store.list_recoverable()

    def recover_session(self, session_id: str):
        with self._lock:
            if self.has_active_session():
                raise CaptureError("A capture session is already active")
            session = self._store.load(session_id)
            active = session.active_track()
            if active and active.status in ACTIVE_TRACK:
                active.fail("Interrupted by app restart")
            if session.status == SessionStatus.RUNNING:
                session.status = SessionStatus.NEEDS_ATTENTION
            session.updated_at = _utc_now()
            self._store.save_atomic(session)
            self._session = session

    # ------------------------------------------------------------------
    # Background worker
    # ------------------------------------------------------------------

    def _run_loop(self):
        session = self._session
        if session is None:
            return

        try:
            saved_state = self._music.save_settings()
            session.saved_music_state = saved_state
            self._music.apply_capture_settings()
        except MusicError as e:
            log.error("Failed to configure Music: %s", e)
            session.last_error = str(e)
            session.transition(SessionStatus.FAILED)
            self._store.save_atomic(session)
            return

        try:
            self._capture_loop(session)
        except Exception as e:
            log.exception("Capture loop error")
            session.last_error = str(e)
            if not session.is_terminal:
                try:
                    session.transition(SessionStatus.FAILED)
                except InvalidTransition:
                    session.status = SessionStatus.FAILED
                self._store.save_atomic(session)
        finally:
            try:
                self._music.restore_settings(saved_state)
            except Exception:
                log.warning("Failed to restore Music settings")
            try:
                self._backend.cleanup()
            except Exception:
                pass

    def _capture_loop(self, session: CaptureSession):
        while True:
            if self._stop_flag.is_set():
                if session.status == SessionStatus.RUNNING:
                    session.transition(SessionStatus.STOPPING)
                    self._store.save_atomic(session)
                break

            if self._pause_flag.is_set():
                self._pause_flag.clear()
                if session.status == SessionStatus.RUNNING:
                    session.transition(SessionStatus.PAUSED)
                    self._store.save_atomic(session)
                break

            track = session.next_pending_track()
            if track is None:
                break

            session.current_ordinal = track.ordinal
            self._store.save_atomic(session)

            success = self._process_track(session, track)
            self._store.save_atomic(session)

            if not success and not self._stop_flag.is_set():
                continue

        if not session.is_terminal:
            remaining = session.pending_count
            if remaining == 0 and not self._pause_flag.is_set():
                if session.unresolved_count > 0:
                    # Queue drained but some tracks failed / need review. Do NOT
                    # go terminal — keep the session recoverable and resumable so
                    # the user can retry the stragglers (e.g. after fixing network
                    # connectivity for cloud tracks).
                    if session.status == SessionStatus.RUNNING:
                        session.transition(SessionStatus.NEEDS_ATTENTION)
                        self._store.save_atomic(session)
                else:
                    session.transition(SessionStatus.FINALISING)
                    self._store.save_atomic(session)
                    session.transition(SessionStatus.COMPLETED)
                    self._store.save_atomic(session)
            elif self._stop_flag.is_set():
                if session.status == SessionStatus.STOPPING:
                    session.transition(SessionStatus.FINALISING)
                    self._store.save_atomic(session)
                    session.transition(SessionStatus.COMPLETED)
                    self._store.save_atomic(session)

    def _process_track(self, session: CaptureSession,
                       track: PlannedTrack) -> bool:
        cfg = session.config_snapshot
        pre_roll = cfg.get("pre_roll_ms", 750) / 1000.0
        post_roll = cfg.get("post_roll_ms", 750) / 1000.0
        start_timeout = cfg.get("play_start_timeout_s", 15)
        stall_timeout = cfg.get("playback_stall_timeout_s", 12)
        grace = cfg.get("duration_grace_s", 15)
        poll_interval = cfg.get("music_poll_ms", 250) / 1000.0

        playlist_pid = session.playlist.persistent_id if session.playlist else ""

        # 1. Resolve track in Music
        try:
            if not self._music.resolve_track(playlist_pid, track.persistent_id):
                track.fail(f"Track not found in playlist: {track.title}")
                return False
        except MusicError as e:
            track.fail(f"Music error resolving track: {e}")
            return False

        # 2. Check free space
        output_dir = session.output_dir
        if output_dir:
            try:
                free = shutil.disk_usage(output_dir).free
                needed = int(track.duration_seconds * 48000 * 2 * 3 * 2)
                reserve = cfg.get("disk_reserve_gb", 5) * 1_073_741_824
                if free < needed + reserve:
                    track.fail("Insufficient disk space")
                    session.transition(SessionStatus.NEEDS_ATTENTION)
                    session.last_error = "Disk space low"
                    return False
            except OSError:
                pass

        # 3. Confirm stopped and idle
        try:
            self._music.stop()
        except MusicError:
            pass

        # 4. Arm recorder
        track.transition(TrackStatus.ARMING)
        track.armed_at = time.monotonic()
        self._store.save_atomic(session)

        raw_dir = self._store.raw_dir_for(session.session_id)
        raw_filename = f"{track.ordinal:04d}_{track.persistent_id[:8]}.flac"
        raw_path = str(raw_dir / raw_filename)

        try:
            armed = self._backend.arm(raw_path, cfg)
            if not armed:
                track.fail("Recorder failed to arm")
                return False
        except Exception as e:
            track.fail(f"Recorder arm error: {e}")
            return False

        # 5. Confirm active
        if self._backend.status() != BackendStatus.ACTIVE:
            track.fail("Recorder not active after arm")
            self._backend.abort()
            return False

        track.transition(TrackStatus.RECORDING)
        self._store.save_atomic(session)

        # 6. Pre-roll
        time.sleep(pre_roll)

        # 7. Play
        track.play_requested_at = time.monotonic()
        try:
            self._music.play_once(playlist_pid, track.persistent_id)
        except MusicError as e:
            track.fail(f"Music play error: {e}")
            self._backend.stop()
            return False

        # 8. Wait for playing state
        playing = False
        t_start = time.monotonic()
        while time.monotonic() - t_start < start_timeout:
            if self._abort_flag.is_set():
                self._music.stop()
                self._backend.stop()
                track.fail("Stopped by user")
                return False
            try:
                pb = self._music.get_playback()
                if pb.state == "playing":
                    playing = True
                    track.playing_at = time.monotonic()
                    break
            except MusicError:
                pass
            time.sleep(poll_interval)

        if not playing:
            track.fail("Music did not start playing within timeout")
            self._music.stop()
            self._backend.stop()
            return False

        # 9. Monitor playback
        last_position = -1.0
        stall_start = 0.0
        max_duration = track.duration_seconds + grace

        while True:
            if self._abort_flag.is_set():
                self._music.stop()
                time.sleep(post_roll)
                self._backend.stop()
                track.fail("Stopped by user during playback")
                return False

            time.sleep(poll_interval)

            try:
                pb = self._music.get_playback()
            except MusicError:
                continue

            elapsed = time.monotonic() - track.playing_at

            if pb.state != "playing":
                track.playback_ended_at = time.monotonic()
                break

            if elapsed > max_duration:
                self._music.stop()
                track.playback_ended_at = time.monotonic()
                log.warning("Track %d exceeded max duration, stopping", track.ordinal)
                break

            if abs(pb.position - last_position) < 0.1:
                if stall_start == 0.0:
                    stall_start = time.monotonic()
                elif time.monotonic() - stall_start > stall_timeout:
                    track.fail("Playback stalled")
                    self._music.stop()
                    time.sleep(post_roll)
                    raw = self._backend.stop()
                    if raw:
                        track.raw_path = raw.path
                    return False
            else:
                stall_start = 0.0
            last_position = pb.position

        # Check if emergency stop happened during playback
        if self._abort_flag.is_set() and track.status == TrackStatus.FAILED:
            self._backend.abort()
            return False

        # 10. Post-roll
        time.sleep(post_roll)

        # 11. Stop recorder
        track.transition(TrackStatus.STOPPING)
        track.recorder_stopped_at = time.monotonic()
        self._store.save_atomic(session)

        try:
            raw = self._backend.stop()
        except Exception as e:
            track.fail(f"Recorder stop error: {e}")
            return False

        if raw is None or not raw.path:
            track.fail("No raw recording returned")
            return False
        track.raw_path = raw.path

        # 12. Convert (OBS MKV→FLAC) or promote (BlackHole direct FLAC)
        track.transition(TrackStatus.CONVERTING)
        self._store.save_atomic(session)

        if session.backend == "obs" and raw.codec != "flac":
            from capture.processing import convert_alac_to_flac24
            try:
                flac_path = str(raw_dir / f"{track.ordinal:04d}_converted.flac")
                convert_alac_to_flac24(raw.path, flac_path)
            except Exception as e:
                track.fail(f"Conversion error: {e}")
                return False
        else:
            flac_path = raw.path

        # 13. Verify
        track.transition(TrackStatus.VERIFYING)
        self._store.save_atomic(session)

        from capture.processing import verify_flac24
        vr = verify_flac24(flac_path, expected_duration=track.duration_seconds)
        if not vr.ok:
            track.fail(f"Verification failed: {'; '.join(vr.issues)}")
            track.status = TrackStatus.NEEDS_REVIEW
            return False

        # 14. Tag
        track.transition(TrackStatus.TAGGING)
        self._store.save_atomic(session)

        from capture.processing import apply_capture_tags, resolve_output_path
        artwork = None
        try:
            artwork = self._music.get_artwork(playlist_pid, track.persistent_id)
            if artwork is None:
                log.info("No artwork in Music for track %d (%s)",
                         track.ordinal, track.title)
        except Exception as e:
            log.warning("Artwork fetch failed for track %d: %s", track.ordinal, e)
        try:
            apply_capture_tags(
                flac_path, track, session.session_id, session.backend,
                artwork=artwork,
            )
        except Exception as e:
            log.warning("Tagging failed for track %d: %s", track.ordinal, e)

        # 15. Move to final location
        final_path = resolve_output_path(
            session.output_dir, track.artist, track.title
        )
        try:
            os.makedirs(os.path.dirname(final_path), exist_ok=True)
            if flac_path != final_path:
                shutil.move(flac_path, final_path)
        except OSError as e:
            track.fail(f"Failed to move to output: {e}")
            return False

        track.final_path = final_path
        track.transition(TrackStatus.COMPLETED)
        track.completed_at = time.monotonic()
        return True
