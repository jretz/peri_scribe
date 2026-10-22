"""Follow real compaction copies and replacement along one checked TLC execution."""

import collections.abc
import contextlib
import dataclasses
import functools
import pathlib
import re
import sqlite3
import unittest.mock

import peri_scribe.geo.compaction
import peri_scribe.geo.database
import tests.formal.helpers.parsed_cache
import tests.formal.helpers.paths
import tests.formal.helpers.tlc
import tests.helpers.factories.peri_scribe.geo.compaction


type Payload = tuple[int, ...]
type Tables = tuple[Payload, ...]
type Value = tuple[Payload, int, str, Tables, Tables]
type Signature = tuple[tuple[tuple[object, ...], ...], ...]
CONFIGURATION_COUNT = 6
TABLE_COUNT = 6
VALIDATION_BOUNDARY = TABLE_COUNT + 1
CLOSURE_BOUNDARY = TABLE_COUNT + 2


def tables(value: str) -> Tables:
    """Decode the checked sequence of table identities without evaluating text.

    Args:
        value: TLC's nested sequence of complete symbolic table contents.

    Returns:
        Every table's ordered symbolic payload.
    """
    return tuple(
        tests.formal.helpers.parsed_cache.numbers(payload)
        for payload in re.findall(r"<<([^<>]*)>>", value)
    )


def contract(
    graph: tests.formal.helpers.tlc.Graph,
) -> tests.formal.helpers.paths.Contract[Value]:
    """Retain complete stage and publication ordering from the checked graph.

    Args:
        graph: Freshly checked complete ParsedCacheCompaction execution graph.

    Returns:
        A matcher with every compaction boundary represented as an explicit event.
    """
    return tests.formal.helpers.paths.Contract(
        graph=graph,
        values={
            identifier: (
                tests.formal.helpers.parsed_cache.numbers(state["original"]),
                int(state["copied"]),
                state["phase"].strip('"'),
                tables(state["staged"]),
                tables(state["durable"]),
            )
            for identifier, state in graph.states.items()
        },
        actions={
            edge: edge.action for edges in graph.outgoing.values() for edge in edges
        },
        internal=frozenset(),
    )


@dataclasses.dataclass(kw_only=True)
class Replay:
    """Observe complete values at the application's actual effect boundaries."""

    path: pathlib.Path
    original: Payload
    expected: Signature
    execution: tests.formal.helpers.paths.Path[Value]
    stop: int | None
    corrupt: bool
    copied: int = 0
    staged: Tables = ((),) * TABLE_COUNT

    def observe(self, action: str, phase: str) -> None:
        """Keep every real observation compatible with its entire prior execution.

        Args:
            action: The effect that has just completed.
            phase: Its resulting lifecycle phase.
        """
        actual = tests.helpers.factories.peri_scribe.geo.compaction.signature(self.path)
        durable = tuple(
            self.original if value == expected else (*self.original, 9)
            for value, expected in zip(actual, self.expected, strict=True)
        )
        self.execution = self.execution.transition(
            action,
            (self.original, self.copied, phase, self.staged, durable),
        )

    def copy(
        self,
        original_copy: collections.abc.Callable[
            [sqlite3.Connection, sqlite3.Connection, str],
            None,
        ],
        source: sqlite3.Connection,
        target: sqlite3.Connection,
        table: str,
    ) -> None:
        """Inject failures or corruption after independently copied tables.

        Args:
            original_copy: The real table-copy function supplied by the patch adapter.
            source: Original pinned source transaction.
            target: Private replacement transaction.
            table: The table being copied.

        Raises:
            InterruptedError: At the selected copy boundary.
        """
        if self.stop == 0:
            raise InterruptedError
        original_copy(source, target, table)
        self.copied += 1
        if self.corrupt and table == "memberships":
            target.execute(f"DELETE FROM {table}")
        actual = tuple(target.execute(f"SELECT rowid, * FROM {table} ORDER BY rowid"))
        payload = (
            self.original
            if actual == self.expected[self.copied - 1]
            else (*self.original, 9)
        )
        self.staged = (
            *self.staged[: self.copied - 1],
            payload,
            *self.staged[self.copied :],
        )
        self.observe("Copy", "copy")
        if self.stop == self.copied:
            raise InterruptedError

    def validate(
        self,
        original_validate: collections.abc.Callable[
            [sqlite3.Connection, sqlite3.Connection],
            None,
        ],
        source: sqlite3.Connection,
        target: sqlite3.Connection,
    ) -> None:
        """Observe actual validation success or rejection before handles close.

        Args:
            original_validate: The real complete-content validator.
            source: Original pinned source transaction.
            target: Complete candidate transaction.

        Raises:
            InterruptedError: After the selected validation boundary.
            ValueError: If the real validator rejects damaged candidate contents.
        """
        try:
            original_validate(source, target)
        except ValueError:
            self.observe("Validate", "failed")
            raise
        self.observe("Validate", "validated")
        if self.stop == VALIDATION_BOUNDARY:
            raise InterruptedError

    def prepare(
        self,
        original_prepare: collections.abc.Callable[
            [pathlib.Path, pathlib.Path, str],
            bool,
        ],
        path: pathlib.Path,
        target: pathlib.Path,
        schema: str,
    ) -> bool:
        """Observe connection retirement before any atomic file replacement.

        Args:
            original_prepare: The real staged preparation function.
            path: Original protected cache.
            target: Private staged cache.
            schema: Current schema.

        Returns:
            The real preparation result.

        Raises:
            InterruptedError: After the selected connection-retirement boundary.
        """
        result = original_prepare(path, target, schema)
        self.observe("Close", "closed")
        if self.stop == CLOSURE_BOUNDARY:
            raise InterruptedError
        return result


def replay(
    checked: tests.formal.helpers.paths.Contract[Value],
    directory: pathlib.Path,
    original: Payload,
    stop: int | None,
    *,
    corrupt: bool = False,
) -> None:
    """Compare every completed copy, failure and publication with one TLC path.

    Args:
        checked: The freshly checked protocol and its full successor relation.
        directory: Isolated test directory.
        original: Source observation identity selected from actual initial states.
        stop: Effect boundary at which interruption is injected, or None.
        corrupt: Whether to damage the copied membership contents before validation.
    """
    path = directory / "cache.db"
    tests.helpers.factories.peri_scribe.geo.compaction.database(path, original)
    expected = tests.helpers.factories.peri_scribe.geo.compaction.signature(path)
    observer = Replay(
        path=path,
        original=original,
        expected=expected,
        execution=checked.start(
            (original, 0, "copy", ((),) * TABLE_COUNT, (original,) * TABLE_COUNT),
        ),
        stop=stop,
        corrupt=corrupt,
    )
    with (
        unittest.mock.patch.object(peri_scribe.geo.compaction, "MINIMUM_FREE_BYTES", 1),
        unittest.mock.patch.object(
            peri_scribe.geo.compaction,
            "copy_table",
            functools.partial(observer.copy, peri_scribe.geo.compaction.copy_table),
        ),
        unittest.mock.patch.object(
            peri_scribe.geo.compaction,
            "validate",
            functools.partial(observer.validate, peri_scribe.geo.compaction.validate),
        ),
        unittest.mock.patch.object(
            peri_scribe.geo.compaction,
            "prepare",
            functools.partial(observer.prepare, peri_scribe.geo.compaction.prepare),
        ),
        peri_scribe.geo.compaction.writer_lock(path),
        contextlib.closing(sqlite3.connect(path)) as reader,
    ):
        reader.execute("BEGIN")
        retained = reader.execute("SELECT rowid, * FROM rows ORDER BY rowid").fetchall()
        try:
            peri_scribe.geo.compaction.compact(
                path,
                peri_scribe.geo.database.RECORD_CACHE_SCHEMA,
            )
        except InterruptedError:
            observer.observe("Fail", "failed")
        except ValueError:
            assert corrupt
        else:
            assert stop is None
            assert not corrupt
            observer.observe("Publish", "published")
        assert (
            reader.execute("SELECT rowid, * FROM rows ORDER BY rowid").fetchall()
            == retained
        )
    assert (
        tests.helpers.factories.peri_scribe.geo.compaction.signature(path) == expected
    )
