"""Tests for peri_scribe.kml_geometry."""

from __future__ import annotations

import xml.etree.ElementTree as ET  # ruff: ignore[suspicious-xml-etree-import]

import pytest
import shapely.geometry

import peri_scribe.kml_geometry
import peri_scribe.kml_template
import tests.kml_helpers


def test_ring_coordinates_converts_coordinates() -> None:
    ring = shapely.geometry.LinearRing(
        [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 0.0)],
    )
    assert peri_scribe.kml_geometry.ring_coordinates(ring) == [
        (0.0, 0.0),
        (1.0, 0.0),
        (1.0, 1.0),
        (0.0, 0.0),
    ]


def test_polygon_geometry_includes_holes() -> None:
    polygon = shapely.geometry.Polygon(
        [(0.0, 0.0), (0.0, 2.0), (2.0, 2.0), (2.0, 0.0), (0.0, 0.0)],
        [[(0.5, 0.5), (0.5, 1.5), (1.5, 1.5), (1.5, 0.5), (0.5, 0.5)]],
    )
    writer = peri_scribe.kml_geometry.KmlWriter()
    peri_scribe.kml_geometry.polygon_geometry(
        writer,
        "Bug",
        "#perimeter-fill",
        polygon,
        0,
        description=None,
    )
    placemark = tests.kml_helpers.placemark_named(
        tests.kml_helpers.document_from_writer(writer),
        "Bug",
    )
    assert tests.kml_helpers.exterior_coordinates(placemark) == [
        (0.0, 0.0),
        (0.0, 2.0),
        (2.0, 2.0),
        (2.0, 0.0),
        (0.0, 0.0),
    ]
    assert tests.kml_helpers.interior_coordinates(placemark) == [
        (0.5, 0.5),
        (0.5, 1.5),
        (1.5, 1.5),
        (1.5, 0.5),
        (0.5, 0.5),
    ]
    assert tests.kml_helpers.draw_order(placemark) == 0


def polygon_draw_orders(multi_geometry: ET.Element) -> list[int]:
    """Return the gx:drawOrder of each polygon in *multi_geometry*.

    Args:
        multi_geometry: The MultiGeometry element to inspect.

    Returns:
        The polygons' draw orders, in order.
    """
    orders: list[int] = []
    for polygon in multi_geometry:
        if polygon.tag != tests.kml_helpers.kml_tag("Polygon"):
            continue
        text = polygon.findtext(tests.kml_helpers.gx_tag("drawOrder"))
        if text is None:
            pytest.fail("MultiGeometry polygon has no gx:drawOrder")
        orders.append(int(text))
    return orders


def test_multi_polygon_geometry_holds_each_polygon() -> None:
    multi_polygon = shapely.geometry.MultiPolygon([
        shapely.geometry.box(0.0, 0.0, 1.0, 1.0),
        shapely.geometry.box(2.0, 2.0, 3.0, 3.0),
    ])
    expected_draw_order = 2
    writer = peri_scribe.kml_geometry.KmlWriter()
    peri_scribe.kml_geometry.multi_polygon_geometry(
        writer,
        "Bug",
        "#perimeter-fill",
        multi_polygon,
        expected_draw_order,
        description=None,
    )
    placemark = tests.kml_helpers.placemark_named(
        tests.kml_helpers.document_from_writer(writer),
        "Bug",
    )
    geometry = placemark.find(tests.kml_helpers.kml_tag("MultiGeometry"))
    if geometry is None:
        pytest.fail("Placemark has no MultiGeometry")
    polygons = [
        child for child in geometry if child.tag == tests.kml_helpers.kml_tag("Polygon")
    ]
    assert len(polygons) == len(multi_polygon.geoms)
    assert geometry.find(tests.kml_helpers.gx_tag("drawOrder")) is None
    assert polygon_draw_orders(geometry) == [
        expected_draw_order,
        expected_draw_order,
    ]
    assert tests.kml_helpers.draw_order(placemark) == expected_draw_order


def test_perimeter_geometry_converts_polygon() -> None:
    writer = peri_scribe.kml_geometry.KmlWriter()
    peri_scribe.kml_geometry.perimeter_geometry(
        writer,
        "Bug",
        "#perimeter-fill",
        tests.kml_helpers.square(1.0),
        0,
        description=None,
    )
    placemark = tests.kml_helpers.placemark_named(
        tests.kml_helpers.document_from_writer(writer),
        "Bug",
    )
    assert placemark.find(tests.kml_helpers.kml_tag("Polygon")) is not None
    assert tests.kml_helpers.draw_order(placemark) == 0


def test_perimeter_geometry_converts_multi_polygon() -> None:
    multi_polygon = shapely.geometry.MultiPolygon([
        tests.kml_helpers.square(1.0),
        tests.kml_helpers.square(2.0),
    ])
    expected_draw_order = 5
    writer = peri_scribe.kml_geometry.KmlWriter()
    peri_scribe.kml_geometry.perimeter_geometry(
        writer,
        "Bug",
        "#perimeter-fill",
        multi_polygon,
        expected_draw_order,
        description=None,
    )
    placemark = tests.kml_helpers.placemark_named(
        tests.kml_helpers.document_from_writer(writer),
        "Bug",
    )
    geometry = placemark.find(tests.kml_helpers.kml_tag("MultiGeometry"))
    if geometry is None:
        pytest.fail("Placemark has no MultiGeometry")
    assert geometry.find(tests.kml_helpers.gx_tag("drawOrder")) is None
    assert polygon_draw_orders(geometry) == [
        expected_draw_order,
        expected_draw_order,
    ]
    assert tests.kml_helpers.draw_order(placemark) == expected_draw_order


def test_point_placemark_names_and_styles_point() -> None:
    point = shapely.geometry.Point(1.0, 2.0)
    writer = peri_scribe.kml_geometry.KmlWriter()
    expected_draw_order = peri_scribe.kml_template.point_draw_order(3)
    peri_scribe.kml_geometry.point_placemark(
        writer,
        "Bug",
        "#point-icon",
        point,
        expected_draw_order,
        description=None,
    )
    placemark = tests.kml_helpers.placemark_named(
        tests.kml_helpers.document_from_writer(writer),
        "Bug",
    )
    assert tests.kml_helpers.placemark_style_url(placemark) == "#point-icon"
    assert tests.kml_helpers.point_coordinates(placemark) == (1.0, 2.0)
    assert tests.kml_helpers.draw_order(placemark) == expected_draw_order


def test_perimeter_placemark_names_and_styles_polygon() -> None:
    writer = peri_scribe.kml_geometry.KmlWriter()
    peri_scribe.kml_geometry.perimeter_placemark(
        writer,
        "Interior",
        "#perimeter-fill",
        tests.kml_helpers.square(1.0),
        0,
        description=None,
    )
    placemark = tests.kml_helpers.placemark_named(
        tests.kml_helpers.document_from_writer(writer),
        "Interior",
    )
    assert tests.kml_helpers.placemark_style_url(placemark) == "#perimeter-fill"
    assert placemark.find(tests.kml_helpers.kml_tag("Polygon")) is not None
    assert tests.kml_helpers.draw_order(placemark) == 0


def test_polygon_geometry_sets_description() -> None:
    writer = peri_scribe.kml_geometry.KmlWriter()
    peri_scribe.kml_geometry.polygon_geometry(
        writer,
        "Bug",
        "#perimeter-fill",
        tests.kml_helpers.square(1.0),
        0,
        description="description text",
    )
    placemark = tests.kml_helpers.placemark_named(
        tests.kml_helpers.document_from_writer(writer),
        "Bug",
    )
    assert (
        placemark.findtext(tests.kml_helpers.kml_tag("description"))
        == "description text"
    )


def test_multi_polygon_geometry_sets_description() -> None:
    writer = peri_scribe.kml_geometry.KmlWriter()
    multi_polygon = shapely.geometry.MultiPolygon([
        tests.kml_helpers.square(1.0),
        tests.kml_helpers.square(2.0),
    ])
    peri_scribe.kml_geometry.multi_polygon_geometry(
        writer,
        "Bug",
        "#perimeter-fill",
        multi_polygon,
        0,
        description="description text",
    )
    placemark = tests.kml_helpers.placemark_named(
        tests.kml_helpers.document_from_writer(writer),
        "Bug",
    )
    assert (
        placemark.findtext(tests.kml_helpers.kml_tag("description"))
        == "description text"
    )


def test_point_placemark_sets_description() -> None:
    writer = peri_scribe.kml_geometry.KmlWriter()
    peri_scribe.kml_geometry.point_placemark(
        writer,
        "Bug",
        "#point-icon",
        shapely.geometry.Point(1.0, 1.0),
        0,
        description="description text",
    )
    placemark = tests.kml_helpers.placemark_named(
        tests.kml_helpers.document_from_writer(writer),
        "Bug",
    )
    assert (
        placemark.findtext(tests.kml_helpers.kml_tag("description"))
        == "description text"
    )
