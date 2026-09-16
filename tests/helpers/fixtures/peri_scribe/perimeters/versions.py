"""Isolate versions tests with explicit fixtures."""

from __future__ import annotations

import typing

import pytest
import shapely.geometry

import tests.helpers.factories.peri_scribe.perimeters.classification_data
import tests.helpers.factories.peri_scribe.perimeters.versions
import tests.helpers.factories.time


if typing.TYPE_CHECKING:
    import peri_scribe.perimeters.versions


@pytest.fixture
def revision_observations() -> list[peri_scribe.perimeters.versions.SourceObservation]:
    """Provide a close mapping pair whose metadata corroborates a minor revision.

    Returns:
        Consecutive flight-source observations with nearly identical footprints and
        separate source references for checking retained provenance.
    """
    return [
        tests.helpers.factories.peri_scribe.perimeters.versions.observation(
            geometry=shapely.geometry.box(0, 0, 1 + minute / 1000, 1),
            observation_time=tests.helpers.factories.time.utc(2026, 9, 7, 20, minute),
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
    flight = tests.helpers.factories.peri_scribe.perimeters.versions.observation(
        source_kind=tests.helpers.factories.peri_scribe.perimeters.classification_data.FIRIS_PERIMETER,
        geometry=shapely.geometry.box(0, 0, 1, 1),
        observation_time=tests.helpers.factories.time.utc(2026, 9, 1, 21, 32),
        source_file="flight.gpkg",
    )
    delayed = tests.helpers.factories.peri_scribe.perimeters.versions.observation(
        source_kind=tests.helpers.factories.peri_scribe.perimeters.classification_data.WFIGS_PERIMETER,
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
        observation_time=tests.helpers.factories.time.utc(2026, 9, 2, 13, 25),
        source_file="delayed.gpkg",
        object_id=2,
        attributes={
            "poly_PolygonDateTime": tests.helpers.factories.time.utc(
                2026,
                9,
                1,
                16,
                48,
            ),
        },
    )
    return flight, delayed
