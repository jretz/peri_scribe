"""Tests for peri_scribe.perimeters.classification_data."""

from __future__ import annotations

import asyncio
import contextlib
import gc
import json
import os
import sys
import unittest.mock
import weakref

import pytest
import shapely.geometry

import peri_scribe.perimeters.classification_data


def test_reproject_to_california_albers_returns_projected_geometry() -> None:
    point = shapely.geometry.Point(-120.0, 39.0)
    result = peri_scribe.perimeters.classification_data.reproject_to_california_albers(
        point,
        4326,
    )
    assert isinstance(result, shapely.geometry.Point)
    assert result != point


def test_reproject_to_california_albers_preserves_z_coordinates() -> None:
    point = shapely.geometry.Point(-120.0, 39.0, 123.0)
    result = peri_scribe.perimeters.classification_data.reproject_to_california_albers(
        point,
        4326,
    )
    assert isinstance(result, shapely.geometry.Point)
    assert result.z == pytest.approx(123.0)


def test_projection_cache_project_reuses_only_matching_object_and_source_crs() -> None:
    geometry = shapely.geometry.Point(-120, 39, 123)
    cache = peri_scribe.perimeters.classification_data.ProjectionCache()
    expected_projections = 3
    with unittest.mock.patch.object(
        peri_scribe.perimeters.classification_data,
        "reproject_to_california_albers",
        wraps=peri_scribe.perimeters.classification_data.reproject_to_california_albers,
    ) as project:
        first = cache.project(geometry, 4326)
        assert cache.project(geometry, 4326) is first
        other_reference = cache.project(geometry, 4269)
        assert cache.project(geometry, 4269) is other_reference
        assert cache.project(shapely.geometry.Point(-120, 39, 123), 4326) is not first
    assert project.call_count == expected_projections
    assert first.z == geometry.z
    assert other_reference.z == geometry.z


def test_projection_cache_project_releases_geometry_with_owner() -> None:
    cache = peri_scribe.perimeters.classification_data.ProjectionCache()
    original = shapely.geometry.Point(-120, 39)
    projected = cache.project(original, 4326)
    source_reference = weakref.ref(original)
    projected_reference = weakref.ref(projected)
    del original, projected
    gc.collect()
    assert source_reference() is not None
    assert projected_reference() is not None
    del cache
    gc.collect()
    assert source_reference() is None
    assert projected_reference() is None


def test_boundaries_prepared_box_retains_coordinates_reference_and_precision() -> None:
    box = shapely.set_srid(
        shapely.set_precision(shapely.geometry.box(0, 0, 10, 10), 0.01),
        4326,
    )
    encoded = shapely.to_wkb(box, include_srid=True)
    boundaries = peri_scribe.perimeters.classification_data.Boundaries(
        box=box,
        border=shapely.geometry.LineString([(10, 0), (10, 10)]),
    )
    prepared = boundaries.prepared_box
    assert not shapely.is_prepared(boundaries.box)
    assert shapely.is_prepared(prepared)
    assert prepared is not boundaries.box
    assert boundaries.prepared_box is prepared
    assert shapely.to_wkb(prepared, include_srid=True) == encoded
    assert shapely.get_precision(prepared) == shapely.get_precision(box)


def test_boundaries_prepared_box_releases_native_clone_with_owner() -> None:
    boundaries = peri_scribe.perimeters.classification_data.Boundaries(
        box=shapely.geometry.box(0, 0, 10, 10),
        border=shapely.geometry.LineString([(10, 0), (10, 10)]),
    )
    prepared = boundaries.prepared_box
    reference = weakref.ref(prepared)
    del boundaries, prepared
    gc.collect()
    assert reference() is None


@pytest.mark.asyncio
async def test_boundaries_prepared_box_isolates_concurrent_native_indexes() -> None:
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "tests.helpers.reference.peri_scribe.perimeters.boundary_threads",
        env=os.environ | {"PYTHONFAULTHANDLER": "1"},
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        async with asyncio.timeout(30):
            stdout, stderr = await process.communicate()
    finally:
        if process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                process.kill()
            await process.communicate()
    assert process.returncode == 0, stderr.decode()
    result = json.loads(stdout)
    assert result["distinct_prepared_objects"] == result["workers"]
    assert not result["source_prepared"]
    assert result["predicate_checks"] > 0
