"""Polygon-version publications use the first KMZ run that could include them."""

from __future__ import annotations

import dataclasses
import datetime
import pathlib
import unittest.mock

import pytest

import peri_scribe.show_latencies.perimeters
import peri_scribe.show_latencies.runs
import peri_scribe.show_latencies.sources
import peri_scribe.sources.feeds
import tests.helpers.factories.peri_scribe.show_latencies.evidence
import tests.helpers.factories.peri_scribe.show_latencies.sources
from measurement_units import units


@pytest.mark.parametrize(("produced", "geography"), [(False, 120), (True, None)])
def test_latencies_needs_no_sources_without_a_kmz_and_input_cutoff(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    produced: bool,
    geography: int | None,
) -> None:
    reader = unittest.mock.Mock(side_effect=AssertionError("No source data needed"))
    monkeypatch.setattr(peri_scribe.show_latencies.sources, "read_versions", reader)
    evidence = tests.helpers.factories.peri_scribe.show_latencies.evidence.evidence(
        runs=(
            tests.helpers.factories.peri_scribe.show_latencies.evidence.run(
                produced=produced,
                geography=geography,
            ),
        ),
        snapshots={},
    )
    assert (
        peri_scribe.show_latencies.perimeters.latencies(
            tmp_path,
            evidence,
            tests.helpers.factories.peri_scribe.show_latencies.evidence.WINDOW,
        )
        == ()
    )
    reader.assert_not_called()


def test_latencies_uses_first_kmz_with_inputs_collected_before_geography(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    publication = (
        tests.helpers.factories.peri_scribe.show_latencies.evidence.publication()
    )
    reader = unittest.mock.Mock(return_value=(publication,))
    monkeypatch.setattr(peri_scribe.show_latencies.sources, "read_versions", reader)
    evidence = tests.helpers.factories.peri_scribe.show_latencies.evidence.evidence(
        runs=(
            tests.helpers.factories.peri_scribe.show_latencies.evidence.run(
                100,
                geography=40,
            ),
            tests.helpers.factories.peri_scribe.show_latencies.evidence.run(
                140,
                produced=False,
                geography=60,
            ),
            tests.helpers.factories.peri_scribe.show_latencies.evidence.run(
                200,
                geography=None,
            ),
            tests.helpers.factories.peri_scribe.show_latencies.evidence.run(),
            tests.helpers.factories.peri_scribe.show_latencies.evidence.run(
                600,
                geography=420,
            ),
        ),
        snapshots={
            publication.source_file: (
                tests.helpers.factories.peri_scribe.show_latencies.evidence.NOW
                + datetime.timedelta(seconds=45)
            ),
        },
    )
    assert peri_scribe.show_latencies.perimeters.latencies(
        tmp_path,
        evidence,
        tests.helpers.factories.peri_scribe.show_latencies.evidence.WINDOW,
    ) == (270 * units.seconds,)
    reader.assert_called_once_with(
        tmp_path,
        tests.helpers.factories.peri_scribe.show_latencies.evidence.WINDOW,
    )


def test_latencies_includes_collection_at_the_geography_start_boundary(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    publication = (
        tests.helpers.factories.peri_scribe.show_latencies.evidence.publication()
    )
    monkeypatch.setattr(
        peri_scribe.show_latencies.sources,
        "read_versions",
        unittest.mock.Mock(return_value=(publication,)),
    )
    evidence = tests.helpers.factories.peri_scribe.show_latencies.evidence.evidence(
        runs=(tests.helpers.factories.peri_scribe.show_latencies.evidence.run(),),
        snapshots={
            publication.source_file: (
                tests.helpers.factories.peri_scribe.show_latencies.evidence.NOW
                + datetime.timedelta(seconds=120)
            ),
        },
    )
    assert peri_scribe.show_latencies.perimeters.latencies(
        tmp_path,
        evidence,
        tests.helpers.factories.peri_scribe.show_latencies.evidence.WINDOW,
    ) == (270 * units.seconds,)


def test_latencies_groups_a_fires_versions_by_earliest_publication_in_each_run(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    early = tests.helpers.factories.peri_scribe.show_latencies.evidence.publication()
    later = tests.helpers.factories.peri_scribe.show_latencies.evidence.publication(
        90,
        source_file="feed/later.gpkg",
    )
    monkeypatch.setattr(
        peri_scribe.show_latencies.sources,
        "read_versions",
        unittest.mock.Mock(return_value=(later, early)),
    )
    evidence = tests.helpers.factories.peri_scribe.show_latencies.evidence.evidence(
        runs=(tests.helpers.factories.peri_scribe.show_latencies.evidence.run(),),
        snapshots={
            early.source_file: early.published,
            later.source_file: later.published,
        },
    )
    assert peri_scribe.show_latencies.perimeters.latencies(
        tmp_path,
        evidence,
        tests.helpers.factories.peri_scribe.show_latencies.evidence.WINDOW,
    ) == (270 * units.seconds,)


def test_latencies_keeps_distinct_fires_in_the_same_source_snapshot(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    publications = tuple(
        tests.helpers.factories.peri_scribe.show_latencies.evidence.publication(
            identifier=identifier,
        )
        for identifier in ("first", "second")
    )
    monkeypatch.setattr(
        peri_scribe.show_latencies.sources,
        "read_versions",
        unittest.mock.Mock(return_value=publications),
    )
    evidence = tests.helpers.factories.peri_scribe.show_latencies.evidence.evidence(
        runs=(tests.helpers.factories.peri_scribe.show_latencies.evidence.run(),),
        snapshots={publications[0].source_file: publications[0].published},
    )
    assert peri_scribe.show_latencies.perimeters.latencies(
        tmp_path,
        evidence,
        tests.helpers.factories.peri_scribe.show_latencies.evidence.WINDOW,
    ) == (270 * units.seconds, 270 * units.seconds)


def test_latencies_counts_later_versions_even_when_legacy_run_identifiers_repeat(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = tests.helpers.factories.peri_scribe.show_latencies.evidence.publication()
    second = tests.helpers.factories.peri_scribe.show_latencies.evidence.publication(
        330,
        source_file="feed/later.gpkg",
    )
    monkeypatch.setattr(
        peri_scribe.show_latencies.sources,
        "read_versions",
        unittest.mock.Mock(return_value=(first, second)),
    )
    evidence = tests.helpers.factories.peri_scribe.show_latencies.evidence.evidence(
        runs=tuple(
            dataclasses.replace(
                tests.helpers.factories.peri_scribe.show_latencies.evidence.run(
                    finished,
                    geography=finished - 180,
                ),
                identifier="legacy",
            )
            for finished in (300, 600, 900)
        ),
        snapshots={
            first.source_file: first.published,
            second.source_file: second.published,
        },
    )
    assert peri_scribe.show_latencies.perimeters.latencies(
        tmp_path,
        evidence,
        tests.helpers.factories.peri_scribe.show_latencies.evidence.WINDOW,
    ) == (270 * units.seconds, 270 * units.seconds)


@pytest.mark.parametrize("collected", [None, 200])
def test_latencies_excludes_versions_without_collection_before_a_kmz_input_cutoff(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    collected: int | None,
) -> None:
    publication = (
        tests.helpers.factories.peri_scribe.show_latencies.evidence.publication()
    )
    monkeypatch.setattr(
        peri_scribe.show_latencies.sources,
        "read_versions",
        unittest.mock.Mock(return_value=(publication,)),
    )
    evidence = tests.helpers.factories.peri_scribe.show_latencies.evidence.evidence(
        runs=(tests.helpers.factories.peri_scribe.show_latencies.evidence.run(),),
        snapshots=(
            {
                publication.source_file: (
                    tests.helpers.factories.peri_scribe.show_latencies.evidence.NOW
                    + datetime.timedelta(seconds=collected)
                ),
            }
            if collected is not None
            else {}
        ),
    )
    assert (
        peri_scribe.show_latencies.perimeters.latencies(
            tmp_path,
            evidence,
            tests.helpers.factories.peri_scribe.show_latencies.evidence.WINDOW,
        )
        == ()
    )


def test_latencies_excludes_publication_clock_after_run_completion(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    publication = (
        tests.helpers.factories.peri_scribe.show_latencies.evidence.publication(
            330,
        )
    )
    monkeypatch.setattr(
        peri_scribe.show_latencies.sources,
        "read_versions",
        unittest.mock.Mock(return_value=(publication,)),
    )
    evidence = tests.helpers.factories.peri_scribe.show_latencies.evidence.evidence(
        runs=(tests.helpers.factories.peri_scribe.show_latencies.evidence.run(),),
        snapshots={
            publication.source_file: (
                tests.helpers.factories.peri_scribe.show_latencies.evidence.NOW
                + datetime.timedelta(seconds=45)
            ),
        },
    )
    assert (
        peri_scribe.show_latencies.perimeters.latencies(
            tmp_path,
            evidence,
            tests.helpers.factories.peri_scribe.show_latencies.evidence.WINDOW,
        )
        == ()
    )


def test_latencies_uses_polygon_version_metadata_without_decoding_coordinates(
    tmp_path: pathlib.Path,
) -> None:
    feed = peri_scribe.sources.feeds.WFIGS_PERIMETERS_FEED
    collected = {}
    for serial, (published, surveyed) in enumerate(
        [(-30, 0), (30, 10), (330, 10), (630, 20)],
    ):
        row = tests.helpers.factories.peri_scribe.show_latencies.sources.record(
            feed,
            surveyed=surveyed,
        )
        row["attr_EstimatedCostToDate"] = serial * 100_000
        row["attr_ModifiedOnDateTime_dt"] = str(serial)
        path = tests.helpers.factories.peri_scribe.show_latencies.sources.snapshot(
            tmp_path,
            feed,
            serial,
            published,
            [row],
        )
        collected[str(path.relative_to(tmp_path / "sources"))] = (
            tests.helpers.factories.peri_scribe.show_latencies.evidence.NOW
            + datetime.timedelta(seconds=published + 5)
        )
    evidence = tests.helpers.factories.peri_scribe.show_latencies.evidence.evidence(
        runs=tuple(
            tests.helpers.factories.peri_scribe.show_latencies.evidence.run(
                finished,
                geography=finished - 180,
            )
            for finished in (300, 600, 900)
        ),
        snapshots=collected,
    )
    assert peri_scribe.show_latencies.perimeters.latencies(
        tmp_path,
        evidence,
        tests.helpers.factories.peri_scribe.show_latencies.evidence.WINDOW,
    ) == (270 * units.seconds, 270 * units.seconds)


def test_latencies_keeps_first_consumption_when_window_moves_inside_its_run(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    publication = (
        tests.helpers.factories.peri_scribe.show_latencies.evidence.publication(
            1,
        )
    )
    monkeypatch.setattr(
        peri_scribe.show_latencies.sources,
        "read_versions",
        unittest.mock.Mock(return_value=(publication,)),
    )
    tests.helpers.factories.peri_scribe.show_latencies.evidence.write_log(
        tmp_path / "logs/2026-09.jsonl",
        [
            tests.helpers.factories.peri_scribe.show_latencies.evidence.record(
                "Starting command",
                -5,
            ),
            tests.helpers.factories.peri_scribe.show_latencies.evidence.record(
                "Finished phase",
                1,
                phase="write-snapshot",
                feed="feed",
                path=f"/remote/sources/{publication.source_file}",
                status="completed",
            ),
            tests.helpers.factories.peri_scribe.show_latencies.evidence.record(
                "Starting phase",
                2,
                phase_path="geography",
            ),
            tests.helpers.factories.peri_scribe.show_latencies.evidence.record(
                "Finished phase",
                4,
                phase_path="kmz.serialize-and-write-kmz",
                status="completed",
            ),
            tests.helpers.factories.peri_scribe.show_latencies.evidence.record(
                "Finished command",
                5,
                duration={"value": 10, "units": "second"},
            ),
            tests.helpers.factories.peri_scribe.show_latencies.evidence.record(
                "Starting command",
                20,
                run_id="second",
            ),
            tests.helpers.factories.peri_scribe.show_latencies.evidence.record(
                "Starting phase",
                25,
                run_id="second",
                phase_path="geography",
            ),
            tests.helpers.factories.peri_scribe.show_latencies.evidence.record(
                "Finished phase",
                29,
                run_id="second",
                phase_path="kmz.serialize-and-write-kmz",
                status="completed",
            ),
            tests.helpers.factories.peri_scribe.show_latencies.evidence.record(
                "Finished command",
                30,
                run_id="second",
                duration={"value": 10, "units": "second"},
            ),
        ],
    )
    for start in (-10, 0):
        window = dataclasses.replace(
            tests.helpers.factories.peri_scribe.show_latencies.evidence.WINDOW,
            start=(
                tests.helpers.factories.peri_scribe.show_latencies.evidence.NOW
                + datetime.timedelta(seconds=start)
            ),
        )
        evidence = peri_scribe.show_latencies.runs.read(tmp_path / "logs", window)
        assert peri_scribe.show_latencies.perimeters.latencies(
            tmp_path,
            evidence,
            window,
        ) == (4 * units.seconds,)


def test_latencies_orders_consumption_by_write_time_instead_of_command_finish(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    publication = (
        tests.helpers.factories.peri_scribe.show_latencies.evidence.publication(
            1,
        )
    )
    monkeypatch.setattr(
        peri_scribe.show_latencies.sources,
        "read_versions",
        unittest.mock.Mock(return_value=(publication,)),
    )
    now = tests.helpers.factories.peri_scribe.show_latencies.evidence.NOW
    evidence = peri_scribe.show_latencies.runs.Evidence(
        runs=(),
        snapshots={publication.source_file: publication.published},
        kmz_writes=tuple(
            peri_scribe.show_latencies.runs.KmzWrite(
                written=now + datetime.timedelta(seconds=written),
                geography=now + datetime.timedelta(seconds=geography),
                finished=now + datetime.timedelta(seconds=finished),
            )
            for written, geography, finished in ((29, 25, 30), (4, 2, 100))
        ),
    )
    assert peri_scribe.show_latencies.perimeters.latencies(
        tmp_path,
        evidence,
        tests.helpers.factories.peri_scribe.show_latencies.evidence.WINDOW,
    ) == (99 * units.seconds,)


@pytest.mark.parametrize("next_identifier", ["one", "retry"])
def test_latencies_does_not_reassign_polygons_written_by_an_interrupted_run(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    next_identifier: str,
) -> None:
    publication = (
        tests.helpers.factories.peri_scribe.show_latencies.evidence.publication(
            1,
        )
    )
    monkeypatch.setattr(
        peri_scribe.show_latencies.sources,
        "read_versions",
        unittest.mock.Mock(return_value=(publication,)),
    )
    tests.helpers.factories.peri_scribe.show_latencies.evidence.write_log(
        tmp_path / "logs/2026-09.jsonl",
        [
            tests.helpers.factories.peri_scribe.show_latencies.evidence.record(
                "Starting command",
            ),
            tests.helpers.factories.peri_scribe.show_latencies.evidence.record(
                "Finished phase",
                1,
                phase="write-snapshot",
                feed="feed",
                path=f"/remote/sources/{publication.source_file}",
                status="completed",
            ),
            tests.helpers.factories.peri_scribe.show_latencies.evidence.record(
                "Starting phase",
                2,
                phase_path="geography",
            ),
            tests.helpers.factories.peri_scribe.show_latencies.evidence.record(
                "Finished phase",
                3,
                phase_path="geography",
                status="completed",
            ),
            tests.helpers.factories.peri_scribe.show_latencies.evidence.record(
                "Finished phase",
                4,
                phase_path="kmz.serialize-and-write-kmz",
                status="completed",
            ),
            tests.helpers.factories.peri_scribe.show_latencies.evidence.record(
                "Starting command",
                20,
                run_id=next_identifier,
            ),
            tests.helpers.factories.peri_scribe.show_latencies.evidence.record(
                "Finished phase",
                29,
                run_id=next_identifier,
                phase_path="kmz.serialize-and-write-kmz",
                status="completed",
            ),
            tests.helpers.factories.peri_scribe.show_latencies.evidence.record(
                "Finished command",
                30,
                run_id=next_identifier,
                duration={"value": 10, "units": "second"},
            ),
        ],
    )
    evidence = peri_scribe.show_latencies.runs.read(
        tmp_path / "logs",
        tests.helpers.factories.peri_scribe.show_latencies.evidence.WINDOW,
    )
    assert (
        peri_scribe.show_latencies.perimeters.latencies(
            tmp_path,
            evidence,
            tests.helpers.factories.peri_scribe.show_latencies.evidence.WINDOW,
        )
        == ()
    )
