"""Build isolated geography and prepared facts for map-input cache checks."""

from __future__ import annotations

import dataclasses
import datetime
import hashlib
import typing

import shapely

import peri_scribe.areas
import peri_scribe.fires.derived_layers
import peri_scribe.kml.prepared_inputs
import peri_scribe.models
import spatial_data.layers
import tests.helpers.factories.geography
import tests.helpers.factories.peri_scribe.kml.parsing
from measurement_units import units


if typing.TYPE_CHECKING:
    import pathlib


@dataclasses.dataclass(frozen=True, kw_only=True)
class Geography:
    """Own independently writable test files and the source evidence they contain."""

    year_directory: pathlib.Path
    full_path: pathlib.Path
    differential_path: pathlib.Path
    index: peri_scribe.models.FireIndex
    layers: peri_scribe.fires.derived_layers.DerivedLayers
    histories: peri_scribe.kml.prepared_inputs.Histories
    identity: tuple[str, str]


def history(area: float | None) -> peri_scribe.areas.PreparedHistory:
    """Keep sparse reporting facts independent of geometry truth in adapter tests.

    Args:
        area: Sparse selected acreage, or absent evidence.

    Returns:
        Complete prepared facts with equal latest and historical acreage.
    """
    value = None if area is None else area * units.acres
    return peri_scribe.areas.PreparedHistory(
        updates=(),
        estimates=(),
        latest_area=value,
        historical_area=value,
    )


def geography(
    directory: pathlib.Path,
    *,
    attributes: tuple[object, ...] | None = (
        '{"old": 1}',
        '{"other": 2}',
        '{"new": 3}',
    ),
) -> Geography:
    """Write real GeoPackage layers without coupling tests to runtime code hashes.

    Args:
        directory: Per-test private parent directory.
        attributes: Stored attribute values, or None to omit the column.

    Returns:
        Original layers, immutable file checksums, and independent prepared facts.
    """
    year_directory = directory / "2026"
    full = year_directory / "derived" / "history_of_full_geography.gpkg"
    differential = year_directory / "derived" / "history_of_differential_geography.gpkg"
    full.parent.mkdir(parents=True)
    values: dict[str, object] = {
        "fire_identifier": ["id-a", "id-b", "id-a"],
        "fire_name": ["Alpha", "Bravo", "Alpha"],
        "observation_time": [
            datetime.datetime(2026, 9, day, tzinfo=datetime.UTC) for day in (1, 1, 2)
        ],
        "area_acres": [25.0, 1.0, 30.0],
    }
    if attributes is not None:
        values["source_attributes"] = list(attributes)
    perimeters = tests.helpers.factories.geography.geo_frame(
        values,
        [shapely.box(index, 0, index + 1, 1) for index in range(3)],
    )
    points = perimeters.copy()
    points.geometry = [shapely.Point(index, index) for index in range(3)]
    incidents = points.iloc[0:0]
    layers = peri_scribe.fires.derived_layers.DerivedLayers(
        perimeters=perimeters,
        points=points,
        differential_perimeters=perimeters.copy(),
        incidents=incidents,
    )
    spatial_data.layers.write_geopackage(
        full,
        [
            spatial_data.layers.LayerData(
                name="perimeter_history",
                dataframe=perimeters,
            ),
            spatial_data.layers.LayerData(name="point_history", dataframe=points),
            spatial_data.layers.LayerData(name="incident_history", dataframe=incidents),
        ],
    )
    spatial_data.layers.write_geopackage(
        differential,
        [
            spatial_data.layers.LayerData(
                name="perimeter_history",
                dataframe=perimeters,
            ),
            spatial_data.layers.LayerData(name="point_history", dataframe=points),
        ],
    )
    checksums = []
    for path in (full, differential):
        with path.open("rb") as stream:
            checksums.append(hashlib.file_digest(stream, "sha256").hexdigest())
    index = tests.helpers.factories.peri_scribe.kml.parsing.fire_index([
        tests.helpers.factories.peri_scribe.kml.parsing.fire_index_entry(
            name,
            "active",
            identifier=identifier,
        )
        for name, identifier in (("Alpha", "id-a"), ("Bravo", "id-b"))
    ])
    return Geography(
        year_directory=year_directory,
        full_path=full,
        differential_path=differential,
        index=index,
        layers=layers,
        histories={("id", "id-a"): history(30), ("id", "id-b"): history(1)},
        identity=(checksums[0], checksums[1]),
    )
