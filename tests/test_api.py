import pytest
from starlette.testclient import TestClient

from media_source.main import create_app
from media_source.models.schemas import StreamResponse, Track
from media_source.providers.base import Provider, ProviderError
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


@pytest.fixture
def client():
    app = create_app()
    app.dependency_overrides = {}
    with TestClient(app) as c:
        # Replace the real registry installed by lifespan with the fake one.
        c.app.state.registry = ProviderRegistry([FakeProvider()])
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
