"""Connect checked dictionary publication outcomes to actual ordered SQL payloads."""

import collections.abc
import contextlib
import pathlib
import sqlite3

import peri_scribe.geo.database
import peri_scribe.geo.package
import peri_scribe.geo.reading
import peri_scribe.sources.snapshots
import spatial_data.geometry_pool
import tests.formal.helpers.parsed_cache
import tests.helpers.factories.peri_scribe.geo.database


CONFIGURATION_COUNT = 36


def contents(sequence: tuple[int, ...]) -> peri_scribe.geo.package.GeopackageContents:
    """Keep every symbolic payload occurrence distinct from storage references.

    Args:
        sequence: Ordered payload identities exported by the checked model.

    Returns:
        Real complete source rows with the model's exact order and multiplicity.
    """
    return peri_scribe.geo.package.GeopackageContents(
        rows=tuple(
            tests.helpers.factories.peri_scribe.geo.database.contents(value).rows[0]
            for value in sequence
        ),
        memberships=(),
    )


def publish(connection: sqlite3.Connection, sequence: tuple[int, ...]) -> None:
    """Exercise complete references, receipt publication, and payload reclamation.

    Args:
        connection: The concrete writer transaction.
        sequence: One checked target sequence.
    """
    peri_scribe.geo.database.write_snapshot(
        connection,
        peri_scribe.sources.snapshots.SourceFile(
            serial_number=1,
            last_edit_timestamp=1,
        ),
        1,
        1,
        contents(sequence),
        checksum=repr(sequence),
    )
    peri_scribe.geo.database.collect_unreferenced_payloads(connection)


def replay(
    original: tuple[int, ...],
    target: tuple[int, ...],
    *,
    commit: bool,
) -> None:
    """Require the checked commit or abort result through an independent SQL reader.

    Args:
        original: The complete checked starting sequence.
        target: The requested checked replacement sequence.
        commit: Whether the selected model outcome publishes or aborts its transaction.
    """
    with contextlib.closing(sqlite3.connect(":memory:")) as connection:
        peri_scribe.geo.database.reset_database(connection)
        publish(connection, original)
        connection.commit()
        publish(connection, target)
        if commit:
            connection.commit()
        else:
            connection.rollback()
        expected = target if commit else original
        actual = peri_scribe.geo.reading.fetch_snapshot_batch(
            connection,
            {pathlib.Path("source"): (1, repr(expected))},
            geometry_pool=spatial_data.geometry_pool.GeometryPool(),
        )
        assert actual == {pathlib.Path("source"): contents(expected)}
        for table in ("geometry_payloads", "attribute_payloads"):
            assert connection.execute(f"SELECT count(*) FROM {table}").fetchone()[
                0
            ] == (len(set(expected)))


def configurations(
    states: collections.abc.Iterable[dict[str, str]],
    phase: str,
) -> set[tuple[tuple[int, ...], tuple[int, ...]]]:
    """Use actual checked outcome states instead of a handwritten state-space sample.

    Args:
        states: The complete states of NormalizedCache's successful TLC exploration.
        phase: The selected durable publication or transaction-abort outcome.

    Returns:
        Every original/target pair that reaches that checked outcome.
    """
    return {
        (
            tests.formal.helpers.parsed_cache.numbers(state["original"]),
            tests.formal.helpers.parsed_cache.numbers(state["target"]),
        )
        for state in states
        if state["phase"] == f'"{phase}"'
    }
