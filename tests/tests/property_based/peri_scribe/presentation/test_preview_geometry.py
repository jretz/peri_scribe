"""Check exact dart alpha and rendered support across generated finite angles."""

import math

import hypothesis
import hypothesis.strategies
import numpy as np
import PIL.Image
import pytest

import peri_scribe.presentation.preview_geometry
import tests.helpers.reference.peri_scribe.presentation.preview_geometry


@hypothesis.settings(max_examples=32)
@hypothesis.given(
    angle=hypothesis.strategies.floats(min_value=-math.pi, max_value=math.pi),
)
def test_supersampled_dart_preserves_binary_and_resampled_colored_alpha(
    angle: float,
) -> None:
    geometry = peri_scribe.presentation.preview_geometry
    high = geometry.supersampled_dart(angle, alpha_only=True)
    assert np.all(np.isin(np.asarray(high), (0, 255)))
    padded = high.resize(
        (geometry.DART_SIZE, geometry.DART_SIZE),
        PIL.Image.Resampling.LANCZOS,
    )
    actual = padded.crop(padded.getbbox())
    expected = geometry.north_dart(angle).getchannel("A")
    assert actual.size == expected.size
    assert actual.tobytes() == expected.tobytes()


@hypothesis.settings(max_examples=32)
@hypothesis.given(
    angle=hypothesis.strategies.floats(min_value=-math.pi, max_value=math.pi),
)
def test_north_dart_hull_matches_independent_rendered_pixel_support(
    angle: float,
) -> None:
    reference = tests.helpers.reference.peri_scribe.presentation.preview_geometry
    actual = peri_scribe.presentation.preview_geometry.north_dart_hull(angle)
    expected = reference.rendered_dart_hull(angle)
    assert actual.symmetric_difference(expected).area == pytest.approx(0, abs=1e-9)
