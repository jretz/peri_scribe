"""Fixtures for perimeter tests."""

from __future__ import annotations

import pytest
import shapely.geometry

import peri_scribe.perimeters.classification_data
import peri_scribe.perimeters.versions
import tests.factories
import tests.peri_scribe.perimeters.classification_helpers


CALIFORNIA_BOX = shapely.geometry.box(0.0, 0.0, 100.0, 100.0)
BORDER = shapely.geometry.LineString([(100.0, 0.0), (100.0, 100.0)])


@pytest.fixture
def boundaries() -> peri_scribe.perimeters.classification_data.Boundaries:
    """Return a synthetic California box and border in planar coordinates.

    Returns:
        The California box and the border along its eastern edge.
    """
    return peri_scribe.perimeters.classification_data.Boundaries(
        box=CALIFORNIA_BOX,
        border=BORDER,
    )


@pytest.fixture
def wgs84_boundaries() -> peri_scribe.perimeters.classification_data.Boundaries:
    """Return a synthetic California box and border in California Albers.

    Returns:
        The California box and border, reprojected from WGS84.
    """
    return peri_scribe.perimeters.classification_data.Boundaries(
        box=peri_scribe.perimeters.classification_data.reproject_to_california_albers(
            tests.peri_scribe.perimeters.classification_helpers.CALIFORNIA_BOX_WGS84,
            4326,
        ),
        border=(
            peri_scribe.perimeters.classification_data.reproject_to_california_albers(
                tests.peri_scribe.perimeters.classification_helpers.CA_BORDER_WGS84,
                4326,
            )
        ),
    )


@pytest.fixture
def revision_observations() -> list[peri_scribe.perimeters.versions.SourceObservation]:
    """Provide a close mapping pair whose metadata corroborates a minor revision.

    Returns:
        Consecutive flight-source observations with nearly identical footprints and
        separate source references for checking retained provenance.
    """
    return [
        tests.factories.observation(
            geometry=shapely.geometry.box(0, 0, 1 + minute / 1000, 1),
            observation_time=tests.factories.utc(2026, 9, 7, 20, minute),
            serial_number=minute,
            source_file=f"{minute}.gpkg",
            attributes={
                "source": "CAL FIRE INTEL FLIGHT DATA",
                "type": "Heat Perimeter",
            },
        )
        for minute in (24, 25)
    ]


@pytest.fixture
def delayed_mapping_pair() -> tuple[
    peri_scribe.perimeters.versions.SourceObservation,
    peri_scribe.perimeters.versions.SourceObservation,
]:
    """Expose a length spike caused by delayed publication of an older survey.

    Returns:
        A preferred flight mapping and a later-published, earlier-captured WFIGS
        footprint with a narrow notch that adds length without much area change.
    """
    flight = tests.factories.observation(
        source_kind=tests.factories.FIRIS_PERIMETER,
        geometry=shapely.geometry.box(0, 0, 1, 1),
        observation_time=tests.factories.utc(2026, 9, 1, 21, 32),
        source_file="flight.gpkg",
    )
    delayed = tests.factories.observation(
        source_kind=tests.factories.WFIGS_PERIMETER,
        geometry=shapely.geometry.Polygon([
            (0, 0),
            (1, 0),
            (1, 1),
            (0.51, 1),
            (0.51, 0.1),
            (0.49, 0.1),
            (0.49, 1),
            (0, 1),
        ]),
        observation_time=tests.factories.utc(2026, 9, 2, 13, 25),
        source_file="delayed.gpkg",
        object_id=2,
        attributes={"poly_PolygonDateTime": tests.factories.utc(2026, 9, 1, 16, 48)},
    )
    return flight, delayed
