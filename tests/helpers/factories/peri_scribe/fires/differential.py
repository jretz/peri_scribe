"""Build inputs for differential tests."""

import typing

import geopandas

import peri_scribe.fires.files
import tests.helpers.factories.geometry


if typing.TYPE_CHECKING:
    import shapely.geometry


def full_perimeter_frame(
    records: list[dict[str, typing.Any]],
    geometries: list[shapely.geometry.base.BaseGeometry],
) -> geopandas.GeoDataFrame:
    """Build a full-perimeter GeoDataFrame from attribute overrides.

    Args:
        records: One attribute override per row.
        geometries: The rows' geometries.

    Returns:
        The rows as a GeoDataFrame with every perimeter column present.
    """
    columns = [
        column
        for column in peri_scribe.fires.files.PERIMETER_COLUMNS
        if column != "geometry"
    ]
    rows = [{column: record.get(column) for column in columns} for record in records]
    return geopandas.GeoDataFrame(rows, geometry=geometries, crs="EPSG:4326")


def multiple_fire_perimeter_frame() -> tuple[geopandas.GeoDataFrame, list[str]]:
    """Return a full perimeter frame with several growing fires.

    Each fire's perimeters grow, so every perimeter adds a differential row and the
    output rows follow the frame's fire order one-for-one.

    Returns:
        The frame and each row's fire identifier in frame order.
    """
    fire_identifiers = [
        "2026-cacdd-000001",
        "2026-cacdd-000001",
        "2026-cacdd-000002",
        "2026-cacdd-000002",
        "2026-cacdd-000002",
        "2026-cacdd-000003",
    ]
    sides = [1.0, 2.0, 1.0, 2.0, 3.0, 2.0]
    records = [
        {
            "fire_name": "Bug",
            "fire_identifier": fire_identifier,
            "area_acres": 100.0 * side,
        }
        for fire_identifier, side in zip(fire_identifiers, sides, strict=True)
    ]
    return (
        full_perimeter_frame(
            records,
            [tests.helpers.factories.geometry.square(side) for side in sides],
        ),
        fire_identifiers,
    )
