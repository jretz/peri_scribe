"""Build inputs for scores tests."""

from __future__ import annotations

import dataclasses
import datetime
import pathlib
import typing

import peri_scribe.models
import peri_scribe.sources.snapshots
import tests.helpers.factories.geography
import tests.helpers.factories.geometry


if typing.TYPE_CHECKING:
    import geopandas
    import shapely.geometry

if typing.TYPE_CHECKING:
    import geopandas


def write_fire_index(
    year_directory: pathlib.Path,
    index: peri_scribe.models.FireIndex,
) -> None:
    """Let scoring consume existing aliases without consulting source feeds.

    Args:
        year_directory: The isolated test directory containing derived inputs.
        index: The indexed aliases available to the scoring stage.
    """
    path = peri_scribe.sources.snapshots.fire_index_path(year_directory)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(index.model_dump_json())


def reported_frame(
    rows: list[tuple[str | None, str, float]],
) -> geopandas.GeoDataFrame:
    """Keep identity and acreage scenarios independent of spatial scoring inputs.

    Args:
        rows: Identifier, name, and reported acreage in chronological row order.

    Returns:
        Point observations with distinct times and their reported acreages.
    """
    beginning = datetime.datetime(2026, 9, 1, tzinfo=datetime.UTC)
    return tests.helpers.factories.geography.geo_frame(
        {
            "fire_identifier": [identifier for identifier, _name, _area in rows],
            "fire_name": [name for _identifier, name, _area in rows],
            "incident_size": [area for _identifier, _name, area in rows],
            "observation_time": [
                beginning + datetime.timedelta(hours=position)
                for position in range(len(rows))
            ],
        },
        [tests.helpers.factories.geometry.point(0, 0) for _row in rows],
    )


def perimeter_frame(
    records: list[dict[str, object]],
    geometries: list[shapely.geometry.base.BaseGeometry],
) -> geopandas.GeoDataFrame:
    """Build a perimeter-history GeoDataFrame from attribute overrides.

    Args:
        records: One attribute override per row.
        geometries: The rows' geometries.

    Returns:
        The rows as a GeoDataFrame with the perimeter columns scoring reads.
    """
    columns = [
        "fire_name",
        "fire_identifier",
        "area_acres",
        "area_acres_differential",
        "observation_time",
    ]
    return tests.helpers.factories.geography.geo_frame(
        {column: [record.get(column) for record in records] for column in columns},
        list(geometries),
    )


def point_frame(
    records: list[dict[str, object]],
    geometries: list[shapely.geometry.base.BaseGeometry],
) -> geopandas.GeoDataFrame:
    """Build a point-history GeoDataFrame from attribute overrides.

    Args:
        records: One attribute override per row.
        geometries: The rows' geometries.

    Returns:
        The rows as a GeoDataFrame with the point columns scoring reads.
    """
    columns = ["fire_name", "fire_identifier", "source_attributes"]
    return tests.helpers.factories.geography.geo_frame(
        {column: [record.get(column) for record in records] for column in columns},
        list(geometries),
    )


@dataclasses.dataclass(frozen=True, kw_only=True)
class ScoreObservation:
    """Retain independent source measurements for per-fire aggregation checks.

    Args:
        key: The fire identifier shared by its observations.
        hour: The observation's offset from the reference date, or None when undated.
        reported_area: The reported acreage, or None when missing.
        reported_growth: The reported growth in acres, or None when missing.
        calculated_area: The geometry acreage, or None when missing.
        calculated_growth: The geometry growth in acres, or None when missing.
    """

    key: str
    hour: int | None
    reported_area: float | None
    reported_growth: float | None
    calculated_area: float | None
    calculated_growth: float | None


def metric_frame(
    observations: list[ScoreObservation],
    *,
    use_geometry: bool,
) -> geopandas.GeoDataFrame:
    """Build history with repeated index labels and optional geometry measurements.

    Args:
        observations: Measurements to aggregate in their input order.
        use_geometry: Whether the history includes persisted geometry measurements.

    Returns:
        A perimeter history frame whose row labels cannot be treated as row positions.
    """
    base = datetime.datetime(2026, 8, 1, tzinfo=datetime.UTC)
    frame = tests.helpers.factories.geography.geo_frame(
        {
            "fire_name": [item.key for item in observations],
            "fire_identifier": [item.key for item in observations],
            "observation_time": [
                None
                if item.hour is None
                else base + datetime.timedelta(hours=item.hour)
                for item in observations
            ],
            "area_acres": [item.reported_area for item in observations],
            "area_acres_differential": [item.reported_growth for item in observations],
            "area_acres_from_geometry": [item.calculated_area for item in observations],
            "area_acres_from_geometry_differential": [
                item.calculated_growth for item in observations
            ],
        },
        [None] * len(observations),
    )
    frame.index = [index % 3 - 1 for index in range(len(observations))]
    if not use_geometry:
        frame.drop(
            columns=[
                "area_acres_from_geometry",
                "area_acres_from_geometry_differential",
            ],
            inplace=True,
        )
    return frame
