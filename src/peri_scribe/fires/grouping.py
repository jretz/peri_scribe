"""Grouping fire records that identify the same fire.

[Grouping and ownership](../../../docs/algorithms/fire-grouping-and-ownership.md)
"""

from __future__ import annotations

import collections
import datetime
import typing

import shapely
import structlog

import peri_scribe.fires.complexes
import peri_scribe.models
from measurement_units import units


if typing.TYPE_CHECKING:
    import pint


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


def nearby_pairs(
    geometries: list[shapely.Geometry],
    *,
    tolerance: pint.Quantity[float],
) -> typing.Iterator[tuple[int, int]]:
    """Yield the index pairs of *geometries* within *tolerance*.

    A spatial index avoids comparing distant geometries. Work still depends on the
    number of nearby pairs, which can grow quadratically when every geometry is near
    every other one. Each nonempty geometry is paired with itself, and each distinct
    pair appears in both directions, so callers can treat the result as a directed
    graph's adjacency and skip self-pairs.

    Args:
        geometries: The geometries to compare.
        tolerance: The maximum distance, in degrees, that counts as nearby.

    Yields:
        Pairs of indices whose geometries are within the tolerance.
    """
    tree = shapely.STRtree(geometries)
    pairs = tree.query(
        geometries,
        predicate="dwithin",
        distance=tolerance.m_as("degrees"),
    )
    for left, right in zip(pairs[0], pairs[1], strict=True):
        yield int(left), int(right)


def records_span_distant_locations(
    records: list[peri_scribe.models.FireRecord],
    group: list[int],
) -> bool:
    """Return whether a record in *group* disagrees with the rest on location.

    A record disagrees when the rest of the group has a geometry and the record has
    none, or when none of the other records' geometries is within the outlier tolerance;
    the distance from a record to the union of the others is the minimum distance to any
    one of them.

    Args:
        records: The records that were grouped.
        group: The record indices of one fire.

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
    matched_indices = matched_within_outlier_tolerance(members)
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

    Returns:
        The indices of the members that have another member within the outlier
        tolerance.
    """
    classes: dict[bytes, list[tuple[int, shapely.Geometry]]] = {}
    for member in members:
        classes.setdefault(member[1].wkb, []).append(member)
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
) -> None:
    """Log location inconsistencies at info level and long time spans at debug level.

    A fire whose member records disagree on location or span a long observation range
    may be two fires that were merged by name. Each log entry names the fire so the
    grouping can be inspected.

    Args:
        records: The records that were grouped.
        groups: The record indices of each fire, aligned with *fires*.
        fires: The fires, aligned with *groups*.
    """
    for fire, group in zip(fires, groups, strict=True):
        if records_span_distant_locations(records, group):
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
) -> list[list[int]]:
    """Group the indices of fire records that identify the same fire.

    Each group holds the indices of its records instead of the records themselves, so
    callers can look up associated data such as each record's source file.

    Args:
        records: The fire records to group.

    Returns:
        The groups of record indices, in the order first encountered.
    """
    parent = list(range(len(records)))

    def find(index: int) -> int:
        """Resolve a record's shared representative for group membership checks.

        Args:
            index: The record index whose group representative is needed.

        Returns:
            The representative record index for the group.
        """
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        """Keep records identified as the same fire in a shared group.

        Args:
            left: One record index whose group should be joined.
            right: The other record index whose group should be joined.
        """
        root_left = find(left)
        root_right = find(right)
        if root_left != root_right:
            parent[root_right] = root_left

    # Records sharing any identifier are the same fire.
    by_identifier: dict[str, int] = {}
    for index, record in enumerate(records):
        for identifier in record.identifiers:
            if identifier in by_identifier:
                union(index, by_identifier[identifier])
            else:
                by_identifier[identifier] = index

    merge_records_by_name(records, union)

    groups_by_root: dict[int, list[int]] = {}
    order: list[int] = []
    for index in range(len(records)):
        root = find(index)
        if root not in groups_by_root:
            order.append(root)
            groups_by_root[root] = []
        groups_by_root[root].append(index)
    return [groups_by_root[root] for root in order]


def merge_records_by_name(
    records: list[peri_scribe.models.FireRecord],
    union: typing.Callable[[int, int], None],
) -> None:
    """Merge records that share a name and are spatially compatible.

    The same fire can acquire different identifiers, for example when a new mapping
    receives a new GUID. A shared name and compatible geometries can still connect those
    records. Fires with the same name in different regions stay separate because their
    geometries are too far apart.

    A spatial index limits comparisons to nearby geometries. A name shared by distant
    fires, such as "Canyon" in California and Alaska, therefore does not require
    comparing every pair.

    Args:
        records: The records to merge.
        union: The union-find union used by the grouping.
    """
    by_name: dict[str, list[int]] = {}
    for index, record in enumerate(records):
        for name in record.names:
            by_name.setdefault(name, []).append(index)
    for indices in by_name.values():
        members: list[tuple[int, shapely.Geometry]] = []
        for index in indices:
            geometry = records[index].geometry
            if geometry is not None and not geometry.is_empty:
                members.append((index, geometry))
        if len(members) < MINIMUM_SPATIAL_GEOMETRIES:
            continue
        # Snapshots often repeat exactly the same perimeter. Those records already lie
        # within the tolerance of one another, so join them first and compare one
        # representative per class. Joining two representatives then connects every
        # record in both classes without repeating the geometry comparisons.
        classes: dict[bytes, list[tuple[int, shapely.Geometry]]] = {}
        for member in members:
            classes.setdefault(member[1].wkb, []).append(member)
        representatives = [class_members[0] for class_members in classes.values()]
        for class_members in classes.values():
            for index, _geometry in class_members[1:]:
                union(class_members[0][0], index)
        if len(representatives) >= MINIMUM_SPATIAL_GEOMETRIES:
            for left, right in nearby_pairs(
                [geometry for _index, geometry in representatives],
                tolerance=FIRE_PROXIMITY_TOLERANCE,
            ):
                if left != right:
                    union(representatives[left][0], representatives[right][0])


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
