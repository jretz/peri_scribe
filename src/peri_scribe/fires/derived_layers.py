"""Reading the derived history layers back.

The geography stage writes the full and differential history GeoPackages, and the score,
KMZ, and report stages read them back. This module holds the one description of which
files and layers those are, so the stages cannot drift apart about them.

Algorithm reasoning and contracts:
[Geography generations](../../../docs/algorithms/geography-generations.md)
"""

from __future__ import annotations

import contextlib
import dataclasses
import errno
import pathlib
import sqlite3

import geopandas

import peri_scribe.execution
import peri_scribe.fires.differential
import peri_scribe.fires.files
import peri_scribe.fires.reuse
import peri_scribe.incidents
import peri_scribe.pipeline_state


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
    missing derived file is an error worth failing on. Tolerant scoring accepts an
    entirely absent pair for a fresh year. Existing files must authenticate as one
    generation, including when an earlier geography writer was interrupted.

    Args:
        year_directory: The year directory that holds the ``derived`` directory.
        tolerate_missing: Whether an entirely absent pair yields empty frames.

    Returns:
        The full perimeter, point, and incident histories and differential perimeters.

    Raises:
        RuntimeError: A writer owns the year or the published generations do not match.
    """
    with peri_scribe.pipeline_state.read_lock(year_directory) as acquired:
        if not acquired:
            message = "A writer owns this year's geography; retry the read later"
            raise RuntimeError(message)
        return read_locked_derived_layers(
            year_directory,
            tolerate_missing=tolerate_missing,
        )


def authenticated_pair(
    year_directory: pathlib.Path,
    history_path: pathlib.Path,
    differential_path: pathlib.Path,
    *,
    tolerate_missing: bool,
) -> tuple[str, str] | None:
    """Reject interrupted, unrelated, and unauthenticated geography generations.

    Args:
        year_directory: The year whose shared or exclusive lock the caller holds.
        history_path: Published full-history GeoPackage.
        differential_path: Published growth-history GeoPackage.
        tolerate_missing: Permit an entirely absent pair for fresh-year scoring.

    Returns:
        Authenticated content identities, or None for an absent tolerant pair.

    Raises:
        FileNotFoundError: A required geography file is absent.
        RuntimeError: Published bytes or their generation relationship are invalid.
    """
    present = (history_path.is_file(), differential_path.is_file())
    if tolerate_missing and not any(present):
        return None
    for path, exists in zip((history_path, differential_path), present, strict=True):
        if not exists:
            raise FileNotFoundError(errno.ENOENT, "No such file", str(path))
    full = peri_scribe.fires.reuse.validated_signature(
        history_path,
        peri_scribe.fires.files.FULL_LAYER_NAMES,
    )
    differential = peri_scribe.fires.reuse.validated_signature(
        differential_path,
        (
            peri_scribe.fires.files.PERIMETER_LAYER_NAME,
            peri_scribe.fires.files.POINT_LAYER_NAME,
        ),
    )
    if (
        full is None
        or differential is None
        or differential.generation is None
        or differential.generation
        != peri_scribe.fires.differential.differential_generation(
            history_path,
            year_directory,
        )
    ):
        message = "Unmatched geography generations; run the geography stage to rebuild"
        raise RuntimeError(message)
    return full.checksum, differential.checksum


def read_locked_derived_layers(
    year_directory: pathlib.Path,
    *,
    tolerate_missing: bool,
) -> DerivedLayers:
    """Cache only a complete authenticated generation while the year stays locked.

    Args:
        year_directory: The year whose shared or exclusive lock the caller holds.
        tolerate_missing: Permit an entirely absent pair for fresh-year scoring.

    Returns:
        Consistent full and differential rows, or empty fresh-year layers.
    """
    history_path = peri_scribe.fires.files.history_geopackage_path(year_directory)
    differential_path = peri_scribe.fires.differential.differential_geopackage_path(
        year_directory,
    )
    identity = authenticated_pair(
        year_directory,
        history_path,
        differential_path,
        tolerate_missing=tolerate_missing,
    )
    key = (year_directory.resolve(), identity)
    cached = peri_scribe.execution.get(peri_scribe.execution.Group.DERIVED, key)
    if isinstance(cached, DerivedLayers):
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
