import logging
from contextlib import asynccontextmanager

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from media_source.api.routes import router
from media_source.config import get_settings
from media_source.logging_setup import setup_logging
from media_source.providers.lastfm import LastfmClient
from media_source.providers.registry import build_default_registry
from media_source.services.discovery import DiscoveryService

load_dotenv()
setup_logging()  # after load_dotenv: the levels and the Telegram token come from .env

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    registry = build_default_registry(settings)
    app.state.registry = registry

    logger.info(
        "starting: providers=%s lastfm_key=%s",
        registry.names(),
        "set" if settings.lastfm_api_key else "missing",
    )

    # One shared HTTP client for all Last.fm calls, closed on shutdown.
    async with httpx.AsyncClient(timeout=10.0) as http_client:
        lastfm = LastfmClient(settings.lastfm_api_key, client=http_client)
        app.state.lastfm = lastfm
        app.state.discovery = DiscoveryService(lastfm, registry.get("youtube"))
        yield

    logger.info("shutting down")


def create_app() -> FastAPI:
    app = FastAPI(
        title="media-source-service",
        version="0.1.0",
        summary="Provider-agnostic media search and stream-URL resolution.",
        lifespan=lifespan,
    )
    app.include_router(router)

    @app.exception_handler(Exception)
    async def unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
        """Anything that reached here is a bug, not an expected upstream failure
        — log it with a traceback so it reaches Telegram."""
        logger.exception(
            "unhandled error on %s %s", request.method, request.url.path
        )
        return JSONResponse(status_code=500, content={"detail": "internal error"})

    return app


app = create_app()


def main() -> None:
    import uvicorn

    settings = get_settings()
    # log_config=None keeps uvicorn from installing its own handlers, so its
    # errors travel up to ours and reach Telegram like everything else.
    uvicorn.run(app, host=settings.host, port=settings.port, log_config=None)


if __name__ == "__main__":
    main()
