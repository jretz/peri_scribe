"""Build version histories with equivalent representations of logical states."""

from __future__ import annotations

import datetime
import typing

import hypothesis.strategies
import shapely

import tests.factories


if typing.TYPE_CHECKING:
    import peri_scribe.perimeters.versions


def attribute_histories() -> hypothesis.strategies.SearchStrategy[
    list[tuple[int | None, int | None]]
]:
    """Make repeated states and reversions common in incident location histories.

    Returns:
        Canonical incident size and personnel states in snapshot order.
    """
    value = hypothesis.strategies.one_of(
        hypothesis.strategies.none(),
        hypothesis.strategies.integers(0, 3),
    )
    return hypothesis.strategies.lists(
        hypothesis.strategies.tuples(value, value),
        max_size=20,
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
        tests.factories.observation(
            source_kind=tests.factories.WFIGS_LOCATION,
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
            tests.factories.observation(
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
