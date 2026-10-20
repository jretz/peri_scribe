"""Properties of growth normalization and independent grid-aligned set operations."""

import hypothesis
import hypothesis.strategies
import shapely

import peri_scribe.geo.growth_geometry
import tests.helpers.strategies.geometry


@hypothesis.given(geometry=tests.helpers.strategies.geometry.footprints())
def test_normalize_is_idempotent_for_valid_geographic_footprints(
    geometry: tests.helpers.strategies.geometry.Footprint,
) -> None:
    result = peri_scribe.geo.growth_geometry.normalize(geometry)

    assert result is not None
    assert result.is_valid
    assert isinstance(result, shapely.Polygon | shapely.MultiPolygon)
    assert peri_scribe.geo.growth_geometry.normalize(result) is result


@hypothesis.given(
    coordinates=hypothesis.strategies.lists(
        hypothesis.strategies.tuples(
            hypothesis.strategies.integers(-100, 100),
            hypothesis.strategies.integers(-100, 100),
            hypothesis.strategies.integers(1, 100),
            hypothesis.strategies.integers(1, 100),
        ),
        min_size=2,
        max_size=2,
    ),
)
def test_union_matches_independent_integer_grid_area(
    coordinates: list[tuple[int, int, int, int]],
) -> None:
    scale = 2**-10
    geometries = [
        shapely.box(
            -100 + left * scale,
            40 + bottom * scale,
            -100 + (left + width) * scale,
            40 + (bottom + height) * scale,
        )
        for left, bottom, width, height in coordinates
    ]
    left, bottom, width, height = coordinates[0]
    other_left, other_bottom, other_width, other_height = coordinates[1]
    overlap_width = max(
        0,
        min(left + width, other_left + other_width) - max(left, other_left),
    )
    overlap_height = max(
        0,
        min(bottom + height, other_bottom + other_height) - max(bottom, other_bottom),
    )
    expected_area = (
        width * height + other_width * other_height - overlap_width * overlap_height
    ) * scale**2

    result = peri_scribe.geo.growth_geometry.union(*geometries)

    assert result is not None
    assert result.is_valid
    assert result.area == expected_area
