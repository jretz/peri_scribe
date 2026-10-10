"""Share complete checked pipeline contracts without repeating graph preprocessing.

Design notes:
[Verification evidence and execution](../../../docs/algorithms/verification-tooling.md).
"""

from __future__ import annotations

import collections
import dataclasses
import pathlib

import pydantic

import tests.formal.helpers.corpus
import tests.formal.helpers.paths
import tests.formal.helpers.pipeline_batches
import tests.formal.helpers.pipeline_composition
import tests.formal.helpers.tlc


@dataclasses.dataclass(frozen=True, kw_only=True)
class Branch:
    """Repeated invocation values use one typed table without merging their prefixes."""

    invocation: int
    children: tuple[Branch, ...]
    terminal: bool


@dataclasses.dataclass(frozen=True, kw_only=True)
class Serialized:
    """Retain raw states and edges alongside every precomputed conformance decision."""

    graph: tests.formal.helpers.tlc.Graph
    values: tuple[tests.formal.helpers.pipeline_composition.Durable, ...]
    projections: dict[int, int]
    actions: tuple[str, ...]
    transitions: dict[int, tuple[int, ...]]
    internal: frozenset[str]
    invocations: tuple[tests.formal.helpers.pipeline_composition.Invocation, ...]
    histories: tuple[tuple[int, ...], ...]
    batches: tuple[tuple[Branch, ...], ...]


@dataclasses.dataclass(frozen=True, kw_only=True)
class Prepared:
    """Each worker owns its decoded mappings and the same complete case inventory."""

    executions: tests.formal.helpers.pipeline_composition.Executions
    batches: tuple[tuple[tests.formal.helpers.pipeline_batches.Branch, ...], ...]


ADAPTER = pydantic.TypeAdapter(Serialized)


def encode_branch(
    branch: tests.formal.helpers.pipeline_batches.Branch,
    positions: dict[tests.formal.helpers.pipeline_composition.Invocation, int],
) -> Branch:
    """Retain terminal internal nodes and child order under their exact parents.

    Args:
        branch: One complete checked invocation subtree.
        positions: Unique invocation values in the shared typed table.

    Returns:
        The same subtree using invocation indices for repeated immutable values.
    """
    return Branch(
        invocation=positions[branch.invocation],
        children=tuple(encode_branch(child, positions) for child in branch.children),
        terminal=branch.terminal,
    )


def encode(
    executions: tests.formal.helpers.pipeline_composition.Executions,
) -> Serialized:
    """Publish the full graph and a partition covering exactly its original histories.

    Args:
        executions: Complete preprocessed executions with checked inventory assertions.

    Returns:
        Typed data containing raw graph fields, ordered edges, and all replay decisions.
    """
    checked = executions.checked
    histories = tuple(executions.histories.values())
    assert all(
        history and history[-1] == outcome
        for outcome, history in executions.histories.items()
    )
    assert set(checked.values) == set(checked.graph.states)
    assert set(checked.actions) == {
        edge for edges in checked.graph.outgoing.values() for edge in edges
    }
    batches = tests.formal.helpers.pipeline_batches.partition(
        tests.formal.helpers.pipeline_batches.trees(histories),
        tests.formal.helpers.pipeline_composition.BATCH_COUNT,
    )
    assert collections.Counter(
        history
        for batch in batches
        for history in tests.formal.helpers.pipeline_batches.histories(batch)
    ) == collections.Counter(histories)
    values = tuple(dict.fromkeys(checked.values.values()))
    value_positions = {value: index for index, value in enumerate(values)}
    actions = tuple(dict.fromkeys(checked.actions.values()))
    action_positions = {value: index for index, value in enumerate(actions)}
    invocations = tuple(
        dict.fromkeys(invocation for history in histories for invocation in history),
    )
    invocation_positions = {value: index for index, value in enumerate(invocations)}
    return Serialized(
        graph=checked.graph,
        values=values,
        projections={
            node: value_positions[value] for node, value in checked.values.items()
        },
        actions=actions,
        transitions={
            node: tuple(action_positions[checked.actions[edge]] for edge in edges)
            for node, edges in checked.graph.outgoing.items()
        },
        internal=checked.internal,
        invocations=invocations,
        histories=tuple(
            tuple(invocation_positions[invocation] for invocation in history)
            for history in histories
        ),
        batches=tuple(
            tuple(encode_branch(branch, invocation_positions) for branch in batch)
            for batch in batches
        ),
    )


def decode_branch(
    branch: Branch,
    invocations: tuple[tests.formal.helpers.pipeline_composition.Invocation, ...],
) -> tests.formal.helpers.pipeline_batches.Branch:
    """Restore prefix ownership without rerunning selection or partition policies.

    Args:
        branch: The serialized complete subtree.
        invocations: Typed immutable invocation table from the same checked corpus.

    Returns:
        Concrete replay inputs with the original children and terminal mark.
    """
    return tests.formal.helpers.pipeline_batches.Branch(
        invocation=invocations[branch.invocation],
        children=tuple(decode_branch(child, invocations) for child in branch.children),
        terminal=branch.terminal,
    )


def decode(value: Serialized) -> Prepared:
    """Restore lookup maps while keeping every raw graph node and successor intact.

    Args:
        value: Complete typed data from this run's successful producer.

    Returns:
        Full path contracts, ordered histories, and independently decoded batches.
    """
    checked = tests.formal.helpers.paths.Contract(
        graph=value.graph,
        values={node: value.values[index] for node, index in value.projections.items()},
        actions={
            edge: value.actions[index]
            for source, edges in value.graph.outgoing.items()
            for edge, index in zip(edges, value.transitions[source], strict=True)
        },
        internal=value.internal,
    )
    histories = tuple(
        tuple(value.invocations[index] for index in history)
        for history in value.histories
    )
    return Prepared(
        executions=tests.formal.helpers.pipeline_composition.Executions(
            checked=checked,
            histories={history[-1]: history for history in histories},
        ),
        batches=tuple(
            tuple(decode_branch(branch, value.invocations) for branch in batch)
            for batch in value.batches
        ),
    )


def build(directory: pathlib.Path) -> Serialized:
    """Run inventory validation before a processed graph becomes reusable evidence.

    Args:
        directory: Private staging directory within the current formal run.

    Returns:
        Checked raw graph plus all deterministic preprocessing and replay partitions.
    """
    return encode(
        tests.formal.helpers.pipeline_composition.executions(
            tests.formal.helpers.corpus.graph(
                "PipelineComposition",
                "PipelineComposition",
                directory,
            ),
        ),
    )


def load(directory: pathlib.Path) -> Prepared:
    """Use the corpus lock and atomic publication for the complete processed contract.

    Args:
        directory: Shared temporary storage owned by this formal invocation.

    Returns:
        Worker-local lookup maps and the producer's exact checked replay inventory.
    """
    return decode(
        tests.formal.helpers.corpus.load(
            directory,
            "pipeline-composition-processed",
            ADAPTER,
            build,
        ),
    )
