import pytest

from media_source.providers.naming import clean_name, normalize_artist, normalize_track


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Death From Above 1979 - Topic", "Death From Above 1979"),
        ("Slipknot - Topic", "Slipknot"),
        ("SlipknotVEVO", "Slipknot"),
        ("Rick Astley VEVO", "Rick Astley"),
        ("Dinosaur Pile-Up", "Dinosaur Pile-Up"),  # hyphen without spaces: not a split
        ("Slipknot - Psychosocial [OFFICIAL VIDEO] [HD]", "Slipknot"),
        ("Slipknot - Psychosocial (Official Music Video)", "Slipknot"),
        ("MONTAGEM ALQUIMIA", "MONTAGEM ALQUIMIA"),  # no artist to extract
        ("  Muse   -   Hysteria  ", "Muse"),
        ("Artist – Track", "Artist"),  # en dash
        ("", ""),
        (None, ""),
    ],
)
def test_normalize_artist(raw, expected):
    assert normalize_artist(raw) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Slipknot - Psychosocial [HD]", "Psychosocial"),
        ("Psychosocial", "Psychosocial"),
        ("Slipknot - Psychosocial [OFFICIAL VIDEO]", "Psychosocial"),
        ("Song (Remix)", "Song (Remix)"),  # meaningful brackets survive
        ("Song (feat. Someone)", "Song (feat. Someone)"),
        ("", ""),
    ],
)
def test_normalize_track(raw, expected):
    assert normalize_track(raw) == expected


def test_clean_name_drops_only_noise_brackets():
    assert clean_name("Track [HD] (Remix) [Official Video]") == "Track (Remix)"


def test_clean_name_collapses_whitespace_and_trims_dashes():
    assert clean_name("  Some   Name -  ") == "Some Name"
