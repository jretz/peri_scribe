"""Index-fire-sources command tests for peri_scribe.main."""

from __future__ import annotations

import datetime
import pathlib
import typing

import peri_scribe.fire_index
import peri_scribe.main
import peri_scribe.output
from tests.conftest import CLICK_USAGE_ERROR_EXIT_CODE
from tests.main_stubs import BASE_DIRECTORY


if typing.TYPE_CHECKING:
    import click.testing
    import pytest


def test_index_fire_sources_defaults_to_current_year_directory(
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
    current_year: typing.Iterator[None],
) -> None:
    indexed: list[pathlib.Path] = []
    monkeypatch.setattr(
        peri_scribe.fire_index,
        "index_fire_sources",
        indexed.append,
    )
    result = runner.invoke(peri_scribe.main.cli, ["index-fire-sources"])
    assert result.exit_code == 0
    assert indexed == [BASE_DIRECTORY / "data" / "2026"]


def test_index_fire_sources_help_names_current_year_default(
    runner: click.testing.CliRunner,
) -> None:
    result = runner.invoke(
        peri_scribe.main.cli,
        ["index-fire-sources", "--help"],
    )
    assert result.exit_code == 0
    assert (
        f"{peri_scribe.output.DATA_DIRECTORY}/{datetime.date.today().year}"
    ) in result.output
    assert "data/<current year>" not in result.output


def test_index_fire_sources_rejects_missing_directory(
    runner: click.testing.CliRunner,
) -> None:
    result = runner.invoke(
        peri_scribe.main.cli,
        ["index-fire-sources", "no-such-directory"],
    )
    assert result.exit_code == CLICK_USAGE_ERROR_EXIT_CODE
    assert "does not exist" in result.output


def test_index_fire_sources_builds_index(
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
) -> None:
    monkeypatch.setattr(
        peri_scribe.output,
        "configure_logging",
        lambda log_level: log_level,
    )
    indexed: list[pathlib.Path] = []
    monkeypatch.setattr(
        peri_scribe.fire_index,
        "index_fire_sources",
        indexed.append,
    )
    result = runner.invoke(
        peri_scribe.main.cli,
        ["index-fire-sources", "data/2026"],
    )
    assert result.exit_code == 0
    assert indexed == [pathlib.Path("data/2026")]
