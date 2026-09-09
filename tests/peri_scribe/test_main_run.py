"""Run command tests for peri_scribe.main."""

from __future__ import annotations

import datetime
import pathlib
import typing

import click
import click.testing
import pytest

import peri_scribe.exceptions
import peri_scribe.fires.differential
import peri_scribe.fires.scores
import peri_scribe.main
import peri_scribe.output
import peri_scribe.sources.digests
import peri_scribe.sources.external_sources
import peri_scribe.sources.fetching
import peri_scribe.sources.full_fetch_state
from tests.conftest import CLICK_USAGE_ERROR_EXIT_CODE
from tests.main_stubs import (
    BASE_DIRECTORY,
    RunStubs,
)


def test_run_runs_all_stages_when_fetch_changed(
    runner: click.testing.CliRunner,
    run_stubs: typing.Callable[..., RunStubs],
) -> None:
    stubs = run_stubs(changed=True)
    result = runner.invoke(
        peri_scribe.main.cli,
        ["run", "data/2026"],
    )
    assert result.exit_code == 0
    year_directory = pathlib.Path("data/2026")
    assert stubs.external_calls == [
        (source, year_directory)
        for source in peri_scribe.sources.external_sources.EXTERNAL_SOURCES
    ]
    assert stubs.ensure_boundary_calls == [year_directory]
    assert stubs.history_calls == [year_directory]
    assert stubs.scores_calls == [year_directory]
    assert stubs.kmz_calls == [year_directory]
    assert stubs.report_calls == [year_directory]


@pytest.mark.usefixtures("current_year")
def test_run_defaults_to_current_year_directory(
    runner: click.testing.CliRunner,
    run_stubs: typing.Callable[..., RunStubs],
) -> None:
    stubs = run_stubs(changed=True)
    result = runner.invoke(peri_scribe.main.cli, ["run"])
    assert result.exit_code == 0
    year_directory = BASE_DIRECTORY / "data" / "2026"
    assert stubs.fetch_calls == [(BASE_DIRECTORY, 2026, False)]
    assert stubs.external_calls == [
        (source, year_directory)
        for source in peri_scribe.sources.external_sources.EXTERNAL_SOURCES
    ]
    assert stubs.ensure_boundary_calls == [year_directory]
    assert stubs.history_calls == [year_directory]
    assert stubs.scores_calls == [year_directory]
    assert stubs.kmz_calls == [year_directory]
    assert stubs.report_calls == [year_directory]


@pytest.mark.usefixtures("current_year")
def test_run_fetches_external_sources_but_skips_later_stages_when_nothing_changed(
    runner: click.testing.CliRunner,
    run_stubs: typing.Callable[..., RunStubs],
) -> None:
    stubs = run_stubs(changed=False)
    result = runner.invoke(peri_scribe.main.cli, ["run"])
    assert result.exit_code == 0
    year_directory = BASE_DIRECTORY / "data" / "2026"
    assert stubs.external_calls == [
        (source, year_directory)
        for source in peri_scribe.sources.external_sources.EXTERNAL_SOURCES
    ]
    assert stubs.ensure_boundary_calls == [year_directory]
    assert stubs.history_calls == []
    assert stubs.scores_calls == []
    assert stubs.kmz_calls == []
    assert stubs.report_calls == []


@pytest.mark.usefixtures("current_year")
def test_run_runs_stages_when_evacuations_changed(
    runner: click.testing.CliRunner,
    run_stubs: typing.Callable[..., RunStubs],
) -> None:
    stubs = run_stubs(changed=False, evacuations_changed=True)
    result = runner.invoke(peri_scribe.main.cli, ["run"])
    assert result.exit_code == 0
    year_directory = BASE_DIRECTORY / "data" / "2026"
    assert stubs.fetch_calls == [(BASE_DIRECTORY, 2026, False)]
    assert stubs.external_calls == [
        (source, year_directory)
        for source in peri_scribe.sources.external_sources.EXTERNAL_SOURCES
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
def test_run_unconditional_runs_stages_when_unchanged(
    runner: click.testing.CliRunner,
    run_stubs: typing.Callable[..., RunStubs],
) -> None:
    stubs = run_stubs(changed=False)
    result = runner.invoke(
        peri_scribe.main.cli,
        ["run", "--unconditional"],
    )
    assert result.exit_code == 0
    year_directory = BASE_DIRECTORY / "data" / "2026"
    assert stubs.fetch_calls == [(BASE_DIRECTORY, 2026, False)]
    assert stubs.write_state_calls == []
    assert stubs.ensure_boundary_calls == [year_directory]
    assert stubs.history_calls == [year_directory]
    assert stubs.scores_calls == [year_directory]
    assert stubs.kmz_calls == [year_directory]
    assert stubs.report_calls == [year_directory]


@pytest.mark.usefixtures("current_year")
def test_run_full_fetch_interval_zero_hours_fetches_in_full_and_records_state(
    runner: click.testing.CliRunner,
    run_stubs: typing.Callable[..., RunStubs],
) -> None:
    stubs = run_stubs(changed=False)
    result = runner.invoke(
        peri_scribe.main.cli,
        ["run", "--full-fetch-interval", "0h"],
    )
    assert result.exit_code == 0
    year_directory = BASE_DIRECTORY / "data" / "2026"
    assert stubs.fetch_calls == [(BASE_DIRECTORY, 2026, True)]
    assert stubs.write_state_calls == [
        (
            year_directory / "sources" / "fetch_state.json",
            datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
        ),
    ]
    assert stubs.ensure_boundary_calls == [year_directory]


@pytest.mark.usefixtures("current_year")
def test_run_full_fetch_interval_zero_days_fetches_in_full(
    runner: click.testing.CliRunner,
    run_stubs: typing.Callable[..., RunStubs],
) -> None:
    stubs = run_stubs(changed=False)
    result = runner.invoke(
        peri_scribe.main.cli,
        ["run", "--full-fetch-interval", "0d"],
    )
    assert result.exit_code == 0
    assert stubs.fetch_calls == [(BASE_DIRECTORY, 2026, True)]


@pytest.mark.usefixtures("current_year")
def test_run_full_fetch_interval_fetches_in_full_without_stored_state(
    runner: click.testing.CliRunner,
    run_stubs: typing.Callable[..., RunStubs],
) -> None:
    stubs = run_stubs(changed=False)
    result = runner.invoke(
        peri_scribe.main.cli,
        ["run", "--full-fetch-interval", "12h"],
    )
    assert result.exit_code == 0
    year_directory = BASE_DIRECTORY / "data" / "2026"
    assert stubs.fetch_calls == [(BASE_DIRECTORY, 2026, True)]
    assert stubs.write_state_calls == [
        (
            year_directory / "sources" / "fetch_state.json",
            datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
        ),
    ]


@pytest.mark.usefixtures("current_year")
def test_run_full_fetch_interval_skips_full_fetch_when_interval_not_elapsed(
    runner: click.testing.CliRunner,
    run_stubs: typing.Callable[..., RunStubs],
) -> None:
    stubs = run_stubs(
        changed=False,
        stored_state=peri_scribe.sources.full_fetch_state.FullFetchState(
            last_full_fetch=(
                datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
                - datetime.timedelta(hours=2)
            ),
        ),
    )
    result = runner.invoke(
        peri_scribe.main.cli,
        ["run", "--full-fetch-interval", "12h"],
    )
    assert result.exit_code == 0
    assert stubs.fetch_calls == [(BASE_DIRECTORY, 2026, False)]
    assert stubs.write_state_calls == []


@pytest.mark.usefixtures("current_year")
def test_run_full_fetch_interval_fetches_in_full_when_interval_elapsed(
    runner: click.testing.CliRunner,
    run_stubs: typing.Callable[..., RunStubs],
) -> None:
    stubs = run_stubs(
        changed=False,
        stored_state=peri_scribe.sources.full_fetch_state.FullFetchState(
            last_full_fetch=(
                datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
                - datetime.timedelta(hours=13)
            ),
        ),
    )
    result = runner.invoke(
        peri_scribe.main.cli,
        ["run", "--full-fetch-interval", "12h"],
    )
    assert result.exit_code == 0
    year_directory = BASE_DIRECTORY / "data" / "2026"
    assert stubs.fetch_calls == [(BASE_DIRECTORY, 2026, True)]
    assert stubs.write_state_calls == [
        (
            year_directory / "sources" / "fetch_state.json",
            datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
        ),
    ]


@pytest.mark.usefixtures("current_year")
def test_run_full_fetch_interval_accepts_days(
    runner: click.testing.CliRunner,
    run_stubs: typing.Callable[..., RunStubs],
) -> None:
    stubs = run_stubs(
        changed=False,
        stored_state=peri_scribe.sources.full_fetch_state.FullFetchState(
            last_full_fetch=(
                datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
                - datetime.timedelta(hours=12)
            ),
        ),
    )
    result = runner.invoke(
        peri_scribe.main.cli,
        ["run", "--full-fetch-interval", "1d"],
    )
    assert result.exit_code == 0
    assert stubs.fetch_calls == [(BASE_DIRECTORY, 2026, False)]
    assert stubs.write_state_calls == []


@pytest.mark.usefixtures("current_year")
def test_run_full_fetch_interval_with_unconditional_runs_all_stages(
    runner: click.testing.CliRunner,
    run_stubs: typing.Callable[..., RunStubs],
) -> None:
    stubs = run_stubs(changed=False)
    result = runner.invoke(
        peri_scribe.main.cli,
        ["run", "--full-fetch-interval", "0h", "--unconditional"],
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
def test_run_full_fetch_interval_does_not_record_state_when_fetch_fails(
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
    run_stubs: typing.Callable[..., RunStubs],
) -> None:
    def fail(
        _base_directory: pathlib.Path,
        *,
        year: int,
        full: bool = False,
    ) -> typing.Never:
        message = "boom"
        raise SystemExit(message)

    stubs = run_stubs(changed=True)
    monkeypatch.setattr(peri_scribe.sources.fetching, "fetch_all_feeds", fail)
    result = runner.invoke(
        peri_scribe.main.cli,
        ["run", "--full-fetch-interval", "0h"],
    )
    assert result.exit_code == 1
    assert "boom" in result.output
    assert stubs.write_state_calls == []


@pytest.mark.usefixtures("current_year")
def test_run_stops_when_fetch_state_is_malformed(
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
    run_stubs: typing.Callable[..., RunStubs],
) -> None:
    def read_state(_path: pathlib.Path) -> typing.Never:
        message = "boom"
        raise ValueError(message)

    stubs = run_stubs(changed=True)
    monkeypatch.setattr(
        peri_scribe.sources.full_fetch_state,
        "read_state",
        read_state,
    )
    result = runner.invoke(
        peri_scribe.main.cli,
        ["run", "--full-fetch-interval", "12h"],
    )
    assert result.exit_code == 1
    assert isinstance(result.exception, ValueError)
    assert stubs.fetch_calls == []


def test_duration_converts_whole_hours_and_days() -> None:
    duration = peri_scribe.main.Duration()
    assert duration.convert("0h", None, None) == datetime.timedelta(0)
    assert duration.convert("12h", None, None) == datetime.timedelta(hours=12)
    assert duration.convert("24h", None, None) == datetime.timedelta(hours=24)
    assert duration.convert("1d", None, None) == datetime.timedelta(days=1)
    assert duration.convert("3d", None, None) == datetime.timedelta(days=3)
    assert duration.convert("0d", None, None) == datetime.timedelta(0)


def test_duration_accepts_an_already_converted_timedelta() -> None:
    duration = peri_scribe.main.Duration()
    value = datetime.timedelta(hours=12)
    assert duration.convert(value, None, None) is value


@pytest.mark.parametrize("value", [None, 12, b"12h"])
def test_duration_rejects_values_that_are_not_duration_text(value: object) -> None:
    duration = peri_scribe.main.Duration()
    with pytest.raises(click.BadParameter):
        duration.convert(value, None, None)


def test_duration_rejects_out_of_range_durations() -> None:
    duration = peri_scribe.main.Duration()
    with pytest.raises(click.BadParameter):
        duration.convert("9999999999999h", None, None)


@pytest.mark.parametrize(
    "value",
    ["-1h", "1.5h", "12", "1w", "1d12h", "1H", "h", ""],
)
def test_run_rejects_invalid_full_fetch_intervals(
    runner: click.testing.CliRunner,
    value: str,
) -> None:
    result = runner.invoke(
        peri_scribe.main.cli,
        ["run", "--full-fetch-interval", value],
    )
    assert result.exit_code == CLICK_USAGE_ERROR_EXIT_CODE
    assert "Invalid value for '--full-fetch-interval'" in result.output


def test_run_help_describes_full_fetch_interval_and_unconditional(
    runner: click.testing.CliRunner,
) -> None:
    result = runner.invoke(peri_scribe.main.cli, ["run", "--help"])
    assert result.exit_code == 0
    assert "--full-fetch-interval DURATION" in result.output
    assert "--unconditional" in result.output


@pytest.mark.usefixtures("current_year")
def test_run_stops_when_fetch_fails(
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
    run_stubs: typing.Callable[..., RunStubs],
) -> None:
    def fail(
        _base_directory: pathlib.Path,
        *,
        year: int,
        full: bool = False,
    ) -> typing.Never:
        message = "boom"
        raise SystemExit(message)

    stubs = run_stubs(changed=True)
    monkeypatch.setattr(peri_scribe.sources.fetching, "fetch_all_feeds", fail)
    result = runner.invoke(
        peri_scribe.main.cli,
        ["run", "--unconditional"],
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
def test_run_stops_when_external_source_fetch_fails(
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
    run_stubs: typing.Callable[..., RunStubs],
) -> None:
    def fail(
        _source: object,
        _year_directory: pathlib.Path,
    ) -> typing.Never:
        message = "boom"
        raise peri_scribe.exceptions.ExternalDataError(message)

    stubs = run_stubs(changed=True)
    monkeypatch.setattr(peri_scribe.main, "fetch_external_source", fail)
    result = runner.invoke(peri_scribe.main.cli, ["run"])
    assert result.exit_code == 1
    assert isinstance(result.exception, peri_scribe.exceptions.ExternalDataError)
    assert stubs.ensure_boundary_calls == []
    assert stubs.history_calls == []
    assert stubs.scores_calls == []
    assert stubs.kmz_calls == []
    assert stubs.report_calls == []


@pytest.mark.usefixtures("current_year")
def test_run_stops_when_a_stage_fails(
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
    run_stubs: typing.Callable[..., RunStubs],
) -> None:
    def fail(_year_directory: pathlib.Path) -> typing.Never:
        message = "boom"
        raise ValueError(message)

    stubs = run_stubs(changed=True)
    monkeypatch.setattr(
        peri_scribe.fires.differential,
        "write_history_of_differential_geography",
        fail,
    )
    result = runner.invoke(peri_scribe.main.cli, ["run"])
    assert result.exit_code == 1
    assert isinstance(result.exception, ValueError)
    assert stubs.ensure_boundary_calls == [BASE_DIRECTORY / "data" / "2026"]
    assert stubs.history_calls == []
    assert stubs.scores_calls == []
    assert stubs.kmz_calls == []
    assert stubs.report_calls == []


@pytest.mark.usefixtures("current_year")
def test_run_stops_when_scoring_fails(
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
    run_stubs: typing.Callable[..., RunStubs],
) -> None:
    def fail(_year_directory: pathlib.Path) -> typing.Never:
        message = "boom"
        raise ValueError(message)

    stubs = run_stubs(changed=True)
    monkeypatch.setattr(peri_scribe.fires.scores, "score_fires", fail)
    result = runner.invoke(peri_scribe.main.cli, ["run"])
    assert result.exit_code == 1
    assert isinstance(result.exception, ValueError)
    assert stubs.ensure_boundary_calls == [BASE_DIRECTORY / "data" / "2026"]
    assert stubs.history_calls == [BASE_DIRECTORY / "data" / "2026"]
    assert stubs.scores_calls == []
    assert stubs.kmz_calls == []
    assert stubs.report_calls == []


@pytest.mark.usefixtures("current_year")
def test_run_only_runs_a_single_stage(
    runner: click.testing.CliRunner,
    run_stubs: typing.Callable[..., RunStubs],
) -> None:
    stubs = run_stubs(changed=True)
    result = runner.invoke(peri_scribe.main.cli, ["run", "--only", "geography"])
    assert result.exit_code == 0
    year_directory = BASE_DIRECTORY / "data" / "2026"
    assert stubs.fetch_calls == []
    assert stubs.external_calls == []
    assert stubs.ensure_boundary_calls == []
    assert stubs.history_calls == [year_directory]
    assert stubs.scores_calls == []
    assert stubs.kmz_calls == []
    assert stubs.report_calls == []


@pytest.mark.usefixtures("current_year")
def test_run_only_fetch_runs_no_later_stages(
    runner: click.testing.CliRunner,
    run_stubs: typing.Callable[..., RunStubs],
) -> None:
    stubs = run_stubs(changed=True)
    result = runner.invoke(peri_scribe.main.cli, ["run", "--only", "fetch"])
    assert result.exit_code == 0
    year_directory = BASE_DIRECTORY / "data" / "2026"
    assert stubs.fetch_calls == [(BASE_DIRECTORY, 2026, False)]
    assert stubs.external_calls == [
        (source, year_directory)
        for source in peri_scribe.sources.external_sources.EXTERNAL_SOURCES
    ]
    assert stubs.ensure_boundary_calls == [year_directory]
    assert stubs.history_calls == []
    assert stubs.scores_calls == []
    assert stubs.kmz_calls == []
    assert stubs.report_calls == []


@pytest.mark.usefixtures("current_year")
def test_run_from_geography_to_kmz(
    runner: click.testing.CliRunner,
    run_stubs: typing.Callable[..., RunStubs],
) -> None:
    stubs = run_stubs(changed=True)
    result = runner.invoke(
        peri_scribe.main.cli,
        ["run", "--from", "geography", "--to", "kmz"],
    )
    assert result.exit_code == 0
    year_directory = BASE_DIRECTORY / "data" / "2026"
    assert stubs.fetch_calls == []
    assert stubs.external_calls == []
    assert stubs.ensure_boundary_calls == []
    assert stubs.history_calls == [year_directory]
    assert stubs.scores_calls == [year_directory]
    assert stubs.kmz_calls == [year_directory]
    assert stubs.report_calls == []


@pytest.mark.usefixtures("current_year")
def test_run_from_score_runs_to_the_end(
    runner: click.testing.CliRunner,
    run_stubs: typing.Callable[..., RunStubs],
) -> None:
    stubs = run_stubs(changed=True)
    result = runner.invoke(peri_scribe.main.cli, ["run", "--from", "score"])
    assert result.exit_code == 0
    year_directory = BASE_DIRECTORY / "data" / "2026"
    assert stubs.fetch_calls == []
    assert stubs.external_calls == []
    assert stubs.ensure_boundary_calls == []
    assert stubs.history_calls == []
    assert stubs.scores_calls == [year_directory]
    assert stubs.kmz_calls == [year_directory]
    assert stubs.report_calls == [year_directory]


@pytest.mark.usefixtures("current_year")
def test_run_to_geography_runs_fetch_through_geography(
    runner: click.testing.CliRunner,
    run_stubs: typing.Callable[..., RunStubs],
) -> None:
    stubs = run_stubs(changed=True)
    result = runner.invoke(peri_scribe.main.cli, ["run", "--to", "geography"])
    assert result.exit_code == 0
    year_directory = BASE_DIRECTORY / "data" / "2026"
    assert stubs.fetch_calls == [(BASE_DIRECTORY, 2026, False)]
    assert stubs.external_calls == [
        (source, year_directory)
        for source in peri_scribe.sources.external_sources.EXTERNAL_SOURCES
    ]
    assert stubs.ensure_boundary_calls == [year_directory]
    assert stubs.history_calls == [year_directory]
    assert stubs.scores_calls == []
    assert stubs.kmz_calls == []
    assert stubs.report_calls == []


@pytest.mark.usefixtures("current_year")
def test_run_to_fetch_short_circuits_without_later_stages(
    runner: click.testing.CliRunner,
    run_stubs: typing.Callable[..., RunStubs],
) -> None:
    stubs = run_stubs(changed=False)
    result = runner.invoke(peri_scribe.main.cli, ["run", "--to", "fetch"])
    assert result.exit_code == 0
    year_directory = BASE_DIRECTORY / "data" / "2026"
    assert stubs.fetch_calls == [(BASE_DIRECTORY, 2026, False)]
    assert stubs.external_calls == [
        (source, year_directory)
        for source in peri_scribe.sources.external_sources.EXTERNAL_SOURCES
    ]
    assert stubs.ensure_boundary_calls == [year_directory]
    assert stubs.history_calls == []
    assert stubs.scores_calls == []
    assert stubs.kmz_calls == []
    assert stubs.report_calls == []


def test_run_only_conflicts_with_from(
    runner: click.testing.CliRunner,
) -> None:
    result = runner.invoke(
        peri_scribe.main.cli,
        ["run", "--only", "geography", "--from", "score"],
    )
    assert result.exit_code == CLICK_USAGE_ERROR_EXIT_CODE
    assert "--only cannot be combined with --from or --to" in result.output


def test_run_rejects_from_after_to(
    runner: click.testing.CliRunner,
) -> None:
    result = runner.invoke(
        peri_scribe.main.cli,
        ["run", "--from", "kmz", "--to", "fetch"],
    )
    assert result.exit_code == CLICK_USAGE_ERROR_EXIT_CODE
    assert "--from kmz cannot follow --to fetch" in result.output


def test_run_list_stages_prints_descriptions_without_running(
    runner: click.testing.CliRunner,
    run_stubs: typing.Callable[..., RunStubs],
) -> None:
    stubs = run_stubs(changed=True)
    result = runner.invoke(peri_scribe.main.cli, ["run", "--list-stages"])
    assert result.exit_code == 0
    assert stubs.fetch_calls == []
    assert stubs.external_calls == []
    assert stubs.ensure_boundary_calls == []
    assert stubs.history_calls == []
    assert stubs.scores_calls == []
    assert stubs.kmz_calls == []
    assert stubs.report_calls == []
    for stage in peri_scribe.main.PIPELINE_STAGES:
        assert stage.name in result.output
        assert stage.description in result.output


def test_run_help_names_current_year_default(
    runner: click.testing.CliRunner,
) -> None:
    result = runner.invoke(peri_scribe.main.cli, ["run", "--help"])
    assert result.exit_code == 0
    assert (
        f"{peri_scribe.output.DATA_DIRECTORY}/{datetime.date.today().year}"
    ) in result.output
    assert "data/<current year>" not in result.output


def test_run_rejects_missing_directory(
    runner: click.testing.CliRunner,
) -> None:
    result = runner.invoke(
        peri_scribe.main.cli,
        ["run", "no-such-directory"],
    )
    assert result.exit_code == CLICK_USAGE_ERROR_EXIT_CODE
    assert "does not exist" in result.output


def test_cli_help_lists_run(
    runner: click.testing.CliRunner,
) -> None:
    result = runner.invoke(peri_scribe.main.cli, ["--help"])
    assert result.exit_code == 0
    assert "run" in result.output
