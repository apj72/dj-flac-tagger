"""Tests for bulk metadata fix API (scan + helpers)."""

import os

import pytest


def test_search_query_from_stem_matched(app_module):
    sq = app_module.search_query_from_ableton_stem("A06 - 139 - Members Of Mayday - 10 In 01")
    assert sq["pattern_matched"] is True
    assert "Members Of Mayday" in sq["query"] and "10 In 01" in sq["query"]
    assert sq["title_hint"] == "10 In 01"


def test_search_query_strips_rekordbox_affixes(app_module):
    sq = app_module.search_query_from_ableton_stem("A02 Ripperton Unfold 2A 119")
    assert "Ripperton" in sq["query"] and "Unfold" in sq["query"]
    assert "2A" not in sq["query"] and "119" not in sq["query"]
    assert "A02" not in sq["query"]


def test_best_track_in_list_prefers_close_title(app_module):
    tl = [
        {"position": "A1", "title": "Intro", "duration": ""},
        {"position": "A2", "title": "My Real Title", "duration": ""},
    ]
    best = app_module._best_track_in_list(tl, "My Real Title")
    assert best["title"] == "My Real Title"


def test_bulk_fix_search_info_uses_wav_tags_when_present(app_module, tmp_path, monkeypatch):
    flac = tmp_path / "Song.flac"
    wav = tmp_path / "Song.wav"
    flac.write_bytes(b"x")
    wav.write_bytes(b"y")

    def fake_read(path):
        if os.path.normpath(path) == os.path.normpath(str(wav)):
            return {"title": "FromWav", "artist": "WaveArtist", "album": ""}
        return app_module._read_wav_embedded_tags(path)

    monkeypatch.setattr(app_module, "_read_wav_embedded_tags", fake_read)
    info = app_module.bulk_fix_search_info_for_flac(str(flac))
    assert info["query"] == "WaveArtist FromWav"
    assert info["title_hint"] == "FromWav"
    assert info["artist_hint"] == "WaveArtist"
    assert info["wav_tags"] == {"artist": "WaveArtist", "title": "FromWav"}


def test_bulk_fix_scan_includes_wav_sibling(client, tmp_path):
    d = tmp_path / "lib"
    d.mkdir()
    f = d / "Track.flac"
    w = d / "Track.wav"
    f.write_bytes(b"x")
    w.write_bytes(b"y")
    r = client.get(f"/api/bulk-fix/scan?path={d}&recursive=0&offset=0&limit=5")
    assert r.status_code == 200
    j = r.get_json()
    assert len(j["items"]) == 1
    item = j["items"][0]
    assert os.path.normpath(item["wav_sibling"]) == os.path.normpath(str(w.resolve()))
    assert item["wav_tags"] is None


def test_bulk_fix_scan_marks_same_basename_in_tree(client, tmp_path):
    d = tmp_path / "lib"
    d.mkdir()
    (d / "a").mkdir()
    (d / "b").mkdir()
    p1 = d / "a" / "Same.flac"
    p2 = d / "b" / "Same.flac"
    p1.write_bytes(b"x")
    p2.write_bytes(b"y")
    r = client.get(f"/api/bulk-fix/scan?path={d}&recursive=1&offset=0&limit=10")
    assert r.status_code == 200
    j = r.get_json()
    assert j["total"] == 2
    assert j["duplicates_in_batch"] == 2
    for it in j["items"]:
        assert it["duplicate_basename"] is True
        assert it["same_basename_count"] == 2
        assert len(it["same_basename_other_paths"]) == 1
        assert it["same_basename_other_paths"][0] in (os.path.normpath(str(p1)), os.path.normpath(str(p2)))
        other = it["same_basename_other_paths"][0]
        assert it["filepath"] != other
        assert it["duplicate_in_batch"] is True


def test_bulk_fix_scan_paged(client, tmp_path):
    d = tmp_path / "lib"
    d.mkdir()
    (d / "A01 - 128 - X - Y.flac").write_bytes(b"x")
    (d / "other.flac").write_bytes(b"y")

    r = client.get(f"/api/bulk-fix/scan?path={d}&recursive=0&offset=0&limit=1")
    assert r.status_code == 200
    j = r.get_json()
    assert j["total"] == 2
    assert len(j["items"]) == 1
    assert j["items"][0]["pattern_matched"] is True
    assert "X" in j["items"][0]["query"]

    r2 = client.get(f"/api/bulk-fix/scan?path={d}&recursive=0&offset=1&limit=5")
    j2 = r2.get_json()
    assert len(j2["items"]) == 1
    assert "other" in (j2["items"][0]["basename"] or "").lower()


def test_fetch_metadata_uses_track_hint_for_discogs_tracklist(client, app_module, monkeypatch):
    """Multi-track discogs style meta picks title from hint."""
    def fake_fetch(url):
        return {
            "artist": "Album Artist",
            "album": "The LP",
            "date": "2020",
            "artwork_url": "",
            "tracklist": [
                {"position": "1", "title": "Alpha", "duration": ""},
                {"position": "2", "title": "Beta", "duration": ""},
            ],
            "source": "discogs",
        }

    monkeypatch.setattr(app_module, "_metadata_from_url", fake_fetch)
    r = client.post(
        "/api/fetch-metadata",
        json={"url": "https://www.discogs.com/release/1", "track_name": "Beta"},
    )
    assert r.status_code == 200
    assert r.get_json().get("title") == "Beta"


def test_bulk_fix_scan_paths_preserves_order(client, tmp_path):
    d = tmp_path / "flat"
    d.mkdir()
    p_a = d / "A Artist - A Title.flac"
    p_z = d / "Z Artist - Z Title.flac"
    p_a.write_bytes(b"x")
    p_z.write_bytes(b"y")
    r = client.post(
        "/api/bulk-fix/scan-paths",
        json={"paths": [str(p_z), str(p_a)]},
    )
    assert r.status_code == 200
    j = r.get_json()
    assert j.get("order") == "explicit_paths"
    assert j["total"] == 2
    assert [it["filepath"] for it in j["items"]] == [
        os.path.normpath(str(p_z)),
        os.path.normpath(str(p_a)),
    ]


def test_bulk_fix_page_serves(client):
    r = client.get("/bulk-fix")
    assert r.status_code == 200
    assert b"Bulk Fix" in r.data or b"bulk-fix.js" in r.data


def test_bulk_fix_apply_rejects_empty_items(client):
    r = client.post("/api/bulk-fix/apply", json={"items": []})
    assert r.status_code == 400
    assert "items" in (r.get_json().get("error") or "").lower()
