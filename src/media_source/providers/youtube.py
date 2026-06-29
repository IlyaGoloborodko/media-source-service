import asyncio
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

_STREAM_OPTS: dict[str, Any] = {
    "quiet": True,
    "no_warnings": True,
    "skip_download": True,
    "noplaylist": True,
    "format": "bestaudio",
}


class YouTubeProvider(Provider):
    name = "youtube"

    def __init__(self, search_opts: dict | None = None, stream_opts: dict | None = None):
        self._search_opts = {**_SEARCH_OPTS, **(search_opts or {})}
        self._stream_opts = {**_STREAM_OPTS, **(stream_opts or {})}

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


def _extract_expiry(stream_url: str) -> datetime | None:
    """Googlevideo CDN URLs carry an `expire` unix-timestamp query param."""
    expire = parse_qs(urlparse(stream_url).query).get("expire", [None])[0]
    if not expire:
        return None
    try:
        return datetime.fromtimestamp(int(expire), tz=timezone.utc)
    except (ValueError, OverflowError, OSError):
        return None
