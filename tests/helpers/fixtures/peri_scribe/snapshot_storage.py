"""Isolate snapshot storage tests with explicit fixtures."""

from __future__ import annotations

import pathlib
import tempfile

import pytest

import peri_scribe.geo.reading
import peri_scribe.sources.snapshots
import spatial_data.layers
import tests.helpers.doubles.peri_scribe.snapshot_storage


@pytest.fixture
def geo_package_store(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> tests.helpers.doubles.peri_scribe.snapshot_storage.GeoPackageStore:
    """Install an in-memory stand-in for the fetch command's file storage.

    Args:
        monkeypatch: Replace dependencies and restore them after the test.
        tmp_path: A real isolated root for staging-directory lifecycle management.

    Returns:
        The store recording written GeoPackage layers.
    """
    store = tests.helpers.doubles.peri_scribe.snapshot_storage.GeoPackageStore()
    monkeypatch.setattr(spatial_data.layers, "write_geopackage", store.write)
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
    original_temporary_directory = tempfile.TemporaryDirectory
    monkeypatch.setattr(
        tempfile,
        "TemporaryDirectory",
        lambda **_kwargs: original_temporary_directory(dir=tmp_path),
    )
    monkeypatch.setattr(
        pathlib.Path,
        "replace",
        lambda source, target: store.replace(source, pathlib.Path(target)),
    )
    monkeypatch.setattr(pathlib.Path, "mkdir", lambda *_args, **_kwargs: None)
    return store
