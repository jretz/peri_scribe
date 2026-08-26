"""Derive-geo-history command tests for peri_scribe.main."""

from __future__ import annotations

import pathlib
import typing

import peri_scribe.fire_differential
import peri_scribe.main
from tests.main_stubs import BASE_DIRECTORY


if typing.TYPE_CHECKING:
    import click.testing
    import pytest


def test_derive_geo_history_builds_history_for_directory(
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
) -> None:
    calls: list[pathlib.Path] = []

    def write_history_of_differential_geography(
        year_directory: pathlib.Path,
    ) -> pathlib.Path:
        calls.append(year_directory)
        return pathlib.Path("/differential.gpkg")

    monkeypatch.setattr(
        peri_scribe.fire_differential,
        "write_history_of_differential_geography",
        write_history_of_differential_geography,
    )
    result = runner.invoke(
        peri_scribe.main.cli,
        ["derive-geo-history", "data/2026"],
    )
    assert result.exit_code == 0
    assert calls == [pathlib.Path("data/2026")]


def test_derive_geo_history_defaults_to_current_year_directory(
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
    current_year: typing.Iterator[None],
) -> None:
    calls: list[pathlib.Path] = []

    def write_history_of_differential_geography(
        year_directory: pathlib.Path,
    ) -> pathlib.Path:
        calls.append(year_directory)
        return pathlib.Path("/differential.gpkg")

    monkeypatch.setattr(
        peri_scribe.fire_differential,
        "write_history_of_differential_geography",
        write_history_of_differential_geography,
    )
    result = runner.invoke(peri_scribe.main.cli, ["derive-geo-history"])
    assert result.exit_code == 0
    assert calls == [BASE_DIRECTORY / "data" / "2026"]


def test_cli_help_lists_derive_geo_history(
    runner: click.testing.CliRunner,
) -> None:
    result = runner.invoke(peri_scribe.main.cli, ["--help"])
    assert result.exit_code == 0
    assert "derive-geo-history" in result.output
