"""Snapshot recovery must never reuse an interrupted GeoPackage write."""

import pathlib
import typing

import pytest

import peri_scribe.sources.feed_types
import peri_scribe.sources.fetching
import peri_scribe.sources.snapshots
import spatial_data.layers
import tests.helpers.doubles.peri_scribe.sources.fetching
import tests.helpers.doubles.peri_scribe.sources.snapshot_fetching


def test_fetch_feed_snapshot_retries_after_interrupted_write(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    tests.helpers.doubles.peri_scribe.sources.snapshot_fetching.configure_fetch(
        monkeypatch,
    )
    feed = typing.cast(
        "peri_scribe.sources.feed_types.Feed",
        tests.helpers.doubles.peri_scribe.sources.fetching.sample_feed_stub(),
    )
    with monkeypatch.context() as failure:
        failure.setattr(
            spatial_data.layers,
            "write_geopackage",
            tests.helpers.doubles.peri_scribe.sources.snapshot_fetching.interrupt_write,
        )
        with pytest.raises(
            tests.helpers.doubles.peri_scribe.sources.snapshot_fetching.Interrupted,
        ):
            peri_scribe.sources.fetching.fetch_feed_snapshot(
                feed,
                base_dir=tmp_path,
                year=2026,
                full=False,
            )
    source_directory = peri_scribe.sources.snapshots.source_directory_path(
        tmp_path,
        2026,
        feed.name,
    )
    assert peri_scribe.sources.snapshots.existing_source_files(source_directory) == []
    result = peri_scribe.sources.fetching.fetch_feed_snapshot(
        feed,
        base_dir=tmp_path,
        year=2026,
        full=False,
    )
    assert result.changed
    assert result.path is not None
    assert len(spatial_data.layers.read_layer(result.path, feed.name)) == 1
