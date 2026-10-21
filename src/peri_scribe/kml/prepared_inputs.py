"""Reuse qualified histories and read only the attributes their map consumers need.

Design notes:
[KMZ preparation](../../../docs/algorithms/kmz-preparation.md).
"""

from __future__ import annotations

import compression.zstd
import contextlib
import dataclasses
import hashlib
import pathlib
import sqlite3
import typing

import geopandas
import pandas as pd
import pint
import pyogrio.errors

import peri_scribe.areas
import peri_scribe.execution
import peri_scribe.fires.derived_layers
import peri_scribe.fires.differential
import peri_scribe.fires.files
import peri_scribe.models
import peri_scribe.pipeline_state
import peri_scribe.presentation.history_index
import peri_scribe.presentation.index
import peri_scribe.presentation.prepared_cache
import peri_scribe.presentation.selection
import spatial_data.cache_values
import spatial_data.product_cache


NAMESPACE = "qualified-kmz-histories-v2"
ATTRIBUTE_COLUMN = "source_attributes"
ATTRIBUTE_BATCH_SIZE = 512
RECORD_FIELD_COUNT = 2
type Histories = dict[
    peri_scribe.presentation.selection.AreaKey,
    peri_scribe.areas.PreparedHistory,
]


@dataclasses.dataclass(frozen=True, kw_only=True)
class PreparedInputs:
    """Keep the map's complete geometry and selected reporting evidence together."""

    layers: peri_scribe.fires.derived_layers.DerivedLayers
    histories: Histories


def latest_positions(selections: tuple[tuple[int, ...], ...]) -> tuple[int, ...]:
    """Demand the final row of every nonempty ordered fire selection.

    Args:
        selections: Original row positions selected independently for each fire.

    Returns:
        Unique demanded positions in the layer's original order.
    """
    return tuple(sorted({selection[-1] for selection in selections if selection}))


def qualifying_histories(
    histories: typing.Mapping[
        peri_scribe.presentation.selection.AreaKey,
        peri_scribe.areas.PreparedHistory,
    ],
) -> Histories:
    """Retain exactly the complete histories meeting the map's area threshold.

    Args:
        histories: Complete histories prepared under the shared area policy.

    Returns:
        The original qualifying history objects, with their original identity keys.
    """
    return {
        key: history
        for key, history in histories.items()
        if history.historical_area is not None
        and history.historical_area
        >= peri_scribe.presentation.selection.MINIMUM_FIRE_AREA
    }


def preparation_key(
    identity: tuple[str, str],
    index: peri_scribe.models.FireIndex,
) -> str:
    """Bind qualified facts to exact published bytes, identities and area policies.

    The product store separately authenticates the code and runtime context. A changed
    generation misses this aggregate cache, leaving per-fire incremental reuse intact.

    Args:
        identity: Authenticated full and differential geography checksums.
        index: Complete current fire index, including aliases and components.

    Returns:
        A compact SHA-256 identity of every input to qualification and selection.
    """
    return hashlib.sha256(
        spatial_data.cache_values.dumps((
            identity,
            peri_scribe.presentation.prepared_cache.document_digest(index),
            peri_scribe.presentation.selection.MINIMUM_FIRE_AREA,
            dataclasses.asdict(peri_scribe.areas.DEFAULT_POLICY),
        )),
    ).hexdigest()


def qualified_index(
    index: peri_scribe.models.FireIndex,
    histories: Histories,
) -> peri_scribe.models.FireIndex:
    """Apply the existing qualification policy without reconstructing source rows.

    Args:
        index: Current names, statuses and identity metadata.
        histories: Already prepared evidence used for qualification.

    Returns:
        The index selected by the same policy used on complete input layers.
    """
    empty = geopandas.GeoDataFrame()
    return peri_scribe.presentation.index.area_qualified_index(
        index,
        empty,
        empty,
        histories=histories,
    )


def complete_for_index(
    index: peri_scribe.models.FireIndex,
    histories: Histories,
) -> bool:
    """Require prepared evidence wherever presentation would otherwise rebuild it.

    Args:
        index: The qualified entries whose descriptions and plots will be prepared.
        histories: The exact canonical histories available to those consumers.

    Returns:
        Whether every entry has its directly selected complete history.
    """
    return all(
        peri_scribe.presentation.selection.fire_area_key(
            entry.identifier,
            entry.name,
            entry.component_id,
        )
        in histories
        for entry in index.fires
    )


def read_histories(key: str) -> Histories | None:
    """Validate every retained fact before permitting projected layer reads.

    Args:
        key: Complete current geography, identity and qualification dependency key.

    Returns:
        Qualified histories, including a valid empty result, or None on a cache miss.
    """
    payload = spatial_data.product_cache.get(NAMESPACE, key)
    if payload is None:
        return None
    try:
        histories = decoded_histories(spatial_data.cache_values.loads(payload))
        return histories if qualifying_histories(histories) == histories else None
    except ValueError, TypeError, pint.errors.PintError, compression.zstd.ZstdError:
        return None


def decoded_histories(records: object) -> Histories:
    """Reject malformed identities, duplicate owners and incomplete prepared facts.

    Args:
        records: Canonically decoded manifest records from the product store.

    Returns:
        Independently validated histories keyed by their complete area identity.

    Raises:
        TypeError: The manifest's top-level records are not a tuple.
        ValueError: A record has an invalid shape, identity or history payload.
    """
    if not isinstance(records, tuple):
        message = "Qualified history records must be a tuple"
        raise TypeError(message)
    histories: Histories = {}
    for record in records:
        if not isinstance(record, tuple) or len(record) != RECORD_FIELD_COUNT:
            message = "A qualified history requires an identity and payload"
            raise ValueError(message)
        identity, content = record
        if not valid_identity(identity) or not isinstance(content, bytes):
            message = "Invalid qualified history identity or payload"
            raise ValueError(message)
        if identity in histories:
            message = "Qualified history identities must be unique"
            raise ValueError(message)
        histories[identity] = read_compressed_history(content)
    return histories


def read_compressed_history(content: bytes) -> peri_scribe.areas.PreparedHistory:
    """Validate one complete compressed frame and its canonical history facts.

    Args:
        content: One history's compressed bytes from the qualified manifest.

    Returns:
        The complete history after exact typed and domain validation.

    Raises:
        ValueError: The compressed frame is incomplete or has trailing data.
    """
    decompressor = compression.zstd.ZstdDecompressor()
    payload = decompressor.decompress(content)
    if not decompressor.eof or decompressor.unused_data:
        message = "A qualified history requires one complete compressed frame"
        raise ValueError(message)
    return peri_scribe.presentation.prepared_cache.read_history(payload)


def valid_identity(
    value: object,
) -> typing.TypeIs[peri_scribe.presentation.selection.AreaKey]:
    """Recognize exactly the tagged area identities accepted by presentation.

    Args:
        value: One decoded manifest identity.

    Returns:
        Whether it names an identifier, anonymous component or legacy fire name.
    """
    return (
        isinstance(value, tuple)
        and len(value) == RECORD_FIELD_COUNT
        and all(isinstance(part, str) for part in value)
        and value[0] in {"id", "name", "component"}
    )


def write_histories(key: str, histories: Histories) -> None:
    """Store a complete qualified selection through the existing atomic product store.

    Args:
        key: Complete authenticated dependency identity.
        histories: Prepared histories from complete authoritative source layers.
    """
    try:
        payload = spatial_data.cache_values.dumps(
            tuple(
                (
                    identity,
                    compression.zstd.compress(
                        peri_scribe.presentation.prepared_cache.history_bytes(history),
                        level=2,
                    ),
                )
                for identity, history in sorted(qualifying_histories(histories).items())
            ),
        )
    except ValueError, compression.zstd.ZstdError:
        return
    spatial_data.product_cache.put(NAMESPACE, key, payload)


def selected_latest_positions(
    frame: geopandas.GeoDataFrame,
    index: peri_scribe.models.FireIndex,
) -> tuple[int, ...]:
    """Use the existing component and alias selector to demand latest attributes.

    Args:
        frame: The complete ordered identity columns for a geography layer.
        index: Qualified fire entries whose descriptions need source attributes.

    Returns:
        Every row position whose attributes a latest-row consumer may request.
    """
    if frame.empty:
        return ()
    rows = peri_scribe.presentation.history_index.HistoryRowIndex.from_frame(frame)
    return latest_positions(
        tuple(
            rows.positions_for(
                peri_scribe.presentation.selection.identifiers(entry),
                entry.name,
                entry.component_id,
            )
            for entry in index.fires
        ),
    )


def read_attribute_rows(
    path: pathlib.Path,
    layer_name: str,
    identifiers: tuple[int, ...],
) -> dict[int, object]:
    """Read demanded source attributes while the owning reader retains its year lock.

    Args:
        path: The authenticated GeoPackage whose geometry is already materialized.
        layer_name: Its perimeter or point history layer.
        identifiers: Exact GeoPackage feature IDs, including gaps when present.

    Returns:
        Attribute scalars keyed by original feature ID.
    """
    result: dict[int, object] = {}
    table = '"' + layer_name.replace('"', '""') + '"'
    with contextlib.closing(
        sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True),
    ) as connection:
        for offset in range(0, len(identifiers), ATTRIBUTE_BATCH_SIZE):
            batch = identifiers[offset : offset + ATTRIBUTE_BATCH_SIZE]
            placeholders = ",".join("?" for _ in batch)
            result.update(
                connection.execute(
                    f"SELECT fid, source_attributes FROM {table} "
                    f"WHERE fid IN ({placeholders})",
                    batch,
                ),
            )
    return result


def read_projected_layer(
    path: pathlib.Path,
    layer_name: str,
    index: peri_scribe.models.FireIndex,
) -> geopandas.GeoDataFrame:
    """Materialize geometry and latest demanded attributes from one locked generation.

    Args:
        path: The authenticated full or differential geography file.
        layer_name: A normalized perimeter or point history layer.
        index: Entries whose final selected source attributes must be preserved.

    Returns:
        Ordered geography with the original columns and attribute dtype.
        Undemanded source attributes are absent values, because prepared histories
        already supply all historical reporting facts to these internal map inputs.
    """
    with contextlib.closing(
        sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True),
    ) as connection:
        table = '"' + layer_name.replace('"', '""') + '"'
        fields = list(connection.execute(f"PRAGMA table_info({table})"))
        columns = [row[1] for row in fields]
        geometry_column = connection.execute(
            "SELECT column_name FROM gpkg_geometry_columns WHERE table_name = ?",
            (layer_name,),
        ).fetchone()[0]
        if ATTRIBUTE_COLUMN not in columns:
            return peri_scribe.fires.derived_layers.read_layer_if_present(
                path,
                layer_name,
            )
        if next(field[2] for field in fields if field[1] == ATTRIBUTE_COLUMN) != "TEXT":
            return peri_scribe.fires.derived_layers.read_layer_if_present(
                path,
                layer_name,
            )
        has_attribute_values = (
            connection.execute(
                f"SELECT 1 FROM {table} WHERE source_attributes IS NOT NULL LIMIT 1",
            ).fetchone()
            is not None
        )
    frame = geopandas.read_file(
        path,
        layer=layer_name,
        columns=[name for name in columns if name not in {ATTRIBUTE_COLUMN, "fid"}],
        fid_as_index=True,
        engine="pyogrio",
    )
    positions = selected_latest_positions(frame, index)
    identifiers = tuple(int(frame.index[position]) for position in positions)
    values = read_attribute_rows(path, layer_name, identifiers)
    attributes = [None] * len(frame)
    for position, identifier in zip(positions, identifiers, strict=True):
        attributes[position] = values[identifier]
    frame = frame.reset_index(drop=True)
    position = [name for name in columns if name not in {"fid", geometry_column}].index(
        ATTRIBUTE_COLUMN,
    )
    frame.insert(
        position,
        ATTRIBUTE_COLUMN,
        pd.Series(attributes, dtype="str" if has_attribute_values else "object"),
    )
    return frame


def read_projected_layers(
    year_directory: pathlib.Path,
    index: peri_scribe.models.FireIndex,
) -> peri_scribe.fires.derived_layers.DerivedLayers:
    """Finish every attribute read inside the caller's authenticated year lock.

    Args:
        year_directory: The locked geography generation owning these map inputs.
        index: Qualified fires with complete cached reporting histories.

    Returns:
        Perimeter and point evidence whose history attributes are loaded on demand.
    """
    full = peri_scribe.fires.files.history_geopackage_path(year_directory)
    differential = peri_scribe.fires.differential.differential_geopackage_path(
        year_directory,
    )
    return peri_scribe.fires.derived_layers.DerivedLayers(
        perimeters=read_projected_layer(
            full,
            peri_scribe.fires.files.PERIMETER_LAYER_NAME,
            index,
        ),
        points=read_projected_layer(
            full,
            peri_scribe.fires.files.POINT_LAYER_NAME,
            index,
        ),
        differential_perimeters=read_projected_layer(
            differential,
            peri_scribe.fires.files.PERIMETER_LAYER_NAME,
            peri_scribe.models.FireIndex(version=index.version, fires=[]),
        ),
    )


def prepare_inputs(
    year_directory: pathlib.Path,
    index: peri_scribe.models.FireIndex,
) -> PreparedInputs:
    """Prefer shared complete layers, then exact cached facts and projected geography.

    Args:
        year_directory: The year whose map and disposable products are being built.
        index: The complete current fire index.

    Returns:
        Safe map inputs, falling back to complete preparation on any optional miss.

    Raises:
        RuntimeError: A writer owns the geography or its published pair is invalid.
    """
    key = None
    store_manifest = True
    full = peri_scribe.fires.files.history_geopackage_path(year_directory)
    differential = peri_scribe.fires.differential.differential_geopackage_path(
        year_directory,
    )
    if (
        spatial_data.product_cache.active()
        and full.is_file()
        and differential.is_file()
    ):
        with peri_scribe.pipeline_state.read_lock(year_directory) as acquired:
            if not acquired:
                message = "A writer owns this year's geography; retry the read later"
                raise RuntimeError(message)
            identity = peri_scribe.fires.derived_layers.authenticated_pair(
                year_directory,
                full,
                differential,
                tolerate_missing=False,
            )
            identity = typing.cast("tuple[str, str]", identity)
            key = preparation_key(identity, index)
            shared = peri_scribe.execution.get(
                peri_scribe.execution.Group.DERIVED,
                (year_directory.resolve(), identity),
            )
            if isinstance(shared, peri_scribe.fires.derived_layers.DerivedLayers):
                store_manifest = spatial_data.product_cache.get(NAMESPACE, key) is None
            else:
                histories = read_histories(key)
                if histories is not None and complete_for_index(
                    qualified_index(index, histories),
                    histories,
                ):
                    try:
                        layers = read_projected_layers(
                            year_directory,
                            qualified_index(index, histories),
                        )
                    except (
                        KeyError,
                        ValueError,
                        sqlite3.Error,
                        pyogrio.errors.DataLayerError,
                        pyogrio.errors.DataSourceError,
                    ):
                        pass
                    else:
                        return PreparedInputs(layers=layers, histories=histories)
            layers = peri_scribe.fires.derived_layers.read_locked_derived_layers(
                year_directory,
                tolerate_missing=False,
            )
    else:
        layers = peri_scribe.fires.derived_layers.read_derived_layers(
            year_directory,
            tolerate_missing=False,
        )
    histories = peri_scribe.presentation.index.prepare_histories(
        index,
        layers.perimeters,
        layers.points,
        layers.incidents,
    )
    if key is not None and store_manifest:
        selected = qualifying_histories(histories)
        if complete_for_index(qualified_index(index, selected), selected):
            write_histories(key, histories)
    return PreparedInputs(layers=layers, histories=histories)
