"""Isolate reuse tests with explicit fixtures."""

from __future__ import annotations

import pathlib

import geopandas
import pytest
import shapely
import shapely.geometry

import peri_scribe.fires.sources
import peri_scribe.geo.package
import peri_scribe.sources.feed_types
import spatial_data.layers
import tests.helpers.factories.geography
import tests.helpers.factories.peri_scribe.models


@pytest.fixture
def cached_layers() -> list[spatial_data.layers.LayerData]:
    """Supply an isolated cache payload.

    Returns:
        Small independent histories with stable derivation keys.
    """
    return [
        spatial_data.layers.LayerData(
            name="perimeters",
            dataframe=geopandas.GeoDataFrame(
                {"derivation_key": ["first", "second"], "revision": [1, 2]},
                geometry=[shapely.box(0, 0, 1, 1), shapely.box(2, 2, 3, 3)],
                crs=4326,
            ),
        ),
    ]


@pytest.fixture
def source_rows() -> peri_scribe.fires.sources.ReadFireSources:
    """Supply observations whose dependencies can change independently.

    Returns:
        Repeated shapes and a missing geometry under one fire identity.
    """
    geometry = shapely.box(0, 0, 1, 1)
    return peri_scribe.fires.sources.ReadFireSources(
        rows=tuple(
            peri_scribe.geo.package.FireRowRecord(
                record=tests.helpers.factories.peri_scribe.models.fire_record(
                    "Example",
                    tests.helpers.factories.peri_scribe.models.ACTIVE,
                    {"example"},
                    geometry=shape,
                ),
                source_name="CA_Perimeters_NIFC_FIRIS_public_view_0",
                object_id=1,
                attributes={"revision": index},
            )
            for index, shape in enumerate([geometry, geometry, None])
        ),
        paths=tuple(
            pathlib.Path(f"sources/feed/00000{index},lastEdit=1.gpkg")
            for index in range(3)
        ),
        memberships=(),
    )


@pytest.fixture
def repeated_geometry_sources(
    tmp_path: pathlib.Path,
    configured_feeds: list[peri_scribe.sources.feed_types.Feed],
) -> pathlib.Path:
    """Provide separate observations retaining the same fire footprint.

    Args:
        tmp_path: Isolated directory for this test's files.
        configured_feeds: Feeds with controlled name and status columns.

    Returns:
        The isolated source directory containing both observations.
    """
    directory = tmp_path / "sources"
    feed = configured_feeds[0]
    for serial, name in enumerate(["First", "Second"]):
        path = directory / feed.name / "000___" / f"{serial:06d},lastEdit=0.gpkg"
        path.parent.mkdir(parents=True, exist_ok=True)
        frame = tests.helpers.factories.geography.geo_frame(
            {
                "incident_name": [name],
                "displayStatus": ["Active"],
                "revision": [serial],
            },
            [shapely.geometry.Point(1, 2)],
        )
        frame.to_file(path, layer=feed.name)
    return directory
