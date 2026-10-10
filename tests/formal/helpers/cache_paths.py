"""Observe committed SQLite records and schema changes along one checked execution."""

import collections.abc
import contextlib
import dataclasses
import hashlib
import operator
import pathlib
import re
import sqlite3

import pytest

import tests.formal.helpers.paths
import tests.formal.helpers.tlc
import tests.helpers.factories.peri_scribe.geo.database


TABLES = ("snapshots", "rows", "memberships")
type Rows = tuple[tuple[object, ...], ...]
type Projection = tuple[tuple[str, Rows], ...]


def contents(revision: int, serial: int, table: str) -> Rows:
    """A model revision denotes every serialized field, not only a checksum marker.

    Args:
        revision: Complete symbolic revision, with zero denoting no records.
        serial: Snapshot identity.
        table: One of the independently mutable cache tables.

    Returns:
        The exact canonical records represented by that model token.
    """
    if not revision:
        return ()
    parsed = tests.helpers.factories.peri_scribe.geo.database.contents(revision)
    if table == "snapshots":
        return ((serial, hashlib.sha256(str(revision).encode()).hexdigest()),)
    if table == "rows":
        return tuple(
            sorted(
                (row.to_row(serial) for row in parsed.rows),
                key=operator.itemgetter(1),
            ),
        )
    return tuple(
        sorted(
            (
                (
                    serial,
                    value.fire_identifier,
                    value.complex_identifier,
                    value.complex_name,
                    None
                    if value.observation_time is None
                    else value.observation_time.isoformat(),
                )
                for value in parsed.memberships
            ),
            key=operator.itemgetter(1),
        ),
    )


def observe(path: pathlib.Path) -> Projection:
    """Independent connections expose committed content, including incomplete schemas.

    Args:
        path: The database being mutated by the actual production writer.

    Returns:
        All available tables and their complete committed row payloads.
    """
    with contextlib.closing(
        sqlite3.connect(f"file:{path}?mode=ro", uri=True),
    ) as reader:
        present = {
            row[0]
            for row in reader.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'",
            )
        }
        return tuple(
            (
                table,
                tuple(
                    reader.execute(
                        f"SELECT {'serial, checksum' if table == 'snapshots' else '*'} "
                        f"FROM {table} ORDER BY serial"
                        + (
                            ", object_id"
                            if table == "rows"
                            else ", fire_identifier"
                            if table == "memberships"
                            else ""
                        ),
                    ).fetchall(),
                ),
            )
            for table in TABLES
            if table in present
        )


def sync_contract(
    graph: tests.formal.helpers.tlc.Graph,
    initial: str,
    target: str,
) -> tests.formal.helpers.paths.Contract[Projection]:
    """Transaction commit, abort, and retry stay explicit across real recovery.

    Args:
        graph: Complete checked transaction graph.
        initial: TLC's exact initial inventory label.
        target: TLC's exact target inventory label.

    Returns:
        A contract retaining pending SQL effects as hidden transaction state.
    """
    values = {}
    for identifier, state in graph.states.items():
        if (state["initial"], state["target"]) != (initial, target):
            continue
        revisions = tuple(map(int, re.findall(r"receipt \|-> (\d+)", state["durable"])))
        values[identifier] = tuple(
            (
                table,
                tuple(
                    row
                    for serial, revision in enumerate(revisions, 1)
                    for row in contents(revision, serial, table)
                ),
            )
            for table in TABLES
        )
    return tests.formal.helpers.paths.Contract(
        graph=graph,
        values=values,
        actions={
            edge: edge.action for edges in graph.outgoing.values() for edge in edges
        },
        internal=frozenset({"Write", "Advance"}),
    )


def rebuild_contract(
    graph: tests.formal.helpers.tlc.Graph,
    source: str,
) -> tests.formal.helpers.paths.Contract[Projection]:
    """A restart cannot invisibly restore a dropped or unauthenticated table.

    Args:
        graph: Complete checked schema and recovery graph.
        source: The fixed authoritative source revision.

    Returns:
        Exact schema/content projections, preserving the model's hidden DDL position.
    """
    return tests.formal.helpers.paths.Contract(
        graph=graph,
        values={
            identifier: tuple(
                (
                    table,
                    contents(
                        int(state["receipt" if table == "snapshots" else table]),
                        1,
                        table,
                    ),
                )
                for table in TABLES
                if f'"{table}"' in state["tables"]
            )
            for identifier, state in graph.states.items()
            if state["source"] == source
        },
        actions={
            edge: edge.action for edges in graph.outgoing.values() for edge in edges
        },
        internal=frozenset({"Reset", "Synchronize"}),
    )


@dataclasses.dataclass(kw_only=True)
class Observer:
    """Callbacks retain assertion failures because SQLite suppresses callback errors."""

    database: pathlib.Path
    execution: tests.formal.helpers.paths.Path[Projection]
    transaction: bool = False
    pending_commit: bool = False
    committed: bool = False
    failure: AssertionError | None = None

    def inspect(self) -> None:
        """Each completed commit consumes one actual TLC commit edge."""
        value = observe(self.database)
        self.execution = (
            self.execution.transition("Commit", value)
            if self.transaction and self.pending_commit
            else self.execution.observe(value)
        )
        if self.transaction and self.pending_commit:
            self.committed = True
        self.pending_commit = False

    def trace(self, statement: str) -> None:
        """Observe the preceding statement before SQLite starts the next statement.

        Args:
            statement: The real next SQL operation.
        """
        if self.failure is not None:
            return
        try:
            self.inspect()
            self.pending_commit = statement.lstrip().startswith("COMMIT")
        except AssertionError as error:
            self.failure = error

    def finish(self, *, aborted: bool = False) -> None:
        """Check the final operation after callbacks can no longer expose its result.

        Args:
            aborted: Whether an interrupted transaction was closed and rolled back.
        """
        if self.failure is not None:
            raise self.failure
        if aborted:
            self.pending_commit = False
            self.execution = self.execution.transition("Abort", observe(self.database))
        else:
            self.inspect()
            if self.transaction and not self.committed:
                self.execution = self.execution.transition(
                    "Commit",
                    observe(self.database),
                )
                self.committed = True


@contextlib.contextmanager
def connections(observer: Observer) -> collections.abc.Generator[None]:
    """Keep production connection setup and cleanup while observing its real SQL.

    Args:
        observer: One continuous checked execution for the target database.

    Yields:
        The real connection factory with only its trace callback extended.
    """
    original = sqlite3.connect

    def connect(
        database: str | pathlib.Path,
        *,
        uri: bool = False,
    ) -> sqlite3.Connection:
        """Only the writer path receives the observer; independent readers use a URI.

        Args:
            database: The production-selected database path or reader URI.
            uri: Whether the database is an independent observation URI.

        Returns:
            A real SQLite connection with ordinary persistence semantics.
        """
        connection = original(database, uri=uri)
        if database == observer.database:
            connection.set_trace_callback(observer.trace)
        return connection

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(sqlite3, "connect", connect)
        yield
