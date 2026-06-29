import os
from datetime import timezone

import pytest

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
