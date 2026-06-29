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
