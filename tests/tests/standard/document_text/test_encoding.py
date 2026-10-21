"""Normalization preserves portable text and replaces unsupported XML characters."""

import pytest

import document_text.encoding


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("", ""),
        ("\r\r\n\x85\r\n\r", "\n\n\n\n\n"),
        ("\x00\x08\x0b\x0c\x0e\x1f", "\ufffd" * 6),
        ("\ud83d\udd25", "\ufffd\ufffd"),
        (
            "\ud7ff\ud800\udfff\ue000\ufffd\ufffe\uffff",
            "\ud7ff\ufffd\ufffd\ue000\ufffd\ufffd\ufffd",
        ),
        (
            "\t\n \u0084\u0086\u2028\u2029\U0001fffe\U0001ffff\U0010ffff",
            "\t\n \u0084\u0086\u2028\u2029\U0001fffe\U0001ffff\U0010ffff",
        ),
        ("Cafe\u0301 日本 🔥🔥", "Cafe\u0301 日本 🔥🔥"),
    ],
)
def test_normalized_preserves_the_declared_portable_text(
    source: str,
    expected: str,
) -> None:
    assert document_text.encoding.normalized(source) == expected
