"""Reading the derived history layers back.

The geography stage writes the full and differential history GeoPackages, and the score,
KMZ, and report stages read them back. This module holds the one description of which
files and layers those are, so the stages cannot drift apart about them.
"""

from __future__ import annotations

import dataclasses
import pathlib

import geopandas

import peri_scribe.fires.differential
import peri_scribe.fires.files
import peri_scribe.geo.reading


@dataclasses.dataclass(frozen=True, kw_only=True)
class DerivedLayers:
    """The derived history layers every later stage reads."""

    perimeters: geopandas.GeoDataFrame
    points: geopandas.GeoDataFrame
    differential_perimeters: geopandas.GeoDataFrame


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
    return peri_scribe.geo.reading.read_layer(path, layer_name)


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
        The full-history perimeters and points and the differential perimeters.
    """
    if tolerate_missing:
        read = read_layer_if_present
    else:
        read = peri_scribe.geo.reading.read_layer
    history_path = peri_scribe.fires.files.history_geopackage_path(year_directory)
    differential_path = peri_scribe.fires.differential.differential_geopackage_path(
        year_directory,
    )
    return DerivedLayers(
        perimeters=read(
            history_path,
            peri_scribe.fires.files.PERIMETER_LAYER_NAME,
        ),
        points=read(
            history_path,
            peri_scribe.fires.files.POINT_LAYER_NAME,
        ),
        differential_perimeters=read(
            differential_path,
            peri_scribe.fires.files.PERIMETER_LAYER_NAME,
        ),
    )
