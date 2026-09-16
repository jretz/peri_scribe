"""Build inputs for classification data tests."""

from __future__ import annotations

import shapely.geometry

import peri_scribe.models
import peri_scribe.perimeters.classification_data


FIRIS_PERIMETER = (
    peri_scribe.perimeters.classification_data.FireSourceKind.FIRIS_PERIMETER
)


WFIGS_PERIMETER = (
    peri_scribe.perimeters.classification_data.FireSourceKind.WFIGS_PERIMETER
)


WFIGS_LOCATION = (
    peri_scribe.perimeters.classification_data.FireSourceKind.WFIGS_LOCATION
)


def classification(
    kind: peri_scribe.models.BorderClassification,
) -> peri_scribe.models.FireClassification:
    """Build a border classification for a test.

    Args:
        kind: The classification kind.

    Returns:
        The classification.
    """
    return peri_scribe.models.FireClassification(
        classification=kind,
        outside_area_fraction=0.0,
        inside_area_fraction=0.0,
    )


CALIFORNIA_BOX = shapely.geometry.box(0.0, 0.0, 100.0, 100.0)


BORDER = shapely.geometry.LineString([(100.0, 0.0), (100.0, 100.0)])
