"""Observe real receipt, archive, and source mutations against checked TLC states.

Design notes:
[Verification evidence and execution](../../../docs/algorithms/verification-tooling.md).
"""

from __future__ import annotations

import compression.zstd
import dataclasses
import hashlib
import importlib
import itertools
import json
import pathlib
import re
import shutil
import tempfile
import typing

import peri_scribe.logging
import tests.helpers.doubles.attribute_overrides
import tests.helpers.doubles.peri_scribe.log_rotation


if typing.TYPE_CHECKING:
    import tests.formal.helpers.paths as paths_types
    import tests.formal.helpers.tlc as tlc_types


LINES = {
    1: b'{"event":"legitimate identical diagnostic"}\n',
    2: b'{"event":"previously archived diagnostic"}\n',
}
type Projection = tuple[
    tuple[int, ...],
    tuple[int, ...],
    bool,
    tuple[int, ...],
    tuple[int, ...],
    tuple[int, ...],
]
type Fault = tuple[str, bool] | None


def numbers(value: str) -> tuple[int, ...]:
    """Decode TLC sequence elements without reproducing its transition policy.

    Args:
        value: A checked sequence of occurrence values.

    Returns:
        The ordered elements including every repetition.
    """
    return tuple(map(int, re.findall(r"\d+", value)))


def records(contents: bytes) -> tuple[int, ...]:
    """Retain repeated diagnostics as distinct positions in the observed sequence.

    Args:
        contents: Complete decoded log contents.

    Returns:
        Model occurrence values in exact file order.
    """
    lookup = {value: key for key, value in LINES.items()}
    return tuple(lookup[line] for line in contents.splitlines(keepends=True))


@dataclasses.dataclass(kw_only=True)
class Scenario:
    """Authenticate receipt fields while observing independently persisted files."""

    path: pathlib.Path
    checked: paths_types.Contract[Projection] | None
    execution: paths_types.Path[Projection] | None = None
    contents: dict[str, tuple[int, ...]] = dataclasses.field(default_factory=dict)
    observations: int = 0

    @property
    def archive(self) -> pathlib.Path:
        """Keep the actual archive destination shared across all boundary observers.

        Returns:
            The production archive path.
        """
        return self.path.with_suffix(".jsonl.zst")

    @property
    def receipt(self) -> pathlib.Path:
        """Keep persistent recovery metadata separate from source and archive bytes.

        Returns:
            The production receipt path.
        """
        return peri_scribe.logging.rotation_receipt_path(self.path)

    def remember(self, path: pathlib.Path, *, compressed: bool) -> tuple[int, ...]:
        """Map an actual checksum token to the exact record sequence it authenticates.

        Args:
            path: A public or staged artifact.
            compressed: Whether bytes are a Zstandard archive.

        Returns:
            Every logical occurrence in its actual order.
        """
        if not path.exists():
            return ()
        payload = path.read_bytes()
        contents = compression.zstd.decompress(payload) if compressed else payload
        values = records(contents)
        self.contents[hashlib.sha256(payload).hexdigest()] = values
        return values

    def snapshot(self) -> Projection:
        """Authenticate receipt tokens against the exact retained occurrence contents.

        Returns:
            The independently observed durable fields of the rotation protocol.
        """
        plain = self.remember(self.path, compressed=False)
        archive = self.remember(self.archive, compressed=True)
        receipt = self.receipt.exists()
        source = base = target = ()
        if receipt:
            fields = json.loads(self.receipt.read_bytes())
            assert fields["version"] == 1
            source = self.contents[fields["source_checksum"]]
            base = (
                ()
                if fields["archive_checksum"] is None
                else self.contents[fields["archive_checksum"]]
            )
            target = self.contents[fields["target_checksum"]]
        return plain, archive, receipt, source, base, target

    def inspect(self) -> None:
        """Reject any durable prefix that cannot extend the same checked execution."""
        actual = self.snapshot()
        assert self.checked is not None
        assert actual in self.checked.values.values(), (
            "rotation escaped checked durable states",
            actual,
        )
        self.execution = (
            self.checked.start(actual)
            if self.execution is None
            else self.execution.observe(actual)
        )
        self.observations += 1

    def install(
        self,
        patch: tests.helpers.doubles.attribute_overrides.AttributePatch,
    ) -> None:
        """Inspect both sides of production replacements and deletions.

        Args:
            patch: Isolated monkeypatch context.
        """
        original_replace = pathlib.Path.replace
        original_unlink = pathlib.Path.unlink

        def replace(path: pathlib.Path, destination: pathlib.Path) -> pathlib.Path:
            """Register staged target bytes before the receipt makes them durable.

            Args:
                path: Private staged file.
                destination: Published file.

            Returns:
                The real replacement result.
            """
            if destination == self.receipt:
                self.remember(path.parent / self.archive.name, compressed=True)
            self.inspect()
            result = original_replace(path, destination)
            self.inspect()
            return result

        def unlink(path: pathlib.Path, *, missing_ok: bool = False) -> None:
            """Preserve separate source and receipt retirement boundaries.

            Args:
                path: The retired path.
                missing_ok: Whether a previous retirement is accepted.
            """
            self.inspect()
            original_unlink(path, missing_ok=missing_ok)
            self.inspect()

        patch.setattr(pathlib.Path, "replace", replace)
        patch.setattr(pathlib.Path, "unlink", unlink)

    def rotate(self, fault: Fault) -> None:
        """Resume the same occurrence sequence after the selected interruption.

        Args:
            fault: One operation and side of its durable boundary, or no interruption.
        """
        pytest = importlib.import_module("pytest")
        with pytest.MonkeyPatch.context() as observer:
            self.install(observer)
            self.inspect()
            if fault is None:
                peri_scribe.logging.compress_log(self.path)
            else:
                boundary, after = fault
                interruption = (
                    tests.helpers.doubles.peri_scribe.log_rotation.Interruption(
                        target={
                            "receipt": self.receipt,
                            "archive": self.archive,
                            "source": self.path,
                            "retire": self.receipt,
                        }[boundary],
                        deletion=boundary in {"source", "retire"},
                        after=after,
                    )
                )
                with pytest.MonkeyPatch.context() as failure:
                    interruption.install(failure)
                    with pytest.raises(
                        tests.helpers.doubles.peri_scribe.log_rotation.ProcessLoss,
                    ):
                        peri_scribe.logging.compress_log(self.path)
                assert interruption.reached
                assert self.execution is not None
                self.execution = self.execution.event(
                    "Crash",
                    terminal_phases=frozenset({'"idle"'}),
                )
                self.inspect()
                if self.path.exists() or self.receipt.exists():
                    peri_scribe.logging.compress_log(self.path)
            self.inspect()


def contract(
    graph: tlc_types.Graph,
) -> paths_types.Contract[Projection]:
    """Bind occurrence projections to real directed successors from the checked model.

    Args:
        graph: The complete LogRotation transition graph exported by TLC.

    Returns:
        A path contract that cannot spend crash transitions invisibly.
    """
    actions = {edge: edge.action for edges in graph.outgoing.values() for edge in edges}
    paths = importlib.import_module("tests.formal.helpers.paths")
    return paths.Contract(
        graph=graph,
        values={
            identifier: (
                numbers(state["plain"]),
                numbers(state["archive"]),
                state["receipt"] == "TRUE",
                numbers(state["source"]),
                numbers(state["base"]),
                numbers(state["target"]),
            )
            for identifier, state in graph.states.items()
        },
        actions=actions,
        internal=frozenset(actions.values()) - {"Crash"},
    )


def replay(graph: tlc_types.Graph, directory: pathlib.Path) -> int:
    """Exercise every interruption pair across initial and identical late arrivals.

    Args:
        graph: Entire checked TLC state graph with its actual directed edges.
        directory: Isolated case root.

    Returns:
        Number of concrete two-rotation histories.
    """
    checked = contract(graph)
    faults: tuple[Fault, ...] = (
        None,
        *itertools.product(("receipt", "archive", "source", "retire"), (False, True)),
    )
    count = 0
    directory.mkdir(parents=True)
    for existing, first in itertools.product((False, True), faults):
        with tempfile.TemporaryDirectory(dir=directory) as temporary:
            prefix = pathlib.Path(temporary)
            seeded = Scenario(path=prefix / "2026-01.jsonl", checked=checked)
            if existing:
                seeded.archive.write_bytes(compression.zstd.compress(LINES[2]))
            seeded.path.write_bytes(LINES[1] * 2)
            seeded.rotate(first)
            for second in faults:
                root = directory / str(count)
                shutil.copytree(prefix, root)
                scenario = dataclasses.replace(
                    seeded,
                    path=root / seeded.path.name,
                    contents=seeded.contents.copy(),
                )
                scenario.path.write_bytes(LINES[1])
                scenario.rotate(second)
                expected = ((2,) if existing else ()) + (1, 1, 1)
                assert scenario.remember(scenario.archive, compressed=True) == expected
                assert set(root.iterdir()) == {scenario.archive}
                assert scenario.observations > 0
                count += 1
    return count
