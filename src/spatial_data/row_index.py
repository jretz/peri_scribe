"""Index normalized published rows while retaining only the current generation."""

from __future__ import annotations

import collections.abc
import dataclasses
import hashlib
import pathlib
import typing

import structlog

import spatial_data.cache_values
import spatial_data.product_cache


if typing.TYPE_CHECKING:
    import geopandas


logger = structlog.get_logger()
KEY_COLUMN = "derivation_key"
MANIFEST_KEY = "current"
ENTRY_LENGTH = 2
MINIMUM_BULK_GROUPS = 128
type Rows = list[dict[str, object]]


@dataclasses.dataclass(frozen=True, kw_only=True)
class Manifest:
    """Bind ordered row groups to the checksum of a completed published artifact."""

    checksum: str
    columns: tuple[str, ...]
    entries: tuple[tuple[str, str], ...]


def namespaces(path: pathlib.Path, layer: str) -> tuple[str, str]:
    """Keep full and differential layer products independent within their year.

    Args:
        path: The published artifact whose basename identifies its output family.
        layer: The normalized layer being indexed.

    Returns:
        The manifest and immutable row-payload namespaces.
    """
    prefix = f"published-rows-v1:{path.name}:{layer}"
    return f"{prefix}:manifest", f"{prefix}:payload"


def read_manifest(payload: bytes) -> Manifest:
    """Reject incomplete indexes instead of treating omitted fires as empty histories.

    Args:
        payload: The authenticated, typed manifest document.

    Returns:
        Its complete ordered index and published checksum.

    Raises:
        ValueError: When the manifest's shape or identifiers are invalid.
    """
    match spatial_data.cache_values.loads(payload):
        case (str(checksum), tuple(columns), tuple(entries)) if all(
            isinstance(column, str) for column in columns
        ) and all(
            isinstance(entry, tuple)
            and len(entry) == ENTRY_LENGTH
            and all(isinstance(part, str) for part in entry)
            for entry in entries
        ):
            typed_entries = typing.cast("tuple[tuple[str, str], ...]", entries)
            if len({key for key, _digest in typed_entries}) == len(typed_entries):
                return Manifest(
                    checksum=checksum,
                    columns=typing.cast("tuple[str, ...]", columns),
                    entries=typed_entries,
                )
    message = "Invalid published row manifest"
    raise ValueError(message)


def read_payload(payload: bytes, key: str, columns: tuple[str, ...]) -> Rows:
    """Require complete normalized rows before a caller can reuse them in an export.

    Args:
        payload: The authenticated typed rows for one source fingerprint.
        key: The derivation key promised by the generation manifest.
        columns: Exact published column names and ordering.

    Returns:
        Fresh mutable dictionaries in published row order.

    Raises:
        ValueError: When a group is empty, incomplete, or belongs to another key.
    """
    value = spatial_data.cache_values.loads(payload)
    if (
        isinstance(value, list)
        and value
        and all(
            isinstance(row, dict)
            and tuple(row) == columns
            and str(row.get(KEY_COLUMN)) == key
            for row in value
        )
    ):
        return typing.cast("Rows", value)
    message = "Invalid published row payload"
    raise ValueError(message)


def read(
    path: pathlib.Path,
    layer: str,
    checksum: str,
    requested_keys: collections.abc.Collection[str] | None = None,
    *,
    adaptive: bool = False,
) -> dict[str, Rows] | None:
    """Read only requested fire products from the authenticated output generation.

    Args:
        path: The published artifact already validated by its owner.
        layer: The normalized layer whose reusable groups are required.
        checksum: The validated checksum of that complete artifact.
        requested_keys: Derivation keys needed by the caller, or None for all groups.
        adaptive: Whether dense requests may defer to the caller's bulk reader.

    Returns:
        Ordered matching groups, possibly empty, or None when bulk reading is needed.
    """
    manifest_namespace, payload_namespace = namespaces(path, layer)
    payload = spatial_data.product_cache.get(manifest_namespace, MANIFEST_KEY)
    if payload is None:
        return None
    try:
        manifest = read_manifest(payload)
        if manifest.checksum != checksum:
            return None
        if not manifest.entries:
            return {}
        if adaptive and prefer_bulk(
            requested_keys,
            tuple(key for key, _digest in manifest.entries),
        ):
            return None
        return load_groups(manifest, payload_namespace, requested_keys)
    except ValueError:
        logger.warning("Published row index is invalid", path=str(path), exc_info=True)
        return None


def prefer_bulk(
    requested_keys: collections.abc.Collection[str] | None,
    available_keys: collections.abc.Collection[str],
) -> bool:
    """Use GDAL's bulk conversion when most of a substantial layer is needed.

    Small explicit selections retain indexed reuse even in a small layer. A complete
    layer request benefits from bulk decoding without building a second representation.

    Args:
        requested_keys: Needed derivation keys, or None for every available history.
        available_keys: Complete keys in the authenticated index or normalized layer.

    Returns:
        Whether the caller should read in bulk and leave index construction deferred.
    """
    if requested_keys is None:
        return True
    available = set(available_keys)
    matching = len(available.intersection(requested_keys))
    return matching >= MINIMUM_BULK_GROUPS and matching * 2 >= len(available)


def load_groups(
    manifest: Manifest,
    namespace: str,
    requested_keys: collections.abc.Collection[str] | None,
) -> dict[str, Rows] | None:
    """Authenticate requested histories without decoding unrelated groups.

    Args:
        manifest: The complete published row index.
        namespace: Its content-addressed payload family.
        requested_keys: Requested keys, or None for every indexed history.

    Returns:
        Matching groups, or None if a promised payload is absent or corrupted.
    """
    requested = None if requested_keys is None else set(requested_keys)
    rows: dict[str, Rows] = {}
    for key, digest in manifest.entries:
        if requested is not None and key not in requested:
            continue
        payload = spatial_data.product_cache.get(namespace, digest)
        if payload is None or hashlib.sha256(payload).hexdigest() != digest:
            return None
        rows[key] = read_payload(payload, key, manifest.columns)
    return rows


def grouped_rows(normalized_frame: geopandas.GeoDataFrame) -> dict[str, Rows]:
    """Preserve published row ordering and scalar conversions when grouping histories.

    Args:
        normalized_frame: Values read back from a published GeoPackage.

    Returns:
        Complete ordered histories, excluding rows without a derivation key.

    Raises:
        ValueError: When a populated layer lacks derivation keys.
    """
    if normalized_frame.empty:
        return {}
    if KEY_COLUMN not in normalized_frame.columns:
        message = "Missing history derivation keys"
        raise ValueError(message)
    records = normalized_frame.to_dict("records")
    return {
        str(key): [records[position] for position in positions]
        for key, positions in normalized_frame.groupby(
            KEY_COLUMN,
            sort=False,
        ).indices.items()
    }


def seed(
    path: pathlib.Path,
    layer: str,
    checksum: str,
    normalized_frame: geopandas.GeoDataFrame,
    *,
    rows: dict[str, Rows] | None = None,
) -> None:
    """Retain post-GDAL values and prune payloads superseded by a complete generation.

    Args:
        path: The published artifact already validated by its owner.
        layer: The normalized layer read from that artifact.
        checksum: The validated checksum of the complete published artifact.
        normalized_frame: Values read back from the published GeoPackage.
        rows: Existing complete groups when the consumer has already materialized them.
    """
    if not spatial_data.product_cache.active():
        return
    try:
        store_generation(
            namespaces(path, layer),
            checksum,
            tuple(normalized_frame.columns),
            grouped_rows(normalized_frame) if rows is None else rows,
        )
    except ValueError:
        logger.warning(
            "Published rows could not be indexed",
            path=str(path),
            exc_info=True,
        )


def store_generation(
    namespace_pair: tuple[str, str],
    checksum: str,
    columns: tuple[str, ...],
    groups: dict[str, Rows],
) -> None:
    """Replace a complete index within its owning publication transaction.

    Args:
        namespace_pair: The manifest and immutable row-payload namespaces.
        checksum: The published file's checksum.
        columns: Exact normalized column names and order.
        groups: Complete GDAL-normalized histories in published order.
    """
    manifest_namespace, payload_namespace = namespace_pair
    entries: list[tuple[str, str]] = []
    for key, rows in groups.items():
        payload = spatial_data.cache_values.dumps(rows)
        digest = hashlib.sha256(payload).hexdigest()
        spatial_data.product_cache.put(payload_namespace, digest, payload)
        entries.append((key, digest))
    spatial_data.product_cache.put(
        manifest_namespace,
        MANIFEST_KEY,
        spatial_data.cache_values.dumps((checksum, columns, tuple(entries))),
    )
    spatial_data.product_cache.prune(
        payload_namespace,
        {digest for _key, digest in entries},
    )
