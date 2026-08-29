"""Scoring fires to surface the ones people are most interested in.

Each fire's score is a weighted sum of points awarded across independent signals: its
reported size, its largest single growth step, its size when first mapped, the buildings
within a mile of it, whether it overlaps an evacuation zone, and its official incident
complexity level. The score is a pure function of the current data: it never looks at
previously recorded scores, so deleting the scores file and regenerating it changes
nothing.

The score is derived from the differential history GeoPackage (for size, growth,
first-mapping size) and the cumulative full history (for geometry), plus the point
history (for the official complexity level), then joined spatially against the retrieved
external datasets: building centroids and evacuation zones. Each external GeoPackage is
queried through its R-Tree index, so only the features near a fire are ever read from
it.

The results are written to ``{year}/derived/fire_scores.json``, along with a
``{year}/derived/fire_scores_ccdf.png`` complementary CDF of the scores.
"""

from __future__ import annotations

import dataclasses
import json
import os
import pathlib
import sqlite3
import typing
from concurrent.futures import ThreadPoolExecutor

import geopandas
import numpy as np
import pandas as pd
import pyogrio
import pyproj
import shapely

import peri_scribe.external_sources
import peri_scribe.fire_differential
import peri_scribe.fire_history
import peri_scribe.geo_package
import peri_scribe.models
import peri_scribe.output
import peri_scribe.snapshots


SCORE_OUTPUT_FILENAME = "fire_scores.json"
CCDF_OUTPUT_FILENAME = "fire_scores_ccdf.png"

FIRE_SCORES_VERSION = "2026-08-28"

# The buffer around a fire's footprint used to count threatened buildings.
BUILDING_BUFFER_IN_METERS = 1609.34

# The maximum number of features read from an external layer at once when scoring.
SCORING_CHUNK_SIZE = 100_000

WEB_MERCATOR_SPATIAL_REFERENCE_ID = 3857

WGS84_SPATIAL_REFERENCE = pyproj.CRS.from_epsg(
    peri_scribe.models.WGS84_SPATIAL_REFERENCE_ID,
)
WEB_MERCATOR_SPATIAL_REFERENCE = pyproj.CRS.from_epsg(
    WEB_MERCATOR_SPATIAL_REFERENCE_ID,
)

# Size, growth, first-mapping, and building-count tiers. Each tier is a (threshold,
# points) pair ordered from the largest threshold down; a value that meets no tier
# scores zero.
SIZE_TIERS = (
    (100_000.0, 5),
    (50_000.0, 4),
    (25_000.0, 3),
    (10_000.0, 2),
    (1_000.0, 1),
)
GROWTH_TIERS = (
    (50_000.0, 4),
    (25_000.0, 3),
    (10_000.0, 2),
    (5_000.0, 1),
)
FIRST_MAPPING_TIERS = (
    (5_000.0, 3),
    (1_000.0, 2),
    (100.0, 1),
)
BUILDING_COUNT_TIERS = (
    (1_000.0, 4),
    (250.0, 3),
    (50.0, 2),
    (5.0, 1),
)

# Points awarded for overlapping each external hazard or threat layer.
EVACUATION_POINTS = 3

# Official importance points by incident complexity level.
IMPORTANCE_POINTS_BY_LEVEL = {
    "Type 1 Incident": 3,
    "Type 2 Incident": 2,
    "Type 3 Incident": 1,
}

# Weight applied to each signal's points when composing the total score. The weights are
# calibrated so that the fires people are most interested in stand out from the season's
# population; the official complexity level dominates, and the reported size, growth,
# and evacuation signals carry the most weight, with the building count as a modest
# tiebreaker.
SIZE_WEIGHT = 27
GROWTH_WEIGHT = 15
FIRST_MAPPING_WEIGHT = 11
BUILDINGS_WEIGHT = 4
EVACUATION_WEIGHT = 11
IMPORTANCE_WEIGHT = 120


def tiered_points(
    value: float | None,
    tiers: tuple[tuple[float, int], ...],
) -> int:
    """Return the points for the first tier *value* meets, or zero.

    Args:
        value: The measured value, or None when unknown.
        tiers: ``(threshold, points)`` pairs ordered from largest threshold down.

    Returns:
        The points of the first tier whose threshold *value* meets, or 0.
    """
    if value is None:
        return 0
    for threshold, points in tiers:
        if value >= threshold:
            return points
    return 0


def importance_points(complexity_level: str | None) -> int:
    """Return the official-importance points for a complexity level.

    Args:
        complexity_level: The incident complexity level, or None.

    Returns:
        The points for the level, or 0 when the level is unrecognized.
    """
    return IMPORTANCE_POINTS_BY_LEVEL.get(complexity_level, 0)


def complexity_level(source_attributes_json: object) -> str | None:
    """Return the incident complexity level from a source-attributes JSON string.

    Args:
        source_attributes_json: A row's serialized source attributes.

    Returns:
        The incident complexity level, or None when it is absent or unreadable.
    """
    if source_attributes_json is None:
        return None
    try:
        attributes = json.loads(str(source_attributes_json))
    except json.JSONDecodeError, TypeError:
        return None
    if not isinstance(attributes, dict):
        return None
    value = attributes.get("IncidentComplexityLevel")
    return str(value) if value is not None else None


def union_geometry(geometries: geopandas.GeoSeries) -> shapely.Geometry | None:
    """Return the union of *geometries*, or None when there is none.

    Args:
        geometries: The geometries to combine.

    Returns:
        The union of the non-empty geometries, or None when all are empty or missing.
    """
    non_empty = [
        geometry
        for geometry in geometries
        if geometry is not None and not geometry.is_empty
    ]
    if not non_empty:
        return None
    if len(non_empty) == 1:
        return non_empty[0]
    return shapely.union_all(non_empty)


@dataclasses.dataclass(frozen=True, kw_only=True)
class PerimeterMetrics:
    """The size and growth measurements derived from a fire's perimeters."""

    area_acres: float | None
    growth_acres: float | None
    first_mapping_acres: float | None
    geometry: shapely.Geometry | None


def fire_importance_points(points: geopandas.GeoDataFrame) -> int:
    """Return the highest official-importance points among a fire's observations.

    Args:
        points: The fire's point-history rows.

    Returns:
        The highest importance points across the rows, or 0 when there are none.
    """
    if points.empty:
        return 0
    levels = (
        complexity_level(attributes) for attributes in points["source_attributes"]
    )
    return max((importance_points(level) for level in levels), default=0)


def buffered_fire_geometries(
    geometries: list[shapely.Geometry | None],
) -> list[shapely.Geometry | None]:
    """Return each fire geometry buffered by the building-count distance, or None.

    The geometries are reprojected to web mercator in one vectorized pass, buffered in
    parallel across a small thread pool (the GEOS buffer releases the GIL), and
    reprojected back in one vectorized pass.

    Args:
        geometries: The fire geometries, in WGS84.

    Returns:
        One buffered WGS84 geometry per fire, None where the fire has no geometry.
    """
    result: list[shapely.Geometry | None] = [None] * len(geometries)
    present = [
        (index, geometry)
        for index, geometry in enumerate(geometries)
        if geometry is not None
    ]
    if not present:
        return result
    metric = geopandas.GeoSeries(
        [geometry for _index, geometry in present],
        crs=WGS84_SPATIAL_REFERENCE,
    ).to_crs(WEB_MERCATOR_SPATIAL_REFERENCE)
    with ThreadPoolExecutor(max_workers=_buffer_worker_count()) as executor:
        buffered_metric = list(executor.map(_buffer_geometry, metric))
    buffered = geopandas.GeoSeries(
        buffered_metric,
        crs=WEB_MERCATOR_SPATIAL_REFERENCE,
    ).to_crs(WGS84_SPATIAL_REFERENCE)
    for (index, _geometry), buffered_geometry in zip(present, buffered, strict=True):
        result[index] = buffered_geometry
    return result


def _buffer_geometry(geometry: shapely.Geometry) -> shapely.Geometry:
    """Return *geometry* buffered by the building-count distance.

    Args:
        geometry: The geometry to buffer.

    Returns:
        The buffered geometry.
    """
    return geometry.buffer(BUILDING_BUFFER_IN_METERS)


def _buffer_worker_count() -> int:
    """Return a sensible number of buffer threads for this machine.

    Returns:
        The number of worker threads, between 1 and 8.
    """
    return max(1, min(8, os.cpu_count() or 1))


def _gpkg_geometry_header_size(flags: int) -> int:
    """Return a GeoPackage geometry blob's header size for its flags byte.

    A point's envelope is trivial, so points store no envelope and use the 8-byte
    header. Other geometries store an XY envelope (40-byte header) or, when they carry a
    Z, an XYZ envelope (56-byte header).

    Args:
        flags: The geometry blob's flags byte.

    Returns:
        The header size in bytes.
    """
    if flags & 0x04:
        return 56
    if flags & 0x02:
        return 40
    return 8


def _gpkg_blob_geometry(blob: bytes) -> bytes:
    """Return the WKB payload of a GeoPackage geometry blob.

    Args:
        blob: The raw GeoPackage geometry blob.

    Returns:
        The WKB geometry payload.
    """
    return blob[_gpkg_geometry_header_size(blob[3]) :]


def _has_rtree(path: pathlib.Path, layer_name: str) -> bool:
    """Return True when the GeoPackage has an R-Tree index for *layer_name*.

    Args:
        path: The GeoPackage file.
        layer_name: The layer to check.

    Returns:
        True when the layer has an R-Tree index.
    """
    connection = sqlite3.connect(path)
    try:
        row = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (f"rtree_{layer_name}_geom",),
        ).fetchone()
        return row is not None
    finally:
        connection.close()


def _candidate_fids(
    path: pathlib.Path,
    layer_name: str,
    boxes: list[tuple[int, float, float, float, float]],
) -> dict[int, list[int]]:
    """Return, per box index, the feature ids whose R-Tree envelope overlaps the box.

    Each box is ``(index, min_x, min_y, max_x, max_y)``.

    Args:
        path: The GeoPackage file.
        layer_name: The layer to query.
        boxes: The boxes to query, as ``(index, min_x, min_y, max_x, max_y)`` tuples.

    Returns:
        A mapping from box index to the feature ids whose envelopes overlap that box.
    """
    connection = sqlite3.connect(path)
    try:
        result: dict[int, list[int]] = {}
        for index, min_x, min_y, max_x, max_y in boxes:
            fids = [
                row[0]
                for row in connection.execute(
                    f"SELECT id FROM rtree_{layer_name}_geom "
                    "WHERE minx <= ? AND maxx >= ? AND miny <= ? AND maxy >= ?",
                    (max_x, min_x, max_y, min_y),
                )
            ]
            if fids:
                result[index] = fids
        return result
    finally:
        connection.close()


def _fetch_layer_geometries(
    path: pathlib.Path,
    layer_name: str,
    fids: typing.Iterable[int],
) -> np.ndarray:
    """Return the geometries of *fids* from *layer_name*, in fid order.

    The features are read straight from the GeoPackage's SQLite storage via a temporary
    table left-joined to the layer, so each candidate is an indexed ``fid`` lookup and
    no attribute columns are parsed.

    Args:
        path: The GeoPackage file.
        layer_name: The layer to read.
        fids: The feature ids to fetch.

    Returns:
        The geometries as a numpy array of shapely geometries.
    """
    sorted_fids = sorted(fids)
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TEMP TABLE cand (fid INTEGER PRIMARY KEY)")
        connection.executemany(
            "INSERT OR IGNORE INTO cand VALUES (?)",
            ((fid,) for fid in sorted_fids),
        )
        blobs = [
            row[0]
            for row in connection.execute(
                f"SELECT b.geom FROM cand c LEFT JOIN {layer_name} b ON b.fid = c.fid",
            )
        ]
    finally:
        connection.close()
    geometry_wkb = np.asarray(
        [_gpkg_blob_geometry(blob) for blob in blobs],
        dtype=object,
    )
    return np.asarray(shapely.from_wkb(geometry_wkb))


def _count_points_within(
    points: np.ndarray,
    valid: list[tuple[int, shapely.Geometry]],
    counts: list[int],
) -> list[int]:
    """Accumulate, into *counts*, how many *points* fall inside each valid geometry.

    Args:
        points: The candidate points.
        valid: The ``(index, geometry)`` pairs to test against.
        counts: The per-fire counts, mutated in place.

    Returns:
        The updated *counts* list.
    """
    tree_geometries = np.asarray([geometry for _index, geometry in valid])
    tree = shapely.STRtree(tree_geometries)
    input_indices, tree_indices = tree.query(points)
    if len(input_indices) == 0:
        return counts
    within = shapely.within(points[input_indices], tree_geometries[tree_indices])
    for position, count in enumerate(
        np.bincount(tree_indices[within], minlength=len(valid)),
    ):
        if count:
            counts[valid[position][0]] += int(count)
    return counts


def building_counts_within(
    buffered_geometries: list[shapely.Geometry | None],
    path: pathlib.Path,
    layer_name: str,
    chunk_size: int = SCORING_CHUNK_SIZE,
) -> list[int]:
    """Return how many building points lie within each buffered geometry.

    The buildings GeoPackage's R-Tree index is used to fetch only the building points
    whose envelopes overlap a buffered fire footprint, so the layer is never read whole;
    the fetched points are then tested for containment through a spatial index over the
    buffered geometries. The buildings layer is in WGS84, matching the buffered
    geometries.

    Args:
        buffered_geometries: One buffered geometry per fire, in WGS84, or None.
        path: The buildings GeoPackage.
        layer_name: The buildings layer.
        chunk_size: The maximum number of features read at once when the layer has no
            R-Tree index and the streaming fallback is used.

    Returns:
        One building count per fire, aligned with *buffered_geometries*.
    """
    valid = [
        (index, geometry)
        for index, geometry in enumerate(buffered_geometries)
        if geometry is not None and not geometry.is_empty
    ]
    counts = [0] * len(buffered_geometries)
    if not valid:
        return counts
    if _has_rtree(path, layer_name):
        boxes = [(index, *geometry.bounds) for index, geometry in valid]
        fire_fids = _candidate_fids(path, layer_name, boxes)
        if fire_fids:
            fids = sorted({fid for fids in fire_fids.values() for fid in fids})
            _count_points_within(
                _fetch_layer_geometries(path, layer_name, fids),
                valid,
                counts,
            )
        return counts
    for chunk in peri_scribe.geo_package.read_layer_chunks(
        path,
        layer_name,
        chunk_size,
    ):
        _count_points_within(np.asarray(chunk.geometry), valid, counts)
    return counts


def overlapping_fire_indices(
    geometries: list[shapely.Geometry | None],
    path: pathlib.Path,
    layer_name: str,
    chunk_size: int = SCORING_CHUNK_SIZE,
) -> set[int]:
    """Return the indices of *geometries* that overlap a feature of *layer_name*.

    The layer's R-Tree index is used to fetch only the features whose envelopes overlap
    a fire footprint, then those features are tested for intersection through a spatial
    index over the fire geometries. The fire geometries are transformed to the layer's
    spatial reference; a layer without one is treated as WGS84.

    Args:
        geometries: The fire geometries, in WGS84, or None.
        path: The layer's GeoPackage.
        layer_name: The layer to read.
        chunk_size: The maximum number of features read at once when the layer has no
            R-Tree index and the streaming fallback is used.

    Returns:
        The indices of the geometries that overlap at least one layer feature.
    """
    valid = [
        (index, geometry)
        for index, geometry in enumerate(geometries)
        if geometry is not None and not geometry.is_empty
    ]
    if not valid:
        return set()
    raw_crs = pyogrio.read_info(path, layer=layer_name)["crs"]
    layer_crs = (
        WGS84_SPATIAL_REFERENCE
        if raw_crs is None
        else pyproj.CRS.from_user_input(raw_crs)
    )
    valid_geometries = [geometry for _index, geometry in valid]
    if layer_crs.equals(WGS84_SPATIAL_REFERENCE):
        reprojected = valid_geometries
    else:
        reprojected = list(
            geopandas.GeoSeries(valid_geometries, crs=WGS84_SPATIAL_REFERENCE).to_crs(
                layer_crs,
            ),
        )
    reproj = [
        (index, geometry)
        for (index, _original), geometry in zip(valid, reprojected, strict=True)
    ]
    tree_geometries = np.asarray([geometry for _index, geometry in reproj])
    tree = shapely.STRtree(tree_geometries)
    if _has_rtree(path, layer_name):
        boxes = [(index, *geometry.bounds) for index, geometry in reproj]
        fire_fids = _candidate_fids(path, layer_name, boxes)
        if not fire_fids:
            return set()
        fids = sorted({fid for fids in fire_fids.values() for fid in fids})
        candidates = _fetch_layer_geometries(path, layer_name, fids)
        return _overlapping_indices(candidates, tree, tree_geometries, reproj)
    overlapping: set[int] = set()
    for chunk in peri_scribe.geo_package.read_layer_chunks(
        path,
        layer_name,
        chunk_size,
    ):
        overlapping.update(
            _overlapping_indices(
                np.asarray(chunk.geometry),
                tree,
                tree_geometries,
                reproj,
            ),
        )
    return overlapping


def _overlapping_indices(
    candidates: np.ndarray,
    tree: shapely.STRtree,
    tree_geometries: np.ndarray,
    reproj: list[tuple[int, shapely.Geometry]],
) -> set[int]:
    """Return the fire indices whose reprojected geometry intersects a candidate.

    Args:
        candidates: The layer features to test.
        tree: A spatial index over the reprojected fire geometries.
        tree_geometries: The reprojected fire geometries backing *tree*.
        reproj: The ``(index, geometry)`` pairs aligned with *tree_geometries*.

    Returns:
        The fire indices that intersect at least one candidate.
    """
    input_indices, tree_indices = tree.query(candidates)
    if len(input_indices) == 0:
        return set()
    intersects = shapely.intersects(
        candidates[input_indices],
        tree_geometries[tree_indices],
    )
    return {reproj[position][0] for position in np.unique(tree_indices[intersects])}


def identity_key(name: str, identifier: str | None) -> str:
    """Return the key that identifies a fire for score persistence.

    A fire's identifier is preferred; a fire without one is keyed by name.

    Args:
        name: The fire's name.
        identifier: The fire's canonical identifier, or None.

    Returns:
        The fire's stable key.
    """
    return identifier if identifier is not None else f"name:{name}"


def normalized_identifier(value: object) -> str | None:
    """Return an identifier as a string, or None when it is missing.

    Args:
        value: A row's identifier value.

    Returns:
        The identifier, or None when the value is missing.
    """
    if peri_scribe.geo_package.is_missing(value):
        return None
    return str(value)


def group_keys(dataframe: geopandas.GeoDataFrame) -> pd.Series:
    """Return the identity key for each history row.

    Args:
        dataframe: A history layer.

    Returns:
        One identity key per row, aligned with the dataframe's index.
    """
    if dataframe.empty:
        return pd.Series(dtype=object, index=dataframe.index)
    return pd.Series(
        [
            identity_key(
                str(name),
                normalized_identifier(identifier),
            )
            for name, identifier in zip(
                dataframe["fire_name"],
                dataframe["fire_identifier"],
                strict=True,
            )
        ],
        index=dataframe.index,
    )


@dataclasses.dataclass(frozen=True, kw_only=True)
class FireRecords:
    """A fire's identity and the history rows that describe it."""

    name: str
    identifier: str | None
    perimeters: geopandas.GeoDataFrame
    points: geopandas.GeoDataFrame


@dataclasses.dataclass(frozen=True, kw_only=True)
class FireScore:
    """A fire's current score and the points each signal contributed."""

    name: str
    identifier: str | None
    size_points: int
    growth_points: int
    first_mapping_points: int
    building_points: int
    evacuation_points: int
    importance_points: int

    @property
    def total(self) -> int:
        """Return the fire's total score."""
        return (
            self.size_points
            + self.growth_points
            + self.first_mapping_points
            + self.building_points
            + self.evacuation_points
            + self.importance_points
        )


def fire_score_for(
    record: FireRecords,
    metrics: PerimeterMetrics,
    *,
    building_count: int,
    evacuation_overlap: bool,
) -> FireScore:
    """Return the score for one fire from its history and external signals.

    Args:
        record: The fire's identity and history rows.
        metrics: The fire's size and growth measurements.
        building_count: The number of buildings within a mile of the fire.
        evacuation_overlap: Whether the fire overlaps an evacuation zone.

    Returns:
        The fire's score.
    """
    return FireScore(
        name=record.name,
        identifier=record.identifier,
        size_points=SIZE_WEIGHT * tiered_points(metrics.area_acres, SIZE_TIERS),
        growth_points=GROWTH_WEIGHT * tiered_points(metrics.growth_acres, GROWTH_TIERS),
        first_mapping_points=FIRST_MAPPING_WEIGHT
        * tiered_points(
            metrics.first_mapping_acres,
            FIRST_MAPPING_TIERS,
        ),
        building_points=BUILDINGS_WEIGHT
        * tiered_points(building_count, BUILDING_COUNT_TIERS),
        evacuation_points=EVACUATION_WEIGHT
        * (EVACUATION_POINTS if evacuation_overlap else 0),
        importance_points=IMPORTANCE_WEIGHT * fire_importance_points(record.points),
    )


def fire_scores_path(year_directory: pathlib.Path) -> pathlib.Path:
    """Return the path of the fire-scores JSON for *year_directory*.

    Args:
        year_directory: The year directory that holds the ``derived`` directory.

    Returns:
        The fire-scores output path.
    """
    return (
        year_directory
        / peri_scribe.fire_history.DERIVED_DIRECTORY_NAME
        / SCORE_OUTPUT_FILENAME
    )


def fire_scores_ccdf_path(year_directory: pathlib.Path) -> pathlib.Path:
    """Return the path of the fire-scores CCDF for *year_directory*.

    Args:
        year_directory: The year directory that holds the ``derived`` directory.

    Returns:
        The fire-scores CCDF output path.
    """
    return (
        year_directory
        / peri_scribe.fire_history.DERIVED_DIRECTORY_NAME
        / CCDF_OUTPUT_FILENAME
    )


def score_entry(
    fire_score: FireScore,
) -> peri_scribe.models.FireScoreEntry:
    """Return the persisted score entry for a fire.

    Args:
        fire_score: The fire's current score.

    Returns:
        The entry holding the fire's score and current components.
    """
    return peri_scribe.models.FireScoreEntry(
        name=fire_score.name,
        identifier=fire_score.identifier,
        score=fire_score.total,
        components=peri_scribe.models.FireScoreComponents(
            size=fire_score.size_points,
            growth=fire_score.growth_points,
            first_mapping=fire_score.first_mapping_points,
            buildings=fire_score.building_points,
            evacuation=fire_score.evacuation_points,
            importance=fire_score.importance_points,
        ),
    )


def fire_scores_document(
    entries: list[peri_scribe.models.FireScoreEntry],
) -> peri_scribe.models.FireScores:
    """Wrap *entries* in the current fire-scores document.

    Args:
        entries: The fire score entries, ordered most-to-least interesting.

    Returns:
        The validated fire-scores document.
    """
    return peri_scribe.models.FireScores(
        version=FIRE_SCORES_VERSION,
        fires=entries,
    )


def read_layer_if_present(
    path: pathlib.Path,
    layer_name: str,
) -> geopandas.GeoDataFrame:
    """Read a GeoPackage layer, returning an empty frame when the file is missing.

    Args:
        path: The GeoPackage file.
        layer_name: The layer to read.

    Returns:
        The layer's features, or an empty GeoDataFrame when the file is absent.
    """
    if not path.is_file():
        return geopandas.GeoDataFrame()
    return peri_scribe.geo_package.read_layer(path, layer_name)


def latest_snapshot_path(directory: pathlib.Path) -> pathlib.Path | None:
    """Return the path of the newest snapshot in *directory*, or None.

    Args:
        directory: A source directory holding serial-numbered snapshots.

    Returns:
        The newest snapshot's path, or None when the directory holds none.
    """
    source_files = peri_scribe.snapshots.existing_source_files(directory)
    if not source_files:
        return None
    return directory / source_files[-1].relative_path


def download_source_layer(
    year_directory: pathlib.Path,
    source: peri_scribe.external_sources.ExternalSource,
) -> tuple[pathlib.Path, str] | None:
    """Return the path and layer name of a downloaded external source, or None.

    Args:
        year_directory: The year directory that holds the ``sources`` directory.
        source: The download-kind external source.

    Returns:
        The source's GeoPackage path and layer name, or None when the source has no
        layer.
    """
    if source.layer_name is None:
        return None
    return (
        peri_scribe.external_sources.output_path(year_directory, source),
        source.layer_name,
    )


def latest_snapshot_layer(
    year_directory: pathlib.Path,
    source: peri_scribe.external_sources.ExternalSource,
) -> tuple[pathlib.Path, str] | None:
    """Return the path and layer name of a live source's newest snapshot, or None.

    Args:
        year_directory: The year directory that holds the ``sources`` directory.
        source: The live external source.

    Returns:
        The newest snapshot's path and layer name, or None when the source has no
        layer or no snapshot.
    """
    if source.layer_name is None:
        return None
    directory = peri_scribe.external_sources.source_directory_path(
        year_directory,
        source,
    )
    path = latest_snapshot_path(directory)
    if path is None:
        return None
    return path, source.layer_name


def read_latest_snapshot(
    year_directory: pathlib.Path,
    source: peri_scribe.external_sources.ExternalSource,
) -> geopandas.GeoDataFrame:
    """Read the newest snapshot of a live external source.

    Args:
        year_directory: The year directory that holds the ``sources`` directory.
        source: The live external source.

    Returns:
        The newest snapshot's features, or an empty GeoDataFrame when there are none.
    """
    layer = latest_snapshot_layer(year_directory, source)
    if layer is None:
        return geopandas.GeoDataFrame()
    path, layer_name = layer
    return peri_scribe.geo_package.read_layer(path, layer_name)


@dataclasses.dataclass(frozen=True, kw_only=True)
class ExternalSignals:
    """The external spatial signals for every fire, aligned with the records."""

    building_counts: tuple[int, ...]
    evacuation_indices: frozenset[int]


def external_signals(
    year_directory: pathlib.Path,
    fire_count: int,
    geometries: list[shapely.Geometry | None],
    buffered: list[shapely.Geometry | None],
) -> ExternalSignals:
    """Compute each fire's external spatial signals.

    Each dataset is read only when its GeoPackage is present, so a missing dataset
    contributes nothing and a present one is queried through its R-Tree index rather
    than read whole. The returned counts and indices are aligned with the fires.

    Args:
        year_directory: The year directory that holds the ``sources`` directory.
        fire_count: The number of fires being scored.
        geometries: One geometry per fire, in WGS84, or None.
        buffered: One building-distance buffered geometry per fire, or None.

    Returns:
        The external signals for the fires.
    """
    buildings = download_source_layer(
        year_directory,
        peri_scribe.external_sources.BUILDINGS_SOURCE,
    )
    if buildings is not None and buildings[0].is_file():
        building_counts = building_counts_within(buffered, buildings[0], buildings[1])
    else:
        building_counts = [0] * fire_count
    evacuations = latest_snapshot_layer(
        year_directory,
        peri_scribe.external_sources.EVACUATIONS_SOURCE,
    )
    evacuation_indices = (
        overlapping_fire_indices(geometries, evacuations[0], evacuations[1])
        if evacuations is not None and evacuations[0].is_file()
        else set()
    )
    return ExternalSignals(
        building_counts=tuple(building_counts),
        evacuation_indices=frozenset(evacuation_indices),
    )


def _fire_identity(
    perimeters: geopandas.GeoDataFrame,
    points: geopandas.GeoDataFrame,
    perimeter_keys: pd.Series,
    point_keys: pd.Series,
) -> tuple[pd.Series, pd.Series]:
    """Return per-fire name and identifier Series, preferring perimeter rows.

    Args:
        perimeters: The differential perimeter layer.
        points: The point history layer.
        perimeter_keys: Each perimeter row's fire identity key.
        point_keys: Each point row's fire identity key.

    Returns:
        The per-fire name and identifier, keyed by fire identity.
    """
    names = pd.Series(dtype=object)
    identifiers = pd.Series(dtype=object)
    if not perimeters.empty:
        perimeter_first = (
            perimeters
            .assign(_key=perimeter_keys)
            .drop_duplicates("_key")
            .set_index("_key")
        )
        names = perimeter_first["fire_name"]
        identifiers = perimeter_first["fire_identifier"]
    if not points.empty:
        point_first = (
            points.assign(_key=point_keys).drop_duplicates("_key").set_index("_key")
        )
        names = names.combine_first(point_first["fire_name"])
        identifiers = identifiers.combine_first(point_first["fire_identifier"])
    return names, identifiers


def _perimeter_metrics_for(
    key: str,
    metrics: pd.DataFrame,
    first_mapping: pd.Series,
) -> PerimeterMetrics:
    """Return the perimeter metrics for a fire, or all-None when it has none.

    Args:
        key: The fire's identity key.
        metrics: The per-fire maximum area and growth, keyed by fire identity.
        first_mapping: The per-fire first-mapping area, keyed by fire identity.

    Returns:
        The fire's perimeter metrics.
    """
    if key not in metrics.index:
        return PerimeterMetrics(
            area_acres=None,
            growth_acres=None,
            first_mapping_acres=None,
            geometry=None,
        )
    row = metrics.loc[key]
    return PerimeterMetrics(
        area_acres=None if pd.isna(row.max_area) else row.max_area,
        growth_acres=None if pd.isna(row.max_growth) else row.max_growth,
        first_mapping_acres=peri_scribe.geo_package.numeric_value(
            first_mapping.get(key),
        ),
        geometry=None,
    )


def _read_history(
    year_directory: pathlib.Path,
) -> tuple[
    geopandas.GeoDataFrame,
    geopandas.GeoDataFrame,
    geopandas.GeoDataFrame,
]:
    """Return the differential perimeters, points, and full perimeters.

    Args:
        year_directory: The year directory that holds the ``derived`` directory.

    Returns:
        The differential perimeter layer, point layer, and full perimeter layer.
    """
    differential_path = peri_scribe.fire_differential.differential_geopackage_path(
        year_directory,
    )
    perimeters = read_layer_if_present(
        differential_path,
        peri_scribe.fire_history.PERIMETER_LAYER_NAME,
    )
    points = read_layer_if_present(
        differential_path,
        peri_scribe.fire_history.POINT_LAYER_NAME,
    )
    full_path = peri_scribe.fire_history.history_geopackage_path(year_directory)
    full_perimeters = read_layer_if_present(
        full_path,
        peri_scribe.fire_history.PERIMETER_LAYER_NAME,
    )
    return perimeters, points, full_perimeters


def _fire_metrics(
    perimeters: geopandas.GeoDataFrame,
    perimeter_keys: pd.Series,
) -> tuple[pd.DataFrame, pd.Series]:
    """Return per-fire size, growth, and first-mapping metrics.

    Args:
        perimeters: The differential perimeter layer.
        perimeter_keys: Each perimeter row's fire identity key.

    Returns:
        The per-fire maximum area and growth as a dataframe, and the first-mapping area
        as a series, both keyed by fire identity.
    """
    if perimeters.empty:
        return pd.DataFrame(), pd.Series(dtype=object)
    keyed = perimeters.assign(_key=perimeter_keys)
    metrics = keyed.groupby("_key", sort=False).agg(
        max_area=("area_acres", "max"),
        max_growth=("area_acres_differential", "max"),
    )
    first_mapping = (
        keyed
        .sort_values("observation_time")
        .groupby("_key", sort=False)
        .head(1)
        .set_index("_key")["area_acres"]
    )
    return metrics, first_mapping


def _fire_geometries(
    keys: list[str],
    full_perimeters: geopandas.GeoDataFrame,
    points: geopandas.GeoDataFrame,
    point_keys: pd.Series,
) -> list[shapely.Geometry | None]:
    """Return each fire's geometry from the cumulative history, else its points.

    Args:
        keys: The fires' identity keys, in score order.
        full_perimeters: The cumulative full perimeter layer.
        points: The point history layer.
        point_keys: Each point row's fire identity key.

    Returns:
        One geometry per fire, or None where the fire has no geometry.
    """
    last_full = pd.Series(dtype=object)
    if not full_perimeters.empty:
        full_keys = group_keys(full_perimeters)
        last_full = (
            full_perimeters
            .assign(_key=full_keys)
            .sort_values("observation_time")
            .groupby("_key", sort=False)
            .geometry.last()
        )
    point_unions = {
        str(key): union_geometry(group.geometry)
        for key, group in points.groupby(point_keys)
    }
    geometries: list[shapely.Geometry | None] = []
    for key in keys:
        geometry = last_full.get(key)
        if geometry is None:
            geometry = point_unions.get(key)
        geometries.append(geometry)
    return geometries


def _record_metrics(
    keys: list[str],
    metrics: pd.DataFrame,
    first_mapping: pd.Series,
) -> list[PerimeterMetrics]:
    """Return one perimeter-metrics record per fire.

    Args:
        keys: The fires' identity keys, in score order.
        metrics: The per-fire maximum area and growth, keyed by fire identity.
        first_mapping: The per-fire first-mapping area, keyed by fire identity.

    Returns:
        One perimeter metrics record per fire, aligned with *keys*.
    """
    return [_perimeter_metrics_for(key, metrics, first_mapping) for key in keys]


@dataclasses.dataclass(frozen=True, kw_only=True)
class _ScoringInput:
    """The per-fire inputs, precomputed and aligned in score order."""

    keys: list[str]
    names: list[str]
    identifiers: list[str | None]
    metrics: list[PerimeterMetrics]
    geometries: list[shapely.Geometry | None]
    buffered: list[shapely.Geometry | None]
    signals: ExternalSignals
    points_by_key: dict[str, geopandas.GeoDataFrame]
    empty_points: geopandas.GeoDataFrame
    empty_perimeters: geopandas.GeoDataFrame


def _scoring_input(year_directory: pathlib.Path) -> _ScoringInput:
    """Compute the per-fire inputs and external signals used to score fires.

    Args:
        year_directory: The year directory that holds the ``derived`` directory.

    Returns:
        The aligned per-fire inputs.
    """
    perimeters, points, full_perimeters = _read_history(year_directory)
    perimeter_keys = group_keys(perimeters)
    point_keys = group_keys(points)
    keys = sorted(set(perimeter_keys) | set(point_keys))
    metrics, first_mapping = _fire_metrics(perimeters, perimeter_keys)
    names, identifiers = _fire_identity(
        perimeters,
        points,
        perimeter_keys,
        point_keys,
    )
    geometries = _fire_geometries(keys, full_perimeters, points, point_keys)
    record_metrics = _record_metrics(keys, metrics, first_mapping)
    buffered = buffered_fire_geometries(geometries)
    signals = external_signals(year_directory, len(keys), geometries, buffered)
    return _ScoringInput(
        keys=keys,
        names=[str(names[key]) for key in keys],
        identifiers=[normalized_identifier(identifiers.get(key)) for key in keys],
        metrics=record_metrics,
        geometries=geometries,
        buffered=buffered,
        signals=signals,
        points_by_key=typing.cast(
            "dict[str, geopandas.GeoDataFrame]",
            {str(key): group for key, group in points.groupby(point_keys)},
        ),
        empty_points=points.iloc[0:0],
        empty_perimeters=perimeters.iloc[0:0],
    )


def score_fires(year_directory: pathlib.Path) -> pathlib.Path:
    """Score every fire and write the results to the derived directory.

    The score is computed from the differential history and the retrieved external
    datasets; it never consults previously written scores, so deleting the scores file
    and regenerating it changes nothing. The fire metrics are aggregated in a single
    groupby pass, the fire geometry comes from the cumulative full history rather than
    re-unioned perimeters, and the external datasets are queried through their R-Tree
    indexes, so neither the history nor the external layers are ever processed one
    feature at a time. The results are written to
    ``{year_directory}/derived/fire_scores.json``, along with a complementary CDF to
    ``{year_directory}/derived/fire_scores_ccdf.png``.

    Args:
        year_directory: The year directory that holds the ``sources`` directory.

    Returns:
        The path of the written fire-scores JSON.
    """
    scoring = _scoring_input(year_directory)
    entries = [
        score_entry(
            fire_score_for(
                FireRecords(
                    name=scoring.names[index],
                    identifier=scoring.identifiers[index],
                    perimeters=scoring.empty_perimeters,
                    points=scoring.points_by_key.get(
                        scoring.keys[index],
                        scoring.empty_points,
                    ),
                ),
                scoring.metrics[index],
                building_count=scoring.signals.building_counts[index],
                evacuation_overlap=index in scoring.signals.evacuation_indices,
            ),
        )
        for index in range(len(scoring.keys))
    ]
    entries.sort(key=lambda entry: (-entry.score, entry.name))
    document = fire_scores_document(entries)
    output_path = fire_scores_path(year_directory)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    peri_scribe.output.write_fire_scores(output_path, document)
    ccdf_path = fire_scores_ccdf_path(year_directory)
    peri_scribe.output.write_fire_scores_ccdf(ccdf_path, document)
    return output_path
