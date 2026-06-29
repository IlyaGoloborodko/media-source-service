from abc import ABC, abstractmethod

from media_source.models.schemas import StreamResponse, Track


class ProviderError(Exception):
    """Raised when an upstream provider fails to fulfil a request."""


class Provider(ABC):
    """A media source. Adding a new source means implementing this interface
    and registering the instance; the HTTP contract stays unchanged."""

    #: Stable, lowercase id used in API paths/params, e.g. "youtube".
    name: str

    @abstractmethod
    async def search(self, query: str, limit: int) -> list[Track]:
        """Return up to ``limit`` tracks matching ``query``."""

    @abstractmethod
    async def resolve_stream(self, track_id: str) -> StreamResponse:
        """Resolve a playable direct stream URL for ``track_id``."""
