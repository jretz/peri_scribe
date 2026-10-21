"""Replay checked worker outcomes and joined admission through real byte readers."""

from __future__ import annotations

import collections.abc
import concurrent.futures
import contextlib
import dataclasses
import enum
import hashlib
import os
import pathlib
import re
import threading
import unittest.mock

import pytest

import peri_scribe.sources.authentication
import tests.formal.helpers.source_authentication
import tests.formal.helpers.tlc
import tests.helpers.factories.peri_scribe.sources.authentication


class Worker(enum.IntEnum):
    """Map the checked finite worker outcomes to their exact exported integers."""

    COMPLETE = 1
    FAILED = 2
    STOPPED = 3


@dataclasses.dataclass(frozen=True, kw_only=True)
class Replay:
    """Keep the concrete files, completed reads and owner for one checked history."""

    paths: tuple[pathlib.Path, ...]
    modifications: tuple[os.stat_result, ...]
    scopes: contextlib.ExitStack
    owner: peri_scribe.sources.authentication.Scope
    evidence: dict[pathlib.Path, peri_scribe.sources.authentication.Evidence] = (
        dataclasses.field(default_factory=dict)
    )
    cancelled: threading.Event = dataclasses.field(default_factory=threading.Event)


def numbers(value: str) -> tuple[int, ...]:
    """Decode finite sequences from actual checked TLC states.

    Args:
        value: Raw numeric sequence exported by TLC.

    Returns:
        Sequence entries in their checked order.
    """
    return tuple(map(int, re.findall(r"\d+", value)))


def changed_position(before: str, after: str) -> int:
    """Select the single position changed by the checked source or worker action.

    Args:
        before: Exact TLC sequence preceding this edge.
        after: Exact TLC sequence following this edge.

    Returns:
        The changed sequence position.
    """
    previous = numbers(before)
    return next(i for i, value in enumerate(numbers(after)) if value != previous[i])


def worker_transition(runtime: Replay, before: str, after: str) -> str:
    """Execute each checked outcome through the actual isolated batch reader.

    Args:
        runtime: Concrete source and evidence state for this history.
        before: Worker sequence before the action.
        after: Worker sequence after the action.

    Returns:
        The exercised worker action family.
    """
    changed = changed_position(before, after)
    path = runtime.paths[changed]
    outcome = numbers(after)[changed]
    if outcome == Worker.COMPLETE:
        runtime.evidence.update(
            peri_scribe.sources.authentication.isolated_inventory_batch(
                (path,),
                runtime.cancelled,
            ),
        )
        return "read"
    if outcome == Worker.FAILED:
        with (
            unittest.mock.patch.object(
                peri_scribe.sources.authentication,
                "read_file_digest",
                side_effect=OSError("modeled source failure"),
            ),
            pytest.raises(OSError, match="modeled source failure"),
        ):
            peri_scribe.sources.authentication.isolated_inventory_batch(
                (path,),
                threading.Event(),
            )
        return "failure"
    assert outcome == Worker.STOPPED
    stopped = threading.Event()
    stopped.set()
    with pytest.raises(concurrent.futures.CancelledError):
        peri_scribe.sources.authentication.isolated_inventory_batch((path,), stopped)
    return "stop"


def edit(runtime: Replay, before: str, after: str) -> None:
    """Realize the checked edit with equal-size bytes and restored modification time.

    Args:
        runtime: Concrete source state for this history.
        before: Source stamps before the checked edit.
        after: Source stamps after the checked edit.
    """
    changed = changed_position(before, after)
    path = runtime.paths[changed]
    modification = runtime.modifications[changed]
    tests.helpers.factories.peri_scribe.sources.authentication.rewrite_with_changed_ctime(
        path,
        tests.formal.helpers.source_authentication.revision_bytes(
            numbers(after)[changed],
        ),
        timestamps=(modification.st_atime_ns, modification.st_mtime_ns),
    )


def resolve(runtime: Replay, before: dict[str, str], after: dict[str, str]) -> str:
    """Use checked outcomes as the oracle for actual complete pending admission.

    Args:
        runtime: Joined concrete results and current owner.
        before: Exact checked state before the admission decision.
        after: Exact checked state after the admission decision.

    Returns:
        The observed publication or rejection action family.
    """
    assert before["joined"] == "TRUE"
    if numbers(before["workers"]) != (1, 1) or runtime.cancelled.is_set():
        return "failed_join"
    if after["phase"] == '"published"':
        peri_scribe.sources.authentication.publish_inventory_evidence(
            runtime.owner,
            runtime.evidence,
        )
        return "publish"
    with pytest.raises(OSError, match=r"Source changed|scope expired"):
        peri_scribe.sources.authentication.publish_inventory_evidence(
            runtime.owner,
            runtime.evidence,
        )
    return "reject"


def transition(
    runtime: Replay,
    before: dict[str, str],
    after: dict[str, str],
) -> tuple[Replay, str]:
    """Map every checked transition to a concrete read, edit or ownership action.

    Args:
        runtime: Concrete state after the complete preceding checked prefix.
        before: The checked edge's source state.
        after: The checked edge's target state.

    Returns:
        The concrete successor and exercised action family.
    """
    if before["workers"] != after["workers"]:
        action = worker_transition(runtime, before["workers"], after["workers"])
    elif before["stamps"] != after["stamps"]:
        edit(runtime, before["stamps"], after["stamps"])
        action = "edit"
    elif before["cancelled"] != after["cancelled"]:
        runtime.cancelled.set()
        action = "cancel"
    elif before["sameProcess"] != after["sameProcess"]:
        owner = dataclasses.replace(runtime.owner, process=os.getpid() + 1)
        runtime = dataclasses.replace(runtime, owner=owner)
        action = "fork"
    elif after["phase"] == '"cleaned"':
        runtime.scopes.close()
        action = "cleanup"
    elif before["active"] != after["active"]:
        runtime.owner.active.clear()
        action = "expire"
    elif after["phase"] == '"joined"':
        assert all(numbers(after["workers"]))
        action = "join"
    else:
        assert after["phase"] in {'"published"', '"aborted"'}
        action = resolve(runtime, before, after)
    return runtime, action


def assert_pending(runtime: Replay, checked: str) -> None:
    """Compare actual pending publication with the exact checked source revisions.

    Args:
        runtime: Concrete successor state after a checked edge.
        checked: Exact pending sequence exported by TLC.
    """
    pending = numbers(checked)
    if pending == (0, 0):
        assert not runtime.owner.pending
        return
    assert set(runtime.owner.pending) == set(runtime.paths)
    for index, path in enumerate(runtime.paths):
        expected = tests.formal.helpers.source_authentication.revision_bytes(
            pending[index],
        )
        assert (
            runtime.owner.pending[path].checksum == hashlib.sha256(expected).hexdigest()
        )
        assert runtime.owner.pending[path].stamp == (
            peri_scribe.sources.authentication.file_stamp(path)
        )


def replay(
    graph: tests.formal.helpers.tlc.Graph,
    history: collections.abc.Sequence[tests.formal.helpers.tlc.Edge],
    directory: pathlib.Path,
) -> set[str]:
    """Replay every edge with its complete admitted prefix and concrete source files.

    Actual batch calls finish before the modeled join. Ordinary tests additionally
    check concurrent shutdown and admission through the complete inventory API.

    Args:
        graph: Fresh complete checked graph containing this path.
        history: Checked transitions with a complete prefix from the initial state.
        directory: Private temporary sources for this history.

    Returns:
        The checked action families actually exercised by this replay.
    """
    directory.mkdir()
    paths = (directory / "first", directory / "second")
    for path in paths:
        path.write_bytes(tests.formal.helpers.source_authentication.revision_bytes(1))
    observed = set()
    node = history[0].source
    assert node in graph.initial
    with contextlib.ExitStack() as scopes:
        scopes.enter_context(peri_scribe.sources.authentication.scope(directory))
        owner = peri_scribe.sources.authentication.CURRENT.get()
        assert owner is not None
        runtime = Replay(
            paths=paths,
            modifications=tuple(path.stat() for path in paths),
            scopes=scopes,
            owner=owner,
        )
        for edge in history:
            assert edge.source == node
            before = graph.states[edge.source]
            after = graph.states[edge.target]
            runtime, action = transition(runtime, before, after)
            observed.add(action)
            assert_pending(runtime, after["pending"])
            node = edge.target
    return observed
