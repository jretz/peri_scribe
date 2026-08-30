"""CLI entrypoint tests for peri_scribe.main."""

from __future__ import annotations

import typing

import peri_scribe.kml_template
import peri_scribe.main
import peri_scribe.output
from tests.conftest import CLICK_USAGE_ERROR_EXIT_CODE


if typing.TYPE_CHECKING:
    import click.testing
    import pytest


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
    assert "update-kmz" in result.output


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
    monkeypatch.setattr(
        peri_scribe.kml_template,
        "create_template",
        lambda **_keywords: None,
    )
    result = runner.invoke(
        peri_scribe.main.cli,
        ["--log-level", "DEBUG", "create-kml-template"],
    )
    assert result.exit_code == 0
    assert configured_levels == ["debug"]
