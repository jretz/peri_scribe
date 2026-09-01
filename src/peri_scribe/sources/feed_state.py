"""Reading and writing each feeds stored current feature state."""

from __future__ import annotations

import contextlib
import datetime
import pathlib
import typing

import pandas as pd
import structlog

import peri_scribe.geo.parsing
import peri_scribe.geo.reading
import peri_scribe.models
import peri_scribe.output
import peri_scribe.sources.feed_types
import peri_scribe.sources.snapshots


logger = structlog.get_logger()


if typing.TYPE_CHECKING:
    import geopandas


def latest_features_by_object_id(
    dataframes: typing.Iterable[geopandas.GeoDataFrame | None],
) -> geopandas.GeoDataFrame | None:
    """Return the latest feature per OBJECTID across *dataframes*.

    A later frame's version of a feature supersedes an earlier one. Frames built from a
    fetch name their geometry column ``geom`` while frames read back from a GeoPackage
    name it ``geometry``, so every frame's geometry column is renamed to ``geometry``
    before the merge, keeping the merged frame to a single geometry column. Returns None
    when no frame is supplied or when the combined frame has no OBJECTID column, so
    callers can treat a None result as "cannot compare against stored features".

    Args:
        dataframes: The feature frames to merge, in order from oldest to newest.

    Returns:
        The latest feature per OBJECTID, or None when no frame is supplied or the
        combined frame has no OBJECTID column.
    """
    present: list[geopandas.GeoDataFrame] = []
    for frame in dataframes:
        if frame is None:
            continue
        normalized = frame
        if (
            normalized.geometry.name
            != peri_scribe.models.GEOPACKAGE_GEOMETRY_COLUMN_NAME
        ):
            normalized = normalized.rename_geometry(
                peri_scribe.models.GEOPACKAGE_GEOMETRY_COLUMN_NAME,
            )
        present.append(
            typing.cast(
                "geopandas.GeoDataFrame",
                normalized,
            ),
        )
    if not present:
        return None
    combined = typing.cast(
        "geopandas.GeoDataFrame",
        pd.concat(present, ignore_index=True),
    )
    if peri_scribe.models.OBJECT_ID_COLUMN_NAME not in combined.columns:
        return None
    return combined[
        ~combined.duplicated(
            subset=[peri_scribe.models.OBJECT_ID_COLUMN_NAME],
            keep="last",
        )
    ]


def existing_features(
    directory: pathlib.Path,
    feed: peri_scribe.sources.feed_types.Feed,
) -> geopandas.GeoDataFrame | None:
    """Return the latest stored feature per OBJECTID across *directory*'s files.

    Files are read in serial order, so a later file's version of a feature supersedes an
    earlier one. Returns None when the directory holds no feature data to compare
    against.

    Args:
        directory: The directory holding the source's GeoPackage files.
        feed: The feed whose layer is read from each file.

    Returns:
        The most recent feature per OBJECTID, or None when there are none.
    """
    dataframes = [
        peri_scribe.geo.reading.read_layer_dataframe(
            directory / source_file.relative_path,
            feed,
        )
        for source_file in peri_scribe.sources.snapshots.existing_source_files(
            directory,
        )
    ]
    return latest_features_by_object_id(dataframes)


def current_state_serial_number(
    directory: pathlib.Path,
) -> int | None:
    """Return the serial number of the newest snapshot in *directory*.

    Args:
        directory: The directory holding the source's GeoPackage files.

    Returns:
        The newest snapshot's serial number, or None when the directory holds no
        snapshots.
    """
    source_files = peri_scribe.sources.snapshots.existing_source_files(directory)
    if not source_files:
        return None
    return source_files[-1].serial_number


def read_current_features(
    directory: pathlib.Path,
    feed: peri_scribe.sources.feed_types.Feed,
) -> geopandas.GeoDataFrame | None:
    """Return the latest stored feature per OBJECTID, from the state file when fresh.

    The feed's maintained current-state file holds the latest feature per OBJECTID
    across the snapshots it covers, so reading it costs one file read instead of a
    read of every snapshot ever stored. The state file is used only when it covers
    the newest snapshot; otherwise the snapshots are read directly, which is also how
    a missing or unreadable state file is handled. A state file is fresh only when
    its covered serial equals the newest snapshot serial, so a state file that
    outlives a snapshot rollback is rebuilt rather than trusted.

    Args:
        directory: The directory holding the source's GeoPackage files.
        feed: The feed whose layer is read from each file.

    Returns:
        The most recent feature per OBJECTID, or None when there are none.
    """
    state_files = peri_scribe.sources.snapshots.current_state_file_paths(
        directory,
    )
    if state_files:
        state_serial_number, state_path = state_files[-1]
        newest_serial_number = current_state_serial_number(directory)
        if (
            newest_serial_number is not None
            and state_serial_number == newest_serial_number
        ):
            try:
                return peri_scribe.geo.reading.read_layer_dataframe(
                    state_path,
                    feed,
                )
            except (OSError, RuntimeError, ValueError) as error:
                logger.warning(
                    "Failed to read current state; reading snapshots instead",
                    feed=feed.name,
                    path=str(state_path),
                    error=str(error),
                )
    return existing_features(directory, feed)


def write_current_state(
    directory: pathlib.Path,
    feed: peri_scribe.sources.feed_types.Feed,
    new_features: geopandas.GeoDataFrame,
) -> None:
    """Update *feed*'s current-state file to cover its newest snapshot.

    The new state is the latest feature per OBJECTID across the previous state (or,
    when there is no usable state file, every stored snapshot) and *new_features*,
    the rows of the snapshot just written. The state file is named for the newest
    snapshot's serial number, and any older state files for the feed are removed.
    The snapshots remain the source of truth: the state file is only a derived
    cache, rebuilt from the snapshots whenever it is missing, stale, or unreadable.

    Args:
        directory: The directory holding the source's GeoPackage files.
        feed: The feed whose layer is stored.
        new_features: The rows of the snapshot that was just written.
    """
    state_files = peri_scribe.sources.snapshots.current_state_file_paths(
        directory,
    )
    base: geopandas.GeoDataFrame | None = None
    if state_files:
        _state_serial_number, state_path = state_files[-1]
        try:
            base = peri_scribe.geo.reading.read_layer_dataframe(
                state_path,
                feed,
            )
        except (OSError, RuntimeError, ValueError) as error:
            logger.warning(
                "Failed to read current state while updating; rebuilding from "
                "snapshots",
                feed=feed.name,
                path=str(state_path),
                error=str(error),
            )
    if base is None:
        base = existing_features(directory, feed)
    merged = latest_features_by_object_id([base, new_features])
    newest_serial_number = current_state_serial_number(directory)
    if merged is None or newest_serial_number is None:
        return
    state_path = peri_scribe.sources.snapshots.current_state_path(
        directory,
        newest_serial_number,
    )
    state_path.parent.mkdir(parents=True, exist_ok=True)
    peri_scribe.output.write_geopackage(
        state_path,
        [
            peri_scribe.models.LayerData(
                name=feed.name,
                dataframe=merged,
            ),
        ],
    )
    for _old_serial_number, old_path in state_files:
        if old_path != state_path:
            with contextlib.suppress(FileNotFoundError):
                old_path.unlink()


def stored_object_ids(
    existing: geopandas.GeoDataFrame | None,
) -> set[int]:
    """Return the OBJECTIDs already stored, or an empty set when unknown.

    The set is the layer's stored identities: an OBJECTID present in the layer but
    not in this set belongs to a feature the store has never captured, so the caller
    can fetch it even when the source never populated its modified timestamp.

    Args:
        existing: The latest stored feature per OBJECTID, or None.

    Returns:
        The stored OBJECTIDs, or an empty set when *existing* has no OBJECTID column.
    """
    if existing is None or peri_scribe.models.OBJECT_ID_COLUMN_NAME not in existing:
        return set()
    return {
        int(object_id)
        for object_id in existing[peri_scribe.models.OBJECT_ID_COLUMN_NAME]
    }


def sql_literal(value: object) -> str:
    """Return *value* formatted as a SQL literal for an ArcGIS where clause.

    Text values are single-quoted and numbers and booleans are returned unquoted.

    Args:
        value: A raw attribute value.

    Returns:
        The SQL literal.

    Raises:
        ValueError: If *value* is not text, a number, or a boolean.

    Examples:
        >>> sql_literal("active")
        "'active'"

        >>> sql_literal(True)
        'true'
    """
    if isinstance(value, str):
        return f"'{value}'"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(int(value))
    message = f"Unsupported SQL literal type: {type(value).__name__}"
    raise ValueError(message)


def stored_status_object_ids(
    existing: geopandas.GeoDataFrame | None,
    feed: peri_scribe.sources.feed_types.Feed,
    status: peri_scribe.models.FireStatus,
) -> list[int]:
    """Return the stored OBJECTIDs whose latest stored status is *status*.

    Each row's raw status value is classified the same way the fire index does, so
    callers can build queries that watch for status changes. Rows whose status value
    is missing or unrecognized are ignored.

    Args:
        existing: The latest stored feature per OBJECTID, or None.
        feed: The feed providing the status column.
        status: The status to select.

    Returns:
        The matching OBJECTIDs, sorted.
    """
    if (
        existing is None
        or feed.status_column not in existing
        or peri_scribe.models.OBJECT_ID_COLUMN_NAME not in existing
    ):
        return []
    object_ids: list[int] = []
    for object_id, value in zip(
        existing[peri_scribe.models.OBJECT_ID_COLUMN_NAME],
        existing[feed.status_column],
        strict=True,
    ):
        try:
            parsed = peri_scribe.geo.parsing.fire_status_from(value)
        except ValueError:
            continue
        if parsed is status:
            object_ids.append(int(object_id))
    return sorted(object_ids)


def stored_status_literals(
    existing: geopandas.GeoDataFrame | None,
    feed: peri_scribe.sources.feed_types.Feed,
    status: peri_scribe.models.FireStatus,
) -> tuple[str, ...]:
    """Return SQL literals for the feed's stored raw values of *status*.

    The literals are the distinct raw status values already stored that classify as
    *status*, formatted for a SQL ``IN`` clause. An empty tuple means the store has
    never recorded the status, so callers should skip status-flip queries built from
    these literals.

    Args:
        existing: The latest stored feature per OBJECTID, or None.
        feed: The feed providing the status column.
        status: The status whose raw values are returned.

    Returns:
        The distinct SQL literals, in the order first encountered.
    """
    if existing is None or feed.status_column not in existing:
        return ()
    literals: list[str] = []
    seen: set[str] = set()
    for value in existing[feed.status_column]:
        try:
            parsed = peri_scribe.geo.parsing.fire_status_from(value)
        except ValueError:
            continue
        if parsed is not status:
            continue
        literal = sql_literal(value)
        if literal not in seen:
            seen.add(literal)
            literals.append(literal)
    return tuple(literals)


def where_clause_for(
    change_columns: tuple[str, ...],
    cutoff: datetime.datetime,
) -> str:
    """Return a where clause selecting features changed since *cutoff*.

    The clause selects features whose change timestamp is at or after *cutoff*,
    plus features with a missing change timestamp. The latter are included because
    a source may add or update features without populating the change columns, and a
    plain ``>=`` comparison would silently skip them. The caller deduplicates identical
    rows already stored, so re-fetching the null-timestamp features is safe.

    Args:
        change_columns: The feed's change timestamp columns.
        cutoff: The aware UTC cutoff timestamp.

    Returns:
        The SQL where clause for an ArcGIS query.
    """
    iso = cutoff.astimezone(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%S")
    return " OR ".join(
        f"{column} >= timestamp '{iso}Z' OR {column} IS NULL"
        for column in change_columns
    )


def latest_snapshot_path(
    directory: pathlib.Path,
    existing_source_files: list[peri_scribe.sources.snapshots.SourceFile],
) -> pathlib.Path | None:
    """Return the most recent snapshot path, or None when there are none.

    Args:
        directory: The directory holding the source's GeoPackage files.
        existing_source_files: The source's source files, in serial order.

    Returns:
        The path of the most recent snapshot, or None when there are none.
    """
    if not existing_source_files:
        return None
    return directory / existing_source_files[-1].relative_path
