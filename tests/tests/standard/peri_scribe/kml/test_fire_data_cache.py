"""Persist only exact fallback ring sequences and release geometry references."""

import dataclasses
import gc
import pathlib
import weakref

import pytest

import peri_scribe.execution
import peri_scribe.kml.fire_data
import peri_scribe.perimeters.progression
import spatial_data.cache_values
import spatial_data.product_cache
import tests.helpers.doubles.errors
import tests.helpers.factories.peri_scribe.kml.fire_data
from measurement_units import units


def test_added_areas_for_rings_reuses_exact_persistent_quantities(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rings = tests.helpers.factories.peri_scribe.kml.fire_data.fallback_rings()
    database = tmp_path / "products.sqlite"
    with spatial_data.product_cache.scope(database, "test"):
        expected = peri_scribe.kml.fire_data.added_areas_for_rings(rings)
    monkeypatch.setattr(
        peri_scribe.perimeters.progression,
        "added_areas",
        tests.helpers.doubles.errors.raising_stub(AssertionError("Repeated union")),
    )
    with spatial_data.product_cache.scope(database, "test"):
        actual = peri_scribe.kml.fire_data.added_areas_for_rings(rings)
    assert spatial_data.cache_values.dumps(actual) == spatial_data.cache_values.dumps(
        expected,
    )


@pytest.mark.parametrize("change", ["reversed", "subset", "geometry"])
def test_added_areas_for_rings_invalidates_changed_display_sequences(
    tmp_path: pathlib.Path,
    change: str,
) -> None:
    rings = tests.helpers.factories.peri_scribe.kml.fire_data.fallback_rings()
    changed = (
        tuple(reversed(rings))
        if change == "reversed"
        else rings[1:]
        if change == "subset"
        else (rings[0], rings[0])
    )
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "test"):
        original = peri_scribe.kml.fire_data.added_areas_for_rings(rings)
        actual = peri_scribe.kml.fire_data.added_areas_for_rings(changed)
    expected = peri_scribe.perimeters.progression.added_areas(
        ring.geometry for ring in changed
    )
    assert actual == expected
    assert actual != original


def test_added_areas_for_rings_trusted_values_override_every_fallback_cache(
    tmp_path: pathlib.Path,
) -> None:
    rings = tests.helpers.factories.peri_scribe.kml.fire_data.fallback_rings()
    digest = peri_scribe.perimeters.progression.sequence_digest(
        ring.geometry for ring in rings
    )
    stored = (1 * units.acres, 2 * units.acres)
    changed = tuple(
        dataclasses.replace(ring, added_area=area, sequence_digest=digest)
        for ring, area in zip(rings, stored, strict=True)
    )
    with (
        spatial_data.product_cache.scope(tmp_path / "products.sqlite", "test"),
        peri_scribe.execution.sharing(),
    ):
        original = peri_scribe.kml.fire_data.added_areas_for_rings(rings)
        assert original != stored
        assert peri_scribe.kml.fire_data.added_areas_for_rings(changed) == stored


@pytest.mark.parametrize(
    "payload",
    [
        b"invalid",
        spatial_data.cache_values.dumps([1 * units.acres, 2 * units.acres]),
        spatial_data.cache_values.dumps((1 * units.acres,)),
        spatial_data.cache_values.dumps((1, 2)),
        spatial_data.cache_values.dumps((1 * units.meters, 2 * units.meters)),
    ],
)
def test_added_areas_for_rings_replaces_malformed_products(
    tmp_path: pathlib.Path,
    payload: bytes,
) -> None:
    rings = tests.helpers.factories.peri_scribe.kml.fire_data.fallback_rings()
    digest = peri_scribe.perimeters.progression.sequence_digest(
        ring.geometry for ring in rings
    )
    expected = peri_scribe.perimeters.progression.added_areas(
        ring.geometry for ring in rings
    )
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "test"):
        spatial_data.product_cache.put(
            peri_scribe.kml.fire_data.RING_AREA_NAMESPACE,
            digest,
            payload,
        )
        assert peri_scribe.kml.fire_data.added_areas_for_rings(rings) == expected
        assert (
            peri_scribe.kml.fire_data.cached_ring_areas(digest, len(rings)) == expected
        )


def test_added_areas_for_rings_releases_geometries_and_execution_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rings = tests.helpers.factories.peri_scribe.kml.fire_data.fallback_rings()
    reference = weakref.ref(rings[0].geometry)
    with peri_scribe.execution.sharing():
        first = peri_scribe.kml.fire_data.added_areas_for_rings(rings)
        assert peri_scribe.kml.fire_data.added_areas_for_rings(rings) is first
        del rings
        gc.collect()
        assert reference() is None
    monkeypatch.setattr(
        peri_scribe.perimeters.progression,
        "added_areas",
        tests.helpers.doubles.errors.raising_stub(AssertionError("Fresh computation")),
    )
    with (
        peri_scribe.execution.sharing(),
        pytest.raises(
            AssertionError,
            match="Fresh computation",
        ),
    ):
        peri_scribe.kml.fire_data.added_areas_for_rings(
            tests.helpers.factories.peri_scribe.kml.fire_data.fallback_rings(),
        )


def test_added_areas_for_rings_keeps_result_when_serialization_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rings = tests.helpers.factories.peri_scribe.kml.fire_data.fallback_rings()
    expected = peri_scribe.perimeters.progression.added_areas(
        ring.geometry for ring in rings
    )
    monkeypatch.setattr(
        spatial_data.cache_values,
        "dumps",
        tests.helpers.doubles.errors.raising_stub(ValueError("Unsupported product")),
    )
    assert peri_scribe.kml.fire_data.added_areas_for_rings(rings) == expected
