"""Orchestration logic for peri_scribe — feed fetching, fire listing, output writing.

This module contains the core business logic shared across all user interfaces.
"""

from __future__ import annotations

import collections
import pathlib

import arcgis.features
import arcgis.gis
import structlog

import peri_scribe.exceptions
import peri_scribe.geo_data
import peri_scribe.models
import peri_scribe.output


logger = structlog.get_logger()


def fetch_all_feeds(
    output_dir: pathlib.Path | None = None,
) -> pathlib.Path:
    """Fetch all configured feeds and write them to a single GeoPackage.

    Args:
        output_dir: Directory in which to create the output file. Defaults to the
            current working directory.

    Returns:
        The path to the output GeoPackage file.

    Raises:
        SystemExit: If a feed is unreachable.
    """
    if output_dir is None:
        output_dir = pathlib.Path.cwd()
    output_path = output_dir / peri_scribe.models.OUTPUT_FILENAME
    logger.info("Output file", path=output_path)
    gis = arcgis.gis.GIS()
    layers: list[peri_scribe.models.LayerData] = []
    for feed in peri_scribe.models.FEEDS:
        logger.info("Fetching", feed=feed.name, url=feed.url)
        try:
            layer = arcgis.features.FeatureLayer(feed.url, gis)
            feature_set = peri_scribe.geo_data.query_with_retry(
                feed.name,
                layer,
            )
            geodataframe = peri_scribe.geo_data.dataframe_for_layer(
                feed,
                layer,
                feature_set,
            )
        except Exception as error:
            # Fail fast with a readable message if a feed is unreachable.
            message = f"Failed to fetch {feed.name}: {error}"
            raise SystemExit(message) from error
        logger.info("Received features", count=len(feature_set.features))
        logger.info(
            "Prepared feed",
            feed=feed.name,
            rows=len(geodataframe),
            crs=geodataframe.crs,
        )
        layers.append(
            peri_scribe.models.LayerData(name=feed.name, dataframe=geodataframe),
        )
    logger.info("Writing layers", count=len(layers), path=output_path)
    peri_scribe.output.write_geopackage(output_path, layers)
    logger.info("Done")
    return output_path


def list_fires(
    geo_package_paths: tuple[pathlib.Path, ...],
) -> list[peri_scribe.models.Fire]:
    """Collect the fires in the given GeoPackage files into a list.

    Fire records are identified by their stable identifier when they have one, falling
    back to a normalized name only when a record has no identifier, so that different
    fires that happen to share a name are not merged (e.g. "Canyon" in California vs.
    Alaska). The most common spelling of each name is the one kept, and a fire is active
    when any of its records is active. Fires that are complex parents are represented by
    a FireComplex instead of listed as fires, and member fires carry a circular link to
    their complex.

    Args:
        geo_package_paths: Paths to GeoPackage files containing fire data.

    Returns:
        The fires, in the order first encountered.

    Raises:
        SystemExit: If a GeoPackage file cannot be read.
        UnknownLayerError: If a layer does not correspond to a configured feed.
    """
    records: list[peri_scribe.models.Fire] = []
    memberships: list[peri_scribe.models.ComplexMembership] = []
    for path in geo_package_paths:
        try:
            records.extend(peri_scribe.geo_data.fire_names(path))
            memberships.extend(peri_scribe.geo_data.complex_memberships(path))
        except peri_scribe.exceptions.UnknownLayerError:
            raise
        except Exception as error:
            # Fail fast with a readable message if a GeoPackage is unreadable.
            message = f"Failed to read {path}: {error}"
            raise SystemExit(message) from error
    groups = group_fire_records(records)
    fires = [most_common_fire(group) for group in groups]
    fires_by_identifier: dict[str, peri_scribe.models.Fire] = {}
    for group, fire in zip(groups, fires, strict=True):
        for record in group:
            if record.identifier is not None:
                fires_by_identifier.setdefault(record.identifier, fire)
    complexes = fire_complexes(memberships, fires_by_identifier)
    complex_identifiers = {complex_.identifier for complex_ in complexes}
    return [
        fire
        for fire, group in zip(fires, groups, strict=True)
        if not any(record.identifier in complex_identifiers for record in group)
    ]


def normalize_fire_name(name: str) -> str:
    """Normalize a fire name for comparison.

    Names are casefolded, stripped of surrounding whitespace, and internal whitespace
    runs are collapsed to a single space.

    Args:
        name: The fire name to normalize.

    Returns:
        The normalized name.
    """
    return " ".join(name.casefold().split())


def group_fire_records(
    records: list[peri_scribe.models.Fire],
) -> list[list[peri_scribe.models.Fire]]:
    """Group fire records that identify the same fire into a single list.

    Records with the same normalized identifier are the same fire, even when their names
    differ (e.g. "Crosswhite" and "0445 CROSSWHITE"). Records with the same normalized
    name are the same fire only when at least one of them has no identifier, since names
    alone are unreliable: different fires can share a name (e.g. "Canyon" in California
    vs. Alaska), and the same fire can appear with and without an identifier (e.g.
    California FIRIS records vs. WFIGS records for the same fire).

    Args:
        records: The fire records to group.

    Returns:
        The groups of records, in the order first encountered.
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

    by_identifier: dict[str, int] = {}
    by_name: dict[str, int] = {}
    by_unidentified_name: dict[str, int] = {}
    for index, fire in enumerate(records):
        name = normalize_fire_name(fire.name)
        by_name.setdefault(name, index)
        if fire.identifier is not None:
            if fire.identifier in by_identifier:
                union(index, by_identifier[fire.identifier])
            else:
                by_identifier[fire.identifier] = index
            if name in by_unidentified_name:
                union(index, by_unidentified_name[name])
        else:
            if name in by_unidentified_name:
                union(index, by_unidentified_name[name])
            else:
                by_unidentified_name[name] = index
            union(index, by_name[name])
    groups_by_root: dict[int, list[peri_scribe.models.Fire]] = {}
    order: list[int] = []
    for index, fire in enumerate(records):
        root = find(index)
        if root not in groups_by_root:
            order.append(root)
            groups_by_root[root] = []
        groups_by_root[root].append(fire)
    return [groups_by_root[root] for root in order]


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
    """
    return name.lower() != name and name.upper() != name


def most_common_fire(
    occurrences: list[peri_scribe.models.Fire],
) -> peri_scribe.models.Fire:
    """Reduce repeated records of the same fire to a single fire.

    The most common mixed case spelling of the name is kept, or the most common
    spelling when none is mixed case. Ties are broken by the first spelling
    encountered. The fire is active when any of its records is active.

    Args:
        occurrences: The records of a single fire, deduplicated by case-folded
            name.

    Returns:
        The fire with its preferred name spelling, its first identifier, and
        aggregated status.
    """
    name_counts = collections.Counter(
        fire.name for fire in occurrences if is_mixed_case(fire.name)
    )
    if not name_counts:
        name_counts = collections.Counter(fire.name for fire in occurrences)
    most_common_name = name_counts.most_common(1)[0][0]
    identifier = next(
        (fire.identifier for fire in occurrences if fire.identifier is not None),
        None,
    )
    status = (
        peri_scribe.models.FireStatus.ACTIVE
        if any(
            fire.status is peri_scribe.models.FireStatus.ACTIVE for fire in occurrences
        )
        else peri_scribe.models.FireStatus.INACTIVE
    )
    return peri_scribe.models.Fire(
        name=most_common_name,
        status=status,
        identifier=identifier,
    )
