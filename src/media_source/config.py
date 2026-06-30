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

    # Playlists are larger than searches, so they get their own limits.
    default_playlist_limit: int = 50
    max_playlist_limit: int = 100

    # Optional path to a yt-dlp binary. Unused when yt-dlp is imported as a
    # library (the default), kept for environments that prefer the CLI.
    ytdlp_binary: str | None = None

    # --- YouTube authentication (cookies) ------------------------------------
    # Unauthenticated requests get rate-limited and eventually blocked
    # ("Sign in to confirm you're not a bot"). Provide ONE of the two below
    # (never both — yt-dlp forbids combining them). See README for export steps.
    #
    # Path to a Netscape-format cookies.txt (equivalent to `--cookies FILE`).
    # The only option that works inside a container (no browser there).
    ytdlp_cookiefile: str | None = None
    # Read cookies straight from a local browser, e.g. "chrome" or
    # "firefox:profile" (equivalent to `--cookies-from-browser`). Host-only.
    ytdlp_cookies_from_browser: str | None = None

    # --- Last.fm (music discovery) -------------------------------------------
    # API key for Last.fm metadata calls (similar tracks, charts, top-by-tag).
    # Read from MSS_LASTFM_API_KEY. Without it, the discovery endpoints return
    # 503. Never logged. https://www.last.fm/api/account/create
    lastfm_api_key: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
