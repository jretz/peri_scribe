"""Replay complete checked authentication paths through real scoped byte reads."""

from __future__ import annotations

import collections
import collections.abc
import contextlib
import hashlib
import os
import pathlib
import re
import typing

import peri_scribe.sources.authentication
import tests.formal.helpers.tlc


if typing.TYPE_CHECKING:
    import tests.helpers.doubles.peri_scribe.sources.authentication


def edge_histories(
    graph: tests.formal.helpers.tlc.Graph,
) -> tuple[tuple[tests.formal.helpers.tlc.Edge, ...], ...]:
    """Exercise every actual transition with its complete shortest admitted prefix.

    Args:
        graph: Complete freshly checked TLC graph and initial-state identities.

    Returns:
        Histories covering every exported edge, retaining continuous source states.
    """
    paths: dict[int, tuple[tests.formal.helpers.tlc.Edge, ...]] = dict.fromkeys(
        graph.initial,
        (),
    )
    pending = collections.deque(graph.initial)
    while pending:
        node = pending.popleft()
        for edge in graph.outgoing.get(node, ()):
            if edge.target not in paths:
                paths[edge.target] = (*paths[node], edge)
                pending.append(edge.target)
    assert paths.keys() == graph.states.keys()
    return tuple(
        (*paths[edge.source], edge)
        for edges in graph.outgoing.values()
        for edge in edges
    )


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
                scopes.enter_context(
                    peri_scribe.sources.authentication.scope(directory),
                )
            elif after["active"] != before["active"]:
                scopes.close()
            elif after["stamps"] != before["stamps"]:
                revision = int(re.findall(r"\d+", after["revisions"])[0])
                source.write_bytes(revision_bytes(revision))
                os.utime(
                    source,
                    ns=(modification.st_atime_ns, modification.st_mtime_ns),
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
