"""Tests for peri_scribe.fires.sources."""

from __future__ import annotations

import pathlib

import hypothesis
import hypothesis.strategies
import pytest

import peri_scribe.fires.sources
import peri_scribe.geo.package
import peri_scribe.sources.snapshots
import tests.helpers.strategies.peri_scribe.geo.database


# This test is slow, so limit examples to keep routine test runs fast.
@hypothesis.settings(max_examples=25)
@hypothesis.given(
    snapshots=hypothesis.strategies.dictionaries(
        hypothesis.strategies.integers(0, 5),
        tests.helpers.strategies.peri_scribe.geo.database.snapshot_contents(),
        max_size=5,
    ),
)
def test_read_fire_sources_preserves_each_rows_provenance_and_all_memberships(
    snapshots: dict[int, peri_scribe.geo.package.GeopackageContents],
) -> None:
    contents = {
        pathlib.Path(f"sources/snapshot-{serial}.gpkg"): snapshot
        for serial, snapshot in snapshots.items()
    }
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(
            peri_scribe.sources.snapshots,
            "geo_package_files",
            lambda _directory: list(contents),
        )
        patch.setattr(
            peri_scribe.fires.sources,
            "read_fire_geopackage",
            lambda path, **_kwargs: contents[path],
        )
        actual = peri_scribe.fires.sources.read_fire_sources(pathlib.Path("sources"))
    assert list(zip(actual.paths, actual.rows, strict=True)) == [
        (path, row) for path, snapshot in contents.items() for row in snapshot.rows
    ]
    assert actual.memberships == tuple(
        membership
        for snapshot in contents.values()
        for membership in snapshot.memberships
    )
