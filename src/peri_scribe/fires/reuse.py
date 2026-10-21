"""Validated reuse of complete fire histories from prior derived files.

Algorithm reasoning and contracts:
[Geography generations](../../../docs/algorithms/geography-generations.md)
"""

from __future__ import annotations

import collections.abc
import dataclasses
import hashlib
import importlib.metadata
import json
import pathlib
import platform
import sys
import tempfile
import typing

import pydantic
import pyproj
import shapely
import structlog

import peri_scribe.execution
import peri_scribe.fires.sources
import peri_scribe.geo.fingerprints
import peri_scribe.perimeters.classification_data
import peri_scribe.perimeters.cleaning
import peri_scribe.perimeters.size_filtering
import peri_scribe.sources.administrative_boundaries
import peri_scribe.sources.authentication
import peri_scribe.sources.provenance
import spatial_data.layers
import spatial_data.row_index


if typing.TYPE_CHECKING:
    import geopandas


logger = structlog.get_logger()
KEY_COLUMN = "derivation_key"
CACHE_VERSION = 1
type Rows = list[dict[str, object]]
type CachedRows = dict[str, dict[str, Rows]]


class Signature(pydantic.BaseModel):
    """A checksum marking a completed output as safe to reuse.

    The checksum must match the current file before its rows can be reused. A partial or
    edited file cannot inherit the completed output's validation.
    """

    version: int
    checksum: str
    generation: str | None = None
    layers: tuple[str, ...] = ()


def file_digest(path: pathlib.Path) -> str:
    """Hash on-disk bytes without retaining another copy of a large geometry file.

    Args:
        path: The file whose contents need a checksum.

    Returns:
        The SHA-256 checksum.
    """
    return peri_scribe.sources.authentication.file_digest(path)


def data_digest(value: object) -> str:
    """Keep fingerprints independent of dictionary insertion order.

    Args:
        value: The dependency data to fingerprint.

    Returns:
        The content fingerprint.
    """
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, default=str).encode(),
    ).hexdigest()


def derivation_context(year_directory: pathlib.Path) -> str:
    """Code, dependencies, settings, and boundary changes invalidate prior histories.

    Args:
        year_directory: The year directory holding the administrative boundary data.

    Returns:
        The derivation environment's fingerprint.
    """
    source_root = pathlib.Path(__file__).parents[2]
    boundary = peri_scribe.sources.administrative_boundaries.output_geopackage_path(
        year_directory,
    )
    return data_digest({
        "version": CACHE_VERSION,
        "code": [
            (str(path.relative_to(source_root)), file_digest(path))
            for package in (
                "peri_scribe",
                "arcgis_access",
                "aircraft_registration",
                "document_text",
                "measurement_units",
                "spatial_data",
            )
            for path in sorted((source_root / package).rglob("*.py"))
        ],
        "libraries": {
            name: importlib.metadata.version(name)
            for name in (
                "shapely",
                "pyproj",
                "geopandas",
                "pyogrio",
                "pint",
                "pandas",
                "numpy",
                "pydantic",
            )
        },
        "geos": shapely.geos_version_string,
        "proj": pyproj.proj_version_str,
        "python": sys.version,
        "platform": platform.platform(),
        "boundary": file_digest(boundary) if boundary.is_file() else None,
        "cleaning": repr(peri_scribe.perimeters.cleaning.DEFAULT_CLEANING_CONFIG),
        "size_filter": repr(
            peri_scribe.perimeters.size_filtering.DEFAULT_SIZE_FILTER_CONFIG,
        ),
        "classification": repr(
            peri_scribe.perimeters.classification_data.BorderClassificationConfig(),
        ),
    })


@dataclasses.dataclass(frozen=True, kw_only=True)
class SharedFireKeys:
    """Retain exact source identities while index and geography share fingerprints."""

    read: peri_scribe.fires.sources.ReadFireSources
    groups: peri_scribe.fires.sources.FireRecordGroups
    keys: dict[int, str]


def shared_fire_keys(
    read: peri_scribe.fires.sources.ReadFireSources,
    groups: peri_scribe.fires.sources.FireRecordGroups,
    sources_directory: pathlib.Path,
    context: str,
) -> dict[int, str]:
    """Fingerprint complete source evidence once per execution and derivation context.

    Args:
        read: Source observations and provenance for this execution.
        groups: The exact grouped fire identities used by the consuming stages.
        sources_directory: The source root used to express provenance paths.
        context: The complete derivation environment and dependency fingerprint.

    Returns:
        Complete input fingerprints keyed by in-memory fire identity.
    """
    key = ("fire_keys", sources_directory.resolve(), context)
    cached = peri_scribe.execution.get(peri_scribe.execution.Group.SOURCES, key)
    if (
        isinstance(cached, SharedFireKeys)
        and cached.read is read
        and cached.groups is groups
    ):
        return cached.keys
    keys = fire_keys(read, groups, sources_directory, context)
    peri_scribe.execution.put(
        peri_scribe.execution.Group.SOURCES,
        key,
        SharedFireKeys(read=read, groups=groups, keys=keys),
    )
    return keys


def fire_keys(
    read: peri_scribe.fires.sources.ReadFireSources,
    groups: peri_scribe.fires.sources.FireRecordGroups,
    sources_directory: pathlib.Path,
    context: str,
) -> dict[int, str]:
    """Fingerprint all source observations, including those reconciliation discards.

    Args:
        read: All source observations and their aligned source paths.
        groups: The fires and record indices grouped from *read*.
        sources_directory: The directory used to make provenance paths relative.
        context: The fingerprint of the derivation environment and configuration.

    Returns:
        The input fingerprint for each in-memory fire identity.
    """
    source_paths = peri_scribe.sources.provenance.for_directory(
        sources_directory,
        read.source_paths,
    )
    rows = [
        provenance_key(
            peri_scribe.geo.fingerprints.row_evidence_fingerprint(row),
            path,
            sources_directory,
            source_paths=source_paths,
        )
        for row, path in zip(read.rows, read.paths, strict=True)
    ]
    return group_keys(rows, groups, context)


def provenance_key(
    evidence: str,
    path: pathlib.Path,
    sources_directory: pathlib.Path,
    *,
    source_paths: peri_scribe.sources.provenance.SourcePaths | None = None,
) -> str:
    """Keep source location in every row identity consumed by a derived fire product.

    Args:
        evidence: Complete path-independent source row identity.
        path: The authoritative snapshot containing this occurrence.
        sources_directory: The source root used to express relative provenance.
        source_paths: Shared lexical strings belonging to this preparation.

    Returns:
        The same canonical identity for full rows and authenticated row summaries.
    """
    return data_digest({
        "evidence": evidence,
        "path": (
            str(path.relative_to(sources_directory))
            if source_paths is None
            else peri_scribe.sources.provenance.for_directory(
                sources_directory,
                source_paths,
            ).relative(path)
        ),
    })


def group_keys(
    rows: collections.abc.Sequence[str],
    groups: peri_scribe.fires.sources.FireRecordGroups,
    context: str,
) -> dict[int, str]:
    """Combine complete ordered row identities with the resolved fire metadata.

    Args:
        rows: Complete evidence and provenance identities in source occurrence order.
        groups: Resolved identities and positions of those same source occurrences.
        context: The complete derivation environment and dependency fingerprint.

    Returns:
        The complete input fingerprint for each in-memory fire identity.
    """
    return {
        id(fire): data_digest({
            "version": 2,
            "context": context,
            "name": fire.name,
            "identifier": fire.identifier,
            "component_id": fire.component_id,
            "component_aliases": sorted(fire.component_aliases),
            "aliases": sorted(fire.aliases),
            "status": fire.status.value,
            "complex": None
            if fire.complex is None
            else (
                fire.complex.identifier,
                fire.complex.name,
                sorted(
                    (member.identifier or "", member.name)
                    for member in fire.complex.fires
                ),
            ),
            "rows": [rows[index] for index in group],
        })
        for fire, group in zip(groups.fires, groups.groups, strict=True)
    }


def signature_path(path: pathlib.Path) -> pathlib.Path:
    """Keep validation metadata beside the history file it authenticates.

    Args:
        path: The history GeoPackage whose checksum metadata is needed.

    Returns:
        The sibling reuse metadata path.
    """
    return path.with_suffix(".reuse.json")


def validated_signature(
    path: pathlib.Path,
    layer_names: tuple[str, ...] = (),
) -> Signature | None:
    """Authenticate a complete published layer set before skipping any derivation.

    Args:
        path: The published GeoPackage whose generation may be reusable.
        layer_names: The required complete layer set in publication order, or empty
            when only the published bytes require authentication.

    Returns:
        The authenticated metadata, or None for unavailable or incompatible output.
    """
    try:
        signature = Signature.model_validate_json(signature_path(path).read_text())
        if (
            signature.version == CACHE_VERSION
            and (not layer_names or signature.layers == layer_names)
            and signature.checksum == file_digest(path)
        ):
            return signature
    except OSError, ValueError:
        logger.info("Ignoring output generation", path=str(path), exc_info=True)
    return None


def generation_matches(
    path: pathlib.Path,
    generation: str,
    layer_names: tuple[str, ...],
) -> bool:
    """Reuse an unchanged publication only when its complete output is authenticated.

    Args:
        path: The published GeoPackage that may already represent these inputs.
        generation: Complete ordered input and derivation dependency identity.
        layer_names: The complete required layer set in publication order.

    Returns:
        Whether the existing bytes are a complete output for this exact generation.
    """
    signature = validated_signature(path, layer_names)
    return signature is not None and signature.generation == generation


def read_rows(
    path: pathlib.Path,
    layer_names: tuple[str, ...],
    *,
    unconditional: bool = False,
    keys: collections.abc.Collection[str] | None = None,
) -> CachedRows:
    """Treat missing, incompatible, interrupted, or corrupt outputs as cache misses.

    Args:
        path: The prior history GeoPackage that may contain reusable results.
        layer_names: The history layers needed by the caller.
        unconditional: Whether to bypass prior results without reading them.
        keys: The complete derivation keys needed by the caller, or None for all fires.

    Returns:
        Validated rows by layer and derivation key, or an empty cache.
    """
    if unconditional:
        logger.info("Bypassing history reuse", path=str(path), reason="unconditional")
        return {}
    try:
        return validated_rows(path, layer_names, keys=keys)
    except (OSError, ValueError, RuntimeError) as error:
        logger.info(
            "Ignoring history cache",
            path=str(path),
            reason=str(error),
            exc_info=True,
        )
        return {}


def validated_rows(
    path: pathlib.Path,
    layer_names: tuple[str, ...],
    *,
    keys: collections.abc.Collection[str] | None = None,
) -> CachedRows:
    """Read only rows covered by a completed output checksum.

    Args:
        path: The history GeoPackage to validate against its checksum metadata.
        layer_names: The history layers whose rows should be grouped for reuse.
        keys: Requested derivation keys, or None for the complete layer.

    Returns:
        Rows grouped by layer and derivation key.

    """
    signature = validated_signature(path)
    if signature is None:
        return {}
    result: CachedRows = {}
    for name in layer_names:
        indexed = spatial_data.row_index.read(
            path,
            name,
            signature.checksum,
            keys,
            adaptive=True,
        )
        if indexed is not None:
            result[name] = indexed
            continue
        frame = spatial_data.layers.read_layer(path, name)
        rows = spatial_data.row_index.grouped_rows(frame)
        selected = {
            key: group for key, group in rows.items() if keys is None or key in keys
        }
        if selected and not spatial_data.row_index.prefer_bulk(keys, rows.keys()):
            spatial_data.row_index.seed(
                path,
                name,
                signature.checksum,
                frame,
                rows=rows,
            )
        result[name] = selected
    return result


def read_published_layer(path: pathlib.Path, layer: str) -> geopandas.GeoDataFrame:
    """Read authoritative post-GDAL values without materializing unused row indexes.

    Args:
        path: The published GeoPackage needed by a downstream stage.
        layer: Its required layer.

    Returns:
        The normalized layer used by downstream presentation and scoring.
    """
    return spatial_data.layers.read_layer(path, layer)


def write_layers(
    path: pathlib.Path,
    layers: list[spatial_data.layers.LayerData],
    *,
    generation: str | None = None,
) -> None:
    """Publish complete geometry files before marking their contents reusable.

    Args:
        path: The destination history GeoPackage.
        layers: The complete layers to publish together in that GeoPackage.
        generation: Complete input identity, or None when unavailable inputs require
            reconsideration during the next execution.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=path.parent) as directory:
        temporary = pathlib.Path(directory) / path.name
        spatial_data.layers.write_geopackage(temporary, layers)
        signature = Signature(
            version=CACHE_VERSION,
            checksum=file_digest(temporary),
            generation=generation,
            layers=tuple(layer.name for layer in layers),
        )
        metadata = signature_path(temporary)
        metadata.write_text(signature.model_dump_json())
        temporary.replace(path)
        metadata.replace(signature_path(path))
