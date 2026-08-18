"""GeoDataFrame construction and query helpers for peri_scribe.

Converts ArcGIS FeatureSet query results into GeoDataFrames in the layer's native
spatial reference, provides retry-aware querying for ArcGIS feature layers, and
reads fires and complex memberships from GeoPackage files.
"""

from __future__ import annotations

import datetime
import pathlib
import re
import typing

import geopandas
import pandas as pd
import pyproj
import structlog

import peri_scribe.exceptions
import peri_scribe.feed_types
import peri_scribe.models
import peri_scribe.retry
import peri_scribe.spatial_reference


if typing.TYPE_CHECKING:
    import arcgis.features
    import shapely


logger = structlog.get_logger()


def extract_geometries(
    dataframe: pd.DataFrame,
) -> tuple[pd.DataFrame, list[shapely.Geometry | None], str | None]:
    """Separate a feature dataframe's SHAPE column from its attributes.

    Returns:
        The dataframe with the SHAPE column removed, the shapely geometries of its
        features (None where a feature has no geometry), and a warning to report when
        the dataframe has no geometry column.
    """
    if "SHAPE" not in dataframe.columns:
        return (
            dataframe,
            [None] * len(dataframe),
            (
                "  warning: all features lack geometry; "
                "writing the layer with NULL geometry"
            ),
        )
    return (
        dataframe.drop(columns=["SHAPE"]),
        list(dataframe["SHAPE"].geom.as_shapely),
        None,
    )


def geo_data_frame_from(
    dataframe: pd.DataFrame,
    shapely_geometries: list[shapely.Geometry | None],
    spatial_reference_id: int,
) -> geopandas.GeoDataFrame:
    """Build the output GeoDataFrame with its geometry column renamed.

    Returns:
        The GeoDataFrame with its geometry column renamed.
    """
    geo_data_frame = geopandas.GeoDataFrame(
        dataframe,
        geometry=shapely_geometries,
        crs=pyproj.CRS.from_epsg(spatial_reference_id),
    )
    return typing.cast(
        "geopandas.GeoDataFrame",
        geo_data_frame.rename_geometry(peri_scribe.models.GEOMETRY_COLUMN_NAME),
    )


def dataframe_for_layer(
    feed: peri_scribe.feed_types.Feed,
    layer: arcgis.features.FeatureLayer,
    feature_set: arcgis.features.FeatureSet,
) -> geopandas.GeoDataFrame:
    """Convert a query result to a GeoDataFrame in the layer's native CRS.

    Returns:
        The GeoDataFrame for the feed's features.

    Raises:
        NoFeaturesError: If the feed returns no features.
    """
    features = feature_set.features
    if not features:
        message = f"Feed {feed.name} returned no features; no output was written"
        raise peri_scribe.exceptions.NoFeaturesError(message)
    dataframe = feature_set.sdf
    dataframe, shapely_geometries, geometry_warning = extract_geometries(dataframe)
    if geometry_warning is not None:
        logger.warning(geometry_warning)
    bounds = peri_scribe.spatial_reference.bounds_of(shapely_geometries)
    spatial_reference_id = peri_scribe.spatial_reference.choose_spatial_reference_id(
        layer,
        feature_set,
        bounds,
    )
    return geo_data_frame_from(dataframe, shapely_geometries, spatial_reference_id)


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

STATE_CODE_LENGTH = 2
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
        and len(folded[0]) == STATE_CODE_LENGTH
        and folded[0].isalpha()
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


def fire_records(
    path: pathlib.Path,
) -> typing.Generator[peri_scribe.models.FireRecord]:
    """Yield the fire records in every layer of the GeoPackage at *path*.

    The GeoPackage is only read, never written. Every layer must correspond to a
    configured feed, which says which columns hold each fire's name, status,
    identifiers, mission, and observation time. Rows without a status are omitted; rows
    whose name is blank are named from the mission code when one is available, and rows
    with no name at all are omitted.

    Args:
        path: The GeoPackage file to read.

    Yields:
        The fire records found in the file, one per row, in the order encountered.

    Raises:
        UnknownLayerError: If a layer does not correspond to a configured feed.
    """
    feeds_by_name = {feed.name: feed for feed in peri_scribe.models.FEEDS}
    for layer_name in geopandas.list_layers(path)["name"]:
        feed = feeds_by_name.get(layer_name)
        if feed is None:
            raise peri_scribe.exceptions.UnknownLayerError(layer_name, path)
        dataframe = geopandas.read_file(path, layer=feed.name)
        for index in range(len(dataframe)):
            row = dataframe.iloc[index]
            status = fire_status_from(row[feed.status_column])
            if status is None:
                continue
            recorded_name = fire_name_from(row[feed.fire_name_column])
            mission = mission_name_from(
                row[feed.mission_column]
                if feed.mission_column is not None
                else None,
            )
            name = recorded_name or (
                mission.name if mission is not None else None
            )
            if name is None:
                continue
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
            yield peri_scribe.models.FireRecord(
                name=name,
                status=status,
                identifiers=identifiers,
                names=names,
                geometry=dataframe.geometry.iloc[index],
                observed_at=observed_at,
            )


def complex_memberships(
    path: pathlib.Path,
) -> typing.Generator[peri_scribe.models.ComplexMembership]:
    """Yield the complex memberships in every layer of the GeoPackage at *path*.

    The GeoPackage is only read, never written. Only layers whose feed declares complex
    columns are considered. Rows that are not marked as complex children, or that lack a
    fire identifier, complex identifier, or complex name, are omitted.

    Args:
        path: The GeoPackage file to read.

    Yields:
        The complex memberships found in the file, one per row, in the order
        encountered.

    Raises:
        UnknownLayerError: If a layer does not correspond to a configured feed.
    """
    feeds_by_name = {feed.name: feed for feed in peri_scribe.models.FEEDS}
    for layer_name in geopandas.list_layers(path)["name"]:
        feed = feeds_by_name.get(layer_name)
        if feed is None:
            raise peri_scribe.exceptions.UnknownLayerError(layer_name, path)
        if (
            not feed.fire_identifier_columns
            or feed.complex_identifier_column is None
            or feed.complex_name_column is None
            or feed.is_complex_child_column is None
        ):
            continue
        columns = [
            feed.fire_identifier_columns[0],
            feed.complex_identifier_column,
            feed.complex_name_column,
            feed.is_complex_child_column,
        ]
        dataframe = geopandas.read_file(path, layer=feed.name)
        rows = dataframe[columns].dropna()
        for (
            raw_fire_identifier,
            raw_complex_identifier,
            raw_complex_name,
            raw_is_complex_child,
        ) in rows.itertuples(index=False, name=None):
            if not is_complex_child_from(raw_is_complex_child):
                continue
            fire_identifier = normalize_identifier(raw_fire_identifier)
            complex_identifier = normalize_identifier(raw_complex_identifier)
            complex_name = str(raw_complex_name).strip()
            if (
                fire_identifier is None
                or complex_identifier is None
                or not complex_name
            ):
                continue
            yield peri_scribe.models.ComplexMembership(
                fire_identifier=fire_identifier,
                complex_identifier=complex_identifier,
                complex_name=complex_name,
            )


def query_with_retry(
    feed_name: str,
    layer: arcgis.features.FeatureLayer,
    *,
    max_retries: int = peri_scribe.retry.DEFAULT_MAX_RETRIES,
    parameters: dict[str, typing.Any] | None = None,
) -> arcgis.features.FeatureSet:
    """Query *layer* for features, retrying on transient and rate-limit errors.

    Args:
        feed_name: Human-readable feed identifier for log messages.
        layer: The FeatureLayer to query.
        max_retries: Maximum number of retries before giving up.
        parameters: Keyword arguments forwarded to ``layer.query``.

    Returns:
        The FeatureSet returned by a successful query.
    """
    query_parameters = {} if parameters is None else parameters
    return peri_scribe.retry.run_with_retry(
        feed_name,
        lambda: layer.query(**query_parameters),
        max_retries=max_retries,
    )


def query_object_ids_with_retry(
    feed_name: str,
    layer: arcgis.features.FeatureLayer,
    *,
    where: str,
    max_retries: int = peri_scribe.retry.DEFAULT_MAX_RETRIES,
) -> list[int]:
    """Return the OBJECTIDs of the features in *layer* matching *where*.

    The query requests only identifiers, so the response is a few bytes for most layers.
    An empty list means no features matched.

    Args:
        feed_name: Human-readable feed identifier for log messages.
        layer: The FeatureLayer to query.
        where: The SQL where clause selecting the features.
        max_retries: Maximum number of retries before giving up.

    Returns:
        The OBJECTIDs of the matching features.

    Raises:
        NoFeaturesError: If the service does not return an object id list.
    """
    result = peri_scribe.retry.run_with_retry(
        feed_name,
        lambda: layer.query(where=where, return_ids_only=True),
        max_retries=max_retries,
    )
    if not isinstance(result, dict) or "objectIds" not in result:
        message = f"Feed {feed_name} returned no object ids"
        raise peri_scribe.exceptions.NoFeaturesError(message)
    return [int(object_id) for object_id in result["objectIds"]]


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
    return geopandas.read_file(path, layer=feed.name)
