"""Changed generations reuse source summaries without decoding unrelated snapshots."""

from __future__ import annotations

import pathlib
import typing

import peri_scribe.execution
import peri_scribe.fires.classification
import peri_scribe.fires.index
import peri_scribe.geo.reading
import peri_scribe.models
import peri_scribe.preparation
import peri_scribe.sources.feed_types
import peri_scribe.sources.snapshots
import tests.helpers.doubles.peri_scribe.fires.index
import tests.helpers.doubles.peri_scribe.geo.reading
import tests.helpers.factories.peri_scribe.geo.package


if typing.TYPE_CHECKING:
    import pytest


def test_incremental_index_hydrates_new_snapshot_and_matches_complete_rebuild(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    repeated_geometry_sources: pathlib.Path,
    configured_feeds: list[peri_scribe.sources.feed_types.Feed],
) -> None:
    classifier = tests.helpers.doubles.peri_scribe.fires.index.ClassificationRecorder(
        classification=peri_scribe.models.FireClassification(
            classification=peri_scribe.models.BorderClassification.OUTSIDE_CALIFORNIA,
            outside_area_fraction=1.0,
            inside_area_fraction=0.0,
        ),
    )
    monkeypatch.setattr(
        peri_scribe.fires.classification,
        "classify_fire_sources",
        classifier.classify,
    )
    peri_scribe.fires.index.index_fire_sources(tmp_path)
    classifier.calls.clear()
    added = tests.helpers.factories.peri_scribe.geo.package.write_cache_snapshot(
        tmp_path,
        configured_feeds[0],
        [("Third", "Active")],
        serial_number=2,
    )
    reads = tests.helpers.doubles.peri_scribe.geo.reading.SnapshotReads(
        read=peri_scribe.geo.reading.read_geopackages_cached,
    )
    monkeypatch.setattr(peri_scribe.geo.reading, "read_geopackages_cached", reads)
    with peri_scribe.execution.sharing():
        peri_scribe.fires.index.index_fire_sources(tmp_path)
        assert (
            peri_scribe.execution.get(
                peri_scribe.execution.Group.SOURCES,
                repeated_geometry_sources.resolve(),
            )
            is None
        )
    assert {path for call in reads.calls for path in call} == {added}
    assert classifier.calls == [("Third",)]
    output = peri_scribe.sources.snapshots.fire_index_path(tmp_path)
    incremental = output.read_bytes()
    with peri_scribe.preparation.scope(tmp_path, unconditional=True):
        peri_scribe.fires.index.index_fire_sources(tmp_path)
    assert output.read_bytes() == incremental
