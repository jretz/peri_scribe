"""Tests for kml_io.geometry."""

from __future__ import annotations

import defusedxml.ElementTree as DefusedElementTree
import hypothesis
import hypothesis.strategies
import numpy as np
import shapely.geometry

import kml_io.geometry
import tests.helpers.assertions.kml_io.geometry
import tests.helpers.factories.kml_io.geometry
import tests.helpers.kml_io.geometry
import tests.helpers.peri_scribe.kml.parsing
import tests.helpers.strategies.geometry
import tests.helpers.strategies.kml_io.geometry


@hypothesis.given(
    geometry=tests.helpers.strategies.geometry.footprints(),
    draw_order=hypothesis.strategies.integers(0, 1000),
)
def test_perimeter_geometry_preserves_parts_holes_and_rounded_coordinates(
    geometry: shapely.Polygon | shapely.MultiPolygon,
    draw_order: int,
) -> None:
    writer = tests.helpers.factories.kml_io.geometry.MemoryKmlWriter()
    kml_io.geometry.perimeter_geometry(
        writer,
        "River",
        "#perimeter",
        geometry,
        draw_order,
    )
    document = tests.helpers.peri_scribe.kml.parsing.document_from_writer(writer)
    polygons = list(
        document.iter(tests.helpers.peri_scribe.kml.parsing.kml_tag("Polygon")),
    )
    expected = (
        [geometry] if isinstance(geometry, shapely.Polygon) else list(geometry.geoms)
    )
    assert len(polygons) == len(expected)
    for actual, original in zip(polygons, expected, strict=True):
        rings = tests.helpers.kml_io.geometry.coordinate_rings(actual)
        original_rings = [original.exterior, *original.interiors]
        assert len(rings) == len(original_rings)
        for coordinates, ring in zip(rings, original_rings, strict=True):
            np.testing.assert_allclose(
                coordinates,
                list(ring.coords),
                rtol=0,
                atol=0.5 * 10**-kml_io.geometry.COORDINATE_DECIMALS + 1e-12,
            )
        assert actual.findtext(
            tests.helpers.peri_scribe.kml.parsing.gx_tag("drawOrder"),
        ) == str(draw_order)


@hypothesis.given(
    geometries=hypothesis.strategies.lists(
        tests.helpers.strategies.geometry.footprints(),
        min_size=1,
        max_size=5,
    ),
)
def test_kml_writer_geometry_xml_matches_fresh_serialization_for_temporary_geometry(
    geometries: list[shapely.Polygon | shapely.MultiPolygon],
) -> None:
    tests.helpers.assertions.kml_io.geometry.assert_temporary_geometry_serialization(
        geometries,
    )


@hypothesis.given(
    before=tests.helpers.strategies.kml_io.geometry.xml_text(),
    content=tests.helpers.strategies.kml_io.geometry.xml_text(),
    after=tests.helpers.strategies.kml_io.geometry.xml_text(),
)
def test_escape_text_round_trips_plain_text_and_cdata(
    before: str,
    content: str,
    after: str,
) -> None:
    escaped = kml_io.geometry.escape_text(
        f"{before}<![CDATA[{content}]]>{after}",
    )
    element = DefusedElementTree.fromstring(f"<text>{escaped}</text>")
    assert (element.text or "") == before + content + after


@hypothesis.given(
    before=tests.helpers.strategies.kml_io.geometry.xml_text(),
    content=tests.helpers.strategies.kml_io.geometry.xml_text(),
)
def test_escape_text_preserves_unterminated_cdata_as_literal_text(
    before: str,
    content: str,
) -> None:
    text = f"{before}<![CDATA[{content}"
    escaped = kml_io.geometry.escape_text(text)
    element = DefusedElementTree.fromstring(f"<text>{escaped}</text>")
    assert element.text == text
