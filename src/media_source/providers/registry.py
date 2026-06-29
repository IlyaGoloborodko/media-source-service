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


def build_default_registry() -> ProviderRegistry:
    return ProviderRegistry([YouTubeProvider()])
