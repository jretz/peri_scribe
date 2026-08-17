"""GeoDataFrame construction and query helpers for peri_scribe.

Converts ArcGIS FeatureSet query results into GeoDataFrames in the layer's native
spatial reference, provides retry-aware querying for ArcGIS feature layers, and
reads fires and complex memberships from GeoPackage files.
"""

from __future__ import annotations

import pathlib
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
    if value is None:
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


def fire_names(
    path: pathlib.Path,
) -> typing.Generator[peri_scribe.models.Fire]:
    """Yield the fires in every layer of the GeoPackage at *path*.

    The GeoPackage is only read, never written. Every layer must correspond to a
    configured feed, which says which columns hold each fire's name, status, and
    identifier. Rows without a name or without a status are omitted; rows without an
    identifier are still yielded, with a None identifier.

    Args:
        path: The GeoPackage file to read.

    Yields:
        The fires found in the file, one per row, in the order encountered.

    Raises:
        UnknownLayerError: If a layer does not correspond to a configured feed.
    """
    feeds_by_name = {feed.name: feed for feed in peri_scribe.models.FEEDS}
    for layer_name in geopandas.list_layers(path)["name"]:
        feed = feeds_by_name.get(layer_name)
        if feed is None:
            raise peri_scribe.exceptions.UnknownLayerError(layer_name, path)
        dataframe = geopandas.read_file(path, layer=feed.name)
        rows = dataframe[[feed.fire_name_column, feed.status_column]].dropna()
        identifier_column = feed.fire_identifier_column
        if identifier_column is None:
            identifiers: typing.Sequence[object] = [None] * len(rows)
        else:
            identifiers = dataframe.loc[rows.index, identifier_column]
        for (name, raw_status), raw_identifier in zip(
            rows.itertuples(index=False, name=None),
            identifiers,
            strict=True,
        ):
            fire_name = str(name)
            status = fire_status_from(raw_status)
            if fire_name.strip() and status is not None:
                yield peri_scribe.models.Fire(
                    name=fire_name,
                    status=status,
                    identifier=normalize_identifier(raw_identifier),
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
            feed.fire_identifier_column is None
            or feed.complex_identifier_column is None
            or feed.complex_name_column is None
            or feed.is_complex_child_column is None
        ):
            continue
        columns = [
            feed.fire_identifier_column,
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
