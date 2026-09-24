"""Reading the derived history layers back.

The geography stage writes the full and differential history GeoPackages, and the score,
KMZ, and report stages read them back. This module holds the one description of which
files and layers those are, so the stages cannot drift apart about them.
"""

from __future__ import annotations

import contextlib
import dataclasses
import pathlib
import sqlite3

import geopandas

import peri_scribe.execution
import peri_scribe.fires.differential
import peri_scribe.fires.files
import peri_scribe.fires.reuse
import peri_scribe.incidents


@dataclasses.dataclass(frozen=True, kw_only=True)
class DerivedLayers:
    """The derived history layers every later stage reads."""

    perimeters: geopandas.GeoDataFrame
    points: geopandas.GeoDataFrame
    differential_perimeters: geopandas.GeoDataFrame
    incidents: geopandas.GeoDataFrame = dataclasses.field(
        default_factory=geopandas.GeoDataFrame,
    )


def read_layer_if_present(
    path: pathlib.Path,
    layer_name: str,
) -> geopandas.GeoDataFrame:
    """Read a GeoPackage layer, returning an empty frame when the file is missing.

    Args:
        path: The GeoPackage file.
        layer_name: The layer to read.

    Returns:
        The layer's features, or an empty GeoDataFrame when the file is absent.
    """
    if not path.is_file():
        return geopandas.GeoDataFrame()
    return peri_scribe.fires.reuse.read_published_layer(path, layer_name)


def read_derived_layers(
    year_directory: pathlib.Path,
    *,
    tolerate_missing: bool,
) -> DerivedLayers:
    """Return the derived history layers for *year_directory*.

    The KMZ and report stages run only after geography and scoring, so for them a
    missing derived file is an error worth failing on. The score stage also runs against
    a year that has never been derived, so it reads tolerantly and receives an empty
    frame for each absent file.

    Args:
        year_directory: The year directory that holds the ``derived`` directory.
        tolerate_missing: Whether an absent derived file yields an empty frame instead
            of a read failure.

    Returns:
        The full perimeter, point, and incident histories and differential perimeters.
    """
    history_path = peri_scribe.fires.files.history_geopackage_path(year_directory)
    differential_path = peri_scribe.fires.differential.differential_geopackage_path(
        year_directory,
    )
    paths = (history_path, differential_path)
    key = (
        tuple(
            (str(path.resolve()), path.stat().st_size, path.stat().st_mtime_ns)
            if path.is_file()
            else (str(path.resolve()), None, None)
            for path in paths
        )
        if peri_scribe.execution.active()
        else None
    )
    cached = peri_scribe.execution.get(peri_scribe.execution.Group.DERIVED, key)
    if isinstance(cached, DerivedLayers) and (
        tolerate_missing or all(path.is_file() for path in paths)
    ):
        return cached
    read = (
        read_layer_if_present
        if tolerate_missing
        else peri_scribe.fires.reuse.read_published_layer
    )
    layers = DerivedLayers(
        incidents=read_incident_layer(history_path),
        perimeters=read(history_path, peri_scribe.fires.files.PERIMETER_LAYER_NAME),
        points=read(history_path, peri_scribe.fires.files.POINT_LAYER_NAME),
        differential_perimeters=read(
            differential_path,
            peri_scribe.fires.files.PERIMETER_LAYER_NAME,
        ),
    )
    peri_scribe.execution.put(peri_scribe.execution.Group.DERIVED, key, layers)
    return layers


def read_incident_layer(path: pathlib.Path) -> geopandas.GeoDataFrame:
    """Support geography histories that have no independent reporting layer.

    Args:
        path: The full-history GeoPackage to read without modifying it.

    Returns:
        Incident-history rows, or an empty frame when the file or layer is absent.
    """
    if not path.is_file():
        return geopandas.GeoDataFrame()
    with contextlib.closing(
        sqlite3.connect(f"file:{path}?mode=ro", uri=True),
    ) as connection:
        present = connection.execute(
            "SELECT 1 FROM gpkg_contents WHERE table_name = ?",
            (peri_scribe.incidents.LAYER_NAME,),
        ).fetchone()
    if present is None:
        return geopandas.GeoDataFrame()
    return peri_scribe.fires.reuse.read_published_layer(
        path,
        peri_scribe.incidents.LAYER_NAME,
    )
