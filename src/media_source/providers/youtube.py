import asyncio
import os
import shutil
import tempfile
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qs, urlparse

from yt_dlp import YoutubeDL

from media_source.models.schemas import StreamResponse, Track
from media_source.providers.base import Provider, ProviderError

# Shared, mostly-immutable yt-dlp options. extract_flat keeps search cheap by
# skipping per-video metadata extraction (we only need id/title for a list).
_SEARCH_OPTS: dict[str, Any] = {
    "quiet": True,
    "no_warnings": True,
    "skip_download": True,
    "extract_flat": True,
    "default_search": "ytsearch",
}

# Like search, but resolves playlists instead of forbidding them. Still flat:
# we only need each entry's id/title, not per-video metadata.
_PLAYLIST_OPTS: dict[str, Any] = {
    "quiet": True,
    "no_warnings": True,
    "skip_download": True,
    "extract_flat": True,
    "noplaylist": False,
}

_STREAM_OPTS: dict[str, Any] = {
    "quiet": True,
    "no_warnings": True,
    "skip_download": True,
    "noplaylist": True,
    # Prefer an audio-only stream; fall back to best combined when a video has
    # no audio-only format (e.g. HLS-only livestreams/premieres). The consumer
    # extracts audio from the combined stream with ffmpeg.
    "format": "bestaudio/best",
}


class YouTubeProvider(Provider):
    name = "youtube"

    def __init__(
        self,
        cookiefile: str | None = None,
        cookies_from_browser: str | None = None,
        search_opts: dict | None = None,
        stream_opts: dict | None = None,
    ):
        cookie_opts = _build_cookie_opts(cookiefile, cookies_from_browser)
        self._search_opts = {**_SEARCH_OPTS, **cookie_opts, **(search_opts or {})}
        self._stream_opts = {**_STREAM_OPTS, **cookie_opts, **(stream_opts or {})}
        self._playlist_opts = {**_PLAYLIST_OPTS, **cookie_opts}

    async def search(self, query: str, limit: int) -> list[Track]:
        query = query.strip()
        if not query:
            return []

        info = await asyncio.to_thread(self._extract, f"ytsearch{limit}:{query}", self._search_opts)
        entries = (info or {}).get("entries") or []

        tracks: list[Track] = []
        for entry in entries:
            track = self._entry_to_track(entry)
            if track is not None:
                tracks.append(track)
            if len(tracks) >= limit:
                break
        return tracks

    async def resolve_stream(self, track_id: str) -> StreamResponse:
        url = f"https://www.youtube.com/watch?v={track_id}"
        info = await asyncio.to_thread(self._extract, url, self._stream_opts)
        if not info:
            raise ProviderError(f"no stream info for id {track_id!r}")

        stream_url = info.get("url")
        if not stream_url:
            raise ProviderError(f"yt-dlp returned no playable URL for id {track_id!r}")

        return StreamResponse(
            provider=self.name,
            id=track_id,
            stream_url=stream_url,
            expires_at=_extract_expiry(stream_url),
        )

    async def resolve_playlist(self, playlist: str, limit: int) -> list[Track]:
        playlist = playlist.strip()
        target = (
            playlist
            if playlist.startswith("http")
            else f"https://www.youtube.com/playlist?list={playlist}"
        )

        info = await asyncio.to_thread(self._extract, target, self._playlist_opts)
        entries = (info or {}).get("entries") or []

        tracks: list[Track] = []
        for entry in entries:
            track = self._entry_to_track(entry)
            if track is not None:
                tracks.append(track)
            if len(tracks) >= limit:
                break

        if not tracks:
            raise ProviderError(f"playlist {playlist!r} yielded no tracks")
        return tracks

    @staticmethod
    def _extract(target: str, opts: dict[str, Any]) -> dict[str, Any] | None:
        try:
            with YoutubeDL(opts) as ydl:
                return ydl.extract_info(target, download=False)
        except Exception as exc:  # yt-dlp raises a wide range of exceptions
            raise ProviderError(str(exc)) from exc

    def _entry_to_track(self, entry: dict[str, Any]) -> Track | None:
        video_id = (entry.get("id") or "").strip()
        title = (entry.get("title") or "").strip()
        if not video_id or not title:
            return None

        url = entry.get("webpage_url") or entry.get("url")
        if not url or not url.startswith("http"):
            url = f"https://www.youtube.com/watch?v={video_id}"

        return Track(
            provider=self.name,
            id=video_id,
            title=title,
            uploader=entry.get("uploader") or entry.get("channel"),
            url=url,
            duration=entry.get("duration"),
            thumbnail=entry.get("thumbnail"),
        )


def _build_cookie_opts(
    cookiefile: str | None, cookies_from_browser: str | None
) -> dict[str, Any]:
    """Translate cookie settings into yt-dlp options.

    yt-dlp forbids combining a cookie file with browser extraction, so we
    reject that up front instead of letting it fail mid-request.
    """
    if cookiefile and cookies_from_browser:
        raise ValueError(
            "set only one of ytdlp_cookiefile / ytdlp_cookies_from_browser"
        )
    if cookiefile:
        return {"cookiefile": _writable_cookie_copy(cookiefile)}
    if cookies_from_browser:
        return {"cookiesfrombrowser": _parse_browser_spec(cookies_from_browser)}
    return {}


def _writable_cookie_copy(cookiefile: str) -> str:
    """Return a writable copy of ``cookiefile``.

    yt-dlp writes rotated cookies back to the cookie file after each run. When
    the source is a read-only mount (e.g. Docker ``:ro``) that write fails with
    "Read-only file system"; even a writable single-file bind mount breaks
    because yt-dlp saves via an atomic rename onto the mount point. Copying to a
    private temp file sidesteps both. The original (mounted) file is untouched.
    """
    fd, dst = tempfile.mkstemp(prefix="mss_cookies_", suffix=".txt")
    os.close(fd)
    shutil.copyfile(cookiefile, dst)
    return dst


def _parse_browser_spec(spec: str) -> tuple[str, str | None, None, None]:
    """Parse a "browser[:profile]" string into yt-dlp's cookiesfrombrowser
    4-tuple ``(browser, profile, keyring, container)``."""
    name, _, profile = spec.partition(":")
    return (name.strip().lower(), profile.strip() or None, None, None)


def _extract_expiry(stream_url: str) -> datetime | None:
    """Googlevideo CDN URLs carry an `expire` unix-timestamp query param."""
    expire = parse_qs(urlparse(stream_url).query).get("expire", [None])[0]
    if not expire:
        return None
    try:
        return datetime.fromtimestamp(int(expire), tz=timezone.utc)
    except (ValueError, OverflowError, OSError):
        return None
