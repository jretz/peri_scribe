"""Recognize sourced formats without mistaking partial tokens for registrations."""

import pytest

import aircraft_registration


@pytest.mark.parametrize(
    "tail_number",
    [
        "N1",
        "N12345",
        "N1234A",
        "N123AB",
        "N5852K",
        "N874EB",
        "N9Z",
        "N9ZZ",
        "NC12345",
        "NR1234A",
        "NL123AB",
        "NX123",
        "C-FABC",
        "C-GABC",
        "C-IABC",
        "CF-ABC",
        "C-FQAA",
        "VH-ABC",
        "VH-A1B",
        "VH-123",
        "ZK-ABC",
        "G-ABCD",
        "F-ABCD",
        "D-ABCD",
        "D-HABC",
        "D-MABC",
        "D-1234",
        "D-0123",
        "PP-ABC",
        "PR-ABC",
        "PS-ABC",
        "PT-ABC",
        "PU-ABC",
        "JA1234",
        "JA123A",
        "JA12AB",
        "9V-ABC",
    ],
)
def test_split_tail_number_recognizes_national_formats(tail_number: str) -> None:
    assert aircraft_registration.split_tail_number(tail_number) == (
        aircraft_registration.TailNumberSplit(prefix="", tail_number=tail_number)
    )


@pytest.mark.parametrize(
    "tail_number",
    [
        "5Y-ABC",
        "9XR-ABC",
        "9GR-ABC",
        "3DC-ABC",
        "A4O-ABC",
        "A9C-ABC",
        "B-12345",
        "RA-12345",
        "RA12345",
        "RDPL-34123",
        "RP-C1234",
        "P-123",
        "Z-WAB",
        "2-ABCD",
        "M-ABCD",
        "ZJ-ABC",
        "VP-CAA",
        "VQ-BAB",
        "VP-LAA",
        "VQ-TAA",
        "XA-ABC",
        "HB-ABC",
        "4YB-ABC",
        "E5-ABC",
        "ZL-ABC",
        "ZM-ABC",
        "CR-ABC",
        "EJ-ABC",
        "XV-ABC",
        "8Q-ABC",
        "9Y-ABC",
    ],
)
def test_split_tail_number_recognizes_notified_and_common_marks(
    tail_number: str,
) -> None:
    assert aircraft_registration.split_tail_number(f"Dome-{tail_number}") == (
        aircraft_registration.TailNumberSplit(prefix="Dome", tail_number=tail_number)
    )


@pytest.mark.parametrize(
    "text",
    [
        "",
        "  ",
        "DOME",
        "NORTH",
        "CREEK",
        "DOME-NORTH",
        "FIRE-40Y",
        "50X",
        "40Y",
        "FIRE-50X",
        "N",
        "N0",
        "N0123",
        "N123456",
        "N12345A",
        "N1234AB",
        "N123ABC",
        "N12I",
        "N12O",
        "N-5852K",
        "N\uff11\uff12\uff13",
        "N\u0661\u0662\u0663",
        "N12\u017f",
        "N12\u212a",
        "C-ABCD",
        "C-F12A",
        "C-FABCDE",
        "CF-ABCD",
        "VH-AB",
        "VH-ABCD",
        "ZK-123",
        "G-ABC",
        "G-1234",
        "F-ABC",
        "D-ZABC",
        "D-123A",
        "PS-ABCD",
        "PP-123",
        "JA12345",
        "JA1ABC",
        "JA123I",
        "JA123O",
        "JA123S",
        "JA12CC",
        "JA12JA",
        "9V-123",
        "XX-ABC",
        "T2-ABC",
        "A2ABC",
        "4YBABC",
        "VH-SOS",
        "5Y-QAB",
        "5Y-XXX",
        "5Y-PAN",
        "5Y-TTT",
        "5Y-SOS",
        "xN5852K",
        "x_N5852K",
        "N5852K-extra",
        "N5852K.txt",
        "N5852K!",
        "Dome-C-FABC-more",
        "Dome\u2013N5852K",
    ],
)
def test_split_tail_number_rejects_incomplete_or_invalid_registrations(
    text: str,
) -> None:
    assert aircraft_registration.split_tail_number(text) is None


@pytest.mark.parametrize(
    ("text", "prefix", "tail_number"),
    [
        ("CA-YNP-DOME-N5852K", "CA-YNP-DOME", "N5852K"),
        ("  Mixed Case — Fire - n874eb \t", "  Mixed Case — Fire", "N874EB"),
        ("Dôme\u2003c-fabc", "Dôme", "C-FABC"),
        ("Dome--vh-a1b", "Dome", "VH-A1B"),
        ("Dome-vp-caa", "Dome", "VP-CAA"),
        ("  n5852k  ", "", "N5852K"),
        ("N5852K N874EB", "N5852K", "N874EB"),
    ],
)
def test_split_tail_number_preserves_prefix_and_complete_tail(
    text: str,
    prefix: str,
    tail_number: str,
) -> None:
    assert aircraft_registration.split_tail_number(text) == (
        aircraft_registration.TailNumberSplit(prefix=prefix, tail_number=tail_number)
    )
