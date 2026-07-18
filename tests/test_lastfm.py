import httpx
import pytest

from media_source.providers.base import ProviderError
from media_source.providers.lastfm import (
    LastfmClient,
    LastfmNotConfigured,
    LastfmNotFound,
    _parse_candidates,
    _parse_tags,
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


# --- tags -------------------------------------------------------------------


def _tags_payload(*pairs):
    return {"toptags": {"tag": [{"name": n, "count": c} for n, c in pairs]}}


def test_parse_tags_sorts_by_weight_desc_and_limits():
    data = _tags_payload(("metal", 76), ("nu metal", 100), ("seen live", 41))
    tags = _parse_tags(data, limit=2)
    assert [(t.name, t.weight) for t in tags] == [("nu metal", 100), ("metal", 76)]


def test_parse_tags_keeps_noise_tags_untouched():
    # Filtering ("seen live", "favorites") is the consumer's job, not ours.
    tags = _parse_tags(_tags_payload(("seen live", 41)), limit=10)
    assert [t.name for t in tags] == ["seen live"]


def test_parse_tags_handles_missing_count_and_single_dict():
    data = {"toptags": {"tag": {"name": "solo"}}}
    assert [(t.name, t.weight) for t in _parse_tags(data, 10)] == [("solo", 0)]


async def test_top_tags_uses_artist_endpoint_and_normalizes_name():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.url.params["method"]
        seen["artist"] = request.url.params["artist"]
        return httpx.Response(200, json=_tags_payload(("thrash metal", 100)))

    tags = await _client(handler).top_tags("Death From Above 1979 - Topic", limit=5)
    assert seen == {"method": "artist.getTopTags", "artist": "Death From Above 1979"}
    assert [t.name for t in tags] == ["thrash metal"]


async def test_top_tags_uses_track_endpoint_when_track_given():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.url.params["method"]
        seen["artist"] = request.url.params["artist"]
        seen["track"] = request.url.params["track"]
        return httpx.Response(200, json=_tags_payload(("metal", 100)))

    await _client(handler).top_tags(
        "Slipknot - Psychosocial [OFFICIAL VIDEO] [HD]",
        track="Slipknot - Psychosocial [HD]",
        limit=5,
    )
    assert seen == {
        "method": "track.getTopTags",
        "artist": "Slipknot",
        "track": "Psychosocial",
    }


async def test_top_tags_unknown_artist_returns_empty_not_error():
    def handler(request: httpx.Request) -> httpx.Response:
        # Exactly what Last.fm sends for an unknown artist: HTTP 200 + error 6.
        return httpx.Response(
            200,
            json={"error": 6, "message": "The artist you supplied could not be found"},
        )

    assert await _client(handler).top_tags("NonexistentArtist12345", limit=5) == []


async def test_top_tags_empty_after_normalization_skips_upstream():
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("Last.fm must not be called for an empty artist")

    assert await _client(handler).top_tags("- Topic", limit=5) == []


async def test_not_found_error_code_raises_lastfm_not_found():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error": 6, "message": "not found"})

    with pytest.raises(LastfmNotFound):
        await _client(handler).artist_top_tags("Whoever", 5)


async def test_other_error_codes_still_raise_provider_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error": 29, "message": "Rate limit exceeded"})

    with pytest.raises(ProviderError) as exc:
        await _client(handler).top_tags("Slipknot", limit=5)
    assert not isinstance(exc.value, LastfmNotFound)
