"""CLI entrypoint and list-fires command tests for peri_scribe.main."""

from __future__ import annotations

import datetime
import pathlib
import typing

import pytest
import structlog

import peri_scribe.exceptions
import peri_scribe.feeds
import peri_scribe.fire_index
import peri_scribe.main
import peri_scribe.models
import peri_scribe.output
from tests.conftest import CLICK_USAGE_ERROR_EXIT_CODE
from tests.main_stubs import BASE_DIRECTORY


if typing.TYPE_CHECKING:
    import click.testing


@pytest.mark.usefixtures("list_fires_setup")
def test_list_fires_defaults_to_current_year_directory(
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
    current_year: typing.Iterator[None],
) -> None:
    indexed: list[pathlib.Path] = []

    def load_fire_index(
        year_directory: pathlib.Path,
    ) -> peri_scribe.models.FireIndex:
        indexed.append(year_directory)
        return peri_scribe.models.FireIndex.model_validate({
            "version": "2026-08-17",
            "fires": [],
        })

    monkeypatch.setattr(
        peri_scribe.fire_index,
        "load_fire_index",
        load_fire_index,
    )
    result = runner.invoke(peri_scribe.main.cli, ["list-fires"])
    assert result.exit_code == 0
    assert indexed == [BASE_DIRECTORY / "data" / "2026"]


def test_list_fires_help_names_current_year_default(
    runner: click.testing.CliRunner,
) -> None:
    result = runner.invoke(peri_scribe.main.cli, ["list-fires", "--help"])
    assert result.exit_code == 0
    assert (
        f"{peri_scribe.output.DATA_DIRECTORY}/{datetime.date.today().year}"
    ) in result.output
    assert "data/<current year>" not in result.output


@pytest.mark.usefixtures("list_fires_setup")
def test_list_fires_logs_fire_names_and_statuses(
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
) -> None:
    index = peri_scribe.models.FireIndex.model_validate({
        "version": "2026-08-17",
        "fires": [
            {"name": "Park Fire", "status": "active", "paths": []},
            {"name": "ALTA", "status": "inactive", "paths": []},
        ],
    })
    monkeypatch.setattr(
        peri_scribe.fire_index,
        "load_fire_index",
        lambda _year_directory: index,
    )
    with structlog.testing.capture_logs() as captured:
        result = runner.invoke(
            peri_scribe.main.cli,
            ["list-fires", "."],
        )
    assert result.exit_code == 0
    assert [(event["name"], event["status"]) for event in captured] == [
        ("Park Fire", "active"),
        ("ALTA", "inactive"),
    ]


@pytest.mark.usefixtures("list_fires_setup")
def test_list_fires_propagates_index_build_error(
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
) -> None:
    def fail(_year_directory: pathlib.Path) -> typing.Never:
        layer_name = "Mystery_Layer_0"
        raise peri_scribe.exceptions.UnknownLayerError(
            layer_name,
            pathlib.Path("fires.gpkg"),
        )

    monkeypatch.setattr(
        peri_scribe.fire_index,
        "load_fire_index",
        fail,
    )
    result = runner.invoke(peri_scribe.main.cli, ["list-fires", "."])
    assert result.exit_code == 1
    assert isinstance(result.exception, peri_scribe.exceptions.UnknownLayerError)


def test_list_fires_rejects_missing_directory(
    runner: click.testing.CliRunner,
) -> None:
    result = runner.invoke(peri_scribe.main.cli, ["list-fires", "no-such-directory"])
    assert result.exit_code == CLICK_USAGE_ERROR_EXIT_CODE
    assert "does not exist" in result.output


def test_cli_help(runner: click.testing.CliRunner) -> None:
    result = runner.invoke(peri_scribe.main.cli, ["--help"])
    assert result.exit_code == 0
    assert "systematic gathering and symbolization of fire geography" in result.output


def test_cli_invalid_log_level(runner: click.testing.CliRunner) -> None:
    result = runner.invoke(peri_scribe.main.cli, ["--log-level", "verbose"])
    assert result.exit_code == CLICK_USAGE_ERROR_EXIT_CODE
    assert "Invalid value for '--log-level'" in result.output


def test_cli_requires_subcommand(runner: click.testing.CliRunner) -> None:
    result = runner.invoke(peri_scribe.main.cli, [])
    assert result.exit_code == CLICK_USAGE_ERROR_EXIT_CODE
    assert "Commands:" in result.output
    assert "fetch" in result.output


def test_cli_configures_logging_from_log_level(
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
) -> None:
    configured_levels: list[str] = []
    monkeypatch.setattr(
        peri_scribe.output,
        "configure_logging",
        configured_levels.append,
    )
    monkeypatch.setattr(peri_scribe.feeds, "FEEDS", [])
    result = runner.invoke(
        peri_scribe.main.cli,
        ["--log-level", "DEBUG", "current-timestamps"],
    )
    assert result.exit_code == 0
    assert configured_levels == ["debug"]
