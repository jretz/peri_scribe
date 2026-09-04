"""Update-kmz command tests for peri_scribe.main."""

from __future__ import annotations

import datetime
import pathlib
import typing

import pytest

import peri_scribe.exceptions
import peri_scribe.fires.differential
import peri_scribe.fires.scores
import peri_scribe.main
import peri_scribe.output
import peri_scribe.sources.digests
import peri_scribe.sources.external_sources
import peri_scribe.sources.fetching
from tests.conftest import CLICK_USAGE_ERROR_EXIT_CODE
from tests.main_stubs import (
    BASE_DIRECTORY,
    UpdateKmzStubs,
)


if typing.TYPE_CHECKING:
    import click.testing


def test_update_kmz_runs_all_steps_when_fetch_changed(
    runner: click.testing.CliRunner,
    update_kmz_stubs: typing.Callable[..., UpdateKmzStubs],
) -> None:
    stubs = update_kmz_stubs(changed=True)
    result = runner.invoke(
        peri_scribe.main.cli,
        ["update-kmz", "data/2026"],
    )
    assert result.exit_code == 0
    year_directory = pathlib.Path("data/2026")
    assert stubs.external_calls == [
        (peri_scribe.sources.external_sources.BUILDINGS_SOURCE, year_directory),
        (peri_scribe.sources.external_sources.EVACUATIONS_SOURCE, year_directory),
    ]
    assert stubs.ensure_boundary_calls == [year_directory]
    assert stubs.history_calls == [year_directory]
    assert stubs.scores_calls == [year_directory]
    assert stubs.kmz_calls == [year_directory]
    assert stubs.report_calls == [year_directory]


@pytest.mark.usefixtures("current_year")
def test_update_kmz_defaults_to_current_year_directory(
    runner: click.testing.CliRunner,
    update_kmz_stubs: typing.Callable[..., UpdateKmzStubs],
) -> None:
    stubs = update_kmz_stubs(changed=True)
    result = runner.invoke(peri_scribe.main.cli, ["update-kmz"])
    assert result.exit_code == 0
    year_directory = BASE_DIRECTORY / "data" / "2026"
    assert stubs.fetch_calls == [(BASE_DIRECTORY, 2026, False)]
    assert stubs.external_calls == [
        (peri_scribe.sources.external_sources.BUILDINGS_SOURCE, year_directory),
        (peri_scribe.sources.external_sources.EVACUATIONS_SOURCE, year_directory),
    ]
    assert stubs.ensure_boundary_calls == [year_directory]
    assert stubs.history_calls == [year_directory]
    assert stubs.scores_calls == [year_directory]
    assert stubs.kmz_calls == [year_directory]
    assert stubs.report_calls == [year_directory]


@pytest.mark.usefixtures("current_year")
def test_update_kmz_fetches_external_sources_but_skips_steps_when_nothing_changed(
    runner: click.testing.CliRunner,
    update_kmz_stubs: typing.Callable[..., UpdateKmzStubs],
) -> None:
    stubs = update_kmz_stubs(changed=False)
    result = runner.invoke(peri_scribe.main.cli, ["update-kmz"])
    assert result.exit_code == 0
    year_directory = BASE_DIRECTORY / "data" / "2026"
    assert stubs.external_calls == [
        (peri_scribe.sources.external_sources.BUILDINGS_SOURCE, year_directory),
        (peri_scribe.sources.external_sources.EVACUATIONS_SOURCE, year_directory),
    ]
    assert stubs.ensure_boundary_calls == []
    assert stubs.history_calls == []
    assert stubs.scores_calls == []
    assert stubs.kmz_calls == []
    assert stubs.report_calls == []


@pytest.mark.usefixtures("current_year")
def test_update_kmz_runs_steps_when_evacuations_changed(
    runner: click.testing.CliRunner,
    update_kmz_stubs: typing.Callable[..., UpdateKmzStubs],
) -> None:
    stubs = update_kmz_stubs(changed=False, evacuations_changed=True)
    result = runner.invoke(peri_scribe.main.cli, ["update-kmz"])
    assert result.exit_code == 0
    year_directory = BASE_DIRECTORY / "data" / "2026"
    assert stubs.fetch_calls == [(BASE_DIRECTORY, 2026, False)]
    assert stubs.external_calls == [
        (peri_scribe.sources.external_sources.BUILDINGS_SOURCE, year_directory),
        (peri_scribe.sources.external_sources.EVACUATIONS_SOURCE, year_directory),
    ]
    assert stubs.ensure_boundary_calls == [year_directory]
    assert stubs.history_calls == [year_directory]
    assert stubs.scores_calls == [year_directory]
    assert stubs.kmz_calls == [year_directory]
    assert stubs.report_calls == [year_directory]


def test_stored_evacuations_digest_uses_evacuations_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = pathlib.Path("/data/2026/sources/evacuations.gpkg")
    monkeypatch.setattr(
        peri_scribe.sources.external_sources,
        "output_path",
        lambda _year_directory, _source: output,
    )
    digests: list[tuple[pathlib.Path, str]] = []

    def stored_geopackage_digest(
        path: pathlib.Path,
        layer_name: str,
    ) -> str | None:
        digests.append((path, layer_name))
        return "digest"

    monkeypatch.setattr(
        peri_scribe.sources.digests,
        "stored_geopackage_digest",
        stored_geopackage_digest,
    )
    result = peri_scribe.main.stored_evacuations_digest(
        pathlib.Path("/data/2026"),
    )
    assert result == "digest"
    assert digests == [(output, "evacuations")]


@pytest.mark.usefixtures("current_year")
def test_update_kmz_force_fetches_feeds_in_full_and_runs_steps_when_unchanged(
    runner: click.testing.CliRunner,
    update_kmz_stubs: typing.Callable[..., UpdateKmzStubs],
) -> None:
    stubs = update_kmz_stubs(changed=False)
    result = runner.invoke(
        peri_scribe.main.cli,
        ["update-kmz", "--force"],
    )
    assert result.exit_code == 0
    year_directory = BASE_DIRECTORY / "data" / "2026"
    assert stubs.fetch_calls == [(BASE_DIRECTORY, 2026, True)]
    assert stubs.ensure_boundary_calls == [year_directory]
    assert stubs.history_calls == [year_directory]
    assert stubs.scores_calls == [year_directory]
    assert stubs.kmz_calls == [year_directory]
    assert stubs.report_calls == [year_directory]


@pytest.mark.usefixtures("current_year")
def test_update_kmz_stops_when_fetch_fails(
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
    update_kmz_stubs: typing.Callable[..., UpdateKmzStubs],
) -> None:
    def fail(
        _base_directory: pathlib.Path,
        *,
        year: int,
        full: bool = False,
    ) -> typing.Never:
        message = "boom"
        raise SystemExit(message)

    stubs = update_kmz_stubs(changed=True)
    monkeypatch.setattr(peri_scribe.sources.fetching, "fetch_all_feeds", fail)
    result = runner.invoke(
        peri_scribe.main.cli,
        ["update-kmz", "--force"],
    )
    assert result.exit_code == 1
    assert "boom" in result.output
    assert stubs.external_calls == []
    assert stubs.ensure_boundary_calls == []
    assert stubs.history_calls == []
    assert stubs.scores_calls == []
    assert stubs.kmz_calls == []
    assert stubs.report_calls == []


@pytest.mark.usefixtures("current_year")
def test_update_kmz_stops_when_external_source_fetch_fails(
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
    update_kmz_stubs: typing.Callable[..., UpdateKmzStubs],
) -> None:
    def fail(
        _source: object,
        _year_directory: pathlib.Path,
    ) -> typing.Never:
        message = "boom"
        raise peri_scribe.exceptions.ExternalDataError(message)

    stubs = update_kmz_stubs(changed=True)
    monkeypatch.setattr(peri_scribe.main, "fetch_external_source", fail)
    result = runner.invoke(peri_scribe.main.cli, ["update-kmz"])
    assert result.exit_code == 1
    assert isinstance(result.exception, peri_scribe.exceptions.ExternalDataError)
    assert stubs.ensure_boundary_calls == []
    assert stubs.history_calls == []
    assert stubs.scores_calls == []
    assert stubs.kmz_calls == []
    assert stubs.report_calls == []


@pytest.mark.usefixtures("current_year")
def test_update_kmz_stops_when_a_step_fails(
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
    update_kmz_stubs: typing.Callable[..., UpdateKmzStubs],
) -> None:
    def fail(_year_directory: pathlib.Path) -> typing.Never:
        message = "boom"
        raise ValueError(message)

    stubs = update_kmz_stubs(changed=True)
    monkeypatch.setattr(
        peri_scribe.fires.differential,
        "write_history_of_differential_geography",
        fail,
    )
    result = runner.invoke(peri_scribe.main.cli, ["update-kmz"])
    assert result.exit_code == 1
    assert isinstance(result.exception, ValueError)
    assert stubs.ensure_boundary_calls == [BASE_DIRECTORY / "data" / "2026"]
    assert stubs.history_calls == []
    assert stubs.scores_calls == []
    assert stubs.kmz_calls == []
    assert stubs.report_calls == []


@pytest.mark.usefixtures("current_year")
def test_update_kmz_stops_when_scoring_fails(
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
    update_kmz_stubs: typing.Callable[..., UpdateKmzStubs],
) -> None:
    def fail(_year_directory: pathlib.Path) -> typing.Never:
        message = "boom"
        raise ValueError(message)

    stubs = update_kmz_stubs(changed=True)
    monkeypatch.setattr(peri_scribe.fires.scores, "score_fires", fail)
    result = runner.invoke(peri_scribe.main.cli, ["update-kmz"])
    assert result.exit_code == 1
    assert isinstance(result.exception, ValueError)
    assert stubs.ensure_boundary_calls == [BASE_DIRECTORY / "data" / "2026"]
    assert stubs.history_calls == [BASE_DIRECTORY / "data" / "2026"]
    assert stubs.scores_calls == []
    assert stubs.kmz_calls == []
    assert stubs.report_calls == []


def test_update_kmz_help_names_current_year_default(
    runner: click.testing.CliRunner,
) -> None:
    result = runner.invoke(peri_scribe.main.cli, ["update-kmz", "--help"])
    assert result.exit_code == 0
    assert (
        f"{peri_scribe.output.DATA_DIRECTORY}/{datetime.date.today().year}"
    ) in result.output
    assert "data/<current year>" not in result.output


def test_update_kmz_rejects_missing_directory(
    runner: click.testing.CliRunner,
) -> None:
    result = runner.invoke(
        peri_scribe.main.cli,
        ["update-kmz", "no-such-directory"],
    )
    assert result.exit_code == CLICK_USAGE_ERROR_EXIT_CODE
    assert "does not exist" in result.output


def test_cli_help_lists_update_kmz(
    runner: click.testing.CliRunner,
) -> None:
    result = runner.invoke(peri_scribe.main.cli, ["--help"])
    assert result.exit_code == 0
    assert "update-kmz" in result.output
