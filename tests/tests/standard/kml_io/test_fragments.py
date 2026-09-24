"""Persistent boundary text must preserve XML and bound retained inputs."""

import pathlib
import weakref

import pytest
import shapely

import kml_io.fragments
import kml_io.geometry
import spatial_data.cache_values
import spatial_data.product_cache
import tests.helpers.doubles.errors
import tests.helpers.doubles.kml_io.fragments


@pytest.mark.parametrize(
    "other",
    [
        shapely.box(0, 0, 2, 1),
        shapely.reverse(shapely.box(0, 0, 1, 1)),
        shapely.set_srid(shapely.box(0, 0, 1, 1), 4326),
        shapely.MultiPolygon([shapely.box(0, 0, 1, 1)]),
    ],
)
def test_geometry_key_distinguishes_exact_geometry(other: shapely.Geometry) -> None:
    assert kml_io.fragments.geometry_key(shapely.box(0, 0, 1, 1), 5) != (
        kml_io.fragments.geometry_key(other, 5)
    )


def test_geometry_key_distinguishes_coordinate_precision() -> None:
    geometry = shapely.box(0, 0, 1, 1)
    assert kml_io.fragments.geometry_key(geometry, 5) != (
        kml_io.fragments.geometry_key(geometry, 6)
    )


def test_geometry_key_distinguishes_polygon_member_order() -> None:
    first, second = shapely.box(0, 0, 1, 1), shapely.box(2, 2, 3, 3)
    assert kml_io.fragments.geometry_key(shapely.MultiPolygon([first, second]), 5) != (
        kml_io.fragments.geometry_key(shapely.MultiPolygon([second, first]), 5)
    )


def test_boundary_cache_boundaries_reuses_equal_objects_without_store() -> None:
    renderer = tests.helpers.doubles.kml_io.fragments.BoundaryRenderer()
    cache = kml_io.fragments.BoundaryCache()
    expected = cache.boundaries(shapely.box(0, 0, 1, 1), 5, renderer)
    actual = cache.boundaries(shapely.box(0, 0, 1, 1), 5, renderer)

    assert actual == expected
    assert len(renderer.calls) == 1
    assert cache.memory_hits == 1


def test_boundary_cache_boundaries_releases_source_geometry() -> None:
    cache = kml_io.fragments.BoundaryCache()
    geometry = shapely.box(0, 0, 1, 1)
    reference = weakref.ref(geometry)
    cache.boundaries(geometry, 5, kml_io.geometry.geometry_boundaries)
    del geometry

    assert reference() is None
    assert cache.retained_bytes > 0


def test_boundary_cache_boundaries_evicts_least_recently_used_fragments() -> None:
    geometries = [shapely.box(i, i, i + 1, i + 1) for i in (0, 2, 4)]
    renderer = tests.helpers.doubles.kml_io.fragments.BoundaryRenderer()
    probe = kml_io.fragments.BoundaryCache()
    probe.boundaries(geometries[0], 5, renderer)
    cache = kml_io.fragments.BoundaryCache(budget=2 * probe.retained_bytes)
    renderer.calls.clear()

    for index in (0, 1, 0, 2, 0, 1):
        cache.boundaries(geometries[index], 5, renderer)

    assert renderer.calls == [geometries[index].wkb for index in (0, 1, 2, 1)]
    expected_entries = 2
    assert len(cache.entries) == expected_entries
    assert cache.retained_bytes == cache.peak_bytes == cache.budget


def test_boundary_cache_boundaries_never_retains_oversized_fragments() -> None:
    renderer = tests.helpers.doubles.kml_io.fragments.BoundaryRenderer()
    cache = kml_io.fragments.BoundaryCache(budget=1)
    geometry = shapely.box(0, 0, 1, 1)

    assert cache.boundaries(geometry, 5, renderer) == cache.boundaries(
        geometry,
        5,
        renderer,
    )
    expected_calls = 2
    assert len(renderer.calls) == expected_calls
    assert cache.retained_bytes == cache.peak_bytes == 0
    assert cache.largest_fragment_bytes > cache.budget
    assert not cache.entries


def test_boundary_cache_boundaries_reads_oversized_fragments_from_storage(
    tmp_path: pathlib.Path,
) -> None:
    renderer = tests.helpers.doubles.kml_io.fragments.BoundaryRenderer()
    cache = kml_io.fragments.BoundaryCache(budget=1)
    geometry = shapely.box(0, 0, 1, 1)

    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "policy"):
        expected = cache.boundaries(geometry, 5, renderer)
        assert cache.boundaries(geometry, 5, renderer) == expected

    assert len(renderer.calls) == 1
    assert cache.persistent_hits == 1
    assert not cache.entries


@pytest.mark.parametrize(
    "payload",
    [
        b"invalid json",
        spatial_data.cache_values.dumps([]),
        spatial_data.cache_values.dumps(()),
        spatial_data.cache_values.dumps((None,)),
        spatial_data.cache_values.dumps(("<broken>",)),
        spatial_data.cache_values.dumps((
            (
                "<outerBoundaryIs><LinearRing><coordinates><script/>"
                "</coordinates></LinearRing></outerBoundaryIs>"
            ),
        )),
        spatial_data.cache_values.dumps((
            (
                "<outerBoundaryIs><LinearRing><coordinates>0.0,0.0"
                "</coordinates></LinearRing></innerBoundaryIs>"
            ),
        )),
    ],
)
def test_boundary_cache_boundaries_replaces_malformed_fragments(
    tmp_path: pathlib.Path,
    payload: bytes,
) -> None:
    geometry = shapely.box(0, 0, 1, 1)
    key = kml_io.fragments.geometry_key(geometry, 5)
    expected = kml_io.geometry.geometry_boundaries(geometry)
    cache = kml_io.fragments.BoundaryCache()

    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "policy"):
        spatial_data.product_cache.put(kml_io.fragments.NAMESPACE, key, payload)
        assert cache.boundaries(geometry, 5, kml_io.geometry.geometry_boundaries) == (
            expected
        )
        assert spatial_data.product_cache.get(kml_io.fragments.NAMESPACE, key) == (
            spatial_data.cache_values.dumps(expected)
        )

    assert cache.computed == 1


def test_boundary_cache_boundaries_does_not_publish_failed_rendering(
    tmp_path: pathlib.Path,
) -> None:
    geometry = shapely.box(0, 0, 1, 1)
    cache = kml_io.fragments.BoundaryCache()
    renderer = tests.helpers.doubles.errors.raising_stub(ValueError("render failed"))

    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "policy"):
        with pytest.raises(ValueError, match="render failed"):
            cache.boundaries(geometry, 5, renderer)
        assert (
            spatial_data.product_cache.get(
                kml_io.fragments.NAMESPACE,
                kml_io.fragments.geometry_key(geometry, 5),
            )
            is None
        )

    assert not cache.entries


def test_boundary_cache_retain_replaces_accounting_for_the_same_key() -> None:
    cache = kml_io.fragments.BoundaryCache()
    cache.retain("same geometry", ("original boundary",))
    cache.retain("same geometry", ("replacement",))
    reference = kml_io.fragments.BoundaryCache()
    reference.retain("same geometry", ("replacement",))

    assert cache.retained_bytes == reference.retained_bytes
    assert cache.entries == reference.entries


def test_boundary_cache_retain_drops_a_replacement_exceeding_the_budget() -> None:
    probe = kml_io.fragments.BoundaryCache()
    probe.retain("geometry", ("original",))
    cache = kml_io.fragments.BoundaryCache(budget=probe.retained_bytes)
    cache.retain("geometry", ("original",))
    cache.retain("geometry", ("larger replacement",))

    assert cache.retained_bytes == 0
    assert not cache.entries
