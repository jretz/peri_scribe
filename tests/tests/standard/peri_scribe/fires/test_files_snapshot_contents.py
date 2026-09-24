"""Authenticated geography generations must use current snapshot content."""

import pathlib
import typing

import peri_scribe.fires.classification
import peri_scribe.fires.files
import peri_scribe.fires.index
import peri_scribe.fires.sources
import peri_scribe.geo.database
import peri_scribe.models
import peri_scribe.preparation
import peri_scribe.sources.feed_types
import peri_scribe.sources.feeds
import spatial_data.layers
import tests.helpers.doubles.errors
import tests.helpers.doubles.peri_scribe.fires.index
import tests.helpers.factories.peri_scribe.geo.package
import tests.helpers.peri_scribe.fires.snapshot_contents
import tests.helpers.peri_scribe.geo.package


if typing.TYPE_CHECKING:
    import pytest


def test_write_history_of_full_geography_uses_current_snapshot_contents(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(peri_scribe.geo.database, "RECORD_CACHE_SYNCED", {})
    feed = peri_scribe.sources.feed_types.ArcGISFeed(
        url=(
            "https://example.test/ArcGIS/rest/services/"
            "WFIGS_Incident_Locations_Current/FeatureServer/0"
        ),
        fire_name_column="incident_name",
        status_column="displayStatus",
    )
    monkeypatch.setattr(peri_scribe.sources.feeds, "FEEDS", [feed])
    path = tests.helpers.factories.peri_scribe.geo.package.write_cache_snapshot(
        tmp_path,
        feed,
        [("Alpha Fire", "Active")],
    )
    classifier = tests.helpers.doubles.peri_scribe.fires.index.ClassificationRecorder(
        classification=peri_scribe.models.FireClassification(
            classification=peri_scribe.models.BorderClassification.INSIDE_CALIFORNIA,
            outside_area_fraction=0.0,
            inside_area_fraction=1.0,
        ),
    )
    monkeypatch.setattr(
        peri_scribe.fires.classification,
        "classify_fire_sources",
        classifier.classify,
    )
    with peri_scribe.preparation.scope(tmp_path):
        peri_scribe.fires.index.index_fire_sources(tmp_path)
        peri_scribe.fires.files.write_history_of_full_geography(tmp_path)
    source_stamp, bucket_stamp = (
        tests.helpers.peri_scribe.fires.snapshot_contents.rename_point_snapshot(
            path,
            feed.name,
            "Bravo Fire",
        )
    )
    assert path.stat().st_size == source_stamp.st_size
    assert path.stat().st_mtime_ns == source_stamp.st_mtime_ns
    assert path.parent.stat().st_mtime_ns == bucket_stamp.st_mtime_ns
    with peri_scribe.preparation.scope(tmp_path):
        peri_scribe.fires.index.index_fire_sources(tmp_path)
        output = peri_scribe.fires.files.write_history_of_full_geography(tmp_path)
    edited = spatial_data.layers.read_layer(
        output,
        peri_scribe.fires.files.POINT_LAYER_NAME,
    )
    tests.helpers.peri_scribe.geo.package.record_cache_database_path(path).unlink()
    monkeypatch.setattr(
        peri_scribe.fires.sources,
        "read_fire_sources",
        tests.helpers.doubles.errors.raising_stub(AssertionError("Repeated parsing")),
    )
    peri_scribe.fires.files.write_history_of_full_geography(tmp_path)
    warmed = spatial_data.layers.read_layer(
        output,
        peri_scribe.fires.files.POINT_LAYER_NAME,
    )

    assert edited["fire_name"].tolist() == ["Bravo Fire"]
    assert edited.equals(warmed)
