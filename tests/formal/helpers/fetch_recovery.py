"""Replay checked fetch outcomes and interruptions against durable run state."""

import dataclasses
import datetime
import json
import pathlib

import pytest

import peri_scribe.pipeline
import peri_scribe.pipeline_state
import tests.formal.helpers.corpus
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
    """A durable source mutation precedes process loss and an unchanged retry."""

    previous: peri_scribe.pipeline_state.PendingRun
    pending: peri_scribe.pipeline_state.PendingRun
    full: bool
    mutation: tests.helpers.doubles.peri_scribe.pipeline_fetch_recovery.Mutation


def outcomes(directory: pathlib.Path) -> tuple[Outcome, ...]:
    """Keep expectations tied to TLC's complete reachable state graph.

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


def replay_interruption(interrupted: Interrupted, directory: pathlib.Path) -> None:
    """Unchanged retries retain requirements surviving abrupt process loss.

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
