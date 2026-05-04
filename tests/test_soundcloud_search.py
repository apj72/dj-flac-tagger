"""Tests for SoundCloud catalogue search via api-v2 (client id from hydration)."""

import json
from unittest.mock import MagicMock


def test_soundcloud_api_client_id_parses_hydration(app_module, monkeypatch):
    html = (
        "<!DOCTYPE html><html><script>window.__sc_hydration = "
        + json.dumps(
            [
                {"hydratable": "geoip", "data": {}},
                {
                    "hydratable": "apiClient",
                    "data": {"id": "abc123clientidABCDEFGH", "isExpiring": False},
                },
            ],
        )
        + ";</script></html>"
    )

    def fake_get(url, headers=None, timeout=None):
        assert "soundcloud.com" in url
        r = MagicMock()
        r.raise_for_status = MagicMock()
        r.content = html.encode("utf-8")
        return r

    monkeypatch.setattr("requests.get", fake_get)
    app_module._soundcloud_api_client_cache["id"] = ""
    app_module._soundcloud_api_client_cache["ts"] = 0.0
    cid = app_module._soundcloud_api_client_id()
    assert cid == "abc123clientidABCDEFGH"


def test_search_soundcloud_maps_tracks(app_module, monkeypatch):
    app_module._soundcloud_api_client_cache["id"] = "cidtest"
    app_module._soundcloud_api_client_cache["ts"] = __import__("time").time()

    payload = {
        "collection": [
            {
                "kind": "track",
                "title": "My Tune",
                "permalink_url": "https://soundcloud.com/u/my-tune",
                "artwork_url": "https://i1.sndcdn.com/foo-large.jpg",
                "release_date": "2024-05-01T00:00:00Z",
                "user": {"username": "uploader"},
                "publisher_metadata": {
                    "artist": "Official Artist",
                    "album_title": "The EP",
                },
            },
        ],
    }

    def fake_get(url, params=None, headers=None, timeout=None):
        assert "api-v2.soundcloud.com/search/tracks" in url
        assert params.get("client_id") == "cidtest"
        r = MagicMock()
        r.raise_for_status = MagicMock()
        r.json = MagicMock(return_value=payload)
        return r

    monkeypatch.setattr("requests.get", fake_get)
    rows = app_module.search_soundcloud("query", limit=5)
    assert len(rows) == 1
    assert rows[0]["source"] == "soundcloud"
    assert rows[0]["title"] == "My Tune"
    assert rows[0]["artist"] == "Official Artist"
    assert rows[0]["album"] == "The EP"
    assert rows[0]["year"] == "2024"
    assert rows[0]["url"] == "https://soundcloud.com/u/my-tune"
    assert "t500x500" in rows[0]["artwork_thumb"]
