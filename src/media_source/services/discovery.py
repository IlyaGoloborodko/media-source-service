"""Music discovery: Last.fm picks the songs, the YouTube provider makes them
playable.

Last.fm returns metadata only. Each candidate ("Artist - Title") is resolved to
a real, streamable YouTube track via the existing provider's search (top hit),
so the result is the same ``Track`` schema as ``/search`` and feeds the unchanged
``/stream`` pipeline. Unresolved candidates are skipped — ids are never invented.
"""

import asyncio

from media_source.models.schemas import Track
from media_source.providers.base import Provider, ProviderError
from media_source.providers.lastfm import LastfmClient, TrackCandidate

# Bound how many YouTube resolutions run at once so a large request can't fan
# out into dozens of simultaneous yt-dlp calls.
_DEFAULT_CONCURRENCY = 5


class DiscoveryService:
    def __init__(
        self,
        lastfm: LastfmClient,
        resolver: Provider,
        max_concurrency: int = _DEFAULT_CONCURRENCY,
    ):
        self._lastfm = lastfm
        self._resolver = resolver
        self._max_concurrency = max_concurrency

    async def similar(self, artist: str, track: str, limit: int) -> list[Track]:
        candidates = await self._lastfm.similar_tracks(artist, track, limit)
        return await self._resolve_all(candidates, limit)

    async def charts(
        self,
        *,
        tag: str | None = None,
        country: str | None = None,
        limit: int = 10,
    ) -> list[Track]:
        """Top tracks by tag (genre/mood), by country, or global — in that
        precedence when several are supplied."""
        if tag:
            candidates = await self._lastfm.top_tracks_by_tag(tag, limit)
        elif country:
            candidates = await self._lastfm.geo_top_tracks(country, limit)
        else:
            candidates = await self._lastfm.chart_top_tracks(limit)
        return await self._resolve_all(candidates, limit)

    async def _resolve_all(
        self, candidates: list[TrackCandidate], limit: int
    ) -> list[Track]:
        candidates = candidates[:limit]
        semaphore = asyncio.Semaphore(self._max_concurrency)
        tracks = await asyncio.gather(
            *(self._resolve_one(c, semaphore) for c in candidates)
        )
        # gather preserves order, so Last.fm's ranking survives; drop misses.
        return [t for t in tracks if t is not None]

    async def _resolve_one(
        self, candidate: TrackCandidate, semaphore: asyncio.Semaphore
    ) -> Track | None:
        query = f"{candidate.artist} {candidate.title}".strip()
        if not query:
            return None
        async with semaphore:
            try:
                hits = await self._resolver.search(query, 1)
            except ProviderError:
                # One unresolvable candidate must not fail the whole request.
                return None
        return hits[0] if hits else None
