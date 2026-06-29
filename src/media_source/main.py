from contextlib import asynccontextmanager

from fastapi import FastAPI

from media_source.api.routes import router
from media_source.config import get_settings
from media_source.providers.registry import build_default_registry


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.registry = build_default_registry()
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
