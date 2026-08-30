"""Reading fire records from GeoPackage files and listing the distinct fires."""

from __future__ import annotations

import concurrent.futures
import dataclasses
import os
import pathlib

import peri_scribe.exceptions
import peri_scribe.fire_grouping
import peri_scribe.geo_package
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


@dataclasses.dataclass(frozen=True, kw_only=True)
class ReadFireSources:
    """Fire rows, memberships, and source files read from a source directory."""

    rows: tuple[peri_scribe.geo_package.FireRowRecord, ...]
    paths: tuple[pathlib.Path, ...]
    memberships: tuple[peri_scribe.models.ComplexMembership, ...]


def read_geopackage(
    path: pathlib.Path,
) -> peri_scribe.geo_package.GeopackageContents:
    """Read one GeoPackage, translating read failures into a readable message.

    The snapshot's record cache is used when it is fresh, so repeated reads of the
    stored snapshots (for the fire index and derived history) do not re-decode files
    whose contents are already cached.

    Args:
        path: The GeoPackage file to read.

    Returns:
        The file's fire rows and complex memberships.

    Raises:
        SystemExit: If the GeoPackage cannot be read.
        UnknownLayerError: If a layer does not correspond to a configured feed.
    """
    try:
        return peri_scribe.geo_package.read_geopackage_cached(path)
    except peri_scribe.exceptions.UnknownLayerError:
        raise
    except Exception as error:
        # Fail fast with a readable message if a GeoPackage is unreadable.
        message = f"Failed to read {path}: {error}"
        raise SystemExit(message) from error


def read_fire_sources(directory: pathlib.Path) -> ReadFireSources:
    """Read the fire rows and complex memberships under *directory* in one pass.

    Every GeoPackage file anywhere below *directory* is read, so snapshots stored under
    ``sources/{feed}/{serial}.gpkg`` are all found. Each file is read once and its rows
    and memberships are collected together, so the two never need to agree on ordering
    from separate passes.

    Args:
        directory: The directory tree holding GeoPackage files with fire data.

    Returns:
        The fire rows, their source files, and the complex memberships.
    """
    files = list(peri_scribe.snapshots.geo_package_files(directory))
    # GeoPackage reads release the GIL, so the files are read in parallel and the
    # results are collected in file order to keep rows, paths, and memberships aligned.
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=os.cpu_count() or 1,
    ) as executor:
        contents_by_file = list(executor.map(read_geopackage, files))
    rows: list[peri_scribe.geo_package.FireRowRecord] = []
    paths: list[pathlib.Path] = []
    memberships: list[peri_scribe.models.ComplexMembership] = []
    for path, contents in zip(files, contents_by_file, strict=True):
        rows.extend(contents.rows)
        paths.extend([path] * len(contents.rows))
        memberships.extend(contents.memberships)
    return ReadFireSources(
        rows=tuple(rows),
        paths=tuple(paths),
        memberships=tuple(memberships),
    )


def group_fire_sources(read: ReadFireSources) -> FireRecordGroups:
    """Group the read fire rows and memberships into distinct fires.

    Fire records sharing any identifier are the same fire; records sharing only a name
    are merged only when they are spatially compatible, so distinct fires that happen to
    share a name (e.g. "Canyon" in California vs. Alaska) stay separate. The most common
    spelling of each name is the one kept, and a fire is active when any of its records
    is active. A fire whose records are spatially or temporally spread out is reported
    with a warning. Fires that are complex parents are represented by a FireComplex
    instead of listed as fires, and member fires carry a circular link to their complex.

    Args:
        read: The fire rows, their source files, and the complex memberships.

    Returns:
        The records, their source files, the grouped fires, and the identifiers of the
        fires that are complex parents.
    """
    records = [row.record for row in read.rows]
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
        list(read.memberships),
        fires_by_identifier,
    )
    complex_identifiers = {complex_.identifier for complex_ in complexes}
    return FireRecordGroups(
        records=tuple(records),
        record_paths=read.paths,
        fires=tuple(fires),
        groups=tuple(tuple(group) for group in groups),
        complex_identifiers=frozenset(complex_identifiers),
    )


def fire_record_groups(directory: pathlib.Path) -> FireRecordGroups:
    """Read and group the fire records under *directory*.

    Args:
        directory: The directory tree holding GeoPackage files with fire data.

    Returns:
        The records, their source files, the grouped fires, and the identifiers of the
        fires that are complex parents.
    """
    return group_fire_sources(read_fire_sources(directory))


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
        One ``(FireSources, record indices)`` pair per non-complex fire, in group order.
    """
    sources: list[tuple[peri_scribe.models.FireSources, tuple[int, ...]]] = []
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
                            {record_groups.record_paths[index] for index in group},
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
    return [source for source, _group in non_complex_fire_sources(record_groups)]


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
