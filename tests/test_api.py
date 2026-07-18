import pytest
from starlette.testclient import TestClient

from media_source.main import create_app
from media_source.models.schemas import StreamResponse, Track
from media_source.providers.base import Provider, ProviderError
from media_source.providers.lastfm import LastfmNotConfigured, TagCount
from media_source.providers.registry import ProviderRegistry


class FakeProvider(Provider):
    """Network-free stand-in so API tests don't hit YouTube."""

    name = "youtube"

    async def search(self, query: str, limit: int) -> list[Track]:
        if query == "boom":
            raise ProviderError("upstream exploded")
        return [
            Track(provider=self.name, id=f"id{i}", title=f"{query} {i}")
            for i in range(limit)
        ]

    async def resolve_stream(self, track_id: str) -> StreamResponse:
        return StreamResponse(
            provider=self.name, id=track_id, stream_url=f"https://cdn/{track_id}"
        )

    async def resolve_playlist(self, playlist: str, limit: int) -> list[Track]:
        if playlist == "boom":
            raise ProviderError("playlist exploded")
        return [
            Track(provider=self.name, id=f"p{i}", title=f"{playlist} {i}")
            for i in range(limit)
        ]


class FakeDiscovery:
    """Stand-in for DiscoveryService used by the /similar and /charts tests."""

    async def similar(self, artist, track, limit):
        if artist == "boom":
            raise ProviderError("discovery exploded")
        if artist == "nokey":
            raise LastfmNotConfigured("Last.fm API key not configured")
        return [
            Track(provider="youtube", id=f"yt{i}", title=f"{artist} {i}")
            for i in range(limit)
        ]

    async def charts(self, *, tag=None, country=None, limit=10):
        label = tag or country or "global"
        return [
            Track(provider="youtube", id=f"yt{i}", title=f"{label} {i}")
            for i in range(limit)
        ]


class FakeLastfm:
    """Stand-in for LastfmClient covering the /tags route."""

    async def top_tags(self, artist, track=None, limit=10):
        if artist == "nokey":
            raise LastfmNotConfigured("Last.fm API key not configured")
        if artist == "unknown":
            return []  # Last.fm doesn't know it -> valid empty answer
        source = f"{artist}:{track}" if track else artist
        return [
            TagCount(name=f"{source} tag{i}", weight=100 - i) for i in range(limit)
        ]


@pytest.fixture
def client():
    app = create_app()
    app.dependency_overrides = {}
    with TestClient(app) as c:
        # Replace the real registry/discovery installed by lifespan with fakes.
        c.app.state.registry = ProviderRegistry([FakeProvider()])
        c.app.state.discovery = FakeDiscovery()
        c.app.state.lastfm = FakeLastfm()
        yield c


def test_health(client):
    body = client.get("/health").json()
    assert body == {"status": "ok", "providers": ["youtube"]}


def test_search_respects_limit(client):
    r = client.get("/search", params={"q": "cats", "limit": 3})
    assert r.status_code == 200
    body = r.json()
    assert body["query"] == "cats"
    assert len(body["results"]) == 3


def test_search_caps_at_max_limit(client):
    r = client.get("/search", params={"q": "cats", "limit": 9999})
    assert r.status_code == 200
    assert len(r.json()["results"]) == 25  # max_search_limit default


def test_search_empty_query_is_rejected(client):
    assert client.get("/search", params={"q": ""}).status_code == 422


def test_unknown_provider_404(client):
    r = client.get("/search", params={"q": "x", "provider": "spotify"})
    assert r.status_code == 404


def test_provider_error_becomes_502(client):
    r = client.get("/search", params={"q": "boom"})
    assert r.status_code == 502
    assert "exploded" in r.json()["detail"]


def test_stream(client):
    r = client.get("/stream", params={"id": "abc"})
    assert r.status_code == 200
    body = r.json()
    assert body["stream_url"] == "https://cdn/abc"
    assert body["expires_at"] is None


def test_playlist_returns_tracks(client):
    r = client.get("/playlist", params={"url": "PL123", "limit": 4})
    assert r.status_code == 200
    body = r.json()
    assert body["provider"] == "youtube"
    assert body["playlist"] == "PL123"
    assert len(body["results"]) == 4
    # Track shape must match /search results exactly.
    assert set(body["results"][0]) == {
        "provider",
        "id",
        "title",
        "uploader",
        "url",
        "duration",
        "thumbnail",
    }


def test_playlist_caps_at_max_limit(client):
    r = client.get("/playlist", params={"url": "PL123", "limit": 9999})
    assert r.status_code == 200
    assert len(r.json()["results"]) == 100  # max_playlist_limit default


def test_playlist_unknown_provider_404(client):
    r = client.get("/playlist", params={"url": "PL123", "provider": "spotify"})
    assert r.status_code == 404


def test_playlist_provider_error_becomes_502(client):
    r = client.get("/playlist", params={"url": "boom"})
    assert r.status_code == 502
    assert "exploded" in r.json()["detail"]


def test_similar_returns_track_shaped_results(client):
    r = client.get("/similar", params={"artist": "Daft Punk", "track": "Da Funk", "limit": 3})
    assert r.status_code == 200
    body = r.json()
    assert len(body["results"]) == 3
    # Discovery results must be identical in shape to /search results.
    assert set(body["results"][0]) == {
        "provider",
        "id",
        "title",
        "uploader",
        "url",
        "duration",
        "thumbnail",
    }
    assert body["results"][0]["provider"] == "youtube"


def test_similar_requires_artist_and_track(client):
    assert client.get("/similar", params={"artist": "x"}).status_code == 422
    assert client.get("/similar", params={"artist": "", "track": "y"}).status_code == 422


def test_similar_caps_at_max_limit(client):
    r = client.get("/similar", params={"artist": "a", "track": "b", "limit": 9999})
    assert len(r.json()["results"]) == 25  # max_search_limit default


def test_similar_missing_api_key_503(client):
    r = client.get("/similar", params={"artist": "nokey", "track": "b"})
    assert r.status_code == 503
    assert "API key" in r.json()["detail"]


def test_similar_upstream_error_502(client):
    r = client.get("/similar", params={"artist": "boom", "track": "b"})
    assert r.status_code == 502
    assert "exploded" in r.json()["detail"]


def test_tags_returns_name_weight_pairs(client):
    r = client.get("/tags", params={"artist": "Slipknot", "limit": 3})
    assert r.status_code == 200
    body = r.json()
    assert list(body) == ["tags"]
    assert set(body["tags"][0]) == {"name", "weight"}
    assert len(body["tags"]) == 3
    # Sorted by descending weight.
    weights = [t["weight"] for t in body["tags"]]
    assert weights == sorted(weights, reverse=True)


def test_tags_track_differs_from_artist(client):
    artist_only = client.get("/tags", params={"artist": "Slipknot"}).json()
    with_track = client.get(
        "/tags", params={"artist": "Slipknot", "track": "Psychosocial"}
    ).json()
    assert artist_only["tags"][0]["name"] != with_track["tags"][0]["name"]


def test_tags_defaults_to_ten(client):
    assert len(client.get("/tags", params={"artist": "Slipknot"}).json()["tags"]) == 10


def test_tags_caps_at_max_limit(client):
    r = client.get("/tags", params={"artist": "Slipknot", "limit": 9999})
    assert len(r.json()["tags"]) == 50  # max_tags_limit default


def test_tags_unknown_artist_is_200_with_empty_list(client):
    r = client.get("/tags", params={"artist": "unknown"})
    assert r.status_code == 200
    assert r.json() == {"tags": []}


def test_tags_requires_artist(client):
    assert client.get("/tags").status_code == 422
    assert client.get("/tags", params={"artist": ""}).status_code == 422


def test_tags_missing_api_key_503(client):
    r = client.get("/tags", params={"artist": "nokey"})
    assert r.status_code == 503


def test_charts_global_and_tag(client):
    r = client.get("/charts", params={"limit": 4})
    assert r.status_code == 200
    assert len(r.json()["results"]) == 4
    r2 = client.get("/charts", params={"tag": "rock", "limit": 2})
    assert r2.status_code == 200
    assert r2.json()["results"][0]["title"].startswith("rock")
