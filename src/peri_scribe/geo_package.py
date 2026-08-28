"""Reading fire records and complex memberships from GeoPackage files.

Interprets each configured feed's layer into fire records, full source rows, and
complex memberships, and provides the attribute-value helpers the rest of the project
uses to read those rows.
"""

from __future__ import annotations

import dataclasses
import datetime
import pathlib
import re
import sqlite3
import typing

import geopandas
import pandas as pd
import us.states

import peri_scribe.exceptions
import peri_scribe.feed_types
import peri_scribe.feeds
import peri_scribe.models


if typing.TYPE_CHECKING:
    import shapely


def fire_status_from(value: object) -> peri_scribe.models.FireStatus | None:
    """Classify a feed's raw status value as active or inactive.

    Blank values (including None) are treated as missing and return None. Values
    that do not represent a known status raise an error, since they point at a
    misconfigured status column or unexpected data.

    Args:
        value: The raw status value from a feed.

    Returns:
        The corresponding fire status, or None when the value is blank.

    Raises:
        ValueError: If the value does not represent a known status.
    """
    if is_missing(value):
        return None
    normalized = str(value).strip().casefold()
    if normalized in {"1", "true", "active"}:
        return peri_scribe.models.FireStatus.ACTIVE
    if normalized in {"0", "false", "inactive"}:
        return peri_scribe.models.FireStatus.INACTIVE
    if normalized:
        message = f"Unknown fire status value: {value!r}"
        raise ValueError(message)
    return None


def is_missing(value: object) -> bool:
    """Return True when *value* is a missing (null) value.

    Pandas missing values are treated as missing, except for strings and bytes, which
    are never treated as missing here (an empty string is a present value). Values that
    pandas cannot truth-test (e.g. lists) are treated as present.

    Args:
        value: The value to test.

    Returns:
        True when *value* is missing.
    """
    if value is None:
        return True
    try:
        return bool(pd.isna(value)) and not isinstance(value, (str, bytes))
    except TypeError, ValueError:
        return False


def numeric_value(value: object) -> float | None:
    """Return *value* as a float, or None when it is missing or not numeric.

    Args:
        value: Any attribute value.

    Returns:
        The numeric value, or None when it cannot be interpreted as a number.
    """
    if is_missing(value):
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def geometries_describe_same_shape(
    left: shapely.Geometry | None,
    right: shapely.Geometry | None,
) -> bool:
    """Return whether two geometries describe the same shape.

    Shapes are compared topologically rather than byte-for-byte, so a source
    re-serializing an unchanged geometry (different vertex order, ring orientation,
    or ring type) still counts as the same shape. None and empty geometries each
    count as equal to themselves.

    Args:
        left: One geometry, or None.
        right: The other geometry, or None.

    Returns:
        True when the geometries are the same shape, or when both are None or empty.
    """
    if left is None or right is None:
        return left is None and right is None
    if left.is_empty or right.is_empty:
        return left.is_empty and right.is_empty
    return left.equals(right)


def normalize_identifier(value: object) -> str | None:
    """Normalize a raw identifier value, or return None when it is missing.

    Identifiers are case-folded and stripped of surrounding braces so that equal
    identifiers match regardless of formatting, e.g. ``{286B7F1D-8945-4A5D-9D81-
    5235C18AF1FE}`` and ``286b7f1d-8945-4a5d-9d81-5235c18af1fe``. Blank values
    (including None and NaN) are treated as missing and return None.

    Args:
        value: The raw identifier value from a feed.

    Returns:
        The normalized identifier, or None when the value is missing.
    """
    if is_missing(value):
        return None
    text = str(value).strip()
    if not text:
        return None
    return text.casefold().strip("{}")


def is_complex_child_from(value: object) -> bool:
    """Classify a feed's raw complex child value.

    Blank values (including None) are treated as false. Values that do not represent a
    known boolean raise an error, since they point at a misconfigured column or
    unexpected data.

    Args:
        value: The raw complex child value from a feed.

    Returns:
        True when the value represents a complex child.

    Raises:
        ValueError: If the value does not represent a known boolean.
    """
    if value is None:
        return False
    normalized = str(value).strip().casefold()
    if normalized in {"1", "true", "yes"}:
        return True
    if normalized in {"0", "false", "no"}:
        return False
    if normalized:
        message = f"Unknown complex child value: {value!r}"
        raise ValueError(message)
    return False


MISSION_TAIL_PATTERN = re.compile(r"^[a-z]?\d{2}[a-z]$")

MINIMUM_UNIT_CODE_LENGTH = 3
UNIT_PREFIX_TOKEN_COUNT = 2

MISSION_NAME_NOISE_TOKENS = frozenset({
    "updated",
    "update",
    "revised",
    "final",
    "copy",
})


def fire_name_from(value: object) -> str | None:
    """Return *value* as a non-blank fire name, or None when it is missing.

    Args:
        value: A raw fire name value.

    Returns:
        The stripped name, or None when *value* is missing or blank.
    """
    if is_missing(value):
        return None
    text = str(value).strip()
    return text or None


def mission_name_from(value: object) -> peri_scribe.models.MissionName | None:
    """Return the fire-name parts of a mapping mission code, or None.

    A mission code such as ``CA-LNU-RUMSEY-UPDATED-N40Y`` is parsed into the fire name
    (``rumsey-updated``) and a base name with mapping-revision markers removed
    (``rumsey``), so an updated re-mapping can still be matched to the original fire.
    The leading state and unit tokens and a trailing aircraft-tail token are dropped
    when present.

    Args:
        value: A raw mission code value.

    Returns:
        The mission name parts, or None when *value* is missing, blank, or does not
        name a fire.
    """
    if is_missing(value):
        return None
    text = str(value).strip()
    if not text:
        return None
    tokens = text.split("-")
    folded = [token.casefold() for token in tokens]
    start = 0
    if (
        len(folded) >= UNIT_PREFIX_TOKEN_COUNT
        and us.states.lookup(folded[0]) is not None
        and len(folded[1]) >= MINIMUM_UNIT_CODE_LENGTH
        and folded[1].isalnum()
    ):
        start = 2
    end = len(folded)
    if end > start and MISSION_TAIL_PATTERN.fullmatch(folded[end - 1]) is not None:
        end -= 1
    name_tokens = tokens[start:end]
    if not name_tokens:
        return None
    folded_name_tokens = folded[start:end]
    base_tokens = list(name_tokens)
    folded_base_tokens = list(folded_name_tokens)
    while folded_base_tokens and folded_base_tokens[-1] in MISSION_NAME_NOISE_TOKENS:
        folded_base_tokens.pop()
        base_tokens.pop()
    name = "-".join(name_tokens)
    base_name = "-".join(base_tokens) if base_tokens else name
    return peri_scribe.models.MissionName(name=name, base_name=base_name)


def observation_time_from(value: object) -> datetime.datetime | None:
    """Parse an observation timestamp into an aware UTC datetime.

    Blank values are treated as missing. Naive datetimes are assumed to be UTC.

    Args:
        value: The raw observation timestamp value.

    Returns:
        The parsed UTC datetime, or None when *value* is blank or not parseable.
    """
    if is_missing(value):
        return None
    parsed: datetime.datetime | None
    if isinstance(value, datetime.datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.datetime.fromisoformat(value.strip())
        except ValueError:
            parsed = None
    else:
        parsed = None
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=datetime.UTC)
    return parsed.astimezone(datetime.UTC)


def fire_record_from_row(
    row: pd.Series,
    feed: peri_scribe.feed_types.Feed,
    geometry: shapely.Geometry | None,
) -> peri_scribe.models.FireRecord | None:
    """Return the fire record described by *row*, or None when it has none.

    A row yields no record when its status is missing or when neither its name column
    nor its mission code names a fire. Every identifier, name spelling, and timestamp
    is read from the columns the feed configures.

    Args:
        row: One feature row from a GeoPackage layer.
        feed: The feed that names the row's columns.
        geometry: The row's shapely geometry.

    Returns:
        The fire record, or None when the row does not describe a fire.
    """
    status = fire_status_from(row[feed.status_column])
    if status is None:
        return None
    recorded_name = fire_name_from(row[feed.fire_name_column])
    mission = mission_name_from(
        row[feed.mission_column] if feed.mission_column is not None else None,
    )
    name = recorded_name or (mission.name if mission is not None else None)
    if name is None:
        return None
    identifiers = frozenset(
        normalized
        for column in feed.fire_identifier_columns
        if (normalized := normalize_identifier(row[column])) is not None
    )
    names = frozenset(
        peri_scribe.models.normalize_fire_name(candidate)
        for candidate in (
            recorded_name,
            mission.name if mission is not None else None,
            mission.base_name if mission is not None else None,
        )
        if candidate is not None
    )
    observed_at = (
        observation_time_from(row[feed.observation_time_column])
        if feed.observation_time_column is not None
        else None
    )
    mission_code = (
        fire_name_from(row[feed.mission_column])
        if feed.mission_column is not None
        else None
    )
    point_of_origin_state = (
        fire_name_from(row[feed.point_of_origin_state_column])
        if feed.point_of_origin_state_column is not None
        else None
    )
    point_of_origin_fips = (
        fire_name_from(row[feed.point_of_origin_fips_column])
        if feed.point_of_origin_fips_column is not None
        else None
    )
    return peri_scribe.models.FireRecord(
        name=name,
        status=status,
        identifiers=identifiers,
        names=names,
        geometry=geometry,
        observed_at=observed_at,
        mission=mission_code,
        point_of_origin_state=point_of_origin_state,
        point_of_origin_fips=point_of_origin_fips,
    )


def layers_by_feed(
    path: pathlib.Path,
) -> typing.Iterator[tuple[peri_scribe.feed_types.Feed, geopandas.GeoDataFrame]]:
    """Yield each layer of the GeoPackage at *path* with its configured feed.

    Args:
        path: The GeoPackage file to read.

    Yields:
        Each ``(feed, dataframe)`` pair, one per layer, in the order encountered.

    Raises:
        UnknownLayerError: If a layer does not correspond to a configured feed.
    """
    feeds_by_name = {feed.name: feed for feed in peri_scribe.feeds.FEEDS}
    for layer_name in geopandas.list_layers(path)["name"]:
        feed = feeds_by_name.get(layer_name)
        if feed is None:
            raise peri_scribe.exceptions.UnknownLayerError(layer_name, path)
        yield feed, geopandas.read_file(path, layer=feed.name)


@dataclasses.dataclass(frozen=True, kw_only=True)
class FireRowRecord:
    """One fire source row with its identifying record and full attributes.

    The record carries the fire's identifying fields; the attributes carry every
    non-geometry column so downstream consumers can bring the row's own fields along.
    """

    record: peri_scribe.models.FireRecord
    object_id: int | None
    source_name: str
    attributes: dict[str, object]


@dataclasses.dataclass(frozen=True, kw_only=True)
class GeopackageContents:
    """Every fire row and complex membership in one GeoPackage file."""

    rows: tuple[FireRowRecord, ...]
    memberships: tuple[peri_scribe.models.ComplexMembership, ...]


def complex_membership_columns(
    feed: peri_scribe.feed_types.Feed,
) -> tuple[str, str, str, str] | None:
    """Return the columns used to read a complex membership, or None.

    A feed that does not declare identifier and complex columns records no memberships.

    Args:
        feed: The feed whose layer is being read.

    Returns:
        The fire identifier, complex identifier, complex name, and complex child
        columns, or None when the feed records no memberships.
    """
    if (
        not feed.fire_identifier_columns
        or feed.complex_identifier_column is None
        or feed.complex_name_column is None
        or feed.is_complex_child_column is None
    ):
        return None
    return (
        feed.fire_identifier_columns[0],
        feed.complex_identifier_column,
        feed.complex_name_column,
        feed.is_complex_child_column,
    )


def complex_membership_from_row(
    row: pd.Series,
    columns: tuple[str, str, str, str],
) -> peri_scribe.models.ComplexMembership | None:
    """Return the complex membership *row* records, or None.

    Args:
        row: One feature row.
        columns: The fire identifier, complex identifier, complex name, and complex
            child columns.

    Returns:
        The membership, or None when the row is not a complex child with a complete
        identifier pair and name.
    """
    fire_identifier_column, complex_identifier_column, complex_name_column, child = (
        columns
    )
    if any(
        is_missing(row[column])
        for column in (
            fire_identifier_column,
            complex_identifier_column,
            complex_name_column,
            child,
        )
    ):
        return None
    if not is_complex_child_from(row[child]):
        return None
    fire_identifier = normalize_identifier(row[fire_identifier_column])
    complex_identifier = normalize_identifier(row[complex_identifier_column])
    complex_name = fire_name_from(row[complex_name_column])
    if fire_identifier is None or complex_identifier is None or complex_name is None:
        return None
    return peri_scribe.models.ComplexMembership(
        fire_identifier=fire_identifier,
        complex_identifier=complex_identifier,
        complex_name=complex_name,
    )


def object_id_from(row: pd.Series) -> int | None:
    """Return the row's OBJECTID, or None when it is missing.

    Args:
        row: One feature row.

    Returns:
        The row's OBJECTID as an integer, or None when the row has none.
    """
    if peri_scribe.models.OBJECT_ID_COLUMN_NAME not in row.index:
        return None
    value = row[peri_scribe.models.OBJECT_ID_COLUMN_NAME]
    if is_missing(value):
        return None
    return int(value)


def row_attributes(
    row: pd.Series,
    geometry_name: str,
) -> dict[str, object]:
    """Return the row's non-geometry columns as a dictionary.

    Args:
        row: One feature row.
        geometry_name: The row's geometry column name.

    Returns:
        The row's attribute columns, keyed by column name.
    """
    return {
        str(column): row[column] for column in row.index if str(column) != geometry_name
    }


def read_geopackage(path: pathlib.Path) -> GeopackageContents:
    """Read the fire rows and complex memberships of the GeoPackage at *path*.

    Each layer is read once and each of its rows is walked once, so a row that both
    names a fire and records a complex membership contributes to both results. The file
    is only read, never written.

    Args:
        path: The GeoPackage file to read.

    Returns:
        The fire rows and complex memberships, each in row order.
    """
    rows: list[FireRowRecord] = []
    memberships: list[peri_scribe.models.ComplexMembership] = []
    for feed, dataframe in layers_by_feed(path):
        geometry_name = str(dataframe.geometry.name)
        membership_columns = complex_membership_columns(feed)
        for index in range(len(dataframe)):
            row = dataframe.iloc[index]
            record = fire_record_from_row(row, feed, row[geometry_name])
            if record is not None:
                rows.append(
                    FireRowRecord(
                        record=record,
                        object_id=object_id_from(row),
                        source_name=feed.name,
                        attributes=row_attributes(row, geometry_name),
                    ),
                )
            if membership_columns is not None:
                membership = complex_membership_from_row(row, membership_columns)
                if membership is not None:
                    memberships.append(membership)
    return GeopackageContents(rows=tuple(rows), memberships=tuple(memberships))


def read_layer(
    path: pathlib.Path,
    layer_name: str,
) -> geopandas.GeoDataFrame:
    """Read *layer_name* from the GeoPackage at *path*.

    The file is only read, never written.

    Args:
        path: The GeoPackage file to read.
        layer_name: The layer to read.

    Returns:
        The layer's features as a GeoDataFrame.
    """
    return geopandas.read_file(path, layer=layer_name)


def read_layer_dataframe(
    path: pathlib.Path,
    feed: peri_scribe.feed_types.Feed,
) -> geopandas.GeoDataFrame:
    """Read the feed's layer from the GeoPackage at *path*.

    The file is only read, never written.

    Args:
        path: The GeoPackage file to read.
        feed: The feed whose layer is read.

    Returns:
        The layer's features as a GeoDataFrame.
    """
    return read_layer(path, feed.name)


def read_layer_chunks(
    path: pathlib.Path,
    layer_name: str | None,
    chunk_size: int,
) -> typing.Iterator[geopandas.GeoDataFrame]:
    """Yield *layer_name* from *path* in chunks of at most *chunk_size* rows.

    Each chunk is a bounded read of at most *chunk_size* features, so a layer of any
    size can be processed without loading the whole layer into memory. The final chunk
    may be smaller; a layer with no features yields nothing. When *layer_name* is None
    the file's default layer is read, which is how a single-layer file such as a
    shapefile or file geodatabase is read. The file is only read, never written.

    GeoPackage layers are paginated by their ``fid`` primary key rather than with
    ``skip_features``, because skip-based pagination rescans the layer from the start
    for every chunk and becomes quadratic over the whole read. Other file kinds fall
    back to skip-based pagination.

    Args:
        path: The vector data file to read.
        layer_name: The layer to read, or None for the file's default layer.
        chunk_size: The maximum number of features per chunk.

    Yields:
        Each chunk of the layer's features, in row order.
    """
    if path.suffix.lower() == ".gpkg" and layer_name is not None:
        yield from _read_gpkg_layer_chunks(path, layer_name, chunk_size)
        return
    yield from _read_skip_layer_chunks(path, layer_name, chunk_size)


def _read_skip_layer_chunks(
    path: pathlib.Path,
    layer_name: str | None,
    chunk_size: int,
) -> typing.Iterator[geopandas.GeoDataFrame]:
    """Yield chunks using ``skip_features``, which rescans from the start each time.

    Yields:
        Each chunk of the layer's features, in row order.
    """
    offset = 0
    while True:
        dataframe = geopandas.read_file(
            path,
            layer=layer_name,
            max_features=chunk_size,
            skip_features=offset,
        )
        if dataframe.empty:
            return
        yield dataframe
        offset += len(dataframe)


def _read_gpkg_layer_chunks(
    path: pathlib.Path,
    layer_name: str,
    chunk_size: int,
) -> typing.Iterator[geopandas.GeoDataFrame]:
    """Yield chunks of a GeoPackage layer paginated by its ``fid`` primary key.

    Each chunk is ``where="fid > lower AND fid <= upper"`` for fid boundaries spaced
    ``chunk_size`` apart, so every chunk is an indexed range read of constant cost
    rather than a rescan. Boundaries are taken at ``fid % chunk_size == 0``; for the
    dense fids this project writes, that yields chunks of exactly ``chunk_size`` rows in
    fid order, matching the skip-based contract.

    Yields:
        Each chunk of the layer's features, in fid order.
    """
    connection = sqlite3.connect(path)
    try:
        minimum_fid = connection.execute(
            f'SELECT MIN(fid) FROM "{layer_name}"',
        ).fetchone()[0]
        boundaries = [
            row[0]
            for row in connection.execute(
                f'SELECT fid FROM "{layer_name}" '
                f"WHERE fid % {chunk_size} = 0 ORDER BY fid",
            )
        ]
    finally:
        connection.close()
    if minimum_fid is None:
        return
    lower = minimum_fid - 1
    for upper in boundaries:
        dataframe = geopandas.read_file(
            path,
            layer=layer_name,
            where=f"fid > {lower} AND fid <= {upper}",
        )
        if not dataframe.empty:
            yield dataframe
        lower = upper
    dataframe = geopandas.read_file(
        path,
        layer=layer_name,
        where=f"fid > {lower}",
    )
    if not dataframe.empty:
        yield dataframe
