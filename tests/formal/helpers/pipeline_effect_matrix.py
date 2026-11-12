"""Check executed pipeline file commands against their independent physical effects.

Design notes:
[Pipeline composition](../tla/composition.md).
"""

from __future__ import annotations

import base64
import collections.abc
import dataclasses
import datetime
import enum
import functools
import hashlib
import json
import os
import pathlib
import stat
import sys

import pydantic
import pytest

import peri_scribe.durable_file
import peri_scribe.pipeline_state
import peri_scribe.publication
import tests.formal.helpers.corpus
import tests.formal.helpers.pipeline_file_footprint
import tests.formal.helpers.pipeline_replay_files
import tests.helpers.doubles.peri_scribe.pipeline_fetch_recovery


type Entry = tests.formal.helpers.pipeline_replay_files.Entry
type Image = tests.formal.helpers.pipeline_replay_files.Image
type Effect = tests.formal.helpers.pipeline_replay_files.Effect
type Effects = tests.formal.helpers.pipeline_replay_files.Effects
type EncodedEntry = tuple[str, int | None] | None
Operation = tests.formal.helpers.pipeline_replay_files.Operation
FILES = tests.formal.helpers.pipeline_replay_files.FILES
FILE_INDEX = tests.formal.helpers.pipeline_replay_files.FILE_INDEX
KMZ = tests.formal.helpers.pipeline_replay_files.KMZ
PENDING = "run_state.json"
CHECKPOINT = "publication_state.json"
DEFERRED = "deferred_inputs"
SIBLING = "other/files/sibling"
SENTINEL_STAMP = 1_662_345_678_123_456_789


class Primitive(enum.StrEnum):
    """Distinguish the ordered Path mutations below each file command."""

    WRITE_TEXT = "write_text"
    WRITE_BYTES = "write_bytes"
    REPLACE = "replace"
    TOUCH = "touch"
    UNLINK = "unlink"
    STAMP = "utime"


@dataclasses.dataclass(frozen=True, kw_only=True)
class PathCall:
    """Keep the actual physical target and arguments of an attempted primitive."""

    primitive: Primitive
    path: pathlib.Path
    arguments: tuple[object, ...] = ()
    options: tuple[tuple[str, object], ...] = ()


@dataclasses.dataclass(frozen=True, kw_only=True)
class Fault:
    """Interrupt at one physical boundary with the requested exception type."""

    error: type[BaseException]
    after: bool
    staging: bool = False


@dataclasses.dataclass(frozen=True, kw_only=True)
class PhysicalEntry:
    """An untouched sibling must retain its bytes, identity, mode, and timestamp."""

    mode: int
    inode: int
    modified_nanoseconds: int
    content: bytes | None


type Frame = dict[str, PhysicalEntry]
FRAME_TYPES = (Primitive, PathCall, Fault, PhysicalEntry)


def put(path: pathlib.Path, entry: Entry) -> None:
    """Restore fixture bytes and the stamp used by the actual publication validator."""
    path.write_bytes(entry.content)
    if (modified := entry.modified_nanoseconds) is not None:
        os.utime(path, ns=(modified, modified))


def restore(year: pathlib.Path, image: Image, *, maps_present: bool) -> None:
    """Create an isolated before-image with fixed independent frame witnesses."""
    year.mkdir(parents=True)
    if maps_present:
        (year / "maps").mkdir()
    for name, entry in zip(FILES, image, strict=True):
        if entry is not None:
            put(year / name, entry)
    siblings = ("unrelated", SIBLING)
    if maps_present:
        siblings += ("maps/unrelated.kmz",)
    for name in siblings:
        path = year / name
        path.parent.mkdir(parents=True, exist_ok=True)
        put(
            path,
            tests.formal.helpers.pipeline_replay_files.Entry(
                content=name.encode(),
                modified_nanoseconds=SENTINEL_STAMP,
            ),
        )
        path.chmod(0o640)


def capture(year: pathlib.Path) -> Frame:
    """Read the actual directory tree, including any surviving unmodeled mutation.

    Returns:
        Every observed regular file and directory with its relevant metadata.
    """
    entries = {}
    pending: list[tuple[str | pathlib.Path, str]] = [(year, "")]
    while pending:
        directory, prefix = pending.pop()
        with os.scandir(directory) as children:
            for child in children:
                status = child.stat(follow_symlinks=False)
                mode = status.st_mode
                name = prefix + child.name
                content = None
                if stat.S_ISREG(mode):
                    content = pathlib.Path(child.path).read_bytes()
                else:
                    assert stat.S_ISDIR(mode), child.path
                    pending.append((child.path, name + "/"))
                entries[name] = PhysicalEntry(
                    mode=mode,
                    inode=status.st_ino,
                    modified_nanoseconds=status.st_mtime_ns,
                    content=content,
                )
    return entries


def project(frame: Frame) -> Image:
    """Project the observed real tree to the exact modeled bytes and KMZ identity.

    Returns:
        The observed modeled artifacts in their canonical order.
    """
    values = []
    for name in FILES:
        if (entry := frame.get(name)) is None:
            values.append(None)
        else:
            assert entry.content is not None, name
            values.append(
                tests.formal.helpers.pipeline_replay_files.Entry(
                    content=entry.content,
                    modified_nanoseconds=entry.modified_nanoseconds
                    if name == KMZ
                    else None,
                ),
            )
    return tuple(values)


def assert_frame(before: Frame, after: Frame, name: str) -> None:
    """A file command may change its target and its parent's directory timestamp."""
    siblings = before.keys() - {name}
    assert siblings == after.keys() - {name}, "physical frame membership"
    parent = pathlib.PurePosixPath(name).parent.as_posix()
    for sibling in siblings:
        expected = before[sibling]
        actual = after[sibling]
        if sibling == parent:
            expected = dataclasses.replace(
                expected,
                modified_nanoseconds=actual.modified_nanoseconds,
            )
        assert actual == expected, ("physical frame changed", sibling)


def execute(path: pathlib.Path, effect: Effect) -> None:
    """Issue the actual default adapter command or the real generation fixture write."""
    file = peri_scribe.durable_file.at(path)
    argument = effect.argument
    match effect.operation:
        case Operation.REPLACE:
            assert isinstance(argument, bytes)
            file.replace_text(argument.decode())
        case Operation.TOUCH:
            assert argument is True
            file.touch()
        case Operation.REMOVE:
            assert isinstance(argument, bool)
            file.remove(missing_ok=argument)
        case Operation.WRITE:
            assert isinstance(argument, bytes)
            path.write_text(argument.decode(), encoding="utf-8")
        case Operation.PUBLISH:
            assert isinstance(
                argument,
                tests.formal.helpers.pipeline_replay_files.Entry,
            )
            assert argument.modified_nanoseconds is not None
            path.write_text(argument.content.decode(), encoding="utf-8")
            modified = argument.modified_nanoseconds
            os.utime(path, ns=(modified, modified))


def fault_primitive(operation: Operation, fault: Fault) -> Primitive:
    """An interrupted fixture publication has a separate timestamp boundary.

    Returns:
        The physical operation where the selected interruption lands.
    """
    if fault.staging:
        assert operation is Operation.REPLACE
        return Primitive.WRITE_TEXT
    return {
        Operation.REPLACE: Primitive.REPLACE,
        Operation.TOUCH: Primitive.TOUCH,
        Operation.REMOVE: Primitive.UNLINK,
        Operation.WRITE: Primitive.WRITE_TEXT,
        Operation.PUBLISH: Primitive.STAMP if fault.after else Primitive.WRITE_TEXT,
    }[operation]


def path_observer[Result](
    method: collections.abc.Callable[..., Result],
    primitive: Primitive,
    destination: pathlib.Path,
    calls: list[PathCall],
    *,
    interruption: Primitive | None,
    fault: Fault | None,
) -> collections.abc.Callable[..., Result]:
    """Record real attempts and inject only at the selected canonical boundary.

    Returns:
        A pass-through observer around the actual operation.
    """

    def observed(path: pathlib.Path, *args: object, **kwargs: object) -> Result:
        """Pass through each real mutation until the selected interruption.

        Returns:
            The physical operation's result on success.
        """
        if primitive is Primitive.STAMP and "ns" not in kwargs:
            # Path.touch already records its timestamp update as one Path operation.
            return method(path, *args, **kwargs)
        calls.append(
            PathCall(
                primitive=primitive,
                path=pathlib.Path(path),
                arguments=args,
                options=tuple(kwargs.items()),
            ),
        )
        target = args[0] if primitive is Primitive.REPLACE else path
        if (
            fault is not None
            and primitive is interruption
            and (target == destination or fault.staging)
        ):
            if fault.after:
                method(path, *args, **kwargs)
            message = "injected physical interruption"
            raise fault.error(message)
        return method(path, *args, **kwargs)

    return observed


def observe_calls(
    patch: pytest.MonkeyPatch,
    destination: pathlib.Path,
    operation: Operation,
    fault: Fault | None,
) -> list[PathCall]:
    """Observe wrong-path attempts even if their effects are later reversed.

    Returns:
        The ordered list populated by the installed observers.
    """
    calls: list[PathCall] = []
    interruption = fault_primitive(operation, fault) if fault is not None else None
    for primitive in Primitive:
        owner = os if primitive is Primitive.STAMP else pathlib.Path
        patch.setattr(
            owner,
            primitive.value,
            path_observer(
                getattr(owner, primitive.value),
                primitive,
                destination,
                calls,
                interruption=interruption,
                fault=fault,
            ),
        )
    return calls


def expected_calls(
    destination: pathlib.Path,
    effect: Effect,
    calls: list[PathCall],
    fault: Fault | None,
) -> list[PathCall]:
    """Keep the staging write and canonical commit distinct in the physical trace.

    Returns:
        The exact allowed physical operations and their arguments.
    """
    argument = effect.argument
    match effect.operation:
        case Operation.REPLACE:
            assert isinstance(argument, bytes)
            assert calls, "missing staging write"
            staged = calls[0].path
            assert staged.name == destination.name
            assert staged.parent != destination.parent
            assert staged.parent.parent == destination.parent
            write = PathCall(
                primitive=Primitive.WRITE_TEXT,
                path=staged,
                arguments=(argument.decode(),),
            )
            if fault is not None and fault.staging:
                return [write]
            return [
                write,
                PathCall(
                    primitive=Primitive.REPLACE,
                    path=staged,
                    arguments=(destination,),
                ),
            ]
        case Operation.TOUCH:
            return [PathCall(primitive=Primitive.TOUCH, path=destination)]
        case Operation.REMOVE:
            return [
                PathCall(
                    primitive=Primitive.UNLINK,
                    path=destination,
                    options=(("missing_ok", argument),),
                ),
            ]
        case Operation.WRITE:
            assert isinstance(argument, bytes)
            return [
                PathCall(
                    primitive=Primitive.WRITE_TEXT,
                    path=destination,
                    arguments=(argument.decode(),),
                    options=(("encoding", "utf-8"),),
                ),
            ]
        case Operation.PUBLISH:
            assert isinstance(
                argument,
                tests.formal.helpers.pipeline_replay_files.Entry,
            )
            calls_expected = [
                PathCall(
                    primitive=Primitive.WRITE_TEXT,
                    path=destination,
                    arguments=(argument.content.decode(),),
                    options=(("encoding", "utf-8"),),
                ),
            ]
            if fault is None or fault.after:
                modified = argument.modified_nanoseconds
                calls_expected.append(
                    PathCall(
                        primitive=Primitive.STAMP,
                        path=destination,
                        options=(("ns", (modified, modified)),),
                    ),
                )
            return calls_expected


def assert_read[Result](
    operation: collections.abc.Callable[[], Result],
    expected: Result | None,
    name: str,
) -> None:
    """Require the raw reply or the absence error used by production readers.

    Args:
        operation: The bound local file read.
        expected: Its exact reply, or None for an absent file.
        name: The canonical path relative to the year directory.
    """
    if expected is None:
        with pytest.raises(FileNotFoundError):
            operation()
    else:
        assert operation() == expected, ("physical file read disagrees", name)


def assert_readers(year: pathlib.Path, image: Image) -> None:
    """Read each canonical artifact with the surrounding files still present.

    Args:
        year: The actual file tree for this image.
        image: The exact bytes and identity expected in that tree.
    """
    for name in (PENDING, CHECKPOINT):
        entry = image[FILE_INDEX[name]]
        file = peri_scribe.durable_file.at(year / name)
        assert_read(file.read_bytes, None if entry is None else entry.content, name)
    deferred = image[FILE_INDEX[DEFERRED]] is not None
    assert peri_scribe.durable_file.at(year / DEFERRED).exists() is deferred
    artifact = image[FILE_INDEX[KMZ]]
    identity = None
    if artifact is not None:
        assert artifact.modified_nanoseconds is not None
        identity = (len(artifact.content), artifact.modified_nanoseconds)
    assert_read(peri_scribe.durable_file.at(year / KMZ).identity, identity, KMZ)


def verify_effect(
    year: pathlib.Path,
    effect: Effect,
    after: Image,
    *,
    fault: Fault | None = None,
) -> None:
    """Check full bytes, raw replies, the untouched frame, and mutation order."""
    restore(year, effect.before, maps_present=effect.maps_present)
    destination = year / effect.name
    before = capture(year)
    assert project(before) == effect.before
    assert ("maps" in before) == effect.maps_present
    if fault is None:
        assert_readers(year, effect.before)
    with pytest.MonkeyPatch.context() as patch:
        calls = observe_calls(patch, destination, effect.operation, fault)
        if fault is None:
            execute(destination, effect)
        else:
            with pytest.raises(fault.error, match="injected physical interruption"):
                execute(destination, effect)
    if fault is None:
        assert_readers(year, after)
    observed = capture(year)
    assert_frame(before, observed, effect.name)
    assert ("maps" in observed) == effect.maps_present
    committed = fault is None or (fault.after and not fault.staging)
    assert project(observed) == (after if committed else effect.before), effect
    if not committed:
        assert observed.get(effect.name) == before.get(effect.name)
    elif effect.operation is Operation.REPLACE and effect.name in before:
        assert observed[effect.name].inode != before[effect.name].inode
    assert calls == expected_calls(destination, effect, calls, fault), (
        "unexpected durable mutations",
        calls,
    )
    if effect.operation is Operation.REPLACE:
        staging = calls[0].path.parent.relative_to(year).as_posix()
        assert staging not in before, "replacement reused an existing staging directory"


def encode_entry(entry: Entry | None) -> EncodedEntry:
    """Keep arbitrary raw bytes and exact nanoseconds in the shared receipt key.

    Returns:
        An exact JSON-ready entry or an explicit absence.
    """
    if entry is None:
        return None
    return base64.b64encode(entry.content).decode("ascii"), entry.modified_nanoseconds


def encode_image(image: Image) -> tuple[EncodedEntry, ...]:
    """Serialize each artifact with explicit absence.

    Returns:
        The encoded complete image in file order.
    """
    return tuple(map(encode_entry, image))


@dataclasses.dataclass(frozen=True, kw_only=True)
class Receipt:
    """Only a completed physical check can authorize skipping an exact repeat."""

    key: str
    after: str


RECEIPT = pydantic.TypeAdapter(Receipt)


def checked_receipt(
    directory: pathlib.Path,
    kind: str,
    key: object,
    after: object,
    verify: collections.abc.Callable[[pathlib.Path], None],
) -> None:
    """Share exact outcomes within one invocation using the corpus lock and commit."""
    encoded = json.dumps(key)
    expected = Receipt(key=encoded, after=json.dumps(after))
    digest = hashlib.sha256(encoded.encode()).hexdigest()

    def build(work: pathlib.Path) -> Receipt:
        """Publish a receipt only after the real check passes.

        Returns:
            The completed result for the exact verification input.
        """
        verify(work)
        return expected

    assert (
        tests.formal.helpers.corpus.load(
            directory,
            f"{kind}-{digest}",
            RECEIPT,
            build,
        )
        == expected
    )


def verify_full(work: pathlib.Path, effect: Effect, after: Image) -> None:
    """Use the receipt staging directory for one fresh physical image."""
    verify_effect(work / "2026", effect, after)


def verify_faults(work: pathlib.Path, effect: Effect, after: Image) -> None:
    """Exercise both exception types before and after the real canonical operation."""
    for error in (
        OSError,
        tests.helpers.doubles.peri_scribe.pipeline_fetch_recovery.ProcessLoss,
    ):
        for committed in (False, True):
            verify_effect(
                work / f"{error.__name__}-{committed}" / "2026",
                effect,
                after,
                fault=Fault(error=error, after=committed),
            )


def verify_footprint(work: pathlib.Path, effect: Effect, after: Image) -> None:
    """Keep the real success and four independent faults under one receipt."""
    verify_full(work, effect, after)
    verify_faults(work, effect, after)


FOOTPRINT_TARGETS = {
    Operation.REPLACE: frozenset((PENDING, CHECKPOINT)),
    Operation.TOUCH: frozenset((DEFERRED,)),
    Operation.REMOVE: frozenset((DEFERRED, CHECKPOINT)),
    Operation.WRITE: frozenset((
        "source-generation",
        "output-1",
        "output-2",
        "output-4",
    )),
    Operation.PUBLISH: frozenset((KMZ,)),
}


def footprint_input(effect: Effect) -> bool:
    """Require the regular-file topology and argument types admitted by the proof.

    Returns:
        Whether this effect can use a shared physical witness.
    """
    entry_type = tests.formal.helpers.pipeline_replay_files.Entry
    if (
        type(effect.operation) is not Operation
        or effect.name not in FOOTPRINT_TARGETS.get(effect.operation, ())
        or type(effect.maps_present) is not bool
        or len(effect.before) != len(FILES)
    ):
        return False
    if not effect.maps_present and effect.before[FILE_INDEX[KMZ]] is not None:
        return False
    for name, entry in zip(FILES, effect.before, strict=True):
        if entry is not None and (
            type(entry) is not entry_type
            or type(entry.content) is not bytes
            or (
                type(entry.modified_nanoseconds) is not int
                or entry.modified_nanoseconds < 0
                if name == KMZ
                else entry.modified_nanoseconds is not None
            )
        ):
            return False
    argument = effect.argument
    match effect.operation:
        case Operation.REPLACE | Operation.WRITE:
            argument_supported = type(argument) is bytes
        case Operation.TOUCH:
            argument_supported = argument is True
        case Operation.REMOVE:
            argument_supported = type(argument) is bool and (
                argument or effect.before[FILE_INDEX[effect.name]] is not None
            )
        case Operation.PUBLISH:
            argument_supported = (
                effect.maps_present
                and type(argument) is entry_type
                and type(argument.content) is bytes
                and type(argument.modified_nanoseconds) is int
                and argument.modified_nanoseconds >= 0
            )
    return argument_supported


def lift_footprint(
    effect: Effect,
    after: Image,
    transfer: tests.formal.helpers.pipeline_file_footprint.Transfer,
) -> None:
    """Check the proved transfer against every original complete after-image."""
    index = FILE_INDEX[effect.name]
    argument = effect.argument
    entry_type = tests.formal.helpers.pipeline_replay_files.Entry
    match transfer:
        case tests.formal.helpers.pipeline_file_footprint.Transfer.RETAIN:
            target = effect.before[index]
        case tests.formal.helpers.pipeline_file_footprint.Transfer.CREATE_EMPTY:
            target = entry_type(content=b"")
        case tests.formal.helpers.pipeline_file_footprint.Transfer.INSTALL_ARGUMENT:
            assert isinstance(argument, (bytes, entry_type))
            target = (
                entry_type(content=argument)
                if isinstance(argument, bytes)
                else argument
            )
        case tests.formal.helpers.pipeline_file_footprint.Transfer.REMOVE:
            target = None
    assert len(after) == len(effect.before), effect
    assert all(
        observed == (target if position == index else original)
        for position, (observed, original) in enumerate(
            zip(after, effect.before, strict=True),
        )
    ), effect


def check_effects(effects: Effects, formal_corpus_directory: pathlib.Path) -> None:
    """Check every full image and share witnesses within a proved footprint."""
    assert effects
    receipts = formal_corpus_directory / "pipeline-effect-checks"
    footprint = tests.formal.helpers.pipeline_file_footprint.resolve(
        sys.modules[__name__],
        FRAME_TYPES,
    )
    if footprint is not None and not all(map(footprint_input, effects)):
        footprint = None
    witnessed = set()
    targets: dict[tuple[object, ...], EncodedEntry] = {}
    readers = set()
    pairs = set()
    for effect, after in effects.items():
        argument = effect.argument
        if isinstance(argument, tests.formal.helpers.pipeline_replay_files.Entry):
            encoded_argument = encode_entry(argument)
        elif isinstance(argument, bytes):
            encoded_argument = base64.b64encode(argument).decode("ascii")
        else:
            encoded_argument = argument
        command = (effect.operation, effect.name, encoded_argument)
        index = FILE_INDEX[effect.name]
        if footprint is not None:
            present = effect.before[index] is not None
            transfer = footprint.transfer(effect.operation, present=present)
            lift_footprint(effect, after, transfer)
            witness = (*command, effect.maps_present, present)
            if witness not in witnessed:
                checked_receipt(
                    receipts,
                    "footprint",
                    witness,
                    transfer,
                    functools.partial(verify_footprint, effect=effect, after=after),
                )
                witnessed.add(witness)
        else:
            checked_receipt(
                receipts,
                "full",
                (*command, effect.maps_present, encode_image(effect.before)),
                encode_image(after),
                functools.partial(verify_full, effect=effect, after=after),
            )
            target = (*command, encode_entry(effect.before[index]))
            value = encode_entry(after[index])
            if target not in targets:
                checked_receipt(
                    receipts,
                    "fault",
                    target,
                    value,
                    functools.partial(verify_faults, effect=effect, after=after),
                )
            assert targets.setdefault(target, value) == value
        readers.update(
            (name, image[FILE_INDEX[name]])
            for image in (effect.before, after)
            for name in (PENDING, CHECKPOINT, DEFERRED, KMZ)
        )
        pairs.update(
            (image[FILE_INDEX[CHECKPOINT]], image[FILE_INDEX[KMZ]])
            for image in (effect.before, after)
        )
    for name, entry in readers:
        checked_receipt(
            receipts,
            "reader",
            (name, encode_entry(entry)),
            None,
            functools.partial(verify_witnessed_reader, name=name, entry=entry),
        )
    for checkpoint, artifact in pairs:
        checked_receipt(
            receipts,
            "publication-pair",
            (encode_entry(checkpoint), encode_entry(artifact)),
            None,
            functools.partial(
                verify_witnessed_publication,
                checkpoint=checkpoint,
                artifact=artifact,
            ),
        )


def reader_memory(
    year: pathlib.Path,
    entries: dict[str, Entry | None],
    *,
    output: pathlib.Path | None = None,
) -> tests.formal.helpers.pipeline_replay_files.Memory:
    """Give physical and map readers the same independently supplied raw inputs.

    Returns:
        The map counterpart of the materialized real year and optional KMZ path.
    """
    year.mkdir(parents=True)
    memory = tests.formal.helpers.pipeline_replay_files.Memory(
        directory=year,
        effects={},
    )
    for name, entry in entries.items():
        path = output if name == KMZ and output is not None else year / name
        memory.names[path] = name
        memory.entries[FILE_INDEX[name]] = entry
        if entry is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            put(path, entry)
    return memory


def compare_pending(
    year: pathlib.Path,
    entry: Entry | None,
) -> peri_scribe.pipeline_state.PendingRun:
    """Read the same stored pending bytes with the real and map adapters.

    Returns:
        The independently parsed result on which both paths agree.
    """
    memory = reader_memory(year, {PENDING: entry})
    physical = peri_scribe.pipeline_state.read_state(year)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(peri_scribe.durable_file, "at", memory.at)
        assert peri_scribe.pipeline_state.read_state(year) == physical
    return physical


def compare_stamp(year: pathlib.Path, entry: Entry | None) -> None:
    """An explicit output path must report its own exact size and nanoseconds."""
    output = year / "explicit-output.kmz"
    memory = reader_memory(year, {KMZ: entry}, output=output)
    if entry is None:
        with pytest.raises(FileNotFoundError):
            peri_scribe.publication.file_stamp(output)
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(peri_scribe.durable_file, "at", memory.at)
            with pytest.raises(FileNotFoundError):
                peri_scribe.publication.file_stamp(output)
    else:
        assert entry.modified_nanoseconds is not None
        stamp = peri_scribe.publication.FileStamp(
            size=len(entry.content),
            modified_nanoseconds=entry.modified_nanoseconds,
        )
        assert peri_scribe.publication.file_stamp(output) == stamp
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(peri_scribe.durable_file, "at", memory.at)
            assert peri_scribe.publication.file_stamp(output) == stamp


def compare_publication_pair(
    year: pathlib.Path,
    checkpoint: Entry | None,
    artifact: Entry | None,
    expected: peri_scribe.publication.Publication | None,
) -> None:
    """Both transports must validate the supplied artifact at its explicit path."""
    output = year / "explicit-output.kmz"
    memory = reader_memory(year, {CHECKPOINT: checkpoint, KMZ: artifact}, output=output)
    assert peri_scribe.publication.read_publication(year, output) == expected
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(peri_scribe.durable_file, "at", memory.at)
        assert peri_scribe.publication.read_publication(year, output) == expected


def verify_witnessed_publication(
    work: pathlib.Path,
    checkpoint: Entry | None,
    artifact: Entry | None,
) -> None:
    """Retain every actual pair of checkpoint bytes and output bytes and timestamp."""
    expected = None
    if checkpoint is not None and artifact is not None:
        candidate = peri_scribe.publication.Publication.model_validate_json(
            checkpoint.content,
        )
        assert artifact.modified_nanoseconds is not None
        if (
            candidate.output.size == len(artifact.content)
            and candidate.output.modified_nanoseconds == artifact.modified_nanoseconds
        ):
            expected = candidate
    compare_publication_pair(work / "2026", checkpoint, artifact, expected)


def compare_publication(
    directory: pathlib.Path,
    entry: Entry | None,
    expected: peri_scribe.publication.Publication | None,
) -> None:
    """A checkpoint authorizes a skip only for the exact supplied output identity."""
    stamp = (
        expected.output
        if expected is not None
        else peri_scribe.publication.FileStamp(
            size=1,
            modified_nanoseconds=SENTINEL_STAMP,
        )
    )
    assert stamp.size > 0
    for label, size, modified in (
        ("missing", 0, None),
        ("matches", stamp.size, stamp.modified_nanoseconds),
        ("size", stamp.size + 1, stamp.modified_nanoseconds),
        ("nanosecond", stamp.size, stamp.modified_nanoseconds + 1),
    ):
        year = directory / label / "2026"
        artifact = (
            None
            if modified is None
            else tests.formal.helpers.pipeline_replay_files.Entry(
                content=b"x" * size,
                modified_nanoseconds=modified,
            )
        )
        compare_publication_pair(
            year,
            entry,
            artifact,
            expected if label == "matches" else None,
        )


def verify_witnessed_reader(work: pathlib.Path, name: str, entry: Entry | None) -> None:
    """Exercise each raw marker or identity witnessed during exhaustive execution."""
    if name == PENDING:
        expected = (
            peri_scribe.pipeline_state.PendingRun()
            if entry is None
            else peri_scribe.pipeline_state.PendingRun.model_validate_json(
                entry.content,
            )
        )
        assert compare_pending(work / "2026", entry) == expected
    elif name == CHECKPOINT:
        published = (
            None
            if entry is None
            else peri_scribe.publication.Publication.model_validate_json(entry.content)
        )
        compare_publication(work, entry, published)
    elif name == DEFERRED:
        year = work / "2026"
        memory = reader_memory(year, {DEFERRED: entry})
        present = entry is not None
        assert peri_scribe.pipeline_state.has_deferred_inputs(year) is present
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(peri_scribe.durable_file, "at", memory.at)
            assert peri_scribe.pipeline_state.has_deferred_inputs(year) is present
    else:
        assert name == KMZ
        compare_stamp(work / "2026", entry)


def invalid_publications() -> tuple[bytes, ...]:
    """Vary parsing and compatibility independently of the matching file stamp.

    Returns:
        Raw corrupt, legacy, and unknown-field documents that cannot authorize a skip.
    """
    valid = peri_scribe.publication.Publication(
        created_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
        output=peri_scribe.publication.FileStamp(
            size=1,
            modified_nanoseconds=SENTINEL_STAMP,
        ),
        files={},
        fires={},
    ).model_dump(mode="json")
    return (
        b"",
        b"{",
        b"[]",
        b"\xff",
        json.dumps(valid | {"version": 3}).encode(),
        json.dumps(valid | {"unknown": True}).encode(),
    )
