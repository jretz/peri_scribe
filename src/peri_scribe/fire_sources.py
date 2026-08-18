"""Reading fire records from GeoPackage files and listing the distinct fires."""

from __future__ import annotations

import dataclasses
import pathlib

import peri_scribe.exceptions
import peri_scribe.fire_grouping
import peri_scribe.geo_data
import peri_scribe.models
import peri_scribe.snapshots


@dataclasses.dataclass(frozen=True, kw_only=True)
class FireRecordGroups:
    """Fire records grouped by fire, with each record's source file."""

    records: tuple[peri_scribe.models.FireRecord, ...]
    record_paths: tuple[pathlib.Path, ...]
    fires: tuple[peri_scribe.models.Fire, ...]
    groups: tuple[tuple[int, ...], ...]
    complex_identifiers: frozenset[str]


def fire_record_groups(directory: pathlib.Path) -> FireRecordGroups:
    """Read and group the fire records under *directory*.

    Every GeoPackage file anywhere below *directory* is read, so snapshots stored under
    ``sources/{feed}/{serial}.gpkg`` are all found. Fire records sharing any identifier
    are the same fire; records sharing only a name are merged only when they are
    spatially compatible, so distinct fires that happen to share a name (e.g. "Canyon"
    in California vs. Alaska) stay separate. The most common spelling of each name is
    the one kept, and a fire is active when any of its records is active. A fire whose
    records are spatially or temporally spread out is reported with a warning. Fires
    that are complex parents are represented by a FireComplex instead of listed as
    fires, and member fires carry a circular link to their complex.

    Args:
        directory: The directory tree holding GeoPackage files with fire data.

    Returns:
        The records, their source files, the grouped fires, and the identifiers of the
        fires that are complex parents.

    Raises:
        SystemExit: If a GeoPackage file cannot be read.
        UnknownLayerError: If a layer does not correspond to a configured feed.
    """
    records: list[peri_scribe.models.FireRecord] = []
    record_paths: list[pathlib.Path] = []
    memberships: list[peri_scribe.models.ComplexMembership] = []
    for path in peri_scribe.snapshots.geo_package_files(directory):
        try:
            file_records = list(peri_scribe.geo_data.fire_records(path))
            file_memberships = list(
                peri_scribe.geo_data.complex_memberships(path),
            )
        except peri_scribe.exceptions.UnknownLayerError:
            raise
        except Exception as error:
            # Fail fast with a readable message if a GeoPackage is unreadable.
            message = f"Failed to read {path}: {error}"
            raise SystemExit(message) from error
        records.extend(file_records)
        record_paths.extend([path] * len(file_records))
        memberships.extend(file_memberships)
    groups = peri_scribe.fire_grouping.group_fire_record_indices(records)
    fires = [
        peri_scribe.fire_grouping.most_common_fire(
            [records[index] for index in group],
        )
        for group in groups
    ]
    peri_scribe.fire_grouping.warn_for_inconsistent_fires(records, groups, fires)
    fires_by_identifier: dict[str, peri_scribe.models.Fire] = {}
    for group, fire in zip(groups, fires, strict=True):
        for index in group:
            for identifier in records[index].identifiers:
                fires_by_identifier.setdefault(identifier, fire)
    complexes = peri_scribe.fire_grouping.fire_complexes(
        memberships,
        fires_by_identifier,
    )
    complex_identifiers = {complex_.identifier for complex_ in complexes}
    return FireRecordGroups(
        records=tuple(records),
        record_paths=tuple(record_paths),
        fires=tuple(fires),
        groups=tuple(tuple(group) for group in groups),
        complex_identifiers=frozenset(complex_identifiers),
    )


def fire_is_complex_parent(
    record_groups: FireRecordGroups,
    group: tuple[int, ...],
) -> bool:
    """Return whether the fire identified by *group* is a complex parent.

    Args:
        record_groups: The grouped fire records.
        group: The record indices of one fire.

    Returns:
        True when any record in the group identifies the fire as a complex parent.
    """
    return any(
        identifier in record_groups.complex_identifiers
        for index in group
        for identifier in record_groups.records[index].identifiers
    )


def non_complex_fire_sources(
    record_groups: FireRecordGroups,
) -> list[tuple[peri_scribe.models.FireSources, tuple[int, ...]]]:
    """Return the non-complex fires with their record indices and source files.

    Args:
        record_groups: The grouped fire records.

    Returns:
        One `(FireSources, record indices)` pair per non-complex fire, in group order.
    """
    sources: list[
        tuple[peri_scribe.models.FireSources, tuple[int, ...]]
    ] = []
    for fire, group in zip(
        record_groups.fires,
        record_groups.groups,
        strict=True,
    ):
        if fire_is_complex_parent(record_groups, group):
            continue
        sources.append(
            (
                peri_scribe.models.FireSources(
                    fire=fire,
                    paths=tuple(
                        sorted(
                            {
                                record_groups.record_paths[index]
                                for index in group
                            },
                        ),
                    ),
                ),
                group,
            ),
        )
    return sources


def fire_sources_from_groups(
    record_groups: FireRecordGroups,
) -> list[peri_scribe.models.FireSources]:
    """Return the non-complex fires from *record_groups*.

    Args:
        record_groups: The grouped fire records.

    Returns:
        The non-complex fires in group order.
    """
    return [
        source
        for source, _group in non_complex_fire_sources(record_groups)
    ]


def fire_sources(directory: pathlib.Path) -> list[peri_scribe.models.FireSources]:
    """Collect the distinct fires and their source files under *directory*.

    Each result records the GeoPackage files whose rows mention the fire, so the same
    fire can be traced back to every snapshot it appears in. Complex parents are
    represented by a FireComplex instead of being listed as fires.

    Args:
        directory: The directory tree holding GeoPackage files with fire data.

    Returns:
        The fires, in the order first encountered, each with the paths of the GeoPackage
        files that mention it.
    """
    return fire_sources_from_groups(fire_record_groups(directory))
