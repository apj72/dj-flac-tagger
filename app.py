import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from flask import Flask, jsonify, request
from mutagen.flac import FLAC, Picture

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


def apply_metadata(flac_path, metadata, artwork_bytes=None, artwork_mime=None):
    audio = FLAC(flac_path)

    tag_map = {
        "title": "title",
        "artist": "artist",
        "albumartist": "albumartist",
        "album": "album",
        "date": "date",
        "genre": "genre",
        "comment": "comment",
        "tracknumber": "tracknumber",
        "label": "organization",
        "catno": "catalognumber",
    }

    for key, vorbis_key in tag_map.items():
        val = metadata.get(key)
        if val:
            audio[vorbis_key] = [val]

    if artwork_bytes:
        pic = Picture()
        pic.type = 3  # front cover
        pic.mime = artwork_mime or "image/jpeg"
        pic.desc = "Cover"
        pic.data = artwork_bytes
        audio.clear_pictures()
        audio.add_picture(pic)

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


def scrape_apple_music(url):
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")

    meta = {}

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

            artists = audio.get("byArtist", [])
            if artists:
                meta["artist"] = " / ".join(a.get("name", "") for a in artists)

            album_info = audio.get("inAlbum", {})
            if album_info:
                meta["album"] = album_info.get("name", "")
                album_artists = album_info.get("byArtist", [])
                if album_artists:
                    meta["albumartist"] = " / ".join(a.get("name", "") for a in album_artists)

                # High-res artwork: replace size suffix to get 1200x1200
                album_img = album_info.get("image", "")
                if album_img:
                    meta["artwork_url"] = re.sub(r"/\d+x\d+\w*\.\w+$", "/1200x1200bb.jpg", album_img)

            if not meta.get("artwork_url") and data.get("image"):
                meta["artwork_url"] = re.sub(r"/\d+x\d+\w*\.\w+$", "/1200x1200bb.jpg", data["image"])

            genres = audio.get("genre", [])
            if isinstance(genres, list):
                genres = [g for g in genres if g.lower() != "music"]
                if genres:
                    meta["genre"] = " / ".join(genres)

        except (json.JSONDecodeError, KeyError):
            pass

    # Fallback to OG tags
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
            meta["artwork_url"] = og_image.get("content", "")

    # Track number from music:album:track
    track_meta = soup.find("meta", property="music:album:track")
    if track_meta:
        meta["tracknumber"] = track_meta.get("content", "")

    meta["source"] = "apple_music"
    return meta


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


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return app.send_static_file("index.html")


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


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5123, debug=True)
