import unicodedata

import pytest

from phenix_apps.common.go_unicode import GO_UNICODE_VERSION, go_is_print


@pytest.mark.parametrize(
    ("c", "printable"),
    [
        (" ", True),
        ("~", True),
        ("é", True),
        ("\U0001f525", True),
        ("\U000323af", True),
        ("\t", False),
        ("\x7f", False),
        ("\u00a0", False),
        ("\u00ad", False),
        ("\u2028", False),
        ("\ud800", False),
        # Added in Unicode 15.1.
        ("\u2ffc", False),
        ("\u31ef", False),
        ("\U0002ebf0", False),
    ],
)
def test_go_is_print_follows_go_at_unicode_15_0(c, printable):
    assert go_is_print(c) is printable


@pytest.mark.skipif(
    unicodedata.unidata_version != GO_UNICODE_VERSION,
    reason=f"Python's Unicode database is not {GO_UNICODE_VERSION}",
)
def test_go_is_print_is_isprintable_at_the_same_unicode_version():
    """Python 3.12 and Go 1.24 both define printable as the categories L, M, N,
    P and S plus the ASCII space."""
    differ = [
        f"U+{cp:04X}"
        for cp in range(0x110000)
        if go_is_print(chr(cp)) != chr(cp).isprintable()
    ]

    assert differ == []
