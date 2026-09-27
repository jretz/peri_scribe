"""Replay checked parsed-cache outcomes through real SQLite transactions."""

import collections.abc
import contextlib
import dataclasses
import functools
import hashlib
import pathlib
import re
import sqlite3

import pytest

import peri_scribe.geo.database
import peri_scribe.geo.package
import peri_scribe.geo.reading
import peri_scribe.sources.snapshots
import spatial_data.geometry_pool
import tests.formal.helpers.cache_paths
import tests.formal.helpers.tlc
import tests.helpers.doubles.peri_scribe.geo.reading
import tests.helpers.factories.peri_scribe.geo.database


READ_PHASE_COUNT = 3
SNAPSHOT_COUNT = 2
READ_SCHEDULE_COUNT = 288
SYNC_CONFIGURATION_COUNT = 12
SYNC_INTERRUPTION_COUNT = 110
SCHEMA_PREFIX_COUNT = 9


def numbers(value: str) -> tuple[int, ...]:
    """Decode small numeric TLC sequences without interpreting executable text.

    Args:
        value: A sequence exported by TLC.

    Returns:
        The sequence's integer values.
    """
    return tuple(map(int, re.findall(r"\d+", value)))


@dataclasses.dataclass(kw_only=True)
class RejectSelect:
    """Simulate unusable cached tables while preserving real SQL reads otherwise."""

    fail_at: int
    count: int = 0

    def __call__(
        self,
        action: int,
        argument: str | None,
        column: str | None,
        database: str | None,
        trigger: str | None,
    ) -> int:
        """Reject exactly the selected read boundary through SQLite's authorizer.

        Args:
            action: SQLite operation being authorized.
            argument: Operation's object name.
            column: Operation's column name.
            database: Attached database identifier.
            trigger: Trigger or view requesting access.

        Returns:
            SQLite's authorization result.
        """
        del argument, column, database, trigger
        if action == sqlite3.SQLITE_SELECT:
            self.count += 1
            if self.count == self.fail_at:
                return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK


def replay_read(state: dict[str, str], path: pathlib.Path) -> None:
    """Compare statement-boundary commits and read failures with the checked answer.

    Args:
        state: A terminal ParsedCacheRead valuation.
        path: An isolated database for this schedule.
    """
    with (
        contextlib.closing(sqlite3.connect(path)) as writer,
        contextlib.closing(sqlite3.connect(path)) as reader,
    ):
        writer.execute("PRAGMA journal_mode = WAL")
        peri_scribe.geo.database.reset_database(writer)
        tests.helpers.factories.peri_scribe.geo.database.store(
            writer,
            int(state["before"]),
        )
        writer.commit()
        commit = tests.helpers.doubles.peri_scribe.geo.reading.ConcurrentCommit(
            writer=writer,
            revision=int(state["after"]),
            before_select=int(state["commitAt"]) + 1,
        )
        reader.set_trace_callback(commit)
        reader.set_authorizer(RejectSelect(fail_at=int(state["failureAt"])))
        actual = None
        try:
            actual = peri_scribe.geo.reading.fetch_snapshot_rows(
                reader,
                1,
                checksum=state["checksum"],
                geometry_pool=spatial_data.geometry_pool.GeometryPool(),
            )
        except sqlite3.DatabaseError:
            assert int(state["failureAt"]) > 0, state
        expected = numbers(state["answer"])
        if expected:
            assert actual == peri_scribe.geo.package.GeopackageContents(
                rows=tests.helpers.factories.peri_scribe.geo.database.contents(
                    expected[0],
                ).rows,
                memberships=tests.helpers.factories.peri_scribe.geo.database.contents(
                    expected[1],
                ).memberships,
            ), state
            if int(state["commitAt"]) < READ_PHASE_COUNT:
                assert commit.committed, state
        else:
            assert actual is None, state
        assert not reader.in_transaction, state


def source_path(directory: pathlib.Path, serial: int) -> pathlib.Path:
    """Keep symbolic files within the application's discoverable snapshot layout.

    Args:
        directory: Isolated feed directory.
        serial: Snapshot identifier.

    Returns:
        The path produced by the application's naming contract.
    """
    return (
        directory
        / peri_scribe.sources.snapshots.SourceFile(
            serial_number=serial,
            last_edit_timestamp=0,
        ).relative_path
    )


def inventory(directory: pathlib.Path, revisions: tuple[int, ...]) -> None:
    """Represent immutable input generations with distinguishable authenticated bytes.

    Args:
        directory: Isolated feed directory.
        revisions: One revision per serial, with zero denoting absence.
    """
    for serial, revision in enumerate(revisions, 1):
        path = source_path(directory, serial)
        if revision:
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists() or path.read_text(encoding="utf-8") != str(revision):
                path.write_text(str(revision), encoding="utf-8")
        else:
            path.unlink(missing_ok=True)


def parse_source(path: pathlib.Path) -> peri_scribe.geo.package.GeopackageContents:
    """Isolate parsing cost while retaining every actual cache serialization operation.

    Args:
        path: The authenticated symbolic source file.

    Returns:
        Distinct complete parsed contents for its bytes.
    """
    return tests.helpers.factories.peri_scribe.geo.database.contents(
        int(path.read_text(encoding="utf-8")),
    )


@dataclasses.dataclass(kw_only=True)
class InterruptStatements:
    """Interrupt real SQLite work at a selected mutation or commit boundary."""

    connection: sqlite3.Connection
    stop_after: int
    mutations: int = 0
    interrupted: bool = False

    def __call__(self, statement: str) -> None:
        """Abort within the SQL virtual machine so production cleanup rolls back.

        Args:
            statement: The actual SQL about to execute.
        """
        if statement.startswith(("INSERT", "DELETE", "COMMIT")):
            if self.mutations == self.stop_after:
                self.connection.interrupt()
                self.interrupted = True
            self.mutations += 1


def expected_revisions(value: str) -> tuple[int, ...]:
    """Read only the checked durable receipts, leaving payload verification separate.

    Args:
        value: The TLC sequence of cache records.

    Returns:
        Its two checksum revision tokens.
    """
    revisions = tuple(map(int, re.findall(r"receipt \|-> (\d+)", value)))
    assert len(revisions) == SNAPSHOT_COUNT, value
    return revisions


def assert_database(path: pathlib.Path, revisions: tuple[int, ...]) -> None:
    """Compare receipts and all serialized payload fields with a checked generation.

    Args:
        path: The committed cache database.
        revisions: TLC's expected revision for each snapshot serial.
    """
    with contextlib.closing(sqlite3.connect(path)) as reader:
        reader.row_factory = sqlite3.Row
        rows = reader.execute("SELECT * FROM snapshots ORDER BY serial").fetchall()
        assert [row["serial"] for row in rows] == [
            serial for serial, revision in enumerate(revisions, 1) if revision
        ]
        for serial, revision in enumerate(revisions, 1):
            if revision:
                actual = peri_scribe.geo.reading.fetch_snapshot_rows(
                    reader,
                    serial,
                    checksum=hashlib.sha256(
                        str(revision).encode(),
                    ).hexdigest(),
                    geometry_pool=spatial_data.geometry_pool.GeometryPool(),
                )
                assert (
                    actual
                    == tests.helpers.factories.peri_scribe.geo.database.contents(
                        revision,
                    )
                )
            else:
                assert not reader.execute(
                    "SELECT 1 FROM rows WHERE serial = ?",
                    (serial,),
                ).fetchall()
                assert not reader.execute(
                    "SELECT 1 FROM memberships WHERE serial = ?",
                    (serial,),
                ).fetchall()


def mutation_count(initial: tuple[int, ...], target: tuple[int, ...]) -> int:
    """Map complete model statements to the concrete two-row insertion groups.

    Args:
        initial: Initial revision of each serial.
        target: Requested revision of each serial.

    Returns:
        The concrete INSERT and DELETE statement count before commit.
    """
    return sum(
        0 if old == new else 3 if new == 0 else 7
        for old, new in zip(initial, target, strict=True)
    )


def trace_statement(
    observer: tests.formal.helpers.cache_paths.Observer,
    interruption: collections.abc.Callable[[str], None],
    statement: str,
) -> None:
    """Observe the previous durable effect before the next statement can be interrupted.

    Args:
        observer: The continuous checked execution.
        interruption: The selected SQL-boundary failure injector.
        statement: The actual next SQL statement.
    """
    observer.trace(statement)
    interruption(statement)


def replay_sync(
    states: list[dict[str, str]],
    directory: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    graph: tests.formal.helpers.tlc.Graph,
) -> int:
    """Exercise every concrete mutation interruption against checked durable states.

    Args:
        states: ParsedCache valuations for one initial and target inventory.
        directory: The isolated source and database root for this configuration.
        monkeypatch: Scoped replacement of expensive source parsing.
        graph: Complete checked graph retaining the actual recovery edges.

    Returns:
        The number of interrupted statement schedules exercised.
    """
    checked = tests.formal.helpers.cache_paths.sync_contract(
        graph,
        states[0]["initial"],
        states[0]["target"],
    )
    initial = numbers(states[0]["initial"])
    target = numbers(states[0]["target"])
    aborted = {
        expected_revisions(state["durable"])
        for state in states
        if state["phase"] == '"aborted"'
    }
    committed = {
        expected_revisions(state["durable"])
        for state in states
        if state["phase"] == '"committed"'
    }
    assert len(aborted) == len(committed) == 1
    old, final = next(iter(aborted)), next(iter(committed))
    monkeypatch.setattr(peri_scribe.geo.package, "read_geopackage", parse_source)
    source = directory / "source"
    source.mkdir(parents=True)
    database = directory / "record_cache.db"
    inventory(source, initial)
    peri_scribe.geo.database.open_and_sync(database, source)
    with contextlib.closing(sqlite3.connect(":memory:")) as original:
        with contextlib.closing(sqlite3.connect(database)) as connection:
            connection.backup(original)
        inventory(source, target)
        count = mutation_count(initial, target)
        for cut in range(count + 1 if count else 0):
            with contextlib.closing(sqlite3.connect(database)) as connection:
                original.backup(connection)
                interruption = InterruptStatements(
                    connection=connection,
                    stop_after=cut,
                )
                observer = tests.formal.helpers.cache_paths.Observer(
                    database=database,
                    execution=checked.start(
                        tests.formal.helpers.cache_paths.observe(database),
                    ),
                    transaction=True,
                )

                connection.set_trace_callback(
                    functools.partial(
                        trace_statement,
                        observer,
                        interruption,
                    ),
                )
                with pytest.raises(sqlite3.OperationalError, match="interrupted"):
                    peri_scribe.geo.database.sync_database(connection, source)
                assert interruption.interrupted
            observer.finish(aborted=True)
            assert_database(database, old)
            observer.execution = observer.execution.event("Restart")
            with tests.formal.helpers.cache_paths.connections(observer):
                peri_scribe.geo.database.open_and_sync(database, source)
            observer.finish()
            assert_database(database, final)
        with contextlib.closing(sqlite3.connect(database)) as connection:
            original.backup(connection)
        observer = tests.formal.helpers.cache_paths.Observer(
            database=database,
            execution=checked.start(tests.formal.helpers.cache_paths.observe(database)),
            transaction=True,
        )
        with tests.formal.helpers.cache_paths.connections(observer):
            peri_scribe.geo.database.open_and_sync(database, source)
        observer.finish()
        assert_database(database, final)
    return count + 1 if count else 0


@dataclasses.dataclass(kw_only=True)
class InterruptSchema:
    """Preserve already committed DDL while interrupting the next schema operation."""

    connection: sqlite3.Connection
    stop_after: int
    statements: int = 0

    def __call__(self, statement: str) -> None:
        """Abort a real schema statement at the checked rebuild prefix.

        Args:
            statement: SQLite's schema operation about to execute.
        """
        if statement.lstrip().startswith(("DROP", "CREATE", "PRAGMA user_version =")):
            if self.statements == self.stop_after:
                self.connection.interrupt()
            self.statements += 1


def replay_rebuild(
    state: dict[str, str],
    directory: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    graph: tests.formal.helpers.tlc.Graph,
) -> None:
    """Check interrupted DDL, authenticated fallback, and subsequent real recovery.

    Args:
        state: One checked reset prefix before any restart.
        directory: Isolated source and cache directory.
        monkeypatch: Scoped symbolic source parser replacement.
        graph: Complete checked graph retaining actual DDL and restart edges.
    """
    source = directory / "source"
    source.mkdir(parents=True)
    database = directory / "record_cache.db"
    monkeypatch.setattr(peri_scribe.geo.package, "read_geopackage", parse_source)
    inventory(source, (1,))
    peri_scribe.geo.database.open_and_sync(database, source)
    revision = int(state["source"])
    inventory(source, (revision,))
    path = source_path(source, 1)
    phase = int(state["phase"])
    checked = tests.formal.helpers.cache_paths.rebuild_contract(graph, state["source"])
    observer = tests.formal.helpers.cache_paths.Observer(
        database=database,
        execution=checked.start(tests.formal.helpers.cache_paths.observe(database)),
    )
    reset_statements = 8
    with contextlib.closing(sqlite3.connect(database)) as connection:
        connection.execute("PRAGMA user_version = 1")
        interruption = InterruptSchema(connection=connection, stop_after=phase)

        connection.set_trace_callback(
            functools.partial(
                trace_statement,
                observer,
                interruption,
            ),
        )
        if phase < reset_statements:
            with pytest.raises(sqlite3.OperationalError, match="interrupted"):
                peri_scribe.geo.database.reset_database(connection)
        else:
            peri_scribe.geo.database.reset_database(connection)
    observer.finish()
    if phase < reset_statements:
        observer.execution = observer.execution.event("CrashAndRestart")
    actual = None
    with contextlib.suppress(sqlite3.DatabaseError):
        actual = peri_scribe.geo.reading.read_snapshot_rows(
            database,
            1,
            checksum=peri_scribe.geo.database.snapshot_checksum(path),
            geometry_pool=spatial_data.geometry_pool.GeometryPool(),
        )
    expected = numbers(state["answer"])
    if expected:
        assert actual == tests.helpers.factories.peri_scribe.geo.database.contents(
            expected[0],
        ), state
    else:
        assert actual is None, state
    assert peri_scribe.geo.reading.read_cached_snapshot(
        database,
        1,
        path,
        geometry_pool=spatial_data.geometry_pool.GeometryPool(),
    ) == tests.helpers.factories.peri_scribe.geo.database.contents(revision)
    try:
        with tests.formal.helpers.cache_paths.connections(observer):
            peri_scribe.geo.database.ensure_database_current(database, source)
        observer.finish()
        assert_database(database, (revision,))
    finally:
        peri_scribe.geo.database.RECORD_CACHE_SYNCED.pop(database, None)
