"""Scoring fires to surface the ones people are most interested in.

Each fire's score is a weighted sum of points awarded across independent signals: its
reported size, its largest single growth step, its size when first mapped, the buildings
within a mile of it, whether it overlaps an evacuation zone, and its official incident
complexity level. The score is a pure function of the current data. It does not depend
on the contents of the scores file, so regenerating it from unchanged inputs produces
the same scores.

The score is derived from the differential history GeoPackage (for size, growth,
first-mapping size) and the cumulative full history (for geometry), plus the point
history (for the official complexity level), then joined spatially against the retrieved
external datasets: building centroids and evacuation zones. Building counts come from
the compact buildings database, whose tiles are selected by each fire's envelope and
whose payloads are filtered in NumPy; the evacuation GeoPackage is queried through its
R-Tree index. Either way, only the features near a fire are ever read.

The results are written to ``{year}/derived/fire_scores.json``, along with a
``{year}/derived/fire_scores_ccdf.png`` complementary CDF of the scores.
"""

from __future__ import annotations

import dataclasses
import pathlib
import typing

import geopandas
import pandas as pd

import peri_scribe.fires.buffering
import peri_scribe.fires.differential
import peri_scribe.fires.files
import peri_scribe.fires.identity
import peri_scribe.fires.overlaps
import peri_scribe.fires.score_files
import peri_scribe.fires.scoring
import peri_scribe.geo.parsing
import peri_scribe.geo.reading
import peri_scribe.output
import peri_scribe.sources.buildings
import peri_scribe.sources.external_sources


if typing.TYPE_CHECKING:
    import shapely


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
    return peri_scribe.geo.reading.read_layer(path, layer_name)


def latest_snapshot_layer(
    year_directory: pathlib.Path,
    source: peri_scribe.sources.external_sources.ExternalSource,
) -> tuple[pathlib.Path, str] | None:
    """Return the path and layer name of a live source's GeoPackage, or None.

    A live source keeps only its latest version, stored as a single GeoPackage named for
    the source, so the layer is read from that fixed path when it exists.

    Args:
        year_directory: The year directory that holds the ``sources`` directory.
        source: The live external source.

    Returns:
        The source's GeoPackage path and layer name, or None when the source has no
        layer or no GeoPackage.
    """
    if source.layer_name is None:
        return None
    path = peri_scribe.sources.external_sources.output_path(year_directory, source)
    if not path.is_file():
        return None
    return path, source.layer_name


def read_latest_snapshot(
    year_directory: pathlib.Path,
    source: peri_scribe.sources.external_sources.ExternalSource,
) -> geopandas.GeoDataFrame:
    """Read the latest version of a live external source.

    Args:
        year_directory: The year directory that holds the ``sources`` directory.
        source: The live external source.

    Returns:
        The source's latest features, or an empty GeoDataFrame when there are none.
    """
    layer = latest_snapshot_layer(year_directory, source)
    if layer is None:
        return geopandas.GeoDataFrame()
    path, layer_name = layer
    return peri_scribe.geo.reading.read_layer(path, layer_name)


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

    Each dataset is read only when its database is present, so a missing dataset
    contributes nothing. Building counts are queried through the compact buildings
    database's tiles, and the evacuation layer through its R-Tree index, so only the
    features near a fire are ever read. The returned counts and indices are aligned with
    the fires.

    Args:
        year_directory: The year directory that holds the ``sources`` directory.
        fire_count: The number of fires being scored.
        geometries: One geometry per fire, in WGS84, or None.
        buffered: One building-distance buffered geometry per fire, or None.

    Returns:
        The external signals for the fires.
    """
    buildings_path = peri_scribe.sources.external_sources.output_path(
        year_directory,
        peri_scribe.sources.external_sources.BUILDINGS_SOURCE,
    )
    if buildings_path.is_file():
        building_counts = peri_scribe.sources.buildings.building_counts_within(
            buffered,
            buildings_path,
        )
    else:
        building_counts = [0] * fire_count
    evacuations = latest_snapshot_layer(
        year_directory,
        peri_scribe.sources.external_sources.EVACUATIONS_SOURCE,
    )
    evacuation_indices = (
        peri_scribe.fires.overlaps.overlapping_fire_indices(
            geometries,
            evacuations[0],
            evacuations[1],
        )
        if evacuations is not None and evacuations[0].is_file()
        else set()
    )
    return ExternalSignals(
        building_counts=tuple(building_counts),
        evacuation_indices=frozenset(evacuation_indices),
    )


def fire_identity(
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
            .assign(key=perimeter_keys)
            .drop_duplicates("key")
            .set_index("key")
        )
        names = perimeter_first["fire_name"]
        identifiers = perimeter_first["fire_identifier"]
    if not points.empty:
        point_first = (
            points.assign(key=point_keys).drop_duplicates("key").set_index("key")
        )
        names = names.combine_first(point_first["fire_name"])
        identifiers = identifiers.combine_first(point_first["fire_identifier"])
    return names, identifiers


def perimeter_metrics_for(
    key: str,
    metrics: pd.DataFrame,
    first_mapping: pd.Series,
) -> peri_scribe.fires.scoring.PerimeterMetrics:
    """Return the perimeter metrics for a fire, or all-None when it has none.

    Args:
        key: The fire's identity key.
        metrics: The per-fire maximum area and growth, keyed by fire identity.
        first_mapping: The per-fire first-mapping area, keyed by fire identity.

    Returns:
        The fire's perimeter metrics.
    """
    if key not in metrics.index:
        return peri_scribe.fires.scoring.PerimeterMetrics(
            area_acres=None,
            growth_acres=None,
            first_mapping_acres=None,
            geometry=None,
        )
    row = metrics.loc[key]
    return peri_scribe.fires.scoring.PerimeterMetrics(
        area_acres=None if pd.isna(row.max_area) else row.max_area,
        growth_acres=None if pd.isna(row.max_growth) else row.max_growth,
        first_mapping_acres=peri_scribe.geo.parsing.numeric_value(
            first_mapping.get(key),
        ),
        geometry=None,
    )


def read_history(
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
    differential_path = peri_scribe.fires.differential.differential_geopackage_path(
        year_directory,
    )
    perimeters = read_layer_if_present(
        differential_path,
        peri_scribe.fires.files.PERIMETER_LAYER_NAME,
    )
    points = read_layer_if_present(
        differential_path,
        peri_scribe.fires.files.POINT_LAYER_NAME,
    )
    full_path = peri_scribe.fires.files.history_geopackage_path(year_directory)
    full_perimeters = read_layer_if_present(
        full_path,
        peri_scribe.fires.files.PERIMETER_LAYER_NAME,
    )
    return perimeters, points, full_perimeters


def fire_metrics(
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
    keyed = perimeters.assign(key=perimeter_keys)
    metrics = keyed.groupby("key", sort=False).agg(
        max_area=("area_acres", "max"),
        max_growth=("area_acres_differential", "max"),
    )
    first_mapping = (
        keyed
        .sort_values("observation_time")
        .groupby("key", sort=False)
        .head(1)
        .set_index("key")["area_acres"]
    )
    return metrics, first_mapping


def fire_geometries(
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
        full_keys = peri_scribe.fires.identity.group_keys(full_perimeters)
        last_full = (
            full_perimeters
            .assign(key=full_keys)
            .sort_values("observation_time")
            .groupby("key", sort=False)
            .geometry.last()
        )
    point_unions = {
        str(key): peri_scribe.fires.buffering.union_geometry(group.geometry)
        for key, group in points.groupby(point_keys)
    }
    geometries: list[shapely.Geometry | None] = []
    for key in keys:
        geometry = last_full.get(key)
        if geometry is None:
            geometry = point_unions.get(key)
        geometries.append(geometry)
    return geometries


def record_metrics(
    keys: list[str],
    metrics: pd.DataFrame,
    first_mapping: pd.Series,
) -> list[peri_scribe.fires.scoring.PerimeterMetrics]:
    """Return one perimeter-metrics record per fire.

    Args:
        keys: The fires' identity keys, in score order.
        metrics: The per-fire maximum area and growth, keyed by fire identity.
        first_mapping: The per-fire first-mapping area, keyed by fire identity.

    Returns:
        One perimeter metrics record per fire, aligned with *keys*.
    """
    return [perimeter_metrics_for(key, metrics, first_mapping) for key in keys]


@dataclasses.dataclass(frozen=True, kw_only=True)
class ScoringInput:
    """The per-fire inputs, precomputed and aligned in score order."""

    keys: list[str]
    names: list[str]
    identifiers: list[str | None]
    metrics: list[peri_scribe.fires.scoring.PerimeterMetrics]
    geometries: list[shapely.Geometry | None]
    buffered: list[shapely.Geometry | None]
    signals: ExternalSignals
    points_by_key: dict[str, geopandas.GeoDataFrame]
    empty_points: geopandas.GeoDataFrame
    empty_perimeters: geopandas.GeoDataFrame


def scoring_input(year_directory: pathlib.Path) -> ScoringInput:
    """Compute the per-fire inputs and external signals used to score fires.

    Args:
        year_directory: The year directory that holds the ``derived`` directory.

    Returns:
        The aligned per-fire inputs.
    """
    perimeters, points, full_perimeters = read_history(year_directory)
    perimeter_keys = peri_scribe.fires.identity.group_keys(perimeters)
    point_keys = peri_scribe.fires.identity.group_keys(points)
    keys = sorted(set(perimeter_keys) | set(point_keys))
    metrics, first_mapping = fire_metrics(perimeters, perimeter_keys)
    names, identifiers = fire_identity(
        perimeters,
        points,
        perimeter_keys,
        point_keys,
    )
    geometries = fire_geometries(keys, full_perimeters, points, point_keys)
    perimeter_records = record_metrics(keys, metrics, first_mapping)
    buffered = peri_scribe.fires.buffering.buffered_fire_geometries(geometries)
    signals = external_signals(year_directory, len(keys), geometries, buffered)
    return ScoringInput(
        keys=keys,
        names=[str(names[key]) for key in keys],
        identifiers=[
            peri_scribe.fires.identity.normalized_identifier(identifiers.get(key))
            for key in keys
        ],
        metrics=perimeter_records,
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
    datasets. It does not depend on the contents of the scores file, so regenerating it
    from unchanged inputs produces the same scores. The fire metrics are aggregated in a
    single groupby pass, the fire geometry comes from the cumulative full history;
    perimeter records are not re-unioned during scoring. The external datasets are
    queried through their R-Tree indexes, so neither the history nor the external layers
    are ever processed one feature at a time. The results are written to
    ``{year_directory}/derived/fire_scores.json``, along with a complementary CDF to
    ``{year_directory}/derived/fire_scores_ccdf.png``.

    Args:
        year_directory: The year directory that holds the ``sources`` directory.

    Returns:
        The path of the written fire-scores JSON.
    """
    scoring = scoring_input(year_directory)
    entries = [
        peri_scribe.fires.scoring.score_entry(
            peri_scribe.fires.scoring.fire_score_for(
                peri_scribe.fires.scoring.FireRecords(
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
    document = peri_scribe.fires.scoring.fire_scores_document(entries)
    output_path = peri_scribe.fires.score_files.fire_scores_path(year_directory)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    peri_scribe.output.write_fire_scores(output_path, document)
    ccdf_path = peri_scribe.fires.score_files.fire_scores_ccdf_path(year_directory)
    peri_scribe.output.write_fire_scores_ccdf(ccdf_path, document)
    return output_path
