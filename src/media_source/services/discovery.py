"""Music discovery: Last.fm picks the songs, the YouTube provider makes them
playable.

Last.fm returns metadata only. Each candidate ("Artist - Title") is resolved to
a real, streamable YouTube track via the existing provider's search (top hit),
so the result is the same ``Track`` schema as ``/search`` and feeds the unchanged
``/stream`` pipeline. Unresolved candidates are skipped — ids are never invented.
"""

import asyncio
import logging

from media_source.models.schemas import Track
from media_source.providers.base import Provider, ProviderError
from media_source.providers.lastfm import LastfmClient, LastfmNotFound, TrackCandidate
from media_source.providers.naming import normalize_artist, normalize_track

logger = logging.getLogger(__name__)

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
        # Callers pass raw YouTube metadata ("X - Topic", "Artist - Track [HD]"),
        # which Last.fm matches against nothing — silently returning an empty
        # list rather than an error. Normalising first is what makes these
        # lookups resolve at all.
        clean_artist = normalize_artist(artist)
        clean_track = normalize_track(track)
        if not clean_artist or not clean_track:
            return []

        try:
            candidates = await self._lastfm.similar_tracks(
                clean_artist, clean_track, limit
            )
        except LastfmNotFound:
            # "Last.fm doesn't know it" is a valid empty answer, not a failure.
            # Real failures (timeouts, 5xx, rate limits) stay ProviderError -> 502,
            # so an outage remains distinguishable from an unknown track.
            return []
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
        try:
            if tag:
                candidates = await self._lastfm.top_tracks_by_tag(tag, limit)
            elif country:
                candidates = await self._lastfm.geo_top_tracks(country, limit)
            else:
                candidates = await self._lastfm.chart_top_tracks(limit)
        except LastfmNotFound:
            # Unknown tag/country -> empty chart, not an error. Outages still 502.
            return []
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
            except ProviderError as exc:
                # One unresolvable candidate must not fail the whole request,
                # but a burst of these is worth seeing in the logs.
                logger.warning("could not resolve %r on YouTube: %s", query, exc)
                return None
        if not hits:
            logger.debug("no YouTube match for %r", query)
            return None
        return hits[0]
