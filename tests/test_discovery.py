import pytest

from media_source.models.schemas import StreamResponse, Track
from media_source.providers.base import Provider, ProviderError
from media_source.providers.lastfm import LastfmNotFound, TrackCandidate
from media_source.services.discovery import DiscoveryService


class FakeLastfm:
    """Stand-in for LastfmClient: returns canned candidates or raises."""

    def __init__(self, candidates=None, error: Exception | None = None):
        self._candidates = candidates or []
        self._error = error

    async def _result(self):
        if self._error:
            raise self._error
        return self._candidates

    async def similar_tracks(self, artist, track, limit):
        return await self._result()

    async def top_tracks_by_tag(self, tag, limit):
        return await self._result()

    async def chart_top_tracks(self, limit):
        return await self._result()

    async def geo_top_tracks(self, country, limit):
        return await self._result()


class FakeYouTube(Provider):
    """Resolver whose search returns a Track unless the query is unresolvable."""

    name = "youtube"

    def __init__(self, unresolvable: set[str] | None = None):
        self._unresolvable = unresolvable or set()
        self.queries: list[str] = []

    async def search(self, query: str, limit: int) -> list[Track]:
        self.queries.append(query)
        if query in self._unresolvable:
            return []
        return [Track(provider="youtube", id=f"yt-{query}", title=query)]

    async def resolve_stream(self, track_id: str) -> StreamResponse:  # unused
        raise NotImplementedError

    async def resolve_playlist(self, playlist: str, limit: int) -> list[Track]:
        raise NotImplementedError


def _candidates(*pairs):
    return [TrackCandidate(artist=a, title=t) for a, t in pairs]


async def test_similar_maps_candidates_to_youtube_tracks():
    lastfm = FakeLastfm(_candidates(("Daft Punk", "One More Time"), ("Justice", "D.A.N.C.E")))
    yt = FakeYouTube()
    svc = DiscoveryService(lastfm, yt)

    tracks = await svc.similar("seed", "track", 10)

    assert [t.provider for t in tracks] == ["youtube", "youtube"]
    assert tracks[0].id == "yt-Daft Punk One More Time"
    # Order preserved from Last.fm ranking.
    assert tracks[1].title == "Justice D.A.N.C.E"


async def test_unresolved_candidates_are_skipped():
    lastfm = FakeLastfm(_candidates(("A", "1"), ("B", "2"), ("C", "3")))
    yt = FakeYouTube(unresolvable={"B 2"})
    svc = DiscoveryService(lastfm, yt)

    tracks = await svc.similar("seed", "track", 10)
    assert [t.id for t in tracks] == ["yt-A 1", "yt-C 3"]


async def test_empty_candidates_returns_empty():
    svc = DiscoveryService(FakeLastfm([]), FakeYouTube())
    assert await svc.charts(tag="rock", limit=10) == []


async def test_limit_caps_candidates_resolved():
    lastfm = FakeLastfm(_candidates(*[(f"A{i}", f"T{i}") for i in range(20)]))
    yt = FakeYouTube()
    svc = DiscoveryService(lastfm, yt)

    tracks = await svc.charts(limit=5)
    assert len(tracks) == 5
    assert len(yt.queries) == 5  # never resolves more than the limit


async def test_charts_dispatches_by_argument():
    class Recorder(FakeLastfm):
        def __init__(self):
            super().__init__(_candidates(("A", "1")))
            self.called = None

        async def top_tracks_by_tag(self, tag, limit):
            self.called = ("tag", tag)
            return await self._result()

        async def geo_top_tracks(self, country, limit):
            self.called = ("geo", country)
            return await self._result()

        async def chart_top_tracks(self, limit):
            self.called = ("global", None)
            return await self._result()

    rec = Recorder()
    svc = DiscoveryService(rec, FakeYouTube())

    await svc.charts(tag="rock", limit=5)
    assert rec.called == ("tag", "rock")
    await svc.charts(country="Germany", limit=5)
    assert rec.called == ("geo", "Germany")
    await svc.charts(limit=5)
    assert rec.called == ("global", None)


async def test_lastfm_error_propagates_as_provider_error():
    svc = DiscoveryService(FakeLastfm(error=ProviderError("upstream")), FakeYouTube())
    with pytest.raises(ProviderError):
        await svc.similar("a", "b", 10)


# --- unknown-vs-broken, and normalisation of raw YouTube names ---------------


class RecordingLastfm(FakeLastfm):
    """Captures the artist/track actually sent upstream."""

    def __init__(self, candidates=None, error=None):
        super().__init__(candidates, error)
        self.seen: tuple | None = None

    async def similar_tracks(self, artist, track, limit):
        self.seen = (artist, track)
        return await self._result()


async def test_similar_normalizes_raw_youtube_names():
    lastfm = RecordingLastfm(_candidates(("X", "Y")))
    svc = DiscoveryService(lastfm, FakeYouTube())

    await svc.similar("Death From Above 1979 - Topic", "Romantic Rights [HD]", 10)
    assert lastfm.seen == ("Death From Above 1979", "Romantic Rights")


async def test_similar_extracts_artist_from_combined_title():
    lastfm = RecordingLastfm(_candidates(("X", "Y")))
    svc = DiscoveryService(lastfm, FakeYouTube())

    await svc.similar("Slipknot - Psychosocial [OFFICIAL VIDEO]", "Psychosocial", 10)
    assert lastfm.seen == ("Slipknot", "Psychosocial")


async def test_similar_unresolvable_names_skip_upstream():
    lastfm = RecordingLastfm(_candidates(("X", "Y")))
    svc = DiscoveryService(lastfm, FakeYouTube())

    assert await svc.similar("- Topic", "[HD]", 10) == []
    assert lastfm.seen is None


async def test_similar_not_found_is_empty_not_error():
    svc = DiscoveryService(
        FakeLastfm(error=LastfmNotFound("Last.fm error 6: Track not found")),
        FakeYouTube(),
    )
    assert await svc.similar("Nonexistent12345", "Nothing", 10) == []


async def test_charts_not_found_is_empty_not_error():
    svc = DiscoveryService(FakeLastfm(error=LastfmNotFound("error 6")), FakeYouTube())
    assert await svc.charts(tag="nonexistent-tag", limit=10) == []


async def test_real_failures_stay_errors_so_outages_remain_visible():
    # Timeout / 5xx / rate limit must NOT be flattened into an empty list.
    for boom in (
        ProviderError("Last.fm request failed (network error)"),
        ProviderError("Last.fm returned HTTP 503"),
        ProviderError("Last.fm error 29: Rate limit exceeded"),
    ):
        svc = DiscoveryService(FakeLastfm(error=boom), FakeYouTube())
        with pytest.raises(ProviderError):
            await svc.similar("Slipknot", "Psychosocial", 10)
        with pytest.raises(ProviderError):
            await svc.charts(tag="metal", limit=10)
