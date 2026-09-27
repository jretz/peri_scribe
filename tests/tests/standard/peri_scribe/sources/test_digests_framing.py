"""Source-change identity retains field boundaries and schema meaning."""

import geopandas
import pyproj
import shapely

import peri_scribe.sources.digests
import tests.helpers.factories.geography


def test_dataframe_digest_distinguishes_attribute_boundaries() -> None:
    first = tests.helpers.factories.geography.geo_frame(
        {"first": ["a"], "second": ["sb"]},
        [shapely.Point(0, 0)],
    )
    second = first.copy()
    second.loc[0, "first"] = "as"
    second.loc[0, "second"] = "b"
    assert peri_scribe.sources.digests.dataframe_digest(first) != (
        peri_scribe.sources.digests.dataframe_digest(second)
    )


def test_dataframe_digest_distinguishes_column_names() -> None:
    first = tests.helpers.factories.geography.geo_frame(
        {"first": ["a"], "second": ["b"]},
        [shapely.Point(0, 0)],
    )
    second = geopandas.GeoDataFrame(first.rename(columns={"first": "other"}))
    assert peri_scribe.sources.digests.dataframe_digest(first) != (
        peri_scribe.sources.digests.dataframe_digest(second)
    )


def test_dataframe_digest_distinguishes_empty_schemas() -> None:
    first = geopandas.GeoDataFrame({"status": []}, geometry=[])
    second = geopandas.GeoDataFrame({"name": []}, geometry=[])
    assert peri_scribe.sources.digests.dataframe_digest(first) != (
        peri_scribe.sources.digests.dataframe_digest(second)
    )


def test_dataframe_digest_distinguishes_coordinate_references() -> None:
    first = geopandas.GeoDataFrame(geometry=[shapely.Point(0, 0)], crs="EPSG:4326")
    second = geopandas.GeoDataFrame(geometry=[shapely.Point(0, 0)], crs="EPSG:3857")
    assert peri_scribe.sources.digests.dataframe_digest(first) != (
        peri_scribe.sources.digests.dataframe_digest(second)
    )


def test_dataframe_digest_preserves_custom_reference_meaning() -> None:
    reference = pyproj.CRS.from_proj4("+proj=longlat +a=7000000 +b=7000000 +no_defs")
    assert reference.to_authority() is None
    first = geopandas.GeoDataFrame(geometry=[shapely.Point(0, 0)], crs=reference)
    same = geopandas.GeoDataFrame(
        geometry=[shapely.Point(0, 0)],
        crs=reference.to_wkt(),
    )
    different = geopandas.GeoDataFrame(geometry=[shapely.Point(0, 0)], crs="EPSG:4326")
    assert peri_scribe.sources.digests.dataframe_digest(first) == (
        peri_scribe.sources.digests.dataframe_digest(same)
    )
    assert peri_scribe.sources.digests.dataframe_digest(first) != (
        peri_scribe.sources.digests.dataframe_digest(different)
    )
