"""Build authenticated compact catalogs with distinguishable exact source rows."""

import contextlib
import datetime
import pathlib
import sqlite3

import shapely

import peri_scribe.geo.database
import peri_scribe.geo.package
import peri_scribe.models
import peri_scribe.sources.snapshots


FEED = "WFIGS_Interagency_Perimeters_Current_0"


def rows() -> tuple[peri_scribe.geo.package.FireRowRecord, ...]:
    """Include identifier bridges, spatial name edges and distinct attribute evidence.

    Returns:
        Three ordered original observations over two independent fires.
    """
    return tuple(
        peri_scribe.geo.package.FireRowRecord(
            record=peri_scribe.models.FireRecord(
                name=name,
                status=peri_scribe.models.FireStatus.ACTIVE,
                identifiers=frozenset({f"fire-{index}"}),
                names=frozenset({name.lower()}),
                geometry=shapely.box(index / 100, 0, 0.02 + index / 100, 0.02),
                observed_at=datetime.datetime(2026, 1, index + 1, tzinfo=datetime.UTC),
            ),
            object_id=index + 1,
            source_name=FEED,
            attributes={
                "attr_IsCpxChild": 0,
                "attr_IncidentSize": 100 + index,
                "poly_Acres_AutoCalc": 100 + index,
                "nested": [index, None, True],
            },
        )
        for index, name in enumerate(("Park", "Park", "Hill"))
    )


def create(
    directory: pathlib.Path,
    records: tuple[peri_scribe.geo.package.FireRowRecord, ...] | None = None,
    memberships: tuple[peri_scribe.models.ComplexMembership, ...] = (),
) -> pathlib.Path:
    """Create a pinned-reader fixture without depending on a geospatial file writer.

    Args:
        directory: Per-test source root.
        records: Complete source evidence, or the default three observations.
        memberships: Independently parsed membership evidence.

    Returns:
        The authoritative snapshot path paired with its exact parsed cache receipt.
    """
    if records is None:
        records = rows()
    source = peri_scribe.sources.snapshots.SourceFile(
        serial_number=0,
        last_edit_timestamp=0,
    )
    feed = directory / FEED
    path = feed / source.relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"authenticated source fixture")
    database = peri_scribe.sources.snapshots.record_cache_database_path(feed)
    with contextlib.closing(sqlite3.connect(database)) as connection:
        peri_scribe.geo.database.reset_database(connection)
        info = path.stat()
        peri_scribe.geo.database.write_snapshot(
            connection,
            source,
            info.st_size,
            info.st_mtime_ns,
            peri_scribe.geo.package.GeopackageContents(
                rows=records,
                memberships=memberships,
            ),
            checksum=peri_scribe.geo.database.snapshot_checksum(path),
        )
        connection.commit()
    return path


def metadata(
    path: pathlib.Path,
    changes: dict[str, object],
) -> sqlite3.Row:
    """Expose real named metadata fields with independently selected invalid values.

    Args:
        path: An authenticated snapshot created by this factory.
        changes: Deliberate field substitutions for metadata authentication tests.

    Returns:
        A SQLite row retaining unchanged evidence and requested substitutions.
    """
    database = peri_scribe.sources.snapshots.record_cache_database_path(
        path.parent.parent,
    )
    with contextlib.closing(sqlite3.connect(database)) as connection:
        connection.row_factory = sqlite3.Row
        values = dict(
            connection.execute(
                "SELECT rows.*, geometry_payloads.digest AS geometry_digest, "
                "attribute_payloads.digest AS attributes_digest, "
                "geometry_payloads.original_size AS geometry_size, "
                "attribute_payloads.original_size AS attributes_size FROM rows "
                "LEFT JOIN geometry_payloads "
                "ON geometry_payloads.id = rows.geometry_id "
                "LEFT JOIN attribute_payloads "
                "ON attribute_payloads.id = rows.attributes_id "
                "ORDER BY rows.rowid LIMIT 1",
            ).fetchone(),
        )
        values.update(changes)
        fields = ", ".join(f'? AS "{name}"' for name in values)
        return connection.execute(f"SELECT {fields}", tuple(values.values())).fetchone()
