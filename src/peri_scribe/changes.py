"""Detecting which fetched features are new or changed since the last snapshot."""

from __future__ import annotations

import datetime
import pathlib
import typing

import pandas as pd

import peri_scribe.feed_types
import peri_scribe.geo_package
import peri_scribe.models
import peri_scribe.snapshots
import peri_scribe.units


if typing.TYPE_CHECKING:
    import geopandas
    import shapely


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
    if not dataframes:
        return None
    combined = typing.cast(
        "geopandas.GeoDataFrame",
        pd.concat(dataframes, ignore_index=True),
    )
    if peri_scribe.models.OBJECT_ID_COLUMN_NAME not in combined.columns:
        return None
    return combined[
        ~combined.duplicated(
            subset=[peri_scribe.models.OBJECT_ID_COLUMN_NAME],
            keep="last",
        )
    ]


def latest_modified_datetime(
    existing: geopandas.GeoDataFrame | None,
    feed: peri_scribe.feed_types.Feed,
) -> datetime.datetime | None:
    """Return the latest modified timestamp across the stored features.

    Args:
        existing: The latest stored feature per OBJECTID, or None.
        feed: The feed providing the modified timestamp column.

    Returns:
        The latest modified UTC datetime, or None when none can be found.
    """
    if existing is None or existing.empty:
        return None
    modified_column = feed.modified_column
    if modified_column is None or modified_column not in existing.columns:
        return None
    values = [modified_datetime_from(value) for value in existing[modified_column]]
    latest = [value for value in values if value is not None]
    if not latest:
        return None
    return max(latest)


def incremental_cutoff(
    existing: geopandas.GeoDataFrame | None,
    feed: peri_scribe.feed_types.Feed,
) -> datetime.datetime:
    """Return the cutoff for an incremental fetch.

    The cutoff is the latest stored modified timestamp minus `OVERLAP`. When no stored
    timestamp can be found, the Unix epoch is used so the query returns every feature
    for deduplication to filter.

    Args:
        existing: The latest stored feature per OBJECTID, or None.
        feed: The feed providing the modified timestamp column.

    Returns:
        The aware UTC cutoff timestamp.
    """
    latest = latest_modified_datetime(existing, feed)
    if latest is None:
        return datetime.datetime.fromtimestamp(0, tz=datetime.UTC)
    return latest - OVERLAP


def where_clause_for(
    modified_column: str,
    cutoff: datetime.datetime,
) -> str:
    """Return a where clause selecting features modified at or after *cutoff*.

    Args:
        modified_column: The feed's modified timestamp column.
        cutoff: The aware UTC cutoff timestamp.

    Returns:
        The SQL where clause for an ArcGIS query.
    """
    iso = cutoff.astimezone(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%S")
    return f"{modified_column} >= timestamp '{iso}Z'"


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


def feature_signature(
    values: dict[str, object],
    columns: list[str],
    geometry: object,
) -> tuple[tuple[object, ...], bytes | None]:
    """Return the content signature of a single feature row.

    The signature combines the row's normalized attribute values with the well-known
    binary of its geometry, so two features are identical only when both their
    attributes and their geometry match.

    Args:
        values: The row's attribute values, keyed by column name.
        columns: The attribute columns to include in the signature.
        geometry: The row's geometry, or None when the feature has none.

    Returns:
        The feature's content signature.
    """
    attributes = tuple(normalized_attribute_value(values[column]) for column in columns)
    shapely_geometry = typing.cast("shapely.Geometry | None", geometry)
    geometry_key = shapely_geometry.wkb if shapely_geometry is not None else None
    return (attributes, geometry_key)


def feature_signatures(
    dataframe: geopandas.GeoDataFrame,
    columns: list[str],
) -> dict[int, tuple[tuple[object, ...], bytes | None]]:
    """Return each feature's content signature, keyed by OBJECTID.

    The signature combines the feature's normalized attribute values with the well-known
    binary of its geometry, so two features are identical only when both their
    attributes and their geometry match.

    Args:
        dataframe: The features to sign.
        columns: The attribute columns to include in each signature.

    Returns:
        The signatures, keyed by OBJECTID.
    """
    geometry_name = dataframe.geometry.name
    signatures: dict[int, tuple[tuple[object, ...], bytes | None]] = {}
    for row in dataframe.itertuples(index=False, name=None):
        values = dict(zip(dataframe.columns, row, strict=True))
        object_id = int(values[peri_scribe.models.OBJECT_ID_COLUMN_NAME])
        signatures[object_id] = feature_signature(
            values,
            columns,
            values[geometry_name],
        )
    return signatures


def drop_features_already_present(
    new_dataframe: geopandas.GeoDataFrame,
    existing_dataframe: geopandas.GeoDataFrame | None,
) -> geopandas.GeoDataFrame:
    """Drop fetched features whose content is already stored identically.

    A feature is kept when its OBJECTID is new, or when its stored content differs from
    the freshly fetched content. Features with a matching OBJECTID and identical
    attributes and geometry are dropped.

    Args:
        new_dataframe: The newly fetched features.
        existing_dataframe: The latest stored feature per OBJECTID, or None.

    Returns:
        The features that are new or changed.
    """
    if existing_dataframe is None or existing_dataframe.empty:
        return new_dataframe
    columns = attribute_columns(new_dataframe, existing_dataframe)
    existing_signatures = feature_signatures(existing_dataframe, columns)
    geometry_name = new_dataframe.geometry.name
    keep: list[bool] = []
    for row in new_dataframe.itertuples(index=False, name=None):
        values = dict(zip(new_dataframe.columns, row, strict=True))
        object_id = int(values[peri_scribe.models.OBJECT_ID_COLUMN_NAME])
        keep.append(
            existing_signatures.get(object_id)
            != feature_signature(values, columns, values[geometry_name]),
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
