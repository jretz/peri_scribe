"""Reused rings must preserve every dynamic KML wrapper and coordinate byte."""

import pathlib

import pytest
import shapely

import kml_io.geometry
import spatial_data.product_cache
import tests.helpers.doubles.errors
import tests.helpers.factories.kml_io.geometry


@pytest.mark.parametrize(
    "geometry",
    [
        shapely.Polygon(),
        shapely.MultiPolygon(),
        shapely.Polygon(
            [(0, 0), (0, 4), (4, 4), (4, 0), (0, 0)],
            [
                [(1, 1), (2, 1), (2, 2), (1, 1)],
                [(2, 2), (3, 2), (3, 3), (2, 2)],
            ],
        ),
        shapely.MultiPolygon([
            shapely.box(2.12345678, 2, 3, 3),
            shapely.box(0, 0, 1, 1),
        ]),
    ],
)
def test_kml_writer_geometry_xml_reuses_exact_fragments_in_a_fresh_writer(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    geometry: shapely.Geometry,
) -> None:
    path = tmp_path / "products.sqlite"
    reference = tests.helpers.factories.kml_io.geometry.MemoryKmlWriter()
    expected = reference.geometry_xml(geometry, 7)
    with spatial_data.product_cache.scope(path, "policy"):
        writer = tests.helpers.factories.kml_io.geometry.MemoryKmlWriter()
        writer.geometry_xml(geometry, 0)
    monkeypatch.setattr(
        kml_io.geometry,
        "polygon_boundaries",
        tests.helpers.doubles.errors.raising_stub(AssertionError("formatted rings")),
    )

    with spatial_data.product_cache.scope(path, "policy"):
        writer = tests.helpers.factories.kml_io.geometry.MemoryKmlWriter()
        actual = writer.geometry_xml(shapely.from_wkb(geometry.wkb), 7)

    assert actual == expected
    assert writer.geometry_cache.persistent_hits == 1
    assert writer.geometry_cache.computed == 0


def test_kml_writer_geometry_xml_invalidates_changed_precision(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    geometry = shapely.box(0.12345678, 0, 1, 1)
    path = tmp_path / "products.sqlite"
    writer = tests.helpers.factories.kml_io.geometry.MemoryKmlWriter()
    with spatial_data.product_cache.scope(path, "policy"):
        original = writer.geometry_xml(geometry, 0)
        monkeypatch.setattr(kml_io.geometry, "COORDINATE_DECIMALS", 7)
        changed = writer.geometry_xml(geometry, 0)
    with spatial_data.product_cache.scope(path, "policy"):
        fresh_writer = tests.helpers.factories.kml_io.geometry.MemoryKmlWriter()
        assert fresh_writer.geometry_xml(geometry, 0) == changed

    assert "0.12346" in original
    assert "0.1234568" in changed
    expected_computed = 2
    assert writer.geometry_cache.computed == expected_computed
    assert fresh_writer.geometry_cache.persistent_hits == 1


@pytest.mark.parametrize("context", ["policy", "changed policy"])
def test_kml_writer_geometry_xml_forces_requested_recomputation(
    tmp_path: pathlib.Path,
    context: str,
) -> None:
    geometry = shapely.box(0, 0, 1, 1)
    path = tmp_path / "products.sqlite"
    with spatial_data.product_cache.scope(path, "policy"):
        writer = tests.helpers.factories.kml_io.geometry.MemoryKmlWriter()
        expected = writer.geometry_xml(geometry, 0)

    with spatial_data.product_cache.scope(
        path,
        context,
        unconditional=context == "policy",
    ):
        writer = tests.helpers.factories.kml_io.geometry.MemoryKmlWriter()
        assert writer.geometry_xml(geometry, 0) == expected
        assert writer.geometry_cache.computed == 1


def test_kml_writer_geometry_xml_standalone_has_no_persistent_state(
    tmp_path: pathlib.Path,
) -> None:
    geometry = shapely.box(0, 0, 1, 1)
    writer = tests.helpers.factories.kml_io.geometry.MemoryKmlWriter()
    expected = writer.geometry_xml(geometry, 0)

    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "policy"):
        writer = tests.helpers.factories.kml_io.geometry.MemoryKmlWriter()
        assert writer.geometry_xml(geometry, 0) == expected
        assert writer.geometry_cache.computed == 1
