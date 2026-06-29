import os
from datetime import timezone

import pytest

from media_source.providers.base import ProviderError
from media_source.providers.youtube import (
    YouTubeProvider,
    _build_cookie_opts,
    _extract_expiry,
    _parse_browser_spec,
)


def test_entry_to_track_fills_missing_url():
    p = YouTubeProvider()
    track = p._entry_to_track({"id": "abc", "title": "Song"})
    assert track is not None
    assert track.url == "https://www.youtube.com/watch?v=abc"
    assert track.provider == "youtube"


def test_entry_to_track_skips_incomplete_entries():
    p = YouTubeProvider()
    assert p._entry_to_track({"id": "", "title": "Song"}) is None
    assert p._entry_to_track({"id": "abc", "title": ""}) is None


def test_entry_to_track_prefers_channel_when_no_uploader():
    p = YouTubeProvider()
    track = p._entry_to_track({"id": "abc", "title": "S", "channel": "Chan"})
    assert track.uploader == "Chan"


def test_extract_expiry_parses_unix_timestamp():
    url = "https://rr.googlevideo.com/x?expire=1700000000&foo=bar"
    dt = _extract_expiry(url)
    assert dt is not None
    assert dt.tzinfo == timezone.utc
    assert dt.year == 2023


def test_extract_expiry_handles_missing_param():
    assert _extract_expiry("https://cdn/x?foo=bar") is None
    assert _extract_expiry("https://cdn/x?expire=notanumber") is None


def test_build_cookie_opts_none():
    assert _build_cookie_opts(None, None) == {}


def test_build_cookie_opts_file_makes_writable_copy(tmp_path):
    src = tmp_path / "cookies.txt"
    src.write_text("# Netscape HTTP Cookie File\n")
    copy = _build_cookie_opts(str(src), None)["cookiefile"]
    assert copy != str(src)
    assert os.path.exists(copy)
    assert open(copy).read() == "# Netscape HTTP Cookie File\n"


def test_build_cookie_opts_browser():
    assert _build_cookie_opts(None, "chrome") == {
        "cookiesfrombrowser": ("chrome", None, None, None)
    }


def test_build_cookie_opts_rejects_both():
    with pytest.raises(ValueError):
        _build_cookie_opts("/c.txt", "chrome")


def test_parse_browser_spec_with_profile():
    assert _parse_browser_spec("Firefox:Default") == ("firefox", "Default", None, None)


def test_cookiefile_threads_writable_copy_into_ydl_opts(tmp_path):
    src = tmp_path / "c.txt"
    src.write_text("# Netscape HTTP Cookie File\n")
    p = YouTubeProvider(cookiefile=str(src))
    assert os.path.exists(p._search_opts["cookiefile"])
    assert os.path.exists(p._stream_opts["cookiefile"])


async def test_resolve_playlist_parses_entries_and_skips_incomplete():
    p = YouTubeProvider()
    p._extract = lambda target, opts: {
        "entries": [
            {"id": "a", "title": "A"},
            {"id": "", "title": "no id"},  # skipped
            {"id": "b", "title": "B"},
        ]
    }
    tracks = await p.resolve_playlist("PLxyz", limit=10)
    assert [t.id for t in tracks] == ["a", "b"]
    assert all(t.provider == "youtube" for t in tracks)


async def test_resolve_playlist_honours_limit():
    p = YouTubeProvider()
    p._extract = lambda target, opts: {
        "entries": [{"id": f"i{n}", "title": str(n)} for n in range(10)]
    }
    tracks = await p.resolve_playlist("PLxyz", limit=3)
    assert len(tracks) == 3


async def test_resolve_playlist_builds_url_from_bare_id():
    captured = {}

    def fake_extract(target, opts):
        captured["target"] = target
        return {"entries": [{"id": "a", "title": "A"}]}

    p = YouTubeProvider()
    p._extract = fake_extract
    await p.resolve_playlist("PLABC", limit=5)
    assert captured["target"] == "https://www.youtube.com/playlist?list=PLABC"


async def test_resolve_playlist_passes_full_url_through():
    captured = {}

    def fake_extract(target, opts):
        captured["target"] = target
        return {"entries": [{"id": "a", "title": "A"}]}

    p = YouTubeProvider()
    p._extract = fake_extract
    url = "https://www.youtube.com/playlist?list=PLABC"
    await p.resolve_playlist(url, limit=5)
    assert captured["target"] == url


async def test_resolve_playlist_empty_raises():
    p = YouTubeProvider()
    p._extract = lambda target, opts: {"entries": []}
    with pytest.raises(ProviderError):
        await p.resolve_playlist("PLxyz", limit=5)
