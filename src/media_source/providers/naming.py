"""Clean YouTube-derived names so they can be looked up on Last.fm.

Consumers pass through whatever the YouTube search returned, which is rarely a
clean artist name: auto-generated ``"... - Topic"`` channels, ``VEVO`` suffixes,
marketing tails like ``[OFFICIAL VIDEO]``, and titles that pack
``"Artist - Track"`` into a single string. Last.fm only matches tidy names, so
normalisation lives here, next to the Last.fm client, rather than in consumers.
"""

import re

# Bracketed segments that are marketing noise rather than part of the title.
# Anything not matching these keywords (e.g. "(Remix)", "(feat. X)") is kept,
# because it genuinely identifies a different recording.
_NOISE_KEYWORDS = (
    "official",
    "video",
    "audio",
    "lyric",
    "hd",
    "hq",
    "4k",
    "mv",
    "m/v",
    "visualizer",
    "visualiser",
    "explicit",
    "remaster",
    "full album",
    "free download",
    "ncs release",
    "clip officiel",
)

_BRACKETED = re.compile(r"[\[\(\{]([^\[\]\(\){}]*)[\]\)\}]")
_TOPIC = re.compile(r"\s*-\s*topic\s*$", re.IGNORECASE)
_VEVO = re.compile(r"\s*vevo\s*$", re.IGNORECASE)
_WHITESPACE = re.compile(r"\s+")
# "Artist - Track". Requires whitespace around the dash so hyphenated names
# such as "Dinosaur Pile-Up" are never split.
_SEPARATOR = re.compile(r"\s+[-‒–—]\s+")


def clean_name(raw: str | None) -> str:
    """Strip marketing noise, "- Topic"/"VEVO" suffixes and stray punctuation."""
    if not raw:
        return ""
    text = _BRACKETED.sub(_drop_if_noise, raw)
    text = _TOPIC.sub("", text)
    text = _VEVO.sub("", text)
    text = _WHITESPACE.sub(" ", text).strip()
    return text.strip("-‒–— ").strip()


def normalize_artist(raw: str | None) -> str:
    """Best-effort artist name.

    ``"Death From Above 1979 - Topic"`` -> ``"Death From Above 1979"``
    ``"Slipknot - Psychosocial [OFFICIAL VIDEO] [HD]"`` -> ``"Slipknot"``
    """
    text = clean_name(raw)
    if not text:
        return ""
    return _SEPARATOR.split(text, maxsplit=1)[0].strip()


def normalize_track(raw: str | None) -> str:
    """Best-effort track title.

    ``"Slipknot - Psychosocial [HD]"`` -> ``"Psychosocial"``
    ``"Psychosocial"`` -> ``"Psychosocial"``
    """
    text = clean_name(raw)
    if not text:
        return ""
    parts = _SEPARATOR.split(text, maxsplit=1)
    return (parts[1] if len(parts) > 1 else parts[0]).strip()


def _drop_if_noise(match: re.Match) -> str:
    inner = match.group(1).casefold()
    return "" if any(word in inner for word in _NOISE_KEYWORDS) else match.group(0)
