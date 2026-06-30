from fastapi import APIRouter, Depends, HTTPException, Query, Request

from media_source.config import Settings, get_settings
from media_source.models.schemas import (
    DiscoveryResponse,
    PlaylistResponse,
    SearchResponse,
    StreamResponse,
)
from media_source.providers.base import Provider, ProviderError
from media_source.providers.lastfm import LastfmNotConfigured
from media_source.providers.registry import ProviderRegistry
from media_source.services.discovery import DiscoveryService

router = APIRouter()


def get_registry(request: Request) -> ProviderRegistry:
    return request.app.state.registry


def get_discovery(request: Request) -> DiscoveryService:
    return request.app.state.discovery


def resolve_provider(name: str, registry: ProviderRegistry) -> Provider:
    provider = registry.get(name)
    if provider is None:
        raise HTTPException(
            status_code=404,
            detail=f"unknown provider {name!r}; available: {registry.names()}",
        )
    return provider


@router.get("/health")
async def health(registry: ProviderRegistry = Depends(get_registry)) -> dict:
    return {"status": "ok", "providers": registry.names()}


@router.get("/search", response_model=SearchResponse)
async def search(
    q: str = Query(..., min_length=1, description="Search query."),
    provider: str = Query("youtube", description="Provider id."),
    limit: int | None = Query(None, ge=1, description="Max results."),
    registry: ProviderRegistry = Depends(get_registry),
    settings: Settings = Depends(get_settings),
) -> SearchResponse:
    prov = resolve_provider(provider, registry)
    effective_limit = min(limit or settings.default_search_limit, settings.max_search_limit)

    try:
        results = await prov.search(q, effective_limit)
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return SearchResponse(provider=provider, query=q, results=results)


@router.get("/playlist", response_model=PlaylistResponse)
async def playlist(
    url: str = Query(..., min_length=1, description="Playlist URL or id."),
    provider: str = Query("youtube", description="Provider id."),
    limit: int | None = Query(None, ge=1, description="Max tracks."),
    registry: ProviderRegistry = Depends(get_registry),
    settings: Settings = Depends(get_settings),
) -> PlaylistResponse:
    prov = resolve_provider(provider, registry)
    effective_limit = min(
        limit or settings.default_playlist_limit, settings.max_playlist_limit
    )

    try:
        results = await prov.resolve_playlist(url, effective_limit)
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return PlaylistResponse(provider=provider, playlist=url, results=results)


@router.get("/stream", response_model=StreamResponse)
async def stream(
    id: str = Query(..., min_length=1, description="Provider-local track id."),
    provider: str = Query("youtube", description="Provider id."),
    registry: ProviderRegistry = Depends(get_registry),
) -> StreamResponse:
    prov = resolve_provider(provider, registry)
    try:
        return await prov.resolve_stream(id)
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/similar", response_model=DiscoveryResponse)
async def similar(
    artist: str = Query(..., min_length=1, description="Seed artist."),
    track: str = Query(..., min_length=1, description="Seed track title."),
    limit: int | None = Query(None, ge=1, description="Max results."),
    discovery: DiscoveryService = Depends(get_discovery),
    settings: Settings = Depends(get_settings),
) -> DiscoveryResponse:
    effective_limit = min(limit or settings.default_search_limit, settings.max_search_limit)
    results = await _discover(discovery.similar(artist, track, effective_limit))
    return DiscoveryResponse(results=results)


@router.get("/charts", response_model=DiscoveryResponse)
async def charts(
    tag: str | None = Query(None, min_length=1, description="Genre/mood tag."),
    country: str | None = Query(
        None, min_length=1, description="ISO country name for geo charts."
    ),
    limit: int | None = Query(None, ge=1, description="Max results."),
    discovery: DiscoveryService = Depends(get_discovery),
    settings: Settings = Depends(get_settings),
) -> DiscoveryResponse:
    effective_limit = min(limit or settings.default_search_limit, settings.max_search_limit)
    results = await _discover(
        discovery.charts(tag=tag, country=country, limit=effective_limit)
    )
    return DiscoveryResponse(results=results)


async def _discover(coro):
    """Await a discovery coroutine, mapping its failures to the HTTP error
    model: missing API key -> 503, upstream/provider failure -> 502."""
    try:
        return await coro
    except LastfmNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
