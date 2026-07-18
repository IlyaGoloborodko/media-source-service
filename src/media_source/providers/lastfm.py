"""Last.fm metadata client.

Last.fm is metadata-only: it yields "artist + title" candidates, never a
playable stream or a YouTube id. The discovery layer (services/discovery.py)
turns these candidates into playable Tracks via the YouTube provider.
"""

from dataclasses import dataclass
from typing import Any

import httpx

from media_source.providers.base import ProviderError
from media_source.providers.naming import normalize_artist, normalize_track

_BASE_URL = "https://ws.audioscrobbler.com/2.0/"

# Last.fm reports "no such artist/track" as an error body, not an empty result.
_NOT_FOUND_ERRORS = {6}


@dataclass(frozen=True)
class TrackCandidate:
    """A bare "artist + title" suggestion from Last.fm, not yet playable."""

    artist: str
    title: str


@dataclass(frozen=True)
class TagCount:
    """A genre/style tag with Last.fm's popularity count (0-100)."""

    name: str
    weight: int


class LastfmNotConfigured(Exception):
    """Raised when a Last.fm call is attempted without an API key configured."""


class LastfmNotFound(ProviderError):
    """Last.fm has no entry for the requested artist/track.

    A subclass of ProviderError so existing callers keep their behaviour;
    callers that treat "unknown" as a valid empty answer catch it explicitly.
    """


class LastfmClient:
    """Thin async wrapper over the Last.fm 2.0 REST API.

    Note on secrets: the API key travels as a query parameter, so it appears in
    request URLs. Error messages here deliberately avoid echoing the URL (or
    ``str(exc)``, which embeds it) to keep the key out of logs and responses.
    """

    def __init__(
        self,
        api_key: str | None,
        client: httpx.AsyncClient,
        base_url: str = _BASE_URL,
    ):
        self._api_key = api_key
        self._client = client
        self._base_url = base_url

    async def similar_tracks(
        self, artist: str, track: str, limit: int
    ) -> list[TrackCandidate]:
        data = await self._call(
            "track.getSimilar", artist=artist, track=track, limit=limit
        )
        return _parse_candidates(data, "similartracks")

    async def top_tracks_by_tag(self, tag: str, limit: int) -> list[TrackCandidate]:
        data = await self._call("tag.getTopTracks", tag=tag, limit=limit)
        return _parse_candidates(data, "tracks")

    async def chart_top_tracks(self, limit: int) -> list[TrackCandidate]:
        data = await self._call("chart.getTopTracks", limit=limit)
        return _parse_candidates(data, "tracks")

    async def geo_top_tracks(self, country: str, limit: int) -> list[TrackCandidate]:
        data = await self._call("geo.getTopTracks", country=country, limit=limit)
        return _parse_candidates(data, "tracks")

    async def artist_top_tags(self, artist: str, limit: int) -> list[TagCount]:
        data = await self._call("artist.getTopTags", artist=artist)
        return _parse_tags(data, limit)

    async def track_top_tags(
        self, artist: str, track: str, limit: int
    ) -> list[TagCount]:
        data = await self._call("track.getTopTags", artist=artist, track=track)
        return _parse_tags(data, limit)

    async def top_tags(
        self, artist: str, track: str | None = None, limit: int = 10
    ) -> list[TagCount]:
        """Genre/style tags for a track (when ``track`` is given) or an artist.

        Forgiving by design: names arrive straight from YouTube so they are
        normalised first, and "Last.fm doesn't know this one" is an empty list,
        not an error — an unknown genre is a valid answer, not a failure.
        """
        clean_artist = normalize_artist(artist)
        if not clean_artist:
            return []
        clean_track = normalize_track(track) if track else ""

        try:
            if clean_track:
                return await self.track_top_tags(clean_artist, clean_track, limit)
            return await self.artist_top_tags(clean_artist, limit)
        except LastfmNotFound:
            return []

    async def _call(self, method: str, **params: Any) -> dict:
        if not self._api_key:
            raise LastfmNotConfigured(
                "Last.fm API key not configured (set MSS_LASTFM_API_KEY)"
            )

        query = {
            "method": method,
            "api_key": self._api_key,
            "format": "json",
            **params,
        }
        try:
            resp = await self._client.get(self._base_url, params=query)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as exc:
            # Avoid str(exc): it contains the URL (and thus the api_key).
            raise ProviderError(
                f"Last.fm returned HTTP {exc.response.status_code}"
            ) from None
        except httpx.HTTPError:
            raise ProviderError("Last.fm request failed (network error)") from None

        # Last.fm signals errors with HTTP 200 and an {"error", "message"} body.
        if isinstance(data, dict) and "error" in data:
            code = data.get("error")
            detail = f"Last.fm error {code}: {data.get('message')}"
            if code in _NOT_FOUND_ERRORS:
                raise LastfmNotFound(detail)
            raise ProviderError(detail)
        return data


def _parse_tags(data: dict, limit: int) -> list[TagCount]:
    """Read ``{"toptags": {"tag": [{"name", "count"}]}}``, heaviest tag first.

    Tags are returned as-is: no genre whitelist, no filtering of "seen live" or
    similar — weighting and filtering belong to the consumer.
    """
    container = data.get("toptags") or {}
    items = container.get("tag") or []
    if isinstance(items, dict):  # Last.fm collapses a single result to a dict.
        items = [items]

    tags: list[TagCount] = []
    for item in items:
        name = (item.get("name") or "").strip()
        if not name:
            continue
        try:
            weight = int(item.get("count") or 0)
        except (TypeError, ValueError):
            weight = 0
        tags.append(TagCount(name=name, weight=weight))

    tags.sort(key=lambda tag: tag.weight, reverse=True)
    return tags[:limit]


def _parse_candidates(data: dict, root_key: str) -> list[TrackCandidate]:
    """Pull (artist, title) pairs out of a Last.fm track-list payload.

    Shapes vary by method but share ``{<root_key>: {"track": [ {name, artist} ]}}``
    where ``artist`` is either a dict with ``name`` or a bare string.
    """
    container = data.get(root_key) or {}
    items = container.get("track") or []
    if isinstance(items, dict):  # Last.fm collapses a single result to a dict.
        items = [items]

    candidates: list[TrackCandidate] = []
    for item in items:
        title = (item.get("name") or "").strip()
        artist = item.get("artist")
        if isinstance(artist, dict):
            artist_name = (artist.get("name") or "").strip()
        else:
            artist_name = (artist or "").strip()
        if title and artist_name:
            candidates.append(TrackCandidate(artist=artist_name, title=title))
    return candidates
