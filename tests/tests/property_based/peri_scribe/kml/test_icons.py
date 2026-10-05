"""Tests for peri_scribe.kml.icons."""

from __future__ import annotations

import io

import hypothesis
import PIL.Image

import peri_scribe.kml.icons
import tests.helpers.strategies.peri_scribe.kml.icons


@hypothesis.given(image=tests.helpers.strategies.peri_scribe.kml.icons.rgba_images())
def test_png_from_rows_round_trips_through_an_independent_decoder(
    image: tuple[int, bytes],
) -> None:
    side, pixels = image
    row_size = side * 4
    rows = [
        b"\0" + pixels[offset : offset + row_size]
        for offset in range(0, len(pixels), row_size)
    ]
    encoded = peri_scribe.kml.icons.png_from_rows(rows, side)
    with PIL.Image.open(io.BytesIO(encoded)) as checked:
        checked.verify()
    with PIL.Image.open(io.BytesIO(encoded)) as decoded:
        assert decoded.size == (side, side)
        assert decoded.mode == "RGBA"
        assert decoded.tobytes() == pixels
