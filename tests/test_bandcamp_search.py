"""Bandcamp search (HTML) and URL normalization."""

import pytest


def test_bandcamp_clean_result_url_strips_query(app_module):
    u = app_module._bandcamp_clean_result_url(
        "https://x.bandcamp.com/track/foo-bar?from=search&search_rank=1"
    )
    assert u == "https://x.bandcamp.com/track/foo-bar"


def test_bandcamp_clean_result_url_rejects_non_bandcamp(app_module):
    assert app_module._bandcamp_clean_result_url("https://example.com/track/x") == ""


def test_search_bandcamp_parses_search_page(app_module, monkeypatch):
    html = """
    <html><body><ul>
    <li class="searchresult data-search">
      <a class="artcont" href="https://artist.bandcamp.com/track/my-track?from=search">
        <div class="art"><img src="https://f4.bcbits.com/img/x.jpg"/></div>
      </a>
      <div class="result-info">
        <div class="heading"><a href="#">My Title Here</a></div>
        <div class="subhead">from Some Album by Test Artist</div>
        <div class="released">released January 1, 2020</div>
      </div>
    </li>
    </ul></body></html>
    """

    class Resp:
        text = html

        def raise_for_status(self):
            return None

    monkeypatch.setattr(app_module.requests, "get", lambda *a, **k: Resp())
    out = app_module.search_bandcamp("query", limit=5)
    assert len(out) == 1
    assert out[0]["source"] == "bandcamp"
    assert out[0]["title"] == "My Title Here"
    assert out[0]["artist"] == "Test Artist"
    assert out[0]["album"] == "Some Album"
    assert out[0]["year"] == "2020"
    assert out[0]["url"] == "https://artist.bandcamp.com/track/my-track"
    assert "bcbits.com" in (out[0].get("artwork_thumb") or "")


def test_api_search_includes_bandcamp_key(client, monkeypatch):
    monkeypatch.setattr(
        "app.search_itunes",
        lambda q, limit=8: [{"title": "A", "artist": "B", "source": "apple_music", "url": "https://x"}],
    )
    monkeypatch.setattr("app.search_discogs", lambda q, limit=5: [])
    monkeypatch.setattr(
        "app.search_bandcamp",
        lambda q, limit=6: [{"title": "T1", "artist": "A1", "album": "", "source": "bandcamp", "url": "https://a.bc/track/t"}],
    )
    r = client.get("/api/search?q=test")
    assert r.status_code == 200
    j = r.get_json()
    assert len(j["results"]) == 2
    kinds = {x["source"] for x in j["results"]}
    assert "bandcamp" in kinds
    assert "apple_music" in kinds
