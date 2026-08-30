"""Tests for peri_scribe.sources.external_sources."""

from __future__ import annotations

import datetime
import hashlib
import pathlib

import geopandas
import pandas as pd
import shapely.geometry

import peri_scribe.models
import peri_scribe.output
import peri_scribe.sources.digests
import peri_scribe.sources.external_sources
import tests.peri_scribe.sources.external_source_helpers


def test_dataframe_digest_ignores_row_order() -> None:
    dataframe = (
        tests.peri_scribe.sources.external_source_helpers.sample_arcgis_dataframe()
    )
    reversed_dataframe = dataframe.iloc[::-1].reset_index(drop=True)
    digest = peri_scribe.sources.digests.dataframe_digest
    assert digest(dataframe) == digest(reversed_dataframe)


def test_dataframe_digest_differs_for_different_geometry() -> None:
    first = tests.peri_scribe.sources.external_source_helpers.sample_arcgis_dataframe()
    second = tests.peri_scribe.sources.external_source_helpers.sample_arcgis_dataframe()
    second.loc[0, "geometry"] = shapely.geometry.Point(9.0, 9.0)
    digest = peri_scribe.sources.digests.dataframe_digest
    assert digest(first) != digest(second)


def test_dataframe_digest_treats_missing_values_equally() -> None:
    def frame(missing: object) -> geopandas.GeoDataFrame:
        return geopandas.GeoDataFrame(
            {"value": pd.array([1, missing], dtype=object)},
            geometry=[
                shapely.geometry.Point(0.0, 0.0),
                shapely.geometry.Point(1.0, 1.0),
            ],
            crs="EPSG:4326",
        )

    digest = peri_scribe.sources.digests.dataframe_digest
    baseline = digest(frame(None))
    assert digest(frame(float("nan"))) == baseline
    assert digest(frame(pd.NA)) == baseline
    assert digest(frame(pd.NaT)) == baseline


def test_dataframe_digest_covers_every_attribute_kind() -> None:
    dataframe = geopandas.GeoDataFrame(
        {
            "a": ["x", "y"],
            "b": [True, False],
            "c": [1.5, 2.5],
            "d": [1, 2],
            "e": [
                datetime.datetime(2026, 1, 1),
                datetime.datetime(2026, 1, 2),
            ],
            "f": [b"\x01", b"\x02"],
            "g": [
                shapely.geometry.Point(5.0, 5.0),
                shapely.geometry.Point(6.0, 6.0),
            ],
            "h": [{"k": 1}, {"k": 2}],
        },
        geometry=[
            shapely.geometry.Point(0.0, 0.0),
            shapely.geometry.Point(1.0, 1.0),
        ],
        crs="EPSG:4326",
    )
    digest = peri_scribe.sources.digests.dataframe_digest(dataframe)
    assert isinstance(digest, str)
    assert len(digest) == len(hashlib.sha256(b"x").hexdigest())


def test_stored_geopackage_digest_returns_none_when_file_missing(
    tmp_path: pathlib.Path,
) -> None:
    digest = peri_scribe.sources.digests.stored_geopackage_digest(
        tmp_path / "missing.gpkg",
        "evacuations",
    )
    assert digest is None


def test_stored_geopackage_digest_returns_none_when_file_unreadable(
    tmp_path: pathlib.Path,
) -> None:
    path = tmp_path / "bad.gpkg"
    path.write_bytes(b"not a geopackage")
    digest = peri_scribe.sources.digests.stored_geopackage_digest(
        path,
        "evacuations",
    )
    assert digest is None


def test_stored_geopackage_digest_digests_file_contents(
    tmp_path: pathlib.Path,
) -> None:
    output = peri_scribe.sources.external_sources.output_path(
        tmp_path,
        peri_scribe.sources.external_sources.EVACUATIONS_SOURCE,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    peri_scribe.output.write_geopackage(
        output,
        [
            peri_scribe.models.LayerData(
                name="evacuations",
                dataframe=tests.peri_scribe.sources.external_source_helpers.sample_arcgis_dataframe(),
            ),
        ],
    )
    digest = peri_scribe.sources.digests.stored_geopackage_digest(
        output,
        "evacuations",
    )
    stored = geopandas.read_file(output, layer="evacuations")
    assert digest == peri_scribe.sources.digests.dataframe_digest(stored)
