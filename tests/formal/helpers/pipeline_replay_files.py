"""Store actual modeled artifact bytes and record each durable mutation."""

from __future__ import annotations

import collections.abc
import dataclasses
import enum
import errno
import os
import pathlib
import typing


KMZ = "maps/PeriScribe Fires 2026.kmz"
PENDING = "run_state.json"
DEFERRED = "deferred_inputs"
CHECKPOINT = "publication_state.json"
FILES = (
    "source-generation",
    "output-1",
    "output-2",
    "output-4",
    KMZ,
    PENDING,
    DEFERRED,
    CHECKPOINT,
)
FILE_INDEX = {name: index for index, name in enumerate(FILES)}
MARKERS = frozenset(FILES[-3:])


@dataclasses.dataclass(frozen=True, kw_only=True)
class Entry:
    """Track bytes and the KMZ timestamp used to validate publication identity."""

    content: bytes
    modified_nanoseconds: int | None = None


type Image = tuple[Entry | None, ...]


class Operation(enum.StrEnum):
    """Distinguish atomic state replacement from generation fixture writes."""

    REPLACE = "replace"
    TOUCH = "touch"
    REMOVE = "remove"
    WRITE = "write"
    PUBLISH = "publish"


@dataclasses.dataclass(frozen=True, kw_only=True)
class Effect:
    """Recreate a real mutation from the complete modeled precondition."""

    before: Image
    maps_present: bool
    operation: Operation
    name: str
    argument: bytes | bool | Entry


type Effects = dict[Effect, Image]


@dataclasses.dataclass(frozen=True, kw_only=True)
class Mutation:
    """Record a durable mutation before delivering its resulting observation."""

    effect: Effect
    after: Image


@dataclasses.dataclass(frozen=True, kw_only=True)
class Observation:
    """Record the independent image presented to the matcher."""

    image: Image


@dataclasses.dataclass(frozen=True, kw_only=True)
class Failure:
    """Separate an interruption from the preceding durable mutation."""

    boundary: str
    image: Image


@dataclasses.dataclass(frozen=True, kw_only=True)
class Calls:
    """Retain actual coordinator dispatch and effective forcing."""

    stages: tuple[int, ...]
    forces: tuple[bool, ...]


class ReadKind(enum.StrEnum):
    """Distinguish the replies observed at the raw file port."""

    BYTES = "read_bytes"
    EXISTS = "exists"
    STAMP = "modified_nanoseconds"
    IDENTITY = "identity"


class Reader(enum.StrEnum):
    """Keep the production and fixture read boundaries distinct."""

    PRODUCTION = "production"
    FIXTURE = "fixture"


@dataclasses.dataclass(frozen=True, kw_only=True)
class Missing:
    """Preserve a native missing reply with its path relative to the private year."""

    error: type[FileNotFoundError]
    arguments: tuple[object, ...]
    number: int | None
    message: str | None
    filename: str | None
    second_filename: str | None


type ReadValue = bytes | bool | int | tuple[int, int]


@dataclasses.dataclass(frozen=True, kw_only=True)
class Read:
    """Record a real reply in its original position in one invocation."""

    reader: Reader
    kind: ReadKind
    name: str
    value: ReadValue | Missing
    number: int


@dataclasses.dataclass(frozen=True, kw_only=True)
class ReadCount:
    """Retain the invocation's independent count of issued raw reads."""

    total: int


type Event = Mutation | Observation | Failure | Calls | Read | ReadCount


class MemoryPath(pathlib.Path):
    """Share lexical paths across one replay while each branch owns its bytes."""

    __slots__ = ("children",)

    def __init__(self, *parts: str | os.PathLike[str]) -> None:
        """Initialize a path whose children use ordinary pathlib join semantics."""
        super().__init__(*parts)
        self.children: dict[str, typing.Self] = {}

    @typing.override
    def __truediv__(self, key: str | os.PathLike[str]) -> typing.Self:
        """Reuse repeated string joins and their cached path hashes.

        Args:
            key: The path component used by the coordinator or replay observer.

        Returns:
            The same joined path that pathlib would construct.
        """
        if not isinstance(key, str):
            return super().__truediv__(key)
        child = self.children.get(key)
        if child is None:
            child = super().__truediv__(key)
            self.children[key] = child
        return child


def read_image(year: pathlib.Path) -> Image:
    """Read all modeled artifacts and the exact publication identity from disk.

    Args:
        year: Isolated real directory whose modeled files are being observed.

    Returns:
        The independently read state in stable file order.
    """
    entries = []
    for name in FILES:
        path = year / name
        try:
            content = path.read_bytes()
        except FileNotFoundError:
            entries.append(None)
        else:
            entries.append(
                Entry(
                    content=content,
                    modified_nanoseconds=path.stat().st_mtime_ns
                    if name == KMZ
                    else None,
                ),
            )
    return tuple(entries)


@dataclasses.dataclass(kw_only=True)
class Memory:
    """Isolate each branch's complete byte image and report its actual effects."""

    directory: pathlib.Path
    effects: Effects
    entries: list[Entry | None] = dataclasses.field(
        default_factory=lambda: [None] * len(FILES),
    )
    maps_present: bool = False
    trace: list[Event] | None = None
    observe: collections.abc.Callable[[], None] | None = None
    names: dict[pathlib.Path, str] = dataclasses.field(init=False)

    def __post_init__(self) -> None:
        """A path outside the modeled artifacts cannot resolve in this store."""
        self.names = {self.directory / name: name for name in FILES}

    def fork(self) -> Memory:
        """Continue from the complete byte image with private mutable storage.

        Returns:
            A child store retaining the current bytes and identity.
        """
        return Memory(
            directory=self.directory,
            effects=self.effects,
            entries=self.entries.copy(),
            maps_present=self.maps_present,
        )

    def at(self, path: pathlib.Path) -> File:
        """Bind one modeled artifact to the production raw file interface.

        Args:
            path: The canonical path requested by the coordinator.

        Returns:
            The file bound to this branch's byte image.
        """
        return File(memory=self, name=self.names[path])

    def mutate(
        self,
        operation: Operation,
        name: str,
        *,
        argument: bytes | bool | Entry,
        entry: Entry | None,
    ) -> None:
        """Capture exact input and result before reporting the durable boundary.

        Args:
            operation: The actual mutation performed by the file or fixture.
            name: Modeled path relative to the year directory.
            argument: Actual arguments received at the mutation boundary.
            entry: The resulting stored value, or absence after a removal.
        """
        effect = Effect(
            before=tuple(self.entries),
            maps_present=self.maps_present,
            operation=operation,
            name=name,
            argument=argument,
        )
        self.entries[FILE_INDEX[name]] = entry
        after = tuple(self.entries)
        previous = self.effects.setdefault(effect, after)
        assert previous == after
        if self.trace is not None:
            self.trace.append(Mutation(effect=effect, after=after))
        if self.observe is not None and name in MARKERS:
            self.observe()

    def write_generation(
        self,
        path: pathlib.Path,
        content: bytes,
        modified_nanoseconds: int | None,
    ) -> None:
        """Publish a generation fixture and assign an identity to the KMZ fixture.

        Args:
            path: The source or derived artifact being written.
            content: The encoded generation.
            modified_nanoseconds: The distinct KMZ stamp, if writing the KMZ.
        """
        name = self.names[path]
        assert name not in MARKERS, name
        entry = Entry(content=content, modified_nanoseconds=modified_nanoseconds)
        if modified_nanoseconds is None:
            self.mutate(Operation.WRITE, name, argument=content, entry=entry)
        else:
            assert name == KMZ
            self.maps_present = True
            self.mutate(Operation.PUBLISH, name, argument=entry, entry=entry)


@dataclasses.dataclass(frozen=True, kw_only=True)
class File:
    """Implement the raw file operations over one isolated byte image."""

    memory: Memory
    name: str

    def entry(self) -> Entry:
        """Read the current contents of the bound entry.

        Returns:
            The file's bytes and relevant identity.

        Raises:
            FileNotFoundError: If the file is absent.
        """
        entry = self.memory.entries[FILE_INDEX[self.name]]
        if entry is None:
            raise FileNotFoundError(
                errno.ENOENT,
                os.strerror(errno.ENOENT),
                str(self.memory.directory / self.name),
            )
        return entry

    def read_bytes(self) -> bytes:
        """Supply raw bytes to the shared production validators.

        Returns:
            The current file contents.
        """
        return self.entry().content

    def replace_text(self, text: str) -> None:
        """Publish the actual serialized document at the canonical destination.

        Args:
            text: The serialized state from the production writer.
        """
        assert self.name in {PENDING, CHECKPOINT}, self.name
        content = text.encode()
        self.memory.mutate(
            Operation.REPLACE,
            self.name,
            argument=content,
            entry=Entry(content=content),
        )

    def exists(self) -> bool:
        """Check this branch's current artifact presence.

        Returns:
            Whether the file exists in this branch.
        """
        return self.memory.entries[FILE_INDEX[self.name]] is not None

    def touch(self) -> None:
        """Create the deferred marker while preserving any existing bytes."""
        assert self.name == DEFERRED, self.name
        current = self.memory.entries[FILE_INDEX[self.name]]
        self.memory.mutate(
            Operation.TOUCH,
            self.name,
            argument=True,
            entry=current or Entry(content=b""),
        )

    def remove(self, *, missing_ok: bool) -> None:
        """Retire one marker with the actual missing-file policy.

        Args:
            missing_ok: Whether an absent marker permits the operation to complete.
        """
        assert self.name in MARKERS, self.name
        if not missing_ok:
            self.entry()
        self.memory.mutate(Operation.REMOVE, self.name, argument=missing_ok, entry=None)

    def identity(self) -> tuple[int, int]:
        """Read exact KMZ size and modification time for publication validation.

        Returns:
            The file size and the modification time in nanoseconds.
        """
        entry = self.entry()
        assert entry.modified_nanoseconds is not None, self.name
        return len(entry.content), entry.modified_nanoseconds


@dataclasses.dataclass(frozen=True, kw_only=True)
class Artifacts:
    """Read and publish the fixture artifacts on the selected replay backend."""

    directory: pathlib.Path
    memory: Memory | None
    trace: list[Event] | None

    def image(self) -> Image:
        """Read all modeled files independently of the expected state.

        Returns:
            An immutable copy of the current bytes and KMZ identity.
        """
        if self.memory is not None:
            return tuple(self.memory.entries)
        return read_image(self.directory)

    def read_bytes(self, path: pathlib.Path) -> bytes:
        """Read current bytes for the selected replay backend.

        Args:
            path: The observed artifact's canonical path.

        Returns:
            The bytes currently stored at that path.
        """
        if self.memory is not None:
            return self.memory.at(path).read_bytes()
        return path.read_bytes()

    def exists(self, path: pathlib.Path) -> bool:
        """Observe presence independently of pending work or matcher state.

        Args:
            path: The observed artifact's canonical path.

        Returns:
            Whether the current store contains the file.
        """
        if self.memory is not None:
            return self.memory.at(path).exists()
        return path.exists()

    def modified_nanoseconds(self, path: pathlib.Path) -> int:
        """Read the current KMZ identity even when its generation bytes match.

        Args:
            path: The KMZ artifact.

        Returns:
            The file's exact modification time in nanoseconds.
        """
        if self.memory is not None:
            return self.memory.at(path).identity()[1]
        return path.stat().st_mtime_ns

    def effect_input(self) -> tuple[Image, bool] | None:
        """Capture a physical before-image only for ordered trace comparisons.

        Returns:
            The complete modeled image and directory presence, when tracing.
        """
        if self.trace is None:
            return None
        return self.image(), (self.directory / "maps").exists()

    def record_effect(
        self,
        operation: Operation,
        path: pathlib.Path,
        *,
        argument: bytes | bool | Entry,
        before: tuple[Image, bool] | None,
    ) -> None:
        """Compare physical and memory mutations with the same trace representation.

        Args:
            operation: The completed physical mutation.
            path: Its canonical destination.
            argument: The bytes, identity, or absence policy passed to the operation.
            before: The independently read image before the operation, when tracing.
        """
        if before is None:
            return
        assert self.trace is not None
        image, maps_present = before
        effect = Effect(
            before=image,
            maps_present=maps_present,
            operation=operation,
            name=path.relative_to(self.directory).as_posix(),
            argument=argument,
        )
        self.trace.append(Mutation(effect=effect, after=self.image()))

    def write_generation(
        self,
        path: pathlib.Path,
        content: bytes,
        modified_nanoseconds: int | None = None,
    ) -> None:
        """Publish the fixture bytes and preserve the separate KMZ identity.

        Args:
            path: The independently durable generation file.
            content: The actual bytes produced by this fixture.
            modified_nanoseconds: The distinct KMZ modification time, when applicable.
        """
        if self.memory is not None:
            self.memory.write_generation(path, content, modified_nanoseconds)
            return
        if modified_nanoseconds is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
        before = self.effect_input()
        path.write_text(content.decode(), encoding="utf-8")
        if modified_nanoseconds is None:
            self.record_effect(Operation.WRITE, path, argument=content, before=before)
        else:
            os.utime(path, ns=(modified_nanoseconds, modified_nanoseconds))
            entry = Entry(
                content=content,
                modified_nanoseconds=modified_nanoseconds,
            )
            self.record_effect(Operation.PUBLISH, path, argument=entry, before=before)
