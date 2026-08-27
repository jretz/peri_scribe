"""External source fetch command tests for peri_scribe.main."""

from __future__ import annotations

import pathlib
import typing

import pytest

import peri_scribe.exceptions
import peri_scribe.external_sources
import peri_scribe.main
from tests.main_stubs import BASE_DIRECTORY


if typing.TYPE_CHECKING:
    import click.testing


COMMANDS = [
    ("fetch-buildings", peri_scribe.external_sources.BUILDINGS_SOURCE),
    ("fetch-evacuations", peri_scribe.external_sources.EVACUATIONS_SOURCE),
    ("fetch-red-flag-warnings", peri_scribe.external_sources.RED_FLAG_WARNINGS_SOURCE),
    ("fetch-wui", peri_scribe.external_sources.WUI_SOURCE),
]


@pytest.mark.parametrize(("command", "source"), COMMANDS)
def test_fetch_external_source_defaults_to_current_year_directory(
    command: str,
    source: peri_scribe.external_sources.ExternalSource,
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
    current_year: typing.Iterator[None],
) -> None:
    fetched: list[tuple[object, pathlib.Path]] = []

    def fetch_external_source(
        source_arg: object,
        year_directory: pathlib.Path,
    ) -> tuple[pathlib.Path, ...]:
        fetched.append((source_arg, year_directory))
        return (pathlib.Path("/out.gpkg"),)

    monkeypatch.setattr(
        peri_scribe.external_sources,
        "fetch_external_source",
        fetch_external_source,
    )
    result = runner.invoke(peri_scribe.main.cli, [command])
    assert result.exit_code == 0
    assert fetched == [(source, BASE_DIRECTORY / "data" / "2026")]


@pytest.mark.parametrize(("command", "source"), COMMANDS)
def test_fetch_external_source_accepts_year_directory(
    command: str,
    source: peri_scribe.external_sources.ExternalSource,
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
) -> None:
    fetched: list[tuple[object, pathlib.Path]] = []

    def fetch_external_source(
        source_arg: object,
        year_directory: pathlib.Path,
    ) -> tuple[pathlib.Path, ...]:
        fetched.append((source_arg, year_directory))
        return (pathlib.Path("/out.gpkg"),)

    monkeypatch.setattr(
        peri_scribe.external_sources,
        "fetch_external_source",
        fetch_external_source,
    )
    result = runner.invoke(peri_scribe.main.cli, [command, "data/2026"])
    assert result.exit_code == 0
    assert fetched == [(source, pathlib.Path("data/2026"))]


@pytest.mark.parametrize(("command", "source"), COMMANDS)
def test_fetch_external_source_propagates_error(
    command: str,
    source: peri_scribe.external_sources.ExternalSource,
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
) -> None:
    def fail(
        _source_arg: object,
        _year_directory: pathlib.Path,
    ) -> typing.Never:
        message = "boom"
        raise peri_scribe.exceptions.ExternalDataError(message)

    monkeypatch.setattr(
        peri_scribe.external_sources,
        "fetch_external_source",
        fail,
    )
    result = runner.invoke(peri_scribe.main.cli, [command])
    assert result.exit_code == 1
    assert isinstance(result.exception, peri_scribe.exceptions.ExternalDataError)


def test_cli_help_lists_external_source_commands(
    runner: click.testing.CliRunner,
) -> None:
    result = runner.invoke(peri_scribe.main.cli, ["--help"])
    assert result.exit_code == 0
    for command, _source in COMMANDS:
        assert command in result.output
