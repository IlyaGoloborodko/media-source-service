from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Service configuration, overridable via env vars (prefix MSS_) or .env."""

    model_config = SettingsConfigDict(
        env_prefix="MSS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    host: str = "0.0.0.0"
    port: int = 8080

    # Default result count for search when the client does not specify one.
    default_search_limit: int = 10
    # Hard cap so a client cannot ask the upstream for an unbounded list.
    max_search_limit: int = 25

    # Optional path to a yt-dlp binary. Unused when yt-dlp is imported as a
    # library (the default), kept for environments that prefer the CLI.
    ytdlp_binary: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
