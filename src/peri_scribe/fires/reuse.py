"""Validated reuse of complete fire histories from prior derived files."""

from __future__ import annotations

import dataclasses
import hashlib
import importlib.metadata
import json
import pathlib
import tempfile

import pydantic
import shapely
import structlog

import peri_scribe.fires.sources
import peri_scribe.geo.parsing
import peri_scribe.geo.reading
import peri_scribe.models
import peri_scribe.output
import peri_scribe.perimeters.classification_data
import peri_scribe.perimeters.cleaning
import peri_scribe.perimeters.size_filtering
import peri_scribe.sources.administrative_boundaries


logger = structlog.get_logger()
KEY_COLUMN = "derivation_key"
CACHE_VERSION = 1
type Rows = list[dict[str, object]]
type CachedRows = dict[str, dict[str, Rows]]


class Signature(pydantic.BaseModel):
    """A completed output's checksum prevents partial or edited files being reused."""

    version: int
    checksum: str


def file_digest(path: pathlib.Path) -> str:
    """Hash on-disk bytes without retaining another copy of a large geometry file.

    Args:
        path: The file whose contents need a checksum.

    Returns:
        The SHA-256 checksum.
    """
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


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
    source_root = pathlib.Path(__file__).parents[1]
    boundary = peri_scribe.sources.administrative_boundaries.output_geopackage_path(
        year_directory,
    )
    return data_digest({
        "version": CACHE_VERSION,
        "code": [
            (str(path.relative_to(source_root)), file_digest(path))
            for path in sorted(source_root.rglob("*.py"))
        ],
        "libraries": {
            name: importlib.metadata.version(name)
            for name in ("shapely", "pyproj", "geopandas", "pyogrio", "pint")
        },
        "geos": shapely.geos_version_string,
        "boundary": file_digest(boundary) if boundary.is_file() else None,
        "cleaning": repr(peri_scribe.perimeters.cleaning.DEFAULT_CLEANING_CONFIG),
        "size_filter": repr(
            peri_scribe.perimeters.size_filtering.DEFAULT_SIZE_FILTER_CONFIG,
        ),
        "classification": repr(
            peri_scribe.perimeters.classification_data.BorderClassificationConfig(),
        ),
    })


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
    geometry_digests: dict[int, str] = {}
    rows: list[str] = []
    for row, path in zip(read.rows, read.paths, strict=True):
        record = row.record
        geometry = record.geometry
        if geometry is not None and id(geometry) not in geometry_digests:
            geometry_digests[id(geometry)] = hashlib.sha256(
                shapely.to_wkb(geometry, include_srid=True),
            ).hexdigest()
        fields = {
            field.name: getattr(record, field.name)
            for field in dataclasses.fields(record)
            if field.name not in {"geometry", "identifiers", "names"}
        }
        rows.append(
            data_digest({
                "record": fields,
                "identifiers": sorted(record.identifiers),
                "names": sorted(record.names),
                "geometry": None
                if geometry is None
                else geometry_digests[id(geometry)],
                "attributes": {
                    key: peri_scribe.geo.parsing.json_native_value(value)
                    for key, value in row.attributes.items()
                },
                "object_id": row.object_id,
                "source": row.source_name,
                "path": str(path.relative_to(sources_directory)),
            }),
        )
    return {
        id(fire): data_digest({
            "context": context,
            "name": fire.name,
            "identifier": fire.identifier,
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


def read_rows(
    path: pathlib.Path,
    layer_names: tuple[str, ...],
    *,
    unconditional: bool = False,
) -> CachedRows:
    """Treat missing, incompatible, interrupted, or corrupt outputs as cache misses.

    Args:
        path: The prior history GeoPackage that may contain reusable results.
        layer_names: The history layers needed by the caller.
        unconditional: Whether to bypass prior results without reading them.

    Returns:
        Validated rows by layer and derivation key, or an empty cache.
    """
    if unconditional:
        logger.info("Bypassing history reuse", path=str(path), reason="unconditional")
        return {}
    try:
        return validated_rows(path, layer_names)
    except (OSError, ValueError, RuntimeError) as error:
        logger.info("Ignoring history cache", path=str(path), reason=str(error))
        return {}


def validated_rows(path: pathlib.Path, layer_names: tuple[str, ...]) -> CachedRows:
    """Read only rows covered by a completed output checksum.

    Args:
        path: The history GeoPackage to validate against its checksum metadata.
        layer_names: The history layers whose rows should be grouped for reuse.

    Returns:
        Rows grouped by layer and derivation key.

    Raises:
        ValueError: When a layer lacks derivation keys.
    """
    signature = Signature.model_validate_json(signature_path(path).read_text())
    if signature.version != CACHE_VERSION or signature.checksum != file_digest(path):
        logger.info(
            "Ignoring history cache",
            path=str(path),
            reason="signature mismatch",
        )
        return {}
    result: CachedRows = {}
    for name in layer_names:
        frame = peri_scribe.geo.reading.read_layer(path, name)
        if frame.empty:
            result[name] = {}
            continue
        if KEY_COLUMN not in frame.columns:
            message = "Missing history derivation keys"
            raise ValueError(message)
        result[name] = {
            str(key): group.to_dict("records")
            for key, group in frame.groupby(KEY_COLUMN, sort=False)
        }
    return result


def write_layers(
    path: pathlib.Path,
    layers: list[peri_scribe.models.LayerData],
) -> None:
    """Publish complete geometry files before marking their contents reusable.

    Args:
        path: The destination history GeoPackage.
        layers: The complete layers to publish together in that GeoPackage.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=path.parent) as directory:
        temporary = pathlib.Path(directory) / path.name
        peri_scribe.output.write_geopackage(temporary, layers)
        signature = Signature(version=CACHE_VERSION, checksum=file_digest(temporary))
        metadata = signature_path(temporary)
        metadata.write_text(signature.model_dump_json())
        temporary.replace(path)
        metadata.replace(signature_path(path))
