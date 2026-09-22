"""Calculate independent expected results for classification tests."""

from __future__ import annotations

import geopandas
import shapely.affinity

import peri_scribe.perimeters.classification_data
import spatial_data.reference


def full_projected_union(
    observations: list[peri_scribe.perimeters.classification_data.FireObservation],
) -> shapely.Geometry | None:
    """Provide a union reference without deduplication or one-sided shortcuts.

    Args:
        observations: Source observations before projection.

    Returns:
        Their complete union in California Albers, or None without usable geometry.
    """
    by_reference: dict[int, list[shapely.Geometry]] = {}
    for observation in observations:
        if observation.geometry is not None and not observation.geometry.is_empty:
            reference = (
                peri_scribe.perimeters.classification_data.SOURCE_SPATIAL_REFERENCE_IDS[
                    observation.source
                ]
            )
            by_reference.setdefault(reference, []).append(observation.geometry)
    projected = [
        geometry
        for reference, geometries in by_reference.items()
        for geometry in geopandas.GeoSeries(geometries, crs=reference).to_crs(
            spatial_data.reference.CALIFORNIA_ALBERS_SPATIAL_REFERENCE_ID,
        )
    ]
    return shapely.union_all(projected) if projected else None
