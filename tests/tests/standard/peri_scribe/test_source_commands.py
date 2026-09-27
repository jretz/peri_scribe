"""Validation participates in writer exclusion and durable rebuild recovery."""

from __future__ import annotations

import pathlib

import click.testing
import pytest

import peri_scribe.main
import peri_scribe.pipeline_state
import tests.helpers.doubles.peri_scribe.source_commands


def test_validate_sources_marks_rebuild_before_new_source_data(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    year_directory = tmp_path / "data" / "2026"
    year_directory.mkdir(parents=True)
    collection = tests.helpers.doubles.peri_scribe.source_commands.Collection()
    tests.helpers.doubles.peri_scribe.source_commands.configure_validation(
        monkeypatch,
        collection,
    )
    result = click.testing.CliRunner().invoke(
        peri_scribe.main.cli,
        ["validate-sources", str(year_directory)],
    )
    assert result.exit_code == 0, result.output
    assert collection.pending[0].remaining == peri_scribe.pipeline_state.DERIVED_STAGES
    assert peri_scribe.pipeline_state.read_state(year_directory).remaining == (
        peri_scribe.pipeline_state.DERIVED_STAGES
    )


def test_validate_sources_skips_when_another_writer_owns_year(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    year_directory = tmp_path / "data" / "2026"
    year_directory.mkdir(parents=True)
    collection = tests.helpers.doubles.peri_scribe.source_commands.Collection()
    tests.helpers.doubles.peri_scribe.source_commands.configure_validation(
        monkeypatch,
        collection,
    )
    with peri_scribe.pipeline_state.run_lock(year_directory) as acquired:
        assert acquired
        result = click.testing.CliRunner().invoke(
            peri_scribe.main.cli,
            ["validate-sources", str(year_directory)],
        )
    assert result.exit_code == 0, result.output
    assert collection.pending == []


@pytest.mark.parametrize("interrupted", [False, True])
def test_validate_sources_preserves_prior_requirements_after_retry(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    interrupted: bool,
) -> None:
    year_directory = tmp_path / "data" / "2026"
    prior = peri_scribe.pipeline_state.PendingRun(
        remaining=(peri_scribe.pipeline_state.DERIVED_STAGES[-1],),
        unconditional=True,
    )
    peri_scribe.pipeline_state.write_state(year_directory, prior)
    collection = tests.helpers.doubles.peri_scribe.source_commands.Collection(
        changed=False,
        interrupt=interrupted,
    )
    tests.helpers.doubles.peri_scribe.source_commands.configure_validation(
        monkeypatch,
        collection,
    )
    result = click.testing.CliRunner().invoke(
        peri_scribe.main.cli,
        ["validate-sources", str(year_directory)],
    )
    assert result.exit_code == int(interrupted), result.output
    expected = (
        peri_scribe.pipeline_state.PendingRun(
            remaining=peri_scribe.pipeline_state.DERIVED_STAGES,
            unconditional=True,
        )
        if interrupted
        else prior
    )
    assert peri_scribe.pipeline_state.read_state(year_directory) == expected
    collection.interrupt = False
    retry = click.testing.CliRunner().invoke(
        peri_scribe.main.cli,
        ["validate-sources", str(year_directory)],
    )
    assert retry.exit_code == 0, retry.output
    assert peri_scribe.pipeline_state.read_state(year_directory) == expected
