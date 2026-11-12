"""Bind proved file effect sharing to the current local adapter and fixture.

See [Verification tooling](../../../docs/algorithms/verification-tooling.md).
"""

import ast
import builtins
import dataclasses
import enum
import functools
import hashlib
import os
import pathlib
import stat
import tempfile
import types

import pytest

import peri_scribe.durable_file
import tests.formal.helpers.oracle
import tests.formal.helpers.pipeline_replay_files
import tests.helpers.doubles.peri_scribe.pipeline_fetch_recovery


ADAPTER = """
from __future__ import annotations
import dataclasses
import pathlib
import tempfile
import typing

class File(typing.Protocol):
    def read_bytes(self) -> bytes: ...
    def replace_text(self, text: str) -> None: ...
    def exists(self) -> bool: ...
    def touch(self) -> None: ...
    def remove(self, *, missing_ok: bool) -> None: ...
    def identity(self) -> tuple[int, int]: ...

@dataclasses.dataclass(frozen=True, kw_only=True)
class LocalFile(File):
    path: pathlib.Path

    @typing.override
    def read_bytes(self) -> bytes:
        return self.path.read_bytes()

    @typing.override
    def replace_text(self, text: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=self.path.parent) as directory:
            temporary = pathlib.Path(directory) / self.path.name
            temporary.write_text(text)
            temporary.replace(self.path)

    @typing.override
    def exists(self) -> bool:
        return self.path.exists()

    @typing.override
    def touch(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch()

    @typing.override
    def remove(self, *, missing_ok: bool) -> None:
        self.path.unlink(missing_ok=missing_ok)

    @typing.override
    def identity(self) -> tuple[int, int]:
        status = self.path.stat()
        return status.st_size, status.st_mtime_ns

def at(path: pathlib.Path) -> File:
    return LocalFile(path=path)
"""

DISPATCH = """
def execute(path: pathlib.Path, effect: Effect) -> None:
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
"""

# The physical assertion and frame definitions qualify the proof's fixture domain.
FRAME_DEFINITIONS = frozenset({
    "Primitive",
    "PathCall",
    "Fault",
    "PhysicalEntry",
    "put",
    "restore",
    "capture",
    "project",
    "assert_frame",
    "path_observer",
    "observe_calls",
    "expected_calls",
    "assert_read",
    "assert_readers",
    "verify_effect",
    "verify_full",
    "verify_faults",
    "verify_footprint",
})
FRAME_FINGERPRINT = "6250d93251900d657c74ce01fec0ba32afb0a53a94d377ef5fe65ed8b3af63aa"
COMMAND_FINGERPRINT = "3b5fc051011ac02f4913a88aec40a31a02831aeceaebb0bf9b6a760ab921f389"
SIBLING_STAMP = 1_662_345_678_123_456_789
FRAME_FILES = (
    "source-generation",
    "output-1",
    "output-2",
    "output-4",
    "maps/PeriScribe Fires 2026.kmz",
    "run_state.json",
    "deferred_inputs",
    "publication_state.json",
)


class Step(enum.IntEnum):
    """Distinguish the six native capabilities in the checked schedule."""

    WRITE_STAGE = 1
    REPLACE_TARGET = 2
    WRITE_TARGET = 3
    STAMP_TARGET = 4
    TOUCH_TARGET = 5
    UNLINK_TARGET = 6


class Transfer(enum.IntEnum):
    """Keep the proved change symbolic until it reaches its own before-image."""

    RETAIN = 0
    CREATE_EMPTY = 1
    INSTALL_ARGUMENT = 2
    REMOVE = 3


CALLS = {
    "temporary.write_text": Step.WRITE_STAGE,
    "temporary.replace": Step.REPLACE_TARGET,
    "path.write_text": Step.WRITE_TARGET,
    "os.utime": Step.STAMP_TARGET,
    "self.path.touch": Step.TOUCH_TARGET,
    "self.path.unlink": Step.UNLINK_TARGET,
}
FAULT_STEPS = {
    "REPLACE": (Step.REPLACE_TARGET,),
    "WRITE_TEXT": (Step.WRITE_STAGE, Step.WRITE_TARGET),
    "STAMP": (Step.STAMP_TARGET,),
    "TOUCH": (Step.TOUCH_TARGET,),
    "UNLINK": (Step.UNLINK_TARGET,),
}
OPERATIONS = ("REPLACE", "TOUCH", "REMOVE", "WRITE", "PUBLISH")
COMMAND_MODULE = tests.formal.helpers.pipeline_replay_files
COMMAND_TYPES = (COMMAND_MODULE.Operation, COMMAND_MODULE.Effect, COMMAND_MODULE.Entry)
PROCESS_LOSS = tests.helpers.doubles.peri_scribe.pipeline_fetch_recovery.ProcessLoss

# Runtime overrides must go through unrestricted physical verification.
NATIVE_IDENTITIES = tuple(
    (owner, name, getattr(owner, name))
    for owner, names in (
        (pathlib, ("Path",)),
        (
            pathlib.Path,
            (
                "mkdir",
                "open",
                "read_bytes",
                "write_text",
                "replace",
                "unlink",
                "touch",
                "exists",
                "stat",
                "with_name",
                "parent",
                "name",
                "__truediv__",
            ),
        ),
        (
            os,
            (
                "mkdir",
                "open",
                "read",
                "write",
                "replace",
                "unlink",
                "utime",
                "stat",
                "lstat",
                "rmdir",
                "scandir",
            ),
        ),
        (tempfile, ("TemporaryDirectory", "mkdtemp")),
        (builtins, ("isinstance", "bytes", "bool")),
    )
    for name in names
)


@dataclasses.dataclass(frozen=True, kw_only=True)
class Initializer:
    """Provide the standard frozen, keyword-only constructor for the same field."""

    path: pathlib.Path


@dataclasses.dataclass(frozen=True, kw_only=True)
class Source:
    """Keep the extracted program and the exact executable bindings it describes."""

    shape: tuple[int, ...]
    adapter: tuple[tuple[str, tuple[object, ...]], ...]
    fixture: tuple[tuple[str, tuple[object, ...]], ...]


@dataclasses.dataclass(frozen=True, kw_only=True)
class Footprint:
    """Use only symbolic transfers returned by the checked Lean definitions."""

    transfers: tuple[Transfer, ...]

    def transfer(
        self,
        operation: tests.formal.helpers.pipeline_replay_files.Operation,
        *,
        present: bool,
    ) -> Transfer:
        """Look up the checked transfer for this command and target presence.

        Returns:
            The change to lift into the exact incoming image.
        """
        return self.transfers[2 * OPERATIONS.index(operation.name) + present]


def normalize(node: ast.AST) -> str:
    """Compare executable structure while allowing descriptive strings to change.

    Returns:
        The normalized syntax tree with source locations omitted.
    """
    for scope in ast.walk(node):
        if (
            isinstance(scope, (ast.Module, ast.ClassDef, ast.FunctionDef))
            and ast.get_docstring(scope) is not None
        ):
            del scope.body[0]
    return ast.dump(node, include_attributes=False)


def trace(
    statements: list[ast.stmt],
    methods: dict[str, list[ast.stmt]],
) -> list[Step]:
    """Read the ordered native effects from the already recognized syntax.

    Returns:
        Each native primitive observed by the physical tests.
    """
    calls = []
    for statement in statements:
        if isinstance(statement, ast.With):
            calls.extend(trace(statement.body, methods))
        if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call):
            name = ast.unparse(statement.value.func)
            if name.startswith("file."):
                calls.extend(trace(methods[name.removeprefix("file.")], methods))
            elif name in CALLS:
                calls.append(CALLS[name])
    return calls


def position(steps: list[Step], selector: ast.expr) -> int:
    """Encode the selected fault position, using one-based indices.

    Returns:
        The unique attempted primitive named by the real fault selector.
    """
    assert isinstance(selector, ast.Attribute)
    matches = FAULT_STEPS[selector.attr]
    return next(index for index, step in enumerate(steps, 1) if step in matches)


def program_shape(
    methods: dict[str, list[ast.stmt]],
    execute: ast.FunctionDef,
    fault: ast.FunctionDef,
) -> tuple[int, ...]:
    """Export the real primitive sequence and fault positions to Lean.

    Returns:
        A length-delimited record for each operation in declaration order.
    """
    dispatch = execute.body[-1]
    staging = fault.body[0]
    select = fault.body[-1]
    assert isinstance(dispatch, ast.Match)
    assert isinstance(staging, ast.If)
    assert isinstance(select, ast.Return)
    assert isinstance(select.value, ast.Subscript)
    assert isinstance(select.value.value, ast.Dict)
    selectors = {
        key.attr: value
        for key, value in zip(
            select.value.value.keys,
            select.value.value.values,
            strict=True,
        )
        if isinstance(key, ast.Attribute)
    }
    stage_selector = staging.body[-1]
    assert isinstance(stage_selector, ast.Return)
    assert stage_selector.value is not None
    records = []
    for branch in dispatch.cases:
        assert isinstance(branch.pattern, ast.MatchValue)
        assert isinstance(branch.pattern.value, ast.Attribute)
        operation = branch.pattern.value.attr
        steps = trace(branch.body, methods)
        selector = selectors[operation]
        if isinstance(selector, ast.IfExp):
            before = position(steps, selector.orelse)
            after = position(steps, selector.body)
        else:
            before = after = position(steps, selector)
        stage = position(steps, stage_selector.value) if operation == "REPLACE" else 0
        records.extend((len(steps), *map(int, steps), before, after, stage, stage))
    return tuple(records)


def signature(code: types.CodeType) -> tuple[object, ...]:
    """Qualify the recognized source against the code that will actually execute.

    Returns:
        Executable fields, including any nested functions and constants.
    """
    constants = tuple(
        signature(value) if isinstance(value, types.CodeType) else value
        for value in code.co_consts
    )
    return (
        code.co_code,
        code.co_names,
        code.co_varnames,
        code.co_freevars,
        code.co_cellvars,
        code.co_flags,
        code.co_argcount,
        code.co_kwonlyargcount,
        code.co_posonlyargcount,
        code.co_exceptiontable,
        constants,
    )


def function_codes(code: types.CodeType) -> dict[str, tuple[object, ...]]:
    """Find definitions under the module and its type parameter scopes.

    Returns:
        Compiled executable signatures keyed by definition name.
    """
    signatures = {}
    for value in code.co_consts:
        if isinstance(value, types.CodeType):
            if value.co_name.startswith("<generic parameters of "):
                signatures.update(function_codes(value))
            else:
                signatures[value.co_name] = signature(value)
    return signatures


@functools.lru_cache(maxsize=4)
def recognize(
    adapter_text: str,
    fixture_text: str,
    commands_text: str,
) -> Source | None:
    """Admit only the complete reviewed adapter and observed fixture shape.

    Returns:
        Current proof inputs, or absence when full physical checks are required.
    """
    try:
        adapter = ast.parse(adapter_text)
        fixture = ast.parse(fixture_text)
        commands = ast.parse(commands_text)
    except SyntaxError:
        return None
    if normalize(adapter) != normalize(ast.parse(ADAPTER)):
        return None
    command_types = [
        normalize(node)
        for node in commands.body
        if isinstance(node, ast.ClassDef)
        and node.name in {"Entry", "Effect", "Operation"}
    ]
    if (
        hashlib.sha256("\n".join(command_types).encode()).hexdigest()
        != COMMAND_FINGERPRINT
    ):
        return None
    local_file = next(
        node
        for node in adapter.body
        if isinstance(node, ast.ClassDef) and node.name == "LocalFile"
    )
    definitions = {
        node.name: node for node in fixture.body if isinstance(node, ast.FunctionDef)
    }
    dispatch = ast.parse(DISPATCH).body
    if any(
        isinstance(expected, ast.FunctionDef)
        and (
            expected.name not in definitions
            or normalize(definitions[expected.name]) != normalize(expected)
        )
        for expected in dispatch
    ):
        return None
    frame = [
        normalize(node)
        for node in fixture.body
        if isinstance(node, (ast.FunctionDef, ast.ClassDef))
        and node.name in FRAME_DEFINITIONS
    ]
    if hashlib.sha256("\n".join(frame).encode()).hexdigest() != FRAME_FINGERPRINT:
        return None
    methods = {
        node.name: node.body
        for node in local_file.body
        if isinstance(node, ast.FunctionDef)
    }
    adapter_code = compile(adapter_text, "adapter", "exec", dont_inherit=True)
    fixture_code = compile(fixture_text, "fixture", "exec", dont_inherit=True)
    local_code = next(
        value
        for value in adapter_code.co_consts
        if isinstance(value, types.CodeType) and value.co_name == "LocalFile"
    )
    fixture_functions = function_codes(fixture_code)
    adapter_functions = function_codes(local_code)
    return Source(
        shape=program_shape(
            methods,
            definitions["execute"],
            definitions["fault_primitive"],
        ),
        adapter=(
            ("at", function_codes(adapter_code)["at"]),
            *((name, adapter_functions[name]) for name in methods),
        ),
        fixture=tuple(
            (name, fixture_functions[name])
            for name in definitions
            if name in FRAME_DEFINITIONS or name in {"execute", "fault_primitive"}
        ),
    )


def matches(
    function: object,
    expected: tuple[object, ...],
    module: types.ModuleType,
) -> bool:
    """Check that code and globals still refer to the inspected module.

    Returns:
        Whether this exact function can use the certificate.
    """
    return (
        isinstance(function, types.FunctionType)
        and function.__globals__ is vars(module)
        and function.__defaults__ is None
        and function.__kwdefaults__
        == ({"fault": None} if function.__name__ == "verify_effect" else None)
        and signature(function.__code__) == expected
    )


def live(
    source: Source,
    fixture: types.ModuleType,
    frame_types: tuple[type, ...],
) -> bool:
    """Keep the certificate scoped to the reviewed dispatch and native primitives.

    Returns:
        Whether the implementation and its live dependencies are the expected ones.
    """
    adapter = peri_scribe.durable_file
    implementation = getattr(adapter, "LocalFile", None)
    commands = COMMAND_MODULE
    namespace = vars(fixture)
    return (
        isinstance(implementation, type)
        and getattr(adapter, "pathlib", None) is pathlib
        and getattr(adapter, "tempfile", None) is tempfile
        and getattr(fixture, "dataclasses", None) is dataclasses
        and getattr(fixture, "pytest", None) is pytest
        and getattr(fixture, "os", None) is os
        and getattr(fixture, "pathlib", None) is pathlib
        and getattr(fixture, "stat", None) is stat
        and getattr(fixture, "peri_scribe", None) is peri_scribe
        and getattr(fixture, "tests", None) is tests
        and getattr(fixture, "Operation", None) is commands.Operation
        and (commands.Operation, commands.Effect, commands.Entry) == COMMAND_TYPES
        and tests.helpers.doubles.peri_scribe.pipeline_fetch_recovery.ProcessLoss
        is PROCESS_LOSS
        and tuple(
            namespace.get(name)
            for name in ("Primitive", "PathCall", "Fault", "PhysicalEntry")
        )
        == frame_types
        and getattr(fixture, "FILES", None) == commands.FILES == FRAME_FILES
        and getattr(fixture, "FILE_INDEX", None)
        == commands.FILE_INDEX
        == {name: index for index, name in enumerate(FRAME_FILES)}
        and all(
            namespace.get(name, getattr(builtins, name)) is getattr(builtins, name)
            for name in ("isinstance", "bool", "bytes", "OSError", "FileNotFoundError")
        )
        and tuple(
            namespace.get(name) for name in ("KMZ", "PENDING", "DEFERRED", "CHECKPOINT")
        )
        == FRAME_FILES[-4:]
        and namespace.get("SIBLING") == "other/files/sibling"
        and namespace.get("SENTINEL_STAMP") == SIBLING_STAMP
        and implementation.__getattribute__ is object.__getattribute__
        and implementation.__new__ is object.__new__
        and not hasattr(implementation, "__getattr__")
        and not hasattr(implementation, "__post_init__")
        and not hasattr(implementation, "path")
        and isinstance(implementation.__init__, types.FunctionType)
        and signature(implementation.__init__.__code__)
        == signature(Initializer.__init__.__code__)
        and all(
            getattr(owner, name, None) is original
            for owner, name, original in NATIVE_IDENTITIES
        )
        and all(
            matches(
                getattr(adapter if name == "at" else implementation, name, None),
                expected,
                adapter,
            )
            for name, expected in source.adapter
        )
        and all(
            matches(getattr(fixture, name, None), expected, fixture)
            for name, expected in source.fixture
        )
    )


def current_oracle() -> bool:
    """Require Lake's current proof build before sharing a physical witness.

    Returns:
        Whether the oracle and proof artifact follow their source inputs.
    """
    directory = tests.formal.helpers.oracle.DIRECTORY / "lean"
    build = directory / ".lake" / "build"
    binary = build / "bin" / "oracle"
    checked = build / "lib" / "lean" / "PeriScribe" / "PipelineFileFootprint.olean"
    proof = directory / "PeriScribe" / "PipelineFileFootprint.lean"
    refinement = directory / "PeriScribe" / "EffectRefinement.lean"
    executable_time = binary.stat().st_mtime_ns
    proof_time = checked.stat().st_mtime_ns
    return executable_time >= proof_time >= max(
        proof.stat().st_mtime_ns,
        refinement.stat().st_mtime_ns,
    ) and executable_time >= max(
        (directory / name).stat().st_mtime_ns
        for name in ("Main.lean", "PeriScribe.lean")
    )


def resolve(
    fixture: types.ModuleType,
    frame_types: tuple[type, ...],
) -> Footprint | None:
    """Obtain current Lean transfers after checking the source and live bindings.

    Returns:
        The checked transfer table, or absence to run the full physical matrix.
    """
    adapter_file = peri_scribe.durable_file.__file__
    fixture_file = fixture.__file__
    commands_file = tests.formal.helpers.pipeline_replay_files.__file__
    if adapter_file is None or fixture_file is None or commands_file is None:
        return None
    try:
        source = recognize(
            *(
                pathlib.Path(path).read_text(encoding="utf-8")
                for path in (adapter_file, fixture_file, commands_file)
            ),
        )
        if (
            source is None
            or not live(source, fixture, frame_types)
            or not current_oracle()
        ):
            return None
        response = tests.formal.helpers.oracle.evaluate([
            "pipeline-file-footprint " + " ".join(map(str, source.shape)),
        ])
    except OSError, UnicodeError:
        return None
    if (
        len(response) != 1
        or len(response[0]) != 1 + 2 * len(OPERATIONS)
        or response[0][0] != 1
    ):
        return None
    try:
        return Footprint(transfers=tuple(map(Transfer, response[0][1:])))
    except ValueError:
        return None
