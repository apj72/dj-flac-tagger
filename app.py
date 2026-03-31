import json
import os
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from flask import Flask, jsonify, request
import mutagen
from mutagen.flac import FLAC, Picture
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4, MP4Cover
from mutagen.id3 import ID3, APIC, TIT2, TPE1, TPE2, TALB, TDRC, TCON, COMM, TPUB, TRCK, TXXX
from mutagen.oggvorbis import OggVorbis

AUDIO_EXTENSIONS = (".flac", ".mp3", ".m4a", ".mp4", ".aac", ".ogg", ".oga", ".wma", ".aiff", ".aif")

app = Flask(__name__)

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")


def load_config():
    defaults = {
        "source_dir": "~/DJ-Mixes",
        "destination_dir": "~/Documents/Rekordbox-music/FLACs",
    }
    try:
        with open(CONFIG_PATH) as f:
            cfg = json.load(f)
        defaults.update(cfg)
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return defaults


def save_config(cfg):
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)
        f.write("\n")


def resolve(path):
    return os.path.expanduser(path)


LOG_PATH = os.path.join(os.path.dirname(__file__), "processing_log.json")


def load_log():
    try:
        with open(LOG_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_log(entries):
    with open(LOG_PATH, "w") as f:
        json.dump(entries, f, indent=2)
        f.write("\n")


def log_extraction(entry):
    entries = load_log()
    entry["timestamp"] = datetime.now().isoformat()
    entries.append(entry)
    save_log(entries)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run_ffprobe(filepath):
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_streams", "-select_streams", "a:0",
            "-show_entries", "stream=codec_name,sample_rate,channels,duration",
            "-show_entries", "format=duration",
            "-of", "json",
            filepath,
        ],
        capture_output=True, text=True,
    )
    return json.loads(result.stdout)


TARGET_LUFS = -14.0
TARGET_TP = -1.0


def analyse_loudness(filepath):
    """Run ffmpeg loudnorm + volumedetect analysis on an audio/video file."""
    result = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-i", filepath,
            "-af", "loudnorm=print_format=json",
            "-f", "null", "-",
        ],
        capture_output=True, text=True,
    )
    stderr = result.stderr

    loudnorm = {}
    json_start = stderr.rfind("{")
    json_end = stderr.rfind("}") + 1
    if json_start != -1 and json_end > json_start:
        try:
            loudnorm = json.loads(stderr[json_start:json_end])
        except json.JSONDecodeError:
            pass

    vol_result = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-i", filepath,
            "-af", "volumedetect",
            "-f", "null", "-",
        ],
        capture_output=True, text=True,
    )
    vol_stderr = vol_result.stderr

    mean_vol = None
    max_vol = None
    for line in vol_stderr.splitlines():
        if "mean_volume" in line:
            m = re.search(r"mean_volume:\s*([-\d.]+)", line)
            if m:
                mean_vol = float(m.group(1))
        if "max_volume" in line:
            m = re.search(r"max_volume:\s*([-\d.]+)", line)
            if m:
                max_vol = float(m.group(1))

    return {
        "integrated_lufs": float(loudnorm.get("input_i", 0)),
        "true_peak": float(loudnorm.get("input_tp", 0)),
        "lra": float(loudnorm.get("input_lra", 0)),
        "threshold": float(loudnorm.get("input_thresh", 0)),
        "mean_volume": mean_vol,
        "max_volume": max_vol,
        "target_lufs": TARGET_LUFS,
        "target_tp": TARGET_TP,
        "loudnorm_params": loudnorm,
    }


def extract_flac(mkv_path, output_path, normalise=False, loudnorm_params=None):
    info = run_ffprobe(mkv_path)
    codec = info["streams"][0]["codec_name"] if info.get("streams") else "unknown"

    if normalise and loudnorm_params:
        # Two-pass EBU R128 normalisation — uses measured values from pass 1
        af = (
            f"loudnorm=I={TARGET_LUFS}:TP={TARGET_TP}:LRA=11"
            f":measured_I={loudnorm_params.get('input_i', -24)}"
            f":measured_TP={loudnorm_params.get('input_tp', -2)}"
            f":measured_LRA={loudnorm_params.get('input_lra', 7)}"
            f":measured_thresh={loudnorm_params.get('input_thresh', -34)}"
            f":linear=true:print_format=json"
        )
        cmd = [
            "ffmpeg", "-hide_banner", "-y", "-i", mkv_path,
            "-vn", "-af", af, "-c:a", "flac", "-sample_fmt", "s16", output_path,
        ]
    elif codec == "flac":
        cmd = ["ffmpeg", "-hide_banner", "-y", "-i", mkv_path, "-vn", "-c:a", "copy", output_path]
    else:
        cmd = [
            "ffmpeg", "-hide_banner", "-y", "-i", mkv_path,
            "-vn", "-c:a", "flac", "-sample_fmt", "s16", output_path,
        ]

    subprocess.run(cmd, capture_output=True, text=True, check=True)
    return codec


def trash_file(filepath):
    """Move a file to macOS Bin via Finder (recoverable)."""
    script = (
        f'tell application "Finder" to delete '
        f'(POSIX file "{filepath}" as alias)'
    )
    subprocess.run(["osascript", "-e", script], capture_output=True, text=True, check=True)


def apply_metadata(filepath, metadata, artwork_bytes=None, artwork_mime=None):
    ext = os.path.splitext(filepath)[1].lower()

    if ext == ".flac":
        _apply_flac(filepath, metadata, artwork_bytes, artwork_mime)
    elif ext == ".mp3":
        _apply_mp3(filepath, metadata, artwork_bytes, artwork_mime)
    elif ext in (".m4a", ".mp4", ".aac"):
        _apply_mp4(filepath, metadata, artwork_bytes, artwork_mime)
    elif ext in (".ogg", ".oga"):
        _apply_vorbis(filepath, metadata, artwork_bytes, artwork_mime)
    else:
        _apply_generic(filepath, metadata, artwork_bytes, artwork_mime)


def _image_dimensions(data):
    """Read width/height from JPEG or PNG binary data."""
    import struct
    if data[:8] == b'\x89PNG\r\n\x1a\n' and len(data) >= 24:
        w, h = struct.unpack('>II', data[16:24])
        return w, h
    if data[:2] == b'\xff\xd8':
        i = 2
        while i < len(data) - 1:
            if data[i] != 0xff:
                break
            marker = data[i + 1]
            if marker in (0xc0, 0xc1, 0xc2):
                if i + 9 < len(data):
                    h, w = struct.unpack('>HH', data[i + 5:i + 9])
                    return w, h
                break
            if marker in (0xd0, 0xd1, 0xd2, 0xd3, 0xd4, 0xd5, 0xd6, 0xd7, 0xd8, 0xd9, 0x01):
                i += 2
                continue
            if i + 3 < len(data):
                seg_len = struct.unpack('>H', data[i + 2:i + 4])[0]
                i += 2 + seg_len
            else:
                break
    return 0, 0


def _apply_flac(filepath, metadata, artwork_bytes, artwork_mime):
    audio = FLAC(filepath)
    vorbis_map = {
        "title": "title", "artist": "artist", "albumartist": "albumartist",
        "album": "album", "date": "date", "genre": "genre", "comment": "comment",
        "tracknumber": "tracknumber", "label": "organization", "catno": "catalognumber",
    }
    for key, vorbis_key in vorbis_map.items():
        val = metadata.get(key)
        if val:
            audio[vorbis_key] = [val]
    if artwork_bytes:
        pic = Picture()
        pic.type = 3
        pic.mime = artwork_mime or "image/jpeg"
        pic.desc = "Cover"
        pic.data = artwork_bytes
        pic.width, pic.height = _image_dimensions(artwork_bytes)
        audio.clear_pictures()
        audio.add_picture(pic)
    audio.save()


def _apply_mp3(filepath, metadata, artwork_bytes, artwork_mime):
    audio = MP3(filepath, ID3=ID3)
    try:
        audio.add_tags()
    except mutagen.id3.error:
        pass
    t = audio.tags
    id3_map = {
        "title": TIT2, "artist": TPE1, "albumartist": TPE2,
        "album": TALB, "genre": TCON,
    }
    for key, frame_cls in id3_map.items():
        val = metadata.get(key)
        if val:
            t.delall(frame_cls.__name__)
            t.add(frame_cls(encoding=3, text=[val]))
    if metadata.get("date"):
        t.delall("TDRC")
        t.add(TDRC(encoding=3, text=[metadata["date"]]))
    if metadata.get("tracknumber"):
        t.delall("TRCK")
        t.add(TRCK(encoding=3, text=[metadata["tracknumber"]]))
    if metadata.get("comment"):
        t.delall("COMM")
        t.add(COMM(encoding=3, lang="eng", desc="", text=[metadata["comment"]]))
    if metadata.get("label"):
        t.delall("TPUB")
        t.add(TPUB(encoding=3, text=[metadata["label"]]))
    if metadata.get("catno"):
        t.delall("TXXX:CATALOGNUMBER")
        t.add(TXXX(encoding=3, desc="CATALOGNUMBER", text=[metadata["catno"]]))
    if artwork_bytes:
        t.delall("APIC")
        t.add(APIC(encoding=3, mime=artwork_mime or "image/jpeg", type=3, desc="Cover", data=artwork_bytes))
    audio.save(v2_version=3)


def _apply_mp4(filepath, metadata, artwork_bytes, artwork_mime):
    audio = MP4(filepath)
    if audio.tags is None:
        audio.add_tags()
    mp4_map = {
        "title": "\xa9nam", "artist": "\xa9ART", "albumartist": "aART",
        "album": "\xa9alb", "date": "\xa9day", "genre": "\xa9gen",
        "comment": "\xa9cmt",
    }
    for key, atom in mp4_map.items():
        val = metadata.get(key)
        if val:
            audio.tags[atom] = [val]
    if metadata.get("tracknumber"):
        try:
            tnum = int(metadata["tracknumber"])
            audio.tags["trkn"] = [(tnum, 0)]
        except ValueError:
            pass
    if artwork_bytes:
        fmt = MP4Cover.FORMAT_JPEG
        if artwork_mime and "png" in artwork_mime:
            fmt = MP4Cover.FORMAT_PNG
        audio.tags["covr"] = [MP4Cover(artwork_bytes, imageformat=fmt)]
    audio.save()


def _apply_vorbis(filepath, metadata, artwork_bytes, artwork_mime):
    audio = OggVorbis(filepath)
    vorbis_map = {
        "title": "title", "artist": "artist", "albumartist": "albumartist",
        "album": "album", "date": "date", "genre": "genre", "comment": "comment",
        "tracknumber": "tracknumber", "label": "organization", "catno": "catalognumber",
    }
    for key, vorbis_key in vorbis_map.items():
        val = metadata.get(key)
        if val:
            audio[vorbis_key] = [val]
    if artwork_bytes:
        import base64
        pic = Picture()
        pic.type = 3
        pic.mime = artwork_mime or "image/jpeg"
        pic.desc = "Cover"
        pic.data = artwork_bytes
        pic.width, pic.height = _image_dimensions(artwork_bytes)
        audio["metadata_block_picture"] = [base64.b64encode(pic.write()).decode("ascii")]
    audio.save()


def _apply_generic(filepath, metadata, artwork_bytes, artwork_mime):
    """Fallback using mutagen.File for any other supported format."""
    audio = mutagen.File(filepath, easy=True)
    if audio is None:
        raise ValueError(f"Unsupported file format: {filepath}")
    if audio.tags is None:
        audio.add_tags()
    easy_map = {"title": "title", "artist": "artist", "albumartist": "albumartist",
                "album": "album", "date": "date", "genre": "genre"}
    for key, tag in easy_map.items():
        val = metadata.get(key)
        if val:
            try:
                audio[tag] = [val]
            except (KeyError, mutagen.MutagenError):
                pass
    audio.save()


# ---------------------------------------------------------------------------
# Scrapers
# ---------------------------------------------------------------------------

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

DISCOGS_HEADERS = {"User-Agent": "DJFlacTagger/1.0 +https://github.com/dj-flac-tagger"}


def scrape_bandcamp(url):
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")

    meta = {}

    ld_json = soup.find("script", type="application/ld+json")
    if ld_json:
        try:
            data = json.loads(ld_json.string)
            if isinstance(data, list):
                data = data[0]

            meta["title"] = data.get("name", "")

            if "inAlbum" in data:
                album = data["inAlbum"]
                meta["album"] = album.get("name", "")
                if "byArtist" in album:
                    meta["albumartist"] = album["byArtist"].get("name", "")

            if "byArtist" in data:
                meta["artist"] = data["byArtist"].get("name", "")

            if "datePublished" in data:
                year_match = re.search(r"(\d{4})", data["datePublished"])
                if year_match:
                    meta["date"] = year_match.group(1)

            if "image" in data:
                meta["artwork_url"] = data["image"]

        except (json.JSONDecodeError, KeyError):
            pass

    if not meta.get("title"):
        name_section = soup.find("h2", class_="trackTitle")
        if name_section:
            meta["title"] = name_section.get_text(strip=True)

    if not meta.get("artist"):
        artist_span = soup.find("span", itemprop="byArtist")
        if artist_span:
            meta["artist"] = artist_span.get_text(strip=True)

    if not meta.get("artwork_url"):
        og_image = soup.find("meta", property="og:image")
        if og_image:
            meta["artwork_url"] = og_image.get("content", "")

    tag_els = soup.select(".tralbumData.tralbum-tags a.tag")
    if tag_els:
        tags = [t.get_text(strip=True) for t in tag_els]
        meta["genre"] = " / ".join(tags[:3])

    return meta


def apple_music_hires_artwork(url):
    """Convert any Apple Music artwork URL to 1200x1200."""
    if not url:
        return ""
    return re.sub(r"/\d+x\d+[^/]*\.\w+$", "/1200x1200bb.jpg", url)


def scrape_apple_music(url):
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")

    meta = {}
    is_album = "/album/" in url

    # --- LD+JSON (works for songs, partial for albums) ---
    ld_json = soup.find("script", type="application/ld+json")
    if ld_json:
        try:
            data = json.loads(ld_json.string)
            meta["title"] = data.get("name", "")

            if "datePublished" in data:
                year_match = re.search(r"(\d{4})", data["datePublished"])
                if year_match:
                    meta["date"] = year_match.group(1)

            audio = data.get("audio", {})

            if audio.get("byArtist"):
                meta["artist"] = " / ".join(
                    a.get("name", "") for a in audio["byArtist"]
                )

            album_info = audio.get("inAlbum", {})
            if album_info:
                meta["album"] = album_info.get("name", "")
                if album_info.get("byArtist"):
                    meta["albumartist"] = " / ".join(
                        a.get("name", "") for a in album_info["byArtist"]
                    )
                meta["artwork_url"] = apple_music_hires_artwork(
                    album_info.get("image", "")
                )

            if not meta.get("artwork_url"):
                meta["artwork_url"] = apple_music_hires_artwork(
                    data.get("image", "")
                )

            genres = audio.get("genre", [])
            if isinstance(genres, list):
                genres = [g for g in genres if g.lower() != "music"]
                if genres:
                    meta["genre"] = " / ".join(genres)

        except (json.JSONDecodeError, KeyError):
            pass

    # --- OG tag fallbacks ---
    if not meta.get("title"):
        og_title = soup.find("meta", property="og:title")
        if og_title:
            title_text = og_title.get("content", "")
            by_split = title_text.split(" by ")
            if by_split:
                meta["title"] = by_split[0].strip()

    if not meta.get("artwork_url"):
        og_image = soup.find("meta", property="og:image")
        if og_image:
            meta["artwork_url"] = apple_music_hires_artwork(
                og_image.get("content", "")
            )

    if not meta.get("genre"):
        og_desc = soup.find("meta", property="og:description")
        if og_desc:
            desc = og_desc.get("content", "")
            meta["_description"] = desc

    if not meta.get("date"):
        rel = soup.find("meta", property="music:release_date")
        if rel:
            ym = re.search(r"(\d{4})", rel.get("content", ""))
            if ym:
                meta["date"] = ym.group(1)

    # --- Extract artist name from og:title ("Album by Artist on Apple Music") ---
    if not meta.get("artist"):
        og_title = soup.find("meta", property="og:title")
        if og_title:
            parts = og_title.get("content", "").split(" by ")
            if len(parts) >= 2:
                artist_part = parts[-1].replace(" on Apple\xa0Music", "").replace(" on Apple Music", "").strip()
                meta["artist"] = artist_part

    # --- Album: build tracklist from music:song meta tags + iTunes API ---
    if is_album:
        content_tag = (
            soup.find("meta", attrs={"name": "apple:content_id"})
            or soup.find("meta", property="apple:content_id")
        )
        album_id = content_tag.get("content", "") if content_tag else ""
        if not album_id:
            m = re.search(r"/(\d+)(?:\?|$)", url)
            if m:
                album_id = m.group(1)

        # Get album-level metadata from iTunes API
        if album_id:
            album_meta = _itunes_lookup_album(album_id)
            if album_meta:
                meta["albumartist"] = album_meta.get("artistName", "")
                if not meta.get("artist"):
                    meta["artist"] = meta["albumartist"]
                if not meta.get("genre"):
                    meta["genre"] = album_meta.get("primaryGenreName", "")
                if not meta.get("artwork_url"):
                    art = album_meta.get("artworkUrl100", "")
                    meta["artwork_url"] = apple_music_hires_artwork(art)

        song_tags = soup.find_all("meta", property="music:song")
        song_ids = []
        for tag in song_tags:
            song_url = tag.get("content", "")
            m = re.search(r"/(\d+)$", song_url)
            if m:
                song_ids.append(m.group(1))

        if song_ids:
            tracklist = _itunes_lookup_songs(song_ids)
            if tracklist:
                meta["tracklist"] = tracklist

        meta["album"] = meta.get("title", "")

    else:
        # Single song — track number
        track_meta = soup.find("meta", property="music:album:track")
        if track_meta:
            meta["tracknumber"] = track_meta.get("content", "")

    meta["source"] = "apple_music"
    return meta


def _itunes_lookup_album(album_id):
    """Fetch album metadata from the iTunes Search API."""
    try:
        resp = requests.get(
            f"https://itunes.apple.com/lookup?id={album_id}&country=us",
            timeout=10,
        )
        data = resp.json()
        for r in data.get("results", []):
            if r.get("wrapperType") == "collection":
                return r
    except Exception:
        pass
    return None


def _itunes_lookup_songs(song_ids):
    """Batch-lookup song titles/artists from the iTunes Search API."""
    tracklist = []
    # iTunes API accepts up to 200 comma-separated IDs
    ids_str = ",".join(song_ids)
    try:
        resp = requests.get(
            f"https://itunes.apple.com/lookup?id={ids_str}&country=us",
            timeout=15,
        )
        data = resp.json()
        for r in data.get("results", []):
            if r.get("wrapperType") == "track":
                dur_ms = r.get("trackTimeMillis", 0)
                mins = dur_ms // 60000
                secs = (dur_ms % 60000) // 1000
                tracklist.append({
                    "position": str(r.get("trackNumber", "")),
                    "title": r.get("trackName", ""),
                    "artist": r.get("artistName", ""),
                    "duration": f"{mins}:{secs:02d}",
                })
    except Exception:
        pass
    return tracklist


SPOTIFY_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
}


def scrape_spotify(url):
    """Scrape metadata from a Spotify track or album URL."""
    resp = requests.get(url, headers=SPOTIFY_HEADERS, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")

    meta = {}
    is_album = "/album/" in url

    # og:title — "Track Name" or "Album Name - Type by Artist | Spotify"
    og_title = soup.find("meta", property="og:title")
    if og_title:
        raw_title = og_title.get("content", "")
        # Album titles: "Album - compilation by Artist | Spotify"
        # Track titles: "Track Name"
        cleaned = raw_title.split(" | Spotify")[0].strip()
        if is_album:
            # "Anokha - Soundz... - Compilation by Various Artists"
            by_split = cleaned.rsplit(" by ", 1)
            if len(by_split) == 2:
                album_part = by_split[0].strip()
                # Remove trailing " - compilation", " - Album", etc.
                album_part = re.sub(r"\s*-\s*(compilation|album|single|ep)\s*$", "", album_part, flags=re.I)
                meta["album"] = album_part
                meta["albumartist"] = by_split[1].strip()
                meta["artist"] = meta["albumartist"]
            else:
                meta["album"] = cleaned
        else:
            meta["title"] = cleaned

    # og:description — "Artist · Album · Song · Year"
    og_desc = soup.find("meta", property="og:description")
    if og_desc:
        desc = og_desc.get("content", "")
        parts = [p.strip() for p in desc.split("·")]
        if not is_album and len(parts) >= 2:
            meta["artist"] = parts[0]
            meta["album"] = parts[1]

    # og:image — high-res artwork
    og_image = soup.find("meta", property="og:image")
    if og_image:
        meta["artwork_url"] = og_image.get("content", "")

    def spot_meta(name):
        return (soup.find("meta", property=name) or soup.find("meta", attrs={"name": name}))

    rel = spot_meta("music:release_date")
    if rel:
        ym = re.search(r"(\d{4})", rel.get("content", ""))
        if ym:
            meta["date"] = ym.group(1)

    mus_desc = spot_meta("music:musician_description")
    if mus_desc and not is_album:
        meta["artist"] = mus_desc.get("content", "")

    track_tag = spot_meta("music:album:track")
    if track_tag:
        meta["tracknumber"] = track_tag.get("content", "")

    # Album: build tracklist from music:song tags + oEmbed
    if is_album:
        song_tags = (
            soup.find_all("meta", property="music:song")
            or soup.find_all("meta", attrs={"name": "music:song"})
        )
        song_urls = []
        for tag in song_tags:
            song_url = tag.get("content", "")
            if song_url and "/track/" in song_url:
                song_urls.append(song_url)

        if song_urls:
            tracklist = _spotify_oembed_tracklist(song_urls)
            if tracklist:
                meta["tracklist"] = tracklist

        if not meta.get("title"):
            meta["title"] = meta.get("album", "")

    meta["source"] = "spotify"
    return meta


def _spotify_oembed_tracklist(song_urls):
    """Fetch track titles from Spotify oEmbed for a list of song URLs."""
    tracklist = []
    for i, url in enumerate(song_urls, 1):
        try:
            resp = requests.get(
                "https://open.spotify.com/oembed",
                params={"url": url},
                timeout=8,
            )
            data = resp.json()
            tracklist.append({
                "position": str(i),
                "title": data.get("title", f"Track {i}"),
                "artist": "",
                "duration": "",
                "url": url,
            })
        except Exception:
            tracklist.append({"position": str(i), "title": f"Track {i}", "artist": "", "duration": ""})
    return tracklist


def parse_discogs_url(url):
    m = re.search(r"discogs\.com/(master|release)/(\d+)", url)
    if m:
        return m.group(1), m.group(2)
    return None, None


def fetch_discogs(url):
    rtype, rid = parse_discogs_url(url)
    if not rtype or not rid:
        return {}

    api_url = f"https://api.discogs.com/{'masters' if rtype == 'master' else 'releases'}/{rid}"
    resp = requests.get(api_url, headers=DISCOGS_HEADERS, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    artists = " / ".join(a["name"] for a in data.get("artists", []))
    album_title = data.get("title", "")
    year = str(data.get("year", ""))

    genres = data.get("genres", [])
    styles = data.get("styles", [])
    genre_str = " / ".join(genres + styles)

    images = data.get("images", [])
    artwork_url = ""
    if images:
        primary = next((i for i in images if i.get("type") == "primary"), images[0])
        artwork_url = primary.get("uri", "")

    tracklist = []
    for t in data.get("tracklist", []):
        if t.get("type_") == "track":
            tracklist.append({
                "position": t.get("position", ""),
                "title": t.get("title", ""),
                "duration": t.get("duration", ""),
            })

    label = ""
    catno = ""
    if rtype == "release":
        labels = data.get("labels", [])
        if labels:
            label = labels[0].get("name", "")
            catno = labels[0].get("catno", "")
    elif data.get("main_release_url"):
        try:
            rel_resp = requests.get(data["main_release_url"], headers=DISCOGS_HEADERS, timeout=10)
            rel_data = rel_resp.json()
            labels = rel_data.get("labels", [])
            if labels:
                label = labels[0].get("name", "")
                catno = labels[0].get("catno", "")
        except Exception:
            pass

    meta = {
        "artist": artists,
        "albumartist": artists,
        "album": album_title,
        "date": year,
        "genre": genre_str,
        "artwork_url": artwork_url,
        "tracklist": tracklist,
        "source": "discogs",
    }
    if label:
        meta["label"] = label
    if catno:
        meta["catno"] = catno
    if len(tracklist) == 1:
        meta["title"] = tracklist[0]["title"]

    return meta


def scrape_generic(url):
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")

    meta = {}
    for prop, key in [("og:title", "title"), ("og:image", "artwork_url"),
                       ("og:description", "comment"), ("music:musician", "artist")]:
        tag = soup.find("meta", property=prop) or soup.find("meta", attrs={"name": prop})
        if tag:
            meta[key] = tag.get("content", "")

    if not meta.get("title"):
        title_tag = soup.find("title")
        if title_tag:
            meta["title"] = title_tag.get_text(strip=True)

    return meta


def fetch_artwork(url):
    if not url:
        return None, None
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    content_type = resp.headers.get("Content-Type", "image/jpeg").split(";")[0]
    return resp.content, content_type


def search_itunes(query, limit=8):
    """Search the iTunes/Apple Music catalogue."""
    results = []
    try:
        resp = requests.get(
            "https://itunes.apple.com/search",
            params={"term": query, "entity": "song", "limit": limit, "country": "us"},
            timeout=10,
        )
        data = resp.json()
        for r in data.get("results", []):
            art_url = r.get("artworkUrl100", "")
            results.append({
                "title": r.get("trackName", ""),
                "artist": r.get("artistName", ""),
                "album": r.get("collectionName", ""),
                "year": str(r.get("releaseDate", ""))[:4],
                "artwork_thumb": art_url,
                "url": r.get("trackViewUrl", ""),
                "source": "apple_music",
            })
    except Exception:
        pass
    return results


def search_discogs(query, limit=5):
    """Search the Discogs catalogue."""
    results = []
    try:
        resp = requests.get(
            "https://api.discogs.com/database/search",
            params={"q": query, "type": "release", "per_page": limit},
            headers=DISCOGS_HEADERS,
            timeout=10,
        )
        data = resp.json()
        for r in data.get("results", []):
            labels = r.get("label", [])
            uri = r.get("uri", "")
            discogs_url = f"https://www.discogs.com{uri}" if uri else ""
            results.append({
                "title": r.get("title", ""),
                "artist": "",
                "album": r.get("title", ""),
                "year": str(r.get("year", "")),
                "artwork_thumb": r.get("thumb", ""),
                "url": discogs_url,
                "source": "discogs",
                "label": labels[0] if labels else "",
            })
    except Exception:
        pass
    return results


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return app.send_static_file("index.html")


@app.route("/fix")
def fix_page():
    return app.send_static_file("fix.html")


@app.route("/api/search")
def search():
    """Search iTunes + Discogs for a track by query string."""
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"results": []})

    itunes = search_itunes(q, limit=8)
    discogs = search_discogs(q, limit=5)

    # Interleave: iTunes results first, then Discogs, de-duped by rough title match
    seen = set()
    combined = []
    for r in itunes + discogs:
        key = (r["title"].lower().strip(), r.get("artist", "").lower().strip())
        if key not in seen:
            seen.add(key)
            combined.append(r)

    return jsonify({"results": combined})


@app.route("/api/settings", methods=["GET"])
def get_settings():
    cfg = load_config()
    cfg["source_dir_resolved"] = resolve(cfg["source_dir"])
    cfg["destination_dir_resolved"] = resolve(cfg["destination_dir"])
    return jsonify(cfg)


@app.route("/api/settings", methods=["POST"])
def update_settings():
    data = request.get_json()
    cfg = load_config()

    if "source_dir" in data:
        cfg["source_dir"] = data["source_dir"]
    if "destination_dir" in data:
        cfg["destination_dir"] = data["destination_dir"]

    save_config(cfg)

    cfg["source_dir_resolved"] = resolve(cfg["source_dir"])
    cfg["destination_dir_resolved"] = resolve(cfg["destination_dir"])
    return jsonify(cfg)


@app.route("/api/browse")
def browse():
    cfg = load_config()
    directory = request.args.get("dir", cfg["source_dir"])
    directory = resolve(directory)
    if not os.path.isdir(directory):
        return jsonify({"error": f"Directory not found: {directory}"}), 404

    files = []
    for f in sorted(Path(directory).iterdir()):
        if f.suffix.lower() in (".mkv", ".mp4", ".mov", ".avi", ".webm"):
            files.append({
                "name": f.name,
                "path": str(f),
                "size_mb": round(f.stat().st_size / (1024 * 1024), 1),
            })
    return jsonify({"directory": directory, "files": files})


@app.route("/api/probe", methods=["POST"])
def probe():
    data = request.get_json()
    filepath = data.get("filepath")
    if not filepath or not os.path.isfile(filepath):
        return jsonify({"error": "File not found"}), 404

    info = run_ffprobe(filepath)
    stream = info["streams"][0] if info.get("streams") else {}
    fmt = info.get("format", {})
    return jsonify({
        "codec": stream.get("codec_name"),
        "sample_rate": stream.get("sample_rate"),
        "channels": stream.get("channels"),
        "duration": stream.get("duration") or fmt.get("duration"),
    })


@app.route("/api/analyse", methods=["POST"])
def analyse():
    data = request.get_json()
    filepath = data.get("filepath")
    if not filepath or not os.path.isfile(filepath):
        return jsonify({"error": "File not found"}), 404

    try:
        result = analyse_loudness(filepath)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/fetch-metadata", methods=["POST"])
def fetch_metadata():
    data = request.get_json()
    url = (data.get("url") or "").strip()
    track_name = (data.get("track_name") or "").strip()

    meta = {}

    if url:
        try:
            if "bandcamp.com" in url:
                meta = scrape_bandcamp(url)
            elif "discogs.com" in url:
                meta = fetch_discogs(url)
            elif "music.apple.com" in url:
                meta = scrape_apple_music(url)
            elif "spotify.com" in url or "spotify.link" in url:
                meta = scrape_spotify(url)
            else:
                meta = scrape_generic(url)
        except Exception as e:
            meta["_warning"] = f"Scrape failed: {e}"

    if track_name and not meta.get("title"):
        meta["title"] = track_name

    return jsonify(meta)


@app.route("/api/fetch-artwork")
def fetch_artwork_route():
    url = request.args.get("url", "")
    if not url:
        return jsonify({"error": "No URL"}), 400
    try:
        img_bytes, content_type = fetch_artwork(url)
        return app.response_class(img_bytes, mimetype=content_type)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/extract", methods=["POST"])
def extract():
    data = request.get_json()
    cfg = load_config()

    filepath = data.get("filepath")
    metadata = data.get("metadata", {})
    artwork_url = data.get("artwork_url", "")

    if not filepath or not os.path.isfile(filepath):
        return jsonify({"error": "Source file not found"}), 404

    title = metadata.get("title", Path(filepath).stem)
    safe_title = re.sub(r'[<>:"/\\|?*]', '', title).strip()
    filename = f"{safe_title}.flac"

    output_dir = os.path.dirname(filepath)
    output_path = os.path.join(output_dir, filename)

    if os.path.exists(output_path):
        return jsonify({"error": f"Output file already exists: {output_path}"}), 409

    normalise = data.get("normalise", False)
    loudnorm_params = data.get("loudnorm_params")

    try:
        source_codec = extract_flac(filepath, output_path, normalise, loudnorm_params)
    except subprocess.CalledProcessError as e:
        return jsonify({"error": f"ffmpeg failed: {e.stderr}"}), 500

    artwork_bytes, artwork_mime = None, None
    if artwork_url:
        try:
            artwork_bytes, artwork_mime = fetch_artwork(artwork_url)
        except Exception:
            pass

    apply_metadata(output_path, metadata, artwork_bytes, artwork_mime)

    # Copy to destination folder
    dest_dir = resolve(cfg["destination_dir"])
    copied_to = None
    copy_error = None

    if dest_dir:
        try:
            os.makedirs(dest_dir, exist_ok=True)
            dest_path = os.path.join(dest_dir, filename)
            shutil.copy2(output_path, dest_path)
            copied_to = dest_path
        except Exception as e:
            copy_error = str(e)

    # Optionally trash source
    delete_source = data.get("delete_source", False)
    source_trashed = False
    source_trash_error = None

    if delete_source:
        try:
            trash_file(filepath)
            source_trashed = True
        except Exception as e:
            source_trash_error = str(e)

    stat = os.stat(output_path)

    log_extraction({
        "filename": filename,
        "source_file": filepath,
        "output_path": output_path,
        "copied_to": copied_to,
        "metadata": metadata,
        "artwork_url": artwork_url,
        "normalised": normalise,
        "source_codec": source_codec,
    })

    result = {
        "output_path": output_path,
        "size_mb": round(stat.st_size / (1024 * 1024), 1),
        "source_codec": source_codec,
        "title": safe_title,
        "source_trashed": source_trashed,
        "normalised": normalise,
    }
    if copied_to:
        result["copied_to"] = copied_to
    if copy_error:
        result["copy_error"] = copy_error
    if source_trash_error:
        result["source_trash_error"] = source_trash_error

    return jsonify(result)


@app.route("/api/log")
def get_log():
    return jsonify(load_log())


@app.route("/api/fix-artwork", methods=["POST"])
def fix_artwork():
    """Re-embed existing artwork with correct dimensions."""
    data = request.get_json()
    filepath = data.get("filepath")
    if not filepath or not os.path.isfile(filepath):
        return jsonify({"error": "File not found"}), 404

    ext = os.path.splitext(filepath)[1].lower()
    if ext != ".flac":
        return jsonify({"error": "Only FLAC files supported for artwork fix"}), 400

    try:
        audio = FLAC(filepath)
        if not audio.pictures:
            return jsonify({"error": "No artwork to fix"}), 400

        pic = audio.pictures[0]
        w, h = _image_dimensions(pic.data)
        if w == pic.width and h == pic.height and w > 0:
            return jsonify({"status": "ok", "message": "Dimensions already correct", "width": w, "height": h})

        pic.width = w
        pic.height = h
        audio.clear_pictures()
        audio.add_picture(pic)
        audio.save()
        return jsonify({"status": "ok", "message": f"Fixed artwork dimensions to {w}x{h}", "width": w, "height": h})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/retag", methods=["POST"])
def retag():
    """Re-apply metadata and artwork to an existing FLAC from a log entry."""
    data = request.get_json()
    filepath = data.get("filepath")
    metadata = data.get("metadata", {})
    artwork_url = data.get("artwork_url", "")

    if not filepath or not os.path.isfile(filepath):
        return jsonify({"error": f"File not found: {filepath}"}), 404

    artwork_bytes, artwork_mime = None, None
    if artwork_url:
        try:
            artwork_bytes, artwork_mime = fetch_artwork(artwork_url)
        except Exception as e:
            return jsonify({"error": f"Artwork fetch failed: {e}"}), 500

    try:
        apply_metadata(filepath, metadata, artwork_bytes, artwork_mime)
    except Exception as e:
        return jsonify({"error": f"Tagging failed: {e}"}), 500

    return jsonify({"status": "ok", "filepath": filepath})


@app.route("/api/retag-batch", methods=["POST"])
def retag_batch():
    """Re-apply metadata+artwork to multiple files from the processing log."""
    data = request.get_json()
    target_dir = data.get("target_dir", "")
    entry_indices = data.get("entries")  # list of log indices, or None for all

    if not target_dir:
        return jsonify({"error": "No target directory"}), 400
    target_dir = resolve(target_dir)
    if not os.path.isdir(target_dir):
        return jsonify({"error": f"Directory not found: {target_dir}"}), 404

    entries = load_log()
    if entry_indices is not None:
        entries = [entries[i] for i in entry_indices if i < len(entries)]

    results = []
    for entry in entries:
        filename = entry.get("filename", "")
        filepath = os.path.join(target_dir, filename)

        if not os.path.isfile(filepath):
            results.append({"filename": filename, "status": "skipped", "reason": "not found"})
            continue

        metadata = entry.get("metadata", {})
        artwork_url = entry.get("artwork_url", "")

        artwork_bytes, artwork_mime = None, None
        if artwork_url:
            try:
                artwork_bytes, artwork_mime = fetch_artwork(artwork_url)
            except Exception:
                pass

        try:
            apply_metadata(filepath, metadata, artwork_bytes, artwork_mime)
            results.append({"filename": filename, "status": "ok"})
        except Exception as e:
            results.append({"filename": filename, "status": "error", "reason": str(e)})

    return jsonify({"results": results})


@app.route("/api/browse-audio")
def browse_audio():
    cfg = load_config()
    directory = request.args.get("dir", cfg["destination_dir"])
    directory = resolve(directory)
    if not os.path.isdir(directory):
        return jsonify({"error": f"Directory not found: {directory}"}), 404

    files = []
    for f in sorted(Path(directory).iterdir()):
        if f.suffix.lower() in AUDIO_EXTENSIONS:
            files.append({
                "name": f.name,
                "path": str(f),
                "size_mb": round(f.stat().st_size / (1024 * 1024), 1),
            })
    return jsonify({"directory": directory, "files": files})


# Keep old endpoint as alias for backwards compatibility
app.add_url_rule("/api/browse-flacs", endpoint="browse_flacs_compat", view_func=browse_audio)


@app.route("/api/read-tags", methods=["POST"])
def read_tags():
    """Read metadata from any supported audio file."""
    data = request.get_json()
    filepath = data.get("filepath")
    if not filepath or not os.path.isfile(filepath):
        return jsonify({"error": "File not found"}), 404

    ext = os.path.splitext(filepath)[1].lower()

    try:
        if ext == ".flac":
            return jsonify(_read_flac_tags(filepath))
        elif ext == ".mp3":
            return jsonify(_read_mp3_tags(filepath))
        elif ext in (".m4a", ".mp4", ".aac"):
            return jsonify(_read_mp4_tags(filepath))
        elif ext in (".ogg", ".oga"):
            return jsonify(_read_vorbis_tags(filepath))
        else:
            return jsonify(_read_generic_tags(filepath))
    except Exception as e:
        return jsonify({"error": f"Cannot read tags: {e}"}), 400


def _read_flac_tags(filepath):
    audio = FLAC(filepath)
    vorbis_reverse = {
        "title": "title", "artist": "artist", "albumartist": "albumartist",
        "album": "album", "date": "date", "genre": "genre", "comment": "comment",
        "organization": "label", "catalognumber": "catno", "tracknumber": "tracknumber",
    }
    meta = {}
    for vorbis_key, field in vorbis_reverse.items():
        vals = audio.get(vorbis_key, [])
        if vals:
            meta[field] = vals[0]
    meta["has_artwork"] = len(audio.pictures) > 0
    meta["format"] = "FLAC"
    return meta


def _read_mp3_tags(filepath):
    audio = MP3(filepath, ID3=ID3)
    meta = {"format": "MP3"}
    if audio.tags is None:
        meta["has_artwork"] = False
        return meta
    t = audio.tags
    frame_map = {
        "TIT2": "title", "TPE1": "artist", "TPE2": "albumartist",
        "TALB": "album", "TDRC": "date", "TCON": "genre", "TPUB": "label",
        "TRCK": "tracknumber",
    }
    for frame_id, field in frame_map.items():
        frame = t.getall(frame_id)
        if frame:
            meta[field] = str(frame[0])
    comm = t.getall("COMM")
    if comm:
        meta["comment"] = str(comm[0])
    catno = t.getall("TXXX:CATALOGNUMBER")
    if catno:
        meta["catno"] = str(catno[0])
    meta["has_artwork"] = bool(t.getall("APIC"))
    return meta


def _read_mp4_tags(filepath):
    audio = MP4(filepath)
    meta = {"format": "AAC/M4A"}
    if audio.tags is None:
        meta["has_artwork"] = False
        return meta
    mp4_reverse = {
        "\xa9nam": "title", "\xa9ART": "artist", "aART": "albumartist",
        "\xa9alb": "album", "\xa9day": "date", "\xa9gen": "genre",
        "\xa9cmt": "comment",
    }
    for atom, field in mp4_reverse.items():
        vals = audio.tags.get(atom)
        if vals:
            meta[field] = str(vals[0])
    trkn = audio.tags.get("trkn")
    if trkn:
        meta["tracknumber"] = str(trkn[0][0])
    meta["has_artwork"] = bool(audio.tags.get("covr"))
    return meta


def _read_vorbis_tags(filepath):
    audio = OggVorbis(filepath)
    vorbis_reverse = {
        "title": "title", "artist": "artist", "albumartist": "albumartist",
        "album": "album", "date": "date", "genre": "genre", "comment": "comment",
        "organization": "label", "catalognumber": "catno", "tracknumber": "tracknumber",
    }
    meta = {"format": "OGG"}
    for vorbis_key, field in vorbis_reverse.items():
        vals = audio.get(vorbis_key, [])
        if vals:
            meta[field] = vals[0]
    meta["has_artwork"] = bool(audio.get("metadata_block_picture"))
    return meta


def _read_generic_tags(filepath):
    audio = mutagen.File(filepath, easy=True)
    if audio is None:
        return {"error": "Unsupported format", "has_artwork": False}
    meta = {"format": type(audio).__name__}
    easy_map = {"title": "title", "artist": "artist", "albumartist": "albumartist",
                "album": "album", "date": "date", "genre": "genre"}
    for tag, field in easy_map.items():
        vals = audio.get(tag, [])
        if vals:
            meta[field] = vals[0]
    meta["has_artwork"] = False
    return meta


@app.route("/inspect")
def inspect_page():
    return app.send_static_file("inspect.html")


@app.route("/api/read-tags-full", methods=["POST"])
def read_tags_full():
    """Read all metadata from an audio file including artwork details."""
    data = request.get_json()
    filepath = data.get("filepath")
    if not filepath or not os.path.isfile(filepath):
        return jsonify({"error": "File not found"}), 404

    ext = os.path.splitext(filepath)[1].lower()
    stat = os.stat(filepath)

    try:
        if ext == ".flac":
            meta = _read_flac_tags(filepath)
            audio = FLAC(filepath)
            if audio.pictures:
                pic = audio.pictures[0]
                meta["artwork_info"] = {
                    "mime": pic.mime,
                    "size_bytes": len(pic.data),
                    "width": pic.width,
                    "height": pic.height,
                    "type": pic.type,
                }
        elif ext == ".mp3":
            meta = _read_mp3_tags(filepath)
            audio = MP3(filepath, ID3=ID3)
            if audio.tags:
                apics = audio.tags.getall("APIC")
                if apics:
                    pic = apics[0]
                    meta["artwork_info"] = {
                        "mime": pic.mime,
                        "size_bytes": len(pic.data),
                        "type": pic.type,
                    }
        elif ext in (".m4a", ".mp4", ".aac"):
            meta = _read_mp4_tags(filepath)
            audio = MP4(filepath)
            if audio.tags and audio.tags.get("covr"):
                covr = audio.tags["covr"][0]
                fmt_name = "JPEG" if covr.imageformat == MP4Cover.FORMAT_JPEG else "PNG"
                meta["artwork_info"] = {
                    "mime": f"image/{'jpeg' if fmt_name == 'JPEG' else 'png'}",
                    "size_bytes": len(bytes(covr)),
                    "format": fmt_name,
                }
        elif ext in (".ogg", ".oga"):
            meta = _read_vorbis_tags(filepath)
        else:
            meta = _read_generic_tags(filepath)
    except Exception as e:
        return jsonify({"error": f"Cannot read tags: {e}"}), 400

    meta["file_info"] = {
        "path": filepath,
        "name": os.path.basename(filepath),
        "size_mb": round(stat.st_size / (1024 * 1024), 1),
        "extension": ext,
    }

    return jsonify(meta)


@app.route("/api/embedded-artwork-img")
def embedded_artwork_img():
    """GET endpoint to serve embedded artwork (for img src)."""
    filepath = request.args.get("path", "")
    return _serve_embedded_artwork(filepath)


@app.route("/api/embedded-artwork", methods=["POST"])
def embedded_artwork():
    """POST endpoint to serve embedded artwork."""
    data = request.get_json()
    filepath = data.get("filepath", "")
    return _serve_embedded_artwork(filepath)


def _serve_embedded_artwork(filepath):
    if not filepath or not os.path.isfile(filepath):
        return jsonify({"error": "File not found"}), 404

    ext = os.path.splitext(filepath)[1].lower()

    try:
        if ext == ".flac":
            audio = FLAC(filepath)
            if audio.pictures:
                pic = audio.pictures[0]
                return app.response_class(pic.data, mimetype=pic.mime)
        elif ext == ".mp3":
            audio = MP3(filepath, ID3=ID3)
            if audio.tags:
                apics = audio.tags.getall("APIC")
                if apics:
                    return app.response_class(apics[0].data, mimetype=apics[0].mime)
        elif ext in (".m4a", ".mp4", ".aac"):
            audio = MP4(filepath)
            if audio.tags and audio.tags.get("covr"):
                covr = audio.tags["covr"][0]
                mime = "image/jpeg" if covr.imageformat == MP4Cover.FORMAT_JPEG else "image/png"
                return app.response_class(bytes(covr), mimetype=mime)
        elif ext in (".ogg", ".oga"):
            import base64
            audio = OggVorbis(filepath)
            pics = audio.get("metadata_block_picture", [])
            if pics:
                pic = Picture(base64.b64decode(pics[0]))
                return app.response_class(pic.data, mimetype=pic.mime)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify({"error": "No embedded artwork"}), 404


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5123, debug=True)
