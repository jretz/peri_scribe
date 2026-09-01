"""Detecting which fetched features are new or changed since the last snapshot."""

from __future__ import annotations

import datetime
import typing

import peri_scribe.geo.parsing
import peri_scribe.models
import peri_scribe.sources.feed_types
import peri_scribe.units


if typing.TYPE_CHECKING:
    import geopandas
    import shapely

OVERLAP = datetime.timedelta(minutes=5)


def parse_iso_datetime(text: str) -> datetime.datetime | None:
    """Parse an ISO-8601 datetime string, or return None when invalid.

    Args:
        text: The datetime string to parse.

    Returns:
        The parsed datetime, or None when *text* is blank or invalid.

    Examples:
        >>> parse_iso_datetime("2025-08-05T20:30:00")
        datetime.datetime(2025, 8, 5, 20, 30)

        >>> parse_iso_datetime("not a date") is None
        True
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

    Examples:
        >>> modified_datetime_from(0).isoformat()
        '1970-01-01T00:00:00+00:00'

        >>> modified_datetime_from("") is None
        True
    """
    if peri_scribe.geo.parsing.is_missing(value):
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


def latest_modified_datetime(
    existing: geopandas.GeoDataFrame | None,
    feed: peri_scribe.sources.feed_types.Feed,
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
    feed: peri_scribe.sources.feed_types.Feed,
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
    if peri_scribe.geo.parsing.is_missing(value):
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
    return peri_scribe.geo.parsing.geometries_describe_same_shape(
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
