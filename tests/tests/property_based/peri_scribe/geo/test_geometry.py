"""Tests for peri_scribe.geo.geometry."""

from __future__ import annotations

import hypothesis
import numpy as np
import pyproj
import shapely.geometry

import peri_scribe.geo.geometry
import tests.helpers.strategies.geometry


@hypothesis.given(case=tests.helpers.strategies.geometry.nested_collections())
def test_polygonal_parts_preserves_polygons_through_nested_collections(
    case: tuple[shapely.Geometry, list[shapely.Polygon]],
) -> None:
    geometry, expected = case
    assert peri_scribe.geo.geometry.polygonal_parts(geometry) == expected


@hypothesis.given(geometry=tests.helpers.strategies.geometry.footprints())
def test_transform_coordinates_round_trips_projection(
    geometry: shapely.Polygon | shapely.MultiPolygon,
) -> None:
    projected = peri_scribe.geo.geometry.transform_coordinates(
        geometry,
        pyproj.Transformer.from_crs(4326, 3857, always_xy=True),
    )
    restored = peri_scribe.geo.geometry.transform_coordinates(
        projected,
        pyproj.Transformer.from_crs(3857, 4326, always_xy=True),
    )
    np.testing.assert_allclose(
        shapely.get_coordinates(restored),
        shapely.get_coordinates(geometry),
        rtol=0,
        atol=1e-10,
    )
