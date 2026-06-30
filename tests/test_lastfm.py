import httpx
import pytest

from media_source.providers.base import ProviderError
from media_source.providers.lastfm import (
    LastfmClient,
    LastfmNotConfigured,
    _parse_candidates,
)


def _client(handler) -> LastfmClient:
    transport = httpx.MockTransport(handler)
    return LastfmClient("secret-key", client=httpx.AsyncClient(transport=transport))


async def test_similar_tracks_parses_candidates():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["method"] == "track.getSimilar"
        assert request.url.params["api_key"] == "secret-key"
        return httpx.Response(
            200,
            json={
                "similartracks": {
                    "track": [
                        {"name": "Song A", "artist": {"name": "Artist A"}},
                        {"name": "Song B", "artist": {"name": "Artist B"}},
                    ]
                }
            },
        )

    candidates = await _client(handler).similar_tracks("Seed", "Track", 10)
    assert [(c.artist, c.title) for c in candidates] == [
        ("Artist A", "Song A"),
        ("Artist B", "Song B"),
    ]


async def test_error_body_raises_provider_error():
    def handler(request: httpx.Request) -> httpx.Response:
        # Last.fm signals failure with HTTP 200 + an error body.
        return httpx.Response(200, json={"error": 6, "message": "Invalid parameters"})

    with pytest.raises(ProviderError) as exc:
        await _client(handler).top_tracks_by_tag("rock", 10)
    assert "Invalid parameters" in str(exc.value)


async def test_http_error_does_not_leak_api_key():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    with pytest.raises(ProviderError) as exc:
        await _client(handler).chart_top_tracks(10)
    assert "secret-key" not in str(exc.value)


async def test_missing_api_key_raises_not_configured():
    client = LastfmClient(None, client=httpx.AsyncClient())
    with pytest.raises(LastfmNotConfigured):
        await client.chart_top_tracks(10)


def test_parse_candidates_handles_string_artist_and_single_dict():
    data = {"tracks": {"track": {"name": "Solo", "artist": "Bare Name"}}}
    candidates = _parse_candidates(data, "tracks")
    assert [(c.artist, c.title) for c in candidates] == [("Bare Name", "Solo")]


def test_parse_candidates_skips_incomplete():
    data = {"tracks": {"track": [{"name": "", "artist": {"name": "X"}}]}}
    assert _parse_candidates(data, "tracks") == []
