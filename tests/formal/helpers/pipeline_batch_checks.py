"""Check prefix sharing against independent concrete files and complete executions."""

import collections.abc
import dataclasses
import os
import pathlib
import stat

import peri_scribe.pipeline_state
import tests.formal.helpers.paths
import tests.formal.helpers.pipeline_batches
import tests.formal.helpers.pipeline_composition
import tests.formal.helpers.tlc


type Invocation = tests.formal.helpers.pipeline_composition.Invocation
type Durable = tests.formal.helpers.pipeline_composition.Durable
type Execution = tests.formal.helpers.paths.Path[Durable]
type Contract = tests.formal.helpers.paths.Contract[Durable]
type History = tuple[Invocation, ...]
type Replay = collections.abc.Callable[
    [Invocation, pathlib.Path, Contract, Execution | None],
    Execution,
]


def invocations() -> tuple[Invocation, ...]:
    """Equal durable projections must not collapse distinct control-event prefixes.

    Returns:
        Distinct invocations whose durable before and after states all agree.
    """
    value = tests.formal.helpers.pipeline_composition.Durable(
        source=0,
        outputs=(0, 0, 0, 0),
        pending=peri_scribe.pipeline_state.PendingRun(),
        deferred=False,
        kmz_version=0,
        publication_version=0,
        publication=0,
    )
    return tuple(
        tests.formal.helpers.pipeline_composition.Invocation(
            before=value,
            after=value,
            first=0,
            last=4,
            gated=False,
            forced=False,
            changed=False,
            threshold=False,
            current=index,
            failed_at="",
            executed=(),
            forces=(),
        )
        for index in range(5)
    )


def histories() -> tuple[History, ...]:
    """Include terminal internal nodes and equal suffixes below different roots.

    Returns:
        Complete histories with shared prefixes and deliberately distinct parents.
    """
    first, second, third, fourth, fifth = invocations()
    return (
        (first, second),
        (fourth, second),
        (first,),
        (first, third),
        (fourth, second, fifth),
    )


def terminal_histories(
    branches: tuple[tests.formal.helpers.pipeline_batches.Branch, ...],
    prefix: History = (),
) -> tuple[History, ...]:
    """Recover complete requested histories independently of the partitioner.

    Args:
        branches: A forest of retained invocation prefixes.
        prefix: The actual ancestors of these branches.

    Returns:
        Every terminal history, including terminals with further descendants.
    """
    result = []
    for branch in branches:
        history = (*prefix, branch.invocation)
        if branch.terminal:
            result.append(history)
        result.extend(terminal_histories(branch.children, history))
    return tuple(result)


@dataclasses.dataclass(frozen=True, kw_only=True)
class File:
    """Copy correctness includes metadata that byte equality cannot establish."""

    content: bytes
    modified_nanoseconds: int
    mode: int


@dataclasses.dataclass(frozen=True, kw_only=True)
class Image:
    """Retain every real file and directory, including empty and unmodeled entries."""

    files: dict[pathlib.Path, File]
    directories: frozenset[pathlib.Path]


def image(directory: pathlib.Path) -> Image:
    """Observe persisted data without consulting the expected durable projection.

    Args:
        directory: The actual year tree to inspect.

    Returns:
        Complete relative file contents, metadata, and directory membership.
    """
    files = {}
    directories = set()
    for path in directory.rglob("*"):
        relative = path.relative_to(directory)
        if path.is_dir():
            directories.add(relative)
        else:
            status = path.stat()
            files[relative] = File(
                content=path.read_bytes(),
                modified_nanoseconds=status.st_mtime_ns,
                mode=stat.S_IMODE(status.st_mode),
            )
    return Image(files=files, directories=frozenset(directories))


@dataclasses.dataclass(frozen=True, kw_only=True)
class BranchProbe:
    """Detect regenerated matchers, incomplete clones, and shared branch mutations."""

    histories: dict[int, History] = dataclasses.field(default_factory=dict)
    paths: dict[History, Execution] = dataclasses.field(default_factory=dict)
    directories: dict[History, pathlib.Path] = dataclasses.field(default_factory=dict)
    images: dict[History, Image] = dataclasses.field(default_factory=dict)

    def replay(
        self,
        invocation: Invocation,
        directory: pathlib.Path,
        checked: Contract,
        execution: Execution | None = None,
    ) -> Execution:
        """A sibling must begin from its exact parent's retained concrete execution.

        Args:
            invocation: Distinct controls sharing an intentionally equal projection.
            directory: This branch's independent year directory.
            checked: The shared immutable path contract.
            execution: The exact preceding matcher, when this is not a root.

        Returns:
            A distinct matcher whose ownership identifies the complete prefix.
        """
        parent = () if execution is None else self.histories[id(execution)]
        history = (*parent, invocation)
        assert history not in self.paths
        assert directory.name == "2026"
        if execution is None:
            directory.mkdir(parents=True)
            (directory / "empty").mkdir()
            (directory / "nested").mkdir()
            (directory / "nested" / "retained").write_bytes(b"unmodeled input")
        else:
            assert execution is self.paths[parent]
            assert image(directory) == self.images[parent]
            (directory / "nested" / "retained").unlink(missing_ok=True)
            (directory / f"child-{invocation.current}").write_bytes(b"new child file")
        changed = directory / "changed"
        changed.write_text(str(invocation.current))
        changed.chmod(0o640)
        nanoseconds = (invocation.current + 2) * 1_000_000_000 + 123_456_789
        os.utime(changed, ns=(nanoseconds, nanoseconds))
        if execution is not None:
            assert image(self.directories[parent]) == self.images[parent]
        result = tests.formal.helpers.paths.Path(
            contract=checked,
            candidates=frozenset({invocation.current}),
            value=invocation.after,
            observations=1 if execution is None else execution.observations + 1,
        )
        self.histories[id(result)] = history
        self.paths[history] = result
        self.directories[history] = directory
        self.images[history] = image(directory)
        return result


def contract() -> Contract:
    """The cloning probe owns matching behavior without requiring a Java process.

    Returns:
        An inert typed contract retained by every synthetic execution matcher.
    """
    return tests.formal.helpers.paths.Contract(
        graph=tests.formal.helpers.tlc.Graph(
            states={},
            initial=frozenset(),
            outgoing={},
        ),
        values={},
        actions={},
        internal=frozenset(),
    )


@dataclasses.dataclass(frozen=True, kw_only=True)
class ObservedReplay:
    """Record real coordinator effects before the caller removes its private files."""

    original: Replay
    histories: dict[int, History] = dataclasses.field(default_factory=dict)
    paths: dict[History, Execution] = dataclasses.field(default_factory=dict)
    images: dict[History, Image] = dataclasses.field(default_factory=dict)

    def replay(
        self,
        invocation: Invocation,
        directory: pathlib.Path,
        checked: Contract,
        execution: Execution | None = None,
    ) -> Execution:
        """Retain actual results while preserving all real assertions and side effects.

        Args:
            invocation: Checked controls and crash boundary for the current call.
            directory: Its independently persisted year tree.
            checked: The complete checked TLC transition contract.
            execution: The actual preceding invocation matcher, when present.

        Returns:
            The unchanged result from the real pipeline replay.
        """
        history = (
            *(self.histories[id(execution)] if execution is not None else ()),
            invocation,
        )
        result = self.original(invocation, directory, checked, execution)
        self.histories[id(result)] = history
        self.paths[history] = result
        self.images[history] = image(directory)
        return result


def selected_histories(
    executions: tests.formal.helpers.pipeline_composition.Executions,
) -> tuple[History, ...]:
    """Exercise real branch sharing across interruption and publication recovery cases.

    Args:
        executions: The complete checked invocation inventory.

    Returns:
        A bounded selection including each relevant retained-state condition.
    """
    available = tuple(executions.histories.values())
    interrupted = next(
        history
        for history in available
        if any(record.failed_at for record in history[:-1])
    )
    deferred = next(
        history
        for history in available
        if any(record.before.deferred for record in history[1:])
    )
    stale = next(
        history
        for history in available
        if any(
            record.before.publication >= 0
            and record.before.publication_version != record.before.kmz_version
            for record in history[1:]
        )
    )
    first = next(history for history in available if len(history) > 1)
    sibling = next(
        history
        for history in available
        if len(history) > 1 and history[0] == first[0] and history[1] != first[1]
    )
    return tuple(
        dict.fromkeys((
            interrupted,
            deferred,
            stale,
            first,
            sibling,
            max(available, key=len),
        )),
    )
