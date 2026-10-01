"""Check bounded RGBA palettes, mandatory colors, and opacity classes."""

import numpy as np
import PIL.Image
import pytest

import peri_scribe.presentation.preview_palette


@pytest.mark.parametrize("opacity", [0, 127, 255])
def test_quantize_preserves_small_palettes_and_always_reserves_required_colors(
    opacity: int,
) -> None:
    image = PIL.Image.new("RGBA", (128, 72), (30, 70, 110, opacity))
    result = peri_scribe.presentation.preview_palette.quantize(image)
    assert np.array_equal(
        result.palette[:5],
        peri_scribe.presentation.preview_palette.RESERVED,
    )
    expected = (0, 0, 0, 0) if opacity == 0 else (30, 70, 110, opacity)
    assert result.image.getpixel((0, 0)) == expected


def test_quantize_preserves_reserved_pixels_solid_fills_and_partial_transparency() -> (
    None
):
    random = np.random.default_rng(1)
    pixels = random.integers(0, 256, size=(72, 128, 4), dtype=np.uint8)
    pixels[:24, :, 3] = 255
    pixels[24:48, :, 3] = 0
    pixels[48:, :, 3] = np.clip(pixels[48:, :, 3], 1, 254)
    reserved = peri_scribe.presentation.preview_palette.RESERVED
    pixels[0, :5] = reserved
    result = peri_scribe.presentation.preview_palette.quantize(
        PIL.Image.fromarray(pixels),
    )
    actual = np.asarray(result.image)
    assert len(result.palette) <= peri_scribe.presentation.preview_palette.COLOR_LIMIT
    assert (
        len(np.unique(actual.reshape(-1, 4), axis=0))
        <= peri_scribe.presentation.preview_palette.COLOR_LIMIT
    )
    assert np.array_equal(actual[0, :5], reserved)
    assert np.all(actual[pixels[:, :, 3] == 0, 3] == 0)
    assert np.all(
        actual[pixels[:, :, 3] == peri_scribe.presentation.preview_palette.OPAQUE, 3]
        == peri_scribe.presentation.preview_palette.OPAQUE,
    )
    partial = (pixels[:, :, 3] > 0) & (
        pixels[:, :, 3] < peri_scribe.presentation.preview_palette.OPAQUE
    )
    assert np.all(
        (actual[partial, 3] > 0)
        & (actual[partial, 3] < peri_scribe.presentation.preview_palette.OPAQUE),
    )
    repeated = peri_scribe.presentation.preview_palette.quantize(
        PIL.Image.fromarray(pixels),
    )
    assert repeated.image.tobytes() == result.image.tobytes()


def test_quantize_handles_images_using_only_the_reserved_opaque_colors() -> None:
    colors = peri_scribe.presentation.preview_palette.RESERVED[1:].reshape((1, 4, 4))
    result = peri_scribe.presentation.preview_palette.quantize(
        PIL.Image.fromarray(colors),
    )
    assert result.image.tobytes() == colors.tobytes()
    assert np.array_equal(
        result.palette,
        peri_scribe.presentation.preview_palette.RESERVED,
    )


def test_refine_colors_preserves_frozen_colors_with_unused_dynamic_centers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(peri_scribe.presentation.preview_palette, "ITERATION_LIMIT", 1)
    red = np.array(((255, 0, 0, 255),), dtype=np.uint8)
    blue = np.array(((0, 0, 255, 255),), dtype=np.uint8)
    colors, labels = peri_scribe.presentation.preview_palette.refine_colors(
        peri_scribe.presentation.preview_palette.features(red),
        np.array((1.0,)),
        peri_scribe.presentation.preview_palette.features(blue),
        opaque=True,
    )
    assert np.array_equal(colors[labels], red)
    assert np.array_equal(colors[-1:], blue)
