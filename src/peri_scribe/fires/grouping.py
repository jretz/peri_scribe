"""Grouping fire records that identify the same fire.

[Grouping and ownership](../../../docs/algorithms/fire-grouping-and-ownership.md)
[Incremental grouping](../../../docs/algorithms/incremental-grouping.md)
"""

from __future__ import annotations

import collections
import collections.abc
import datetime
import functools
import typing

import shapely
import structlog

import peri_scribe.fires.complexes
import peri_scribe.fires.connectivity
import peri_scribe.fires.grouping_cache
import peri_scribe.fires.proximity
import peri_scribe.models
import spatial_data.geometry_pool
import spatial_data.product_cache
from measurement_units import units


logger = structlog.get_logger()


# Same-named records can describe one fire when their geometries overlap or lie within
# this gap. The tolerance is roughly 5.5 km north-south; east-west distance depends on
# latitude.
FIRE_PROXIMITY_TOLERANCE = 0.05 * units.degrees

# Widely separated records can indicate that two fires were merged by mistake. This
# threshold allows much larger gaps than the grouping tolerance so ordinary changes to a
# reported point location do not trigger a warning.
FIRE_OUTLIER_TOLERANCE = 1.0 * units.degrees

# A fire whose records span longer than this across observation times is reported as
# possibly two fires that were merged.
FIRE_OBSERVATION_SPREAD_TOLERANCE = datetime.timedelta(days=60)

# The number of timed records needed to measure an observation-time spread.
MINIMUM_TIMED_RECORDS = 2

# The number of non-empty geometries needed before spatial compatibility can merge
# records or mark them as disagreeing.
MINIMUM_SPATIAL_GEOMETRIES = 2


def records_span_distant_locations(
    records: list[peri_scribe.models.FireRecord],
    group: list[int],
    *,
    geometry_keys: spatial_data.geometry_pool.GeometryKeys | None = None,
) -> bool:
    """Return whether a record in *group* disagrees with the rest on location.

    A record disagrees when the rest of the group has a geometry and the record has
    none, or when none of the other records' geometries is within the outlier tolerance;
    the distance from a record to the union of the others is the minimum distance to any
    one of them.

    Args:
        records: The records that were grouped.
        group: The record indices of one fire.
        geometry_keys: Execution-owned exact geometry identities, when available.

    Returns:
        True when some record disagrees with the rest of the group on location.
    """
    geometries_by_index: dict[int, shapely.Geometry] = {}
    for index in group:
        geometry = records[index].geometry
        if geometry is not None:
            geometries_by_index[index] = geometry
    members = [
        (index, geometry)
        for index, geometry in geometries_by_index.items()
        if not geometry.is_empty
    ]
    matched_indices = matched_within_outlier_tolerance(
        members,
        geometry_keys=geometry_keys,
    )
    for index in group:
        geometry = records[index].geometry
        others_count = len(geometries_by_index) - (
            1 if index in geometries_by_index else 0
        )
        if others_count == 0:
            continue
        if geometry is None or geometry.is_empty or index not in matched_indices:
            return True
    return False


def matched_within_outlier_tolerance(
    members: list[tuple[int, shapely.Geometry]],
    *,
    geometry_keys: spatial_data.geometry_pool.GeometryKeys | None = None,
) -> set[int]:
    """Return the members with another member within the outlier tolerance.

    Members with byte-identical geometry already have a match when their class has more
    than one member. The remaining comparisons need only one representative of each
    class.

    Check representatives until a nearby one is found. A fire's records are usually near
    one another, so the first comparison often settles the question. An actual outlier
    requires checking every other representative.

    Args:
        members: The group's non-empty geometries, as (index, geometry) pairs.
        geometry_keys: Execution-owned exact geometry identities, when available.

    Returns:
        The indices of the members that have another member within the outlier
        tolerance.
    """
    if geometry_keys is None:
        geometry_keys = spatial_data.geometry_pool.GeometryKeys()
    classes: dict[tuple[bytes, int], list[tuple[int, shapely.Geometry]]] = {}
    for member in members:
        classes.setdefault(geometry_keys.key(member[1]), []).append(member)
    matched_indices: set[int] = set()
    for class_members in classes.values():
        if len(class_members) >= MINIMUM_SPATIAL_GEOMETRIES:
            matched_indices.update(index for index, _geometry in class_members)
    representatives = [class_members[0] for class_members in classes.values()]
    for position, (index, geometry) in enumerate(representatives):
        if index in matched_indices:
            continue
        for other_position, (other_index, other_geometry) in enumerate(representatives):
            if position == other_position:
                continue
            if shapely.dwithin(
                geometry,
                other_geometry,
                FIRE_OUTLIER_TOLERANCE.m_as("degrees"),
            ):
                matched_indices.add(index)
                matched_indices.add(other_index)
                break
    return matched_indices


def warn_for_inconsistent_fires(
    records: list[peri_scribe.models.FireRecord],
    groups: list[list[int]],
    fires: list[peri_scribe.models.Fire],
    *,
    geometry_keys: spatial_data.geometry_pool.GeometryKeys | None = None,
) -> None:
    """Log location inconsistencies at info level and long time spans at debug level.

    A fire whose member records disagree on location or span a long observation range
    may be two fires that were merged by name. Each log entry names the fire so the
    grouping can be inspected.

    Args:
        records: The records that were grouped.
        groups: The record indices of each fire, aligned with *fires*.
        fires: The fires, aligned with *groups*.
        geometry_keys: Execution-owned exact geometry identities, when available.
    """
    if geometry_keys is None:
        geometry_keys = spatial_data.geometry_pool.GeometryKeys()
    for fire, group in zip(fires, groups, strict=True):
        if records_span_distant_locations(records, group, geometry_keys=geometry_keys):
            logger.info(
                "Fire records span distant locations",
                fire=fire.name,
                identifier=fire.identifier,
            )
        observed_times: list[datetime.datetime] = []
        for index in group:
            observed_at = records[index].observed_at
            if observed_at is not None:
                observed_times.append(observed_at)
        if len(observed_times) >= MINIMUM_TIMED_RECORDS:
            spread = max(observed_times) - min(observed_times)
            if spread > FIRE_OBSERVATION_SPREAD_TOLERANCE:
                logger.debug(
                    "Fire records span distant times",
                    fire=fire.name,
                    identifier=fire.identifier,
                    days=spread.days,
                )


def group_fire_record_indices(
    records: list[peri_scribe.models.FireRecord],
    *,
    row_keys: collections.abc.Sequence[str] | None = None,
    geometry_keys: spatial_data.geometry_pool.GeometryKeys | None = None,
) -> list[list[int]]:
    """Group source positions while retaining exact ordered component semantics.

    Complete row identities permit independent dependency blocks to reuse previously
    calculated partitions. Bare calls calculate the entire relation directly.

    Args:
        records: The fire records to group, in authoritative occurrence order.
        row_keys: Complete canonical source-row fingerprints, aligned with records.
        geometry_keys: Execution-owned exact geometry identities, when available.

    Returns:
        Ordered positions in components ordered by their first occurrence.

    Raises:
        ValueError: If supplied row fingerprints do not align with all records.
    """
    if geometry_keys is None:
        geometry_keys = spatial_data.geometry_pool.GeometryKeys()
    if row_keys is not None:
        if len(row_keys) != len(records):
            message = "Grouping evidence keys must align with every source occurrence"
            raise ValueError(message)
        if spatial_data.product_cache.active():
            return peri_scribe.fires.grouping_cache.grouped_indices(
                records,
                row_keys,
                str(FIRE_PROXIMITY_TOLERANCE.m_as("degrees")),
                functools.partial(
                    group_fire_record_indices,
                    geometry_keys=geometry_keys,
                ),
            )
    components = peri_scribe.fires.connectivity.UnionFind.for_count(len(records))
    by_identifier: dict[str, int] = {}
    for index, record in enumerate(records):
        for identifier in record.identifiers:
            components.union(index, by_identifier.setdefault(identifier, index))
    merge_records_by_name(
        records,
        components.union,
        find=components.find,
        geometry_keys=geometry_keys,
    )
    return components.groups()


def merge_records_by_name(
    records: list[peri_scribe.models.FireRecord],
    union: typing.Callable[[int, int], None],
    *,
    find: typing.Callable[[int], int] | None = None,
    geometry_keys: spatial_data.geometry_pool.GeometryKeys | None = None,
) -> None:
    """Merge only spatial relationships that can still change identity connectivity.

    Identifier-connected name buckets already have every possible edge represented by a
    path. Other buckets collapse exact geometry classes and emit sufficient proximity
    edges to preserve the complete connected components.

    Args:
        records: The records to merge.
        union: The union operation used by the owning grouping.
        find: Current representatives, when the owning grouping exposes them.
        geometry_keys: Execution-owned exact geometry identities, when available.
    """
    if geometry_keys is None:
        geometry_keys = spatial_data.geometry_pool.GeometryKeys()
    by_name: dict[str, list[int]] = {}
    for index, record in enumerate(records):
        for name in record.names:
            by_name.setdefault(name, []).append(index)
    for indices in by_name.values():
        if find is not None:
            root = find(indices[0])
            if all(find(index) == root for index in indices):
                continue
        representatives = named_representatives(records, indices, union, geometry_keys)
        if len(representatives) >= MINIMUM_SPATIAL_GEOMETRIES:
            for left, right in peri_scribe.fires.proximity.spanning_pairs(
                [geometry for _index, geometry in representatives],
                tolerance=FIRE_PROXIMITY_TOLERANCE,
            ):
                union(representatives[left][0], representatives[right][0])


def named_representatives(
    records: list[peri_scribe.models.FireRecord],
    indices: list[int],
    union: typing.Callable[[int, int], None],
    geometry_keys: spatial_data.geometry_pool.GeometryKeys,
) -> list[tuple[int, shapely.Geometry]]:
    """Join exact geometry classes and retain all possible proximity bridges.

    Args:
        records: Current source occurrences.
        indices: Original positions sharing one normalized name.
        union: The owning grouping's union operation.
        geometry_keys: Exact geometry identities owned by this source preparation.

    Returns:
        One original occurrence per distinct nonempty geometry class.
    """
    classes: dict[tuple[bytes, int], list[tuple[int, shapely.Geometry]]] = {}
    for index in indices:
        geometry = records[index].geometry
        if geometry is not None and not geometry.is_empty:
            classes.setdefault(geometry_keys.key(geometry), []).append((
                index,
                geometry,
            ))
    for members in classes.values():
        for index, _geometry in members[1:]:
            union(members[0][0], index)
    return [members[0] for members in classes.values()]


def fire_complexes(
    memberships: list[peri_scribe.models.ComplexMembership],
    fires_by_identifier: dict[str, peri_scribe.models.Fire],
    *,
    observations: list[peri_scribe.fires.complexes.MembershipObservation] | None = None,
) -> list[peri_scribe.models.FireComplex]:
    """Build the complexes named by *memberships*, linking their member fires.

    Each component follows its latest declaration through subsequent parent mergers.
    Reciprocal links name one current owner; contradictory exact ties and cycles leave
    ownership unassigned. Unknown component references are skipped with a warning.

    Args:
        memberships: The observed complex memberships.
        fires_by_identifier: The identified fires, keyed by every identifier each fire
            is known by.
        observations: Incident-timed assignments and explicit releases when available.

    Returns:
        The declared complexes with their current members, in first-encounter order.
    """
    declarations = (
        observations
        if observations is not None
        else [
            peri_scribe.fires.complexes.MembershipObservation(
                fire_identifier=membership.fire_identifier,
                complex_identifier=membership.complex_identifier,
                complex_name=membership.complex_name,
                observation_time=membership.observation_time,
            )
            for membership in memberships
        ]
    )
    return peri_scribe.fires.complexes.resolve(declarations, fires_by_identifier)


def is_mixed_case(name: str) -> bool:
    """Return whether *name* contains both uppercase and lowercase letters.

    Args:
        name: The name to check.

    Returns:
        True when the name contains both uppercase and lowercase letters.

    Examples:
        >>> is_mixed_case("Camp Fire")
        True

        >>> is_mixed_case("CAMP FIRE")
        False
    """
    return name.lower() != name and name.upper() != name


def most_common_fire(
    occurrences: list[peri_scribe.models.FireRecord],
) -> peri_scribe.models.Fire:
    """Reduce repeated records of the same fire to a single fire.

    The most common mixed case spelling of the name is kept, or the most common spelling
    when none is mixed case. Ties are broken by the first spelling encountered. The fire
    is active when any of its records is active. The canonical identifier prefers a
    unique fire identifier over a GUID, and every identifier is kept as an alias.

    Args:
        occurrences: The records of a single fire.

    Returns:
        The fire with its preferred name spelling, canonical identifier, every alias,
        and aggregated status.
    """
    name_counts = collections.Counter(
        record.name for record in occurrences if is_mixed_case(record.name)
    )
    if not name_counts:
        name_counts = collections.Counter(record.name for record in occurrences)
    most_common_name = name_counts.most_common(1)[0][0]
    identifiers = frozenset(
        identifier for record in occurrences for identifier in record.identifiers
    )
    status = (
        peri_scribe.models.FireStatus.ACTIVE
        if any(
            record.status is peri_scribe.models.FireStatus.ACTIVE
            for record in occurrences
        )
        else peri_scribe.models.FireStatus.INACTIVE
    )
    return peri_scribe.models.Fire(
        name=most_common_name,
        status=status,
        identifier=peri_scribe.models.canonical_fire_identifier(identifiers),
        aliases=identifiers,
    )
