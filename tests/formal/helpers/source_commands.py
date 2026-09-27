"""Compare real validation command recovery with the checked writer protocol."""

import itertools
import pathlib
import re

import click.testing
import pytest

import peri_scribe.main
import peri_scribe.pipeline_state
import tests.helpers.doubles.peri_scribe.source_commands


def booleans(value: str) -> tuple[bool, ...]:
    """Decode TLC Boolean function values without executing model text.

    Args:
        value: A TLC sequence representation over the two modeled writers.

    Returns:
        The writer-indexed Boolean values.
    """
    return tuple(word == "TRUE" for word in re.findall(r"TRUE|FALSE", value))


def terminal_states(
    states: list[dict[str, str]],
) -> dict[
    tuple[bool, bool, bool],
    tuple[bool, bool],
]:
    """Require validation's successful result to be independent of interleaving.

    Args:
        states: Complete TLC writer state graph.

    Returns:
        Pending/forcing outcomes keyed by previous pending/forcing and source changes.
    """
    outcomes: dict[tuple[bool, bool, bool], set[tuple[bool, bool]]] = {}
    for state in states:
        phases = re.findall(r'"([^"]+)"', state["phase"])
        if phases[1] != "end":
            continue
        key = (
            booleans(state["previous"])[1],
            booleans(state["previousForce"])[1],
            booleans(state["changed"])[1],
        )
        outcomes.setdefault(key, set()).add((
            state["pending"] == "TRUE",
            state["forced"] == "TRUE",
        ))
    assert set(outcomes) == set(itertools.product((False, True), repeat=3))
    assert all(len(values) == 1 for values in outcomes.values())
    return {key: next(iter(values)) for key, values in outcomes.items()}


def replay(states: list[dict[str, str]], directory: pathlib.Path) -> None:
    """Exercise every real pending-stage subset, forcing bit, outcome, and retry.

    Args:
        states: Checked source-writer state graph.
        directory: Isolated application roots for each command execution.
    """
    outcomes = terminal_states(states)
    stages = peri_scribe.pipeline_state.DERIVED_STAGES
    scenarios = itertools.product(
        itertools.product((False, True), repeat=4),
        (False, True),
    )
    for number, (selected, forced) in enumerate(scenarios):
        prior = peri_scribe.pipeline_state.PendingRun(
            remaining=tuple(
                stage
                for stage, include in zip(stages, selected, strict=True)
                if include
            ),
            unconditional=forced,
        )
        for changed, interrupted in ((False, False), (True, False), (True, True)):
            year = directory / f"{number}-{changed}-{interrupted}" / "data" / "2026"
            peri_scribe.pipeline_state.write_state(year, prior)
            collection = tests.helpers.doubles.peri_scribe.source_commands.Collection(
                changed=changed,
                interrupt=interrupted,
            )
            with pytest.MonkeyPatch.context() as patch:
                tests.helpers.doubles.peri_scribe.source_commands.configure_validation(
                    patch,
                    collection,
                )
                result = click.testing.CliRunner().invoke(
                    peri_scribe.main.cli,
                    ["validate-sources", str(year)],
                )
                assert result.exit_code == int(interrupted), result.output
                assert collection.pending[0].remaining == stages
                after = peri_scribe.pipeline_state.read_state(year)
                if interrupted:
                    assert after.remaining == stages
                    collection.interrupt = False
                    collection.changed = False
                    retry = click.testing.CliRunner().invoke(
                        peri_scribe.main.cli,
                        ["validate-sources", str(year)],
                    )
                    assert retry.exit_code == 0, retry.output
                    assert peri_scribe.pipeline_state.read_state(year) == after
                else:
                    assert (bool(after.remaining), after.unconditional) == outcomes[
                        bool(prior.remaining),
                        forced,
                        changed,
                    ]
                    assert after.remaining == (stages if changed else prior.remaining)
                assert after.unconditional == forced
