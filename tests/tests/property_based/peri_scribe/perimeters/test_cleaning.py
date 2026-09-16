"""Tests for peri_scribe.perimeters.cleaning."""

import hypothesis

import peri_scribe.perimeters.cleaning
import tests.helpers.strategies.geometry


@hypothesis.given(geometry=tests.helpers.strategies.geometry.footprints())
def test_clean_perimeter_preserves_valid_nonempty_footprints(
    geometry: tests.helpers.strategies.geometry.Footprint,
) -> None:
    cleaned = peri_scribe.perimeters.cleaning.clean_perimeter(geometry)
    assert cleaned is not None
    assert cleaned.is_valid
    assert not cleaned.is_empty
    assert cleaned.area > 0


@hypothesis.given(geometry=tests.helpers.strategies.geometry.footprints())
def test_clean_perimeter_is_idempotent_for_generated_footprints(
    geometry: tests.helpers.strategies.geometry.Footprint,
) -> None:
    cleaned = peri_scribe.perimeters.cleaning.clean_perimeter(geometry)
    repeated = peri_scribe.perimeters.cleaning.clean_perimeter(cleaned)
    assert cleaned is not None
    assert repeated is not None
    assert repeated.equals(cleaned)
