"""Web scrapers and search functions for music metadata services."""

__all__ = [
    'HEADERS', 'DISCOGS_HEADERS', 'SPOTIFY_HEADERS', '_response_text_utf8',
    '_ld_json_script_text', 'scrape_bandcamp', '_bandcamp_clean_result_url',
    'search_bandcamp', 'apple_music_hires_artwork', 'scrape_apple_music',
    '_itunes_lookup_album', '_itunes_lookup_songs', 'search_itunes',
    'scrape_spotify', '_spotify_oembed_tracklist', '_soundcloud_hydration_list',
    '_soundcloud_artwork_hires', '_soundcloud_api_client_cache',
    '_SOUNDSCLOUD_CLIENT_ID_TTL_SEC', '_soundcloud_api_client_id',
    'scrape_soundcloud', 'search_soundcloud', '_beatport_next_track',
    'scrape_beatport', 'search_beatport', 'parse_discogs_url', 'fetch_discogs', 'search_discogs',
    'scrape_generic', 'fetch_artwork',
]

import json
import re
import time
from urllib.parse import quote_plus, urlunparse, urlparse

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Request headers
# ---------------------------------------------------------------------------

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

DISCOGS_HEADERS = {"User-Agent": "DJMetaManager/1.0 +https://github.com/apj72/dj-meta-manager"}

SPOTIFY_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _response_text_utf8(resp: requests.Response) -> str:
    """
    Decode HTML (or other text) body as UTF-8. Many sites omit charset or default to
    ISO-8859-1 in requests, which mojibakes non-ASCII (e.g. Andre -> AndrA(c)).
    """
    return (resp.content or b"").decode("utf-8", errors="replace")


def _ld_json_script_text(tag) -> str:
    """Raw JSON-LD string from a script tag (BeautifulSoup .string can be None on some trees)."""
    if tag is None:
        return ""
    s = tag.string
    if s is not None and str(s).strip():
        return str(s).strip()
    return (tag.get_text() or "").strip()


# ---------------------------------------------------------------------------
# Bandcamp
# ---------------------------------------------------------------------------

def scrape_bandcamp(url):
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(_response_text_utf8(resp), "lxml")

    meta = {}

    ld_json = soup.find("script", type="application/ld+json")
    if ld_json:
        try:
            data = json.loads(_ld_json_script_text(ld_json))
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


def _bandcamp_clean_result_url(href: str) -> str:
    """Normalize a Bandcamp search link to a stable https URL (no tracking query)."""
    if not (href or "").strip():
        return ""
    p = urlparse(href.strip())
    netloc = (p.netloc or "").lower()
    if "bandcamp.com" not in netloc:
        return ""
    path = (p.path or "").rstrip("/")
    if "/track/" not in path and "/album/" not in path:
        return ""
    return urlunparse(("https", p.netloc, path, "", "", ""))


def search_bandcamp(query, limit=6):
    """
    Search bandcamp.com (public search page). Returns track hits with clean URLs suitable
    for scrape_bandcamp / apply metadata.
    """
    results = []
    q = (query or "").strip()
    if not q or limit < 1:
        return results
    try:
        resp = requests.get(
            "https://bandcamp.com/search",
            params={"q": q},
            headers=HEADERS,
            timeout=18,
        )
        resp.raise_for_status()
        soup = BeautifulSoup(_response_text_utf8(resp), "lxml")
        for li in soup.find_all("li"):
            if len(results) >= limit:
                break
            classes = li.get("class") or []
            if "searchresult" not in classes:
                continue
            artcont = li.find("a", class_="artcont")
            if not artcont or not artcont.get("href"):
                continue
            href = artcont["href"]
            if "/track/" not in href:
                continue
            clean = _bandcamp_clean_result_url(href)
            if not clean:
                continue
            heading = li.find("div", class_="heading")
            title = ""
            if heading:
                ha = heading.find("a")
                if ha:
                    title = ha.get_text(" ", strip=True)
            if not title:
                continue
            subhead = li.find("div", class_="subhead")
            artist, album = "", ""
            if subhead:
                text = re.sub(r"\s+", " ", subhead.get_text(" ", strip=True))
                m = re.search(r"from\s+(.+?)\s+by\s+(.+)$", text, re.I)
                if m:
                    album, artist = m.group(1).strip(), m.group(2).strip()
                else:
                    m2 = re.search(r"\bby\s+(.+)$", text, re.I)
                    if m2:
                        artist = m2.group(1).strip()
            thumb = ""
            art = li.find("div", class_="art")
            if art:
                im = art.find("img")
                if im and (im.get("src") or im.get("data-src")):
                    thumb = (im.get("src") or im.get("data-src") or "").strip()
            year = ""
            rel = li.find("div", class_="released")
            if rel:
                y = re.search(r"(\d{4})", rel.get_text())
                if y:
                    year = y.group(1)
            results.append({
                "title": title,
                "artist": artist,
                "album": album,
                "year": year,
                "artwork_thumb": thumb,
                "url": clean,
                "source": "bandcamp",
            })
    except Exception:
        pass
    return results


# ---------------------------------------------------------------------------
# Apple Music
# ---------------------------------------------------------------------------

def apple_music_hires_artwork(url):
    """Convert any Apple Music artwork URL to 1200x1200."""
    if not url:
        return ""
    return re.sub(r"/\d+x\d+[^/]*\.\w+$", "/1200x1200bb.jpg", url)


def scrape_apple_music(url):
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(_response_text_utf8(resp), "lxml")

    meta = {}
    is_album = "/album/" in url

    # --- LD+JSON (works for songs, partial for albums) ---
    ld_json = soup.find("script", type="application/ld+json")
    if ld_json:
        try:
            data = json.loads(_ld_json_script_text(ld_json))
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
        # Single song -- track number
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
        resp.raise_for_status()
        data = json.loads(resp.content.decode("utf-8", errors="replace"))
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
        resp.raise_for_status()
        data = json.loads(resp.content.decode("utf-8", errors="replace"))
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
            web = (r.get("trackViewUrl") or r.get("collectionViewUrl") or "").strip()
            if not web:
                an = r.get("artistName") or ""
                tn = r.get("trackName") or ""
                t_a = f"{an} {tn}".strip()
                if t_a:
                    web = f"https://music.apple.com/search?term={quote_plus(t_a)}"
            results.append({
                "title": r.get("trackName", ""),
                "artist": r.get("artistName", ""),
                "album": r.get("collectionName", ""),
                "year": str(r.get("releaseDate", ""))[:4],
                "artwork_thumb": art_url,
                "url": web,
                "source": "apple_music",
            })
    except Exception:
        pass
    return results


# ---------------------------------------------------------------------------
# Spotify
# ---------------------------------------------------------------------------

def scrape_spotify(url):
    """Scrape metadata from a Spotify track or album URL."""
    resp = requests.get(url, headers=SPOTIFY_HEADERS, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(_response_text_utf8(resp), "lxml")

    meta = {}
    is_album = "/album/" in url

    # og:title -- "Track Name" or "Album Name - Type by Artist | Spotify"
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

    # og:description -- "Artist . Album . Song . Year"
    og_desc = soup.find("meta", property="og:description")
    if og_desc:
        desc = og_desc.get("content", "")
        parts = [p.strip() for p in desc.split("\xb7")]
        if not is_album and len(parts) >= 2:
            meta["artist"] = parts[0]
            meta["album"] = parts[1]

    # og:image -- high-res artwork
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


# ---------------------------------------------------------------------------
# SoundCloud
# ---------------------------------------------------------------------------

def _soundcloud_hydration_list(html: str):
    """Parse ``window.__sc_hydration = [...]`` from a SoundCloud track page."""
    marker = "window.__sc_hydration = "
    i = html.find(marker)
    if i < 0:
        return None
    j = i + len(marker)
    while j < len(html) and html[j] in " \t\r\n":
        j += 1
    try:
        data, _end = json.JSONDecoder().raw_decode(html, j)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, list) else None


def _soundcloud_artwork_hires(url: str) -> str:
    if not url:
        return ""
    return re.sub(r"-large\.(jpg|jpeg|png)(\?[^#]*)?$", r"-t500x500.\1", url, flags=re.I)


_soundcloud_api_client_cache: dict = {"id": "", "ts": 0.0}
_SOUNDSCLOUD_CLIENT_ID_TTL_SEC = 6 * 3600


def _soundcloud_api_client_id() -> str:
    """
    SoundCloud's public web app embeds an API ``client_id`` in ``window.__sc_hydration`` on
    https://soundcloud.com/ . It may rotate; callers should tolerate empty return on failure.
    """
    now = time.time()
    cached = (_soundcloud_api_client_cache.get("id") or "").strip()
    ts = float(_soundcloud_api_client_cache.get("ts") or 0.0)
    if cached and (now - ts) < _SOUNDSCLOUD_CLIENT_ID_TTL_SEC:
        return cached
    try:
        resp = requests.get("https://soundcloud.com/", headers=HEADERS, timeout=18)
        resp.raise_for_status()
        html = _response_text_utf8(resp)
        m = re.search(r"window\.__sc_hydration\s*=\s*(\[.*?\])\s*;", html, re.S)
        if not m:
            return cached
        blob = json.loads(m.group(1))
        for item in blob:
            if not isinstance(item, dict) or item.get("hydratable") != "apiClient":
                continue
            data = item.get("data") if isinstance(item.get("data"), dict) else {}
            new_id = (data.get("id") or "").strip()
            if new_id:
                _soundcloud_api_client_cache["id"] = new_id
                _soundcloud_api_client_cache["ts"] = now
                return new_id
    except (json.JSONDecodeError, OSError, requests.RequestException, TypeError, ValueError):
        pass
    return cached


def scrape_soundcloud(url: str) -> dict:
    """Metadata from a public SoundCloud track URL (embedded ``__sc_hydration`` JSON)."""
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    html = _response_text_utf8(resp)
    blob = _soundcloud_hydration_list(html)
    meta: dict = {"source": "soundcloud"}
    sound = None
    if blob:
        for item in blob:
            if not isinstance(item, dict) or item.get("hydratable") != "sound":
                continue
            d = item.get("data")
            if isinstance(d, dict) and (d.get("title") or "").strip():
                sound = d
                break
    if not sound:
        soup = BeautifulSoup(html, "lxml")
        tw = soup.find("meta", attrs={"property": "twitter:title"})
        if tw and tw.get("content"):
            meta["title"] = tw["content"].strip()
        og = soup.find("meta", property="og:image")
        if og and og.get("content"):
            meta["artwork_url"] = _soundcloud_artwork_hires(og["content"].strip())
        return meta

    meta["title"] = (sound.get("title") or "").strip()
    pm = sound.get("publisher_metadata") if isinstance(sound.get("publisher_metadata"), dict) else {}
    user = sound.get("user") if isinstance(sound.get("user"), dict) else {}
    meta["artist"] = (
        (pm.get("artist") or user.get("username") or user.get("full_name") or "")
    ).strip()
    album_title = pm.get("album_title")
    if album_title:
        meta["album"] = str(album_title).strip()
    g = (sound.get("genre") or "").strip()
    if not g:
        tl = sound.get("tag_list")
        if isinstance(tl, str) and tl.strip():
            g = tl.strip()
    if g:
        meta["genre"] = g
    rd = sound.get("release_date") or sound.get("created_at") or ""
    ym = re.search(r"(\d{4})", str(rd))
    if ym:
        meta["date"] = ym.group(1)
    au = sound.get("artwork_url") or ""
    if au:
        meta["artwork_url"] = _soundcloud_artwork_hires(str(au).strip())
    return meta


def search_soundcloud(query, limit=6):
    """
    Search tracks on soundcloud.com via the same ``api-v2`` endpoint the site uses.
    Results are suitable for ``scrape_soundcloud`` / apply-metadata when the user picks a URL.
    """
    results: list[dict] = []
    q = (query or "").strip()
    if not q or limit < 1:
        return results
    client_id = _soundcloud_api_client_id()
    if not client_id:
        return results
    limit = max(1, min(limit, 25))
    try:
        resp = requests.get(
            "https://api-v2.soundcloud.com/search/tracks",
            params={
                "q": q,
                "limit": limit,
                "linked_partitioning": "true",
                "client_id": client_id,
            },
            headers=HEADERS,
            timeout=22,
        )
        resp.raise_for_status()
        data = resp.json()
        for tr in data.get("collection") or []:
            if len(results) >= limit:
                break
            if not isinstance(tr, dict) or tr.get("kind") != "track":
                continue
            title = (tr.get("title") or "").strip()
            url = (tr.get("permalink_url") or "").strip()
            if not title or not url:
                continue
            user = tr.get("user") if isinstance(tr.get("user"), dict) else {}
            uploader = (user.get("full_name") or user.get("username") or "").strip()
            pm = tr.get("publisher_metadata") if isinstance(tr.get("publisher_metadata"), dict) else {}
            artist = (pm.get("artist") or "").strip() or uploader
            album = (
                (pm.get("album_title") or pm.get("release_title") or "").strip()
            )
            year = ""
            rd = tr.get("release_date") or tr.get("display_date") or tr.get("created_at") or ""
            ym = re.search(r"(\d{4})", str(rd))
            if ym:
                year = ym.group(1)
            thumb = ""
            au = tr.get("artwork_url") or ""
            if au:
                thumb = _soundcloud_artwork_hires(str(au).strip())
            results.append({
                "title": title,
                "artist": artist,
                "album": album,
                "year": year,
                "artwork_thumb": thumb,
                "url": url,
                "source": "soundcloud",
            })
    except Exception:
        pass
    return results


# ---------------------------------------------------------------------------
# Beatport
# ---------------------------------------------------------------------------

def _beatport_next_track(html: str):
    m = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
        html,
        re.DOTALL,
    )
    if not m:
        return None
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError:
        return None
    tr = (data.get("props") or {}).get("pageProps") or {}
    tr = tr.get("track")
    return tr if isinstance(tr, dict) else None


def scrape_beatport(url: str) -> dict:
    """Metadata from a Beatport track page (Next.js ``__NEXT_DATA__``)."""
    if "/track/" not in url.lower():
        return {}
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    html = _response_text_utf8(resp)
    tr = _beatport_next_track(html)
    meta: dict = {"source": "beatport"}
    if not tr:
        return meta

    name = (tr.get("name") or "").strip()
    mix = (tr.get("mix_name") or "").strip()
    if mix and mix.lower() not in ("original mix", "original"):
        meta["title"] = f"{name} ({mix})"
    else:
        meta["title"] = name

    artists = tr.get("artists") or []
    names = []
    if isinstance(artists, list):
        for a in artists:
            if isinstance(a, dict) and (a.get("name") or "").strip():
                names.append(a["name"].strip())
    meta["artist"] = " / ".join(names)

    rel = tr.get("release") if isinstance(tr.get("release"), dict) else {}
    if rel.get("name"):
        meta["album"] = str(rel["name"]).strip()
    lab = rel.get("label") if isinstance(rel.get("label"), dict) else {}
    if lab.get("name"):
        meta["label"] = str(lab["name"]).strip()

    art_url = ""
    rim = rel.get("image") if isinstance(rel.get("image"), dict) else {}
    if rim.get("dynamic_uri"):
        art_url = str(rim["dynamic_uri"]).replace("{w}x{h}", "1400x1400")
    elif rim.get("uri"):
        art_url = str(rim["uri"])
    if not art_url:
        img = tr.get("image") if isinstance(tr.get("image"), dict) else {}
        if img.get("dynamic_uri"):
            art_url = str(img["dynamic_uri"]).replace("{w}x{h}", "1400x1400")
        elif img.get("uri"):
            art_url = str(img["uri"])
    if art_url:
        meta["artwork_url"] = art_url

    g = tr.get("genre") if isinstance(tr.get("genre"), dict) else {}
    if g.get("name"):
        meta["genre"] = str(g["name"]).strip()
    pd = tr.get("publish_date") or ""
    ym = re.search(r"(\d{4})", str(pd))
    if ym:
        meta["date"] = ym.group(1)
    return meta


def search_beatport(query, limit=5):
    """Search Beatport tracks via their search page and __NEXT_DATA__ JSON."""
    results = []
    q = (query or "").strip()
    if not q or limit < 1:
        return results
    try:
        from urllib.parse import quote_plus as _qp
        resp = requests.get(
            f"https://www.beatport.com/search?q={_qp(q)}",
            headers=HEADERS,
            timeout=20,
        )
        resp.raise_for_status()
        html = _response_text_utf8(resp)
        m = re.search(
            r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
            html,
            re.DOTALL,
        )
        if not m:
            return results
        data = json.loads(m.group(1))
        tracks = ((data.get("props") or {}).get("pageProps") or {}).get("dehydratedState", {})
        queries = tracks.get("queries") or []
        for qobj in queries:
            state = qobj.get("state") or {}
            items = state.get("data") or {}
            track_list = items.get("tracks") or items.get("data") or []
            if not isinstance(track_list, list):
                continue
            for tr in track_list:
                if len(results) >= limit:
                    break
                if not isinstance(tr, dict):
                    continue
                name = (tr.get("name") or "").strip()
                if not name:
                    continue
                mix = (tr.get("mix_name") or "").strip()
                title = f"{name} ({mix})" if mix and mix.lower() not in ("original mix", "original") else name
                artists_list = tr.get("artists") or []
                artist_names = []
                if isinstance(artists_list, list):
                    for a in artists_list:
                        if isinstance(a, dict) and (a.get("name") or "").strip():
                            artist_names.append(a["name"].strip())
                artist = " / ".join(artist_names)
                slug = tr.get("slug") or ""
                tid = tr.get("id") or ""
                url = f"https://www.beatport.com/track/{slug}/{tid}" if slug and tid else ""
                art_url = ""
                rim = tr.get("release", {})
                if isinstance(rim, dict):
                    img = rim.get("image") or {}
                    if isinstance(img, dict):
                        if img.get("dynamic_uri"):
                            art_url = str(img["dynamic_uri"]).replace("{w}x{h}", "500x500")
                        elif img.get("uri"):
                            art_url = str(img["uri"])
                hit = {
                    "source": "beatport",
                    "title": title,
                    "artist": artist,
                    "url": url,
                }
                if art_url:
                    hit["artwork_url"] = art_url
                label = (rim.get("label") or {}) if isinstance(rim, dict) else {}
                if isinstance(label, dict) and label.get("name"):
                    hit["label"] = str(label["name"]).strip()
                results.append(hit)
            if len(results) >= limit:
                break
    except Exception:
        pass
    return results


# ---------------------------------------------------------------------------
# Discogs
# ---------------------------------------------------------------------------

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
            uri = (r.get("uri") or "").strip()
            if uri.startswith("http://") or uri.startswith("https://"):
                discogs_url = uri
            elif uri:
                discogs_url = f"https://www.discogs.com{uri}" if uri.startswith("/") else f"https://www.discogs.com/{uri}"
            else:
                rid, rty = r.get("id"), (r.get("type") or "").lower()
                if rty == "release" and rid is not None:
                    discogs_url = f"https://www.discogs.com/release/{rid}"
                else:
                    discogs_url = ""
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
# Generic scraper & artwork fetch
# ---------------------------------------------------------------------------

def scrape_generic(url):
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(_response_text_utf8(resp), "lxml")

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
