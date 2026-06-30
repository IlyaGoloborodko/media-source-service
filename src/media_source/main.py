from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from media_source.api.routes import router
from media_source.config import get_settings
from media_source.providers.lastfm import LastfmClient
from media_source.providers.registry import build_default_registry
from media_source.services.discovery import DiscoveryService


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    registry = build_default_registry(settings)
    app.state.registry = registry

    # One shared HTTP client for all Last.fm calls, closed on shutdown.
    async with httpx.AsyncClient(timeout=10.0) as http_client:
        lastfm = LastfmClient(settings.lastfm_api_key, client=http_client)
        app.state.discovery = DiscoveryService(lastfm, registry.get("youtube"))
        yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="media-source-service",
        version="0.1.0",
        summary="Provider-agnostic media search and stream-URL resolution.",
        lifespan=lifespan,
    )
    app.include_router(router)
    return app


app = create_app()


def main() -> None:
    import uvicorn

    settings = get_settings()
    uvicorn.run(app, host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
