"""Provide data builders and stand-ins for grouping tests."""

from __future__ import annotations

import typing

import hypothesis.strategies
import shapely
import structlog

import peri_scribe.fires.grouping
import peri_scribe.models


def warning_events(
    records: list[peri_scribe.models.FireRecord],
    fires: list[peri_scribe.models.Fire],
) -> list[typing.MutableMapping[str, object]]:
    """Return events logged while warning about inconsistent *records*.

    Args:
        records: The grouped fire records.
        fires: The fires built from the groups.

    Returns:
        The logged events.
    """
    groups = [[0, 1]]
    with structlog.testing.capture_logs() as captured:
        peri_scribe.fires.grouping.warn_for_inconsistent_fires(records, groups, fires)
    return captured


@hypothesis.strategies.composite
def local_geometries(draw: hypothesis.strategies.DrawFn) -> shapely.Geometry:
    """Include touching, nearby, distant, and duplicate point and polygon locations.

    Args:
        draw: The current example's strategy sampler.

    Returns:
        A nonempty geometry on a small coordinate grid in degrees.
    """
    longitude = draw(hypothesis.strategies.integers(0, 8)) / 32
    latitude = draw(hypothesis.strategies.integers(0, 8)) / 32
    longitude += 2 * draw(hypothesis.strategies.integers(0, 2))
    if draw(hypothesis.strategies.booleans()):
        return shapely.Point(longitude, latitude)
    return shapely.box(longitude, latitude, longitude + 1 / 32, latitude + 1 / 32)


def fire_records() -> hypothesis.strategies.SearchStrategy[
    list[peri_scribe.models.FireRecord]
]:
    """Allow identifier aliases and spatial name matches to form transitive groups.

    Returns:
        Short record lists with overlapping identifiers, names, and locations.
    """
    return hypothesis.strategies.lists(
        hypothesis.strategies.builds(
            peri_scribe.models.FireRecord,
            name=hypothesis.strategies.just("River"),
            status=hypothesis.strategies.from_type(peri_scribe.models.FireStatus),
            identifiers=hypothesis.strategies.frozensets(
                hypothesis.strategies.sampled_from(("id-a", "id-b", "id-c")),
                max_size=2,
            ),
            names=hypothesis.strategies.frozensets(
                hypothesis.strategies.sampled_from(("river", "canyon", "ridge")),
                min_size=1,
                max_size=2,
            ),
            geometry=hypothesis.strategies.one_of(
                hypothesis.strategies.none(),
                hypothesis.strategies.just(shapely.Point()),
                local_geometries(),
            ),
        ),
        max_size=15,
    )


def reference_groups(records: list[peri_scribe.models.FireRecord]) -> list[list[int]]:
    """Find connected components by walking all pairwise identity and proximity edges.

    Args:
        records: Records with normalized identity keys and degree coordinates.

    Returns:
        Components in encounter order, with each component's indices sorted.
    """
    neighbors = {index: set[int]() for index in range(len(records))}
    for left, record in enumerate(records):
        for right, other in enumerate(records):
            shared_identifier = bool(record.identifiers & other.identifiers)
            shared_location = (
                bool(record.names & other.names)
                and record.geometry is not None
                and other.geometry is not None
                and not record.geometry.is_empty
                and not other.geometry.is_empty
                and record.geometry.distance(other.geometry)
                <= peri_scribe.fires.grouping.FIRE_PROXIMITY_TOLERANCE.m_as("degrees")
            )
            if shared_identifier or shared_location:
                neighbors[left].add(right)
    remaining = set(neighbors)
    groups = []
    while remaining:
        pending = [min(remaining)]
        component: set[int] = set()
        while pending:
            index = pending.pop()
            if index not in component:
                component.add(index)
                pending.extend(neighbors[index] - component)
        remaining -= component
        groups.append(sorted(component))
    return groups
