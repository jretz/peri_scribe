"""CLI entrypoint tests for peri_scribe.main."""

from __future__ import annotations

import datetime
import importlib.metadata
import itertools
import json
import pathlib
import typing

import click
import click.testing
import pytest
import structlog
import structlog.testing
import time_machine

import peri_scribe.exceptions
import peri_scribe.fires.differential
import peri_scribe.fires.index
import peri_scribe.fires.scores
import peri_scribe.kml.colormap
import peri_scribe.logging
import peri_scribe.main
import peri_scribe.output
import peri_scribe.pipeline_state
import peri_scribe.publication
import peri_scribe.report.gathering
import peri_scribe.report.markdown
import peri_scribe.sources.digests
import peri_scribe.sources.external_data
import peri_scribe.sources.external_sources
import peri_scribe.sources.fetching
import peri_scribe.sources.full_fetch_state
import peri_scribe.sources.snapshots
import peri_scribe.sources.validation
import tests.helpers.doubles.errors
import tests.helpers.doubles.peri_scribe.main
import tests.helpers.doubles.peri_scribe.main_run
import tests.helpers.doubles.peri_scribe.main_show_colormap
import tests.helpers.doubles.peri_scribe.main_source
import tests.helpers.doubles.peri_scribe.main_write_reports
import tests.helpers.factories.peri_scribe.publication
import tests.helpers.factories.peri_scribe.sources.snapshots
import tests.helpers.peri_scribe.main
import tests.helpers.peri_scribe.main_publication
from peri_scribe.units import units


def test_cli_help(runner: click.testing.CliRunner) -> None:
    result = runner.invoke(peri_scribe.main.cli, ["--help"])
    assert result.exit_code == 0
    assert "systematic gathering and symbolization of fire geography" in result.output


@pytest.mark.parametrize("option", ["--stderr-log-level", "--file-log-level"])
def test_cli_invalid_log_level(runner: click.testing.CliRunner, option: str) -> None:
    result = runner.invoke(peri_scribe.main.cli, [option, "verbose"])
    assert (
        result.exit_code == tests.helpers.peri_scribe.main.CLICK_USAGE_ERROR_EXIT_CODE
    )
    assert f"Invalid value for '{option}'" in result.output


def test_cli_requires_subcommand(runner: click.testing.CliRunner) -> None:
    result = runner.invoke(peri_scribe.main.cli, [])
    assert (
        result.exit_code == tests.helpers.peri_scribe.main.CLICK_USAGE_ERROR_EXIT_CODE
    )
    assert "Commands:" in result.output
    assert "run" in result.output


def test_version_prints_installed_version(runner: click.testing.CliRunner) -> None:
    result = runner.invoke(peri_scribe.main.cli, ["version"])
    assert result.exit_code == 0
    assert (
        result.stdout.strip()
        == f"peri_scribe v{importlib.metadata.version('peri_scribe')}"
    )
    assert result.stderr == ""


def test_version_looks_up_the_distribution_named_for_this_package(
    runner: click.testing.CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    looked_up_distributions: list[str] = []

    record_lookup = tests.helpers.doubles.peri_scribe.main.make_version_lookup_recorder(
        looked_up_distributions=looked_up_distributions,
    )

    monkeypatch.setattr(peri_scribe.main, "__package__", "some_other_package")
    monkeypatch.setattr(importlib.metadata, "version", record_lookup)
    result = runner.invoke(peri_scribe.main.cli, ["version"])
    assert result.exit_code == 0
    assert looked_up_distributions == ["some_other_package"]
    assert result.stdout.strip() == "some_other_package v1.2.3"
    assert result.stderr == ""


@pytest.mark.usefixtures("current_year")
@pytest.mark.parametrize(
    ("arguments", "parameters"),
    [(["run", "--list-stages"], {"list_stages": True}), (["validate-sources"], {})],
)
def test_cli_logs_command_boundaries_and_elapsed_seconds(
    runner: click.testing.CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    cli_log_output: structlog.testing.LogCapture,
    validate_sources_stubs: typing.Callable[
        ...,
        tests.helpers.doubles.peri_scribe.main.ValidateSourcesStubs,
    ],
    *,
    arguments: list[str],
    parameters: dict[str, object],
) -> None:
    validate_sources_stubs(())
    ticks = iter((100.0, 223.45))
    monkeypatch.setattr(peri_scribe.logging.time, "perf_counter", lambda: next(ticks))

    result = runner.invoke(peri_scribe.main.cli, arguments)

    assert result.exit_code == 0
    assert cli_log_output.entries[0] == {
        "event": "Starting command",
        "command": arguments[0],
        "log_level": "info",
        "parameters": parameters,
    }
    assert cli_log_output.entries[-1] == {
        "event": "Finished command",
        "command": arguments[0],
        "duration": {"value": 123.45, "units": units.seconds},
        "status": "completed",
        "log_level": "info",
    }
    assert isinstance(cli_log_output.entries[-1]["duration"]["value"], float)


def test_cli_logs_supplied_arguments_options_and_global_parameters(
    runner: click.testing.CliRunner,
    cli_log_output: structlog.testing.LogCapture,
    tmp_path: pathlib.Path,
) -> None:
    year_directory = tmp_path / "fire data" / "2026"
    year_directory.mkdir(parents=True)

    result = runner.invoke(
        peri_scribe.main.cli,
        [
            "--stderr-log-level",
            "info",
            "--file-log-level",
            "warning",
            "run",
            str(year_directory),
            "--full-fetch-interval",
            "6h",
            "--unconditional",
            "--from",
            "geography",
            "--to",
            "reports",
            "--list-stages",
        ],
    )

    assert result.exit_code == 0
    assert cli_log_output.entries[0]["parameters"] == {
        "stderr_log_level": "info",
        "file_log_level": "warning",
        "year_directory": str(year_directory),
        "full_fetch_interval": {"value": 21600.0, "units": units.seconds},
        "unconditional": True,
        "from_stage": "geography",
        "to_stage": "reports",
        "list_stages": True,
    }
    assert "parameters" not in cli_log_output.entries[-1]


def test_cli_suppresses_execution_logs_above_info(
    runner: click.testing.CliRunner,
) -> None:
    result = runner.invoke(
        peri_scribe.main.cli,
        ["--stderr-log-level", "warning", "run", "--list-stages"],
    )
    assert result.exit_code == 0
    assert "fetch" in result.stdout
    assert result.stderr == ""


def test_cli_keeps_logs_separate_from_command_output(
    runner: click.testing.CliRunner,
) -> None:
    result = runner.invoke(peri_scribe.main.cli, ["run", "--list-stages"])
    assert result.exit_code == 0
    assert "fetch" in result.stdout
    assert "Starting command" not in result.stdout
    assert "Finished command" not in result.stdout
    assert "Starting command" in result.stderr
    assert "Finished command" in result.stderr


@pytest.mark.parametrize("command", ["version", "show-colormap"])
def test_cli_display_commands_do_not_log_execution(
    runner: click.testing.CliRunner,
    cli_log_output: structlog.testing.LogCapture,
    command: str,
) -> None:
    result = runner.invoke(peri_scribe.main.cli, [command])
    assert result.exit_code == 0
    assert cli_log_output.entries == []


def test_distribution_version_raises_without_a_package_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(peri_scribe.main, "__package__", None)
    with pytest.raises(RuntimeError, match="not imported as part of its package"):
        peri_scribe.main.distribution_version()


@pytest.mark.parametrize("command", ["run", "validate-sources"])
@pytest.mark.parametrize("explicit_directory", [False, True])
def test_cli_logs_year_commands_to_their_resolved_directory(
    runner: click.testing.CliRunner,
    tmp_path: pathlib.Path,
    validate_sources_stubs: typing.Callable[
        ...,
        tests.helpers.doubles.peri_scribe.main.ValidateSourcesStubs,
    ],
    command: str,
    *,
    explicit_directory: bool,
) -> None:
    validate_sources_stubs(())
    year_directory = (
        tmp_path / "chosen" / "2026"
        if explicit_directory
        else peri_scribe.main.default_year_directory()
    )
    arguments = [command]
    if explicit_directory:
        year_directory.mkdir(parents=True)
        arguments.append(str(year_directory))
    if command == "run":
        arguments.append("--list-stages")
    result = runner.invoke(peri_scribe.main.cli, arguments)
    assert result.exit_code == 0, result.exception
    paths = list((year_directory / "logs").glob("*.jsonl"))
    assert [path.name for path in paths] == [
        datetime.datetime.now().strftime("%Y-%m.jsonl"),
    ]
    entries = [json.loads(line) for line in paths[0].read_text().splitlines()]
    assert entries[0]["event"] == "Starting command"
    assert entries[-1]["event"] == "Finished command"
    assert entries[0]["command"] == entries[-1]["command"] == command
    assert entries[-1]["duration"]["units"] == str(units.seconds)
    assert "Starting command" in result.stderr
    assert "Finished command" in result.stderr


@pytest.mark.parametrize("command", ["version", "show-colormap"])
def test_cli_display_commands_do_not_create_log_files(
    runner: click.testing.CliRunner,
    tmp_path: pathlib.Path,
    command: str,
) -> None:
    result = runner.invoke(peri_scribe.main.cli, [command])
    assert result.exit_code == 0
    assert list(tmp_path.iterdir()) == []


def test_cli_defaults_both_log_destinations_to_debug(
    runner: click.testing.CliRunner,
    tmp_path: pathlib.Path,
    run_stubs: typing.Callable[..., tests.helpers.doubles.peri_scribe.main.RunStubs],
) -> None:
    run_stubs(changed=False)
    year_directory = tmp_path / "2026"
    year_directory.mkdir()
    result = runner.invoke(peri_scribe.main.cli, ["run", str(year_directory)])
    assert result.exit_code == 0, result.exception
    assert "Nothing changed; skipping remaining pipeline steps" in result.stderr
    path = next((year_directory / "logs").glob("*.jsonl"))
    entries = [json.loads(line) for line in path.read_text().splitlines()]
    assert any(entry["level"] == "debug" for entry in entries)


@pytest.mark.parametrize(
    ("stderr_level", "file_level", "console_logged", "file_logged"),
    [("WARNING", "INFO", False, True), ("INFO", "WARNING", True, False)],
)
def test_cli_uses_independent_log_level_options(
    runner: click.testing.CliRunner,
    tmp_path: pathlib.Path,
    stderr_level: str,
    file_level: str,
    *,
    console_logged: bool,
    file_logged: bool,
) -> None:
    result = runner.invoke(
        peri_scribe.main.cli,
        [
            "--stderr-log-level",
            stderr_level,
            "--file-log-level",
            file_level,
            "run",
            str(tmp_path),
            "--list-stages",
        ],
    )
    assert result.exit_code == 0, result.exception
    assert ("Starting command" in result.stderr) is console_logged
    assert bool(list((tmp_path / "logs").glob("*.jsonl"))) is file_logged


def test_cli_closes_failed_command_logging_before_the_next_invocation(
    runner: click.testing.CliRunner,
    tmp_path: pathlib.Path,
) -> None:
    result = runner.invoke(
        peri_scribe.main.cli,
        ["run", str(tmp_path), "--only", "score", "--from", "geography"],
    )
    assert (
        result.exit_code == tests.helpers.peri_scribe.main.CLICK_USAGE_ERROR_EXIT_CODE
    )
    path = next((tmp_path / "logs").glob("*.jsonl"))
    contents = path.read_text()
    assert json.loads(contents.splitlines()[-1])["status"] == "failed"
    structlog.get_logger().info("Outside the command")
    assert runner.invoke(peri_scribe.main.cli, ["version"]).exit_code == 0
    assert path.read_text() == contents


def test_stored_evacuations_digest_uses_evacuations_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = pathlib.Path("/data/2026/sources/evacuations.gpkg")
    monkeypatch.setattr(
        peri_scribe.sources.external_data,
        "output_path",
        lambda _year_directory, _source: output,
    )
    digests: list[tuple[pathlib.Path, str]] = []

    stored_geopackage_digest = (
        tests.helpers.doubles.peri_scribe.main_run.make_digest_recorder(
            digests=digests,
        )
    )

    monkeypatch.setattr(
        peri_scribe.sources.digests,
        "stored_geopackage_digest",
        stored_geopackage_digest,
    )
    result = peri_scribe.main.stored_evacuations_digest(pathlib.Path("/data/2026"))
    assert result == "digest"
    assert digests == [(output, "evacuations")]


def test_duration_convert_whole_hours_and_days() -> None:
    duration = peri_scribe.main.Duration()
    assert duration.convert("0h", None, None) == datetime.timedelta(0)
    assert duration.convert("12h", None, None) == datetime.timedelta(hours=12)
    assert duration.convert("24h", None, None) == datetime.timedelta(hours=24)
    assert duration.convert("1d", None, None) == datetime.timedelta(days=1)
    assert duration.convert("3d", None, None) == datetime.timedelta(days=3)
    assert duration.convert("0d", None, None) == datetime.timedelta(0)


def test_duration_convert_accepts_an_already_converted_timedelta() -> None:
    duration = peri_scribe.main.Duration()
    value = datetime.timedelta(hours=12)
    assert duration.convert(value, None, None) is value


@pytest.mark.parametrize("value", [None, 12, b"12h"])
def test_duration_convert_rejects_values_that_are_not_duration_text(
    value: object,
) -> None:
    duration = peri_scribe.main.Duration()
    with pytest.raises(click.BadParameter):
        duration.convert(value, None, None)


def test_duration_convert_rejects_out_of_range_durations() -> None:
    duration = peri_scribe.main.Duration()
    with pytest.raises(click.BadParameter):
        duration.convert("9999999999999h", None, None)


def test_fetch_external_source_uses_given_year_directory(
    monkeypatch: pytest.MonkeyPatch,
    log_output: structlog.testing.LogCapture,
) -> None:
    source = peri_scribe.sources.external_sources.BUILDINGS_SOURCE
    year_directory = pathlib.Path("data/2026")
    fetched: list[tuple[object, pathlib.Path]] = []

    fetch_external_source = (
        tests.helpers.doubles.peri_scribe.main_source.make_fetch_recorder(
            fetched=fetched,
        )
    )

    monkeypatch.setattr(
        peri_scribe.sources.external_sources,
        "fetch_external_source",
        fetch_external_source,
    )
    peri_scribe.main.fetch_external_source(source, year_directory)
    assert fetched == [(source, year_directory)]
    fetched_entry = next(
        entry
        for entry in log_output.entries
        if entry["event"] == "Fetched external source"
    )
    assert fetched_entry["paths"] == ["/out.gpkg"]


def test_fetch_external_source_defaults_to_current_year_directory(
    monkeypatch: pytest.MonkeyPatch,
    current_year: typing.Iterator[None],
) -> None:
    source = peri_scribe.sources.external_sources.EVACUATIONS_SOURCE
    fetched: list[tuple[object, pathlib.Path]] = []

    fetch_external_source = (
        tests.helpers.doubles.peri_scribe.main_source.make_fetch_recorder(
            fetched=fetched,
        )
    )

    monkeypatch.setattr(
        peri_scribe.sources.external_sources,
        "fetch_external_source",
        fetch_external_source,
    )
    peri_scribe.main.fetch_external_source(source, None)
    assert fetched == [
        (
            source,
            tests.helpers.factories.peri_scribe.sources.snapshots.BASE_DIRECTORY
            / "data"
            / "2026",
        ),
    ]


def test_write_reports_gathers_and_renders(monkeypatch: pytest.MonkeyPatch) -> None:
    year_directory = pathlib.Path("data/2026")
    report = peri_scribe.report.gathering.FireReport(
        new_notable_fires=(),
        type_one_fires=(),
        fastest_growing_by_acres=(),
        fastest_growing_by_percent=(),
        top_fires=(),
        fire_details=(),
    )
    output = year_directory / "reports" / "PeriScribe Fires 2026.md"
    gathered: list[pathlib.Path] = []
    rendered: list[tuple[peri_scribe.report.gathering.FireReport, pathlib.Path]] = []

    gather_report = (
        tests.helpers.doubles.peri_scribe.main_write_reports.make_report_gatherer(
            gathered=gathered,
            report=report,
        )
    )

    render_markdown_report = (
        tests.helpers.doubles.peri_scribe.main_write_reports.make_report_renderer(
            rendered=rendered,
            output=output,
        )
    )

    monkeypatch.setattr(peri_scribe.report.gathering, "gather_report", gather_report)
    monkeypatch.setattr(
        peri_scribe.report.markdown,
        "render_markdown_report",
        render_markdown_report,
    )

    result = peri_scribe.main.write_reports(year_directory)

    assert result == output
    assert gathered == [year_directory]
    assert rendered == [(report, year_directory)]


def test_area_convert_accepts_equivalent_explicit_units() -> None:
    parser = peri_scribe.main.Area()
    assert parser.convert("1 hectare", None, None) == 10000 * units.meters**2
    with pytest.raises(click.BadParameter, match="positive area"):
        parser.convert(object(), None, None)


def test_gate_skip_checks_evacuations_and_preserves_checkpoint_without_pending_failure(
    scenario: tests.helpers.peri_scribe.main_publication.Scenario,
    runner: click.testing.CliRunner,
    cli_log_output: structlog.testing.LogCapture,
) -> None:
    before = peri_scribe.publication.publication_path(scenario.year).read_bytes()
    with time_machine.travel(
        tests.helpers.peri_scribe.main_publication.NOW,
        tick=False,
    ):
        result = runner.invoke(
            peri_scribe.main.cli,
            [
                "run",
                str(scenario.year),
                *tests.helpers.peri_scribe.main_publication.OPTIONS,
            ],
        )
    assert result.exit_code == 0, result.output
    assert scenario.indexed == []
    assert scenario.stubs.history_calls == []
    assert scenario.stubs.external_calls == [
        (peri_scribe.sources.external_sources.EVACUATIONS_SOURCE, scenario.year),
    ]
    assert scenario.stubs.ensure_boundary_calls == []
    assert not peri_scribe.pipeline_state.read_state(scenario.year).remaining
    assert (
        peri_scribe.publication.publication_path(scenario.year).read_bytes() == before
    )
    decision = next(
        entry
        for entry in cli_log_output.entries
        if entry["event"] == "Publication gate skipped"
    )
    assert decision["reason"] == peri_scribe.publication.Reason.BELOW_THRESHOLD
    assert {
        entry["phase"]
        for entry in cli_log_output.entries
        if entry.get("event") == "Finished phase"
    } == {"fetch", "evacuation-check", "publication-gate"}


def test_timer_builds_saved_updates_on_unchanged_fetch_and_advances_checkpoint(
    scenario: tests.helpers.peri_scribe.main_publication.Scenario,
    runner: click.testing.CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        peri_scribe.sources.fetching,
        "fetch_all_feeds",
        lambda *_args, **_kwargs: peri_scribe.sources.fetching.FetchResult(
            snapshot_paths=(),
            changed=False,
        ),
    )
    completed = tests.helpers.peri_scribe.main_publication.NOW + datetime.timedelta(
        minutes=5,
    )
    with time_machine.travel(completed, tick=False):
        result = runner.invoke(
            peri_scribe.main.cli,
            [
                "run",
                str(scenario.year),
                *tests.helpers.peri_scribe.main_publication.OPTIONS,
            ],
        )
    assert result.exit_code == 0, result.output
    assert scenario.indexed == [scenario.year]
    assert scenario.stubs.history_calls == [scenario.year]
    assert scenario.stubs.kmz_calls == [scenario.year]
    assert scenario.stubs.report_calls == [scenario.year]
    assert [source for source, _year in scenario.stubs.external_calls].count(
        peri_scribe.sources.external_sources.EVACUATIONS_SOURCE,
    ) == 1
    published = peri_scribe.publication.read_publication(scenario.year, scenario.output)
    assert published is not None
    assert published.files == scenario.inputs.files
    assert published.created_at == completed
    assert not peri_scribe.pipeline_state.read_state(scenario.year).remaining


@pytest.mark.parametrize(
    "override",
    ["unconditional", "full", "pending", "checkpoint", "evacuations"],
)
def test_required_work_bypasses_area_and_timer_gate(
    scenario: tests.helpers.peri_scribe.main_publication.Scenario,
    runner: click.testing.CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    override: str,
) -> None:
    arguments = []
    if override == "unconditional":
        arguments = ["--unconditional"]
    elif override == "full":
        arguments = ["--full-fetch-interval", "6h"]
    elif override == "pending":
        peri_scribe.pipeline_state.require_stages(
            scenario.year,
            peri_scribe.pipeline_state.DERIVED_STAGES,
        )
    elif override == "checkpoint":
        peri_scribe.publication.publication_path(scenario.year).unlink()
    else:
        changed = scenario.inputs.model_copy(
            update={
                "evacuations": tests.helpers.factories.peri_scribe.publication.STAMP,
            },
        )
        monkeypatch.setattr(peri_scribe.publication, "collect", lambda _year: changed)
    with time_machine.travel(
        tests.helpers.peri_scribe.main_publication.NOW,
        tick=False,
    ):
        result = runner.invoke(
            peri_scribe.main.cli,
            [
                "run",
                str(scenario.year),
                *tests.helpers.peri_scribe.main_publication.OPTIONS,
                *arguments,
                "--to",
                "geography",
            ],
        )
    assert result.exit_code == 0, result.output
    assert scenario.indexed == [scenario.year]
    assert scenario.stubs.history_calls == [scenario.year]
    if override == "full":
        assert scenario.stubs.fetch_calls[0][2]
        assert len(scenario.stubs.write_state_calls) == 1
        assert scenario.stubs.unconditional_history_calls == [scenario.year]


@pytest.mark.parametrize("operation", ["collection", "evacuations", "gate", "index"])
@pytest.mark.parametrize("error", [RuntimeError("failure"), SystemExit("failure")])
def test_failed_fetch_or_check_requires_retry_without_advancing_publication(
    scenario: tests.helpers.peri_scribe.main_publication.Scenario,
    runner: click.testing.CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    error: BaseException,
) -> None:
    module, name = {
        "collection": (peri_scribe.sources.fetching, "fetch_all_feeds"),
        "evacuations": (peri_scribe.main, "fetch_external_source"),
        "gate": (peri_scribe.publication, "collect"),
        "index": (peri_scribe.fires.index, "index_fire_sources"),
    }[operation]
    monkeypatch.setattr(module, name, tests.helpers.doubles.errors.raising_stub(error))
    before = peri_scribe.publication.publication_path(scenario.year).read_bytes()
    with time_machine.travel(
        tests.helpers.peri_scribe.main_publication.NOW,
        tick=False,
    ):
        result = runner.invoke(
            peri_scribe.main.cli,
            [
                "run",
                str(scenario.year),
                *tests.helpers.peri_scribe.main_publication.OPTIONS,
                "--unconditional",
            ],
        )
    assert result.exit_code != 0
    assert result.exception is error
    assert (
        peri_scribe.pipeline_state.read_state(scenario.year).remaining
        == peri_scribe.pipeline_state.DERIVED_STAGES
    )
    assert (
        peri_scribe.publication.publication_path(scenario.year).read_bytes() == before
    )


def test_partial_kmz_run_invalidates_checkpoint_without_acknowledging_new_sources(
    scenario: tests.helpers.peri_scribe.main_publication.Scenario,
    runner: click.testing.CliRunner,
) -> None:
    result = runner.invoke(
        peri_scribe.main.cli,
        [
            "run",
            str(scenario.year),
            *tests.helpers.peri_scribe.main_publication.OPTIONS,
            "--only",
            "kmz",
        ],
    )
    assert result.exit_code == 0, result.output
    assert scenario.stubs.kmz_calls == [scenario.year]
    assert not peri_scribe.publication.publication_path(scenario.year).exists()


@pytest.mark.parametrize(
    "area",
    ["25", "25 meters", "-25 acres", "0 acre", "nan acres", "inf acres", "nonsense"],
)
def test_cli_rejects_invalid_publication_areas(
    runner: click.testing.CliRunner,
    area: str,
) -> None:
    result = runner.invoke(
        peri_scribe.main.cli,
        ["run", "--publish-threshold", area, "5m"],
    )
    assert (
        result.exit_code == tests.helpers.peri_scribe.main.CLICK_USAGE_ERROR_EXIT_CODE
    )
    assert "positive area" in result.output


def test_cli_rejects_zero_publication_interval(runner: click.testing.CliRunner) -> None:
    result = runner.invoke(
        peri_scribe.main.cli,
        ["run", "--publish-threshold", "25 acre", "0m"],
    )
    assert (
        result.exit_code == tests.helpers.peri_scribe.main.CLICK_USAGE_ERROR_EXIT_CODE
    )
    assert "publication interval must be positive" in result.output


def test_overlapping_invocation_does_not_fetch_or_restart_work(
    scenario: tests.helpers.peri_scribe.main_publication.Scenario,
    runner: click.testing.CliRunner,
) -> None:
    with peri_scribe.pipeline_state.run_lock(scenario.year) as acquired:
        assert acquired
        result = runner.invoke(
            peri_scribe.main.cli,
            [
                "run",
                str(scenario.year),
                *tests.helpers.peri_scribe.main_publication.OPTIONS,
            ],
        )
    assert result.exit_code == 0, result.output
    assert scenario.stubs.fetch_calls == []
    assert scenario.stubs.kmz_calls == []
    assert not peri_scribe.pipeline_state.read_state(scenario.year).remaining


def test_report_failure_does_not_undo_completed_local_publication(
    scenario: tests.helpers.peri_scribe.main_publication.Scenario,
    runner: click.testing.CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        peri_scribe.main,
        "write_reports",
        tests.helpers.doubles.errors.raising_stub(RuntimeError("report failed")),
    )
    with time_machine.travel(
        tests.helpers.peri_scribe.main_publication.NOW,
        tick=False,
    ):
        result = runner.invoke(
            peri_scribe.main.cli,
            [
                "run",
                str(scenario.year),
                *tests.helpers.peri_scribe.main_publication.OPTIONS,
                "--unconditional",
            ],
        )
    assert result.exit_code != 0
    assert peri_scribe.pipeline_state.read_state(scenario.year).remaining == (
        "reports",
    )
    published = peri_scribe.publication.read_publication(scenario.year, scenario.output)
    assert published is not None
    assert published.files == scenario.inputs.files
    assert published.created_at == tests.helpers.peri_scribe.main_publication.NOW


@pytest.mark.usefixtures("current_year")
@pytest.mark.parametrize("changed", [True, False])
def test_run_logs_each_executed_phase_inside_command_boundaries(
    runner: click.testing.CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    run_stubs: typing.Callable[..., tests.helpers.doubles.peri_scribe.main.RunStubs],
    cli_log_output: structlog.testing.LogCapture,
    *,
    changed: bool,
) -> None:
    run_stubs(changed=changed)
    monkeypatch.setattr(
        peri_scribe.main,
        "refresh_external_sources",
        lambda _year_directory: False,
    )
    ticks = itertools.count()
    monkeypatch.setattr(peri_scribe.logging.time, "perf_counter", lambda: next(ticks))

    result = runner.invoke(peri_scribe.main.cli, ["run"])

    assert result.exit_code == 0
    phases = ["fetch", "geography", "score", "kmz", "reports"] if changed else ["fetch"]
    entries = [
        entry
        for entry in cli_log_output.entries
        if "command" in entry or "phase" in entry
    ]
    assert entries == [
        {
            "event": "Starting command",
            "command": "run",
            "parameters": {},
            "log_level": "info",
        },
        *(
            entry
            for phase in phases
            for entry in (
                {
                    "event": "Starting phase",
                    "phase": phase,
                    "phase_path": phase,
                    "log_level": "info",
                },
                {
                    "event": "Finished phase",
                    "phase": phase,
                    "phase_path": phase,
                    "duration": {"value": 1.0, "units": units.seconds},
                    "status": "completed",
                    "log_level": "info",
                },
            )
        ),
        {
            "event": "Finished command",
            "command": "run",
            "duration": {"value": float(2 * len(phases) + 1), "units": units.seconds},
            "status": "completed",
            "log_level": "info",
        },
    ]


@pytest.mark.usefixtures("current_year")
@pytest.mark.parametrize("error", [RuntimeError("boom"), SystemExit("boom")])
def test_run_logs_elapsed_time_when_a_phase_fails(
    runner: click.testing.CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    run_stubs: typing.Callable[..., tests.helpers.doubles.peri_scribe.main.RunStubs],
    cli_log_output: structlog.testing.LogCapture,
    error: BaseException,
) -> None:
    run_stubs(changed=True)
    monkeypatch.setattr(
        peri_scribe.fires.scores,
        "score_fires",
        tests.helpers.doubles.errors.raising_stub(error),
    )
    ticks = iter((0.0, 10.0, 133.45, 200.0))
    monkeypatch.setattr(peri_scribe.logging.time, "perf_counter", lambda: next(ticks))

    result = runner.invoke(peri_scribe.main.cli, ["run", "--from", "score"])

    assert result.exit_code != 0
    assert result.exception is error
    assert cli_log_output.entries[-2:] == [
        {
            "event": "Finished phase",
            "phase": "score",
            "phase_path": "score",
            "duration": {"value": 123.45, "units": units.seconds},
            "status": "failed",
            "log_level": "error",
        },
        {
            "event": "Finished command",
            "command": "run",
            "duration": {"value": 200.0, "units": units.seconds},
            "status": "failed",
            "log_level": "error",
        },
    ]


def test_run_runs_all_stages_when_fetch_changed(
    runner: click.testing.CliRunner,
    run_stubs: typing.Callable[..., tests.helpers.doubles.peri_scribe.main.RunStubs],
    tmp_path: pathlib.Path,
) -> None:
    stubs = run_stubs(changed=True)
    year_directory = tmp_path / "data" / "2026"
    year_directory.mkdir(parents=True)
    result = runner.invoke(peri_scribe.main.cli, ["run", str(year_directory)])
    assert result.exit_code == 0
    assert stubs.external_calls == [
        (source, year_directory)
        for source in peri_scribe.sources.external_sources.EXTERNAL_SOURCES
    ]
    assert stubs.ensure_boundary_calls == [year_directory]
    assert stubs.history_calls == [year_directory]
    assert stubs.scores_calls == [year_directory]
    assert stubs.kmz_calls == [year_directory]
    assert stubs.report_calls == [year_directory]


@pytest.mark.usefixtures("current_year")
def test_run_defaults_to_current_year_directory(
    runner: click.testing.CliRunner,
    run_stubs: typing.Callable[..., tests.helpers.doubles.peri_scribe.main.RunStubs],
) -> None:
    stubs = run_stubs(changed=True)
    result = runner.invoke(peri_scribe.main.cli, ["run"])
    assert result.exit_code == 0
    year_directory = (
        tests.helpers.factories.peri_scribe.sources.snapshots.BASE_DIRECTORY
        / "data"
        / "2026"
    )
    assert stubs.fetch_calls == [
        (
            tests.helpers.factories.peri_scribe.sources.snapshots.BASE_DIRECTORY,
            2026,
            False,
        ),
    ]
    assert stubs.external_calls == [
        (source, year_directory)
        for source in peri_scribe.sources.external_sources.EXTERNAL_SOURCES
    ]
    assert stubs.ensure_boundary_calls == [year_directory]
    assert stubs.history_calls == [year_directory]
    assert stubs.scores_calls == [year_directory]
    assert stubs.kmz_calls == [year_directory]
    assert stubs.report_calls == [year_directory]


@pytest.mark.usefixtures("current_year")
def test_run_fetches_external_sources_but_skips_later_stages_when_nothing_changed(
    runner: click.testing.CliRunner,
    run_stubs: typing.Callable[..., tests.helpers.doubles.peri_scribe.main.RunStubs],
) -> None:
    stubs = run_stubs(changed=False)
    result = runner.invoke(peri_scribe.main.cli, ["run"])
    assert result.exit_code == 0
    year_directory = (
        tests.helpers.factories.peri_scribe.sources.snapshots.BASE_DIRECTORY
        / "data"
        / "2026"
    )
    assert stubs.external_calls == [
        (source, year_directory)
        for source in peri_scribe.sources.external_sources.EXTERNAL_SOURCES
    ]
    assert stubs.ensure_boundary_calls == [year_directory]
    assert stubs.history_calls == []
    assert stubs.scores_calls == []
    assert stubs.kmz_calls == []
    assert stubs.report_calls == []


@pytest.mark.usefixtures("current_year")
def test_run_runs_stages_when_evacuations_changed(
    runner: click.testing.CliRunner,
    run_stubs: typing.Callable[..., tests.helpers.doubles.peri_scribe.main.RunStubs],
) -> None:
    stubs = run_stubs(changed=False, evacuations_changed=True)
    result = runner.invoke(peri_scribe.main.cli, ["run"])
    assert result.exit_code == 0
    year_directory = (
        tests.helpers.factories.peri_scribe.sources.snapshots.BASE_DIRECTORY
        / "data"
        / "2026"
    )
    assert stubs.fetch_calls == [
        (
            tests.helpers.factories.peri_scribe.sources.snapshots.BASE_DIRECTORY,
            2026,
            False,
        ),
    ]
    assert stubs.external_calls == [
        (source, year_directory)
        for source in peri_scribe.sources.external_sources.EXTERNAL_SOURCES
    ]
    assert stubs.ensure_boundary_calls == [year_directory]
    assert stubs.history_calls == [year_directory]
    assert stubs.scores_calls == [year_directory]
    assert stubs.kmz_calls == [year_directory]
    assert stubs.report_calls == [year_directory]


@pytest.mark.usefixtures("current_year")
def test_run_unconditional_runs_stages_when_unchanged(
    runner: click.testing.CliRunner,
    run_stubs: typing.Callable[..., tests.helpers.doubles.peri_scribe.main.RunStubs],
) -> None:
    stubs = run_stubs(changed=False)
    result = runner.invoke(peri_scribe.main.cli, ["run", "--unconditional"])
    assert result.exit_code == 0
    year_directory = (
        tests.helpers.factories.peri_scribe.sources.snapshots.BASE_DIRECTORY
        / "data"
        / "2026"
    )
    assert stubs.fetch_calls == [
        (
            tests.helpers.factories.peri_scribe.sources.snapshots.BASE_DIRECTORY,
            2026,
            False,
        ),
    ]
    assert stubs.write_state_calls == []
    assert stubs.ensure_boundary_calls == [year_directory]
    assert stubs.history_calls == [year_directory]
    assert stubs.scores_calls == [year_directory]
    assert stubs.kmz_calls == [year_directory]
    assert stubs.report_calls == [year_directory]


@pytest.mark.usefixtures("current_year")
def test_run_full_fetch_interval_zero_hours_fetches_in_full_and_records_state(
    runner: click.testing.CliRunner,
    run_stubs: typing.Callable[..., tests.helpers.doubles.peri_scribe.main.RunStubs],
) -> None:
    stubs = run_stubs(changed=False)
    result = runner.invoke(peri_scribe.main.cli, ["run", "--full-fetch-interval", "0h"])
    assert result.exit_code == 0
    year_directory = (
        tests.helpers.factories.peri_scribe.sources.snapshots.BASE_DIRECTORY
        / "data"
        / "2026"
    )
    assert stubs.fetch_calls == [
        (
            tests.helpers.factories.peri_scribe.sources.snapshots.BASE_DIRECTORY,
            2026,
            True,
        ),
    ]
    assert stubs.write_state_calls == [
        (
            year_directory / "sources" / "fetch_state.json",
            datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
        ),
    ]
    assert stubs.ensure_boundary_calls == [year_directory]


@pytest.mark.usefixtures("current_year")
def test_run_full_fetch_interval_zero_days_fetches_in_full(
    runner: click.testing.CliRunner,
    run_stubs: typing.Callable[..., tests.helpers.doubles.peri_scribe.main.RunStubs],
) -> None:
    stubs = run_stubs(changed=False)
    result = runner.invoke(peri_scribe.main.cli, ["run", "--full-fetch-interval", "0d"])
    assert result.exit_code == 0
    assert stubs.fetch_calls == [
        (
            tests.helpers.factories.peri_scribe.sources.snapshots.BASE_DIRECTORY,
            2026,
            True,
        ),
    ]


@pytest.mark.usefixtures("current_year")
def test_run_full_fetch_interval_fetches_in_full_without_stored_state(
    runner: click.testing.CliRunner,
    run_stubs: typing.Callable[..., tests.helpers.doubles.peri_scribe.main.RunStubs],
) -> None:
    stubs = run_stubs(changed=False)
    result = runner.invoke(
        peri_scribe.main.cli,
        ["run", "--full-fetch-interval", "12h"],
    )
    assert result.exit_code == 0
    year_directory = (
        tests.helpers.factories.peri_scribe.sources.snapshots.BASE_DIRECTORY
        / "data"
        / "2026"
    )
    assert stubs.fetch_calls == [
        (
            tests.helpers.factories.peri_scribe.sources.snapshots.BASE_DIRECTORY,
            2026,
            True,
        ),
    ]
    assert stubs.write_state_calls == [
        (
            year_directory / "sources" / "fetch_state.json",
            datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
        ),
    ]


@pytest.mark.usefixtures("current_year")
def test_run_full_fetch_interval_skips_full_fetch_when_interval_not_elapsed(
    runner: click.testing.CliRunner,
    run_stubs: typing.Callable[..., tests.helpers.doubles.peri_scribe.main.RunStubs],
) -> None:
    stubs = run_stubs(
        changed=False,
        stored_state=peri_scribe.sources.full_fetch_state.FullFetchState(
            last_full_fetch=(
                datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
                - datetime.timedelta(hours=2)
            ),
        ),
    )
    result = runner.invoke(
        peri_scribe.main.cli,
        ["run", "--full-fetch-interval", "12h"],
    )
    assert result.exit_code == 0
    assert stubs.fetch_calls == [
        (
            tests.helpers.factories.peri_scribe.sources.snapshots.BASE_DIRECTORY,
            2026,
            False,
        ),
    ]
    assert stubs.write_state_calls == []


@pytest.mark.usefixtures("current_year")
def test_run_full_fetch_interval_fetches_in_full_when_interval_elapsed(
    runner: click.testing.CliRunner,
    run_stubs: typing.Callable[..., tests.helpers.doubles.peri_scribe.main.RunStubs],
) -> None:
    stubs = run_stubs(
        changed=False,
        stored_state=peri_scribe.sources.full_fetch_state.FullFetchState(
            last_full_fetch=(
                datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
                - datetime.timedelta(hours=13)
            ),
        ),
    )
    result = runner.invoke(
        peri_scribe.main.cli,
        ["run", "--full-fetch-interval", "12h"],
    )
    assert result.exit_code == 0
    year_directory = (
        tests.helpers.factories.peri_scribe.sources.snapshots.BASE_DIRECTORY
        / "data"
        / "2026"
    )
    assert stubs.fetch_calls == [
        (
            tests.helpers.factories.peri_scribe.sources.snapshots.BASE_DIRECTORY,
            2026,
            True,
        ),
    ]
    assert stubs.write_state_calls == [
        (
            year_directory / "sources" / "fetch_state.json",
            datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
        ),
    ]


@pytest.mark.usefixtures("current_year")
def test_run_full_fetch_interval_accepts_days(
    runner: click.testing.CliRunner,
    run_stubs: typing.Callable[..., tests.helpers.doubles.peri_scribe.main.RunStubs],
) -> None:
    stubs = run_stubs(
        changed=False,
        stored_state=peri_scribe.sources.full_fetch_state.FullFetchState(
            last_full_fetch=(
                datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
                - datetime.timedelta(hours=12)
            ),
        ),
    )
    result = runner.invoke(peri_scribe.main.cli, ["run", "--full-fetch-interval", "1d"])
    assert result.exit_code == 0
    assert stubs.fetch_calls == [
        (
            tests.helpers.factories.peri_scribe.sources.snapshots.BASE_DIRECTORY,
            2026,
            False,
        ),
    ]
    assert stubs.write_state_calls == []


@pytest.mark.usefixtures("current_year")
def test_run_full_fetch_interval_with_unconditional_runs_all_stages(
    runner: click.testing.CliRunner,
    run_stubs: typing.Callable[..., tests.helpers.doubles.peri_scribe.main.RunStubs],
) -> None:
    stubs = run_stubs(changed=False)
    result = runner.invoke(
        peri_scribe.main.cli,
        ["run", "--full-fetch-interval", "0h", "--unconditional"],
    )
    assert result.exit_code == 0
    year_directory = (
        tests.helpers.factories.peri_scribe.sources.snapshots.BASE_DIRECTORY
        / "data"
        / "2026"
    )
    assert stubs.fetch_calls == [
        (
            tests.helpers.factories.peri_scribe.sources.snapshots.BASE_DIRECTORY,
            2026,
            True,
        ),
    ]
    assert stubs.ensure_boundary_calls == [year_directory]
    assert stubs.history_calls == [year_directory]
    assert stubs.scores_calls == [year_directory]
    assert stubs.kmz_calls == [year_directory]
    assert stubs.report_calls == [year_directory]


@pytest.mark.usefixtures("current_year")
def test_run_full_fetch_forces_geography_without_source_changes(
    runner: click.testing.CliRunner,
    run_stubs: typing.Callable[..., tests.helpers.doubles.peri_scribe.main.RunStubs],
) -> None:
    stubs = run_stubs(changed=False)
    result = runner.invoke(peri_scribe.main.cli, ["run", "--full-fetch-interval", "6h"])
    assert result.exit_code == 0
    assert stubs.unconditional_history_calls == stubs.history_calls
    assert stubs.history_calls == [
        tests.helpers.factories.peri_scribe.sources.snapshots.BASE_DIRECTORY
        / "data"
        / "2026",
    ]
    assert not peri_scribe.pipeline_state.read_state(
        tests.helpers.factories.peri_scribe.sources.snapshots.BASE_DIRECTORY
        / "data"
        / "2026",
    ).remaining


@pytest.mark.usefixtures("current_year")
def test_run_retries_failed_full_rebuild_without_another_full_fetch(
    runner: click.testing.CliRunner,
    run_stubs: typing.Callable[..., tests.helpers.doubles.peri_scribe.main.RunStubs],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stubs = run_stubs(changed=False)
    write_history = (
        peri_scribe.fires.differential.write_history_of_differential_geography
    )
    monkeypatch.setattr(
        peri_scribe.fires.differential,
        "write_history_of_differential_geography",
        tests.helpers.doubles.errors.raising_stub(ValueError("interrupted")),
    )
    failed = runner.invoke(peri_scribe.main.cli, ["run", "--full-fetch-interval", "6h"])
    assert failed.exit_code != 0
    monkeypatch.setattr(
        peri_scribe.fires.differential,
        "write_history_of_differential_geography",
        write_history,
    )
    monkeypatch.setattr(
        peri_scribe.sources.full_fetch_state,
        "read_state",
        lambda _path: peri_scribe.sources.full_fetch_state.FullFetchState(
            last_full_fetch=datetime.datetime.now(datetime.UTC),
        ),
    )
    retry = runner.invoke(peri_scribe.main.cli, ["run", "--full-fetch-interval", "6h"])
    assert retry.exit_code == 0
    assert [full for _base, _year, full in stubs.fetch_calls] == [True, False]
    assert stubs.unconditional_history_calls == [
        tests.helpers.factories.peri_scribe.sources.snapshots.BASE_DIRECTORY
        / "data"
        / "2026",
    ]


@pytest.mark.usefixtures("current_year")
def test_run_retries_external_failure_after_full_fetch(
    runner: click.testing.CliRunner,
    run_stubs: typing.Callable[..., tests.helpers.doubles.peri_scribe.main.RunStubs],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stubs = run_stubs(changed=False)
    refresh = peri_scribe.main.refresh_external_sources
    monkeypatch.setattr(
        peri_scribe.main,
        "refresh_external_sources",
        tests.helpers.doubles.errors.raising_stub(ValueError("interrupted")),
    )
    failed = runner.invoke(peri_scribe.main.cli, ["run", "--full-fetch-interval", "6h"])
    assert failed.exit_code != 0
    monkeypatch.setattr(peri_scribe.main, "refresh_external_sources", refresh)
    retry = runner.invoke(peri_scribe.main.cli, ["run"])
    assert retry.exit_code == 0
    assert stubs.unconditional_history_calls == [
        tests.helpers.factories.peri_scribe.sources.snapshots.BASE_DIRECTORY
        / "data"
        / "2026",
    ]


@pytest.mark.usefixtures("current_year")
def test_run_partial_selection_keeps_full_rebuild_pending(
    runner: click.testing.CliRunner,
    run_stubs: typing.Callable[..., tests.helpers.doubles.peri_scribe.main.RunStubs],
) -> None:
    run_stubs(changed=False)
    result = runner.invoke(
        peri_scribe.main.cli,
        ["run", "--only", "fetch", "--full-fetch-interval", "6h"],
    )
    assert result.exit_code == 0
    year = (
        tests.helpers.factories.peri_scribe.sources.snapshots.BASE_DIRECTORY
        / "data"
        / "2026"
    )
    assert (
        peri_scribe.pipeline_state.read_state(year).remaining
        == peri_scribe.pipeline_state.DERIVED_STAGES
    )
    result = runner.invoke(peri_scribe.main.cli, ["run", "--only", "kmz"])
    assert result.exit_code == 0
    assert (
        peri_scribe.pipeline_state.read_state(year).remaining
        == peri_scribe.pipeline_state.DERIVED_STAGES
    )


@pytest.mark.usefixtures("current_year")
def test_run_skips_an_overlapping_invocation(
    runner: click.testing.CliRunner,
    run_stubs: typing.Callable[..., tests.helpers.doubles.peri_scribe.main.RunStubs],
    cli_log_output: structlog.testing.LogCapture,
) -> None:
    stubs = run_stubs(changed=True)
    with peri_scribe.pipeline_state.run_lock(
        tests.helpers.factories.peri_scribe.sources.snapshots.BASE_DIRECTORY
        / "data"
        / "2026",
    ) as acquired:
        assert acquired
        result = runner.invoke(peri_scribe.main.cli, ["run"])
    assert result.exit_code == 0
    assert stubs.fetch_calls == []
    assert [entry["event"] for entry in cli_log_output.entries] == [
        "Starting command",
        "Another run owns this year; skipping invocation",
        "Finished command",
    ]


@pytest.mark.usefixtures("current_year")
def test_run_full_fetch_interval_does_not_record_state_when_fetch_fails(
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
    run_stubs: typing.Callable[..., tests.helpers.doubles.peri_scribe.main.RunStubs],
) -> None:
    fail = tests.helpers.doubles.errors.raising_stub(SystemExit("boom"))

    stubs = run_stubs(changed=True)
    monkeypatch.setattr(peri_scribe.sources.fetching, "fetch_all_feeds", fail)
    result = runner.invoke(peri_scribe.main.cli, ["run", "--full-fetch-interval", "0h"])
    assert result.exit_code == 1
    assert "boom" in result.output
    assert stubs.write_state_calls == []


@pytest.mark.usefixtures("current_year")
def test_run_stops_when_fetch_state_is_malformed(
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
    run_stubs: typing.Callable[..., tests.helpers.doubles.peri_scribe.main.RunStubs],
) -> None:

    read_state = tests.helpers.doubles.peri_scribe.main_run.raise_malformed_state

    stubs = run_stubs(changed=True)
    monkeypatch.setattr(peri_scribe.sources.full_fetch_state, "read_state", read_state)
    result = runner.invoke(
        peri_scribe.main.cli,
        ["run", "--full-fetch-interval", "12h"],
    )
    assert result.exit_code == 1
    assert isinstance(result.exception, ValueError)
    assert stubs.fetch_calls == []


@pytest.mark.parametrize("value", ["-1h", "1.5h", "12", "1w", "1d12h", "1H", "h", ""])
def test_run_rejects_invalid_full_fetch_intervals(
    runner: click.testing.CliRunner,
    value: str,
) -> None:
    result = runner.invoke(
        peri_scribe.main.cli,
        ["run", "--full-fetch-interval", value],
    )
    assert (
        result.exit_code == tests.helpers.peri_scribe.main.CLICK_USAGE_ERROR_EXIT_CODE
    )
    assert "Invalid value for '--full-fetch-interval'" in result.output


def test_run_help_describes_full_fetch_interval_and_unconditional(
    runner: click.testing.CliRunner,
) -> None:
    result = runner.invoke(peri_scribe.main.cli, ["run", "--help"])
    assert result.exit_code == 0
    assert "--full-fetch-interval DURATION" in result.output
    assert "--unconditional" in result.output


@pytest.mark.usefixtures("current_year")
def test_run_stops_when_fetch_fails(
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
    run_stubs: typing.Callable[..., tests.helpers.doubles.peri_scribe.main.RunStubs],
) -> None:
    fail = tests.helpers.doubles.errors.raising_stub(SystemExit("boom"))

    stubs = run_stubs(changed=True)
    monkeypatch.setattr(peri_scribe.sources.fetching, "fetch_all_feeds", fail)
    result = runner.invoke(peri_scribe.main.cli, ["run", "--unconditional"])
    assert result.exit_code == 1
    assert "boom" in result.output
    assert stubs.external_calls == []
    assert stubs.ensure_boundary_calls == []
    assert stubs.history_calls == []
    assert stubs.scores_calls == []
    assert stubs.kmz_calls == []
    assert stubs.report_calls == []


@pytest.mark.usefixtures("current_year")
def test_run_stops_when_external_source_fetch_fails(
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
    run_stubs: typing.Callable[..., tests.helpers.doubles.peri_scribe.main.RunStubs],
) -> None:
    fail = tests.helpers.doubles.errors.raising_stub(
        peri_scribe.exceptions.ExternalDataError("boom"),
    )

    stubs = run_stubs(changed=True)
    monkeypatch.setattr(peri_scribe.main, "fetch_external_source", fail)
    result = runner.invoke(peri_scribe.main.cli, ["run"])
    assert result.exit_code == 1
    assert isinstance(result.exception, peri_scribe.exceptions.ExternalDataError)
    assert stubs.ensure_boundary_calls == []
    assert stubs.history_calls == []
    assert stubs.scores_calls == []
    assert stubs.kmz_calls == []
    assert stubs.report_calls == []


@pytest.mark.usefixtures("current_year")
def test_run_stops_when_a_stage_fails(
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
    run_stubs: typing.Callable[..., tests.helpers.doubles.peri_scribe.main.RunStubs],
) -> None:
    fail = tests.helpers.doubles.errors.raising_stub(ValueError("boom"))

    stubs = run_stubs(changed=True)
    monkeypatch.setattr(
        peri_scribe.fires.differential,
        "write_history_of_differential_geography",
        fail,
    )
    result = runner.invoke(peri_scribe.main.cli, ["run"])
    assert result.exit_code == 1
    assert isinstance(result.exception, ValueError)
    assert stubs.ensure_boundary_calls == [
        tests.helpers.factories.peri_scribe.sources.snapshots.BASE_DIRECTORY
        / "data"
        / "2026",
    ]
    assert stubs.history_calls == []
    assert stubs.scores_calls == []
    assert stubs.kmz_calls == []
    assert stubs.report_calls == []


@pytest.mark.usefixtures("current_year")
def test_run_stops_when_scoring_fails(
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
    run_stubs: typing.Callable[..., tests.helpers.doubles.peri_scribe.main.RunStubs],
) -> None:
    fail = tests.helpers.doubles.errors.raising_stub(ValueError("boom"))

    stubs = run_stubs(changed=True)
    monkeypatch.setattr(peri_scribe.fires.scores, "score_fires", fail)
    result = runner.invoke(peri_scribe.main.cli, ["run"])
    assert result.exit_code == 1
    assert isinstance(result.exception, ValueError)
    assert stubs.ensure_boundary_calls == [
        tests.helpers.factories.peri_scribe.sources.snapshots.BASE_DIRECTORY
        / "data"
        / "2026",
    ]
    assert stubs.history_calls == [
        tests.helpers.factories.peri_scribe.sources.snapshots.BASE_DIRECTORY
        / "data"
        / "2026",
    ]
    assert stubs.scores_calls == []
    assert stubs.kmz_calls == []
    assert stubs.report_calls == []


@pytest.mark.usefixtures("current_year")
def test_run_only_runs_a_single_stage(
    runner: click.testing.CliRunner,
    run_stubs: typing.Callable[..., tests.helpers.doubles.peri_scribe.main.RunStubs],
) -> None:
    stubs = run_stubs(changed=True)
    result = runner.invoke(peri_scribe.main.cli, ["run", "--only", "geography"])
    assert result.exit_code == 0
    year_directory = (
        tests.helpers.factories.peri_scribe.sources.snapshots.BASE_DIRECTORY
        / "data"
        / "2026"
    )
    assert stubs.fetch_calls == []
    assert stubs.external_calls == []
    assert stubs.ensure_boundary_calls == []
    assert stubs.history_calls == [year_directory]
    assert stubs.scores_calls == []
    assert stubs.kmz_calls == []
    assert stubs.report_calls == []


@pytest.mark.usefixtures("current_year")
def test_run_only_fetch_runs_no_later_stages(
    runner: click.testing.CliRunner,
    run_stubs: typing.Callable[..., tests.helpers.doubles.peri_scribe.main.RunStubs],
) -> None:
    stubs = run_stubs(changed=True)
    result = runner.invoke(peri_scribe.main.cli, ["run", "--only", "fetch"])
    assert result.exit_code == 0
    year_directory = (
        tests.helpers.factories.peri_scribe.sources.snapshots.BASE_DIRECTORY
        / "data"
        / "2026"
    )
    assert stubs.fetch_calls == [
        (
            tests.helpers.factories.peri_scribe.sources.snapshots.BASE_DIRECTORY,
            2026,
            False,
        ),
    ]
    assert stubs.external_calls == [
        (source, year_directory)
        for source in peri_scribe.sources.external_sources.EXTERNAL_SOURCES
    ]
    assert stubs.ensure_boundary_calls == [year_directory]
    assert stubs.history_calls == []
    assert stubs.scores_calls == []
    assert stubs.kmz_calls == []
    assert stubs.report_calls == []


@pytest.mark.usefixtures("current_year")
def test_run_from_geography_to_kmz(
    runner: click.testing.CliRunner,
    run_stubs: typing.Callable[..., tests.helpers.doubles.peri_scribe.main.RunStubs],
) -> None:
    stubs = run_stubs(changed=True)
    result = runner.invoke(
        peri_scribe.main.cli,
        ["run", "--from", "geography", "--to", "kmz"],
    )
    assert result.exit_code == 0
    year_directory = (
        tests.helpers.factories.peri_scribe.sources.snapshots.BASE_DIRECTORY
        / "data"
        / "2026"
    )
    assert stubs.fetch_calls == []
    assert stubs.external_calls == []
    assert stubs.ensure_boundary_calls == []
    assert stubs.history_calls == [year_directory]
    assert stubs.scores_calls == [year_directory]
    assert stubs.kmz_calls == [year_directory]
    assert stubs.report_calls == []


@pytest.mark.usefixtures("current_year")
def test_run_from_score_runs_to_the_end(
    runner: click.testing.CliRunner,
    run_stubs: typing.Callable[..., tests.helpers.doubles.peri_scribe.main.RunStubs],
) -> None:
    stubs = run_stubs(changed=True)
    result = runner.invoke(peri_scribe.main.cli, ["run", "--from", "score"])
    assert result.exit_code == 0
    year_directory = (
        tests.helpers.factories.peri_scribe.sources.snapshots.BASE_DIRECTORY
        / "data"
        / "2026"
    )
    assert stubs.fetch_calls == []
    assert stubs.external_calls == []
    assert stubs.ensure_boundary_calls == []
    assert stubs.history_calls == []
    assert stubs.scores_calls == [year_directory]
    assert stubs.kmz_calls == [year_directory]
    assert stubs.report_calls == [year_directory]


@pytest.mark.usefixtures("current_year")
def test_run_to_geography_runs_fetch_through_geography(
    runner: click.testing.CliRunner,
    run_stubs: typing.Callable[..., tests.helpers.doubles.peri_scribe.main.RunStubs],
) -> None:
    stubs = run_stubs(changed=True)
    result = runner.invoke(peri_scribe.main.cli, ["run", "--to", "geography"])
    assert result.exit_code == 0
    year_directory = (
        tests.helpers.factories.peri_scribe.sources.snapshots.BASE_DIRECTORY
        / "data"
        / "2026"
    )
    assert stubs.fetch_calls == [
        (
            tests.helpers.factories.peri_scribe.sources.snapshots.BASE_DIRECTORY,
            2026,
            False,
        ),
    ]
    assert stubs.external_calls == [
        (source, year_directory)
        for source in peri_scribe.sources.external_sources.EXTERNAL_SOURCES
    ]
    assert stubs.ensure_boundary_calls == [year_directory]
    assert stubs.history_calls == [year_directory]
    assert stubs.scores_calls == []
    assert stubs.kmz_calls == []
    assert stubs.report_calls == []


@pytest.mark.usefixtures("current_year")
def test_run_to_fetch_short_circuits_without_later_stages(
    runner: click.testing.CliRunner,
    run_stubs: typing.Callable[..., tests.helpers.doubles.peri_scribe.main.RunStubs],
) -> None:
    stubs = run_stubs(changed=False)
    result = runner.invoke(peri_scribe.main.cli, ["run", "--to", "fetch"])
    assert result.exit_code == 0
    year_directory = (
        tests.helpers.factories.peri_scribe.sources.snapshots.BASE_DIRECTORY
        / "data"
        / "2026"
    )
    assert stubs.fetch_calls == [
        (
            tests.helpers.factories.peri_scribe.sources.snapshots.BASE_DIRECTORY,
            2026,
            False,
        ),
    ]
    assert stubs.external_calls == [
        (source, year_directory)
        for source in peri_scribe.sources.external_sources.EXTERNAL_SOURCES
    ]
    assert stubs.ensure_boundary_calls == [year_directory]
    assert stubs.history_calls == []
    assert stubs.scores_calls == []
    assert stubs.kmz_calls == []
    assert stubs.report_calls == []


def test_run_only_conflicts_with_from(runner: click.testing.CliRunner) -> None:
    result = runner.invoke(
        peri_scribe.main.cli,
        ["run", "--only", "geography", "--from", "score"],
    )
    assert (
        result.exit_code == tests.helpers.peri_scribe.main.CLICK_USAGE_ERROR_EXIT_CODE
    )
    assert "--only cannot be combined with --from or --to" in result.output


def test_run_rejects_from_after_to(runner: click.testing.CliRunner) -> None:
    result = runner.invoke(
        peri_scribe.main.cli,
        ["run", "--from", "kmz", "--to", "fetch"],
    )
    assert (
        result.exit_code == tests.helpers.peri_scribe.main.CLICK_USAGE_ERROR_EXIT_CODE
    )
    assert "--from kmz cannot follow --to fetch" in result.output


def test_run_list_stages_prints_descriptions_without_running(
    runner: click.testing.CliRunner,
    run_stubs: typing.Callable[..., tests.helpers.doubles.peri_scribe.main.RunStubs],
) -> None:
    stubs = run_stubs(changed=True)
    result = runner.invoke(peri_scribe.main.cli, ["run", "--list-stages"])
    assert result.exit_code == 0
    assert stubs.fetch_calls == []
    assert stubs.external_calls == []
    assert stubs.ensure_boundary_calls == []
    assert stubs.history_calls == []
    assert stubs.scores_calls == []
    assert stubs.kmz_calls == []
    assert stubs.report_calls == []
    for stage in peri_scribe.main.PIPELINE_STAGES:
        assert stage.name in result.output
        assert stage.description in result.output


def test_run_help_names_current_year_default(runner: click.testing.CliRunner) -> None:
    result = runner.invoke(peri_scribe.main.cli, ["run", "--help"])
    assert result.exit_code == 0
    assert (
        f"{peri_scribe.output.DATA_DIRECTORY}/{datetime.date.today().year}"
    ) in result.output
    assert "data/<current year>" not in result.output


def test_run_rejects_missing_directory(runner: click.testing.CliRunner) -> None:
    result = runner.invoke(peri_scribe.main.cli, ["run", "no-such-directory"])
    assert (
        result.exit_code == tests.helpers.peri_scribe.main.CLICK_USAGE_ERROR_EXIT_CODE
    )
    assert "does not exist" in result.output


def test_cli_help_lists_run(runner: click.testing.CliRunner) -> None:
    result = runner.invoke(peri_scribe.main.cli, ["--help"])
    assert result.exit_code == 0
    assert "run" in result.output


def test_show_turbo_colormap_prints_the_strip(
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
) -> None:
    calls: list[tuple[int, int]] = []
    strip = "fake-strip"

    monkeypatch.setattr(
        peri_scribe.kml.colormap,
        "turbo_colormap_ansi",
        tests.helpers.doubles.peri_scribe.main_show_colormap.recording_renderer(
            calls,
            strip,
        ),
    )
    result = runner.invoke(peri_scribe.main.cli, ["show-colormap"])
    assert result.exit_code == 0
    assert calls == [
        (
            peri_scribe.kml.colormap.TURBO_TRIM_FROM_START,
            peri_scribe.kml.colormap.TURBO_TRIM_FROM_END,
        ),
    ]
    assert result.stdout == f"{strip}\n"
    assert result.stderr == ""


def test_show_turbo_colormap_passes_trim_options(
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
) -> None:
    calls: list[tuple[int, int]] = []
    strip = "fake-strip"

    monkeypatch.setattr(
        peri_scribe.kml.colormap,
        "turbo_colormap_ansi",
        tests.helpers.doubles.peri_scribe.main_show_colormap.recording_renderer(
            calls,
            strip,
        ),
    )
    result = runner.invoke(
        peri_scribe.main.cli,
        ["show-colormap", "--trim-start", "16", "--trim-end", "8"],
    )
    assert result.exit_code == 0
    assert calls == [(16, 8)]


@pytest.mark.usefixtures("current_year", "validate_sources_setup")
def test_validate_sources_removes_complete_directory_when_clean(
    runner: click.testing.CliRunner,
    validate_sources_stubs: typing.Callable[
        ...,
        tests.helpers.doubles.peri_scribe.main.ValidateSourcesStubs,
    ],
) -> None:
    stubs = validate_sources_stubs(())
    result = runner.invoke(peri_scribe.main.cli, ["validate-sources"])
    assert result.exit_code == 0
    year_directory = (
        tests.helpers.factories.peri_scribe.sources.snapshots.BASE_DIRECTORY
        / "data"
        / "2026"
    )
    complete_directory = peri_scribe.sources.snapshots.validation_directory_path(
        year_directory,
    )
    assert stubs.fetch_complete_calls == [
        (tests.helpers.factories.peri_scribe.sources.snapshots.BASE_DIRECTORY, 2026),
    ]
    assert stubs.fetch_incremental_calls == [
        (tests.helpers.factories.peri_scribe.sources.snapshots.BASE_DIRECTORY, 2026),
    ]
    assert stubs.validate_calls == [year_directory]
    assert stubs.removal_calls == [complete_directory, complete_directory]


@pytest.mark.usefixtures("current_year", "validate_sources_setup")
def test_validate_sources_logs_summary_and_keeps_directory_with_problems(
    runner: click.testing.CliRunner,
    validate_sources_stubs: typing.Callable[
        ...,
        tests.helpers.doubles.peri_scribe.main.ValidateSourcesStubs,
    ],
) -> None:
    problems = (
        peri_scribe.sources.validation.FeedValidationResult(
            feed_name="Feed_0",
            complete_feature_count=3,
            missing_object_ids=frozenset({2}),
            mismatched_object_ids=frozenset({3}),
            columns_missing_from_stored=frozenset({"size"}),
        ),
    )
    stubs = validate_sources_stubs(problems)
    with structlog.testing.capture_logs() as captured:
        result = runner.invoke(peri_scribe.main.cli, ["validate-sources"])
    assert result.exit_code == 0
    year_directory = (
        tests.helpers.factories.peri_scribe.sources.snapshots.BASE_DIRECTORY
        / "data"
        / "2026"
    )
    complete_directory = peri_scribe.sources.snapshots.validation_directory_path(
        year_directory,
    )
    assert stubs.removal_calls == [complete_directory]
    problem_events = [
        event for event in captured if event["event"] == "Validation problems"
    ]
    assert len(problem_events) == 1
    assert problem_events[0]["log_level"] == "error"
    assert problem_events[0]["feed"] == "Feed_0"
    assert problem_events[0]["complete_features"] == problems[0].complete_feature_count
    assert problem_events[0]["missing_features"] == 1
    assert problem_events[0]["mismatched_features"] == 1
    assert problem_events[0]["columns_missing_from_stored"] == ["size"]
    assert any(
        event["event"] == "Validation found problems in 1 of 1 feeds"
        and event["log_level"] == "error"
        for event in captured
    )


@pytest.mark.usefixtures("current_year", "validate_sources_setup")
def test_validate_sources_stops_when_complete_fetch_fails(
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
    validate_sources_stubs: typing.Callable[
        ...,
        tests.helpers.doubles.peri_scribe.main.ValidateSourcesStubs,
    ],
) -> None:
    stubs = validate_sources_stubs(())

    fail = tests.helpers.doubles.errors.raising_stub(SystemExit("boom"))

    monkeypatch.setattr(peri_scribe.sources.fetching, "fetch_all_feeds_complete", fail)
    result = runner.invoke(peri_scribe.main.cli, ["validate-sources"])
    assert result.exit_code == 1
    assert "boom" in result.output
    year_directory = (
        tests.helpers.factories.peri_scribe.sources.snapshots.BASE_DIRECTORY
        / "data"
        / "2026"
    )
    complete_directory = peri_scribe.sources.snapshots.validation_directory_path(
        year_directory,
    )
    assert stubs.fetch_incremental_calls == []
    assert stubs.validate_calls == []
    assert stubs.removal_calls == [complete_directory]


@pytest.mark.usefixtures("current_year", "validate_sources_setup")
def test_validate_sources_stops_when_incremental_fetch_fails(
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
    validate_sources_stubs: typing.Callable[
        ...,
        tests.helpers.doubles.peri_scribe.main.ValidateSourcesStubs,
    ],
) -> None:
    stubs = validate_sources_stubs(())

    fail = tests.helpers.doubles.errors.raising_stub(SystemExit("boom"))

    monkeypatch.setattr(peri_scribe.sources.fetching, "fetch_all_feeds", fail)
    result = runner.invoke(peri_scribe.main.cli, ["validate-sources"])
    assert result.exit_code == 1
    assert "boom" in result.output
    year_directory = (
        tests.helpers.factories.peri_scribe.sources.snapshots.BASE_DIRECTORY
        / "data"
        / "2026"
    )
    complete_directory = peri_scribe.sources.snapshots.validation_directory_path(
        year_directory,
    )
    assert stubs.fetch_complete_calls == [
        (tests.helpers.factories.peri_scribe.sources.snapshots.BASE_DIRECTORY, 2026),
    ]
    assert stubs.validate_calls == []
    assert stubs.removal_calls == [complete_directory]


def test_validate_sources_help_names_current_year_default(
    runner: click.testing.CliRunner,
) -> None:
    result = runner.invoke(peri_scribe.main.cli, ["validate-sources", "--help"])
    assert result.exit_code == 0
    assert (
        f"{peri_scribe.output.DATA_DIRECTORY}/{datetime.date.today().year}"
    ) in result.output
    assert "data/<current year>" not in result.output


def test_validate_sources_rejects_missing_directory(
    runner: click.testing.CliRunner,
) -> None:
    result = runner.invoke(
        peri_scribe.main.cli,
        ["validate-sources", "no-such-directory"],
    )
    assert (
        result.exit_code == tests.helpers.peri_scribe.main.CLICK_USAGE_ERROR_EXIT_CODE
    )
    assert "does not exist" in result.output


def test_cli_help_lists_validate_sources(runner: click.testing.CliRunner) -> None:
    result = runner.invoke(peri_scribe.main.cli, ["--help"])
    assert result.exit_code == 0
    assert "validate-sources" in result.output
