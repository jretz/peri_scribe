"""Scoring fires to surface the ones people are most interested in.

Each fire's score is a sum of points awarded across independent signals: its reported
size, its largest single growth step, its size when first mapped, the buildings within
a mile of it, whether it overlaps an evacuation zone, a red-flag warning, or the
wildland-urban interface, and its official incident complexity level. A fire keeps the
highest score it has ever reached, so a fire that was once interesting stays
interesting for the rest of the season.

The score is derived from the differential history GeoPackage (for size, growth,
first-mapping size, and geometry) and the point history (for the official complexity
level), then joined spatially against the retrieved external datasets: building
centroids, evacuation zones, red-flag warnings, and the wildland-urban interface.

The results are written to ``{year}/derived/fire_scores.json``.
"""

from __future__ import annotations

import dataclasses
import json
import pathlib
import typing

import geopandas
import pandas as pd
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

FIRE_SCORES_VERSION = "2026-08-27"

# The buffer around a fire's footprint used to count threatened buildings.
BUILDING_BUFFER_IN_METERS = 1609.34

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
RED_FLAG_WARNING_POINTS = 2
WUI_POINTS = 2

# Official importance points by incident complexity level.
IMPORTANCE_POINTS_BY_LEVEL = {
    "Type 1 Incident": 3,
    "Type 2 Incident": 2,
    "Type 3 Incident": 1,
}


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


def maximum_value(values: typing.Iterable[object]) -> float | None:
    """Return the largest numeric value among *values*, or None when none.

    Args:
        values: The values to consider.

    Returns:
        The largest numeric value, or None when every value is missing or non-numeric.
    """
    numeric = [
        value
        for value in (peri_scribe.geo_package.numeric_value(item) for item in values)
        if value is not None
    ]
    return max(numeric) if numeric else None


def first_mapping_acres(perimeters: geopandas.GeoDataFrame) -> float | None:
    """Return the fire's reported size at its first mapping.

    The first mapping is the earliest perimeter observation; when no perimeter carries
    an observation time, the first row is used as the earliest.

    Args:
        perimeters: The fire's differential perimeter rows, in chronological order.

    Returns:
        The reported area in acres of the earliest perimeter, or None when unknown.
    """
    with_times = perimeters.dropna(subset=["observation_time"])
    if with_times.empty:
        return peri_scribe.geo_package.numeric_value(
            perimeters.iloc[0]["area_acres"],
        )
    earliest = with_times.sort_values("observation_time").iloc[0]
    return peri_scribe.geo_package.numeric_value(earliest["area_acres"])


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


def perimeter_metrics(perimeters: geopandas.GeoDataFrame) -> PerimeterMetrics:
    """Return the size and growth measurements for a fire's perimeters.

    Args:
        perimeters: The fire's differential perimeter rows.

    Returns:
        The fire's largest reported size, largest growth step, first-mapping size, and
        the union of its perimeters.
    """
    if perimeters.empty:
        return PerimeterMetrics(
            area_acres=None,
            growth_acres=None,
            first_mapping_acres=None,
            geometry=None,
        )
    return PerimeterMetrics(
        area_acres=maximum_value(perimeters["area_acres"]),
        growth_acres=maximum_value(perimeters["area_acres_differential"]),
        first_mapping_acres=first_mapping_acres(perimeters),
        geometry=union_geometry(perimeters.geometry),
    )


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


def intersects_any(
    geometry: shapely.Geometry | None,
    candidates: geopandas.GeoSeries,
) -> bool:
    """Return whether *geometry* intersects any candidate geometry.

    Args:
        geometry: The geometry to test, or None.
        candidates: The candidate geometries, in the same spatial reference.

    Returns:
        True when *geometry* intersects at least one candidate.
    """
    if geometry is None or geometry.is_empty:
        return False
    return bool(candidates.intersects(geometry).any())


def count_within(
    geometry: shapely.Geometry | None,
    points: geopandas.GeoSeries,
) -> int:
    """Return how many of *points* lie within *geometry*.

    Args:
        geometry: The geometry to test, or None.
        points: The point geometries, in the same spatial reference.

    Returns:
        The number of points within *geometry*.
    """
    if geometry is None or geometry.is_empty:
        return 0
    return int(points.within(geometry).sum())


def reproject_geometry(
    geometry: shapely.Geometry,
    source_crs: pyproj.CRS,
    target_crs: pyproj.CRS,
) -> shapely.Geometry:
    """Return *geometry* transformed from *source_crs* to *target_crs*.

    Args:
        geometry: The geometry to transform.
        source_crs: The geometry's current spatial reference.
        target_crs: The spatial reference to transform into.

    Returns:
        The geometry in *target_crs*.
    """
    if source_crs.equals(target_crs):
        return geometry
    return geopandas.GeoSeries([geometry], crs=source_crs).to_crs(target_crs).iloc[0]


def buffered_wgs84_geometry(
    geometry: shapely.Geometry,
    distance_in_meters: float,
) -> shapely.Geometry:
    """Return *geometry* (WGS84) buffered by *distance_in_meters* in WGS84.

    Args:
        geometry: The geometry to buffer, in WGS84.
        distance_in_meters: The buffer distance, in meters.

    Returns:
        The buffered geometry, in WGS84.
    """
    metric = reproject_geometry(
        geometry,
        WGS84_SPATIAL_REFERENCE,
        WEB_MERCATOR_SPATIAL_REFERENCE,
    )
    buffered = metric.buffer(distance_in_meters)
    return reproject_geometry(
        buffered,
        WEB_MERCATOR_SPATIAL_REFERENCE,
        WGS84_SPATIAL_REFERENCE,
    )


def overlap_points(
    geometry: shapely.Geometry | None,
    candidates: geopandas.GeoDataFrame,
    points: int,
) -> int:
    """Return *points* when *geometry* overlaps any candidate, else 0.

    The candidate geometries may use any spatial reference; *geometry* is in WGS84 and
    is transformed to match the candidates when needed.

    Args:
        geometry: The fire's geometry, in WGS84, or None.
        candidates: The threat or hazard polygons.
        points: The points to award when the fire overlaps the candidates.

    Returns:
        The awarded points.
    """
    if geometry is None or geometry.is_empty:
        return 0
    target = geometry
    if candidates.crs is not None and not candidates.crs.equals(
        WGS84_SPATIAL_REFERENCE,
    ):
        target = reproject_geometry(geometry, WGS84_SPATIAL_REFERENCE, candidates.crs)
    if intersects_any(target, candidates.geometry):
        return points
    return 0


def building_points(
    geometry: shapely.Geometry | None,
    buildings: geopandas.GeoSeries,
) -> int:
    """Return the building-count points for a fire geometry.

    Args:
        geometry: The fire's geometry, in WGS84, or None.
        buildings: The building centroid points, in WGS84.

    Returns:
        The points for the number of buildings within a mile of the fire.
    """
    if geometry is None or geometry.is_empty:
        return 0
    buffered = buffered_wgs84_geometry(geometry, BUILDING_BUFFER_IN_METERS)
    return tiered_points(
        count_within(buffered, buildings),
        BUILDING_COUNT_TIERS,
    )


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


def row_identity(row: pd.Series) -> tuple[str, str | None]:
    """Return a history row's fire name and identifier.

    Args:
        row: One history row.

    Returns:
        The fire's name and canonical identifier, where the identifier is None when the
        row has none.
    """
    name = str(row["fire_name"])
    return name, normalized_identifier(row.get("fire_identifier"))


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


def fire_name_and_identifier(
    perimeters: geopandas.GeoDataFrame,
    points: geopandas.GeoDataFrame,
) -> tuple[str, str | None]:
    """Return a fire's name and identifier from its history rows.

    Args:
        perimeters: The fire's perimeter rows.
        points: The fire's point rows.

    Returns:
        The fire's name and identifier, from the perimeters when present and otherwise
        from the points.
    """
    if not perimeters.empty:
        return row_identity(perimeters.iloc[0])
    return row_identity(points.iloc[0])


@dataclasses.dataclass(frozen=True, kw_only=True)
class FireRecords:
    """A fire's identity and the history rows that describe it."""

    name: str
    identifier: str | None
    perimeters: geopandas.GeoDataFrame
    points: geopandas.GeoDataFrame


def fire_records(
    perimeters: geopandas.GeoDataFrame,
    points: geopandas.GeoDataFrame,
) -> list[FireRecords]:
    """Group the history layers into one record set per fire.

    Args:
        perimeters: The perimeter history layer.
        points: The point history layer.

    Returns:
        One record set per fire, sorted by identity key.
    """
    perimeter_groups = typing.cast(
        "dict[str, geopandas.GeoDataFrame]",
        {str(key): group for key, group in perimeters.groupby(group_keys(perimeters))},
    )
    point_groups = typing.cast(
        "dict[str, geopandas.GeoDataFrame]",
        {str(key): group for key, group in points.groupby(group_keys(points))},
    )
    records: list[FireRecords] = []
    for key in sorted(set(perimeter_groups) | set(point_groups)):
        fire_perimeters = perimeter_groups.get(key, perimeters.iloc[0:0])
        fire_points = point_groups.get(key, points.iloc[0:0])
        name, identifier = fire_name_and_identifier(fire_perimeters, fire_points)
        records.append(
            FireRecords(
                name=name,
                identifier=identifier,
                perimeters=fire_perimeters,
                points=fire_points,
            ),
        )
    return records


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
    red_flag_warning_points: int
    wui_points: int
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
            + self.red_flag_warning_points
            + self.wui_points
            + self.importance_points
        )


@dataclasses.dataclass(frozen=True, kw_only=True)
class ExternalContext:
    """The retrieved external datasets used for spatial scoring signals."""

    buildings: geopandas.GeoDataFrame
    evacuations: geopandas.GeoDataFrame
    red_flag_warnings: geopandas.GeoDataFrame
    wui: geopandas.GeoDataFrame


def score_for_fire(
    perimeters: geopandas.GeoDataFrame,
    points: geopandas.GeoDataFrame,
    external: ExternalContext,
) -> FireScore:
    """Return the current score for one fire.

    Args:
        perimeters: The fire's perimeter rows.
        points: The fire's point rows.
        external: The retrieved external datasets.

    Returns:
        The fire's score.
    """
    name, identifier = fire_name_and_identifier(perimeters, points)
    metrics = perimeter_metrics(perimeters)
    geometry = metrics.geometry
    if geometry is None and not points.empty:
        geometry = union_geometry(points.geometry)
    return FireScore(
        name=name,
        identifier=identifier,
        size_points=tiered_points(metrics.area_acres, SIZE_TIERS),
        growth_points=tiered_points(metrics.growth_acres, GROWTH_TIERS),
        first_mapping_points=tiered_points(
            metrics.first_mapping_acres,
            FIRST_MAPPING_TIERS,
        ),
        building_points=building_points(geometry, external.buildings.geometry),
        evacuation_points=overlap_points(
            geometry,
            external.evacuations,
            EVACUATION_POINTS,
        ),
        red_flag_warning_points=overlap_points(
            geometry,
            external.red_flag_warnings,
            RED_FLAG_WARNING_POINTS,
        ),
        wui_points=overlap_points(geometry, external.wui, WUI_POINTS),
        importance_points=fire_importance_points(points),
    )


def current_fire_scores(
    perimeters: geopandas.GeoDataFrame,
    points: geopandas.GeoDataFrame,
    external: ExternalContext,
) -> list[FireScore]:
    """Return the current score for every fire in the history layers.

    Args:
        perimeters: The perimeter history layer.
        points: The point history layer.
        external: The retrieved external datasets.

    Returns:
        One score per fire.
    """
    return [
        score_for_fire(records.perimeters, records.points, external)
        for records in fire_records(perimeters, points)
    ]


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


def best_score(previous_score: int | None, current_score: int) -> int:
    """Return the highest score a fire has ever reached.

    Args:
        previous_score: The fire's previously recorded best score, or None.
        current_score: The fire's current total score.

    Returns:
        The higher of the two.
    """
    return (
        current_score
        if previous_score is None
        else max(
            previous_score,
            current_score,
        )
    )


def score_entry(
    fire_score: FireScore,
    previous_score: int | None,
) -> peri_scribe.models.FireScoreEntry:
    """Return the persisted score entry for a fire.

    Args:
        fire_score: The fire's current score.
        previous_score: The fire's previously recorded best score, or None.

    Returns:
        The entry holding the fire's best-ever score and current components.
    """
    return peri_scribe.models.FireScoreEntry(
        name=fire_score.name,
        identifier=fire_score.identifier,
        score=best_score(previous_score, fire_score.total),
        components=peri_scribe.models.FireScoreComponents(
            size=fire_score.size_points,
            growth=fire_score.growth_points,
            first_mapping=fire_score.first_mapping_points,
            buildings=fire_score.building_points,
            evacuation=fire_score.evacuation_points,
            red_flag_warning=fire_score.red_flag_warning_points,
            wui=fire_score.wui_points,
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


def previous_scores(year_directory: pathlib.Path) -> dict[str, int]:
    """Return each fire's previously recorded best score.

    Args:
        year_directory: The year directory that holds the fire-scores file.

    Returns:
        The best score keyed by each fire's identity key, or an empty mapping when no
        scores have been written yet.
    """
    path = fire_scores_path(year_directory)
    if not path.is_file():
        return {}
    document = peri_scribe.models.FireScores.model_validate_json(
        path.read_text(encoding="utf-8"),
    )
    return {
        identity_key(entry.name, entry.identifier): entry.score
        for entry in document.fires
    }


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


def read_download_source(
    year_directory: pathlib.Path,
    source: peri_scribe.external_sources.ExternalSource,
) -> geopandas.GeoDataFrame:
    """Read a downloaded external source's GeoPackage.

    Args:
        year_directory: The year directory that holds the ``sources`` directory.
        source: The download-kind external source.

    Returns:
        The source's features, or an empty GeoDataFrame when it is not available.
    """
    if source.layer_name is None:
        return geopandas.GeoDataFrame()
    return read_layer_if_present(
        peri_scribe.external_sources.output_path(year_directory, source),
        source.layer_name,
    )


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
    if source.layer_name is None:
        return geopandas.GeoDataFrame()
    directory = peri_scribe.external_sources.source_directory_path(
        year_directory,
        source,
    )
    path = latest_snapshot_path(directory)
    if path is None:
        return geopandas.GeoDataFrame()
    return peri_scribe.geo_package.read_layer(path, source.layer_name)


def score_fires(year_directory: pathlib.Path) -> pathlib.Path:
    """Score every fire and write the results to the derived directory.

    The current score is computed from the differential history and the retrieved
    external datasets, then each fire keeps the highest score it has ever reached
    across runs. The results are written to
    ``{year_directory}/derived/fire_scores.json``.

    Args:
        year_directory: The year directory that holds the ``sources`` directory.

    Returns:
        The path of the written fire-scores JSON.
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
    buildings = read_download_source(
        year_directory,
        peri_scribe.external_sources.BUILDINGS_SOURCE,
    )
    evacuations = read_latest_snapshot(
        year_directory,
        peri_scribe.external_sources.EVACUATIONS_SOURCE,
    )
    red_flag_warnings = read_latest_snapshot(
        year_directory,
        peri_scribe.external_sources.RED_FLAG_WARNINGS_SOURCE,
    )
    wui = read_download_source(
        year_directory,
        peri_scribe.external_sources.WUI_SOURCE,
    )
    external = ExternalContext(
        buildings=buildings,
        evacuations=evacuations,
        red_flag_warnings=red_flag_warnings,
        wui=wui,
    )
    current = current_fire_scores(perimeters, points, external)
    previous = previous_scores(year_directory)
    entries = [
        score_entry(
            fire_score,
            previous.get(identity_key(fire_score.name, fire_score.identifier)),
        )
        for fire_score in current
    ]
    entries.sort(key=lambda entry: (-entry.score, entry.name))
    document = fire_scores_document(entries)
    output_path = fire_scores_path(year_directory)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    peri_scribe.output.write_fire_scores(output_path, document)
    return output_path
