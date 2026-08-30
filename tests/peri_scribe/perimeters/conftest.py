"""Fixtures for perimeter tests."""

from __future__ import annotations

import pytest
import shapely.geometry

import peri_scribe.perimeters.border_classification


CALIFORNIA_BOX = shapely.geometry.box(0.0, 0.0, 100.0, 100.0)
BORDER = shapely.geometry.LineString([(100.0, 0.0), (100.0, 100.0)])


@pytest.fixture
def boundaries() -> peri_scribe.perimeters.border_classification.Boundaries:
    """Return a synthetic California box and border in planar coordinates.

    Returns:
        The California box and the border along its eastern edge.
    """
    return peri_scribe.perimeters.border_classification.Boundaries(
        box=CALIFORNIA_BOX,
        border=BORDER,
    )
