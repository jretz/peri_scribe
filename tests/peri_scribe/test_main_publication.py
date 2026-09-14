"""Exercise the serial CLI gate with durable checkpoints and pending work."""

from __future__ import annotations

import dataclasses
import datetime
import pathlib
import typing

import click
import click.testing
import pytest
import time_machine

import peri_scribe.fires.index
import peri_scribe.kml.builder
import peri_scribe.main
import peri_scribe.pipeline_state
import peri_scribe.publication
import peri_scribe.sources.external_sources
import peri_scribe.sources.fetching
import tests.factories
import tests.main_stubs
import tests.peri_scribe.test_publication
from peri_scribe.units import units
from tests.conftest import CLICK_USAGE_ERROR_EXIT_CODE


if typing.TYPE_CHECKING:
    import structlog.testing


NOW = tests.peri_scribe.test_publication.NOW
OPTIONS = ["--publish-threshold", "25 acre", "5m"]


@dataclasses.dataclass(frozen=True, kw_only=True)
class Scenario:
    """Only external operations are stubbed; state and the decision remain real.

    Args:
        year: The isolated year directory containing test sources and outputs.
        stubs: Pipeline substitutes that record which stages run.
        indexed: The year directories for which deferred indexing was requested.
        inputs: The downloaded source inventory supplied to the publication gate.
        output: The local KMZ path used to validate the publication checkpoint.
    """

    year: pathlib.Path
    stubs: tests.main_stubs.RunStubs
    indexed: list[pathlib.Path]
    inputs: peri_scribe.publication.Collection
    output: pathlib.Path


@pytest.fixture
def scenario(
    run_stubs: typing.Callable[..., tests.main_stubs.RunStubs],
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Scenario:
    """Start with a published 100-acre map and a downloaded 110-acre update.

    Args:
        run_stubs: The fixture factory replacing external pipeline operations.
        tmp_path: The isolated root for this scenario's files.
        monkeypatch: The fixture installing temporary pipeline substitutes.

    Returns:
        An isolated year with source geometry saved but not acknowledged by publication.
    """
    year = tmp_path / "data/2026"
    year.mkdir(parents=True)
    stubs = run_stubs(changed=True)
    baseline = tests.peri_scribe.test_publication.mapping(100)
    inputs = tests.peri_scribe.test_publication.collection(
        baseline,
        tests.peri_scribe.test_publication.mapping(110, serial=2),
    )
    monkeypatch.setattr(peri_scribe.publication, "collect", lambda _year: inputs)
    output = peri_scribe.kml.builder.kmz_path(year)
    output.parent.mkdir()
    output.write_bytes(b"complete previous KMZ")
    with time_machine.travel(NOW, tick=False):
        peri_scribe.publication.commit(
            year,
            output,
            tests.peri_scribe.test_publication.collection(baseline),
            tests.peri_scribe.test_publication.publication(baseline).fires,
        )

    def fetch(
        base: pathlib.Path,
        *,
        year: int,
        full: bool,
        build_index: bool,
    ) -> peri_scribe.sources.fetching.FetchResult:
        """The gate must collect source geometry without building the index.

        Args:
            base: The base directory supplied to the fire fetcher.
            year: The requested collection year.
            full: Whether the request forces a full source refresh.
            build_index: Whether indexing was requested; must be false for gated
                fetches.

        Returns:
            The requested collection outcome.
        """
        assert not build_index
        stubs.fetch_calls.append((base, year, full))
        return stubs.fetch_result

    def create(
        year: pathlib.Path,
        *,
        publication_inputs: peri_scribe.publication.Collection | None = None,
    ) -> pathlib.Path:
        """Complete a local file and commit only the inputs supplied by geography.

        Args:
            year: The year directory supplied to the KMZ builder.
            publication_inputs: Frozen sources to acknowledge, or None without a
                publication checkpoint request.

        Returns:
            The output path, as the actual builder does.
        """
        stubs.kmz_calls.append(year)
        output.write_bytes(b"complete new KMZ")
        if publication_inputs is not None:
            assert publication_inputs == inputs
            peri_scribe.publication.commit(year, output, publication_inputs, {})
        return output

    indexed: list[pathlib.Path] = []
    monkeypatch.setattr(peri_scribe.sources.fetching, "fetch_all_feeds", fetch)
    monkeypatch.setattr(peri_scribe.fires.index, "index_fire_sources", indexed.append)
    monkeypatch.setattr(peri_scribe.kml.builder, "create_kmz", create)
    return Scenario(
        year=year,
        stubs=stubs,
        indexed=indexed,
        inputs=inputs,
        output=output,
    )


def test_gate_skip_checks_evacuations_and_preserves_checkpoint_without_pending_failure(
    scenario: Scenario,
    runner: click.testing.CliRunner,
    cli_log_output: structlog.testing.LogCapture,
) -> None:
    before = peri_scribe.publication.publication_path(scenario.year).read_bytes()
    with time_machine.travel(NOW, tick=False):
        result = runner.invoke(
            peri_scribe.main.cli,
            ["run", str(scenario.year), *OPTIONS],
        )
    assert result.exit_code == 0, result.output
    assert scenario.indexed == []
    assert scenario.stubs.history_calls == []
    assert scenario.stubs.external_calls == [
        (peri_scribe.sources.external_sources.EVACUATIONS_SOURCE, scenario.year),
    ]
    assert scenario.stubs.ensure_boundary_calls == []
    assert not peri_scribe.pipeline_state.read_state(scenario.year).remaining
    assert (
        peri_scribe.publication.publication_path(scenario.year).read_bytes() == before
    )
    decision = next(
        entry
        for entry in cli_log_output.entries
        if entry["event"] == "Publication gate skipped"
    )
    assert decision["reason"] == peri_scribe.publication.Reason.BELOW_THRESHOLD
    assert {
        entry["phase"]
        for entry in cli_log_output.entries
        if entry.get("event") == "Finished phase"
    } == {"fetch", "fire-collection", "evacuation-check", "publication-gate"}


def test_timer_builds_saved_updates_on_unchanged_fetch_and_advances_checkpoint(
    scenario: Scenario,
    runner: click.testing.CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        peri_scribe.sources.fetching,
        "fetch_all_feeds",
        lambda *_args, **_keywords: peri_scribe.sources.fetching.FetchResult(
            snapshot_paths=(),
            changed=False,
        ),
    )
    completed = NOW + datetime.timedelta(minutes=5)
    with time_machine.travel(completed, tick=False):
        result = runner.invoke(
            peri_scribe.main.cli,
            ["run", str(scenario.year), *OPTIONS],
        )
    assert result.exit_code == 0, result.output
    assert scenario.indexed == [scenario.year]
    assert scenario.stubs.history_calls == [scenario.year]
    assert scenario.stubs.kmz_calls == [scenario.year]
    assert scenario.stubs.report_calls == [scenario.year]
    assert [source for source, _year in scenario.stubs.external_calls].count(
        peri_scribe.sources.external_sources.EVACUATIONS_SOURCE,
    ) == 1
    published = peri_scribe.publication.read_publication(scenario.year, scenario.output)
    assert published is not None
    assert published.files == scenario.inputs.files
    assert published.created_at == completed
    assert not peri_scribe.pipeline_state.read_state(scenario.year).remaining


@pytest.mark.parametrize(
    "override",
    ["unconditional", "full", "pending", "checkpoint", "evacuations"],
)
def test_required_work_bypasses_area_and_timer_gate(
    scenario: Scenario,
    runner: click.testing.CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    override: str,
) -> None:
    arguments = []
    if override == "unconditional":
        arguments = ["--unconditional"]
    elif override == "full":
        arguments = ["--full-fetch-interval", "6h"]
    elif override == "pending":
        peri_scribe.pipeline_state.require_stages(
            scenario.year,
            peri_scribe.pipeline_state.DERIVED_STAGES,
        )
    elif override == "checkpoint":
        peri_scribe.publication.publication_path(scenario.year).unlink()
    else:
        changed = scenario.inputs.model_copy(
            update={"evacuations": tests.peri_scribe.test_publication.STAMP},
        )
        monkeypatch.setattr(peri_scribe.publication, "collect", lambda _year: changed)
    with time_machine.travel(NOW, tick=False):
        result = runner.invoke(
            peri_scribe.main.cli,
            ["run", str(scenario.year), *OPTIONS, *arguments, "--to", "geography"],
        )
    assert result.exit_code == 0, result.output
    assert scenario.indexed == [scenario.year]
    assert scenario.stubs.history_calls == [scenario.year]
    if override == "full":
        assert scenario.stubs.fetch_calls[0][2]
        assert len(scenario.stubs.write_state_calls) == 1
        assert scenario.stubs.unconditional_history_calls == [scenario.year]


@pytest.mark.parametrize("operation", ["collection", "evacuations", "gate", "index"])
@pytest.mark.parametrize("error", [RuntimeError("failure"), SystemExit("failure")])
def test_failed_fetch_or_check_requires_retry_without_advancing_publication(
    scenario: Scenario,
    runner: click.testing.CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    error: BaseException,
) -> None:
    module, name = {
        "collection": (peri_scribe.sources.fetching, "fetch_all_feeds"),
        "evacuations": (peri_scribe.main, "fetch_external_source"),
        "gate": (peri_scribe.publication, "collect"),
        "index": (peri_scribe.fires.index, "index_fire_sources"),
    }[operation]
    monkeypatch.setattr(module, name, tests.factories.raising_stub(error))
    before = peri_scribe.publication.publication_path(scenario.year).read_bytes()
    with time_machine.travel(NOW, tick=False):
        result = runner.invoke(
            peri_scribe.main.cli,
            ["run", str(scenario.year), *OPTIONS, "--unconditional"],
        )
    assert result.exit_code != 0
    assert result.exception is error
    assert (
        peri_scribe.pipeline_state.read_state(scenario.year).remaining
        == peri_scribe.pipeline_state.DERIVED_STAGES
    )
    assert (
        peri_scribe.publication.publication_path(scenario.year).read_bytes() == before
    )


def test_partial_kmz_run_invalidates_checkpoint_without_acknowledging_new_sources(
    scenario: Scenario,
    runner: click.testing.CliRunner,
) -> None:
    result = runner.invoke(
        peri_scribe.main.cli,
        ["run", str(scenario.year), *OPTIONS, "--only", "kmz"],
    )
    assert result.exit_code == 0, result.output
    assert scenario.stubs.kmz_calls == [scenario.year]
    assert not peri_scribe.publication.publication_path(scenario.year).exists()


@pytest.mark.parametrize(
    "area",
    ["25", "25 meters", "-25 acres", "0 acre", "nan acres", "inf acres", "nonsense"],
)
def test_cli_rejects_invalid_publication_areas(
    runner: click.testing.CliRunner,
    area: str,
) -> None:
    result = runner.invoke(
        peri_scribe.main.cli,
        ["run", "--publish-threshold", area, "5m"],
    )
    assert result.exit_code == CLICK_USAGE_ERROR_EXIT_CODE
    assert "positive area" in result.output


def test_cli_rejects_zero_publication_interval(runner: click.testing.CliRunner) -> None:
    result = runner.invoke(
        peri_scribe.main.cli,
        ["run", "--publish-threshold", "25 acre", "0m"],
    )
    assert result.exit_code == CLICK_USAGE_ERROR_EXIT_CODE
    assert "publication interval must be positive" in result.output


def test_area_parser_accepts_equivalent_explicit_units() -> None:
    parser = peri_scribe.main.Area()
    assert parser.convert("1 hectare", None, None) == 10000 * units.meters**2
    with pytest.raises(click.BadParameter, match="positive area"):
        parser.convert(object(), None, None)


def test_overlapping_invocation_does_not_fetch_or_restart_work(
    scenario: Scenario,
    runner: click.testing.CliRunner,
) -> None:
    with peri_scribe.pipeline_state.run_lock(scenario.year) as acquired:
        assert acquired
        result = runner.invoke(
            peri_scribe.main.cli,
            ["run", str(scenario.year), *OPTIONS],
        )
    assert result.exit_code == 0, result.output
    assert scenario.stubs.fetch_calls == []
    assert scenario.stubs.kmz_calls == []
    assert not peri_scribe.pipeline_state.read_state(scenario.year).remaining


def test_report_failure_does_not_undo_completed_local_publication(
    scenario: Scenario,
    runner: click.testing.CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        peri_scribe.main,
        "write_reports",
        tests.factories.raising_stub(RuntimeError("report failed")),
    )
    with time_machine.travel(NOW, tick=False):
        result = runner.invoke(
            peri_scribe.main.cli,
            ["run", str(scenario.year), *OPTIONS, "--unconditional"],
        )
    assert result.exit_code != 0
    assert peri_scribe.pipeline_state.read_state(scenario.year).remaining == (
        "reports",
    )
    published = peri_scribe.publication.read_publication(scenario.year, scenario.output)
    assert published is not None
    assert published.files == scenario.inputs.files
    assert published.created_at == NOW
