"""Tests for peri_scribe.report.locations."""

from __future__ import annotations

import geopandas
import pyproj
import pytest
import shapely

import peri_scribe.report.locations
import tests.helpers.factories.peri_scribe.report.locations
from peri_scribe.units import units


def test_nearest_city_ignores_empty_point_alongside_usable_city() -> None:
    cities = geopandas.GeoDataFrame(
        {"NAME": ["Usable", "Empty"], "STATE_ABBR": ["OR", "OR"]},
        geometry=[shapely.Point(0, 0), shapely.Point()],
        crs="EPSG:4326",
    )
    nearest = peri_scribe.report.locations.nearest_city(shapely.Point(0, 0), cities)
    assert nearest is not None
    assert nearest.name == "Usable"
    assert nearest.distance == 0 * units.meters


def test_compass_point_names_each_wind() -> None:
    names = peri_scribe.report.locations.COMPASS_POINT_NAMES
    step = peri_scribe.report.locations.COMPASS_POINT_SPAN

    for index, name in enumerate(names):
        assert peri_scribe.report.locations.compass_point(index * step) == name


def test_compass_point_wraps_past_north() -> None:
    assert peri_scribe.report.locations.compass_point(359.0 * units.degrees) == "N"
    assert peri_scribe.report.locations.compass_point(360.0 * units.degrees) == "N"


def test_location_text_formats_distance_and_direction() -> None:
    city = peri_scribe.report.locations.NearestCity(
        name="Portland",
        state_abbreviation="OR",
        distance=14.6 * units.miles,
        bearing=112.5 * units.degrees,
    )

    assert (
        peri_scribe.report.locations.location_text(city) == "15 mi ESE of Portland, OR"
    )


def test_location_text_rounds_distance_to_whole_miles() -> None:
    city = peri_scribe.report.locations.NearestCity(
        name="Portland",
        state_abbreviation="OR",
        distance=15.6 * units.miles,
        bearing=90.0 * units.degrees,
    )

    assert peri_scribe.report.locations.location_text(city) == "16 mi E of Portland, OR"


def test_location_text_without_bearing_names_zero_distance_city() -> None:
    city = peri_scribe.report.locations.NearestCity(
        name="Portland",
        state_abbreviation="OR",
        distance=0.0 * units.miles,
    )

    assert peri_scribe.report.locations.location_text(city) == "0 mi of Portland, OR"


def test_azimuthal_equidistant_projection_centers_on_point() -> None:
    projection = peri_scribe.report.locations.azimuthal_equidistant_projection(
        tests.helpers.factories.peri_scribe.report.locations.PORTLAND_LONGITUDE,
        tests.helpers.factories.peri_scribe.report.locations.PORTLAND_LATITUDE,
    )
    transformer = pyproj.Transformer.from_crs("EPSG:4326", projection, always_xy=True)

    x_coordinate, y_coordinate = transformer.transform(
        tests.helpers.factories.peri_scribe.report.locations.PORTLAND_LONGITUDE,
        tests.helpers.factories.peri_scribe.report.locations.PORTLAND_LATITUDE,
    )

    assert x_coordinate == pytest.approx(0.0, abs=1e-6)
    assert y_coordinate == pytest.approx(0.0, abs=1e-6)


def test_distance_and_bearing_from_point_measure_geodesically() -> None:
    interior = tests.helpers.factories.peri_scribe.report.locations.geodesic_quad(
        tests.helpers.factories.peri_scribe.report.locations.PORTLAND_LONGITUDE,
        tests.helpers.factories.peri_scribe.report.locations.PORTLAND_LATITUDE,
        112.5,
        15.0,
        length=10.0,
        width_in_miles=5.0,
    )

    distance, bearing = peri_scribe.report.locations.distance_and_bearing_from_point(
        interior,
        tests.helpers.factories.peri_scribe.report.locations.PORTLAND_LONGITUDE,
        tests.helpers.factories.peri_scribe.report.locations.PORTLAND_LATITUDE,
    )

    assert distance is not None
    assert distance.m_as("miles") == pytest.approx(15.0, rel=1e-6)
    assert bearing is not None
    assert bearing.m_as("degrees") == pytest.approx(112.5, abs=1e-6)


def test_distance_and_bearing_from_point_zero_inside_interior() -> None:
    interior = shapely.Point(
        tests.helpers.factories.peri_scribe.report.locations.PORTLAND_LONGITUDE,
        tests.helpers.factories.peri_scribe.report.locations.PORTLAND_LATITUDE,
    ).buffer(0.5)

    distance, bearing = peri_scribe.report.locations.distance_and_bearing_from_point(
        interior,
        tests.helpers.factories.peri_scribe.report.locations.PORTLAND_LONGITUDE,
        tests.helpers.factories.peri_scribe.report.locations.PORTLAND_LATITUDE,
    )

    assert distance.m_as("meters") == pytest.approx(0.0, abs=1e-9)
    assert bearing is None


def test_nearest_city_picks_closest_city() -> None:
    interior = tests.helpers.factories.peri_scribe.report.locations.geodesic_quad(
        tests.helpers.factories.peri_scribe.report.locations.PORTLAND_LONGITUDE,
        tests.helpers.factories.peri_scribe.report.locations.PORTLAND_LATITUDE,
        112.5,
        15.0,
        length=10.0,
        width_in_miles=5.0,
    )
    far_longitude, far_latitude, _ = (
        tests.helpers.factories.peri_scribe.report.locations.GEODESIC.fwd(
            tests.helpers.factories.peri_scribe.report.locations.PORTLAND_LONGITUDE,
            tests.helpers.factories.peri_scribe.report.locations.PORTLAND_LATITUDE,
            0.0,
            (80.0 * units.miles).m_as("meters"),
        )
    )
    cities = tests.helpers.factories.peri_scribe.report.locations.city_frame([
        ("Faraway", "OR", (far_longitude, far_latitude)),
        (
            "Portland",
            "OR",
            (
                tests.helpers.factories.peri_scribe.report.locations.PORTLAND_LONGITUDE,
                tests.helpers.factories.peri_scribe.report.locations.PORTLAND_LATITUDE,
            ),
        ),
    ])

    nearest = peri_scribe.report.locations.nearest_city(interior, cities)

    assert nearest is not None
    assert nearest.name == "Portland"
    assert nearest.state_abbreviation == "OR"
    assert nearest.distance is not None
    assert nearest.distance.m_as("miles") == pytest.approx(15.0, rel=1e-6)
    assert nearest.bearing is not None
    assert nearest.bearing.m_as("degrees") == pytest.approx(112.5, abs=1e-6)
    assert (
        peri_scribe.report.locations.location_text(nearest)
        == "15 mi ESE of Portland, OR"
    )


def test_nearest_city_names_city_inside_the_interior() -> None:
    interior = shapely.Point(
        tests.helpers.factories.peri_scribe.report.locations.PORTLAND_LONGITUDE,
        tests.helpers.factories.peri_scribe.report.locations.PORTLAND_LATITUDE,
    ).buffer(1.0)
    cities = tests.helpers.factories.peri_scribe.report.locations.city_frame([
        (
            "Portland",
            "OR",
            (
                tests.helpers.factories.peri_scribe.report.locations.PORTLAND_LONGITUDE,
                tests.helpers.factories.peri_scribe.report.locations.PORTLAND_LATITUDE,
            ),
        ),
        (
            "Faraway",
            "OR",
            (
                tests.helpers.factories.peri_scribe.report.locations.PORTLAND_LONGITUDE
                - 2.0,
                tests.helpers.factories.peri_scribe.report.locations.PORTLAND_LATITUDE,
            ),
        ),
    ])

    nearest = peri_scribe.report.locations.nearest_city(interior, cities)

    assert nearest is not None
    assert nearest.name == "Portland"
    assert nearest.distance.m_as("meters") == pytest.approx(0.0, abs=1e-9)
    assert nearest.bearing is None
    assert peri_scribe.report.locations.location_text(nearest) == "0 mi of Portland, OR"


def test_nearest_city_ties_go_to_first_city_alphabetically() -> None:
    interior = shapely.Point(
        tests.helpers.factories.peri_scribe.report.locations.PORTLAND_LONGITUDE,
        tests.helpers.factories.peri_scribe.report.locations.PORTLAND_LATITUDE,
    ).buffer(1.0)
    cities = tests.helpers.factories.peri_scribe.report.locations.city_frame([
        (
            "Zebra",
            "OR",
            (
                tests.helpers.factories.peri_scribe.report.locations.PORTLAND_LONGITUDE,
                tests.helpers.factories.peri_scribe.report.locations.PORTLAND_LATITUDE,
            ),
        ),
        (
            "Alpha",
            "OR",
            (
                tests.helpers.factories.peri_scribe.report.locations.PORTLAND_LONGITUDE,
                tests.helpers.factories.peri_scribe.report.locations.PORTLAND_LATITUDE,
            ),
        ),
    ])

    nearest = peri_scribe.report.locations.nearest_city(interior, cities)

    assert nearest is not None
    assert nearest.name == "Alpha"


def test_nearest_city_returns_none_for_empty_cities() -> None:
    interior = shapely.Point(
        tests.helpers.factories.peri_scribe.report.locations.PORTLAND_LONGITUDE,
        tests.helpers.factories.peri_scribe.report.locations.PORTLAND_LATITUDE,
    ).buffer(1.0)

    assert (
        peri_scribe.report.locations.nearest_city(
            interior,
            tests.helpers.factories.peri_scribe.report.locations.city_frame([]),
        )
        is None
    )


def test_nearest_city_ignores_unusable_rows() -> None:
    interior = shapely.Point(
        tests.helpers.factories.peri_scribe.report.locations.PORTLAND_LONGITUDE,
        tests.helpers.factories.peri_scribe.report.locations.PORTLAND_LATITUDE,
    ).buffer(1.0)
    cities = tests.helpers.factories.peri_scribe.report.locations.city_frame([
        (
            None,
            "OR",
            (
                tests.helpers.factories.peri_scribe.report.locations.PORTLAND_LONGITUDE,
                tests.helpers.factories.peri_scribe.report.locations.PORTLAND_LATITUDE,
            ),
        ),
        (
            "No state",
            None,
            (
                tests.helpers.factories.peri_scribe.report.locations.PORTLAND_LONGITUDE,
                tests.helpers.factories.peri_scribe.report.locations.PORTLAND_LATITUDE,
            ),
        ),
        ("No geometry", "OR", None),
    ])

    nearest = peri_scribe.report.locations.nearest_city(interior, cities)

    assert nearest is None


def test_nearest_city_ignores_non_point_rows() -> None:
    interior = shapely.Point(
        tests.helpers.factories.peri_scribe.report.locations.PORTLAND_LONGITUDE,
        tests.helpers.factories.peri_scribe.report.locations.PORTLAND_LATITUDE,
    ).buffer(1.0)
    cities = geopandas.GeoDataFrame(
        {
            "NAME": ["Portland", "Many"],
            "STATE_ABBR": ["OR", "OR"],
            "geometry": [
                shapely.Point(
                    tests.helpers.factories.peri_scribe.report.locations.PORTLAND_LONGITUDE,
                    tests.helpers.factories.peri_scribe.report.locations.PORTLAND_LATITUDE,
                ),
                shapely.MultiPoint([
                    (
                        tests.helpers.factories.peri_scribe.report.locations.PORTLAND_LONGITUDE,
                        tests.helpers.factories.peri_scribe.report.locations.PORTLAND_LATITUDE,
                    ),
                    (
                        tests.helpers.factories.peri_scribe.report.locations.PORTLAND_LONGITUDE
                        + 1.0,
                        tests.helpers.factories.peri_scribe.report.locations.PORTLAND_LATITUDE,
                    ),
                ]),
            ],
        },
        crs="EPSG:4326",
    )

    nearest = peri_scribe.report.locations.nearest_city(interior, cities)

    assert nearest is not None
    assert nearest.name == "Portland"


def test_nearest_city_keeps_usable_rows_among_unusable() -> None:
    interior = shapely.Point(
        tests.helpers.factories.peri_scribe.report.locations.PORTLAND_LONGITUDE,
        tests.helpers.factories.peri_scribe.report.locations.PORTLAND_LATITUDE,
    ).buffer(1.0)
    far_longitude, far_latitude, _ = (
        tests.helpers.factories.peri_scribe.report.locations.GEODESIC.fwd(
            tests.helpers.factories.peri_scribe.report.locations.PORTLAND_LONGITUDE,
            tests.helpers.factories.peri_scribe.report.locations.PORTLAND_LATITUDE,
            0.0,
            (80.0 * units.miles).m_as("meters"),
        )
    )
    cities = tests.helpers.factories.peri_scribe.report.locations.city_frame([
        (None, "OR", None),
        (
            "Portland",
            "OR",
            (
                tests.helpers.factories.peri_scribe.report.locations.PORTLAND_LONGITUDE,
                tests.helpers.factories.peri_scribe.report.locations.PORTLAND_LATITUDE,
            ),
        ),
        ("Faraway", "OR", (far_longitude, far_latitude)),
    ])

    nearest = peri_scribe.report.locations.nearest_city(interior, cities)

    assert nearest is not None
    assert nearest.name == "Portland"


def test_nearest_city_measures_to_the_interior_not_the_point() -> None:
    # A ring-shaped fire surrounds a hole at its center: the city at the very center
    # lies nearest to the fire's centroid but outside its interior, while a city within
    # the ring is at distance zero from the interior.
    center = shapely.Point(
        tests.helpers.factories.peri_scribe.report.locations.PORTLAND_LONGITUDE,
        tests.helpers.factories.peri_scribe.report.locations.PORTLAND_LATITUDE,
    )
    interior = center.buffer(0.5).difference(center.buffer(0.3))
    cities = tests.helpers.factories.peri_scribe.report.locations.city_frame([
        (
            "Hole",
            "OR",
            (
                tests.helpers.factories.peri_scribe.report.locations.PORTLAND_LONGITUDE,
                tests.helpers.factories.peri_scribe.report.locations.PORTLAND_LATITUDE,
            ),
        ),
        (
            "Ring",
            "OR",
            (
                tests.helpers.factories.peri_scribe.report.locations.PORTLAND_LONGITUDE
                + 0.4,
                tests.helpers.factories.peri_scribe.report.locations.PORTLAND_LATITUDE,
            ),
        ),
    ])

    nearest = peri_scribe.report.locations.nearest_city(interior, cities)

    assert nearest is not None
    assert nearest.name == "Ring"
    assert nearest.distance.m_as("meters") == pytest.approx(0.0, abs=1e-9)


def test_plausible_city_indices_orders_by_name() -> None:
    interior = shapely.Point(
        tests.helpers.factories.peri_scribe.report.locations.PORTLAND_LONGITUDE,
        tests.helpers.factories.peri_scribe.report.locations.PORTLAND_LATITUDE,
    ).buffer(0.05)
    cities = tests.helpers.factories.peri_scribe.report.locations.city_frame([
        (
            "Second",
            "OR",
            (
                tests.helpers.factories.peri_scribe.report.locations.PORTLAND_LONGITUDE
                - 0.02,
                tests.helpers.factories.peri_scribe.report.locations.PORTLAND_LATITUDE
                + 0.02,
            ),
        ),
        (
            "First",
            "OR",
            (
                tests.helpers.factories.peri_scribe.report.locations.PORTLAND_LONGITUDE
                + 0.02,
                tests.helpers.factories.peri_scribe.report.locations.PORTLAND_LATITUDE
                - 0.02,
            ),
        ),
    ])

    indices = peri_scribe.report.locations.plausible_city_indices(
        interior,
        cities.geometry.x.to_numpy(dtype=float),
        cities.geometry.y.to_numpy(dtype=float),
        [str(name) for name in cities["NAME"]],
        [str(state) for state in cities["STATE_ABBR"]],
    )

    assert indices == [1, 0]


def test_plausible_city_indices_without_boundary_vertices() -> None:
    interior = shapely.Point(
        tests.helpers.factories.peri_scribe.report.locations.PORTLAND_LONGITUDE,
        tests.helpers.factories.peri_scribe.report.locations.PORTLAND_LATITUDE,
    )
    cities = tests.helpers.factories.peri_scribe.report.locations.city_frame([
        (
            "Portland",
            "OR",
            (
                tests.helpers.factories.peri_scribe.report.locations.PORTLAND_LONGITUDE,
                tests.helpers.factories.peri_scribe.report.locations.PORTLAND_LATITUDE,
            ),
        ),
    ])

    indices = peri_scribe.report.locations.plausible_city_indices(
        interior,
        cities.geometry.x.to_numpy(dtype=float),
        cities.geometry.y.to_numpy(dtype=float),
        [str(name) for name in cities["NAME"]],
        [str(state) for state in cities["STATE_ABBR"]],
    )

    assert indices == [0]


def test_nearest_city_measures_to_a_point_location() -> None:
    point_longitude, point_latitude, _ = (
        tests.helpers.factories.peri_scribe.report.locations.GEODESIC.fwd(
            tests.helpers.factories.peri_scribe.report.locations.PORTLAND_LONGITUDE,
            tests.helpers.factories.peri_scribe.report.locations.PORTLAND_LATITUDE,
            112.5,
            (15.0 * units.miles).m_as("meters"),
        )
    )
    far_longitude, far_latitude, _ = (
        tests.helpers.factories.peri_scribe.report.locations.GEODESIC.fwd(
            tests.helpers.factories.peri_scribe.report.locations.PORTLAND_LONGITUDE,
            tests.helpers.factories.peri_scribe.report.locations.PORTLAND_LATITUDE,
            0.0,
            (80.0 * units.miles).m_as("meters"),
        )
    )
    cities = tests.helpers.factories.peri_scribe.report.locations.city_frame([
        ("Faraway", "OR", (far_longitude, far_latitude)),
        (
            "Portland",
            "OR",
            (
                tests.helpers.factories.peri_scribe.report.locations.PORTLAND_LONGITUDE,
                tests.helpers.factories.peri_scribe.report.locations.PORTLAND_LATITUDE,
            ),
        ),
    ])

    nearest = peri_scribe.report.locations.nearest_city(
        shapely.Point(point_longitude, point_latitude),
        cities,
    )

    assert nearest is not None
    assert nearest.name == "Portland"
    assert nearest.distance is not None
    assert nearest.distance.m_as("miles") == pytest.approx(15.0, rel=1e-6)
    assert nearest.bearing is not None
    assert nearest.bearing.m_as("degrees") == pytest.approx(112.5, abs=1e-6)
    assert (
        peri_scribe.report.locations.location_text(nearest)
        == "15 mi ESE of Portland, OR"
    )
