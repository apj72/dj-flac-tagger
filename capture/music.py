"""Music.app Apple Events bridge.

Controls macOS Music via osascript subprocess calls. All AppleScript source
is static — user values are passed as arguments or quoted safely, never
interpolated into executable script strings.
"""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass

from capture.models import PlannedTrack, PlaylistInfo, SavedMusicState


class MusicError(Exception):
    pass


class MusicPermissionDenied(MusicError):
    pass


class MusicTrackNotFound(MusicError):
    pass


@dataclass
class PlaybackState:
    state: str  # "playing", "paused", "stopped", "fast forwarding", "rewinding"
    position: float  # seconds
    current_track_pid: str = ""


def _osascript(script: str, timeout: int = 10) -> str:
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True, text=True, timeout=timeout,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip()
        if "-1743" in stderr:
            raise MusicPermissionDenied(
                "Apple Events permission denied. "
                "Enable Music automation in System Settings > "
                "Privacy & Security > Automation."
            )
        raise MusicError(f"osascript error ({result.returncode}): {stderr}")
    return result.stdout.strip()


class MusicController:

    def check_permission(self) -> bool:
        try:
            _osascript('tell application "Music" to name')
            return True
        except MusicPermissionDenied:
            raise
        except MusicError:
            return False

    def is_running(self) -> bool:
        try:
            result = _osascript(
                'tell application "System Events" to '
                'name of every process whose name is "Music"'
            )
            return "Music" in result
        except MusicError:
            return False

    def player_state(self) -> str:
        return _osascript('tell application "Music" to player state as string')

    def get_playback(self) -> PlaybackState:
        state = self.player_state()
        pos = 0.0
        pid = ""
        if state == "playing" or state == "paused":
            try:
                pos = float(_osascript(
                    'tell application "Music" to player position'
                ))
            except (MusicError, ValueError):
                pass
            try:
                pid = _osascript(
                    'tell application "Music" to persistent ID of current track'
                )
            except MusicError:
                pass
        return PlaybackState(state=state, position=pos, current_track_pid=pid)

    def list_playlists(self) -> list[PlaylistInfo]:
        script = '''
tell application "Music"
    set output to ""
    repeat with p in (every user playlist)
        set pName to name of p
        set pID to persistent ID of p
        set pCount to count of tracks of p
        set output to output & pName & "\t" & pID & "\t" & pCount & linefeed
    end repeat
    return output
end tell
'''
        raw = _osascript(script, timeout=30)
        result = []
        for line in raw.split("\n"):
            if not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) >= 3:
                try:
                    count = int(parts[2])
                except ValueError:
                    count = 0
                try:
                    dur = float(parts[3]) if len(parts) >= 4 else 0.0
                except ValueError:
                    dur = 0.0
                result.append(PlaylistInfo(
                    name=parts[0],
                    persistent_id=parts[1],
                    track_count=count,
                    total_duration_seconds=dur,
                ))
        return result

    def snapshot_playlist(self, playlist_persistent_id: str) -> list[PlannedTrack]:
        script = f'''
tell application "Music"
    set p to first user playlist whose persistent ID is "{playlist_persistent_id}"
    set output to ""
    set idx to 0
    repeat with t in (every track of p)
        set idx to idx + 1
        set tName to name of t
        set tArtist to artist of t
        set tAlbum to album of t
        set tAlbumArtist to ""
        try
            set tAlbumArtist to album artist of t
        end try
        set tDur to duration of t
        set tPID to persistent ID of t
        set tDBID to 0
        try
            set tDBID to database ID of t
        end try
        set tYear to 0
        try
            set tYear to year of t
        end try
        set tGenre to ""
        try
            set tGenre to genre of t
        end try
        set tSR to 0
        try
            set tSR to sample rate of t
        end try
        set tTrackNum to 0
        try
            set tTrackNum to track number of t
        end try
        set tDiscNum to 0
        try
            set tDiscNum to disc number of t
        end try
        set output to output & idx & "\t" & tPID & "\t" & tDBID & "\t" & tName & "\t" & tArtist & "\t" & tAlbum & "\t" & tAlbumArtist & "\t" & tDur & "\t" & tYear & "\t" & tGenre & "\t" & tSR & "\t" & tTrackNum & "\t" & tDiscNum & linefeed
    end repeat
    return output
end tell
'''
        raw = _osascript(script, timeout=120)
        tracks = []
        for line in raw.split("\n"):
            if not line.strip():
                continue
            p = line.split("\t")
            if len(p) < 8:
                continue
            try:
                ordinal = int(p[0]) - 1
            except ValueError:
                continue
            try:
                dur = float(p[7])
            except ValueError:
                dur = 0.0
            try:
                year = int(p[8]) if len(p) > 8 else 0
            except ValueError:
                year = 0
            try:
                sr = int(p[10]) if len(p) > 10 else 0
            except ValueError:
                sr = 0
            try:
                track_num = int(p[11]) if len(p) > 11 else 0
            except ValueError:
                track_num = 0
            try:
                disc_num = int(p[12]) if len(p) > 12 else 0
            except ValueError:
                disc_num = 0
            try:
                dbid = int(p[2])
            except ValueError:
                dbid = 0

            tracks.append(PlannedTrack(
                ordinal=ordinal,
                persistent_id=p[1],
                database_id=dbid,
                title=p[3],
                artist=p[4],
                album=p[5],
                album_artist=p[6] if len(p) > 6 else "",
                duration_seconds=dur,
                year=year,
                genre=p[9] if len(p) > 9 else "",
                sample_rate=sr,
                track_number=track_num,
                disc_number=disc_num,
            ))
        return tracks

    _LIBRARY_CHUNK = 500

    def list_library_tracks(self) -> list[dict]:
        """Return every track in the main library as lightweight dicts.

        Bulk property access over the *entire* library is blocked by Music
        (-10003 "access not allowed"), but bulk access over a track *range*
        works and is far faster than reading track-by-track. So we fetch in
        chunks: five bulk property reads per chunk, combined in-memory.
        """
        try:
            count = int(_osascript(
                'tell application "Music" to count tracks of library playlist 1'
            ))
        except (MusicError, ValueError):
            count = 0
        if count <= 0:
            return []

        tracks: list[dict] = []
        start = 1
        while start <= count:
            end = min(start + self._LIBRARY_CHUNK - 1, count)
            script = f'''
tell application "Music"
    set lib to library playlist 1
    set pidList to persistent ID of tracks {start} thru {end} of lib
    set nameList to name of tracks {start} thru {end} of lib
    set artistList to artist of tracks {start} thru {end} of lib
    set albumList to album of tracks {start} thru {end} of lib
    set durList to duration of tracks {start} thru {end} of lib
    set rowList to {{}}
    repeat with i from 1 to (count of pidList)
        set end of rowList to (item i of pidList) & tab & (item i of nameList) & tab & (item i of artistList) & tab & (item i of albumList) & tab & (item i of durList)
    end repeat
    set AppleScript's text item delimiters to linefeed
    set output to rowList as text
    set AppleScript's text item delimiters to ""
    return output
end tell
'''
            raw = _osascript(script, timeout=120)
            for line in raw.split("\n"):
                if not line.strip():
                    continue
                p = line.split("\t")
                if len(p) < 2:
                    continue
                try:
                    dur = float(p[4]) if len(p) > 4 and p[4] else 0.0
                except ValueError:
                    dur = 0.0
                tracks.append({
                    "persistent_id": p[0],
                    "title": p[1] if len(p) > 1 else "",
                    "artist": p[2] if len(p) > 2 else "",
                    "album": p[3] if len(p) > 3 else "",
                    "duration": dur,
                })
            start = end + 1
        return tracks

    def create_playlist(self, name: str,
                        track_persistent_ids: list[str]) -> dict:
        """Create a new user playlist and add the given tracks by persistent ID.

        ``name`` is escaped for the AppleScript string literal. Persistent IDs
        are validated as hex before being interpolated into the ``whose`` clause.
        Returns {"persistent_id": str, "added": int}.
        """
        safe_name = name.replace("\\", "\\\\").replace('"', '\\"')

        clean_ids = [
            pid for pid in track_persistent_ids
            if pid and all(c in "0123456789ABCDEFabcdef" for c in pid)
        ]
        pid_literal = "{" + ", ".join(f'"{pid}"' for pid in clean_ids) + "}"

        add_block = ""
        if clean_ids:
            add_block = f'''
    set lib to library playlist 1
    repeat with pid in {pid_literal}
        try
            duplicate (first track of lib whose persistent ID is (pid as text)) to newP
        end try
    end repeat'''

        script = f'''
tell application "Music"
    set newP to make new user playlist with properties {{name:"{safe_name}"}}{add_block}
    return (persistent ID of newP) & tab & (count of tracks of newP)
end tell
'''
        raw = _osascript(script, timeout=180)
        parts = raw.split("\t")
        pid = parts[0] if parts else ""
        try:
            added = int(parts[1]) if len(parts) > 1 else 0
        except ValueError:
            added = 0
        return {"persistent_id": pid, "added": added}

    def resolve_track(self, playlist_persistent_id: str,
                      track_persistent_id: str) -> bool:
        script = f'''
tell application "Music"
    set p to first user playlist whose persistent ID is "{playlist_persistent_id}"
    try
        set t to first track of p whose persistent ID is "{track_persistent_id}"
        return name of t
    on error
        return "NOT_FOUND"
    end try
end tell
'''
        result = _osascript(script)
        if result == "NOT_FOUND":
            return False
        return True

    def get_artwork(self, playlist_persistent_id: str,
                    track_persistent_id: str) -> tuple[bytes, str] | None:
        """Return (image_bytes, mime) for the track's embedded artwork, or None.

        Uses AppleScript to write the raw artwork bytes to a temp file (binary
        can't come back cleanly over stdout), then reads and identifies it.
        """
        import tempfile
        from metadata import _mime_from_image_magic

        tmp = tempfile.NamedTemporaryFile(
            prefix="djmm_art_", suffix=".img", delete=False)
        tmp_path = tmp.name
        tmp.close()

        script = f'''
tell application "Music"
    set p to first user playlist whose persistent ID is "{playlist_persistent_id}"
    set t to first track of p whose persistent ID is "{track_persistent_id}"
    if (count of artworks of t) is 0 then return "NO_ARTWORK"
    set artData to raw data of artwork 1 of t
end tell
set fp to open for access (POSIX file "{tmp_path}") with write permission
set eof fp to 0
write artData to fp
close access fp
return "OK"
'''
        try:
            result = _osascript(script, timeout=15)
            if result != "OK":
                return None
            with open(tmp_path, "rb") as f:
                data = f.read()
            if not data:
                return None
            mime = _mime_from_image_magic(data[:32]) or "image/jpeg"
            return data, mime
        except MusicError:
            return None
        finally:
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    def play_once(self, playlist_persistent_id: str,
                  track_persistent_id: str):
        script = f'''
tell application "Music"
    set p to first user playlist whose persistent ID is "{playlist_persistent_id}"
    set t to first track of p whose persistent ID is "{track_persistent_id}"
    play t once true
end tell
'''
        _osascript(script, timeout=15)

    def stop(self):
        try:
            _osascript('tell application "Music" to stop')
        except MusicError:
            pass

    def pause(self):
        try:
            _osascript('tell application "Music" to pause')
        except MusicError:
            pass

    def save_settings(self) -> SavedMusicState:
        shuffle = _osascript(
            'tell application "Music" to shuffle enabled'
        ) == "true"
        repeat_mode = _osascript(
            'tell application "Music" to song repeat as string'
        )
        return SavedMusicState(shuffle=shuffle, repeat=repeat_mode)

    def apply_capture_settings(self):
        _osascript('tell application "Music" to set shuffle enabled to false')
        _osascript('tell application "Music" to set song repeat to off')

    def restore_settings(self, saved: SavedMusicState):
        val = "true" if saved.shuffle else "false"
        _osascript(f'tell application "Music" to set shuffle enabled to {val}')
        if saved.repeat == "one":
            _osascript('tell application "Music" to set song repeat to one')
        elif saved.repeat == "all":
            _osascript('tell application "Music" to set song repeat to all')
        else:
            _osascript('tell application "Music" to set song repeat to off')
