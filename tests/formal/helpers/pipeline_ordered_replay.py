"""Compare the whole pipeline tape with continuous native witnesses.

See [Verification tooling](../../../docs/algorithms/verification-tooling.md).
"""

from __future__ import annotations

import collections.abc
import contextlib
import contextvars
import dataclasses
import errno
import os
import pathlib
import typing

import pytest

import peri_scribe.durable_file
import tests.formal.helpers.paths
import tests.formal.helpers.pipeline_batches
import tests.formal.helpers.pipeline_composition
import tests.formal.helpers.pipeline_effect_matrix
import tests.formal.helpers.pipeline_file_footprint
import tests.formal.helpers.pipeline_replay_files


files = tests.formal.helpers.pipeline_replay_files
batches = tests.formal.helpers.pipeline_batches
pipeline = tests.formal.helpers.pipeline_composition
matrix = tests.formal.helpers.pipeline_effect_matrix
type Checked = tests.formal.helpers.paths.Contract[pipeline.Durable]
type Completed = dict[batches.History, batches.Path]
type Witness = tuple[collections.abc.Hashable, ...]


@dataclasses.dataclass(kw_only=True)
class ReadTrace:
    """Own the raw reads of one active invocation."""

    directory: pathlib.Path
    events: list[files.Event]
    count: int = 0
    delegated: bool = False

    def record(
        self,
        reader: files.Reader,
        kind: files.ReadKind,
        name: str,
        value: files.ReadValue | files.Missing,
    ) -> None:
        """Give each raw reply an occurrence number independent of its value."""
        self.events.append(
            files.Read(
                reader=reader,
                kind=kind,
                name=name,
                value=value,
                number=self.count,
            ),
        )
        self.count += 1


ACTIVE: contextvars.ContextVar[ReadTrace | None] = contextvars.ContextVar(
    "ordered_pipeline_reads",
    default=None,
)


def missing_reply(error: FileNotFoundError, directory: pathlib.Path) -> files.Missing:
    """Keep the actual exception fields while relativizing the private year path.

    Returns:
        The complete missing-file reply at this boundary.
    """
    return files.Missing(
        error=type(error),
        arguments=error.args,
        number=error.errno,
        message=error.strerror,
        filename=(
            pathlib.Path(error.filename).relative_to(directory).as_posix()
            if error.filename is not None
            else None
        ),
        second_filename=error.filename2,
    )


def read_hook(
    original: collections.abc.Callable[..., files.ReadValue],
    reader: files.Reader,
    kind: files.ReadKind,
) -> collections.abc.Callable[..., files.ReadValue]:
    """Wrap one port method and leave the actual reply or exception with its caller.

    Returns:
        The same read with a single tape observation at the outermost port.
    """

    def observed(receiver: object, *args: object) -> files.ReadValue:
        """Retain the actual raw reply before continuing the pipeline.

        Returns:
            The unchanged native or memory reply.

        Raises:
            FileNotFoundError: When the underlying raw read reports a missing file.
        """
        active = ACTIVE.get()
        if active is None or active.delegated:
            return original(receiver, *args)
        if isinstance(receiver, peri_scribe.durable_file.LocalFile):
            name = receiver.path.relative_to(active.directory).as_posix()
        elif isinstance(receiver, files.File):
            name = receiver.name
        else:
            (path,) = args
            assert isinstance(path, pathlib.Path)
            name = path.relative_to(active.directory).as_posix()
        assert name in files.FILE_INDEX
        active.delegated = True
        try:
            value = original(receiver, *args)
        except FileNotFoundError as error:
            active.record(reader, kind, name, missing_reply(error, active.directory))
            raise
        else:
            active.record(reader, kind, name, value)
            return value
        finally:
            active.delegated = False

    return observed


def reject_path(path: pathlib.Path) -> typing.Never:
    """Keep memory invocations inside the reviewed lexical file ports.

    Raises:
        AssertionError: When a virtual path reaches a native filesystem operation.
    """
    raise AssertionError(("unmodeled native file access in pipeline replay", str(path)))


@contextlib.contextmanager
def trace_reads() -> collections.abc.Generator[None]:
    """Keep read observations local to the paired native and memory runs.

    Yields:
        Control with the actual file and fixture port reads observed.
    """
    original = pipeline.replay

    def replay(
        invocation: pipeline.Invocation,
        directory: pathlib.Path,
        checked: Checked,
        execution: batches.Path | None = None,
        *,
        memory: files.Memory | None = None,
        trace: list[files.Event] | None = None,
    ) -> batches.Path:
        """Run the unchanged pipeline and close its raw-read inventory.

        Returns:
            The actual continuing model path.
        """
        assert trace is not None
        active = ReadTrace(directory=directory, events=trace)
        token = ACTIVE.set(active)
        try:
            result = original(
                invocation,
                directory,
                checked,
                execution,
                memory=memory,
                trace=trace,
            )
        finally:
            ACTIVE.reset(token)
        trace.append(files.ReadCount(total=active.count))
        return result

    with pytest.MonkeyPatch.context() as patch:
        for owner in (peri_scribe.durable_file.LocalFile, files.File):
            for kind in (
                files.ReadKind.BYTES,
                files.ReadKind.EXISTS,
                files.ReadKind.IDENTITY,
            ):
                patch.setattr(
                    owner,
                    kind,
                    read_hook(
                        getattr(owner, kind),
                        files.Reader.PRODUCTION,
                        kind,
                    ),
                )
        for kind in (files.ReadKind.BYTES, files.ReadKind.EXISTS, files.ReadKind.STAMP):
            patch.setattr(
                files.Artifacts,
                kind,
                read_hook(
                    getattr(files.Artifacts, kind),
                    files.Reader.FIXTURE,
                    kind,
                ),
            )
        patch.setattr(pipeline, "replay", replay)
        patch.setattr(files.MemoryPath, "__fspath__", reject_path)
        yield


def expected_reply(
    image: files.Image,
    event: files.Read,
) -> files.ReadValue | files.Missing:
    """Read the target of this actual command in the independently replayed frame.

    Returns:
        The exact bytes, presence, timestamp, identity, or missing reply.
    """
    entry = image[files.FILE_INDEX[event.name]]
    if event.kind is files.ReadKind.EXISTS:
        return entry is not None
    if entry is None:
        message = os.strerror(errno.ENOENT)
        return files.Missing(
            error=FileNotFoundError,
            arguments=(errno.ENOENT, message),
            number=errno.ENOENT,
            message=message,
            filename=event.name,
            second_filename=None,
        )
    if event.kind is files.ReadKind.BYTES:
        return entry.content
    assert event.name == files.KMZ
    stamp = entry.modified_nanoseconds
    assert stamp is not None
    assert stamp >= 0
    return stamp if event.kind is files.ReadKind.STAMP else (len(entry.content), stamp)


@dataclasses.dataclass(frozen=True, kw_only=True)
class Prefix:
    """Carry the complete immutable bytes and matcher count into a continuation."""

    image: files.Image = (None,) * len(files.FILES)
    maps_present: bool = False
    observations: int = 0


def verify_tape(
    prior: Prefix,
    invocation: pipeline.Invocation,
    tape: list[files.Event],
    footprint: tests.formal.helpers.pipeline_file_footprint.Footprint,
) -> Prefix:
    """Check every actual raw reply and full durable effect in original order.

    Returns:
        The immutable frame observed when this invocation ended.

    Raises:
        AssertionError: When a reply or event disagrees with its actual prefix.
    """
    image, maps_present = prior.image, prior.maps_present
    observations = prior.observations + 1
    reads = 0
    failures = []
    calls = None
    *events, count = tape
    assert isinstance(count, files.ReadCount)
    for event in events:
        if calls is not None:
            assert isinstance(event, files.Read)
        match event:
            case files.Read():
                expected = expected_reply(image, event)
                assert type(event.value) is type(expected)
                assert event.value == expected
                assert event.number == reads
                reads += 1
            case files.Mutation(effect=effect, after=after):
                maps_present = (
                    maps_present or effect.operation is files.Operation.PUBLISH
                )
                assert effect.before == image
                assert effect.maps_present == maps_present
                index = files.FILE_INDEX[effect.name]
                matrix.lift_footprint(
                    effect,
                    after,
                    footprint.transfer(
                        effect.operation,
                        present=image[index] is not None,
                    ),
                )
                image = after
            case files.Observation(image=observed):
                assert observed == image
                observations += 1
            case files.Failure(boundary=boundary, image=observed):
                assert observed == image
                failures.append(boundary)
                observations += 1
            case files.Calls():
                calls = event
            case _:
                raise AssertionError(("unexpected ordered pipeline event", event))
    assert reads == count.total
    assert calls is not None
    assert (calls.stages, calls.forces) == (invocation.executed, invocation.forces)
    assert failures == ([invocation.failed_at] if invocation.failed_at else [])
    return Prefix(image=image, maps_present=maps_present, observations=observations)


def verify(
    roots: tuple[batches.Branch, ...],
    tapes: batches.Traces,
    completed: Completed,
    footprint: tests.formal.helpers.pipeline_file_footprint.Footprint,
) -> None:
    """Visit every actual prefix, checking its bytes and independent matcher count."""
    visited = set()

    def visit(branch: batches.Branch, parent: batches.History, before: Prefix) -> None:
        """Continue from the actual parent's immutable file image."""
        history = (*parent, branch.invocation)
        assert history not in visited
        visited.add(history)
        after = verify_tape(before, branch.invocation, tapes[history], footprint)
        if branch.terminal:
            assert after.observations == completed[history].observations
        for child in branch.children:
            visit(child, history, after)

    for branch in roots:
        visit(branch, (), Prefix())
    assert visited == tapes.keys()


def categories(history: batches.History, tape: list[files.Event]) -> set[Witness]:
    """Identify exact raw classes requiring a continuous native witness.

    Returns:
        The read, write, failure and dispatch classes observed in this invocation.
    """
    result: set[Witness] = set()
    for event in tape:
        match event:
            case files.Read(reader=reader, kind=kind, name=name, value=value):
                result.add(("read", reader, kind, name, value))
            case files.Mutation(effect=effect, after=after):
                offset = files.FILE_INDEX[effect.name]
                result.add((
                    "write",
                    effect.operation,
                    effect.name,
                    effect.maps_present,
                    effect.before[offset],
                    effect.argument,
                    after[offset],
                ))
            case files.Failure(boundary=boundary, image=image):
                result.add(("failure", boundary, history[-1].current, image))
            case files.Calls(stages=stages, forces=forces):
                result.add(("dispatch", stages, forces))
    return result


def witness_masks(tapes: batches.Traces) -> tuple[dict[batches.History, int], int]:
    """Encode each exact class as one bit in the local witness inventory.

    Returns:
        Each prefix's immutable class mask and the complete required mask.
    """
    classes: dict[Witness, int] = {}
    masks = {}
    for history, tape in tapes.items():
        masks[history] = sum(
            1 << classes.setdefault(fact, len(classes))
            for fact in categories(history, tape)
        )
    return masks, (1 << len(classes)) - 1


def representatives(
    roots: tuple[batches.Branch, ...],
    tapes: batches.Traces,
) -> tuple[tuple[batches.History, ...], frozenset[batches.History]]:
    """Cover each class using original histories and their actual native ancestors.

    Returns:
        The selected terminal histories and all their replayed prefixes.
    """
    masks, required = witness_masks(tapes)
    histories = tuple(masks)
    indices = {history: index for index, history in enumerate(histories)}
    coverage = tuple(masks.values())
    remaining = required
    candidates = tuple(
        tuple(indices[history[:position]] for position in range(1, len(history) + 1))
        for history in batches.histories(roots)
    )
    retained: set[int] = set()
    chosen = []

    def priority(prefixes: tuple[int, ...]) -> tuple[float, int]:
        """Prefer the most uncovered classes per additional native invocation.

        Returns:
            Coverage per new prefix followed by absolute coverage.
        """
        fresh = gained = 0
        for prefix in prefixes:
            if prefix not in retained:
                fresh += 1
                gained |= coverage[prefix]
        count = (gained & remaining).bit_count()
        return (count / fresh, count) if fresh else (0, 0)

    while remaining:
        prefixes = max(candidates, key=priority)
        assert priority(prefixes)[1]
        retained.update(prefixes)
        for prefix in prefixes:
            remaining &= ~coverage[prefix]
        chosen.append(histories[prefixes[-1]])
    covered = 0
    for prefix in retained:
        covered |= coverage[prefix]
    assert covered == required
    return tuple(chosen), frozenset(histories[index] for index in retained)


def compare(
    roots: tuple[batches.Branch, ...],
    directory: pathlib.Path,
    checked: Checked,
    footprint: tests.formal.helpers.pipeline_file_footprint.Footprint,
) -> bool:
    """Verify every logical trace and run the selected histories on real private files.

    Returns:
        Whether the complete recorded input domain was admitted.
    """
    tapes: batches.Traces = {}
    native_tapes: batches.Traces = {}
    with trace_reads():
        completed = batches.replay_memory(
            roots,
            directory / "memory",
            checked,
            {},
            traces=tapes,
        )
        assert completed.keys() == set(batches.histories(roots))
        if not all(
            matrix.footprint_input(event.effect)
            for tape in tapes.values()
            for event in tape
            if isinstance(event, files.Mutation)
        ):
            return False
        verify(roots, tapes, completed, footprint)
        selected, retained = representatives(roots, tapes)
        native_roots = batches.trees(selected)
        native = batches.replay(
            native_roots,
            directory / "native",
            checked,
            traces=native_tapes,
        )
    assert native == {history: completed[history] for history in selected}
    assert native_tapes.keys() == retained
    verify(native_roots, native_tapes, native, footprint)
    assert all(tape == tapes[history] for history, tape in native_tapes.items())
    return True
