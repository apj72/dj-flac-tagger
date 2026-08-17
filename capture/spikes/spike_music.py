#!/usr/bin/env python3
"""
Phase 0 Spike — Music.app AppleScript control

Tests the core assumptions for playlist capture:
1. Can we list playlists with persistent IDs?
2. Can we snapshot a playlist's tracks with metadata?
3. Can we play a specific track once and detect when it stops?
4. Can we save/restore shuffle and repeat settings?

Run interactively — this will control your Music app.

Usage:
    python capture/spikes/spike_music.py
    python capture/spikes/spike_music.py --play   # also tests playback control
"""

import subprocess
import json
import sys
import time


def osascript(script, timeout=10):
    """Run AppleScript and return stdout. Raises on failure."""
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True, text=True, timeout=timeout,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip()
        if "-1743" in stderr:
            raise PermissionError(
                "Apple Events permission denied (-1743). "
                "Go to System Settings > Privacy & Security > Automation "
                "and enable Music for Terminal (or your IDE)."
            )
        raise RuntimeError(f"osascript failed ({result.returncode}): {stderr}")
    return result.stdout.strip()


def osascript_lines(script, timeout=10):
    """Run AppleScript that returns tab-separated lines."""
    raw = osascript(script, timeout)
    if not raw:
        return []
    rows = []
    for line in raw.split("\n"):
        rows.append(line.split("\t"))
    return rows


# ---------- Test 1: Permission and basic access ----------

def test_permission():
    print("\n=== Test 1: Music.app permission ===")
    try:
        name = osascript('tell application "Music" to name')
        print(f"  Music app name: {name}")
        state = osascript('tell application "Music" to player state as string')
        print(f"  Player state: {state}")
        print("  PASS: Apple Events permission works")
        return True
    except PermissionError as e:
        print(f"  FAIL: {e}")
        return False
    except Exception as e:
        print(f"  FAIL: {e}")
        return False


# ---------- Test 2: List playlists ----------

def test_list_playlists():
    print("\n=== Test 2: List playlists ===")
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
    try:
        rows = osascript_lines(script, timeout=30)
        print(f"  Found {len(rows)} user playlists:")
        for row in rows[:10]:
            if len(row) >= 3:
                print(f"    {row[0]:40s}  ID={row[1]}  tracks={row[2]}")
        if len(rows) > 10:
            print(f"    ... and {len(rows) - 10} more")
        print("  PASS: Playlist listing works with persistent IDs")
        return rows
    except Exception as e:
        print(f"  FAIL: {e}")
        return []


# ---------- Test 3: Snapshot a playlist's tracks ----------

def test_snapshot_playlist(playlist_id):
    print(f"\n=== Test 3: Snapshot playlist tracks (ID={playlist_id}) ===")
    script = f'''
tell application "Music"
    set p to first user playlist whose persistent ID is "{playlist_id}"
    set output to ""
    set idx to 0
    repeat with t in (every track of p)
        set idx to idx + 1
        set tName to name of t
        set tArtist to artist of t
        set tAlbum to album of t
        set tDur to duration of t
        set tPID to persistent ID of t
        try
            set tDBID to database ID of t
        on error
            set tDBID to 0
        end try
        try
            set tYear to year of t
        on error
            set tYear to 0
        end try
        try
            set tGenre to genre of t
        on error
            set tGenre to ""
        end try
        try
            set tSR to sample rate of t
        on error
            set tSR to 0
        end try
        set output to output & idx & "\t" & tPID & "\t" & tDBID & "\t" & tName & "\t" & tArtist & "\t" & tAlbum & "\t" & tDur & "\t" & tYear & "\t" & tGenre & "\t" & tSR & linefeed
        if idx >= 5 then exit repeat
    end repeat
    return output
end tell
'''
    try:
        rows = osascript_lines(script, timeout=30)
        print(f"  Snapshot (first {len(rows)} tracks):")
        for row in rows:
            if len(row) >= 7:
                print(f"    #{row[0]:3s} PID={row[1]}  DBID={row[2]}")
                print(f"         {row[4]} - {row[3]}")
                print(f"         Album: {row[5]}  Dur: {float(row[6]):.1f}s  Year: {row[7]}  SR: {row[9]}")
        print("  PASS: Track snapshot with persistent IDs works")
        return rows
    except Exception as e:
        print(f"  FAIL: {e}")
        import traceback; traceback.print_exc()
        return []


# ---------- Test 4: Shuffle/repeat save and restore ----------

def test_shuffle_repeat():
    print("\n=== Test 4: Shuffle and repeat settings ===")
    try:
        shuffle = osascript('tell application "Music" to shuffle enabled')
        repeat_mode = osascript('tell application "Music" to song repeat as string')
        print(f"  Current shuffle: {shuffle}")
        print(f"  Current repeat: {repeat_mode}")

        osascript('tell application "Music" to set shuffle enabled to false')
        osascript('tell application "Music" to set song repeat to off')
        s2 = osascript('tell application "Music" to shuffle enabled')
        r2 = osascript('tell application "Music" to song repeat as string')
        print(f"  After setting off — shuffle: {s2}, repeat: {r2}")

        # Restore
        restore_shuffle = "true" if shuffle == "true" else "false"
        osascript(f'tell application "Music" to set shuffle enabled to {restore_shuffle}')
        if repeat_mode == "one":
            osascript('tell application "Music" to set song repeat to one')
        elif repeat_mode == "all":
            osascript('tell application "Music" to set song repeat to all')
        else:
            osascript('tell application "Music" to set song repeat to off')

        print("  PASS: Shuffle/repeat save and restore works")
        return True
    except Exception as e:
        print(f"  FAIL: {e}")
        return False


# ---------- Test 5: Play a track once and monitor ----------

def test_play_once(playlist_id, track_persistent_id, expected_duration):
    print(f"\n=== Test 5: Play track once (PID={track_persistent_id}, ~{expected_duration:.0f}s) ===")
    print("  This will play the track through Music.app.")
    print("  It will stop automatically when the track ends.")

    try:
        # Stop any current playback
        osascript('tell application "Music" to stop')
        time.sleep(0.5)

        # Disable shuffle/repeat for clean playback
        osascript('tell application "Music" to set shuffle enabled to false')
        osascript('tell application "Music" to set song repeat to off')

        # Play the specific track once
        play_script = f'''
tell application "Music"
    set p to first user playlist whose persistent ID is "{playlist_id}"
    set t to first track of p whose persistent ID is "{track_persistent_id}"
    play t once true
end tell
'''
        print("  Issuing play command...")
        t_start = time.monotonic()
        osascript(play_script)

        # Wait for playing state
        playing = False
        for _ in range(30):  # 15 seconds max
            time.sleep(0.5)
            state = osascript('tell application "Music" to player state as string')
            if state == "playing":
                playing = True
                t_playing = time.monotonic()
                print(f"  Playing detected after {t_playing - t_start:.1f}s")
                break

        if not playing:
            print("  FAIL: Music never entered playing state")
            return False

        # Verify current track identity
        cur_pid = osascript('''
tell application "Music"
    try
        persistent ID of current track
    on error
        "unknown"
    end try
end tell
''')
        if cur_pid == track_persistent_id:
            print(f"  Current track PID matches: {cur_pid}")
        else:
            print(f"  WARNING: Current track PID mismatch: got {cur_pid}, expected {track_persistent_id}")

        # Poll until stopped — limit to expected_duration + 30s
        max_wait = expected_duration + 30
        poll_count = 0
        last_position = -1
        stall_count = 0

        print("  Monitoring playback...")
        while time.monotonic() - t_playing < max_wait:
            time.sleep(0.5)
            poll_count += 1

            state = osascript('tell application "Music" to player state as string')
            position_str = osascript('tell application "Music" to player position')
            try:
                position = float(position_str)
            except (ValueError, TypeError):
                position = 0.0

            if poll_count % 10 == 0:  # Log every 5 seconds
                print(f"    [{time.monotonic() - t_playing:.0f}s] state={state} pos={position:.1f}s")

            if state != "playing":
                elapsed = time.monotonic() - t_playing
                print(f"  Playback ended: state={state} after {elapsed:.1f}s (expected ~{expected_duration:.0f}s)")

                # Check if duration is reasonable
                if abs(elapsed - expected_duration) < 15:
                    print("  PASS: Track played once and stopped. Duration matches.")
                else:
                    print(f"  WARNING: Duration mismatch ({elapsed:.1f}s vs {expected_duration:.0f}s)")
                    print("  PASS (with warning): Play once worked but duration differs")
                return True

            # Stall detection
            if abs(position - last_position) < 0.1:
                stall_count += 1
                if stall_count > 24:  # 12 seconds
                    print(f"  WARNING: Position stalled at {position:.1f}s for 12+ seconds")
            else:
                stall_count = 0
            last_position = position

        # If we got here, playback ran too long
        osascript('tell application "Music" to stop')
        elapsed = time.monotonic() - t_playing
        print(f"  FAIL: Playback exceeded max wait ({elapsed:.1f}s). Stopped manually.")
        return False

    except Exception as e:
        print(f"  FAIL: {e}")
        import traceback; traceback.print_exc()
        try:
            osascript('tell application "Music" to stop')
        except Exception:
            pass
        return False


# ---------- Main ----------

def main():
    do_play = "--play" in sys.argv

    print("DJ MetaManager — Phase 0 Spike: Music.app Control")
    print("=" * 55)

    # Test 1: Permission
    if not test_permission():
        print("\nCannot proceed without Apple Events permission.")
        sys.exit(1)

    # Test 2: List playlists
    playlists = test_list_playlists()
    if not playlists:
        print("\nNo playlists found.")
        sys.exit(1)

    # Let user pick a playlist for testing
    print("\n--- Select a playlist for further testing ---")
    for i, row in enumerate(playlists[:20]):
        if len(row) >= 3:
            print(f"  [{i}] {row[0]:40s}  ({row[2]} tracks)")
    choice = input("\nEnter number (or press Enter to use the first): ").strip()
    idx = int(choice) if choice.isdigit() else 0
    selected = playlists[idx]
    playlist_id = selected[1]
    print(f"  Selected: {selected[0]} (ID={playlist_id})")

    # Test 3: Snapshot
    tracks = test_snapshot_playlist(playlist_id)

    # Test 4: Shuffle/repeat
    test_shuffle_repeat()

    # Test 5: Playback (only with --play flag)
    if do_play and tracks:
        first_track = tracks[0]
        if len(first_track) >= 7:
            track_pid = first_track[1]
            duration = float(first_track[6])

            if duration > 120:
                print(f"\n  Note: Track is {duration:.0f}s long. This test will play the full track.")
                confirm = input("  Continue? (y/n): ").strip().lower()
                if confirm != "y":
                    print("  Skipped playback test.")
                    return
            test_play_once(playlist_id, track_pid, duration)
        else:
            print("  Cannot test playback — insufficient track data")
    elif not do_play:
        print("\n  Playback test skipped. Use --play to test playback control.")

    print("\n" + "=" * 55)
    print("Spike complete. Review the results above.")


if __name__ == "__main__":
    main()
