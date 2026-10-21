"""Building and reading the fire source index for a year's data.

[Generation and reuse](../../../docs/algorithms/geography-generations.md)
"""

from __future__ import annotations

import dataclasses
import pathlib
import typing

import pydantic
import structlog

import peri_scribe.execution
import peri_scribe.fires.classification
import peri_scribe.fires.generation
import peri_scribe.fires.reuse
import peri_scribe.fires.source_index_cache
import peri_scribe.fires.sources
import peri_scribe.logging
import peri_scribe.models
import peri_scribe.output
import peri_scribe.phases
import peri_scribe.preparation
import peri_scribe.sources.provenance
import peri_scribe.sources.snapshots
import spatial_data.product_cache


if typing.TYPE_CHECKING:
    import collections.abc


# The current version of the fire source index format; bump it when the format changes
# so that consumers can tell which format a file uses.
FIRE_INDEX_VERSION = "2026-09-26"
CLASSIFICATION_NAMESPACE = "fire-classification-v1"
GENERATION_NAMESPACE = "source-index-generation-v1"
logger = structlog.get_logger()


def fire_document(fire: peri_scribe.models.Fire) -> dict[str, object]:
    """Return a JSON-serializable document describing *fire*.

    A fire in a complex is described with the complex's name and identifier. The
    complex's member list is not included, because it links back to the fire and would
    make the document circular.

    Args:
        fire: The fire to describe.

    Returns:
        The fire's attributes as a JSON-serializable dictionary.
    """
    complex_document: dict[str, object] | None
    if fire.complex is None:
        complex_document = None
    else:
        complex_document = {
            "name": fire.complex.name,
            "identifier": fire.complex.identifier,
        }
    return {
        **(
            {
                "component_id": fire.component_id,
                "component_aliases": sorted(fire.component_aliases),
            }
            if fire.component_id is not None
            else {}
        ),
        "name": fire.name,
        "status": fire.status.value,
        "identifier": fire.identifier,
        "aliases": sorted(fire.aliases),
        "complex": complex_document,
    }


def fire_sources_document(
    source: peri_scribe.models.FireSources,
    sources_directory: pathlib.Path,
    classification: peri_scribe.models.FireClassification | None = None,
    *,
    source_paths: peri_scribe.sources.provenance.SourcePaths | None = None,
) -> dict[str, object]:
    """Return a JSON-serializable document for *source*.

    The document includes the fire's attributes and its border classification when
    known. It also lists the GeoPackage files that mention the fire. Those paths are
    relative to *sources_directory* and sorted, so the file list does not depend on the
    data directory's absolute location or the order in which files were read.

    Args:
        source: The fire and its source files.
        sources_directory: The directory that holds the index file, used to make the
            GeoPackage paths relative.
        classification: The fire's border classification, or None.
        source_paths: Exact relative strings shared with this preparation.

    Returns:
        The fire and its source paths as a JSON-serializable dictionary.
    """
    provenance = peri_scribe.sources.provenance.for_directory(
        sources_directory,
        source_paths,
    )
    document: dict[str, object] = {
        **fire_document(source.fire),
        "paths": sorted(provenance.relative(path) for path in source.paths),
    }
    if classification is not None:
        document["classification"] = classification.model_dump(mode="json")
    return document


def fire_index_entries(
    sources: list[peri_scribe.models.FireSources],
    sources_directory: pathlib.Path,
    classifications: dict[int, peri_scribe.models.FireClassification] | None = None,
    *,
    source_paths: peri_scribe.sources.provenance.SourcePaths | None = None,
) -> list[dict[str, object]]:
    """Return the fire index documents for *sources*, sorted by fire name.

    Args:
        sources: The fires and their source files.
        sources_directory: The directory that holds the index file, used to make the
            GeoPackage paths relative.
        classifications: Each fire's border classification, keyed by the fire object's
            identity, or None when no classifications are known.
        source_paths: Relative source strings retained by the current preparation.

    Returns:
        One document per fire, sorted by fire name.
    """
    if classifications is None:
        classifications = {}
    provenance = peri_scribe.sources.provenance.for_directory(
        sources_directory,
        source_paths,
    )
    return [
        fire_sources_document(
            source,
            sources_directory,
            classifications.get(id(source.fire)),
            source_paths=provenance,
        )
        for source in sorted(
            sources,
            key=lambda source: (source.fire.name, source.fire.component_id or ""),
        )
    ]


def fire_index_document(
    entries: list[dict[str, object]],
) -> peri_scribe.models.FireIndex:
    """Validate *entries* as the fire index for the current version.

    Args:
        entries: The fire index entry documents.

    Returns:
        The validated fire index document.
    """
    return peri_scribe.models.FireIndex.model_validate({
        "version": FIRE_INDEX_VERSION,
        "fires": entries,
    })


def cached_classification(key: str) -> peri_scribe.models.FireClassification | None:
    """Treat incomplete or incompatible classification products as cache misses.

    Args:
        key: The complete fire evidence and derivation dependency fingerprint.

    Returns:
        The validated classification, or None when it must be calculated.
    """
    payload = spatial_data.product_cache.get(CLASSIFICATION_NAMESPACE, key)
    if payload is None:
        return None
    try:
        return peri_scribe.models.FireClassification.model_validate_json(payload)
    except pydantic.ValidationError:
        logger.info("Ignoring invalid classification product", exc_info=True)
        return None


def classifications_for_prepared_sources(
    year_directory: pathlib.Path,
    prepared: peri_scribe.fires.sources.PreparedSources,
) -> dict[int, peri_scribe.models.FireClassification]:
    """Reuse cached classifications whose source evidence and dependencies match.

    Args:
        year_directory: The year holding the administrative boundary dependency.
        prepared: Complete source evidence and the grouped fire identities.

    Returns:
        Available classifications keyed by each grouped fire's in-memory identity.
    """
    if not spatial_data.product_cache.active():
        return peri_scribe.fires.classification.classify_fire_sources(
            prepared.groups,
            year_directory,
        )
    keys = peri_scribe.fires.reuse.shared_fire_keys(
        prepared.read,
        prepared.groups,
        peri_scribe.sources.snapshots.sources_directory_path(year_directory),
        peri_scribe.fires.reuse.derivation_context(year_directory),
    )
    return classifications_for_group_keys(year_directory, prepared.groups, keys)


def classifications_for_group_keys(
    year_directory: pathlib.Path,
    record_groups: peri_scribe.fires.sources.FireRecordGroups,
    keys: dict[int, str],
    *,
    hydrate_groups: collections.abc.Callable[
        [tuple[tuple[int, ...], ...]],
        peri_scribe.fires.sources.FireRecordGroups,
    ]
    | None = None,
) -> dict[int, peri_scribe.models.FireClassification]:
    """Load exact evidence only for fires whose complete classification is missing.

    Args:
        year_directory: The year holding the administrative boundary dependency.
        record_groups: Resolved identities and original source occurrence positions.
        keys: Complete fire evidence and dependency identities.
        hydrate_groups: Optional source-summary adapter returning complete records for
            the requested groups while retaining their original fire objects.

    Returns:
        Available classifications keyed by those same fire objects.
    """
    pairs = peri_scribe.fires.sources.non_complex_fire_sources(record_groups)
    classifications = {
        id(source.fire): classification
        for source, _group in pairs
        if (classification := cached_classification(keys[id(source.fire)])) is not None
    }
    missing = [
        (source.fire, group)
        for source, group in pairs
        if id(source.fire) not in classifications
    ]
    if missing:
        missing_groups = (
            dataclasses.replace(
                record_groups,
                fires=tuple(fire for fire, _group in missing),
                groups=tuple(group for _fire, group in missing),
            )
            if hydrate_groups is None
            else hydrate_groups(tuple(group for _fire, group in missing))
        )
        calculated = peri_scribe.fires.classification.classify_fire_sources(
            missing_groups,
            year_directory,
        )
        for identifier, classification in calculated.items():
            spatial_data.product_cache.put(
                CLASSIFICATION_NAMESPACE,
                keys[identifier],
                classification.model_dump_json().encode(),
            )
        classifications.update(calculated)
    logger.info(
        "Classification reuse",
        reused=len(pairs) - len(missing),
        recomputed=len(missing),
    )
    return classifications


def prepare_source_index(
    directory: pathlib.Path,
) -> (
    peri_scribe.fires.sources.PreparedSources
    | peri_scribe.fires.source_index_cache.IndexSources
):
    """Preserve complete execution preparations while reusing saved index summaries.

    Args:
        directory: The authoritative source snapshot directory.

    Returns:
        Complete execution evidence, or an explicitly separate selective index plan.
    """
    cached = peri_scribe.execution.get(
        peri_scribe.execution.Group.SOURCES,
        directory.resolve(),
    )
    if not isinstance(cached, peri_scribe.fires.sources.PreparedSources):
        incremental = peri_scribe.fires.source_index_cache.prepare_index_sources(
            directory,
        )
        if incremental is not None:
            return incremental
    prepared = peri_scribe.fires.sources.prepare_fire_sources(directory)
    peri_scribe.fires.source_index_cache.remember_index_sources(directory, prepared)
    return prepared


def classifications_for_index_sources(
    year_directory: pathlib.Path,
    plan: peri_scribe.fires.source_index_cache.IndexSources,
) -> dict[int, peri_scribe.models.FireClassification]:
    """Authenticate per-fire summary evidence before selectively loading geometry.

    Args:
        year_directory: The year holding all source and classification dependencies.
        plan: Current ordered snapshot summaries and their exact grouped identities.

    Returns:
        Reused or freshly calculated classifications with complete source evidence.
    """
    directory = peri_scribe.sources.snapshots.sources_directory_path(year_directory)
    rows = tuple(
        peri_scribe.fires.reuse.provenance_key(
            evidence,
            path,
            directory,
            source_paths=plan.read.source_paths,
        )
        for evidence, path in zip(
            plan.evidence_keys,
            plan.groups.record_paths,
            strict=True,
        )
    )
    keys = peri_scribe.fires.reuse.group_keys(
        rows,
        plan.groups,
        peri_scribe.fires.reuse.derivation_context(year_directory),
    )
    return classifications_for_group_keys(
        year_directory,
        plan.groups,
        keys,
        hydrate_groups=plan.hydrate_groups,
    )


@peri_scribe.preparation.cached_year
def index_fire_sources(year_directory: pathlib.Path) -> None:
    """Build the fire source index for *year_directory*.

    The index lists each fire, excluding parent complexes, from the GeoPackages under
    ``{year_directory}/sources``, along with the GeoPackage files that mention each fire
    and each fire's border classification when the administrative boundary data is
    available. It is written to ``{year_directory}/sources/fires.json``.

    Args:
        year_directory: The year directory that holds the ``sources`` directory.
    """
    with peri_scribe.logging.log_phase(peri_scribe.phases.Phase.SOURCE_INDEX):
        generation = peri_scribe.fires.generation.source_key(year_directory)
        if generation_matches(year_directory, generation):
            logger.info("Reusing complete source index", generation=generation)
            return
        sources_directory = peri_scribe.sources.snapshots.sources_directory_path(
            year_directory,
        )
        with peri_scribe.logging.log_phase(
            peri_scribe.phases.Phase.LOAD_AND_GROUP_SOURCES,
        ):
            prepared = prepare_source_index(sources_directory)
            record_groups = prepared.groups
        with peri_scribe.logging.log_phase(peri_scribe.phases.Phase.CLASSIFY_FIRES):
            if isinstance(prepared, peri_scribe.fires.sources.PreparedSources):
                classifications = prepared.classifications
                if classifications is None:
                    classifications = classifications_for_prepared_sources(
                        year_directory,
                        prepared,
                    )
                    peri_scribe.fires.sources.remember_prepared_sources(
                        sources_directory,
                        dataclasses.replace(prepared, classifications=classifications),
                    )
            else:
                classifications = classifications_for_index_sources(
                    year_directory,
                    prepared,
                )
        with peri_scribe.logging.log_phase(peri_scribe.phases.Phase.WRITE_INDEX):
            write_fire_index(year_directory, record_groups, classifications)
        if peri_scribe.fires.generation.classifications_complete(
            record_groups,
            classifications,
        ):
            path = peri_scribe.sources.snapshots.fire_index_path(year_directory)
            spatial_data.product_cache.put(
                GENERATION_NAMESPACE,
                "current",
                generation_signature(path, generation),
            )


def generation_signature(path: pathlib.Path, generation: str) -> bytes:
    """Bind a complete index's exact bytes to its authoritative source generation.

    Args:
        path: The successfully published source index.
        generation: The complete source and derivation fingerprint.

    Returns:
        The cache validation token.
    """
    return f"{generation}:{peri_scribe.fires.reuse.file_digest(path)}".encode()


def generation_matches(year_directory: pathlib.Path, generation: str) -> bool:
    """Avoid parsing unchanged observations only when the output is authenticated.

    Args:
        year_directory: The year owning the index and its disposable cache.
        generation: The currently observed complete source generation.

    Returns:
        Whether the existing index exactly matches a completed source generation.
    """
    cached = spatial_data.product_cache.get(GENERATION_NAMESPACE, "current")
    if cached is None:
        return False
    path = peri_scribe.sources.snapshots.fire_index_path(year_directory)
    try:
        return cached == generation_signature(path, generation)
    except OSError:
        return False


def write_fire_index(
    year_directory: pathlib.Path,
    record_groups: peri_scribe.fires.sources.FireRecordGroups,
    classifications: dict[int, peri_scribe.models.FireClassification],
) -> None:
    """Share already classified source groups with a complete geography rebuild.

    Args:
        year_directory: The year directory whose source index should be written.
        record_groups: The grouped fire records and their source paths.
        classifications: Available border classifications keyed by fire identity.
    """
    sources_directory = peri_scribe.sources.snapshots.sources_directory_path(
        year_directory,
    )
    index = fire_index_document(
        fire_index_entries(
            peri_scribe.fires.sources.fire_sources_from_groups(record_groups),
            sources_directory,
            classifications=classifications,
            source_paths=record_groups.source_paths,
        ),
    )
    output_path = peri_scribe.sources.snapshots.fire_index_path(year_directory)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    peri_scribe.output.write_document(output_path, index)


def load_fire_index(year_directory: pathlib.Path) -> peri_scribe.models.FireIndex:
    """Return the fire index for *year_directory*, building it first if needed.

    The index is read from ``{year_directory}/sources/fires.json``. When the file is
    missing, it is built from the GeoPackage files under the sources directory before it
    is read, so the index is always available once this returns.

    Args:
        year_directory: The year directory that holds the ``sources`` directory.

    Returns:
        The validated fire index.
    """
    index_path = peri_scribe.sources.snapshots.fire_index_path(year_directory)
    if not index_path.is_file():
        index_fire_sources(year_directory)
    return peri_scribe.output.read_document(index_path, peri_scribe.models.FireIndex)
