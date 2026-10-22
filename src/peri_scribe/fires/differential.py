"""Build the differential perimeter history for a year's fires.

The differential history is derived from the full-history GeoPackage. Each perimeter
shows the area added over the previous one. Reductions in later perimeters are folded
into the previous perimeter as corrections, so the differential layer shows only growth.
Point and incident evidence belongs to the authenticated full-history file.

[Growth rings](../../../docs/algorithms/corrected-growth-rings.md)
[Generation and reuse](../../../docs/algorithms/geography-generations.md)
[Bounded history work](../../../docs/algorithms/history-work-queues.md)
"""

from __future__ import annotations

import functools
import os
import pathlib
import typing

import shapely
import structlog

import peri_scribe.concurrency
import peri_scribe.execution
import peri_scribe.fires.files
import peri_scribe.fires.history
import peri_scribe.fires.reuse
import peri_scribe.geo.growth_geometry
import peri_scribe.geo.measurements
import peri_scribe.geo.parsing
import peri_scribe.logging
import peri_scribe.perimeters.progression
import peri_scribe.phases
import peri_scribe.preparation
import spatial_data.layers
import spatial_data.surface_measurements


if typing.TYPE_CHECKING:
    import geopandas
    import pandas as pd


DIFFERENTIAL_OUTPUT_FILENAME = "history_of_differential_geography.gpkg"
DIFFERENTIAL_LAYER_NAMES = (peri_scribe.fires.files.PERIMETER_LAYER_NAME,)
logger = structlog.get_logger()

# Geometry calls release the GIL, but Python attribute work still competes for it. Keep
# the pool small so contention does not erase the benefit of parallel geometry work.
DIFFERENTIAL_WORKER_COUNT = min(4, os.cpu_count() or 1)

GROWTH_COLUMNS = [
    "area_acres",
    "percent_contained",
    "estimated_cost_to_date",
    "estimated_final_cost",
]

ATTRIBUTE_COLUMNS = [
    column
    for column in peri_scribe.fires.files.PERIMETER_COLUMNS
    if column != "geometry"
]

DIFFERENTIAL_PERIMETER_COLUMNS = [
    peri_scribe.fires.reuse.KEY_COLUMN,
    *peri_scribe.fires.history.IDENTITY_COLUMNS,
    "source",
    "source_subsource",
    "source_objectid",
    "source_globalid",
    "source_file",
    "source_serial",
    "observation_time",
    "created_time",
    "modified_time",
    "discovery_time",
    "area_acres",
    "area_acres_differential",
    "area_acres_from_geometry",
    "area_acres_from_geometry_differential",
    peri_scribe.geo.measurements.AREA_COLUMN,
    peri_scribe.perimeters.progression.ADDED_AREA_COLUMN,
    peri_scribe.perimeters.progression.SEQUENCE_COLUMN,
    "percent_contained",
    "percent_contained_differential",
    "containment_datetime",
    "estimated_cost_to_date",
    "estimated_cost_to_date_differential",
    "estimated_final_cost",
    "estimated_final_cost_differential",
    "type",
    "feature_category",
    "map_method",
    "mission",
    "description",
    "source_attributes",
    "geometry",
]


def differential_geopackage_path(year_directory: pathlib.Path) -> pathlib.Path:
    """Return the differential history GeoPackage path.

    Args:
        year_directory: The year directory that holds the ``derived`` directory.

    Returns:
        The output GeoPackage path.
    """
    return (
        year_directory
        / peri_scribe.fires.files.DERIVED_DIRECTORY_NAME
        / DIFFERENTIAL_OUTPUT_FILENAME
    )


def polygonal_area(geometry: shapely.Geometry | None) -> shapely.Geometry | None:
    """Return *geometry*'s polygonal area, or None when it has none.

    Args:
        geometry: The geometry to reduce, or None.

    Returns:
        The polygon or multi-polygon area, or None when the geometry is empty or has no
        polygonal parts.
    """
    return peri_scribe.geo.growth_geometry.polygonal(geometry)


def geometry_difference(
    current: shapely.Geometry | None,
    previous: shapely.Geometry | None,
) -> shapely.Geometry | None:
    """Return the polygonal area of *current* outside *previous*.

    Args:
        current: The current geometry, or None.
        previous: The previous geometry, or None.

    Returns:
        The difference as a polygon or multi-polygon, or None when it is empty.
    """
    return peri_scribe.geo.growth_geometry.difference(current, previous)


def geometry_grows_beyond(
    current: shapely.Geometry | None,
    previous: shapely.Geometry | None,
) -> bool:
    """Check for potential polygonal growth without constructing the difference.

    Testing coverage avoids constructing a difference when the caller only needs to know
    whether a perimeter adds area. It usually agrees with ``geometry_difference(current,
    previous) is not None``. Numerical edge cases can disagree: the coverage test can
    report growth whose constructed difference collapses to an empty sliver.
    ``differential_rows_for_fire`` drops those cases when it builds the rows.

    Args:
        current: The current geometry, or None.
        previous: The previous geometry, or None.

    Returns:
        True when the coverage test finds possible growth. Constructing the difference
        can still yield no polygonal area in numerical edge cases.
    """
    if current is None or current.is_empty:
        return False
    if previous is None or previous.is_empty:
        return polygonal_area(current) is not None
    return not previous.covers(current)


def geometry_intersection(
    current: shapely.Geometry | None,
    later: shapely.Geometry | None,
) -> shapely.Geometry | None:
    """Return the polygonal area shared by *current* and *later*.

    Args:
        current: The earlier geometry, or None.
        later: The later geometry, or None.

    Returns:
        The intersection as a polygon or multi-polygon, or None when it is empty.
    """
    return peri_scribe.geo.growth_geometry.intersection(current, later)


def corrected_geometries(
    geometries: typing.Sequence[shapely.Geometry | None],
) -> list[shapely.Geometry | None]:
    """Return each perimeter reduced by every later perimeter.

    Args:
        geometries: The full perimeters for one fire, in chronological order.

    Returns:
        One corrected geometry per perimeter. The area a later perimeter no longer
        covers is removed from every earlier perimeter.
    """
    corrected: list[shapely.Geometry | None] = [None] * len(geometries)
    if not geometries:
        return corrected
    corrected[-1] = peri_scribe.geo.growth_geometry.normalize(geometries[-1])
    for index in range(len(geometries) - 2, -1, -1):
        corrected[index] = geometry_intersection(
            geometries[index],
            corrected[index + 1],
        )
    return corrected


def growth_indices(corrected: typing.Sequence[shapely.Geometry | None]) -> list[int]:
    """Return the indices of *corrected* that add area over their predecessor.

    Args:
        corrected: The corrected perimeters for one fire.

    Returns:
        The indices whose corrected geometry adds area over the previous one, in order.
    """
    indices: list[int] = []
    previous: shapely.Geometry | None = None
    for index, geometry in enumerate(corrected):
        if geometry_grows_beyond(geometry, previous):
            indices.append(index)
        previous = geometry
    return indices


def representative_indices(
    survivors: list[int],
    perimeter_count: int,
) -> dict[int, int]:
    """Return the full-perimeter index each surviving growth step represents.

    Perimeters that add no area still correct the preceding growth step. That step
    therefore takes the attributes of the last correcting perimeter before the next
    growth step.

    Args:
        survivors: The surviving (growth) perimeter indices, in order.
        perimeter_count: The number of full perimeters.

    Returns:
        Each survivor index mapped to the full-perimeter index whose attributes it
        keeps.
    """
    representatives: dict[int, int] = {}
    for position, survivor in enumerate(survivors):
        if position + 1 < len(survivors):
            representatives[survivor] = survivors[position + 1] - 1
        else:
            representatives[survivor] = perimeter_count - 1
    return representatives


def growth_difference(current: object, previous: list[object]) -> float | None:
    """Return *current* minus the most recent present value in *previous*.

    Args:
        current: The current attribute value.
        previous: Earlier attribute values, most recent first.

    Returns:
        The difference, or None when the current value is missing.
    """
    current_value = peri_scribe.geo.parsing.numeric_value(current)
    if current_value is None:
        return None
    subtrahend = 0.0
    for value in previous:
        numeric = peri_scribe.geo.parsing.numeric_value(value)
        if numeric is not None:
            subtrahend = numeric
            break
    return current_value - subtrahend


def row_identity(row: pd.Series, identity_columns: list[str]) -> tuple[object, ...]:
    """Return *row*'s identity, with missing values normalized to None.

    Args:
        row: One perimeter history row.
        identity_columns: The columns that identify the fire.

    Returns:
        The identity values, with missing values replaced by None so rows compare.
    """
    return tuple(
        None if peri_scribe.geo.parsing.is_missing(row.get(column)) else row[column]
        for column in identity_columns
    )


def fire_positions(frame: geopandas.GeoDataFrame) -> list[list[int]]:
    """Return the positions of each fire's consecutive perimeter rows.

    Args:
        frame: The full perimeter history.

    Returns:
        One position list per fire, in order.
    """
    groups: list[list[int]] = []
    current_key: tuple[object, ...] | None = None
    current: list[int] = []
    identity_columns = peri_scribe.fires.history.IDENTITY_COLUMNS
    for position in range(len(frame)):
        key = row_identity(frame.iloc[position], identity_columns)
        if current and key != current_key:
            groups.append(current)
            current = []
        current_key = key
        current.append(position)
    if current:
        groups.append(current)
    return groups


def group_records(
    frame: geopandas.GeoDataFrame,
    positions: list[int],
) -> tuple[list[dict[str, object]], list[shapely.Geometry | None]]:
    """Return the attribute rows and geometries for *positions*.

    Args:
        frame: The full perimeter history.
        positions: The row positions for one fire.

    Returns:
        The attribute rows and their geometries, aligned by index.
    """
    attributes: list[dict[str, object]] = []
    geometries: list[shapely.Geometry | None] = []
    for position in positions:
        row = frame.iloc[position]
        attributes.append({column: row[column] for column in ATTRIBUTE_COLUMNS})
        geometries.append(frame.geometry.iloc[position])
    return attributes, geometries


def serializable_growth_geometry(
    geometry: shapely.Geometry,
) -> shapely.MultiPolygon:
    """Match the multipart geometry representation restored from GeoPackage.

    A fresh multipart wrapper also clears transient GEOS precision metadata. Measuring
    that representation binds prepared values to the same input a reader will use.

    Args:
        geometry: A nonempty polygonal growth result on the common precision grid.

    Returns:
        A fresh multipart geometry with identical coordinates and no precision metadata.
    """
    parts = (
        [geometry]
        if isinstance(geometry, shapely.Polygon)
        else list(typing.cast("shapely.MultiPolygon", geometry).geoms)
    )
    return shapely.MultiPolygon(parts)


def differential_rows_for_fire(
    attributes: list[dict[str, object]],
    geometries: list[shapely.Geometry | None],
) -> list[dict[str, object]]:
    """Return the differential perimeter rows for one fire.

    Args:
        attributes: The full perimeter attributes for the fire.
        geometries: The full perimeter geometries for the fire.

    Returns:
        One differential row per growth step, in chronological order.
    """
    corrected = corrected_geometries(geometries)
    survivors = growth_indices(corrected)
    representatives = representative_indices(survivors, len(geometries))
    rows: list[dict[str, object]] = []
    for position, survivor in enumerate(survivors):
        cumulative_geometry = typing.cast("shapely.Geometry", corrected[survivor])
        previous_geometry = None if survivor == 0 else corrected[survivor - 1]
        differential_geometry = typing.cast(
            "shapely.Geometry",
            geometry_difference(cumulative_geometry, previous_geometry),
        )
        if differential_geometry is None:
            # A coverage test can report growth that collapses to an empty sliver when
            # the difference is constructed. With no visible area, it adds no ring.
            continue
        differential_geometry = serializable_growth_geometry(differential_geometry)
        representative = representatives[survivor]
        row = dict(attributes[representative])
        row["geometry"] = differential_geometry
        for column in GROWTH_COLUMNS:
            cumulative_value = attributes[representative].get(column)
            row[column] = cumulative_value
            row[f"{column}_differential"] = growth_difference(
                cumulative_value,
                [
                    attributes[representatives[earlier]].get(column)
                    for earlier in reversed(survivors[:position])
                ],
            )
        row["area_acres_from_geometry"] = spatial_data.surface_measurements.area(
            cumulative_geometry,
        ).m_as("acres")
        ring_area = spatial_data.surface_measurements.area(differential_geometry)
        row["area_acres_from_geometry_differential"] = ring_area.m_as("acres")
        row[peri_scribe.geo.measurements.AREA_COLUMN] = ring_area.m_as("meters ** 2")
        rows.append(row)
    measure_drawn_rings(rows)
    return rows


def measure_drawn_rings(rows: list[dict[str, object]]) -> None:
    """Persist added ground for the same dated, visible rings the map displays.

    Args:
        rows: One fire's differential rows in progression order, including geometry,
            observation time, and measured area; selected rows receive added-area
            measurements and the sequence digest in place.
    """
    selected = [
        row
        for row in rows
        if peri_scribe.geo.parsing.observation_time_from(row["observation_time"])
        is not None
        and typing.cast("float", row[peri_scribe.geo.measurements.AREA_COLUMN])
        > peri_scribe.perimeters.progression.MINIMUM_RING_AREA.m_as("meters ** 2")
    ]
    geometries = [typing.cast("shapely.Geometry", row["geometry"]) for row in selected]
    digest = peri_scribe.perimeters.progression.sequence_digest(geometries)
    areas = peri_scribe.perimeters.progression.added_areas(geometries)
    for row, area in zip(selected, areas, strict=True):
        row[peri_scribe.perimeters.progression.ADDED_AREA_COLUMN] = area.m_as(
            "meters ** 2",
        )
        row[peri_scribe.perimeters.progression.SEQUENCE_COLUMN] = digest


def differential_group_rows(
    group: tuple[list[dict[str, object]], list[shapely.Geometry | None]],
    *,
    reused: dict[str, peri_scribe.fires.reuse.Rows],
) -> tuple[peri_scribe.fires.reuse.Rows, bool]:
    """Keep one fire's inputs and result within the bounded work queue.

    Args:
        group: Source attributes and geometries for one fire.
        reused: Validated rows keyed by complete source fingerprint.

    Returns:
        The fire's rows and whether they came from validated history.
    """
    attributes, geometries = group
    key = str(attributes[0].get(peri_scribe.fires.reuse.KEY_COLUMN))
    cached = reused.get(key)
    if cached is not None and row_classifications(attributes) == row_classifications(
        cached,
    ):
        return cached, True
    return differential_rows_for_fire(attributes, geometries), False


def row_classifications(rows: peri_scribe.fires.reuse.Rows) -> frozenset[str | None]:
    """Return normalized classifications so reuse can detect newly available evidence.

    GDAL and pandas represent a missing classification with several scalar null values.
    Normalize those values so an equivalent representation does not invalidate an
    otherwise unchanged history. A newly available classification must still differ
    from a missing one so the caller knows to recompute unclassified rings.

    Args:
        rows: Full or differential rows belonging to one fire.

    Returns:
        The normalized classification values present throughout the history.
    """
    return frozenset(
        None if peri_scribe.geo.parsing.is_missing(value) else str(value)
        for row in rows
        for value in (row.get("border_classification"),)
    )


def differential_perimeter_dataframe(
    full_perimeters: geopandas.GeoDataFrame,
    *,
    reused: dict[str, peri_scribe.fires.reuse.Rows] | None = None,
) -> geopandas.GeoDataFrame:
    """Build the differential perimeter history from the full history.

    Each fire's growth rows are derived from only that fire's perimeters, and the
    intersection and area work releases the GIL, so the fires are processed in parallel
    and their rows are collected in fire order.

    Args:
        full_perimeters: The full perimeter history layer.
        reused: Validated differential rows keyed by their fire's derivation key, or
            None when all fires must be derived.

    Returns:
        The differential perimeter rows as a GeoDataFrame in the output spatial
        reference.
    """
    reused = {} if reused is None else reused
    groups = (
        group_records(full_perimeters, positions)
        for positions in fire_positions(full_perimeters)
    )
    rows: list[dict[str, object]] = []
    reused_count = 0
    recomputed_count = 0
    with peri_scribe.concurrency.ordered_parallel_map(
        functools.partial(differential_group_rows, reused=reused),
        groups,
        max_workers=DIFFERENTIAL_WORKER_COUNT,
        max_pending=peri_scribe.fires.history.HISTORY_TASK_BUFFER_SIZE,
    ) as results:
        for fire_rows, was_reused in results:
            rows.extend(fire_rows)
            reused_count += was_reused
            recomputed_count += not was_reused
    logger.info(
        "Differential history reuse",
        reused=reused_count,
        recomputed=recomputed_count,
    )
    return peri_scribe.fires.history.build_dataframe(
        rows,
        DIFFERENTIAL_PERIMETER_COLUMNS,
    )


def differential_generation(
    full_path: pathlib.Path,
    year_directory: pathlib.Path,
) -> str | None:
    """Bind growth rings to complete authenticated full-history output and native code.

    Args:
        full_path: The full-history GeoPackage providing perimeter and point evidence.
        year_directory: The year whose derivation settings and dependencies apply.

    Returns:
        The differential input generation, or None for unauthenticated full history.
    """
    signature = peri_scribe.fires.reuse.validated_signature(
        full_path,
        peri_scribe.fires.files.FULL_LAYER_NAMES,
    )
    if signature is None:
        return None
    return peri_scribe.fires.reuse.data_digest({
        "full_history": signature.checksum,
        "context": peri_scribe.fires.reuse.derivation_context(year_directory),
    })


@peri_scribe.preparation.cached_year
def write_history_of_differential_geography(
    year_directory: pathlib.Path,
    *,
    unconditional: bool = False,
) -> pathlib.Path:
    """Build and write the canonical differential perimeter history.

    The full history is built first so the differential always matches the current
    source data. The output holds a ``perimeter_history`` layer of per-perimeter growth.
    Unchanged fires retain their rings and measurements; changes rebuild the fire's
    complete sequence.

    Args:
        year_directory: The year directory that holds the ``sources`` directory.
        unconditional: Bypass prior full and differential history results.

    Returns:
        The path of the written differential GeoPackage.
    """
    unconditional = peri_scribe.preparation.unconditional_rebuild(
        requested=unconditional,
    )
    with peri_scribe.logging.log_phase(peri_scribe.phases.Phase.FULL_HISTORY):
        full_path = peri_scribe.fires.files.write_history_of_full_geography(
            year_directory,
            unconditional=unconditional,
        )
    peri_scribe.execution.clear(peri_scribe.execution.Group.SOURCES)
    with peri_scribe.logging.log_phase(peri_scribe.phases.Phase.DIFFERENTIAL_HISTORY):
        output_path = differential_geopackage_path(year_directory)
        generation = differential_generation(full_path, year_directory)
        if (
            not unconditional
            and generation is not None
            and peri_scribe.fires.reuse.generation_matches(
                output_path,
                generation,
                DIFFERENTIAL_LAYER_NAMES,
            )
        ):
            logger.info("Differential geography unchanged", path=str(output_path))
            return output_path
        full_perimeters = peri_scribe.fires.reuse.read_published_layer(
            full_path,
            peri_scribe.fires.files.PERIMETER_LAYER_NAME,
        )
        cached = peri_scribe.fires.reuse.read_rows(
            output_path,
            (peri_scribe.fires.files.PERIMETER_LAYER_NAME,),
            unconditional=unconditional,
            keys=frozenset(
                str(key)
                for key in full_perimeters.get(peri_scribe.fires.reuse.KEY_COLUMN, ())
            ),
        )
        peri_scribe.fires.reuse.write_layers(
            output_path,
            [
                spatial_data.layers.LayerData(
                    name=peri_scribe.fires.files.PERIMETER_LAYER_NAME,
                    dataframe=differential_perimeter_dataframe(
                        full_perimeters,
                        reused=cached.get(
                            peri_scribe.fires.files.PERIMETER_LAYER_NAME,
                            {},
                        ),
                    ),
                ),
            ],
            generation=generation,
        )
    return output_path
