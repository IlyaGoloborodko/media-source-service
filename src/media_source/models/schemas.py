from datetime import datetime

from pydantic import BaseModel, Field


class Track(BaseModel):
    """A single searchable media item, independent of its source provider."""

    provider: str = Field(description="Source provider id, e.g. 'youtube'.")
    id: str = Field(description="Provider-local id used to resolve a stream.")
    title: str
    uploader: str | None = None
    url: str | None = Field(default=None, description="Human-facing page URL.")
    duration: float | None = Field(default=None, description="Length in seconds.")
    thumbnail: str | None = None


class SearchResponse(BaseModel):
    provider: str
    query: str
    results: list[Track]


class Tag(BaseModel):
    """A genre/style tag with its Last.fm popularity count."""

    name: str
    weight: int = Field(description="Last.fm tag count, 0-100.")


class TagsResponse(BaseModel):
    """Tags for an artist or track. An empty list means "genre unknown", which
    is a valid answer rather than an error."""

    tags: list[Tag]


class DiscoveryResponse(BaseModel):
    """Discovery results, already resolved to playable Tracks (same shape as
    ``/search`` results) so the bot can ``/stream`` them unchanged."""

    results: list[Track]


class PlaylistResponse(BaseModel):
    provider: str
    playlist: str = Field(description="Requested playlist reference (URL or id).")
    results: list[Track]


class StreamResponse(BaseModel):
    """Resolved direct stream URL. Bytes are served by the provider CDN, not
    proxied through this service."""

    provider: str
    id: str
    stream_url: str
    expires_at: datetime | None = Field(
        default=None,
        description="When the CDN URL stops working, if derivable.",
    )
