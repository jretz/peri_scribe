"""CLI entrypoint tests for peri_scribe.main."""

from __future__ import annotations

import datetime
import importlib.metadata
import json
import pathlib
import typing

import pytest
import structlog

import peri_scribe.logging
import peri_scribe.main
from peri_scribe.units import units
from tests.conftest import CLICK_USAGE_ERROR_EXIT_CODE


if typing.TYPE_CHECKING:
    import click.testing

    import tests.main_stubs


def test_cli_help(runner: click.testing.CliRunner) -> None:
    result = runner.invoke(peri_scribe.main.cli, ["--help"])
    assert result.exit_code == 0
    assert "systematic gathering and symbolization of fire geography" in result.output


@pytest.mark.parametrize("option", ["--stderr-log-level", "--file-log-level"])
def test_cli_invalid_log_level(runner: click.testing.CliRunner, option: str) -> None:
    result = runner.invoke(peri_scribe.main.cli, [option, "verbose"])
    assert result.exit_code == CLICK_USAGE_ERROR_EXIT_CODE
    assert f"Invalid value for '{option}'" in result.output


def test_cli_requires_subcommand(runner: click.testing.CliRunner) -> None:
    result = runner.invoke(peri_scribe.main.cli, [])
    assert result.exit_code == CLICK_USAGE_ERROR_EXIT_CODE
    assert "Commands:" in result.output
    assert "run" in result.output


def test_version_prints_installed_version(
    runner: click.testing.CliRunner,
) -> None:
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

    def record_lookup(name: str) -> str:
        looked_up_distributions.append(name)
        return "1.2.3"

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
    [
        (["run", "--list-stages"], {"list_stages": True}),
        (["validate-sources"], {}),
    ],
)
def test_cli_logs_command_boundaries_and_elapsed_seconds(
    runner: click.testing.CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    cli_log_output: structlog.testing.LogCapture,
    validate_sources_stubs: typing.Callable[..., tests.main_stubs.ValidateSourcesStubs],
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
    validate_sources_stubs: typing.Callable[..., tests.main_stubs.ValidateSourcesStubs],
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
    run_stubs: typing.Callable[..., tests.main_stubs.RunStubs],
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
    assert result.exit_code == CLICK_USAGE_ERROR_EXIT_CODE
    path = next((tmp_path / "logs").glob("*.jsonl"))
    contents = path.read_text()
    assert json.loads(contents.splitlines()[-1])["status"] == "failed"
    structlog.get_logger().info("Outside the command")
    assert runner.invoke(peri_scribe.main.cli, ["version"]).exit_code == 0
    assert path.read_text() == contents
