"""Replay complete checked authentication paths through real scoped byte reads.

Design notes:
[Verification evidence and execution](../../../docs/algorithms/verification-tooling.md).
"""

from __future__ import annotations

import collections
import collections.abc
import contextlib
import hashlib
import pathlib
import re

import peri_scribe.sources.authentication
import tests.formal.helpers.tlc
import tests.helpers.doubles.peri_scribe.sources.authentication
import tests.helpers.factories.peri_scribe.sources.authentication


type Occurrence = tuple[int, int]


def maximal_edge_histories(
    graph: tests.formal.helpers.tlc.Graph,
) -> tuple[tuple[tests.formal.helpers.tlc.Edge, ...], ...]:
    """Exercise each edge with its shortest prefix, sharing exact prefixes.

    Args:
        graph: Complete freshly checked TLC graph and initial-state identities.

    Returns:
        Maximal histories covering every exported edge occurrence and prefix.
    """
    paths: dict[int, tuple[Occurrence, ...]] = dict.fromkeys(
        graph.initial,
        (),
    )
    pending = collections.deque(graph.initial)
    while pending:
        node = pending.popleft()
        for index, edge in enumerate(graph.outgoing.get(node, ())):
            if edge.target not in paths:
                paths[edge.target] = (*paths[node], (node, index))
                pending.append(edge.target)
    assert paths.keys() == graph.states.keys()
    prefixes = {paths[node] for node, edges in graph.outgoing.items() if edges}
    occurrences = {
        (node, index)
        for node, edges in graph.outgoing.items()
        for index in range(len(edges))
    }
    histories = []
    for node, edges in graph.outgoing.items():
        for index in range(len(edges)):
            history = (*paths[node], (node, index))
            if history not in prefixes:
                histories.append(history)
    assert {step for history in histories for step in history} == occurrences
    return tuple(
        tuple(graph.outgoing[node][index] for node, index in history)
        for history in histories
    )


@contextlib.contextmanager
def checked_scope(
    directory: pathlib.Path,
) -> collections.abc.Generator[peri_scribe.sources.authentication.Scope]:
    """Observe cleanup of the real scope opened for this replay.

    Args:
        directory: Private source directory requiring a new owner.

    Yields:
        The current owner, whose evidence the finalizer must clear.
    """
    previous = peri_scribe.sources.authentication.CURRENT.get()
    with peri_scribe.sources.authentication.scope(directory):
        owner = peri_scribe.sources.authentication.CURRENT.get()
        assert owner is not None
        assert owner is not previous
        yield owner
    assert peri_scribe.sources.authentication.CURRENT.get() is previous
    assert not owner.active.is_set()
    assert not owner.values
    assert not owner.pending


def revision_bytes(revision: int) -> bytes:
    """Give the two modeled revisions equal-sized distinct authoritative payloads.

    Args:
        revision: Checked nonempty revision identifier.

    Returns:
        Concrete source bytes corresponding to that revision.
    """
    return {1: b"first", 2: b"other"}[revision]


def replay(
    graph: tests.formal.helpers.tlc.Graph,
    history: collections.abc.Sequence[tests.formal.helpers.tlc.Edge],
    directory: pathlib.Path,
    recorder: tests.helpers.doubles.peri_scribe.sources.authentication.DigestRecorder,
    *,
    inventory_first: bool,
) -> None:
    """Compare real checksums and byte-read counts with the checked transition path.

    Args:
        graph: Complete checked model containing this exact history.
        history: Continuous checked transitions starting at an initial node.
        directory: Independent temporary source directory for this concrete replay.
        recorder: Real byte reader recording actual authentication work.
        inventory_first: Which authentication entry point starts the alternating reads.
    """
    directory.mkdir()
    source = directory / "snapshot"
    source.write_bytes(revision_bytes(1))
    modification = source.stat()
    node = history[0].source
    assert node in graph.initial
    requests = 0
    with contextlib.ExitStack() as scopes:
        for edge in history:
            assert edge.source == node
            before = graph.states[edge.source]
            after = graph.states[edge.target]
            if after["scope"] != before["scope"]:
                scopes.enter_context(checked_scope(directory))
            elif after["active"] != before["active"]:
                scopes.close()
            elif after["stamps"] != before["stamps"]:
                revision = int(re.findall(r"\d+", after["revisions"])[0])
                tests.helpers.factories.peri_scribe.sources.authentication.rewrite_with_changed_ctime(
                    source,
                    revision_bytes(revision),
                    timestamps=(modification.st_atime_ns, modification.st_mtime_ns),
                )
            else:
                calls = len(recorder.paths)
                use_inventory = (requests % 2 == 0) == inventory_first
                authenticate = (
                    peri_scribe.sources.authentication.inventory_digest
                    if use_inventory
                    else peri_scribe.sources.authentication.file_digest
                )
                checksum = authenticate(source)
                requests += 1
                answer = [int(value) for value in re.findall(r"\d+", after["answer"])]
                assert checksum == hashlib.sha256(revision_bytes(answer[0])).hexdigest()
                assert checksum == hashlib.sha256(revision_bytes(answer[1])).hexdigest()
                assert len(recorder.paths) - calls == (
                    int(after["hashes"]) - int(before["hashes"])
                )
            node = edge.target
