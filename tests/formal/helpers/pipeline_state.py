"""Replay the state relations actually enumerated and checked by TLC."""

import collections
import dataclasses
import json
import pathlib
import re

import peri_scribe.pipeline_stages
import peri_scribe.pipeline_state
import tests.formal.helpers.oracle
import tests.formal.helpers.tlc


@dataclasses.dataclass(frozen=True, kw_only=True)
class Transition:
    """A checked model event with the input needed to replay it in Python."""

    before: peri_scribe.pipeline_state.PendingRun
    after: peri_scribe.pipeline_state.PendingRun
    operation: str
    required: tuple[peri_scribe.pipeline_stages.Stage, ...]
    forced: bool
    completed: peri_scribe.pipeline_stages.Stage


def stages(value: str) -> tuple[peri_scribe.pipeline_stages.Stage, ...]:
    """Bind the model's stage numbers to the production dependency order.

    Args:
        value: Comma-separated stage numbers in the finite model's collection.

    Returns:
        The corresponding application stages.
    """
    return tuple(
        peri_scribe.pipeline_state.DERIVED_STAGES[int(item.strip()) - 1]
        for item in value.split(",")
        if item.strip()
    )


def state(value: str) -> peri_scribe.pipeline_state.PendingRun:
    """Reject unexpected TLC formatting instead of silently ignoring model states.

    Args:
        value: A state record in TLC's text dump format.

    Returns:
        The corresponding persistent Python state.
    """
    reordered = re.fullmatch(
        r"\[unconditional \|-> (TRUE|FALSE),\s*remaining \|-> <<([\d,\s]*)>>\]",
        value,
    )
    if reordered is not None:
        value = f"[remaining |-> <<{reordered[2]}>>, unconditional |-> {reordered[1]}]"
    match = re.fullmatch(
        r"\[remaining \|-> <<([\d,\s]*)>>,\s*unconditional \|-> (TRUE|FALSE)\]",
        value,
    )
    assert match is not None, value
    return peri_scribe.pipeline_state.PendingRun(
        remaining=stages(match[1]),
        unconditional=match[2] == "TRUE",
    )


def transitions(directory: pathlib.Path) -> list[Transition]:
    """Export the full checked relation without relying on saved generated fixtures.

    Args:
        directory: An isolated location for TLC state and dump files.

    Returns:
        Every event in the model's complete finite state graph.
    """
    records = []
    for fields in tests.formal.helpers.tlc.states("RunState", "RunState", directory):
        assert set(fields) == {
            "before",
            "after",
            "operation",
            "required",
            "forced",
            "completed",
        }, fields
        records.append(
            Transition(
                before=state(fields["before"]),
                after=state(fields["after"]),
                operation=json.loads(fields["operation"]),
                required=stages(fields["required"].removeprefix("{").removesuffix("}")),
                forced=fields["forced"] == "TRUE",
                completed=(
                    peri_scribe.pipeline_stages.Stage.FETCH,
                    *peri_scribe.pipeline_state.DERIVED_STAGES,
                )[int(fields["completed"])],
            ),
        )
    count = len(peri_scribe.pipeline_state.DERIVED_STAGES)
    states_count = 2 ** (count + 1)
    assert collections.Counter(record.operation for record in records) == {
        "init": states_count,
        "require": states_count**2,
        "complete": states_count * (count + 1),
        "invalid": states_count,
    }
    return records


def replay(transition: Transition, directory: pathlib.Path) -> None:
    """Use real persistence boundaries for each checked recovery transition.

    Args:
        transition: A TLC event with its exact input and expected output states.
        directory: An isolated year directory for persisted pipeline state.

    Raises:
        AssertionError: If a model event has no corresponding implementation action.
    """
    peri_scribe.pipeline_state.write_state(directory, transition.before)
    match transition.operation:
        case "require":
            peri_scribe.pipeline_state.require_stages(
                directory,
                transition.required,
                unconditional=transition.forced,
            )
        case "complete":
            peri_scribe.pipeline_state.complete_stage(directory, transition.completed)
        case "invalid":
            peri_scribe.pipeline_state.state_path(directory).write_text("{")
        case "init":
            pass
        case _:
            raise AssertionError(transition.operation)
    assert peri_scribe.pipeline_state.read_state(directory) == transition.after, (
        transition
    )


def mask(stages: tuple[peri_scribe.pipeline_stages.Stage, ...]) -> int:
    """Encode stage membership in the Lean oracle's finite transport format.

    Args:
        stages: The canonically ordered application stages.

    Returns:
        The corresponding four-bit pending-stage mask.
    """
    return sum(
        1 << index
        for index, stage in enumerate(peri_scribe.pipeline_state.DERIVED_STAGES)
        if stage in stages
    )


def check_lean(transitions: list[Transition]) -> None:
    """Bind both specifications to the same complete finite transition relation.

    Args:
        transitions: Events exported by TLC after successful model checking.
    """
    commands = []
    expected = []
    for transition in transitions:
        arguments = (
            f"{mask(transition.before.remaining)} "
            f"{int(transition.before.unconditional)}"
        )
        if transition.operation == "require":
            commands.append(
                f"require {arguments} {mask(transition.required)} "
                f"{int(transition.forced)}",
            )
        elif (
            transition.operation == "complete"
            and transition.completed in peri_scribe.pipeline_state.DERIVED_STAGES
        ):
            stage = peri_scribe.pipeline_state.DERIVED_STAGES.index(
                transition.completed,
            )
            commands.append(f"complete {arguments} {stage}")
        else:
            continue
        expected.append((
            mask(transition.after.remaining),
            int(transition.after.unconditional),
        ))
    assert tests.formal.helpers.oracle.evaluate(commands) == expected
