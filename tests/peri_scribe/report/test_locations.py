"""Tests for peri_scribe.report.locations."""

from __future__ import annotations

import geopandas
import pyproj
import pytest
import shapely

import peri_scribe.report.locations
import peri_scribe.units


GEOD = pyproj.Geod(ellps="WGS84")

PORTLAND_LONGITUDE = -122.6750
PORTLAND_LATITUDE = 45.5051


def city_frame(
    rows: list[tuple[str | None, str | None, tuple[float, float] | None]],
) -> geopandas.GeoDataFrame:
    """Build a major-cities frame from (name, state, coordinates) rows.

    A row whose name, state, or coordinates are None holds that missing value, so
    tests can exercise the filtering of unusable rows.

    Args:
        rows: The city name, state abbreviation, and point coordinates of each row.

    Returns:
        The rows as a GeoDataFrame in WGS 84.
    """
    return geopandas.GeoDataFrame(
        {
            "NAME": [name for name, _state, _coordinates in rows],
            "STATE_ABBR": [state for _name, state, _coordinates in rows],
            "geometry": [
                None if coordinates is None else shapely.Point(coordinates)
                for _name, _state, coordinates in rows
            ],
        },
        crs="EPSG:4326",
    )


def geodesic_quad(
    longitude: float,
    latitude: float,
    bearing_in_degrees: float,
    distance_in_miles: float,
    *,
    length_in_miles: float,
    width_in_miles: float,
) -> shapely.Geometry:
    """Return a quad whose nearest corner sits at a known geodesic distance and bearing.

    The quad's first corner lies exactly *distance_in_miles* miles from the point at
    *bearing_in_degrees*, and the quad extends away along that bearing and
    perpendicular to it, so the corner is the point of the quad nearest to the given
    point.

    Args:
        longitude: The point's longitude, in degrees.
        latitude: The point's latitude, in degrees.
        bearing_in_degrees: The bearing toward the quad's nearest corner.
        distance_in_miles: The distance to the quad's nearest corner.
        length_in_miles: How far the quad extends along the bearing.
        width_in_miles: How far the quad extends to the right of the bearing.

    Returns:
        The quad polygon, in WGS 84 degrees.
    """
    corner_longitude, corner_latitude, _ = GEOD.fwd(
        longitude,
        latitude,
        bearing_in_degrees,
        distance_in_miles * peri_scribe.units.METERS_PER_MILE,
    )
    first = (corner_longitude, corner_latitude)
    second = GEOD.fwd(
        first[0],
        first[1],
        bearing_in_degrees,
        length_in_miles * peri_scribe.units.METERS_PER_MILE,
    )[:2]
    third = GEOD.fwd(
        second[0],
        second[1],
        bearing_in_degrees + 90.0,
        width_in_miles * peri_scribe.units.METERS_PER_MILE,
    )[:2]
    fourth = GEOD.fwd(
        first[0],
        first[1],
        bearing_in_degrees + 90.0,
        width_in_miles * peri_scribe.units.METERS_PER_MILE,
    )[:2]
    return shapely.Polygon([first, second, third, fourth])


def test_compass_point_names_each_wind() -> None:
    names = peri_scribe.report.locations.COMPASS_POINT_NAMES
    step = peri_scribe.report.locations.DEGREES_PER_COMPASS_POINT

    for index, name in enumerate(names):
        assert peri_scribe.report.locations.compass_point(index * step) == name


def test_compass_point_wraps_past_north() -> None:
    assert peri_scribe.report.locations.compass_point(359.0) == "N"
    assert peri_scribe.report.locations.compass_point(360.0) == "N"


def test_location_text_formats_distance_and_direction() -> None:
    city = peri_scribe.report.locations.NearestCity(
        name="Portland",
        state_abbreviation="OR",
        distance_in_miles=14.6,
        bearing_in_degrees=112.5,
    )

    assert (
        peri_scribe.report.locations.location_text(city) == "15 mi ESE of Portland, OR"
    )


def test_location_text_rounds_distance_to_whole_miles() -> None:
    city = peri_scribe.report.locations.NearestCity(
        name="Portland",
        state_abbreviation="OR",
        distance_in_miles=15.6,
        bearing_in_degrees=90.0,
    )

    assert peri_scribe.report.locations.location_text(city) == "16 mi E of Portland, OR"


def test_location_text_without_bearing_names_zero_distance_city() -> None:
    city = peri_scribe.report.locations.NearestCity(
        name="Portland",
        state_abbreviation="OR",
        distance_in_miles=0.0,
    )

    assert peri_scribe.report.locations.location_text(city) == "0 mi of Portland, OR"


def test_azimuthal_equidistant_projection_centers_on_point() -> None:
    projection = peri_scribe.report.locations.azimuthal_equidistant_projection(
        PORTLAND_LONGITUDE,
        PORTLAND_LATITUDE,
    )
    transformer = pyproj.Transformer.from_crs(
        "EPSG:4326",
        projection,
        always_xy=True,
    )

    x_coordinate, y_coordinate = transformer.transform(
        PORTLAND_LONGITUDE,
        PORTLAND_LATITUDE,
    )

    assert x_coordinate == pytest.approx(0.0, abs=1e-6)
    assert y_coordinate == pytest.approx(0.0, abs=1e-6)


def test_distance_and_bearing_from_point_measure_geodesically() -> None:
    interior = geodesic_quad(
        PORTLAND_LONGITUDE,
        PORTLAND_LATITUDE,
        112.5,
        15.0,
        length_in_miles=10.0,
        width_in_miles=5.0,
    )

    distance_in_miles, bearing_in_degrees = (
        peri_scribe.report.locations.distance_and_bearing_from_point(
            interior,
            PORTLAND_LONGITUDE,
            PORTLAND_LATITUDE,
        )
    )

    assert distance_in_miles == pytest.approx(15.0, rel=1e-6)
    assert bearing_in_degrees == pytest.approx(112.5, abs=1e-6)


def test_distance_and_bearing_from_point_zero_inside_interior() -> None:
    interior = shapely.Point(PORTLAND_LONGITUDE, PORTLAND_LATITUDE).buffer(0.5)

    distance_in_miles, bearing_in_degrees = (
        peri_scribe.report.locations.distance_and_bearing_from_point(
            interior,
            PORTLAND_LONGITUDE,
            PORTLAND_LATITUDE,
        )
    )

    assert distance_in_miles == pytest.approx(0.0, abs=1e-9)
    assert bearing_in_degrees is None


def test_nearest_city_picks_closest_city() -> None:
    interior = geodesic_quad(
        PORTLAND_LONGITUDE,
        PORTLAND_LATITUDE,
        112.5,
        15.0,
        length_in_miles=10.0,
        width_in_miles=5.0,
    )
    far_longitude, far_latitude, _ = GEOD.fwd(
        PORTLAND_LONGITUDE,
        PORTLAND_LATITUDE,
        0.0,
        80.0 * peri_scribe.units.METERS_PER_MILE,
    )
    cities = city_frame(
        [
            ("Faraway", "OR", (far_longitude, far_latitude)),
            ("Portland", "OR", (PORTLAND_LONGITUDE, PORTLAND_LATITUDE)),
        ],
    )

    nearest = peri_scribe.report.locations.nearest_city(interior, cities)

    assert nearest is not None
    assert nearest.name == "Portland"
    assert nearest.state_abbreviation == "OR"
    assert nearest.distance_in_miles == pytest.approx(15.0, rel=1e-6)
    assert nearest.bearing_in_degrees == pytest.approx(112.5, abs=1e-6)
    assert (
        peri_scribe.report.locations.location_text(nearest)
        == "15 mi ESE of Portland, OR"
    )


def test_nearest_city_names_city_inside_the_interior() -> None:
    interior = shapely.Point(PORTLAND_LONGITUDE, PORTLAND_LATITUDE).buffer(1.0)
    cities = city_frame(
        [
            ("Portland", "OR", (PORTLAND_LONGITUDE, PORTLAND_LATITUDE)),
            ("Faraway", "OR", (PORTLAND_LONGITUDE - 2.0, PORTLAND_LATITUDE)),
        ],
    )

    nearest = peri_scribe.report.locations.nearest_city(interior, cities)

    assert nearest is not None
    assert nearest.name == "Portland"
    assert nearest.distance_in_miles == pytest.approx(0.0, abs=1e-9)
    assert nearest.bearing_in_degrees is None
    assert peri_scribe.report.locations.location_text(nearest) == "0 mi of Portland, OR"


def test_nearest_city_ties_go_to_first_city_alphabetically() -> None:
    interior = shapely.Point(PORTLAND_LONGITUDE, PORTLAND_LATITUDE).buffer(1.0)
    cities = city_frame(
        [
            ("Zebra", "OR", (PORTLAND_LONGITUDE, PORTLAND_LATITUDE)),
            ("Alpha", "OR", (PORTLAND_LONGITUDE, PORTLAND_LATITUDE)),
        ],
    )

    nearest = peri_scribe.report.locations.nearest_city(interior, cities)

    assert nearest is not None
    assert nearest.name == "Alpha"


def test_nearest_city_returns_none_for_empty_cities() -> None:
    interior = shapely.Point(PORTLAND_LONGITUDE, PORTLAND_LATITUDE).buffer(1.0)

    assert (
        peri_scribe.report.locations.nearest_city(
            interior,
            city_frame([]),
        )
        is None
    )


def test_nearest_city_ignores_unusable_rows() -> None:
    interior = shapely.Point(PORTLAND_LONGITUDE, PORTLAND_LATITUDE).buffer(1.0)
    cities = city_frame(
        [
            (None, "OR", (PORTLAND_LONGITUDE, PORTLAND_LATITUDE)),
            ("No state", None, (PORTLAND_LONGITUDE, PORTLAND_LATITUDE)),
            ("No geometry", "OR", None),
        ],
    )

    nearest = peri_scribe.report.locations.nearest_city(interior, cities)

    assert nearest is None


def test_nearest_city_ignores_non_point_rows() -> None:
    interior = shapely.Point(PORTLAND_LONGITUDE, PORTLAND_LATITUDE).buffer(1.0)
    cities = geopandas.GeoDataFrame(
        {
            "NAME": ["Portland", "Many"],
            "STATE_ABBR": ["OR", "OR"],
            "geometry": [
                shapely.Point(PORTLAND_LONGITUDE, PORTLAND_LATITUDE),
                shapely.MultiPoint(
                    [
                        (PORTLAND_LONGITUDE, PORTLAND_LATITUDE),
                        (PORTLAND_LONGITUDE + 1.0, PORTLAND_LATITUDE),
                    ],
                ),
            ],
        },
        crs="EPSG:4326",
    )

    nearest = peri_scribe.report.locations.nearest_city(interior, cities)

    assert nearest is not None
    assert nearest.name == "Portland"


def test_nearest_city_keeps_usable_rows_among_unusable() -> None:
    interior = shapely.Point(PORTLAND_LONGITUDE, PORTLAND_LATITUDE).buffer(1.0)
    far_longitude, far_latitude, _ = GEOD.fwd(
        PORTLAND_LONGITUDE,
        PORTLAND_LATITUDE,
        0.0,
        80.0 * peri_scribe.units.METERS_PER_MILE,
    )
    cities = city_frame(
        [
            (None, "OR", None),
            ("Portland", "OR", (PORTLAND_LONGITUDE, PORTLAND_LATITUDE)),
            ("Faraway", "OR", (far_longitude, far_latitude)),
        ],
    )

    nearest = peri_scribe.report.locations.nearest_city(interior, cities)

    assert nearest is not None
    assert nearest.name == "Portland"


def test_nearest_city_measures_to_the_interior_not_the_point() -> None:
    # A ring-shaped fire surrounds a hole at its center: the city at the very center
    # lies nearest to the fire's centroid but outside its interior, while a city within
    # the ring is at distance zero from the interior.
    center = shapely.Point(PORTLAND_LONGITUDE, PORTLAND_LATITUDE)
    interior = center.buffer(0.5).difference(center.buffer(0.3))
    cities = city_frame(
        [
            ("Hole", "OR", (PORTLAND_LONGITUDE, PORTLAND_LATITUDE)),
            (
                "Ring",
                "OR",
                (PORTLAND_LONGITUDE + 0.4, PORTLAND_LATITUDE),
            ),
        ],
    )

    nearest = peri_scribe.report.locations.nearest_city(interior, cities)

    assert nearest is not None
    assert nearest.name == "Ring"
    assert nearest.distance_in_miles == pytest.approx(0.0, abs=1e-9)


def test_plausible_city_indices_orders_by_name() -> None:
    interior = shapely.Point(PORTLAND_LONGITUDE, PORTLAND_LATITUDE).buffer(0.05)
    cities = city_frame(
        [
            (
                "Second",
                "OR",
                (PORTLAND_LONGITUDE - 0.02, PORTLAND_LATITUDE + 0.02),
            ),
            (
                "First",
                "OR",
                (PORTLAND_LONGITUDE + 0.02, PORTLAND_LATITUDE - 0.02),
            ),
        ],
    )

    indices = peri_scribe.report.locations.plausible_city_indices(
        interior,
        cities.geometry.x.to_numpy(dtype=float),
        cities.geometry.y.to_numpy(dtype=float),
        [str(name) for name in cities["NAME"]],
        [str(state) for state in cities["STATE_ABBR"]],
    )

    assert indices == [1, 0]


def test_plausible_city_indices_without_boundary_vertices() -> None:
    interior = shapely.Point(PORTLAND_LONGITUDE, PORTLAND_LATITUDE)
    cities = city_frame(
        [("Portland", "OR", (PORTLAND_LONGITUDE, PORTLAND_LATITUDE))],
    )

    indices = peri_scribe.report.locations.plausible_city_indices(
        interior,
        cities.geometry.x.to_numpy(dtype=float),
        cities.geometry.y.to_numpy(dtype=float),
        [str(name) for name in cities["NAME"]],
        [str(state) for state in cities["STATE_ABBR"]],
    )

    assert indices == [0]


def test_nearest_city_measures_to_a_point_location() -> None:
    point_longitude, point_latitude, _ = GEOD.fwd(
        PORTLAND_LONGITUDE,
        PORTLAND_LATITUDE,
        112.5,
        15.0 * peri_scribe.units.METERS_PER_MILE,
    )
    far_longitude, far_latitude, _ = GEOD.fwd(
        PORTLAND_LONGITUDE,
        PORTLAND_LATITUDE,
        0.0,
        80.0 * peri_scribe.units.METERS_PER_MILE,
    )
    cities = city_frame(
        [
            ("Faraway", "OR", (far_longitude, far_latitude)),
            ("Portland", "OR", (PORTLAND_LONGITUDE, PORTLAND_LATITUDE)),
        ],
    )

    nearest = peri_scribe.report.locations.nearest_city(
        shapely.Point(point_longitude, point_latitude),
        cities,
    )

    assert nearest is not None
    assert nearest.name == "Portland"
    assert nearest.distance_in_miles == pytest.approx(15.0, rel=1e-6)
    assert nearest.bearing_in_degrees == pytest.approx(112.5, abs=1e-6)
    assert (
        peri_scribe.report.locations.location_text(nearest)
        == "15 mi ESE of Portland, OR"
    )
