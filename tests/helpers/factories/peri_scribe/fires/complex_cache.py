"""Real GeoPackage histories for cached temporal complex ownership."""

from __future__ import annotations

import datetime
import pathlib

import geopandas
import shapely

import peri_scribe.sources.feed_types
import peri_scribe.sources.snapshots
import spatial_data.layers


def write_snapshot(
    path: pathlib.Path,
    feed: peri_scribe.sources.feed_types.Feed,
    declarations: tuple[tuple[str | None, int, bool], ...],
    *,
    fire_identifiers: tuple[tuple[str | None, ...], ...] | None = None,
) -> None:
    """Keep independently dated declarations even when a row cannot name a fire.

    Args:
        path: Isolated source snapshot to create.
        feed: The configured WFIGS perimeter or incident-location source.
        declarations: Parent, incident day, and whether the child has a parseable name.
        fire_identifiers: Each row's identifiers in the feed's configured column order.
    """
    assert feed.complex_identifier_column is not None
    assert feed.complex_name_column is not None
    assert feed.is_complex_child_column is not None
    prefix = "attr_" if feed.is_complex_child_column.startswith("attr_") else ""
    columns: dict[str, list[object]] = {
        feed.fire_name_column: [
            "Child" if named else None for _, _, named in declarations
        ],
        feed.status_column: ["active"] * len(declarations),
        feed.complex_identifier_column: [parent for parent, _, _ in declarations],
        feed.complex_name_column: [parent for parent, _, _ in declarations],
        feed.is_complex_child_column: [
            str(parent is not None) for parent, _, _ in declarations
        ],
        prefix + "ModifiedOnDateTime_dt": [
            datetime.datetime(2026, 1, day, tzinfo=datetime.UTC).isoformat()
            for _, day, _ in declarations
        ],
    }
    for index, field in enumerate(feed.fire_identifier_columns):
        columns[field] = (
            [identifiers[index] for identifiers in fire_identifiers]
            if fire_identifiers is not None
            else ["child"] * len(declarations)
        )
    for field in (
        feed.point_of_origin_state_column,
        feed.point_of_origin_fips_column,
    ):
        if field is not None:
            columns[field] = [None] * len(declarations)
    if feed.observation_time_column != prefix + "ModifiedOnDateTime_dt":
        assert feed.observation_time_column is not None
        columns[feed.observation_time_column] = [
            "2026-03-01T00:00:00+00:00",
        ] * len(declarations)
    path.parent.mkdir(parents=True, exist_ok=True)
    spatial_data.layers.write_geopackage(
        path,
        [
            spatial_data.layers.LayerData(
                name=feed.name,
                dataframe=geopandas.GeoDataFrame(
                    columns,
                    geometry=[shapely.Point(-120, 39)] * len(declarations),
                    crs="EPSG:4326",
                ),
            ),
        ],
    )


def snapshots(
    directory: pathlib.Path,
    feed: peri_scribe.sources.feed_types.Feed,
    *,
    release: bool,
    unparsed: int | None = None,
) -> tuple[pathlib.Path, ...]:
    """Write out-of-order incident declarations with increasing collection clocks.

    Args:
        directory: The isolated authoritative source root.
        feed: The configured WFIGS perimeter or incident-location source.
        release: Whether to append a later explicit negative declaration.
        unparsed: Snapshot ordinal with a missing fire name, or None for complete rows.

    Returns:
        The authoritative snapshots in source-file order.
    """
    declarations = [("new-parent", 2), ("old-parent", 1)]
    if release:
        declarations.append((None, 3))
    paths = []
    for serial, (parent, day) in enumerate(declarations):
        collection = datetime.datetime(2026, 2, serial + 1, tzinfo=datetime.UTC)
        path = (
            directory
            / feed.name
            / peri_scribe.sources.snapshots.SourceFile(
                serial_number=serial,
                last_edit_timestamp=int(collection.timestamp() * 1000),
            ).relative_path
        )
        write_snapshot(path, feed, ((parent, day, serial != unparsed),))
        paths.append(path)
    return tuple(paths)


def correction_snapshot(
    directory: pathlib.Path,
    feed: peri_scribe.sources.feed_types.Feed,
    *,
    release: bool,
    reverse: bool,
) -> pathlib.Path:
    """A repeated relationship must retain the latest standalone declaration's date.

    Args:
        directory: The isolated authoritative source root.
        feed: The configured WFIGS perimeter or incident-location source.
        release: Whether the first and latest declarations explicitly release the child.
        reverse: Whether source row order opposes incident chronology.

    Returns:
        One snapshot containing all three independently dated declarations.
    """
    parent = None if release else "first-parent"
    declarations = ((parent, 1, True), ("other-parent", 2, True), (parent, 3, False))
    collection = datetime.datetime(2026, 2, 1, tzinfo=datetime.UTC)
    path = (
        directory
        / feed.name
        / peri_scribe.sources.snapshots.SourceFile(
            serial_number=0,
            last_edit_timestamp=int(collection.timestamp() * 1000),
        ).relative_path
    )
    write_snapshot(
        path,
        feed,
        tuple(reversed(declarations)) if reverse else declarations,
    )
    return path


def alias_snapshots(
    directory: pathlib.Path,
    feed: peri_scribe.sources.feed_types.Feed,
    *,
    primary_identifier: str | None,
    release: bool,
) -> tuple[pathlib.Path, ...]:
    """Preserve relationship corrections when only a secondary alias identifies a fire.

    Args:
        directory: The isolated authoritative source root.
        feed: The configured WFIGS perimeter or incident-location source.
        primary_identifier: The later unnamed row's primary alias, if present.
        release: Whether the later declaration releases or transfers the child.

    Returns:
        The earlier named source and later incomplete relationship source.
    """
    parent = None if release else "new-parent"
    declarations = (("old-parent", 1, True), (parent, 2, False))
    identifiers = (
        ("child-primary", "child-secondary"),
        (primary_identifier, "child-secondary"),
    )
    paths = []
    for serial, (declaration, aliases) in enumerate(
        zip(declarations, identifiers, strict=True),
    ):
        collection = datetime.datetime(2026, 2, serial + 1, tzinfo=datetime.UTC)
        path = (
            directory
            / feed.name
            / peri_scribe.sources.snapshots.SourceFile(
                serial_number=serial,
                last_edit_timestamp=int(collection.timestamp() * 1000),
            ).relative_path
        )
        write_snapshot(path, feed, (declaration,), fire_identifiers=(aliases,))
        paths.append(path)
    return tuple(paths)
