from datetime import timezone

from media_source.providers.youtube import YouTubeProvider, _extract_expiry


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
