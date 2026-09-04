"""CLI entrypoint tests for peri_scribe.main."""

from __future__ import annotations

import importlib.metadata
import typing

import pytest

import peri_scribe.main
from tests.conftest import CLICK_USAGE_ERROR_EXIT_CODE


if typing.TYPE_CHECKING:
    import click.testing


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


def test_version_prints_installed_version(
    runner: click.testing.CliRunner,
) -> None:
    result = runner.invoke(peri_scribe.main.cli, ["version"])
    assert result.exit_code == 0
    assert (
        result.output.strip()
        == f"peri_scribe v{importlib.metadata.version('peri_scribe')}"
    )


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
    assert result.output.strip() == "some_other_package v1.2.3"


def test_distribution_version_raises_without_a_package_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(peri_scribe.main, "__package__", None)
    with pytest.raises(RuntimeError, match="not imported as part of its package"):
        peri_scribe.main.distribution_version()
