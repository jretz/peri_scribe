"""Tests for scoped snapshot geometry sharing."""

from __future__ import annotations

import hypothesis
import shapely

import spatial_data.geometry_pool
import tests.helpers.strategies.spatial_data.geometry_pool


@hypothesis.given(
    observations=tests.helpers.strategies.spatial_data.geometry_pool.observations(),
)
def test_shared_geometry_matches_reference_cache(
    observations: list[tuple[bytes, bytes]],
) -> None:
    state = None
    reference: dict[bytes, shapely.Geometry] = {}
    for digest, wkb in observations:
        state, geometry = spatial_data.geometry_pool.shared_geometry(
            state,
            digest,
            wkb,
        )
        assert shapely.to_wkb(geometry, include_srid=True) == wkb
        assert geometry is reference.setdefault(wkb, geometry)


@hypothesis.given(
    observations=tests.helpers.strategies.spatial_data.geometry_pool.observations(),
)
def test_shared_geometry_preserves_generated_snapshots(
    observations: list[tuple[bytes, bytes]],
) -> None:
    state = None
    contents: dict[tuple[bytes, bytes], shapely.Geometry] = {}
    snapshots = []
    for digest, wkb in observations:
        state, geometry = spatial_data.geometry_pool.shared_geometry(
            state,
            digest,
            wkb,
        )
        contents[digest, wkb] = geometry
        snapshots.append((state, contents.copy()))
    for snapshot, expected in snapshots:
        for digest, wkb in dict.fromkeys(observations):
            updated, geometry = spatial_data.geometry_pool.shared_geometry(
                snapshot,
                digest,
                wkb,
            )
            if (digest, wkb) in expected:
                assert updated is snapshot
                assert geometry is expected[digest, wkb]
            else:
                assert updated is not snapshot
