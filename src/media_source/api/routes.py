from fastapi import APIRouter, Depends, HTTPException, Query, Request

from media_source.config import Settings, get_settings
from media_source.models.schemas import SearchResponse, StreamResponse
from media_source.providers.base import Provider, ProviderError
from media_source.providers.registry import ProviderRegistry

router = APIRouter()


def get_registry(request: Request) -> ProviderRegistry:
    return request.app.state.registry


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
