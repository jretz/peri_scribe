"""Detecting which fetched features are new or changed since the last snapshot."""

from __future__ import annotations

import contextlib
import datetime
import pathlib
import typing

import pandas as pd
import structlog

import peri_scribe.feed_types
import peri_scribe.geo_package
import peri_scribe.models
import peri_scribe.output
import peri_scribe.snapshots
import peri_scribe.units


if typing.TYPE_CHECKING:
    import geopandas
    import shapely


logger = structlog.get_logger()


# When fetching only changed features, the cutoff for the query is moved back by this
# amount so that recently edited features are re-fetched and re-checked rather than
# missed because of clock skew or in-flight edits.
OVERLAP = datetime.timedelta(minutes=5)


def parse_iso_datetime(text: str) -> datetime.datetime | None:
    """Parse an ISO-8601 datetime string, or return None when invalid.

    Args:
        text: The datetime string to parse.

    Returns:
        The parsed datetime, or None when *text* is blank or invalid.
    """
    try:
        return datetime.datetime.fromisoformat(text.strip())
    except ValueError:
        return None


def modified_datetime_from(value: object) -> datetime.datetime | None:
    """Parse a modified timestamp value into an aware UTC datetime.

    ArcGIS date fields arrive as epoch milliseconds in query responses and as ISO-8601
    strings or pandas timestamps when read back from a GeoPackage. Blank values are
    treated as missing.

    Args:
        value: The raw modified timestamp value.

    Returns:
        The parsed UTC datetime, or None when *value* is blank or not parseable.
    """
    if peri_scribe.geo_package.is_missing(value):
        return None

    parsed: datetime.datetime | None
    if isinstance(value, datetime.datetime):
        parsed = value
    elif isinstance(value, str):
        parsed = parse_iso_datetime(value)
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        parsed = datetime.datetime.fromtimestamp(
            value / peri_scribe.units.MILLISECONDS_PER_SECOND,
            tz=datetime.UTC,
        )
    else:
        parsed = None

    if parsed is None:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=datetime.UTC)
    return parsed.astimezone(datetime.UTC)


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
    feed: peri_scribe.feed_types.Feed,
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
        peri_scribe.geo_package.read_layer_dataframe(
            directory / source_file.relative_path,
            feed,
        )
        for source_file in peri_scribe.snapshots.existing_source_files(directory)
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
    source_files = peri_scribe.snapshots.existing_source_files(directory)
    if not source_files:
        return None
    return source_files[-1].serial_number


def read_current_features(
    directory: pathlib.Path,
    feed: peri_scribe.feed_types.Feed,
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
    state_files = peri_scribe.snapshots.current_state_file_paths(
        directory,
        feed.name,
    )
    if state_files:
        state_serial_number, state_path = state_files[-1]
        newest_serial_number = current_state_serial_number(directory)
        if (
            newest_serial_number is not None
            and state_serial_number == newest_serial_number
        ):
            try:
                return peri_scribe.geo_package.read_layer_dataframe(
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
    feed: peri_scribe.feed_types.Feed,
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
    state_files = peri_scribe.snapshots.current_state_file_paths(
        directory,
        feed.name,
    )
    base: geopandas.GeoDataFrame | None = None
    if state_files:
        _state_serial_number, state_path = state_files[-1]
        try:
            base = peri_scribe.geo_package.read_layer_dataframe(
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
    state_path = peri_scribe.snapshots.current_state_path(
        directory,
        feed.name,
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
    feed: peri_scribe.feed_types.Feed,
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
            parsed = peri_scribe.geo_package.fire_status_from(value)
        except ValueError:
            continue
        if parsed is status:
            object_ids.append(int(object_id))
    return sorted(object_ids)


def stored_status_literals(
    existing: geopandas.GeoDataFrame | None,
    feed: peri_scribe.feed_types.Feed,
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
            parsed = peri_scribe.geo_package.fire_status_from(value)
        except ValueError:
            continue
        if parsed is not status:
            continue
        literal = sql_literal(value)
        if literal not in seen:
            seen.add(literal)
            literals.append(literal)
    return tuple(literals)


def latest_modified_datetime(
    existing: geopandas.GeoDataFrame | None,
    feed: peri_scribe.feed_types.Feed,
) -> datetime.datetime | None:
    """Return the latest change timestamp across the stored features.

    Every change column the feed declares is considered, since a source may update one
    timestamp (for example a polygon date) without moving another (for example the
    attribute modified time).

    Args:
        existing: The latest stored feature per OBJECTID, or None.
        feed: The feed providing the change timestamp columns.

    Returns:
        The latest change UTC datetime, or None when none can be found.
    """
    if existing is None or existing.empty:
        return None
    latest: list[datetime.datetime] = []
    for column in feed.change_columns:
        if column not in existing.columns:
            continue
        for value in existing[column]:
            parsed = modified_datetime_from(value)
            if parsed is not None:
                latest.append(parsed)
    if not latest:
        return None
    return max(latest)


def incremental_cutoff(
    existing: geopandas.GeoDataFrame | None,
    feed: peri_scribe.feed_types.Feed,
) -> datetime.datetime:
    """Return the cutoff for an incremental fetch.

    The cutoff is the latest stored change timestamp minus ``OVERLAP``. When no stored
    timestamp can be found, the Unix epoch is used so the query returns every feature
    for deduplication to filter.

    Args:
        existing: The latest stored feature per OBJECTID, or None.
        feed: The feed providing the change timestamp columns.

    Returns:
        The aware UTC cutoff timestamp.
    """
    latest = latest_modified_datetime(existing, feed)
    if latest is None:
        return datetime.datetime.fromtimestamp(0, tz=datetime.UTC)
    return latest - OVERLAP


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


def normalized_attribute_value(value: object) -> object:
    """Return *value* with missing and sub-second timestamps normalized.

    Pandas missing values are mapped to None so equal rows compare equal, and datetimes
    are truncated to whole seconds so the server's inconsistent fractional-second
    serialization does not make identical rows look different.

    Args:
        value: An attribute value from a feature row.

    Returns:
        The comparable form of *value*.
    """
    if peri_scribe.geo_package.is_missing(value):
        return None
    if isinstance(value, datetime.datetime):
        return value.replace(microsecond=0)
    return value


def attribute_columns(
    new_dataframe: geopandas.GeoDataFrame,
    existing_dataframe: geopandas.GeoDataFrame,
) -> list[str]:
    """Return the attribute columns shared by two feature dataframes.

    The geometry column of each dataframe is excluded. Columns are ordered as they
    appear in *new_dataframe* so that signatures from both dataframes line up.

    Args:
        new_dataframe: The newly fetched features.
        existing_dataframe: The stored features to compare against.

    Returns:
        The shared attribute column names.
    """
    existing_columns = set(existing_dataframe.columns) - {
        existing_dataframe.geometry.name,
    }
    return [
        column
        for column in new_dataframe.columns
        if column != new_dataframe.geometry.name and column in existing_columns
    ]


def features_are_identical(
    values: typing.Mapping[str, object],
    geometry: object,
    existing_values: typing.Mapping[str, object],
    existing_geometry: object,
    columns: list[str],
) -> bool:
    """Return whether two feature rows describe the same feature.

    Attributes must match after normalization, and the geometries must describe the
    same shape. Comparing shapes rather than raw coordinates lets a source re-publish
    an unchanged feature (different vertex order, ring orientation, or ring type)
    without making it look new or changed. The geometries are passed separately
    because the two frames may name their geometry columns differently.

    Args:
        values: The freshly fetched row's values, keyed by column name.
        geometry: The freshly fetched row's geometry, or None.
        existing_values: The stored row's values, keyed by column name.
        existing_geometry: The stored row's geometry, or None.
        columns: The attribute columns that must match.

    Returns:
        True when the rows' attributes and shapes match.
    """
    for column in columns:
        if normalized_attribute_value(values[column]) != normalized_attribute_value(
            existing_values[column],
        ):
            return False
    return peri_scribe.geo_package.geometries_describe_same_shape(
        typing.cast("shapely.Geometry | None", geometry),
        typing.cast("shapely.Geometry | None", existing_geometry),
    )


def drop_features_already_present(
    new_dataframe: geopandas.GeoDataFrame,
    existing_dataframe: geopandas.GeoDataFrame | None,
) -> geopandas.GeoDataFrame:
    """Drop fetched features whose content is already stored identically.

    A feature is kept when its OBJECTID is new, or when its stored content differs
    from the freshly fetched content. Features with a matching OBJECTID and identical
    attributes and geometry are dropped, where geometry counts as identical when the
    stored and fetched shapes describe the same area.

    Args:
        new_dataframe: The newly fetched features.
        existing_dataframe: The latest stored feature per OBJECTID, or None.

    Returns:
        The features that are new or changed.
    """
    if existing_dataframe is None or existing_dataframe.empty:
        return new_dataframe
    columns = attribute_columns(new_dataframe, existing_dataframe)
    new_geometry_column = str(new_dataframe.geometry.name)
    existing_geometry_column = str(existing_dataframe.geometry.name)
    existing_by_object_id: dict[int, tuple[dict[str, object], object]] = {}
    for row in existing_dataframe.itertuples(index=False, name=None):
        values = dict(zip(existing_dataframe.columns, row, strict=True))
        existing_by_object_id[int(values[peri_scribe.models.OBJECT_ID_COLUMN_NAME])] = (
            values,
            values[existing_geometry_column],
        )
    keep: list[bool] = []
    for row in new_dataframe.itertuples(index=False, name=None):
        values = dict(zip(new_dataframe.columns, row, strict=True))
        object_id = int(values[peri_scribe.models.OBJECT_ID_COLUMN_NAME])
        existing = existing_by_object_id.get(object_id)
        keep.append(
            existing is None
            or not features_are_identical(
                values,
                values[new_geometry_column],
                existing[0],
                existing[1],
                columns,
            ),
        )
    return new_dataframe[keep].reset_index(drop=True)


def latest_snapshot_path(
    directory: pathlib.Path,
    existing_source_files: list[peri_scribe.snapshots.SourceFile],
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
