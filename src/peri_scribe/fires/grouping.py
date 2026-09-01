"""Grouping fire records that identify the same fire."""

from __future__ import annotations

import collections
import datetime
import typing

import shapely
import structlog

import peri_scribe.models


logger = structlog.get_logger()


# Two fire geometries are treated as the same fire when they overlap or the gap between
# them is within this tolerance. It is expressed in degrees, which is roughly 5.5 km.
FIRE_PROXIMITY_TOLERANCE_IN_DEGREES = 0.05

# A fire whose records are farther apart than this is reported as possibly two fires
# that were merged. It is far looser than the proximity tolerance so that a point
# location moving between snapshots does not raise a warning.
FIRE_OUTLIER_TOLERANCE_IN_DEGREES = 1.0

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
    tolerance_in_degrees: float,
) -> typing.Iterator[tuple[int, int]]:
    """Yield the index pairs of *geometries* within *tolerance_in_degrees*.

    A spatial index limits the comparisons to geometries that are actually close, so
    the number of pairs grows with the number of nearby geometries rather than with
    the square of the list length. Each geometry is paired with itself, and each
    distinct pair appears in both directions, so callers can treat the result as the
    adjacency of a directed graph and skip self-pairs.

    Args:
        geometries: The geometries to compare.
        tolerance_in_degrees: The maximum distance, in degrees, that counts as nearby.

    Yields:
        Pairs of indices whose geometries are within the tolerance.
    """
    tree = shapely.STRtree(geometries)
    pairs = tree.query(
        geometries,
        predicate="dwithin",
        distance=tolerance_in_degrees,
    )
    for left, right in zip(pairs[0], pairs[1], strict=True):
        yield int(left), int(right)


def records_span_distant_locations(
    records: list[peri_scribe.models.FireRecord],
    group: list[int],
) -> bool:
    """Return whether a record in *group* disagrees with the rest on location.

    A record disagrees when the rest of the group has a geometry and the record has
    none, or when none of the other records' geometries is within the outlier
    tolerance; the distance from a record to the union of the others is the minimum
    distance to any one of them.

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

    Byte-identical geometries are within the tolerance of one another, so every member
    of a multi-member identical-geometry class has a match and the rest of the
    comparisons use one representative per class. Each representative is checked against
    the others until one is found within the tolerance: a fire's own records are almost
    always all near one another, so the first comparison settles the common case and
    only an actual outlier requires checking every other representative.

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
        for other_position, (other_index, other_geometry) in enumerate(
            representatives,
        ):
            if position == other_position:
                continue
            if shapely.dwithin(
                geometry,
                other_geometry,
                FIRE_OUTLIER_TOLERANCE_IN_DEGREES,
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
    """Log a warning for each fire whose records are spread across space or time.

    A fire whose member records disagree on location or span a long observation range
    may be two fires that were merged by name. The warning names the fire so the
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
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
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

    Records sharing a name are grouped by spatial proximity, whether or not they have
    identifiers. A same-named fire is the same fire wherever it is mapped, even when
    different rows carry different identifiers (for example a re-mapping that received a
    new GUID), so any two same-named records whose geometries are compatible are one
    fire. Fires with the same name in different regions stay separate because their
    geometries are not compatible. A spatial index limits the compatibility checks to
    records whose geometries are actually close, so a name shared by many distant fires
    (e.g. "Canyon" in California vs. Alaska) does not make the grouping quadratic.

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
        # Records with byte-identical geometry are trivially within the tolerance of one
        # another (a fire mapped repeatedly carries the same perimeter in many
        # snapshots), so each identical-geometry class is unioned as a unit and the
        # spatial index compares one representative per class. Uniting the class's
        # representative with another class's representative connects every member of
        # both classes through the class unions.
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
                tolerance_in_degrees=FIRE_PROXIMITY_TOLERANCE_IN_DEGREES,
            ):
                if left != right:
                    union(representatives[left][0], representatives[right][0])


def fire_complexes(
    memberships: list[peri_scribe.models.ComplexMembership],
    fires_by_identifier: dict[str, peri_scribe.models.Fire],
) -> list[peri_scribe.models.FireComplex]:
    """Build the complexes named by *memberships*, linking their member fires.

    Each complex is linked to every fire it contains, and each linked fire points back
    at the complex. Memberships that reference an unidentified fire are skipped with a
    warning.

    Args:
        memberships: The observed complex memberships.
        fires_by_identifier: The identified fires, keyed by every identifier
            each fire is known by.

    Returns:
        The complexes, in the order first encountered.
    """
    fires_by_complex: dict[str, set[peri_scribe.models.Fire]] = {}
    names_by_complex: dict[str, str] = {}
    for membership in memberships:
        fire = fires_by_identifier.get(membership.fire_identifier)
        if fire is None:
            logger.warning(
                "Complex membership references an unidentified fire",
                fire_identifier=membership.fire_identifier,
                complex_identifier=membership.complex_identifier,
            )
            continue
        fires_by_complex.setdefault(
            membership.complex_identifier,
            set(),
        ).add(fire)
        names_by_complex.setdefault(
            membership.complex_identifier,
            membership.complex_name,
        )
    return [
        peri_scribe.models.FireComplex(
            name=names_by_complex[complex_identifier],
            identifier=complex_identifier,
            fires=frozenset(fires_by_complex[complex_identifier]),
        )
        for complex_identifier in fires_by_complex
    ]


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
