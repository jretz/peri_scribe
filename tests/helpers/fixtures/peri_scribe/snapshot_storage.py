"""Isolate snapshot storage tests with explicit fixtures."""

from __future__ import annotations

import pathlib

import pytest

import peri_scribe.geo.reading
import peri_scribe.output
import peri_scribe.sources.snapshots
import tests.helpers.doubles.peri_scribe.snapshot_storage


@pytest.fixture
def geo_package_store(
    monkeypatch: pytest.MonkeyPatch,
) -> tests.helpers.doubles.peri_scribe.snapshot_storage.GeoPackageStore:
    """Install an in-memory stand-in for the fetch command's file storage.

    Args:
        monkeypatch: Replace dependencies and restore them after the test.

    Returns:
        The store recording written GeoPackage layers.
    """
    store = tests.helpers.doubles.peri_scribe.snapshot_storage.GeoPackageStore()
    monkeypatch.setattr(peri_scribe.output, "write_geopackage", store.write)
    monkeypatch.setattr(
        peri_scribe.sources.snapshots,
        "existing_source_files",
        store.source_files,
    )
    monkeypatch.setattr(
        peri_scribe.geo.reading,
        "read_layer_dataframe",
        store.read_layer,
    )
    monkeypatch.setattr(pathlib.Path, "mkdir", lambda *_args, **_kwargs: None)
    return store
