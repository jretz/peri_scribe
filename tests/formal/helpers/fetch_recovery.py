"""Replay checked fetch outcomes and interruptions against durable run state."""

import dataclasses
import datetime
import importlib
import json
import pathlib

import pytest

import peri_scribe.durable_file
import peri_scribe.pipeline
import peri_scribe.pipeline_state
import tests.formal.helpers.corpus
import tests.formal.helpers.oracle
import tests.formal.helpers.pipeline_replay_files
import tests.formal.helpers.pipeline_state
import tests.helpers.doubles.peri_scribe.pipeline_fetch_recovery


@dataclasses.dataclass(frozen=True, kw_only=True)
class Outcome:
    """One checked complete fetch transition preserves all prior-state distinctions."""

    previous: peri_scribe.pipeline_state.PendingRun
    pending: peri_scribe.pipeline_state.PendingRun
    fire_changed: bool
    evacuations_changed: bool
    full: bool
    unconditional: bool
    proceed: bool


@dataclasses.dataclass(frozen=True, kw_only=True)
class Interrupted:
    """A durable source mutation precedes simulated interruption and unchanged retry."""

    previous: peri_scribe.pipeline_state.PendingRun
    pending: peri_scribe.pipeline_state.PendingRun
    full: bool
    mutation: tests.helpers.doubles.peri_scribe.pipeline_fetch_recovery.Mutation


def outcomes(directory: pathlib.Path) -> tuple[Outcome, ...]:
    """Keep expectations tied to TLC's complete set of reachable states.

    Args:
        directory: An isolated destination for checked model states.

    Returns:
        Every distinct successful fetch input/output relation found by TLC.
    """
    records = {}
    for fields in tests.formal.helpers.corpus.states(
        "FetchCrash",
        "FetchCrash",
        directory,
    ):
        if json.loads(fields["action"]) != "finish":
            continue
        record = Outcome(
            previous=tests.formal.helpers.pipeline_state.state(fields["previous"]),
            pending=tests.formal.helpers.pipeline_state.state(fields["pending"]),
            fire_changed=fields["fireChanged"] == "TRUE",
            evacuations_changed=fields["evacuationChanged"] == "TRUE",
            full=fields["full"] == "TRUE",
            unconditional=fields["unconditional"] == "TRUE",
            proceed=fields["proceed"] == "TRUE",
        )
        records[record] = None
    prior_states = 2 ** (len(peri_scribe.pipeline_state.DERIVED_STAGES) + 1)
    assert len(records) == prior_states * 2**4
    assert {record.proceed for record in records} == {False, True}
    return tuple(records)


def interruptions(directory: pathlib.Path) -> tuple[Interrupted, ...]:
    """Bind each tested fault boundary to the state immediately after durable mutation.

    Args:
        directory: An isolated destination for checked model states.

    Returns:
        Every prior-state and collection-mode combination at both mutation boundaries.
    """
    mutation_type = tests.helpers.doubles.peri_scribe.pipeline_fetch_recovery.Mutation
    records = {}
    for fields in tests.formal.helpers.corpus.states(
        "FetchCrash",
        "FetchCrash",
        directory,
    ):
        action = json.loads(fields["action"])
        if action == "fire" and fields["fireChanged"] == "TRUE":
            mutation = mutation_type.FIRE
        elif action == "evacuations" and fields["evacuationChanged"] == "TRUE":
            mutation = mutation_type.EVACUATIONS
        else:
            continue
        record = Interrupted(
            previous=tests.formal.helpers.pipeline_state.state(fields["previous"]),
            pending=tests.formal.helpers.pipeline_state.state(fields["pending"]),
            full=fields["full"] == "TRUE",
            mutation=mutation,
        )
        records[record] = None
    prior_states = 2 ** (len(peri_scribe.pipeline_state.DERIVED_STAGES) + 1)
    mutation_count = len(mutation_type)
    assert len(records) == prior_states * 2 * mutation_count
    return tuple(records)


def replay_outcome(outcome: Outcome, directory: pathlib.Path) -> None:
    """Keep actual full-fetch scheduling, state I/O, and the coordinator's return value.

    Args:
        outcome: Checked formal input and expected result.
        directory: Per-case isolated year directory.
    """
    mutation = tests.helpers.doubles.peri_scribe.pipeline_fetch_recovery.Mutation
    changes = frozenset(
        item
        for item, changed in (
            (mutation.FIRE, outcome.fire_changed),
            (mutation.EVACUATIONS, outcome.evacuations_changed),
        )
        if changed
    )
    scenario = tests.helpers.doubles.peri_scribe.pipeline_fetch_recovery.Scenario(
        directory=directory,
        changes=changes,
    )
    peri_scribe.pipeline_state.write_state(directory, outcome.previous)
    with pytest.MonkeyPatch.context() as monkeypatch:
        tests.helpers.doubles.peri_scribe.pipeline_fetch_recovery.install(
            monkeypatch,
            scenario,
        )
        result = peri_scribe.pipeline.run_fetch_stage(
            directory,
            full_fetch_interval=datetime.timedelta(0) if outcome.full else None,
            unconditional=outcome.unconditional,
        )
    assert result == outcome.proceed, outcome
    assert peri_scribe.pipeline_state.read_state(directory) == outcome.pending, outcome


def replay_outcomes(
    records: tuple[Outcome, ...],
    directory: pathlib.Path,
) -> tuple[int, int]:
    """Keep every real invocation and source effect with independent marker bytes.

    Returns:
        The total input count and the retained native marker-storage count.
    """
    binding = importlib.import_module("tests.formal.helpers.feed_component_binding")
    qualified = binding.supported()
    if qualified:
        commands = [
            "fetch-finish "
            + " ".join(
                map(
                    str,
                    (
                        tests.formal.helpers.pipeline_state.mask(
                            record.previous.remaining,
                        ),
                        int(record.previous.unconditional),
                        int(record.fire_changed),
                        int(record.evacuations_changed),
                        int(record.full),
                        0,
                        int(record.unconditional),
                    ),
                ),
            )
            for record in records
        ]
        for record, row in zip(
            records,
            tests.formal.helpers.oracle.evaluate(commands),
            strict=True,
        ):
            assert row == (
                tests.formal.helpers.pipeline_state.mask(record.pending.remaining),
                int(record.pending.unconditional),
                int(record.proceed),
            )
    native = 0
    for number, record in enumerate(records):
        year = directory / str(number) / "2026"
        native_basis = not (
            record.fire_changed
            or record.evacuations_changed
            or record.full
            or record.unconditional
        ) or record.previous.remaining in {
            (),
            peri_scribe.pipeline_state.DERIVED_STAGES,
        }
        if not qualified or native_basis:
            replay_outcome(record, year)
            native += 1
            continue
        # Real source and cadence files remain independent for every invocation.
        year.mkdir(parents=True)
        memory = tests.formal.helpers.pipeline_replay_files.Memory(
            directory=year,
            effects={},
        )
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(peri_scribe.durable_file, "at", memory.at)
            replay_outcome(record, year)
    return len(records), native


def replay_interruption(interrupted: Interrupted, directory: pathlib.Path) -> None:
    """Unchanged retries retain requirements after a simulated interruption.

    Args:
        interrupted: Checked durable mutation boundary and expected recovery marker.
        directory: Per-case isolated year directory.
    """
    scenario = tests.helpers.doubles.peri_scribe.pipeline_fetch_recovery.Scenario(
        directory=directory,
        changes=frozenset({interrupted.mutation}),
        interrupt=interrupted.mutation,
    )
    peri_scribe.pipeline_state.write_state(directory, interrupted.previous)
    with pytest.MonkeyPatch.context() as monkeypatch:
        tests.helpers.doubles.peri_scribe.pipeline_fetch_recovery.install(
            monkeypatch,
            scenario,
        )
        with pytest.raises(
            tests.helpers.doubles.peri_scribe.pipeline_fetch_recovery.ProcessLoss,
        ):
            peri_scribe.pipeline.run_fetch_stage(
                directory,
                full_fetch_interval=datetime.timedelta(0) if interrupted.full else None,
                unconditional=False,
            )
        assert scenario.path(interrupted.mutation).is_file()
        assert peri_scribe.pipeline_state.read_state(directory) == interrupted.pending
        assert peri_scribe.pipeline.run_fetch_stage(
            directory,
            full_fetch_interval=None,
            unconditional=False,
        )
        assert peri_scribe.pipeline_state.read_state(directory) == interrupted.pending
