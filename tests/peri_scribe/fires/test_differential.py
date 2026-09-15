"""Tests for peri_scribe.fires.differential."""

import pathlib

import geopandas
import pandas as pd
import pytest
import shapely.geometry

import peri_scribe.fires.differential
import peri_scribe.fires.files
import peri_scribe.fires.reuse
import peri_scribe.geo.reading
import peri_scribe.models
import tests.factories
import tests.peri_scribe.fires.differential_helpers


def test_differential_geopackage_path_names_output() -> None:
    assert peri_scribe.fires.differential.differential_geopackage_path(
        pathlib.Path("data/2026"),
    ) == pathlib.Path("data/2026/derived/history_of_differential_geography.gpkg")


def test_polygonal_area_keeps_polygon() -> None:
    geometry = tests.factories.square(1.0)
    assert peri_scribe.fires.differential.polygonal_area(geometry) is geometry


def test_polygonal_area_returns_none_for_missing() -> None:
    assert peri_scribe.fires.differential.polygonal_area(None) is None


def test_polygonal_area_returns_none_for_non_polygonal() -> None:
    line = shapely.geometry.LineString([(0, 0), (1, 1)])
    assert peri_scribe.fires.differential.polygonal_area(line) is None


def test_polygonal_area_extracts_polygons_from_geometry_collection() -> None:
    collection = shapely.geometry.GeometryCollection([
        tests.factories.square(1.0),
        shapely.geometry.LineString([(0, 0), (1, 1)]),
    ])
    result = peri_scribe.fires.differential.polygonal_area(collection)
    assert result is not None
    assert result.equals(tests.factories.square(1.0))


def test_polygonal_area_returns_none_for_line_only_collection() -> None:
    collection = shapely.geometry.GeometryCollection([
        shapely.geometry.LineString([(0, 0), (1, 1)]),
    ])
    assert peri_scribe.fires.differential.polygonal_area(collection) is None


def test_polygonal_area_unions_multiple_polygons() -> None:
    collection = shapely.geometry.GeometryCollection([
        tests.factories.square(1.0),
        shapely.geometry.box(2.0, 2.0, 3.0, 3.0),
    ])
    result = peri_scribe.fires.differential.polygonal_area(collection)
    assert result is not None
    assert result.geom_type == "MultiPolygon"


def test_geometry_difference_returns_current_without_previous() -> None:
    geometry = tests.factories.square(1.0)
    result = peri_scribe.fires.differential.geometry_difference(geometry, None)
    assert result is not None
    assert result.equals(geometry)


def test_geometry_difference_returns_none_for_missing_current() -> None:
    assert (
        peri_scribe.fires.differential.geometry_difference(
            None,
            tests.factories.square(1.0),
        )
        is None
    )


def test_geometry_difference_subtracts_overlap() -> None:
    result = peri_scribe.fires.differential.geometry_difference(
        tests.factories.square(2.0),
        tests.factories.square(1.0),
    )
    assert result is not None
    assert result.equals(
        tests.factories.square(2.0).difference(tests.factories.square(1.0)),
    )


def test_geometry_intersection_returns_none_for_missing() -> None:
    assert (
        peri_scribe.fires.differential.geometry_intersection(
            None,
            tests.factories.square(1.0),
        )
        is None
    )
    assert (
        peri_scribe.fires.differential.geometry_intersection(
            tests.factories.square(1.0),
            None,
        )
        is None
    )


def test_geometry_intersection_keeps_shared_area() -> None:
    result = peri_scribe.fires.differential.geometry_intersection(
        tests.factories.square(2.0),
        tests.factories.square(1.5),
    )
    assert result is not None
    assert result.equals(tests.factories.square(1.5))


def test_corrected_geometries_removes_later_reductions() -> None:
    geometries = [
        tests.factories.square(3.0),
        tests.factories.square(2.0),
        tests.factories.square(1.0),
    ]
    corrected = peri_scribe.fires.differential.corrected_geometries(geometries)
    expected = tests.factories.square(1.0)
    assert all(
        geometry is not None and geometry.equals(expected) for geometry in corrected
    )


def test_corrected_geometries_keeps_growth_area() -> None:
    geometries = [
        tests.factories.square(1.0),
        tests.factories.square(2.0),
        tests.factories.square(3.0),
    ]
    corrected = peri_scribe.fires.differential.corrected_geometries(geometries)
    assert all(
        geometry is not None and geometry.equals(expected)
        for geometry, expected in zip(corrected, geometries, strict=True)
    )


def test_corrected_geometries_handles_empty() -> None:
    assert peri_scribe.fires.differential.corrected_geometries([]) == []


def test_growth_indices_keeps_only_growth() -> None:
    corrected = [
        tests.factories.square(1.0),
        tests.factories.square(2.0),
        tests.factories.square(1.5),
    ]
    assert peri_scribe.fires.differential.growth_indices(corrected) == [0, 1]


def test_geometry_grows_beyond_returns_false_for_missing_current() -> None:
    assert not peri_scribe.fires.differential.geometry_grows_beyond(
        None,
        tests.factories.square(1.0),
    )


def test_geometry_grows_beyond_returns_false_for_empty_current() -> None:
    assert not peri_scribe.fires.differential.geometry_grows_beyond(
        shapely.geometry.Polygon(),
        tests.factories.square(1.0),
    )


def test_geometry_grows_beyond_returns_true_without_previous() -> None:
    assert peri_scribe.fires.differential.geometry_grows_beyond(
        tests.factories.square(1.0),
        None,
    )


def test_geometry_grows_beyond_compares_to_previous() -> None:
    assert peri_scribe.fires.differential.geometry_grows_beyond(
        tests.factories.square(2.0),
        tests.factories.square(1.0),
    )
    assert not peri_scribe.fires.differential.geometry_grows_beyond(
        tests.factories.square(1.0),
        tests.factories.square(2.0),
    )


def test_representative_indices_maps_survivors() -> None:
    assert peri_scribe.fires.differential.representative_indices([0, 1, 3], 4) == {
        0: 0,
        1: 2,
        3: 3,
    }


def test_growth_difference_subtracts_most_recent_present() -> None:
    assert peri_scribe.fires.differential.growth_difference(
        150.0,
        [None, 100.0],
    ) == pytest.approx(50.0)


def test_growth_difference_returns_none_when_current_missing() -> None:
    assert peri_scribe.fires.differential.growth_difference(None, [100.0]) is None
    assert (
        peri_scribe.fires.differential.growth_difference(float("nan"), [100.0]) is None
    )


def test_growth_difference_falls_back_to_zero() -> None:
    assert peri_scribe.fires.differential.growth_difference(150.0, []) == pytest.approx(
        150.0,
    )


def test_row_identity_normalizes_missing() -> None:
    row = pd.Series({"fire_name": "Bug", "fire_identifier": float("nan")})
    assert peri_scribe.fires.differential.row_identity(
        row,
        ["fire_name", "fire_identifier"],
    ) == ("Bug", None)


def test_fire_positions_groups_by_identity() -> None:
    rows = [
        {
            "fire_name": "Bug",
            "fire_identifier": float("nan"),
            "fire_aliases": "",
            "complex_name": None,
            "complex_identifier": None,
            "border_classification": "inside_california",
        },
        {
            "fire_name": "Bug",
            "fire_identifier": float("nan"),
            "fire_aliases": "",
            "complex_name": None,
            "complex_identifier": None,
            "border_classification": "inside_california",
        },
        {
            "fire_name": "Bee",
            "fire_identifier": "2026-cacdd-000001",
            "fire_aliases": "2026-cacdd-000001",
            "complex_name": None,
            "complex_identifier": None,
            "border_classification": "inside_california",
        },
    ]
    frame = geopandas.GeoDataFrame(
        rows,
        geometry=[shapely.geometry.Point(0, 0)] * len(rows),
        crs="EPSG:4326",
    )
    assert peri_scribe.fires.differential.fire_positions(frame) == [[0, 1], [2]]


def test_differential_perimeter_dataframe_builds_growth_rows() -> None:
    records = [
        {
            "fire_name": "Bug",
            "fire_identifier": "2026-cacdd-000001",
            "area_acres": 100.0,
            "percent_contained": 10.0,
            "type": "a",
        },
        {
            "fire_name": "Bug",
            "fire_identifier": "2026-cacdd-000001",
            "area_acres": 150.0,
            "percent_contained": 20.0,
            "type": "b",
        },
        {
            "fire_name": "Bug",
            "fire_identifier": "2026-cacdd-000001",
            "area_acres": 140.0,
            "percent_contained": 30.0,
            "type": "c",
        },
    ]
    frame = tests.peri_scribe.fires.differential_helpers.full_perimeter_frame(
        records,
        [
            tests.factories.square(1.0),
            tests.factories.square(2.0),
            tests.factories.square(1.5),
        ],
    )
    output = peri_scribe.fires.differential.differential_perimeter_dataframe(frame)
    assert (
        list(output.columns)
        == peri_scribe.fires.differential.DIFFERENTIAL_PERIMETER_COLUMNS
    )
    assert len(output) == len(records) - 1
    assert output["area_acres_differential"].tolist() == pytest.approx([100.0, 40.0])
    assert output["area_acres"].tolist() == pytest.approx([100.0, 140.0])
    assert output["percent_contained_differential"].tolist() == pytest.approx([
        10.0,
        20.0,
    ])
    assert output["percent_contained"].tolist() == pytest.approx([10.0, 30.0])
    assert output["type"].tolist() == ["a", "c"]
    assert output.geometry.iloc[0].equals(tests.factories.square(1.0))
    assert output.geometry.iloc[1].equals(
        tests.factories.square(1.5).difference(tests.factories.square(1.0)),
    )
    cumulative = output["area_acres_from_geometry"]
    differential = output["area_acres_from_geometry_differential"]
    assert not cumulative.isna().any()
    assert not differential.isna().any()
    assert differential.iloc[0] == pytest.approx(cumulative.iloc[0])
    assert differential.iloc[1] == pytest.approx(
        cumulative.iloc[1] - cumulative.iloc[0],
    )


def test_differential_perimeter_dataframe_back_propagates_null_values() -> None:
    records = [
        {
            "fire_name": "Bug",
            "fire_identifier": "2026-cacdd-000001",
            "area_acres": 100.0,
            "type": "a",
        },
        {
            "fire_name": "Bug",
            "fire_identifier": "2026-cacdd-000001",
            "area_acres": None,
            "type": "b",
        },
        {
            "fire_name": "Bug",
            "fire_identifier": "2026-cacdd-000001",
            "area_acres": 50.0,
            "type": "c",
        },
    ]
    frame = tests.peri_scribe.fires.differential_helpers.full_perimeter_frame(
        records,
        [
            tests.factories.square(1.0),
            tests.factories.square(0.5),
            tests.factories.square(1.5),
        ],
    )
    output = peri_scribe.fires.differential.differential_perimeter_dataframe(frame)
    assert output["area_acres_differential"].isna().tolist() == [True, False]
    assert output["area_acres"].isna().tolist() == [True, False]
    assert output["area_acres_differential"].iloc[1] == pytest.approx(50.0)
    assert output["area_acres"].iloc[1] == pytest.approx(50.0)
    assert output["type"].tolist() == ["b", "c"]


def test_differential_perimeter_dataframe_skips_collapsed_growth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = [
        {
            "fire_name": "Bug",
            "fire_identifier": "2026-cacdd-000001",
            "area_acres": 100.0,
        },
        {
            "fire_name": "Bug",
            "fire_identifier": "2026-cacdd-000001",
            "area_acres": 150.0,
        },
        {
            "fire_name": "Bug",
            "fire_identifier": "2026-cacdd-000001",
            "area_acres": 140.0,
        },
    ]
    frame = tests.peri_scribe.fires.differential_helpers.full_perimeter_frame(
        records,
        [
            tests.factories.square(1.0),
            tests.factories.square(2.0),
            tests.factories.square(1.5),
        ],
    )
    real_difference = peri_scribe.fires.differential.geometry_difference

    collapsing_difference = (
        tests.peri_scribe.fires.differential_helpers.make_collapsing_difference(
            real_difference=real_difference,
        )
    )

    monkeypatch.setattr(
        peri_scribe.fires.differential,
        "geometry_difference",
        collapsing_difference,
    )
    output = peri_scribe.fires.differential.differential_perimeter_dataframe(frame)
    # The second growth step collapses, so it contributes no ring and the area of its
    # empty difference is never measured.
    assert len(output) == 1
    assert output.geometry.iloc[0].equals(tests.factories.square(1.0))


def test_differential_perimeter_dataframe_parallel_matches_single_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame, fire_identifiers = (
        tests.peri_scribe.fires.differential_helpers.multiple_fire_perimeter_frame()
    )
    monkeypatch.setattr(peri_scribe.fires.differential, "DIFFERENTIAL_WORKER_COUNT", 1)
    single_worker = peri_scribe.fires.differential.differential_perimeter_dataframe(
        frame,
    )
    monkeypatch.setattr(peri_scribe.fires.differential, "DIFFERENTIAL_WORKER_COUNT", 4)
    parallel = peri_scribe.fires.differential.differential_perimeter_dataframe(frame)
    assert parallel.equals(single_worker)
    assert parallel["fire_identifier"].tolist() == fire_identifiers


def test_write_history_of_differential_geography_writes_two_layers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    full_path = tmp_path / "derived/history_of_full_geography.gpkg"
    monkeypatch.setattr(
        peri_scribe.fires.files,
        "write_history_of_full_geography",
        lambda _directory, **_kwargs: full_path,
    )
    perimeters = tests.peri_scribe.fires.differential_helpers.full_perimeter_frame(
        [],
        [],
    )
    points = tests.factories.geo_frame(
        {"fire_name": ["Bug"]},
        [shapely.geometry.Point(0, 0)],
    )
    monkeypatch.setattr(
        peri_scribe.geo.reading,
        "read_layer",
        lambda _path, layer_name: (
            perimeters if layer_name == "perimeter_history" else points
        ),
    )
    written: list[tuple[pathlib.Path, list[peri_scribe.models.LayerData]]] = []
    monkeypatch.setattr(
        peri_scribe.fires.reuse,
        "write_layers",
        lambda path, layers: written.append((path, layers)),
    )
    result = peri_scribe.fires.differential.write_history_of_differential_geography(
        tmp_path,
    )
    assert result == tmp_path / "derived/history_of_differential_geography.gpkg"
    assert len(written) == 1
    _path, layers = written[0]
    assert [layer.name for layer in layers] == [
        peri_scribe.fires.files.PERIMETER_LAYER_NAME,
        peri_scribe.fires.files.POINT_LAYER_NAME,
    ]
    assert layers[1].dataframe is points
