from media_source.config import Settings, get_settings
from media_source.providers.base import Provider
from media_source.providers.youtube import YouTubeProvider


class ProviderRegistry:
    """Holds the available providers keyed by their ``name``."""

    def __init__(self, providers: list[Provider]):
        self._providers = {p.name: p for p in providers}

    def get(self, name: str) -> Provider | None:
        return self._providers.get(name)

    def names(self) -> list[str]:
        return list(self._providers)


def build_default_registry(settings: Settings | None = None) -> ProviderRegistry:
    settings = settings or get_settings()
    return ProviderRegistry(
        [
            YouTubeProvider(
                cookiefile=settings.ytdlp_cookiefile,
                cookies_from_browser=settings.ytdlp_cookies_from_browser,
            )
        ]
    )
