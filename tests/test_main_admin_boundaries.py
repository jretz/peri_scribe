"""Ensure-admin-boundaries command tests for peri_scribe.main."""

from __future__ import annotations

import pathlib
import typing

import peri_scribe.administrative_boundaries
import peri_scribe.exceptions
import peri_scribe.main
from tests.main_stubs import BASE_DIRECTORY


if typing.TYPE_CHECKING:
    import click.testing
    import pytest


def test_ensure_administrative_boundaries_calls_module_with_default(
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
    current_year: typing.Iterator[None],
) -> None:
    called: list[pathlib.Path | None] = []

    def ensure_administrative_boundaries(
        year_directory: pathlib.Path | None = None,
    ) -> pathlib.Path:
        called.append(year_directory)
        return pathlib.Path("/boundaries.gpkg")

    monkeypatch.setattr(
        peri_scribe.administrative_boundaries,
        "ensure_administrative_boundaries",
        ensure_administrative_boundaries,
    )
    result = runner.invoke(
        peri_scribe.main.cli,
        ["ensure-admin-boundaries"],
    )
    assert result.exit_code == 0
    assert called == [BASE_DIRECTORY / "data" / "2026"]


def test_ensure_administrative_boundaries_calls_module_with_year_directory(
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
) -> None:
    called: list[pathlib.Path | None] = []

    def ensure_administrative_boundaries(
        year_directory: pathlib.Path | None = None,
    ) -> pathlib.Path:
        called.append(year_directory)
        return pathlib.Path("/boundaries.gpkg")

    monkeypatch.setattr(
        peri_scribe.administrative_boundaries,
        "ensure_administrative_boundaries",
        ensure_administrative_boundaries,
    )
    result = runner.invoke(
        peri_scribe.main.cli,
        ["ensure-admin-boundaries", "data/2026"],
    )
    assert result.exit_code == 0
    assert called == [pathlib.Path("data/2026")]


def test_ensure_administrative_boundaries_propagates_error(
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
) -> None:
    def fail(_year_directory: pathlib.Path | None = None) -> typing.Never:
        message = "boom"
        raise peri_scribe.exceptions.AdministrativeBoundariesError(message)

    monkeypatch.setattr(
        peri_scribe.administrative_boundaries,
        "ensure_administrative_boundaries",
        fail,
    )
    result = runner.invoke(
        peri_scribe.main.cli,
        ["ensure-admin-boundaries"],
    )
    assert result.exit_code == 1
    assert isinstance(
        result.exception,
        peri_scribe.exceptions.AdministrativeBoundariesError,
    )


def test_cli_help_lists_ensure_administrative_boundaries(
    runner: click.testing.CliRunner,
) -> None:
    result = runner.invoke(peri_scribe.main.cli, ["--help"])
    assert result.exit_code == 0
    assert "ensure-admin-boundaries" in result.output
