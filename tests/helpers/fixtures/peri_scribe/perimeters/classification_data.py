"""Isolate classification data tests with explicit fixtures."""

from __future__ import annotations

import pytest

import peri_scribe.perimeters.classification_data
import tests.helpers.factories.peri_scribe.perimeters.classification
import tests.helpers.factories.peri_scribe.perimeters.classification_data


@pytest.fixture
def boundaries() -> peri_scribe.perimeters.classification_data.Boundaries:
    """Return a synthetic California box and border in planar coordinates.

    Returns:
        The California box and the border along its eastern edge.
    """
    return peri_scribe.perimeters.classification_data.Boundaries(
        box=tests.helpers.factories.peri_scribe.perimeters.classification_data.CALIFORNIA_BOX,
        border=tests.helpers.factories.peri_scribe.perimeters.classification_data.BORDER,
    )


@pytest.fixture
def wgs84_boundaries() -> peri_scribe.perimeters.classification_data.Boundaries:
    """Return a synthetic California box and border in California Albers.

    Returns:
        The California box and border, reprojected from WGS84.
    """
    return peri_scribe.perimeters.classification_data.Boundaries(
        box=peri_scribe.perimeters.classification_data.reproject_to_california_albers(
            tests.helpers.factories.peri_scribe.perimeters.classification.CALIFORNIA_BOX_WGS84,
            4326,
        ),
        border=(
            peri_scribe.perimeters.classification_data.reproject_to_california_albers(
                tests.helpers.factories.peri_scribe.perimeters.classification.CA_BORDER_WGS84,
                4326,
            )
        ),
    )
