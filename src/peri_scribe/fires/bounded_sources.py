"""Build complete histories while each raw source group has one bounded lifetime.

[Bounded source work](../../../docs/algorithms/bounded-source-work.md).
"""

from __future__ import annotations

import dataclasses
import functools
import pathlib

import structlog

import peri_scribe.concurrency
import peri_scribe.fires.grouping
import peri_scribe.fires.grouping_cache
import peri_scribe.fires.history
import peri_scribe.fires.incident_history
import peri_scribe.fires.reuse
import peri_scribe.fires.sources
import peri_scribe.geo.catalog
import peri_scribe.models
import peri_scribe.perimeters.border_classification
import peri_scribe.perimeters.classification_data


logger = structlog.get_logger()
SOURCE_WORK_BYTES = 128 * 1024 * 1024


@dataclasses.dataclass(frozen=True, kw_only=True)
class Rows:
    """Retain published-scale rows after their raw evidence has been released."""

    perimeters: list[dict[str, object]]
    points: list[dict[str, object]]
    incidents: list[dict[str, object]]


@dataclasses.dataclass(frozen=True, kw_only=True)
class CompletedFire:
    """Carry only output rows and scalar classification out of a worker."""

    rows: Rows
    classification: peri_scribe.models.FireClassification | None


def prepare_groups(
    catalog: peri_scribe.geo.catalog.Catalog,
) -> peri_scribe.fires.sources.FireRecordGroups:
    """Resolve exact grouping and global ownership from bounded detailed reads.

    Args:
        catalog: Complete compact metadata under pinned source-cache transactions.

    Returns:
        Metadata records and exact fire identities, with global complex links resolved.
    """
    records = [row.record for row in catalog.read.rows]
    positions = {id(record): index for index, record in enumerate(records)}

    def calculate(block: list[peri_scribe.models.FireRecord]) -> list[list[int]]:
        """Retire each conservative block's coordinates after its partition is known.

        Args:
            block: A subset of the retained metadata record objects in source order.

        Returns:
            The exact partition in local occurrence positions.
        """
        return peri_scribe.fires.grouping.group_fire_record_indices(
            catalog.records([positions[id(record)] for record in block]),
        )

    groups = peri_scribe.fires.grouping_cache.grouped_indices(
        records,
        [entry.row["evidence_fingerprint"] for entry in catalog.entries],
        str(peri_scribe.fires.grouping.FIRE_PROXIMITY_TOLERANCE.m_as("degrees")),
        calculate,
    )
    return peri_scribe.fires.sources.assemble_groups(
        catalog.read,
        groups,
        observations=catalog.observations(),
        warn=False,
    )


def load_boundaries(
    year_directory: pathlib.Path,
) -> peri_scribe.perimeters.classification_data.Boundaries | None:
    """Keep missing administrative evidence on the existing incomplete-output path.

    Args:
        year_directory: The year containing the administrative boundary input.

    Returns:
        Shared immutable boundaries with worker-local prepared indexes, or None.
    """
    try:
        return peri_scribe.perimeters.border_classification.load_boundaries(
            year_directory,
        )
    except OSError, RuntimeError, ValueError:
        logger.warning("Skipping border classification", exc_info=True)
        return None


def build_fire(
    position: int,
    *,
    catalog: peri_scribe.geo.catalog.Catalog,
    groups: peri_scribe.fires.sources.FireRecordGroups,
    keys: dict[int, str],
    cached: dict[int, Rows],
    classifications: dict[int, peri_scribe.models.FireClassification],
    boundaries: peri_scribe.perimeters.classification_data.Boundaries | None,
) -> CompletedFire:
    """Consume one fire's raw evidence and return detached completed rows.

    Args:
        position: Original position in the complete resolved fire inventory.
        catalog: The source lease retained until every worker settles.
        groups: Global identities and complex ownership over compact records.
        keys: Complete provenance/dependency identities by fire object identity.
        cached: Authenticated complete prior output rows eligible for reuse.
        classifications: Valid cached scalar classifications, read by the owner.
        boundaries: Exact border evidence or None when unavailable.

    Returns:
        Output rows and classification with no retained raw source containers.
    """
    fire = groups.fires[position]
    read = catalog.hydrate(groups.groups[position])
    local_group = tuple(range(len(read.rows)))
    records = [row.record for row in read.rows]
    peri_scribe.fires.grouping.warn_for_inconsistent_fires(
        records,
        [list(local_group)],
        [fire],
        geometry_keys=read.geometry_keys,
    )
    if peri_scribe.fires.sources.fire_is_complex_parent(
        groups,
        groups.groups[position],
    ):
        return CompletedFire(
            rows=Rows(perimeters=[], points=[], incidents=[]),
            classification=None,
        )
    classification = classifications.get(id(fire))
    if classification is None and boundaries is not None:
        classification = peri_scribe.perimeters.border_classification.classify_fire(
            records=records,
            record_paths=list(read.paths),
            boundaries=boundaries,
            geometry_keys=read.geometry_keys,
        )
    if id(fire) in cached:
        return CompletedFire(rows=cached[id(fire)], classification=classification)
    perimeters, points = peri_scribe.fires.history.history_rows_for_fire(
        fire,
        local_group,
        list(read.rows),
        list(read.paths),
        sources_directory=catalog.directory,
        classification=classification,
    )
    for row in (*perimeters, *points):
        row[peri_scribe.fires.reuse.KEY_COLUMN] = keys[id(fire)]
    local = peri_scribe.fires.sources.FireRecordGroups(
        records=tuple(records),
        record_paths=read.paths,
        fires=(fire,),
        groups=(local_group,),
        complex_identifiers=frozenset(),
        source_paths=read.source_paths,
        geometry_keys=read.geometry_keys,
    )
    incidents = peri_scribe.fires.incident_history.incident_layer_rows(
        read,
        local,
        catalog.directory,
        derivation_keys=keys,
    )
    return CompletedFire(
        rows=Rows(perimeters=perimeters, points=points, incidents=incidents),
        classification=classification,
    )


def build_rows(
    catalog: peri_scribe.geo.catalog.Catalog,
    groups: peri_scribe.fires.sources.FireRecordGroups,
    keys: dict[int, str],
    year_directory: pathlib.Path,
    *,
    cached: dict[int, Rows],
    classifications: dict[int, peri_scribe.models.FireClassification],
) -> tuple[Rows, dict[int, peri_scribe.models.FireClassification]]:
    """Admit detailed source work by bytes independently of ordered output delivery.

    Args:
        catalog: Pinned compact metadata and on-demand detailed source readers.
        groups: The complete exact partition with resolved ownership.
        keys: Complete fire evidence and dependency fingerprints.
        year_directory: The year containing administrative boundary evidence.
        cached: Complete authenticated prior histories eligible for reuse.
        classifications: Cached classifications loaded on the SQLite owner's thread.

    Returns:
        Ordered layer rows and scalar classifications.
    """
    boundaries = load_boundaries(year_directory)
    perimeters = []
    points = []
    incidents = []
    completed_classifications = {}

    def weight(position: int) -> int:
        """Account for distinct canonical payloads before a worker hydrates them.

        Args:
            position: Original fire position in the metadata inventory.

        Returns:
            Canonical encoded input bytes needed by that fire.
        """
        return catalog.weight(groups.groups[position])

    with peri_scribe.concurrency.ordered_parallel_map(
        functools.partial(
            build_fire,
            catalog=catalog,
            groups=groups,
            keys=keys,
            cached=cached,
            classifications=classifications,
            boundaries=boundaries,
        ),
        range(len(groups.fires)),
        max_workers=peri_scribe.fires.history.HISTORY_ROW_WORKER_COUNT,
        max_pending=peri_scribe.fires.history.HISTORY_TASK_BUFFER_SIZE,
        weight=weight,
        max_weight=SOURCE_WORK_BYTES,
    ) as results:
        for fire, completed in zip(groups.fires, results, strict=True):
            perimeters.extend(completed.rows.perimeters)
            points.extend(completed.rows.points)
            incidents.extend(completed.rows.incidents)
            if completed.classification is not None:
                completed_classifications[id(fire)] = completed.classification
    return (
        Rows(perimeters=perimeters, points=points, incidents=incidents),
        completed_classifications,
    )
