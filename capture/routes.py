"""Flask routes for the capture subsystem."""

from __future__ import annotations

import logging
import os
from flask import Blueprint, Response, jsonify, request, current_app

from capture.models import (
    CaptureSession, PlannedTrack, PlaylistInfo,
    SessionStatus, TrackStatus, InvalidTransition,
)
from capture.storage import SessionStore
from capture.manager import CaptureManager, CaptureError
from capture.music import MusicController, MusicError, MusicPermissionDenied
from capture.backends.base import BackendStatus

log = logging.getLogger(__name__)

capture_bp = Blueprint("capture", __name__)

_manager: CaptureManager | None = None


def _make_backend(backend_name: str):
    if backend_name == "obs":
        from capture.backends.obs import OBSBackend
        return OBSBackend()
    from capture.backends.blackhole import BlackHoleBackend
    return BlackHoleBackend()


def init_capture(app, config: dict):
    """Initialise the capture subsystem and register the blueprint."""
    cap_cfg = config.get("capture", {})
    backend_name = cap_cfg.get("backend", "obs")

    store = SessionStore(cap_cfg.get("output_dir", "") or config.get("destination_dir", ""))
    music = MusicController()
    backend = _make_backend(backend_name)
    global _manager
    _manager = CaptureManager(store, music, backend, config)

    app.register_blueprint(capture_bp)


def _get_manager() -> CaptureManager:
    if _manager is None:
        raise CaptureError("Capture subsystem not initialised")
    return _manager


def update_capture_config(config: dict) -> None:
    """Push freshly-saved settings into the live manager (no restart needed)."""
    if _manager is not None:
        _manager.update_config(config)


# ------------------------------------------------------------------
# Page
# ------------------------------------------------------------------

@capture_bp.route("/capture")
def capture_page():
    """Serve the capture page, auto cache-busting capture.js by its
    modification time so front-end edits are picked up without a manual
    hard reload.
    """
    static_dir = current_app.static_folder
    html_path = os.path.join(static_dir, "capture.html")
    try:
        with open(html_path, encoding="utf-8") as f:
            html = f.read()
    except OSError:
        return current_app.send_static_file("capture.html")

    try:
        ver = int(os.path.getmtime(os.path.join(static_dir, "capture.js")))
    except OSError:
        ver = 0
    html = html.replace('src="/static/capture.js"',
                        f'src="/static/capture.js?v={ver}"')

    resp = Response(html, mimetype="text/html")
    resp.headers["Cache-Control"] = "no-cache"
    return resp


# ------------------------------------------------------------------
# Playlists
# ------------------------------------------------------------------

@capture_bp.route("/api/capture/playlists")
def list_playlists():
    try:
        m = _get_manager()
        playlists = m._music.list_playlists()
        return jsonify([p.to_dict() for p in playlists])
    except MusicPermissionDenied as e:
        return jsonify({"error": str(e), "code": "permission_denied"}), 403
    except MusicError as e:
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@capture_bp.route("/api/capture/snapshot", methods=["POST"])
def snapshot_playlist():
    data = request.get_json(silent=True) or {}
    playlist_pid = data.get("playlist_persistent_id", "")
    if not playlist_pid:
        return jsonify({"error": "playlist_persistent_id required"}), 400

    try:
        m = _get_manager()
        tracks = m._music.snapshot_playlist(playlist_pid)
        return jsonify({
            "playlist_persistent_id": playlist_pid,
            "track_count": len(tracks),
            "tracks": [t.to_dict() for t in tracks],
        })
    except MusicError as e:
        return jsonify({"error": str(e)}), 500


# ------------------------------------------------------------------
# Preflight
# ------------------------------------------------------------------

@capture_bp.route("/api/capture/preflight", methods=["POST"])
def run_preflight():
    data = request.get_json(silent=True) or {}
    m = _get_manager()

    checks = []

    # Music permission
    try:
        ok = m._music.check_permission()
        checks.append({"name": "Music.app permission", "ok": ok,
                        "fix": "" if ok else "Enable Automation in System Settings"})
    except MusicPermissionDenied as e:
        checks.append({"name": "Music.app permission", "ok": False,
                        "fix": str(e)})

    # Music running
    try:
        running = m._music.is_running()
        checks.append({"name": "Music.app running", "ok": running,
                        "fix": "" if running else "Open Music.app"})
    except Exception:
        checks.append({"name": "Music.app running", "ok": False,
                        "fix": "Open Music.app"})

    # Backend
    cfg = m._config.get("capture", {})
    backend_ok, backend_issues = m._backend.preflight(cfg)
    checks.append({"name": "Recording backend", "ok": backend_ok,
                    "fix": "; ".join(backend_issues)})

    # FFmpeg
    import subprocess
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=5)
        checks.append({"name": "FFmpeg available", "ok": True, "fix": ""})
    except (FileNotFoundError, subprocess.TimeoutExpired):
        checks.append({"name": "FFmpeg available", "ok": False,
                        "fix": "Install FFmpeg: brew install ffmpeg"})

    # FFprobe
    try:
        subprocess.run(["ffprobe", "-version"], capture_output=True, timeout=5)
        checks.append({"name": "FFprobe available", "ok": True, "fix": ""})
    except (FileNotFoundError, subprocess.TimeoutExpired):
        checks.append({"name": "FFprobe available", "ok": False,
                        "fix": "Install FFmpeg: brew install ffmpeg"})

    # Signal test (BlackHole direct only)
    from capture.backends.blackhole import BlackHoleBackend
    if backend_ok and data.get("test_signal", False) and isinstance(m._backend, BlackHoleBackend):
        from capture.backends.blackhole import probe_signal, find_blackhole_device
        device_name = cfg.get("blackhole_device_name", "BlackHole 16ch")
        channels = cfg.get("blackhole_channels", [3, 4])
        device = find_blackhole_device(device_name)
        if device:
            sig = probe_signal(device[0], duration=2.0, channels=channels)
            ch_label = f"channels {channels[0]}-{channels[1]}"
            checks.append({
                "name": f"Signal detected ({ch_label})",
                "ok": sig.has_signal,
                "fix": "" if sig.has_signal else
                    f"No audio on {ch_label}. Route Music to "
                    f"BlackHole {ch_label}.",
                "detail": {
                    "has_signal": sig.has_signal,
                    "left_db": sig.left_db,
                    "right_db": sig.right_db,
                    "clipping": sig.clipping,
                    "one_channel_missing": sig.one_channel_missing,
                },
            })

    all_ok = all(c["ok"] for c in checks)
    return jsonify({"ok": all_ok, "checks": checks})


# ------------------------------------------------------------------
# Sessions
# ------------------------------------------------------------------

@capture_bp.route("/api/capture/sessions", methods=["POST"])
def create_session():
    data = request.get_json(silent=True) or {}
    playlist_pid = data.get("playlist_persistent_id", "")
    tracks_data = data.get("tracks", [])
    output_dir = data.get("output_dir", "")

    if not playlist_pid or not tracks_data:
        return jsonify({"error": "playlist_persistent_id and tracks required"}), 400

    m = _get_manager()

    # Backend: honour an explicit request, else fall back to the configured
    # default (config.py sets capture.backend = "obs").
    backend_name = data.get("backend") or \
        m._config.get("capture", {}).get("backend", "obs")

    # Switch backend if requested differs from current
    new_backend = _make_backend(backend_name)
    if type(new_backend) != type(m._backend):
        m._backend.cleanup()
        m._backend = new_backend

    playlist = PlaylistInfo(
        name=data.get("playlist_name", ""),
        persistent_id=playlist_pid,
        track_count=len(tracks_data),
    )
    tracks = [PlannedTrack.from_dict(t) for t in tracks_data]

    try:
        session = m.create_session(playlist, tracks,
                                   backend_name=backend_name,
                                   output_dir=output_dir)
    except CaptureError as e:
        return jsonify({"error": str(e)}), 409

    # Run preflight and advance to READY
    session.transition(SessionStatus.PREFLIGHTING)
    m._store.save_atomic(session)
    session.transition(SessionStatus.READY)
    m._store.save_atomic(session)

    # Start the session
    try:
        sid = m.start_session()
    except (CaptureError, InvalidTransition) as e:
        return jsonify({"error": str(e)}), 409

    return jsonify({"session_id": sid, "status": session.status.value}), 202


@capture_bp.route("/api/capture/sessions/<session_id>")
def get_session(session_id):
    m = _get_manager()
    if m.session and m.session.session_id == session_id:
        session = m.session
    else:
        try:
            session = m._store.load(session_id)
        except Exception:
            return jsonify({"error": "Session not found"}), 404

    return jsonify(session.to_dict())


@capture_bp.route("/api/capture/sessions/<session_id>/pause", methods=["POST"])
def pause_session(session_id):
    m = _get_manager()
    if not m.session or m.session.session_id != session_id:
        return jsonify({"error": "No active session with this ID"}), 404
    m.pause_after_track()
    return jsonify({"status": "pause_requested"})


@capture_bp.route("/api/capture/sessions/<session_id>/stop", methods=["POST"])
def stop_session(session_id):
    m = _get_manager()
    if not m.session or m.session.session_id != session_id:
        return jsonify({"error": "No active session with this ID"}), 404
    m.stop_after_track()
    return jsonify({"status": "stop_requested"})


@capture_bp.route("/api/capture/sessions/<session_id>/emergency-stop",
                   methods=["POST"])
def emergency_stop_session(session_id):
    m = _get_manager()
    if not m.session or m.session.session_id != session_id:
        return jsonify({"error": "No active session with this ID"}), 404
    m.emergency_stop()
    return jsonify({"status": "emergency_stopped"})


@capture_bp.route("/api/capture/sessions/<session_id>/resume", methods=["POST"])
def resume_session(session_id):
    m = _get_manager()
    if not m.session or m.session.session_id != session_id:
        return jsonify({"error": "No active session with this ID"}), 404
    try:
        m.resume()
        return jsonify({"status": "resumed"})
    except CaptureError as e:
        return jsonify({"error": str(e)}), 409


@capture_bp.route(
    "/api/capture/sessions/<session_id>/tracks/<int:ordinal>/retry",
    methods=["POST"],
)
def retry_track(session_id, ordinal):
    m = _get_manager()
    if not m.session or m.session.session_id != session_id:
        return jsonify({"error": "No active session with this ID"}), 404
    try:
        m.retry_track(ordinal)
        return jsonify({"status": "retry_queued"})
    except CaptureError as e:
        return jsonify({"error": str(e)}), 409


@capture_bp.route(
    "/api/capture/sessions/<session_id>/tracks/<int:ordinal>/skip",
    methods=["POST"],
)
def skip_track(session_id, ordinal):
    m = _get_manager()
    if not m.session or m.session.session_id != session_id:
        return jsonify({"error": "No active session with this ID"}), 404
    try:
        m.skip_track(ordinal)
        return jsonify({"status": "skipped"})
    except CaptureError as e:
        return jsonify({"error": str(e)}), 409


@capture_bp.route("/api/capture/sessions/<session_id>/fix-artwork",
                   methods=["POST"])
def fix_artwork(session_id):
    m = _get_manager()
    if m.session and m.session.session_id == session_id:
        session = m.session
    else:
        try:
            session = m._store.load(session_id)
        except Exception:
            return jsonify({"error": "Session not found"}), 404
    try:
        result = m.start_fix_artwork(session)
        return jsonify({"status": "started", **result})
    except CaptureError as e:
        return jsonify({"error": str(e)}), 409


@capture_bp.route("/api/capture/sessions/<session_id>/fix-artwork/status")
def fix_artwork_status(session_id):
    m = _get_manager()
    status = m.artwork_status()
    if status is None:
        return jsonify({"running": False, "total": 0, "done": 0,
                        "fixed": [], "skipped": [], "failed": [],
                        "current": "", "error": None})
    return jsonify(status)


@capture_bp.route("/api/capture/sessions/<session_id>/cleanup",
                   methods=["POST"])
def cleanup_session(session_id):
    m = _get_manager()
    try:
        m._store.delete_session(session_id)
        return jsonify({"status": "cleaned_up"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ------------------------------------------------------------------
# Recovery
# ------------------------------------------------------------------

@capture_bp.route("/api/capture/current")
def current_session():
    """The session live in this process, if any.

    Used on page load to reconnect the UI to an in-progress capture after the
    browser navigated away and back (the worker keeps running server-side).
    Returns {} when there is no in-memory session.
    """
    m = _get_manager()
    if m.session is None:
        return jsonify({})
    data = m.session.to_dict()
    data["worker_alive"] = m._worker_alive()
    return jsonify(data)


@capture_bp.route("/api/capture/recoverable")
def list_recoverable():
    m = _get_manager()
    sessions = m.load_recoverable()
    return jsonify([s.to_dict() for s in sessions])


@capture_bp.route("/api/capture/recover/<session_id>", methods=["POST"])
def recover_session(session_id):
    m = _get_manager()
    try:
        m.recover_session(session_id)
        return jsonify({"status": "recovered",
                        "session": m.session.to_dict() if m.session else None})
    except CaptureError as e:
        return jsonify({"error": str(e)}), 409
