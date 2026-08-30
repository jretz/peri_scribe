"""Create-kml-template command tests for peri_scribe.main."""

from __future__ import annotations

import pathlib
import typing

import peri_scribe.kml_template
import peri_scribe.main


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
