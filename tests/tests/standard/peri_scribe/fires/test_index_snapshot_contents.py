"""Source generations must authenticate the parsed records used to build the index."""

import pathlib

import pytest

import peri_scribe.fires.classification
import peri_scribe.fires.index
import peri_scribe.fires.sources
import peri_scribe.geo.database
import peri_scribe.models
import peri_scribe.sources.feed_types
import tests.helpers.doubles.errors
import tests.helpers.doubles.peri_scribe.fires.index
import tests.helpers.factories.peri_scribe.geo.package
import tests.helpers.peri_scribe.fires.snapshot_contents
import tests.helpers.peri_scribe.geo.package


@pytest.mark.parametrize("clear_memo", [False, True])
def test_index_fire_sources_rechecks_snapshot_bytes_before_certifying_generation(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    configured_feeds: list[peri_scribe.sources.feed_types.Feed],
    *,
    clear_memo: bool,
) -> None:
    monkeypatch.setattr(peri_scribe.geo.database, "RECORD_CACHE_SYNCED", {})
    feed = configured_feeds[0]
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
    peri_scribe.fires.index.index_fire_sources(tmp_path)
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
    if clear_memo:
        peri_scribe.geo.database.RECORD_CACHE_SYNCED.clear()

    peri_scribe.fires.index.index_fire_sources(tmp_path)
    edited = peri_scribe.fires.index.load_fire_index(tmp_path)
    tests.helpers.peri_scribe.geo.package.record_cache_database_path(path).unlink()
    monkeypatch.setattr(
        peri_scribe.fires.sources,
        "read_fire_sources",
        tests.helpers.doubles.errors.raising_stub(AssertionError("Repeated parsing")),
    )
    peri_scribe.fires.index.index_fire_sources(tmp_path)
    warmed = peri_scribe.fires.index.load_fire_index(tmp_path)

    assert [[fire.name for fire in index.fires] for index in (edited, warmed)] == [
        ["Bravo Fire"],
        ["Bravo Fire"],
    ]
