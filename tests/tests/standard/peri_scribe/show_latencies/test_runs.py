"""Run metrics preserve failures, publication gates, and cross-file boundaries."""

from __future__ import annotations

import datetime
import json
import pathlib
import unittest.mock

import pytest

import peri_scribe.show_latencies.runs
import tests.helpers.factories.peri_scribe.show_latencies.evidence
from measurement_units import units


@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        ({"event": "Starting command"}, True),
        ({"event": "Finished command"}, True),
        ({"event": "Finished command detail"}, False),
        ({"message": "Finished command"}, False),
        ({"event": "Starting phase", "phase_path": "geography"}, True),
        ({"event": "Finished phase", "phase_path": "geography"}, True),
        (
            {"event": "Finished phase", "phase_path": "kmz.serialize-and-write-kmz"},
            True,
        ),
        ({"event": "Finished phase", "phase": "write-snapshot"}, True),
        ({"event": "Finished phase", "phase": "write-snapshot-details"}, False),
        ({"event": "Starting phase", "phase_path": "fetch"}, False),
        ({"event": "Debug", "phase_path": "geography"}, False),
    ],
)
def test_includes_evidence_selects_only_recognized_event_and_phase_names(
    fields: dict[str, str],
    *,
    expected: bool,
) -> None:
    assert (
        peri_scribe.show_latencies.runs.includes_evidence(json.dumps(fields).encode())
        is expected
    )


def test_read_counts_gate_stops_and_failures_but_not_incomplete_runs(
    tmp_path: pathlib.Path,
) -> None:
    tests.helpers.factories.peri_scribe.show_latencies.evidence.write_log(
        tmp_path / "2026-09.jsonl",
        [
            tests.helpers.factories.peri_scribe.show_latencies.evidence.record(
                "Starting command",
            ),
            tests.helpers.factories.peri_scribe.show_latencies.evidence.record(
                "Publication gate skipped",
                2,
            ),
            tests.helpers.factories.peri_scribe.show_latencies.evidence.record(
                "Finished command",
                4,
                duration={"value": 4, "units": "second"},
            ),
            tests.helpers.factories.peri_scribe.show_latencies.evidence.record(
                "Starting command",
                5,
                run_id="two",
            ),
            tests.helpers.factories.peri_scribe.show_latencies.evidence.record(
                "Finished command",
                8,
                run_id="two",
                status="failed",
                duration={"value": 0.05, "units": "minute"},
            ),
            tests.helpers.factories.peri_scribe.show_latencies.evidence.record(
                "Starting command",
                9,
                run_id="unfinished",
            ),
        ],
    )
    result = peri_scribe.show_latencies.runs.read(
        tmp_path,
        tests.helpers.factories.peri_scribe.show_latencies.evidence.WINDOW,
    )
    assert [run.duration for run in result.runs] == [
        4 * units.seconds,
        3 * units.seconds,
    ]
    assert not any(run.produced_kmz for run in result.runs)


def test_read_uses_archives_when_the_window_reaches_before_plain_logs(
    tmp_path: pathlib.Path,
) -> None:
    tests.helpers.factories.peri_scribe.show_latencies.evidence.write_log(
        tmp_path / "2026-08.jsonl.zst",
        [
            tests.helpers.factories.peri_scribe.show_latencies.evidence.record(
                "Starting command",
                -86400,
            ),
            tests.helpers.factories.peri_scribe.show_latencies.evidence.record(
                "Finished command",
                -86390,
                duration={"value": 10, "units": "second"},
            ),
        ],
    )
    tests.helpers.factories.peri_scribe.show_latencies.evidence.write_log(
        tmp_path / "2026-09.jsonl",
        [
            tests.helpers.factories.peri_scribe.show_latencies.evidence.record(
                "Starting command",
            ),
            tests.helpers.factories.peri_scribe.show_latencies.evidence.record(
                "Finished command",
                5,
                duration={"value": 5, "units": "second"},
            ),
        ],
    )
    window = peri_scribe.show_latencies.runs.Window(
        start=tests.helpers.factories.peri_scribe.show_latencies.evidence.NOW
        - datetime.timedelta(days=2),
        end=tests.helpers.factories.peri_scribe.show_latencies.evidence.WINDOW.end,
    )
    result = peri_scribe.show_latencies.runs.read(tmp_path, window)
    assert [run.duration.m_as("seconds") for run in result.runs] == [10, 5]


def test_read_tracks_source_capture_and_kmz_through_report_failure(
    tmp_path: pathlib.Path,
) -> None:
    tests.helpers.factories.peri_scribe.show_latencies.evidence.write_log(
        tmp_path / "2026-09.jsonl",
        [
            tests.helpers.factories.peri_scribe.show_latencies.evidence.record(
                "Starting command",
            ),
            tests.helpers.factories.peri_scribe.show_latencies.evidence.record(
                "Finished phase",
                10,
                phase="write-snapshot",
                feed="feed",
                path="/remote/sources/feed/snapshot.gpkg",
                status="completed",
            ),
            tests.helpers.factories.peri_scribe.show_latencies.evidence.record(
                "Finished phase",
                11,
                phase="write-snapshot",
                feed="feed",
                path="/remote/sources/feed/snapshot.gpkg",
                status="completed",
            ),
            tests.helpers.factories.peri_scribe.show_latencies.evidence.record(
                "Starting phase",
                20,
                phase_path="geography",
            ),
            tests.helpers.factories.peri_scribe.show_latencies.evidence.record(
                "Finished phase",
                30,
                phase_path="geography",
                status="completed",
            ),
            tests.helpers.factories.peri_scribe.show_latencies.evidence.record(
                "Finished phase",
                40,
                phase_path="kmz.serialize-and-write-kmz",
                status="completed",
            ),
            tests.helpers.factories.peri_scribe.show_latencies.evidence.record(
                "Finished command",
                50,
                status="failed",
                duration={"value": 50, "units": "second"},
            ),
            tests.helpers.factories.peri_scribe.show_latencies.evidence.record(
                "Starting command",
                60,
                run_id="retry",
            ),
            tests.helpers.factories.peri_scribe.show_latencies.evidence.record(
                "Finished phase",
                70,
                run_id="retry",
                phase_path="kmz.serialize-and-write-kmz",
                status="completed",
            ),
            tests.helpers.factories.peri_scribe.show_latencies.evidence.record(
                "Finished command",
                80,
                run_id="retry",
                duration={"value": 20, "units": "second"},
            ),
        ],
    )
    result = peri_scribe.show_latencies.runs.read(
        tmp_path,
        tests.helpers.factories.peri_scribe.show_latencies.evidence.WINDOW,
    )
    assert all(run.produced_kmz for run in result.runs)
    assert all(
        run.geography
        == tests.helpers.factories.peri_scribe.show_latencies.evidence.NOW
        + datetime.timedelta(seconds=20)
        for run in result.runs
    )
    assert result.snapshots == {
        "feed/snapshot.gpkg": (
            tests.helpers.factories.peri_scribe.show_latencies.evidence.NOW
            + datetime.timedelta(seconds=10)
        ),
    }
    assert (
        result.runs[0].finished
        == tests.helpers.factories.peri_scribe.show_latencies.evidence.NOW
        + datetime.timedelta(seconds=50)
    )


def test_read_retains_crossing_start_but_excludes_unfinished_and_unusable_records(
    tmp_path: pathlib.Path,
) -> None:
    tests.helpers.factories.peri_scribe.show_latencies.evidence.write_log(
        tmp_path / "2026-09.jsonl",
        [
            tests.helpers.factories.peri_scribe.show_latencies.evidence.record(
                "Starting command",
                -10,
            ),
            tests.helpers.factories.peri_scribe.show_latencies.evidence.record(
                "Finished command",
                2,
                duration={"value": 12, "units": "second"},
            ),
            tests.helpers.factories.peri_scribe.show_latencies.evidence.record(
                "Finished command",
                3,
            ),
            tests.helpers.factories.peri_scribe.show_latencies.evidence.record(
                "Finished command",
                4,
                duration={"value": -1, "units": "second"},
            ),
            tests.helpers.factories.peri_scribe.show_latencies.evidence.record(
                "Starting phase",
                5,
                phase_path="fetch",
            ),
            tests.helpers.factories.peri_scribe.show_latencies.evidence.record(
                "Finished phase",
                6,
                phase="write-snapshot",
                feed="feed",
                path="not-a-source",
                status="completed",
            ),
            tests.helpers.factories.peri_scribe.show_latencies.evidence.record(
                "Finished phase",
                7,
                status="failed",
            ),
            tests.helpers.factories.peri_scribe.show_latencies.evidence.record(
                "Finished command",
                8,
                command="other",
            ),
            tests.helpers.factories.peri_scribe.show_latencies.evidence.record(
                "Starting command",
                9,
                timestamp=None,
            ),
            tests.helpers.factories.peri_scribe.show_latencies.evidence.record(
                "Starting command",
                10,
            ),
            tests.helpers.factories.peri_scribe.show_latencies.evidence.record(
                "Finished command",
                3601,
                duration={"value": 3591, "units": "second"},
            ),
        ],
    )
    result = peri_scribe.show_latencies.runs.read(
        tmp_path,
        tests.helpers.factories.peri_scribe.show_latencies.evidence.WINDOW,
    )
    assert len(result.runs) == 1
    assert result.runs[0].duration == 12 * units.seconds
    assert result.runs[0].started == (
        tests.helpers.factories.peri_scribe.show_latencies.evidence.NOW
        - datetime.timedelta(seconds=10)
    )


def test_records_prunes_other_months_and_ignores_unstructured_records(
    tmp_path: pathlib.Path,
) -> None:
    (tmp_path / "2025-12.jsonl.zst").write_bytes(b"bad archive")
    (tmp_path / "2026-09.jsonl").write_text(
        '[{"event":"Starting command"}]\n{"event":"unrelated"}\n',
    )
    assert (
        list(
            peri_scribe.show_latencies.runs.records(
                tmp_path,
                tests.helpers.factories.peri_scribe.show_latencies.evidence.WINDOW,
            ),
        )
        == []
    )


def test_records_deserializes_only_eligible_suffix(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "2026-09.jsonl"
    recent = tests.helpers.factories.peri_scribe.show_latencies.evidence.record(
        "Starting command",
    )
    path.write_text(
        '{"timestamp":"2026-08-31","event":"Starting command","broken":}\n' * 10000
        + json.dumps(recent)
        + "\n",
    )
    parser = unittest.mock.Mock(wraps=json.loads)
    monkeypatch.setattr(json, "loads", parser)
    assert list(
        peri_scribe.show_latencies.runs.records(
            tmp_path,
            tests.helpers.factories.peri_scribe.show_latencies.evidence.WINDOW,
        ),
    ) == [recent]
    parser.assert_called_once()


def test_read_avoids_archives_when_plain_logs_already_cover_the_window(
    tmp_path: pathlib.Path,
) -> None:
    (tmp_path / "2026-08.jsonl.zst").write_bytes(b"unneeded archive must stay unopened")
    tests.helpers.factories.peri_scribe.show_latencies.evidence.write_log(
        tmp_path / "2026-09.jsonl",
        [
            tests.helpers.factories.peri_scribe.show_latencies.evidence.record(
                "Starting command",
            ),
            tests.helpers.factories.peri_scribe.show_latencies.evidence.record(
                "Finished command",
                5,
                duration={"value": 5, "units": "second"},
            ),
        ],
    )
    result = peri_scribe.show_latencies.runs.read(
        tmp_path,
        tests.helpers.factories.peri_scribe.show_latencies.evidence.WINDOW,
    )
    assert [run.duration.m_as("seconds") for run in result.runs] == [5]


@pytest.mark.parametrize("compressed", [True, False])
def test_read_recovers_crossing_command_phases_from_the_previous_month(
    tmp_path: pathlib.Path,
    *,
    compressed: bool,
) -> None:
    earlier = tmp_path / ("2026-08.jsonl.zst" if compressed else "2026-08.jsonl")
    tests.helpers.factories.peri_scribe.show_latencies.evidence.write_log(
        earlier,
        [
            tests.helpers.factories.peri_scribe.show_latencies.evidence.record(
                "Starting command",
                -43210,
            ),
            tests.helpers.factories.peri_scribe.show_latencies.evidence.record(
                "Finished phase",
                -43209,
                phase="write-snapshot",
                feed="feed",
                path="/remote/sources/feed/snapshot.gpkg",
                status="completed",
            ),
            tests.helpers.factories.peri_scribe.show_latencies.evidence.record(
                "Starting phase",
                -43205,
                phase_path="geography",
            ),
            tests.helpers.factories.peri_scribe.show_latencies.evidence.record(
                "Finished phase",
                -43204,
                phase_path="geography",
                status="completed",
            ),
            tests.helpers.factories.peri_scribe.show_latencies.evidence.record(
                "Finished phase",
                -43201,
                phase_path="kmz.serialize-and-write-kmz",
                status="completed",
            ),
        ],
    )
    tests.helpers.factories.peri_scribe.show_latencies.evidence.write_log(
        tmp_path / "2026-09.jsonl",
        [
            tests.helpers.factories.peri_scribe.show_latencies.evidence.record(
                "Finished command",
                10,
                duration={"value": 43220, "units": "second"},
            ),
        ],
    )
    evidence = peri_scribe.show_latencies.runs.read(
        tmp_path,
        tests.helpers.factories.peri_scribe.show_latencies.evidence.WINDOW,
    )
    assert len(evidence.runs) == 1
    run = evidence.runs[0]
    assert run.produced_kmz
    assert run.geography == (
        tests.helpers.factories.peri_scribe.show_latencies.evidence.NOW
        - datetime.timedelta(seconds=43205)
    )
    assert evidence.snapshots == {
        "feed/snapshot.gpkg": (
            tests.helpers.factories.peri_scribe.show_latencies.evidence.NOW
            - datetime.timedelta(seconds=43209)
        ),
    }


def test_read_recovers_precise_start_despite_rounded_completion_duration(
    tmp_path: pathlib.Path,
) -> None:
    tests.helpers.factories.peri_scribe.show_latencies.evidence.write_log(
        tmp_path / "2026-09.jsonl",
        [
            tests.helpers.factories.peri_scribe.show_latencies.evidence.record(
                "Starting command",
                -10,
            ),
            tests.helpers.factories.peri_scribe.show_latencies.evidence.record(
                "Starting phase",
                -9.75,
                phase_path="geography",
            ),
            tests.helpers.factories.peri_scribe.show_latencies.evidence.record(
                "Finished command",
                2,
                duration={"value": 11.5, "units": "second"},
            ),
        ],
    )
    evidence = peri_scribe.show_latencies.runs.read(
        tmp_path,
        tests.helpers.factories.peri_scribe.show_latencies.evidence.WINDOW,
    )
    assert evidence.runs[0].started == (
        tests.helpers.factories.peri_scribe.show_latencies.evidence.NOW
        - datetime.timedelta(seconds=10)
    )
    assert evidence.runs[0].geography == (
        tests.helpers.factories.peri_scribe.show_latencies.evidence.NOW
        - datetime.timedelta(seconds=9.75)
    )


def test_read_recovers_missing_start_when_rounded_duration_places_it_in_window(
    tmp_path: pathlib.Path,
) -> None:
    tests.helpers.factories.peri_scribe.show_latencies.evidence.write_log(
        tmp_path / "2026-09.jsonl",
        [
            tests.helpers.factories.peri_scribe.show_latencies.evidence.record(
                "Starting command",
                -0.4,
            ),
            tests.helpers.factories.peri_scribe.show_latencies.evidence.record(
                "Starting phase",
                -0.3,
                phase_path="geography",
            ),
            tests.helpers.factories.peri_scribe.show_latencies.evidence.record(
                "Finished phase",
                -0.1,
                phase_path="kmz.serialize-and-write-kmz",
                status="completed",
            ),
            tests.helpers.factories.peri_scribe.show_latencies.evidence.record(
                "Finished command",
                1.1,
                duration={"value": 1, "units": "second"},
            ),
        ],
    )
    evidence = peri_scribe.show_latencies.runs.read(
        tmp_path,
        tests.helpers.factories.peri_scribe.show_latencies.evidence.WINDOW,
    )
    assert len(evidence.runs) == 1
    assert evidence.runs[0].started == (
        tests.helpers.factories.peri_scribe.show_latencies.evidence.NOW
        - datetime.timedelta(seconds=0.4)
    )
    assert evidence.runs[0].geography == (
        tests.helpers.factories.peri_scribe.show_latencies.evidence.NOW
        - datetime.timedelta(seconds=0.3)
    )
    assert evidence.runs[0].produced_kmz


@pytest.mark.parametrize(
    ("path", "year", "expected"),
    [
        ("/copy/2026/sources/feed/file.gpkg", "2026", "feed/file.gpkg"),
        ("/copy/2025/sources/feed/file.gpkg", "2026", None),
        ("sources/feed/file.gpkg", "2026", None),
        ("/copy/sources/feed/file.gpkg", None, "feed/file.gpkg"),
        ("/copy/2026/sources/another/file.gpkg", "2026", None),
        ("", "2026", None),
    ],
)
def test_relative_snapshot_requires_the_year_and_feed_source_directory(
    path: str,
    year: str | None,
    expected: str | None,
) -> None:
    assert (
        peri_scribe.show_latencies.runs.relative_snapshot(
            {"path": path, "feed": "feed"},
            year,
        )
        == expected
    )


def test_read_identifies_year_source_directory_after_an_ancestor_named_sources(
    tmp_path: pathlib.Path,
) -> None:
    directory = tmp_path / "2026/logs"
    tests.helpers.factories.peri_scribe.show_latencies.evidence.write_log(
        directory / "2026-09.jsonl",
        [
            tests.helpers.factories.peri_scribe.show_latencies.evidence.record(
                "Finished phase",
                1,
                phase="write-snapshot",
                feed="feed",
                path="/srv/sources/application/data/2026/sources/feed/snapshot.gpkg",
                status="completed",
            ),
            tests.helpers.factories.peri_scribe.show_latencies.evidence.record(
                "Finished phase",
                2,
                phase="write-snapshot",
                feed="feed",
                path="/srv/sources/application/unrelated.gpkg",
                status="completed",
            ),
        ],
    )
    evidence = peri_scribe.show_latencies.runs.read(
        directory,
        tests.helpers.factories.peri_scribe.show_latencies.evidence.WINDOW,
    )
    assert evidence.snapshots == {
        "feed/snapshot.gpkg": (
            tests.helpers.factories.peri_scribe.show_latencies.evidence.NOW
            + datetime.timedelta(seconds=1)
        ),
    }
