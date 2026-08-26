"""Full-pipeline command tests for peri_scribe.main."""

from __future__ import annotations

import datetime
import pathlib
import typing

import pytest

import peri_scribe.fetching
import peri_scribe.fire_differential
import peri_scribe.main
import peri_scribe.output
from tests.conftest import CLICK_USAGE_ERROR_EXIT_CODE
from tests.main_stubs import (
    BASE_DIRECTORY,
    FullPipelineStubs,
)


if typing.TYPE_CHECKING:
    import click.testing


def test_full_pipeline_runs_all_steps_when_fetch_changed(
    runner: click.testing.CliRunner,
    full_pipeline_stubs: typing.Callable[..., FullPipelineStubs],
) -> None:
    stubs = full_pipeline_stubs(changed=True)
    result = runner.invoke(
        peri_scribe.main.cli,
        ["full-pipeline", "data/2026"],
    )
    assert result.exit_code == 0
    year_directory = pathlib.Path("data/2026")
    assert stubs.ensure_boundary_calls == [None]
    assert stubs.history_calls == [year_directory]
    assert stubs.kmz_calls == [year_directory]


@pytest.mark.usefixtures("current_year")
def test_full_pipeline_defaults_to_current_year_directory(
    runner: click.testing.CliRunner,
    full_pipeline_stubs: typing.Callable[..., FullPipelineStubs],
) -> None:
    stubs = full_pipeline_stubs(changed=True)
    result = runner.invoke(peri_scribe.main.cli, ["full-pipeline"])
    assert result.exit_code == 0
    year_directory = BASE_DIRECTORY / "data" / "2026"
    assert stubs.fetch_calls == [(BASE_DIRECTORY, 2026, False)]
    assert stubs.ensure_boundary_calls == [None]
    assert stubs.history_calls == [year_directory]
    assert stubs.kmz_calls == [year_directory]


@pytest.mark.usefixtures("current_year")
def test_full_pipeline_skips_remaining_steps_when_fetch_unchanged(
    runner: click.testing.CliRunner,
    full_pipeline_stubs: typing.Callable[..., FullPipelineStubs],
) -> None:
    stubs = full_pipeline_stubs(changed=False)
    result = runner.invoke(peri_scribe.main.cli, ["full-pipeline"])
    assert result.exit_code == 0
    assert stubs.ensure_boundary_calls == []
    assert stubs.history_calls == []
    assert stubs.kmz_calls == []


@pytest.mark.usefixtures("current_year")
def test_full_pipeline_force_runs_remaining_steps_when_fetch_unchanged(
    runner: click.testing.CliRunner,
    full_pipeline_stubs: typing.Callable[..., FullPipelineStubs],
) -> None:
    stubs = full_pipeline_stubs(changed=False)
    result = runner.invoke(
        peri_scribe.main.cli,
        ["full-pipeline", "--force"],
    )
    assert result.exit_code == 0
    year_directory = BASE_DIRECTORY / "data" / "2026"
    assert stubs.ensure_boundary_calls == [None]
    assert stubs.history_calls == [year_directory]
    assert stubs.kmz_calls == [year_directory]


@pytest.mark.usefixtures("current_year")
def test_full_pipeline_full_fetches_every_feed_in_full(
    runner: click.testing.CliRunner,
    full_pipeline_stubs: typing.Callable[..., FullPipelineStubs],
) -> None:
    stubs = full_pipeline_stubs(changed=True)
    result = runner.invoke(
        peri_scribe.main.cli,
        ["full-pipeline", "--full"],
    )
    assert result.exit_code == 0
    year_directory = BASE_DIRECTORY / "data" / "2026"
    assert stubs.fetch_calls == [(BASE_DIRECTORY, 2026, True)]
    assert stubs.ensure_boundary_calls == [None]
    assert stubs.history_calls == [year_directory]
    assert stubs.kmz_calls == [year_directory]


@pytest.mark.usefixtures("current_year")
def test_full_pipeline_stops_when_fetch_fails(
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
    full_pipeline_stubs: typing.Callable[..., FullPipelineStubs],
) -> None:
    def fail(
        _base_directory: pathlib.Path,
        *,
        year: int,
        full: bool = False,
    ) -> typing.Never:
        message = "boom"
        raise SystemExit(message)

    stubs = full_pipeline_stubs(changed=True)
    monkeypatch.setattr(peri_scribe.fetching, "fetch_all_feeds", fail)
    result = runner.invoke(
        peri_scribe.main.cli,
        ["full-pipeline", "--force"],
    )
    assert result.exit_code == 1
    assert "boom" in result.output
    assert stubs.ensure_boundary_calls == []
    assert stubs.history_calls == []
    assert stubs.kmz_calls == []


@pytest.mark.usefixtures("current_year")
def test_full_pipeline_stops_when_a_step_fails(
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
    full_pipeline_stubs: typing.Callable[..., FullPipelineStubs],
) -> None:
    def fail(_year_directory: pathlib.Path) -> typing.Never:
        message = "boom"
        raise ValueError(message)

    stubs = full_pipeline_stubs(changed=True)
    monkeypatch.setattr(
        peri_scribe.fire_differential,
        "write_history_of_differential_geography",
        fail,
    )
    result = runner.invoke(peri_scribe.main.cli, ["full-pipeline"])
    assert result.exit_code == 1
    assert isinstance(result.exception, ValueError)
    assert stubs.ensure_boundary_calls == [None]
    assert stubs.history_calls == []
    assert stubs.kmz_calls == []


def test_full_pipeline_help_names_current_year_default(
    runner: click.testing.CliRunner,
) -> None:
    result = runner.invoke(peri_scribe.main.cli, ["full-pipeline", "--help"])
    assert result.exit_code == 0
    assert (
        f"{peri_scribe.output.DATA_DIRECTORY}/{datetime.date.today().year}"
    ) in result.output
    assert "data/<current year>" not in result.output


def test_full_pipeline_rejects_missing_directory(
    runner: click.testing.CliRunner,
) -> None:
    result = runner.invoke(
        peri_scribe.main.cli,
        ["full-pipeline", "no-such-directory"],
    )
    assert result.exit_code == CLICK_USAGE_ERROR_EXIT_CODE
    assert "does not exist" in result.output


def test_cli_help_lists_full_pipeline(
    runner: click.testing.CliRunner,
) -> None:
    result = runner.invoke(peri_scribe.main.cli, ["--help"])
    assert result.exit_code == 0
    assert "full-pipeline" in result.output
