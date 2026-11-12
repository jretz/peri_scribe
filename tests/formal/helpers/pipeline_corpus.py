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
    """Retain exact nodes and edges alongside every precomputed conformance decision."""

    field_rows: tuple[tuple[tuple[str, str], ...], ...]
    states: dict[int, int]
    initials: frozenset[int]
    labels: tuple[str, ...]
    edges: dict[int, tuple[tuple[int, int, int], ...]]
    values: tuple[tests.formal.helpers.pipeline_composition.Durable, ...]
    projections: dict[int, int]
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
        Typed data containing matcher fields, ordered edges, and all replay decisions.
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
    fields = {node: tuple(row.items()) for node, row in checked.graph.states.items()}
    field_rows = tuple(dict.fromkeys(fields.values()))
    field_positions = {row: index for index, row in enumerate(field_rows)}
    labels = tuple(
        dict.fromkeys(
            label
            for edges in checked.graph.outgoing.values()
            for edge in edges
            for label in (edge.action, checked.actions[edge])
        ),
    )
    label_positions = {label: index for index, label in enumerate(labels)}
    invocations = tuple(
        dict.fromkeys(invocation for history in histories for invocation in history),
    )
    invocation_positions = {value: index for index, value in enumerate(invocations)}
    return Serialized(
        field_rows=field_rows,
        states={node: field_positions[row] for node, row in fields.items()},
        initials=checked.graph.initial,
        labels=labels,
        edges={
            node: tuple(
                (
                    edge.target,
                    label_positions[edge.action],
                    label_positions[checked.actions[edge]],
                )
                for edge in edges
            )
            for node, edges in checked.graph.outgoing.items()
        },
        values=values,
        projections={
            node: value_positions[value] for node, value in checked.values.items()
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
    """Restore lookup maps while keeping every graph node and successor intact.

    Args:
        value: Complete typed data from this run's successful producer.

    Returns:
        Full path contracts, ordered histories, and independently decoded batches.
    """
    outgoing: dict[int, tuple[tests.formal.helpers.tlc.Edge, ...]] = {}
    actions = {}
    for source, entries in value.edges.items():
        edges = []
        for target, label, projection in entries:
            edge = tests.formal.helpers.tlc.Edge(
                source=source,
                target=target,
                action=value.labels[label],
            )
            edges.append(edge)
            actions[edge] = value.labels[projection]
        outgoing[source] = tuple(edges)
    checked = tests.formal.helpers.paths.Contract(
        graph=tests.formal.helpers.tlc.Graph(
            states={
                node: dict(value.field_rows[index])
                for node, index in value.states.items()
            },
            initial=value.initials,
            outgoing=outgoing,
        ),
        values={node: value.values[index] for node, index in value.projections.items()},
        actions=actions,
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
        Checked replay contract and partitions derived from the full TLC graph.
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
