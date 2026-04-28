"""SoundCloud / Beatport metadata scrapers (HTML embedded JSON)."""

import json
from unittest.mock import MagicMock


def test_soundcloud_artwork_hires(app_module):
    assert app_module._soundcloud_artwork_hires(
        "https://i1.sndcdn.com/artworks-abc-large.jpg"
    ) == "https://i1.sndcdn.com/artworks-abc-t500x500.jpg"


def test_scrape_soundcloud_uses_hydration(app_module, monkeypatch):
    hydration = [
        {"hydratable": "user", "data": {}},
        {
            "hydratable": "sound",
            "data": {
                "title": "My Track",
                "genre": "Techno",
                "created_at": "2019-06-01T12:00:00Z",
                "artwork_url": "https://i1.sndcdn.com/x-large.jpg",
                "user": {"username": "Uploader"},
                "publisher_metadata": {
                    "artist": "Featured Artist",
                    "album_title": "EP One",
                },
            },
        },
    ]
    html = (
        "<!DOCTYPE html><html><script>window.__sc_hydration = "
        + json.dumps(hydration)
        + ";</script></html>"
    )

    def fake_get(url, headers=None, timeout=None):
        r = MagicMock()
        r.content = html.encode("utf-8")
        r.raise_for_status = MagicMock()
        return r

    monkeypatch.setattr("requests.get", fake_get)
    meta = app_module.scrape_soundcloud("https://soundcloud.com/u/my-track")
    assert meta["title"] == "My Track"
    assert meta["artist"] == "Featured Artist"
    assert meta["album"] == "EP One"
    assert meta["genre"] == "Techno"
    assert meta["date"] == "2019"
    assert "t500x500" in meta["artwork_url"]
    assert meta["source"] == "soundcloud"


def test_scrape_beatport_next_data(app_module, monkeypatch):
    next_data = {
        "props": {
            "pageProps": {
                "track": {
                    "name": "Wackypaky",
                    "mix_name": "Original Mix",
                    "publish_date": "2022-05-27",
                    "artists": [{"name": "Monika Kruse"}],
                    "genre": {"name": "Tech House"},
                    "release": {
                        "name": "Roadhouse Grooves 13",
                        "label": {"name": "Clepsydra"},
                        "image": {
                            "dynamic_uri": "https://geo-media.beatport.com/image_size/{w}x{h}/abc.jpg",
                        },
                    },
                }
            }
        }
    }
    html = (
        '<!DOCTYPE html><html><script id="__NEXT_DATA__" type="application/json">'
        + json.dumps(next_data)
        + "</script></html>"
    )

    def fake_get(url, headers=None, timeout=None):
        r = MagicMock()
        r.content = html.encode("utf-8")
        r.raise_for_status = MagicMock()
        return r

    monkeypatch.setattr("requests.get", fake_get)
    meta = app_module.scrape_beatport("https://www.beatport.com/track/wackypaky/16495841")
    assert meta["title"] == "Wackypaky"
    assert meta["artist"] == "Monika Kruse"
    assert meta["album"] == "Roadhouse Grooves 13"
    assert meta["label"] == "Clepsydra"
    assert meta["genre"] == "Tech House"
    assert meta["date"] == "2022"
    assert "1400x1400" in meta["artwork_url"]
    assert meta["source"] == "beatport"


def test_scrape_beatport_non_track_url(app_module):
    assert app_module.scrape_beatport("https://www.beatport.com/release/x/1") == {}
