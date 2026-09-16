"""Build inputs for versions tests."""

from __future__ import annotations

import datetime

import shapely
import shapely.geometry

import peri_scribe.perimeters.classification_data
import peri_scribe.perimeters.versions
import tests.helpers.factories.peri_scribe.perimeters.classification_data


def observation(
    *,
    source_kind: peri_scribe.perimeters.classification_data.FireSourceKind = (
        tests.helpers.factories.peri_scribe.perimeters.classification_data.FIRIS_PERIMETER
    ),
    geometry: shapely.geometry.base.BaseGeometry | None = None,
    observation_time: datetime.datetime | None = None,
    snapshot_time: datetime.datetime | None = None,
    serial_number: int = 0,
    object_id: int | None = 1,
    source_file: str = "source.gpkg",
    attributes: dict[str, object] | None = None,
) -> peri_scribe.perimeters.versions.SourceObservation:
    """Build a source observation for a test.

    Args:
        source_kind: The observation's source kind.
        geometry: The observation's geometry.
        observation_time: The mapping time.
        snapshot_time: The snapshot's last-edit time.
        serial_number: The snapshot serial number.
        object_id: The source row's OBJECTID.
        source_file: The source file path.
        attributes: The row's attributes.

    Returns:
        The observation.
    """
    return peri_scribe.perimeters.versions.SourceObservation(
        source_kind=source_kind,
        geometry=geometry,
        observation_time=observation_time,
        snapshot_time=snapshot_time,
        serial_number=serial_number,
        object_id=object_id,
        source_file=source_file,
        attributes={} if attributes is None else attributes,
    )


def point_observations(
    states: list[tuple[int | None, int | None]],
) -> list[peri_scribe.perimeters.versions.SourceObservation]:
    """Change locations and null representations independently of attribute state.

    Args:
        states: Canonical incident measurements in snapshot order.

    Returns:
        Distinct source rows with varied geometry, timing, and provenance.
    """
    base = datetime.datetime(2026, 8, 1, tzinfo=datetime.UTC)
    return [
        observation(
            source_kind=tests.helpers.factories.peri_scribe.perimeters.classification_data.WFIGS_LOCATION,
            geometry=shapely.Point(index, index / 10),
            observation_time=base + datetime.timedelta(minutes=index),
            snapshot_time=base + datetime.timedelta(hours=index),
            serial_number=index,
            object_id=index,
            source_file=f"{index}.gpkg",
            attributes={
                key: float("nan") if value is None and index % 2 else value
                for key, value in zip(("IncidentSize", "Personnel"), state, strict=True)
            },
        )
        for index, state in enumerate(states)
    ]


def perimeter_observations(
    shapes: list[int],
) -> list[peri_scribe.perimeters.versions.SourceObservation]:
    """Republish boundaries with different winding and polygon container types.

    Args:
        shapes: Footprint identities in observation order; zero means missing geometry.

    Returns:
        Mappings without new survey evidence, carrying distinct publication metadata.
    """
    observations = []
    base = datetime.datetime(2026, 8, 1, tzinfo=datetime.UTC)
    for index, shape in enumerate(shapes):
        polygon = shapely.box(0, 0, shape, shape)
        geometry = (
            None
            if shape == 0
            else shapely.MultiPolygon([shapely.reverse(polygon)])
            if index % 2
            else polygon
        )
        observations.append(
            observation(
                geometry=geometry,
                observation_time=base + datetime.timedelta(hours=index),
                snapshot_time=base + datetime.timedelta(days=index),
                serial_number=index,
                object_id=index,
                source_file=f"{index}.gpkg",
                attributes={"revision": index},
            ),
        )
    return observations
