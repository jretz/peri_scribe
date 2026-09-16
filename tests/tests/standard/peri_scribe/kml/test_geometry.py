"""Tests for peri_scribe.kml.geometry."""

from __future__ import annotations

import defusedxml.ElementTree as DefusedElementTree
import pytest
import shapely.geometry

import peri_scribe.kml.geometry
import peri_scribe.kml.styles
import tests.helpers.assertions.peri_scribe.kml.geometry
import tests.helpers.factories.geometry
import tests.helpers.peri_scribe.kml.geometry
import tests.helpers.peri_scribe.kml.parsing


def test_kml_writer_geometry_xml_keeps_distinct_temporary_polygons() -> None:
    tests.helpers.assertions.peri_scribe.kml.geometry.assert_temporary_geometry_serialization([
        shapely.box(0, 0, 1, 1),
        shapely.box(2, 2, 3, 3),
    ])


@pytest.mark.parametrize("text", ["<![CDATA[", "Fire <![CDATA["])
def test_escape_text_escapes_unclosed_cdata_marker(text: str) -> None:
    escaped = peri_scribe.kml.geometry.escape_text(text)
    element = DefusedElementTree.fromstring(f"<text>{escaped}</text>")
    assert element.text == text


def test_ring_coordinates_text_rounds_and_omits_altitude() -> None:
    ring = shapely.geometry.LinearRing([
        (-120.540340932131, 44.05275449364),
        (-120.541198250056, 44.0527635164056),
        (-120.539987133856, 44.0536779666668),
        (-120.540340932131, 44.05275449364),
    ])
    assert (
        peri_scribe.kml.geometry.ring_coordinates_text(ring)
        == "-120.54034,44.05275 -120.54120,44.05276 "
        "-120.53999,44.05368 -120.54034,44.05275"
    )


def test_polygon_geometry_includes_holes() -> None:
    polygon = shapely.geometry.Polygon(
        [(0.0, 0.0), (0.0, 2.0), (2.0, 2.0), (2.0, 0.0), (0.0, 0.0)],
        [[(0.5, 0.5), (0.5, 1.5), (1.5, 1.5), (1.5, 0.5), (0.5, 0.5)]],
    )
    writer = peri_scribe.kml.geometry.KmlWriter()
    peri_scribe.kml.geometry.polygon_geometry(
        writer,
        "Bug",
        "#perimeter-fill",
        polygon,
        0,
    )
    placemark = tests.helpers.peri_scribe.kml.parsing.placemark_named(
        tests.helpers.peri_scribe.kml.parsing.document_from_writer(writer),
        "Bug",
    )
    assert tests.helpers.peri_scribe.kml.parsing.exterior_coordinates(placemark) == [
        (0.0, 0.0),
        (0.0, 2.0),
        (2.0, 2.0),
        (2.0, 0.0),
        (0.0, 0.0),
    ]
    assert tests.helpers.peri_scribe.kml.parsing.interior_coordinates(placemark) == [
        (0.5, 0.5),
        (0.5, 1.5),
        (1.5, 1.5),
        (1.5, 0.5),
        (0.5, 0.5),
    ]
    assert tests.helpers.peri_scribe.kml.parsing.draw_order(placemark) == 0


def test_multi_polygon_geometry_holds_each_polygon() -> None:
    multi_polygon = shapely.geometry.MultiPolygon([
        shapely.geometry.box(0.0, 0.0, 1.0, 1.0),
        shapely.geometry.box(2.0, 2.0, 3.0, 3.0),
    ])
    expected_draw_order = 2
    writer = peri_scribe.kml.geometry.KmlWriter()
    peri_scribe.kml.geometry.multi_polygon_geometry(
        writer,
        "Bug",
        "#perimeter-fill",
        multi_polygon,
        expected_draw_order,
    )
    placemark = tests.helpers.peri_scribe.kml.parsing.placemark_named(
        tests.helpers.peri_scribe.kml.parsing.document_from_writer(writer),
        "Bug",
    )
    geometry = placemark.find(
        tests.helpers.peri_scribe.kml.parsing.kml_tag("MultiGeometry"),
    )
    if geometry is None:
        pytest.fail("Placemark has no MultiGeometry")
    polygons = [
        child
        for child in geometry
        if child.tag == tests.helpers.peri_scribe.kml.parsing.kml_tag("Polygon")
    ]
    assert len(polygons) == len(multi_polygon.geoms)
    assert (
        geometry.find(tests.helpers.peri_scribe.kml.parsing.gx_tag("drawOrder")) is None
    )
    assert tests.helpers.peri_scribe.kml.geometry.polygon_draw_orders(geometry) == [
        expected_draw_order,
        expected_draw_order,
    ]
    assert (
        tests.helpers.peri_scribe.kml.parsing.draw_order(placemark)
        == expected_draw_order
    )


def test_perimeter_geometry_converts_polygon() -> None:
    writer = peri_scribe.kml.geometry.KmlWriter()
    peri_scribe.kml.geometry.perimeter_geometry(
        writer,
        "Bug",
        "#perimeter-fill",
        tests.helpers.factories.geometry.square(1.0),
        0,
    )
    placemark = tests.helpers.peri_scribe.kml.parsing.placemark_named(
        tests.helpers.peri_scribe.kml.parsing.document_from_writer(writer),
        "Bug",
    )
    assert (
        placemark.find(tests.helpers.peri_scribe.kml.parsing.kml_tag("Polygon"))
        is not None
    )
    assert tests.helpers.peri_scribe.kml.parsing.draw_order(placemark) == 0


def test_perimeter_geometry_converts_multi_polygon() -> None:
    multi_polygon = shapely.geometry.MultiPolygon([
        tests.helpers.factories.geometry.square(1.0),
        tests.helpers.factories.geometry.square(2.0),
    ])
    expected_draw_order = 5
    writer = peri_scribe.kml.geometry.KmlWriter()
    peri_scribe.kml.geometry.perimeter_geometry(
        writer,
        "Bug",
        "#perimeter-fill",
        multi_polygon,
        expected_draw_order,
    )
    placemark = tests.helpers.peri_scribe.kml.parsing.placemark_named(
        tests.helpers.peri_scribe.kml.parsing.document_from_writer(writer),
        "Bug",
    )
    geometry = placemark.find(
        tests.helpers.peri_scribe.kml.parsing.kml_tag("MultiGeometry"),
    )
    if geometry is None:
        pytest.fail("Placemark has no MultiGeometry")
    assert (
        geometry.find(tests.helpers.peri_scribe.kml.parsing.gx_tag("drawOrder")) is None
    )
    assert tests.helpers.peri_scribe.kml.geometry.polygon_draw_orders(geometry) == [
        expected_draw_order,
        expected_draw_order,
    ]
    assert (
        tests.helpers.peri_scribe.kml.parsing.draw_order(placemark)
        == expected_draw_order
    )


def test_point_placemark_names_and_styles_point() -> None:
    point = shapely.geometry.Point(1.0, 2.0)
    writer = peri_scribe.kml.geometry.KmlWriter()
    expected_draw_order = peri_scribe.kml.styles.point_draw_order(3)
    peri_scribe.kml.geometry.point_placemark(
        writer,
        "Bug",
        "#point-icon",
        point,
        expected_draw_order,
    )
    placemark = tests.helpers.peri_scribe.kml.parsing.placemark_named(
        tests.helpers.peri_scribe.kml.parsing.document_from_writer(writer),
        "Bug",
    )
    assert (
        tests.helpers.peri_scribe.kml.parsing.placemark_style_url(placemark)
        == "#point-icon"
    )
    assert tests.helpers.peri_scribe.kml.parsing.point_coordinates(placemark) == (
        1.0,
        2.0,
    )
    assert (
        tests.helpers.peri_scribe.kml.parsing.draw_order(placemark)
        == expected_draw_order
    )


def test_point_placemark_coordinates_round_and_omit_altitude() -> None:
    writer = peri_scribe.kml.geometry.KmlWriter()
    peri_scribe.kml.geometry.point_placemark(
        writer,
        "Bug",
        "#point-icon",
        shapely.geometry.Point(1.23456789, -2.98765432),
        0,
    )
    placemark = tests.helpers.peri_scribe.kml.parsing.placemark_named(
        tests.helpers.peri_scribe.kml.parsing.document_from_writer(writer),
        "Bug",
    )
    coordinates = placemark.find(
        f"{tests.helpers.peri_scribe.kml.parsing.kml_tag('Point')}/"
        f"{tests.helpers.peri_scribe.kml.parsing.kml_tag('coordinates')}",
    )
    assert coordinates is not None
    assert coordinates.text == "1.23457,-2.98765"


def test_perimeter_placemark_names_and_styles_polygon() -> None:
    writer = peri_scribe.kml.geometry.KmlWriter()
    peri_scribe.kml.geometry.perimeter_placemark(
        writer,
        "Interior",
        "#perimeter-fill",
        tests.helpers.factories.geometry.square(1.0),
        0,
    )
    placemark = tests.helpers.peri_scribe.kml.parsing.placemark_named(
        tests.helpers.peri_scribe.kml.parsing.document_from_writer(writer),
        "Interior",
    )
    assert (
        tests.helpers.peri_scribe.kml.parsing.placemark_style_url(placemark)
        == "#perimeter-fill"
    )
    assert (
        placemark.find(tests.helpers.peri_scribe.kml.parsing.kml_tag("Polygon"))
        is not None
    )
    assert tests.helpers.peri_scribe.kml.parsing.draw_order(placemark) == 0


def test_polygon_geometry_sets_description() -> None:
    writer = peri_scribe.kml.geometry.KmlWriter()
    peri_scribe.kml.geometry.polygon_geometry(
        writer,
        "Bug",
        "#perimeter-fill",
        tests.helpers.factories.geometry.square(1.0),
        0,
        description="description text",
    )
    placemark = tests.helpers.peri_scribe.kml.parsing.placemark_named(
        tests.helpers.peri_scribe.kml.parsing.document_from_writer(writer),
        "Bug",
    )
    assert (
        placemark.findtext(tests.helpers.peri_scribe.kml.parsing.kml_tag("description"))
        == "description text"
    )


def test_multi_polygon_geometry_sets_description() -> None:
    writer = peri_scribe.kml.geometry.KmlWriter()
    multi_polygon = shapely.geometry.MultiPolygon([
        tests.helpers.factories.geometry.square(1.0),
        tests.helpers.factories.geometry.square(2.0),
    ])
    peri_scribe.kml.geometry.multi_polygon_geometry(
        writer,
        "Bug",
        "#perimeter-fill",
        multi_polygon,
        0,
        description="description text",
    )
    placemark = tests.helpers.peri_scribe.kml.parsing.placemark_named(
        tests.helpers.peri_scribe.kml.parsing.document_from_writer(writer),
        "Bug",
    )
    assert (
        placemark.findtext(tests.helpers.peri_scribe.kml.parsing.kml_tag("description"))
        == "description text"
    )


def test_point_placemark_sets_description() -> None:
    writer = peri_scribe.kml.geometry.KmlWriter()
    peri_scribe.kml.geometry.point_placemark(
        writer,
        "Bug",
        "#point-icon",
        shapely.geometry.Point(1.0, 1.0),
        0,
        description="description text",
    )
    placemark = tests.helpers.peri_scribe.kml.parsing.placemark_named(
        tests.helpers.peri_scribe.kml.parsing.document_from_writer(writer),
        "Bug",
    )
    assert (
        placemark.findtext(tests.helpers.peri_scribe.kml.parsing.kml_tag("description"))
        == "description text"
    )
