"""Provide isolated fixtures for this test package."""

from __future__ import annotations

import typing

import pytest

import peri_scribe.fires.index
import peri_scribe.models
import peri_scribe.output
import peri_scribe.sources.feeds
import peri_scribe.sources.fetching
import peri_scribe.sources.snapshots
import tests.factories
import tests.peri_scribe.sources.fetching_helpers


if typing.TYPE_CHECKING:
    import pathlib

    import arcgis.features
    import geopandas


@pytest.fixture
def fetch_all_feeds_stubs(
    monkeypatch: pytest.MonkeyPatch,
) -> typing.Callable[
    [
        list[tests.peri_scribe.sources.fetching_helpers.FeedStub],
        typing.Callable[[str, object], object],
    ],
    None,
]:
    """Install feed, GIS, and FeatureLayer stubs for fetch-all-feeds tests.

    Args:
        monkeypatch: Replace dependencies and restore them after the test.

    Returns:
        A callable that installs the stubs for one test.
    """

    def install(
        feeds: list[tests.peri_scribe.sources.fetching_helpers.FeedStub],
        layer_factory: typing.Callable[[str, object], object],
    ) -> None:
        """Install feed and layer substitutes for an isolated collection run.

        Args:
            feeds: Feed configurations to include in the collection or validation.
            layer_factory: Construct a controlled layer for each feed URL and GIS
                connection.
        """
        monkeypatch.setattr(peri_scribe.sources.feeds, "FEEDS", feeds)
        monkeypatch.setattr(peri_scribe.sources.fetching.arcgis.gis, "GIS", object)
        monkeypatch.setattr(
            peri_scribe.sources.fetching.arcgis.features,
            "FeatureLayer",
            layer_factory,
        )
        monkeypatch.setattr(
            peri_scribe.fires.index,
            "index_fire_sources",
            lambda _year_directory: None,
        )

    return install


@pytest.fixture
def full_fetch(
    tmp_path: pathlib.Path,
) -> typing.Callable[
    [list[tuple[int, str, float, float]]],
    geopandas.GeoDataFrame | None,
]:
    """Exercise full-fetch behavior against isolated storage and an ArcGIS stand-in.

    Args:
        tmp_path: The temporary directory for the existing source snapshot.

    Returns:
        A fetch operation accepting the features currently returned by the source.
    """
    feed = tests.factories.change_feed(change_columns=())
    source_file = peri_scribe.sources.snapshots.SourceFile(
        serial_number=0,
        last_edit_timestamp=0,
    )
    source_path = tmp_path / source_file.relative_path
    source_path.parent.mkdir(parents=True)
    peri_scribe.output.write_geopackage(
        source_path,
        [
            peri_scribe.models.LayerData(
                name=feed.name,
                dataframe=tests.factories.change_dataframe([(1, "stored", (0.0, 0.0))]),
            ),
        ],
    )

    def fetch(
        rows: list[tuple[int, str, float, float]],
    ) -> geopandas.GeoDataFrame | None:
        """Exercise conversion and deduplication with controlled source data.

        Args:
            rows: Source object identifiers, names, longitudes, and latitudes.

        Returns:
            The new or changed features, or None when the snapshot is current.
        """
        layer = tests.factories.FeatureLayerStub(
            feed.url,
            object(),
            tests.factories.wgs84_feature_set([
                (identifier, name, longitude, latitude)
                for identifier, name, longitude, latitude in rows
            ]),
        )
        return peri_scribe.sources.fetching.fetch_feed_dataframe(
            feed,
            typing.cast("arcgis.features.FeatureLayer", layer),
            [source_file],
            tmp_path,
            full=True,
        )

    return fetch
