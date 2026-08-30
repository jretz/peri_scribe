"""Validate-sources command tests for peri_scribe.main."""

from __future__ import annotations

import datetime
import pathlib
import typing

import pytest
import structlog

import peri_scribe.main
import peri_scribe.output
import peri_scribe.sources.fetching
import peri_scribe.sources.snapshots
import peri_scribe.sources.validation
from tests.conftest import CLICK_USAGE_ERROR_EXIT_CODE
from tests.main_stubs import (
    BASE_DIRECTORY,
    ValidateSourcesStubs,
)


if typing.TYPE_CHECKING:
    import click.testing


@pytest.mark.usefixtures("current_year", "validate_sources_setup")
def test_validate_sources_removes_complete_directory_when_clean(
    runner: click.testing.CliRunner,
    validate_sources_stubs: typing.Callable[..., ValidateSourcesStubs],
) -> None:
    stubs = validate_sources_stubs(())
    result = runner.invoke(peri_scribe.main.cli, ["validate-sources"])
    assert result.exit_code == 0
    year_directory = BASE_DIRECTORY / "data" / "2026"
    complete_directory = peri_scribe.sources.snapshots.validation_directory_path(
        year_directory,
    )
    assert stubs.fetch_complete_calls == [(BASE_DIRECTORY, 2026)]
    assert stubs.fetch_incremental_calls == [(BASE_DIRECTORY, 2026)]
    assert stubs.validate_calls == [year_directory]
    assert stubs.removal_calls == [complete_directory, complete_directory]


@pytest.mark.usefixtures("current_year", "validate_sources_setup")
def test_validate_sources_logs_summary_and_keeps_directory_with_problems(
    runner: click.testing.CliRunner,
    validate_sources_stubs: typing.Callable[..., ValidateSourcesStubs],
) -> None:
    problems = (
        peri_scribe.sources.validation.FeedValidationResult(
            feed_name="Feed_0",
            complete_feature_count=3,
            missing_object_ids=frozenset({2}),
            mismatched_object_ids=frozenset({3}),
            columns_missing_from_stored=frozenset({"size"}),
        ),
    )
    stubs = validate_sources_stubs(problems)
    with structlog.testing.capture_logs() as captured:
        result = runner.invoke(peri_scribe.main.cli, ["validate-sources"])
    assert result.exit_code == 0
    year_directory = BASE_DIRECTORY / "data" / "2026"
    complete_directory = peri_scribe.sources.snapshots.validation_directory_path(
        year_directory,
    )
    assert stubs.removal_calls == [complete_directory]
    problem_events = [
        event for event in captured if event["event"] == "Validation problems"
    ]
    assert len(problem_events) == 1
    assert problem_events[0]["log_level"] == "error"
    assert problem_events[0]["feed"] == "Feed_0"
    assert problem_events[0]["complete_features"] == problems[0].complete_feature_count
    assert problem_events[0]["missing_features"] == 1
    assert problem_events[0]["mismatched_features"] == 1
    assert problem_events[0]["columns_missing_from_stored"] == ["size"]
    assert any(
        event["event"] == "Validation found problems in 1 of 1 feeds"
        and event["log_level"] == "error"
        for event in captured
    )


@pytest.mark.usefixtures("current_year", "validate_sources_setup")
def test_validate_sources_stops_when_complete_fetch_fails(
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
    validate_sources_stubs: typing.Callable[..., ValidateSourcesStubs],
) -> None:
    stubs = validate_sources_stubs(())

    def fail(_base_directory: pathlib.Path, *, year: int) -> typing.Never:
        message = "boom"
        raise SystemExit(message)

    monkeypatch.setattr(
        peri_scribe.sources.fetching,
        "fetch_all_feeds_complete",
        fail,
    )
    result = runner.invoke(peri_scribe.main.cli, ["validate-sources"])
    assert result.exit_code == 1
    assert "boom" in result.output
    year_directory = BASE_DIRECTORY / "data" / "2026"
    complete_directory = peri_scribe.sources.snapshots.validation_directory_path(
        year_directory,
    )
    assert stubs.fetch_incremental_calls == []
    assert stubs.validate_calls == []
    assert stubs.removal_calls == [complete_directory]


@pytest.mark.usefixtures("current_year", "validate_sources_setup")
def test_validate_sources_stops_when_incremental_fetch_fails(
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
    validate_sources_stubs: typing.Callable[..., ValidateSourcesStubs],
) -> None:
    stubs = validate_sources_stubs(())

    def fail(_base_directory: pathlib.Path, *, year: int) -> typing.Never:
        message = "boom"
        raise SystemExit(message)

    monkeypatch.setattr(
        peri_scribe.sources.fetching,
        "fetch_all_feeds",
        fail,
    )
    result = runner.invoke(peri_scribe.main.cli, ["validate-sources"])
    assert result.exit_code == 1
    assert "boom" in result.output
    year_directory = BASE_DIRECTORY / "data" / "2026"
    complete_directory = peri_scribe.sources.snapshots.validation_directory_path(
        year_directory,
    )
    assert stubs.fetch_complete_calls == [(BASE_DIRECTORY, 2026)]
    assert stubs.validate_calls == []
    assert stubs.removal_calls == [complete_directory]


def test_validate_sources_help_names_current_year_default(
    runner: click.testing.CliRunner,
) -> None:
    result = runner.invoke(peri_scribe.main.cli, ["validate-sources", "--help"])
    assert result.exit_code == 0
    assert (
        f"{peri_scribe.output.DATA_DIRECTORY}/{datetime.date.today().year}"
    ) in result.output
    assert "data/<current year>" not in result.output


def test_validate_sources_rejects_missing_directory(
    runner: click.testing.CliRunner,
) -> None:
    result = runner.invoke(
        peri_scribe.main.cli,
        ["validate-sources", "no-such-directory"],
    )
    assert result.exit_code == CLICK_USAGE_ERROR_EXIT_CODE
    assert "does not exist" in result.output


def test_cli_help_lists_validate_sources(
    runner: click.testing.CliRunner,
) -> None:
    result = runner.invoke(peri_scribe.main.cli, ["--help"])
    assert result.exit_code == 0
    assert "validate-sources" in result.output
