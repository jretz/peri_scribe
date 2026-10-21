"""Prepare source-index metadata while hydrating only affected snapshot closures.

[Incremental preparation](../../../docs/algorithms/incremental-grouping.md)
[Retained-index proof](../../../tests/formal/lean/retained_source_index.md)
"""

from __future__ import annotations

import collections
import collections.abc
import dataclasses
import functools
import operator
import pathlib
import typing

import pydantic
import structlog

import peri_scribe.fires.grouping
import peri_scribe.fires.grouping_cache
import peri_scribe.fires.sources
import peri_scribe.geo.database
import peri_scribe.geo.fingerprints
import peri_scribe.geo.package
import peri_scribe.geo.reading
import peri_scribe.geo.source_summaries
import peri_scribe.models
import peri_scribe.sources.provenance
import peri_scribe.sources.snapshots
import spatial_data.geometry_pool
import spatial_data.product_cache


NAMESPACE = "source-index-reverse-dependencies-v1"
type RowRef = tuple[str, int]
type DependencyKind = typing.Literal["identifier", "name"]
logger = structlog.get_logger()


class DependencyRow(pydantic.BaseModel):
    """Retain exact evidence and tagged incidences for one ordered occurrence."""

    model_config = pydantic.ConfigDict(strict=True, frozen=True, extra="forbid")

    path: str
    position: pydantic.NonNegativeInt
    evidence_key: str
    identifiers: frozenset[str] = frozenset()
    names: frozenset[str] = frozenset()

    @property
    def reference(self) -> RowRef:
        """Identify this occurrence independently of its changing evidence.

        Returns:
            The relative snapshot path and its ordered row position.
        """
        return self.path, self.position


class DependencyIncidence(pydantic.BaseModel):
    """Index all occurrences sharing one identifier or normalized name."""

    model_config = pydantic.ConfigDict(strict=True, frozen=True, extra="forbid")

    kind: DependencyKind
    value: str
    references: tuple[RowRef, ...]


def reverse_for(
    rows: collections.abc.Sequence[DependencyRow],
) -> tuple[DependencyIncidence, ...]:
    """Keep reverse incidences complete, tagged, and deterministic.

    Args:
        rows: Complete occurrence metadata in authoritative order.

    Returns:
        One canonical reverse entry for each distinct tagged value.
    """
    reverse: dict[tuple[DependencyKind, str], list[RowRef]] = collections.defaultdict(
        list,
    )
    for row in rows:
        for kind, values in (("identifier", row.identifiers), ("name", row.names)):
            for value in values:
                reverse[kind, value].append(row.reference)
    return tuple(
        DependencyIncidence(kind=kind, value=value, references=tuple(references))
        for (kind, value), references in sorted(reverse.items())
    )


class DependencyIndex(pydantic.BaseModel):
    """Publish the complete metadata and its validated reverse index together."""

    model_config = pydantic.ConfigDict(strict=True, frozen=True, extra="forbid")

    rows: tuple[DependencyRow, ...]
    reverse: tuple[DependencyIncidence, ...]

    @pydantic.model_validator(mode="after")
    def complete(self) -> typing.Self:
        """Reject missing, duplicate, or inconsistent reverse dependency evidence.

        Returns:
            This complete validated dependency index.

        Raises:
            ValueError: If occurrences repeat or reverse entries omit evidence.
        """
        references = [row.reference for row in self.rows]
        if len(set(references)) != len(references):
            message = "Dependency row references must be unique"
            raise ValueError(message)
        if self.reverse != reverse_for(self.rows):
            message = "Reverse dependencies must exactly cover the source metadata"
            raise ValueError(message)
        return self


def index_from_rows(rows: collections.abc.Sequence[DependencyRow]) -> DependencyIndex:
    """Construct a complete reverse index from ordered compact row evidence.

    Args:
        rows: Every current source occurrence and its full evidence identity.

    Returns:
        A validated current dependency index.
    """
    return DependencyIndex(rows=tuple(rows), reverse=reverse_for(rows))


def changed_rows(
    previous: DependencyIndex | None,
    current: DependencyIndex,
) -> set[RowRef]:
    """Include insertions, deletions, and changed complete evidence as dirty seeds.

    Args:
        previous: The prior complete dependency inventory, if authenticated.
        current: The current complete authenticated metadata.

    Returns:
        Changed references from the union of the old and new universes.
    """
    before = (
        {}
        if previous is None
        else {row.reference: row.evidence_key for row in previous.rows}
    )
    after = {row.reference: row.evidence_key for row in current.rows}
    return {
        reference
        for reference in before.keys() | after.keys()
        if before.get(reference) != after.get(reference)
    }


def affected_rows(
    previous: DependencyIndex | None,
    current: DependencyIndex,
) -> set[RowRef]:
    """Follow old and new incidences so removed bridge rows invalidate both sides.

    Args:
        previous: The authenticated previous inventory, or None for a full rebuild.
        current: The complete current metadata and reverse dependencies.

    Returns:
        Current references in the complete old-plus-new dirty dependency closure.
    """
    current_references = {row.reference for row in current.rows}
    if previous is None:
        return current_references
    reached = changed_rows(previous, current)
    if not reached:
        return set()
    by_reference: dict[RowRef, set[tuple[DependencyKind, str]]] = (
        collections.defaultdict(set)
    )
    reverse: dict[tuple[DependencyKind, str], set[RowRef]] = collections.defaultdict(
        set,
    )
    for index in (previous, current):
        for incidence in index.reverse:
            token = incidence.kind, incidence.value
            reverse[token].update(incidence.references)
            for reference in incidence.references:
                by_reference[reference].add(token)
    pending = list(reached)
    visited: set[tuple[DependencyKind, str]] = set()
    while pending:
        for token in by_reference[pending.pop()]:
            if token in visited:
                continue
            visited.add(token)
            added = reverse[token] - reached
            reached.update(added)
            pending.extend(added)
    return reached & current_references


def cached_index() -> DependencyIndex | None:
    """Require a complete prior reverse manifest before selective preparation.

    Returns:
        The authenticated validated inventory, or None for complete preparation.
    """
    payload = spatial_data.product_cache.get(NAMESPACE, "current")
    if payload is None:
        return None
    try:
        return DependencyIndex.model_validate_json(payload)
    except pydantic.ValidationError:
        logger.info("Ignoring invalid source dependency inventory", exc_info=True)
        return None


@dataclasses.dataclass(frozen=True, kw_only=True)
class IndexRead:
    """Keep payload-free rows separate from complete source preparation objects."""

    directory: pathlib.Path
    rows: tuple[peri_scribe.geo.source_summaries.RowSummary, ...]
    paths: tuple[pathlib.Path, ...]
    positions: tuple[int, ...]
    contents: dict[pathlib.Path, peri_scribe.geo.package.GeopackageContents]
    geometry_pool: spatial_data.geometry_pool.GeometryPool
    source_paths: peri_scribe.sources.provenance.SourcePaths


def index_read(
    directory: pathlib.Path,
    summaries: collections.abc.Mapping[
        pathlib.Path,
        peri_scribe.geo.source_summaries.SnapshotSummary,
    ],
    contents: dict[pathlib.Path, peri_scribe.geo.package.GeopackageContents],
    geometry_pool: spatial_data.geometry_pool.GeometryPool,
    *,
    source_paths: peri_scribe.sources.provenance.SourcePaths | None = None,
) -> IndexRead:
    """Align compact row metadata and provenance once for selective consumers.

    Args:
        directory: The common source provenance root.
        summaries: Every current snapshot in authoritative encounter order.
        contents: Full snapshots already decoded for summary misses.
        geometry_pool: Shared geometries for later selective hydration.
        source_paths: Exact lexical provenance retained by an existing complete read.

    Returns:
        Complete slim rows with their stable per-snapshot positions.
    """
    return IndexRead(
        directory=directory,
        rows=tuple(row for summary in summaries.values() for row in summary.rows),
        paths=tuple(
            path for path, summary in summaries.items() for _row in summary.rows
        ),
        positions=tuple(
            index
            for summary in summaries.values()
            for index in range(len(summary.rows))
        ),
        contents=contents,
        geometry_pool=geometry_pool,
        source_paths=peri_scribe.sources.provenance.for_directory(
            directory,
            source_paths,
        ),
    )


def hydrate_indices(
    read: IndexRead,
    indices: collections.abc.Iterable[int],
) -> dict[int, peri_scribe.geo.package.FireRowRecord]:
    """Batch affected snapshots and validate each selected occurrence's full identity.

    Args:
        read: Slim index evidence and complete snapshots already decoded on misses.
        indices: Current row positions required by grouping or classification.

    Returns:
        Full selected rows; other rows in those snapshots may also be decoded.

    Raises:
        ValueError: If consumed evidence no longer matches its authenticated summary.
    """
    selected = sorted(set(indices))
    missing = sorted({read.paths[index] for index in selected} - read.contents.keys())
    if missing:
        read.contents.update(
            peri_scribe.geo.reading.read_geopackages_cached(
                missing,
                geometry_pool=read.geometry_pool,
                read_fallback=functools.partial(
                    peri_scribe.fires.sources.read_fire_geopackage,
                    geometry_pool=read.geometry_pool,
                ),
            ),
        )
    result = {}
    for index in selected:
        path = read.paths[index]
        contents = read.contents[path]
        ordinal = read.positions[index]
        if ordinal >= len(contents.rows):
            message = "Source summary row count changed during preparation"
            raise ValueError(message)
        row = contents.rows[ordinal]
        if peri_scribe.geo.fingerprints.row_evidence_fingerprint(row) != (
            read.rows[index].row_key
        ):
            message = "Source evidence changed during selective preparation"
            raise ValueError(message)
        result[index] = row
    return result


@dataclasses.dataclass(frozen=True, kw_only=True)
class IndexSources:
    """Metadata-only index preparation, never a complete PreparedSources value."""

    read: IndexRead
    groups: peri_scribe.fires.sources.FireRecordGroups
    evidence_keys: tuple[str, ...]

    def hydrate_groups(
        self,
        requested: tuple[tuple[int, ...], ...],
    ) -> peri_scribe.fires.sources.FireRecordGroups:
        """Materialize complete evidence only for the requested classification groups.

        Args:
            requested: Original group positions whose classification product missed.

        Returns:
            Complete compact groups retaining the original Fire object identities.
        """
        selected = sorted({index for group in requested for index in group})
        rows = hydrate_indices(self.read, selected)
        positions = {original: current for current, original in enumerate(selected)}
        fires = dict(zip(self.groups.groups, self.groups.fires, strict=True))
        return peri_scribe.fires.sources.FireRecordGroups(
            records=tuple(rows[index].record for index in selected),
            record_paths=tuple(self.read.paths[index] for index in selected),
            fires=tuple(fires[group] for group in requested),
            groups=tuple(
                tuple(positions[index] for index in group) for group in requested
            ),
            complex_identifiers=self.groups.complex_identifiers,
            geometry_keys=self.read.geometry_pool.geometry_keys,
            source_paths=self.read.source_paths,
        )


def dependency_index(read: IndexRead) -> DependencyIndex:
    """Retain occurrence locations and exact metadata dependencies without payloads.

    Args:
        read: Complete slim rows in authoritative encounter order.

    Returns:
        The current complete reverse dependency inventory.
    """
    rows = []
    for row, path, position in zip(read.rows, read.paths, read.positions, strict=True):
        rows.append(
            DependencyRow(
                path=read.source_paths.relative(path),
                position=position,
                evidence_key=row.row_key,
                identifiers=row.record.identifiers,
                names=row.record.names,
            ),
        )
    values = tuple(rows)
    references = [row.reference for row in values]
    if len(set(references)) != len(references):
        return index_from_rows(values)
    # Each local row passed strict validation above; canonical incidence construction
    # and the uniqueness check establish the aggregate validator's complete contract.
    return DependencyIndex.model_construct(rows=values, reverse=reverse_for(values))


def partitions(
    read: IndexRead,
    current: DependencyIndex,
    affected: set[RowRef],
) -> list[list[int]]:
    """Hydrate changed closures and reuse exact partitions for untouched blocks.

    Args:
        read: Complete slim evidence and any already hydrated snapshot misses.
        current: The complete current dependency inventory.
        affected: Current occurrences reached through old and new dependencies.

    Returns:
        The complete current partition in first-encounter order.
    """
    result = []
    retained = set()
    policy = str(peri_scribe.fires.grouping.FIRE_PROXIMITY_TOLERANCE.m_as("degrees"))
    records = [row.record for row in read.rows]
    for block in peri_scribe.fires.grouping_cache.dependency_blocks(records):
        if len(block) == 1:
            result.append(block)
            continue
        key = peri_scribe.fires.grouping_cache.block_key(
            [read.rows[index].row_key for index in block],
            policy,
        )
        retained.add(key)
        partition = peri_scribe.fires.grouping_cache.cached_partition(key, len(block))
        if partition is None or any(
            current.rows[index].reference in affected for index in block
        ):
            rows = hydrate_indices(read, block)
            grouped = peri_scribe.fires.grouping.group_fire_record_indices(
                [rows[index].record for index in block],
                geometry_keys=read.geometry_pool.geometry_keys,
            )
            partition = peri_scribe.fires.grouping_cache.Partition(
                count=len(block),
                groups=tuple(tuple(group) for group in grouped),
            )
            spatial_data.product_cache.put(
                peri_scribe.fires.grouping_cache.NAMESPACE,
                key,
                partition.model_dump_json().encode(),
            )
        result.extend([block[index] for index in group] for group in partition.groups)
    spatial_data.product_cache.prune(
        peri_scribe.fires.grouping_cache.NAMESPACE,
        retained,
    )
    return sorted(result, key=operator.itemgetter(0))


def comparable_anchors(read: IndexRead) -> bool:
    """Require compact token ranks to belong to distinct snapshot prefixes.

    Args:
        read: Slim rows with their source/serial/filename anchor prefixes.

    Returns:
        Whether rank comparisons preserve the complete anchor ordering.
    """
    seen = {}
    for row, path in zip(read.rows, read.paths, strict=True):
        prefix = row.anchor_order[:3]
        if seen.setdefault(prefix, path) != path:
            return False
    return True


def prepare_index_sources(directory: pathlib.Path) -> IndexSources | None:
    """Use slim summaries only after a complete prior preparation established them.

    Args:
        directory: The authoritative source root for this index invocation.

    Returns:
        Separate metadata-only index evidence, or None for complete preparation.
    """
    previous = cached_index()
    if previous is None:
        return None
    paths = peri_scribe.sources.snapshots.geo_package_files(directory)
    pool = spatial_data.geometry_pool.GeometryPool()
    summaries, hydrated = peri_scribe.geo.source_summaries.read_summaries(
        paths,
        directory,
        geometry_pool=pool,
        read_fallback=functools.partial(
            peri_scribe.fires.sources.read_fire_geopackage,
            geometry_pool=pool,
        ),
    )
    read = index_read(directory, summaries, hydrated, pool)
    if not comparable_anchors(read):
        return None
    current = dependency_index(read)
    affected = affected_rows(previous, current)
    groups = partitions(read, current, affected)
    records = tuple(row.record for row in read.rows)
    fires = tuple(
        dataclasses.replace(
            peri_scribe.fires.grouping.most_common_fire([
                records[index] for index in group
            ]),
            component_id=min(
                (read.rows[index] for index in group),
                key=operator.attrgetter("anchor_order"),
            ).anchor_digest,
            component_aliases=frozenset(
                read.rows[index].anchor_digest for index in group
            ),
        )
        for group in groups
    )
    by_identifier = {}
    for fire, group in zip(fires, groups, strict=True):
        for index in group:
            for identifier in records[index].identifiers:
                by_identifier.setdefault(identifier, fire)
    observations = [
        observation
        for row_declarations in (True, False)
        for path in paths
        for observation in (
            summaries[path].observations[: summaries[path].row_observation_count]
            if row_declarations
            else summaries[path].observations[summaries[path].row_observation_count :]
        )
    ]
    complexes = peri_scribe.fires.grouping.fire_complexes(
        [membership for path in paths for membership in summaries[path].memberships],
        by_identifier,
        observations=observations,
    )
    result = IndexSources(
        read=read,
        groups=peri_scribe.fires.sources.FireRecordGroups(
            records=records,
            record_paths=read.paths,
            fires=fires,
            groups=tuple(tuple(group) for group in groups),
            complex_identifiers=frozenset(
                complex_.identifier for complex_ in complexes
            ),
            geometry_keys=pool.geometry_keys,
            source_paths=read.source_paths,
        ),
        evidence_keys=tuple(row.row_key for row in read.rows),
    )
    spatial_data.product_cache.put(
        NAMESPACE,
        "current",
        current.model_dump_json().encode(),
    )
    logger.info(
        "Selective source-index preparation",
        rows=len(read.rows),
        affected=len(affected),
        hydrated_snapshots=len(hydrated),
        snapshots=len(paths),
    )
    return result


def remember_index_sources(
    directory: pathlib.Path,
    prepared: peri_scribe.fires.sources.PreparedSources,
) -> None:
    """Seed authenticated slim preparation after a complete successful source read.

    Args:
        directory: The authoritative source root for the complete preparation.
        prepared: Complete evidence, never a metadata-only index plan.

    Raises:
        ValueError: If source bytes changed after the complete parse was authenticated.
    """
    if not spatial_data.product_cache.active():
        return
    paths = peri_scribe.sources.snapshots.geo_package_files(directory)
    checksums = dict(prepared.read.source_checksums)
    if any(not path.is_file() for path in paths) or set(checksums) != set(paths):
        return
    if not (set(prepared.read.paths) | set(prepared.read.membership_paths)).issubset(
        paths,
    ) or (prepared.read.memberships and not prepared.read.membership_paths):
        return
    if any(
        peri_scribe.geo.database.snapshot_checksum(path) != checksums[path]
        for path in paths
    ):
        message = "Source evidence changed before retaining index summaries"
        raise ValueError(message)
    rows: dict[pathlib.Path, list[peri_scribe.geo.package.FireRowRecord]] = (
        collections.defaultdict(list)
    )
    memberships: dict[pathlib.Path, list[peri_scribe.models.ComplexMembership]] = (
        collections.defaultdict(list)
    )
    for row, path in zip(prepared.read.rows, prepared.read.paths, strict=True):
        rows[path].append(row)
    for membership, path in zip(
        prepared.read.memberships,
        prepared.read.membership_paths,
        strict=True,
    ):
        memberships[path].append(membership)
    contents = {
        path: peri_scribe.geo.package.GeopackageContents(
            rows=tuple(rows[path]),
            memberships=tuple(memberships[path]),
        )
        for path in paths
    }
    summaries = {}
    for path, value in contents.items():
        summary = peri_scribe.geo.source_summaries.summarize(path, value)
        peri_scribe.geo.source_summaries.store_summary(
            path,
            directory,
            checksums[path],
            summary,
        )
        summaries[path] = summary
    read = index_read(
        directory,
        summaries,
        contents,
        spatial_data.geometry_pool.GeometryPool(),
        source_paths=prepared.read.source_paths,
    )
    current = dependency_index(read)
    spatial_data.product_cache.put(
        NAMESPACE,
        "current",
        current.model_dump_json().encode(),
    )
