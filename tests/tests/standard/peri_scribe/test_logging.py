"""Logging configuration and serialization tests for consistent diagnostics."""

from __future__ import annotations

import compression.zstd
import concurrent.futures
import datetime
import functools
import json
import logging
import pathlib
import typing
import unittest.mock
import zoneinfo

import click
import pyproj
import pytest
import structlog
import time_machine

import peri_scribe.logging
import tests.helpers.doubles.errors
import tests.helpers.factories.peri_scribe.logging
from peri_scribe.units import units


def test_configure_logging_filters_below_configured_level() -> None:
    with structlog.testing.capture_logs():
        peri_scribe.logging.configure_logging("warning")
        logger = structlog.get_logger()
        assert not logger.is_enabled_for(logging.DEBUG)
        assert not logger.is_enabled_for(logging.INFO)
        assert logger.is_enabled_for(logging.WARNING)
        assert logger.is_enabled_for(logging.ERROR)


def test_configure_logging_debug_level_enables_every_level() -> None:
    with structlog.testing.capture_logs():
        peri_scribe.logging.configure_logging()
        logger = structlog.get_logger()
        assert logger.is_enabled_for(logging.DEBUG)
        assert logger.is_enabled_for(logging.CRITICAL)


def test_configure_logging_writes_to_stderr(capsys: pytest.CaptureFixture[str]) -> None:
    peri_scribe.logging.configure_logging("info")
    structlog.get_logger().info("Source fetched", source="evacuations")
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Source fetched" in captured.err
    assert "evacuations" in captured.err


@pytest.mark.parametrize("kind", ["command", "phase"])
def test_log_execution_emits_failures_when_both_destinations_require_error(
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
    kind: typing.Literal["command", "phase"],
) -> None:
    peri_scribe.logging.configure_logging("error", "error", year_directory=tmp_path)
    error = RuntimeError("execution failed")
    with (
        pytest.raises(RuntimeError, match="execution failed"),
        peri_scribe.logging.log_execution(kind, "fetch"),
    ):
        raise error
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Starting" not in captured.err
    assert f"Finished {kind}" in captured.err
    path = next((tmp_path / "logs").glob("*.jsonl"))
    entry = json.loads(path.read_text())
    assert entry["level"] == "error"
    assert entry["status"] == "failed"
    assert entry[kind] == "fetch"
    assert entry["duration"]["units"] == str(units.seconds)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (pathlib.Path("fires.json"), "fires.json"),
        (tests.helpers.factories.peri_scribe.logging.LogStatus.SKIPPED, "skipped"),
        (
            tests.helpers.factories.peri_scribe.logging.LogDetails(
                path=pathlib.Path("fires.json"),
                status=tests.helpers.factories.peri_scribe.logging.LogStatus.SKIPPED,
            ),
            {"path": "fires.json", "status": "skipped"},
        ),
        (datetime.timedelta(hours=6), {"value": 21600.0, "units": units.seconds}),
        (pyproj.CRS.from_epsg(4326), "EPSG:4326"),
        (
            datetime.datetime(2026, 9, 13, tzinfo=datetime.UTC),
            "2026-09-13T00:00:00+00:00",
        ),
        (datetime.date(2026, 9, 13), "2026-09-13"),
        (datetime.time(12, 30), "12:30:00"),
        (123.45 * units.seconds, {"value": 123.45, "units": units.seconds}),
        (25.0 * units.acres, {"value": 25.0, "units": units.acres}),
        (2.0 * units.kilometers, {"value": 2.0, "units": units.kilometers}),
        ((pathlib.Path("one.gpkg"), None, True), ["one.gpkg", None, True]),
        ({"score", "fetch", "reports"}, ["fetch", "reports", "score"]),
        (frozenset({"score", "fetch", "reports"}), ["fetch", "reports", "score"]),
        ({10, 2, -3}, [-3, 2, 10]),
        (frozenset({10, 2, -3}), [-3, 2, 10]),
        ({pathlib.Path("b.gpkg"), pathlib.Path("a.gpkg")}, ["a.gpkg", "b.gpkg"]),
        ({None, "fetch", 10}, ["fetch", 10, None]),
        (frozenset({None, "fetch", 10}), ["fetch", 10, None]),
        ({frozenset({"z", "y"}), frozenset({"b", "a"})}, [["a", "b"], ["y", "z"]]),
        (("score", "fetch"), ["score", "fetch"]),
        (["score", "fetch"], ["score", "fetch"]),
        (set(), []),
        (
            {"nested": [pathlib.Path("two.gpkg"), 2.0 * units.seconds]},
            {"nested": ["two.gpkg", {"value": 2.0, "units": units.seconds}]},
        ),
    ],
)
def test_log_value_produces_json_values(value: object, expected: object) -> None:
    assert json.loads(json.dumps(peri_scribe.logging.log_value(value))) == expected


def test_serialize_log_values_preserves_exception_metadata() -> None:
    error = ValueError("boom")
    exception_info = (ValueError, error, None)
    event = {"event": "Failure", "exc_info": exception_info}
    result = peri_scribe.logging.serialize_log_values(None, "exception", event)
    assert result["exc_info"] is exception_info


def test_serialize_log_values_preserves_original_collections() -> None:
    path = pathlib.Path("fires.json")
    paths = [path]
    parameters = {"paths": paths}
    event = {"parameters": parameters}
    result = peri_scribe.logging.serialize_log_values(None, "info", event)
    assert result == {"parameters": {"paths": ["fires.json"]}}
    assert parameters == {"paths": [path]}
    assert event["parameters"] is parameters
    assert parameters["paths"] is paths


@pytest.mark.parametrize("json_output", [False, True])
def test_configure_logging_normalizes_values_for_each_renderer(
    capsys: pytest.CaptureFixture[str],
    *,
    json_output: bool,
) -> None:
    peri_scribe.logging.configure_logging("info")
    if json_output:
        structlog.configure(
            processors=[
                *structlog.get_config()["processors"][:-1],
                structlog.processors.JSONRenderer(default=None, allow_nan=False),
            ],
        )
    structlog.get_logger().info(
        "Finished",
        path=pathlib.Path("fires.json"),
        duration=123.45 * units.seconds,
    )
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "PosixPath" not in captured.err
    assert "Quantity" not in captured.err
    assert "fires.json" in captured.err
    assert "123.45" in captured.err
    assert str(units.seconds) in captured.err
    if json_output:
        entry = json.loads(captured.err)
        assert entry["path"] == "fires.json"
        assert entry["duration"] == {"value": 123.45, "units": units.seconds}
        assert "duration_units" not in entry


@pytest.mark.parametrize(
    ("stderr_level", "file_level", "stderr_events", "file_events"),
    [
        ("warning", "debug", ["Warning event"], ["Debug event", "Warning event"]),
        ("debug", "warning", ["Debug event", "Warning event"], ["Warning event"]),
    ],
)
def test_configure_logging_filters_each_destination_independently(
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
    *,
    stderr_level: str,
    file_level: str,
    stderr_events: list[str],
    file_events: list[str],
) -> None:
    peri_scribe.logging.configure_logging(
        stderr_level,
        file_level,
        year_directory=tmp_path,
    )
    logger = structlog.get_logger()
    logger.debug("Debug event")
    logger.warning("Warning event")
    captured = capsys.readouterr()
    assert captured.out == ""
    assert [
        event for event in ("Debug event", "Warning event") if event in captured.err
    ] == stderr_events
    path = next((tmp_path / "logs").glob("*.jsonl"))
    entries = [json.loads(line) for line in path.read_text().splitlines()]
    assert [entry["event"] for entry in entries] == file_events


def test_configure_logging_preserves_exception_details_in_both_destinations(
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    peri_scribe.logging.configure_logging(year_directory=tmp_path)
    error = ValueError("fetch failed")
    try:
        raise error
    except ValueError:
        structlog.get_logger().exception("Could not fetch", path=tmp_path)
    captured = capsys.readouterr()
    assert "ValueError: fetch failed" in captured.err
    assert "Traceback (most recent call last)" in captured.err
    path = next((tmp_path / "logs").glob("*.jsonl"))
    entry = json.loads(path.read_text())
    assert entry["path"] == str(tmp_path)
    assert entry["event"] == "Could not fetch"
    assert entry["level"] == "error"
    assert "ValueError: fetch failed" in entry["exception"]
    assert "Traceback (most recent call last)" in entry["exception"]
    assert "exc_info" not in entry


@pytest.mark.parametrize(
    ("before", "after"),
    [
        (datetime.datetime(2026, 7, 31, 23, 59, 59), datetime.datetime(2026, 8, 1)),
        (datetime.datetime(2026, 12, 31, 23, 59, 59), datetime.datetime(2027, 1, 1)),
        (datetime.datetime(2028, 2, 29, 23, 59, 59), datetime.datetime(2028, 3, 1)),
    ],
)
def test_configure_logging_rotates_at_the_local_month_boundary(
    tmp_path: pathlib.Path,
    before: datetime.datetime,
    after: datetime.datetime,
) -> None:
    local_zone = zoneinfo.ZoneInfo("America/Los_Angeles")
    peri_scribe.logging.configure_logging(year_directory=tmp_path)
    logger = structlog.get_logger()
    with time_machine.travel(before.replace(tzinfo=local_zone), tick=False):
        logger.debug("Before midnight", duration=1.25 * units.seconds)
        logger.info("Still the same month")
    old_log = tmp_path / "logs" / before.strftime("%Y-%m.jsonl")
    previous = old_log.read_text()
    assert [json.loads(line)["event"] for line in previous.splitlines()] == [
        "Before midnight",
        "Still the same month",
    ]
    assert not old_log.with_suffix(".jsonl.zst").exists()
    with time_machine.travel(after.replace(tzinfo=local_zone), tick=False):
        logger.info("After midnight")
    assert not old_log.exists()
    with compression.zstd.open(old_log.with_suffix(".jsonl.zst"), "rt") as archive:
        assert archive.read() == previous
    path = tmp_path / "logs" / after.strftime("%Y-%m.jsonl")
    entry = json.loads(path.read_text())
    assert entry["event"] == "After midnight"
    assert entry["timestamp"] == after.replace(tzinfo=local_zone).strftime(
        "%Y-%m-%dT%H:%M:%S%z",
    )


def test_configure_logging_rotates_older_months_after_a_restart(
    tmp_path: pathlib.Path,
) -> None:
    directory = tmp_path / "logs"
    directory.mkdir()
    older = {
        "2026-01.jsonl": '{"event":"January"}\n',
        "2026-02.jsonl": '{"event":"February"}\n',
    }
    untouched = {
        "2026-05.jsonl": "future",
        "2026-13.jsonl": "invalid",
        "notes.jsonl": "notes",
    }
    for name, content in {**older, **untouched}.items():
        (directory / name).write_text(content)
    with time_machine.travel(datetime.datetime(2026, 4, 15, tzinfo=datetime.UTC)):
        peri_scribe.logging.configure_logging(year_directory=tmp_path)
        structlog.get_logger().info("Restarted")
    for name, content in older.items():
        assert not (directory / name).exists()
        with compression.zstd.open(directory / f"{name}.zst", "rt") as archive:
            assert archive.read() == content
    for name, content in untouched.items():
        assert (directory / name).read_text() == content


def test_compress_log_uses_zstd_level_19(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "2026-01.jsonl"
    path.write_text('{"event":"Archived"}\n')
    with unittest.mock.patch.object(
        compression.zstd,
        "open",
        wraps=compression.zstd.open,
    ) as compressor:
        peri_scribe.logging.compress_log(path)
    expected_level = 19
    assert compressor.call_args.kwargs["level"] == expected_level
    assert not path.exists()
    with compression.zstd.open(path.with_suffix(".jsonl.zst"), "rt") as archive:
        assert archive.read() == '{"event":"Archived"}\n'


def test_compress_log_preserves_an_existing_archive(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "2026-01.jsonl"
    path.write_text("original\n")
    peri_scribe.logging.compress_log(path)
    path.write_text("late arrival\n")
    peri_scribe.logging.compress_log(path)
    with compression.zstd.open(path.with_suffix(".jsonl.zst"), "rt") as archive:
        assert archive.read() == "original\nlate arrival\n"


def test_compress_log_preserves_logs_if_compression_fails(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "2026-01.jsonl"
    path.write_text("original\n")
    peri_scribe.logging.compress_log(path)
    archive = path.with_suffix(".jsonl.zst")
    original = archive.read_bytes()
    path.write_text("late arrival\n")
    monkeypatch.setattr(
        peri_scribe.logging.shutil,
        "copyfileobj",
        tests.helpers.doubles.errors.raising_stub(OSError("compression failed")),
    )
    with pytest.raises(OSError, match="compression failed"):
        peri_scribe.logging.compress_log(path)
    assert path.read_text() == "late arrival\n"
    assert archive.read_bytes() == original
    assert sorted(tmp_path.iterdir()) == [path, archive]


def test_append_monthly_log_serializes_overlapping_writes_and_rotation(
    tmp_path: pathlib.Path,
) -> None:
    old_log = tmp_path / "2000-01.jsonl"
    old_log.write_text('{"event":"Older month"}\n')
    entries = [
        json.dumps({"event": f"Writer {index}", "details": "🔥\n" * 5000})
        for index in range(12)
    ]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        list(
            executor.map(
                functools.partial(peri_scribe.logging.append_monthly_log, tmp_path),
                entries,
            ),
        )
    path = next(tmp_path.glob("*.jsonl"))
    assert sorted(path.read_text().splitlines()) == sorted(entries)
    with compression.zstd.open(old_log.with_suffix(".jsonl.zst"), "rt") as archive:
        assert json.loads(archive.read()) == {"event": "Older month"}


def test_command_file_logging_leaves_commands_without_a_year_on_stderr() -> None:
    context = click.Context(click.Command("display"))
    configuration = structlog.get_config()
    with peri_scribe.logging.command_file_logging(context):
        assert structlog.get_config() == configuration
    assert structlog.get_config() == configuration
