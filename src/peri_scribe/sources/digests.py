"""Digest comparisons for detecting whether stored external data changed."""

from __future__ import annotations

import datetime
import hashlib
import math
import pathlib

import geopandas
import pandas as pd
import shapely
import structlog


logger = structlog.get_logger()


def snapshot_matches(
    dataframe: geopandas.GeoDataFrame,
    snapshot_path: pathlib.Path,
    layer_name: str,
) -> bool:
    """Return whether *dataframe* holds the same features as *snapshot_path*.

    The comparison uses each frame's content digest, so the features may appear in any
    row order. An unreadable snapshot is treated as a mismatch, so a new snapshot is
    written rather than history being lost.

    Args:
        dataframe: The freshly fetched features.
        snapshot_path: The latest stored snapshot.
        layer_name: The snapshot's layer name.

    Returns:
        True when the snapshot holds the same features as *dataframe*.
    """
    try:
        stored = geopandas.read_file(snapshot_path, layer=layer_name)
    except (OSError, RuntimeError, ValueError) as error:
        logger.warning(
            "Failed to read external source snapshot",
            path=snapshot_path,
            error=str(error),
        )
        return False
    return dataframe_digest(dataframe) == dataframe_digest(stored)


def stored_geopackage_digest(
    path: pathlib.Path,
    layer_name: str,
) -> str | None:
    """Return the content digest of the GeoPackage at *path*, or None.

    A file that is missing or cannot be read has no digest; a readable file digests the
    same as its contents, so two files holding the same features in a different row
    order digest alike.

    Args:
        path: The GeoPackage to digest.
        layer_name: The GeoPackage layer whose contents are digested.

    Returns:
        The digest of the layer's contents, or None when the file is missing or
        unreadable.
    """
    try:
        stored = geopandas.read_file(path, layer=layer_name)
    except OSError, RuntimeError, ValueError:
        return None
    return dataframe_digest(stored)


def dataframe_digest(dataframe: geopandas.GeoDataFrame) -> str:
    """Return an order-independent content digest for *dataframe*.

    Every row contributes a digest of its attributes and geometry, and the row digests
    are hashed in sorted order, so two dataframes holding the same features in a
    different row order digest alike. Missing values of any kind (None, pandas NA or
    NaT, NaN) digest alike, so a value that a GeoPackage round-trip stores as NaN rather
    than None does not count as a change.

    Args:
        dataframe: The GeoDataFrame to digest.

    Returns:
        The SHA-256 digest of the dataframe's content.
    """
    geometry_column = dataframe.geometry.name
    attribute_columns = sorted(
        column for column in dataframe.columns if column != geometry_column
    )
    row_digests: list[str] = []
    for _index, row in dataframe.iterrows():
        hasher = hashlib.sha256()
        for column in attribute_columns:
            hasher.update(digest_value(row[column]))
        geometry = row[geometry_column]
        hasher.update(geometry.wkb if geometry is not None else b"m")
        row_digests.append(hasher.hexdigest())
    row_digests.sort()
    final_hasher = hashlib.sha256()
    for digest in row_digests:
        final_hasher.update(digest.encode("ascii"))
    return final_hasher.hexdigest()


def digest_value(value: object) -> bytes:
    """Return a digest fragment for one attribute *value*.

    Missing values of any flavor (None, pandas NA or NaT, NaN) share a fragment, so a
    value stored by a GeoPackage as NaN rather than None does not count as a change. The
    remaining fragments tag the value's kind, keeping values of different types from
    digesting alike.

    Args:
        value: The attribute value to digest.

    Returns:
        The digest fragment for *value*.
    """
    if (
        value is None
        or value is pd.NA
        or value is pd.NaT
        or (isinstance(value, float) and math.isnan(value))
    ):
        fragment = b"m"
    elif isinstance(value, str):
        fragment = b"s" + value.encode("utf-8")
    elif isinstance(value, bool):
        fragment = b"t" if value else b"f"
    elif isinstance(value, (int, float)):
        fragment = b"n" + repr(value).encode("ascii")
    elif isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        fragment = b"d" + value.isoformat().encode("ascii")
    elif isinstance(value, bytes):
        fragment = b"x" + value
    elif isinstance(value, shapely.Geometry):
        fragment = b"g" + value.wkb
    else:
        fragment = b"?" + repr(value).encode("utf-8")
    return fragment
