"""Last.fm metadata client.

Last.fm is metadata-only: it yields "artist + title" candidates, never a
playable stream or a YouTube id. The discovery layer (services/discovery.py)
turns these candidates into playable Tracks via the YouTube provider.
"""

from dataclasses import dataclass
from typing import Any

import httpx

from media_source.providers.base import ProviderError

_BASE_URL = "https://ws.audioscrobbler.com/2.0/"


@dataclass(frozen=True)
class TrackCandidate:
    """A bare "artist + title" suggestion from Last.fm, not yet playable."""

    artist: str
    title: str


class LastfmNotConfigured(Exception):
    """Raised when a Last.fm call is attempted without an API key configured."""


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
            raise ProviderError(
                f"Last.fm error {data.get('error')}: {data.get('message')}"
            )
        return data


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
