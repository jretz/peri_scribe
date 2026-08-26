"""Create-kml-template and create-kml command tests for peri_scribe.main."""

from __future__ import annotations

import pathlib
import typing

import peri_scribe.kml
import peri_scribe.kml_template
import peri_scribe.main
from tests.main_stubs import BASE_DIRECTORY


if typing.TYPE_CHECKING:
    import click.testing
    import pytest


def test_create_kml_template_calls_module(
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
) -> None:
    calls: list[bool] = []

    def create_template(*, force: bool = False) -> pathlib.Path:
        calls.append(force)
        return pathlib.Path("/templates/PeriScribe Template.kml")

    monkeypatch.setattr(
        peri_scribe.kml_template,
        "create_template",
        create_template,
    )
    result = runner.invoke(peri_scribe.main.cli, ["create-kml-template"])
    assert result.exit_code == 0
    assert calls == [False]


def test_create_kml_template_force_flag(
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
) -> None:
    calls: list[bool] = []

    def create_template(*, force: bool = False) -> pathlib.Path:
        calls.append(force)
        return pathlib.Path("/templates/PeriScribe Template.kml")

    monkeypatch.setattr(
        peri_scribe.kml_template,
        "create_template",
        create_template,
    )
    result = runner.invoke(
        peri_scribe.main.cli,
        ["create-kml-template", "--force"],
    )
    assert result.exit_code == 0
    assert calls == [True]


def test_create_kml_template_skips_success_log_when_not_written(
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
) -> None:
    def create_template(*, force: bool = False) -> None:
        return None

    monkeypatch.setattr(
        peri_scribe.kml_template,
        "create_template",
        create_template,
    )
    result = runner.invoke(peri_scribe.main.cli, ["create-kml-template"])
    assert result.exit_code == 0


def test_cli_help_lists_create_kml_template(
    runner: click.testing.CliRunner,
) -> None:
    result = runner.invoke(peri_scribe.main.cli, ["--help"])
    assert result.exit_code == 0
    assert "create-kml-template" in result.output


def test_create_kml_builds_for_directory(
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
) -> None:
    calls: list[pathlib.Path] = []

    def create_kmz(year_directory: pathlib.Path) -> pathlib.Path:
        calls.append(year_directory)
        return pathlib.Path("/maps/PeriScribe Fires 2026.kmz")

    monkeypatch.setattr(peri_scribe.kml, "create_kmz", create_kmz)
    result = runner.invoke(
        peri_scribe.main.cli,
        ["create-kml", "data/2026"],
    )
    assert result.exit_code == 0
    assert calls == [pathlib.Path("data/2026")]


def test_create_kml_defaults_to_current_year_directory(
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
    current_year: typing.Iterator[None],
) -> None:
    calls: list[pathlib.Path] = []

    def create_kmz(year_directory: pathlib.Path) -> pathlib.Path:
        calls.append(year_directory)
        return pathlib.Path("/maps/PeriScribe Fires 2026.kmz")

    monkeypatch.setattr(peri_scribe.kml, "create_kmz", create_kmz)
    result = runner.invoke(peri_scribe.main.cli, ["create-kml"])
    assert result.exit_code == 0
    assert calls == [BASE_DIRECTORY / "data" / "2026"]


def test_cli_help_lists_create_kml(
    runner: click.testing.CliRunner,
) -> None:
    result = runner.invoke(peri_scribe.main.cli, ["--help"])
    assert result.exit_code == 0
    assert "create-kml" in result.output
