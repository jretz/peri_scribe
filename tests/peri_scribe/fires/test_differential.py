"""Tests for peri_scribe.fires.differential."""

import pathlib
import typing

import geopandas
import pandas as pd
import pytest
import shapely.geometry

import peri_scribe.fires.differential
import peri_scribe.fires.files
import peri_scribe.geo.reading
import peri_scribe.models
import peri_scribe.output


def square(side: float) -> shapely.geometry.Polygon:
    """Return a square of the given side, centered at the origin.

    Args:
        side: The length of each side.

    Returns:
        The square.
    """
    half = side / 2
    return shapely.geometry.box(-half, -half, half, half)


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


def test_differential_geopackage_path_names_output() -> None:
    assert peri_scribe.fires.differential.differential_geopackage_path(
        pathlib.Path("data/2026"),
    ) == pathlib.Path("data/2026/derived/history_of_differential_geography.gpkg")


def test_polygonal_area_keeps_polygon() -> None:
    geometry = square(1.0)
    assert peri_scribe.fires.differential.polygonal_area(geometry) is geometry


def test_polygonal_area_returns_none_for_missing() -> None:
    assert peri_scribe.fires.differential.polygonal_area(None) is None


def test_polygonal_area_returns_none_for_non_polygonal() -> None:
    line = shapely.geometry.LineString([(0, 0), (1, 1)])
    assert peri_scribe.fires.differential.polygonal_area(line) is None


def test_polygonal_area_extracts_polygons_from_geometry_collection() -> None:
    collection = shapely.geometry.GeometryCollection(
        [
            square(1.0),
            shapely.geometry.LineString([(0, 0), (1, 1)]),
        ],
    )
    result = peri_scribe.fires.differential.polygonal_area(collection)
    assert result is not None
    assert result.equals(square(1.0))


def test_polygonal_area_returns_none_for_line_only_collection() -> None:
    collection = shapely.geometry.GeometryCollection(
        [shapely.geometry.LineString([(0, 0), (1, 1)])],
    )
    assert peri_scribe.fires.differential.polygonal_area(collection) is None


def test_polygonal_area_unions_multiple_polygons() -> None:
    collection = shapely.geometry.GeometryCollection(
        [square(1.0), shapely.geometry.box(2.0, 2.0, 3.0, 3.0)],
    )
    result = peri_scribe.fires.differential.polygonal_area(collection)
    assert result is not None
    assert result.geom_type == "MultiPolygon"


def test_geometry_difference_returns_current_without_previous() -> None:
    geometry = square(1.0)
    result = peri_scribe.fires.differential.geometry_difference(
        geometry,
        None,
    )
    assert result is not None
    assert result.equals(geometry)


def test_geometry_difference_returns_none_for_missing_current() -> None:
    assert peri_scribe.fires.differential.geometry_difference(None, square(1.0)) is None


def test_geometry_difference_subtracts_overlap() -> None:
    result = peri_scribe.fires.differential.geometry_difference(
        square(2.0),
        square(1.0),
    )
    assert result is not None
    assert result.equals(square(2.0).difference(square(1.0)))


def test_geometry_intersection_returns_none_for_missing() -> None:
    assert (
        peri_scribe.fires.differential.geometry_intersection(None, square(1.0)) is None
    )
    assert (
        peri_scribe.fires.differential.geometry_intersection(square(1.0), None) is None
    )


def test_geometry_intersection_keeps_shared_area() -> None:
    result = peri_scribe.fires.differential.geometry_intersection(
        square(2.0),
        square(1.5),
    )
    assert result is not None
    assert result.equals(square(1.5))


def test_corrected_geometries_removes_later_reductions() -> None:
    geometries = [square(3.0), square(2.0), square(1.0)]
    corrected = peri_scribe.fires.differential.corrected_geometries(geometries)
    expected = square(1.0)
    assert all(
        geometry is not None and geometry.equals(expected) for geometry in corrected
    )


def test_corrected_geometries_keeps_growth_area() -> None:
    geometries = [square(1.0), square(2.0), square(3.0)]
    corrected = peri_scribe.fires.differential.corrected_geometries(geometries)
    assert all(
        geometry is not None and geometry.equals(expected)
        for geometry, expected in zip(corrected, geometries, strict=True)
    )


def test_corrected_geometries_handles_empty() -> None:
    assert peri_scribe.fires.differential.corrected_geometries([]) == []


def test_growth_indices_keeps_only_growth() -> None:
    corrected = [square(1.0), square(2.0), square(1.5)]
    assert peri_scribe.fires.differential.growth_indices(corrected) == [0, 1]


def test_geometry_grows_beyond_returns_false_for_missing_current() -> None:
    assert not peri_scribe.fires.differential.geometry_grows_beyond(
        None,
        square(1.0),
    )


def test_geometry_grows_beyond_returns_false_for_empty_current() -> None:
    assert not peri_scribe.fires.differential.geometry_grows_beyond(
        shapely.geometry.Polygon(),
        square(1.0),
    )


def test_geometry_grows_beyond_returns_true_without_previous() -> None:
    assert peri_scribe.fires.differential.geometry_grows_beyond(square(1.0), None)


def test_geometry_grows_beyond_compares_to_previous() -> None:
    assert peri_scribe.fires.differential.geometry_grows_beyond(
        square(2.0),
        square(1.0),
    )
    assert not peri_scribe.fires.differential.geometry_grows_beyond(
        square(1.0),
        square(2.0),
    )


def test_representative_indices_maps_survivors() -> None:
    assert peri_scribe.fires.differential.representative_indices(
        [0, 1, 3],
        4,
    ) == {0: 0, 1: 2, 3: 3}


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
    assert peri_scribe.fires.differential.growth_difference(
        150.0,
        [],
    ) == pytest.approx(150.0)


def test_identity_key_normalizes_missing() -> None:
    row = pd.Series({"fire_name": "Bug", "fire_identifier": float("nan")})
    assert peri_scribe.fires.differential.identity_key(
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
    frame = full_perimeter_frame(
        records,
        [square(1.0), square(2.0), square(1.5)],
    )
    output = peri_scribe.fires.differential.differential_perimeter_dataframe(frame)
    assert (
        list(output.columns)
        == peri_scribe.fires.differential.DIFFERENTIAL_PERIMETER_COLUMNS
    )
    assert len(output) == len(records) - 1
    assert output["area_acres_differential"].tolist() == pytest.approx(
        [100.0, 40.0],
    )
    assert output["area_acres"].tolist() == pytest.approx([100.0, 140.0])
    assert output["percent_contained_differential"].tolist() == pytest.approx(
        [10.0, 20.0],
    )
    assert output["percent_contained"].tolist() == pytest.approx([10.0, 30.0])
    assert output["type"].tolist() == ["a", "c"]
    assert output.geometry.iloc[0].equals(square(1.0))
    assert output.geometry.iloc[1].equals(square(1.5).difference(square(1.0)))
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
    frame = full_perimeter_frame(
        records,
        [square(1.0), square(0.5), square(1.5)],
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
    frame = full_perimeter_frame(
        records,
        [square(1.0), square(2.0), square(1.5)],
    )
    real_difference = peri_scribe.fires.differential.geometry_difference

    def collapsing_difference(
        current: shapely.geometry.base.BaseGeometry | None,
        previous: shapely.geometry.base.BaseGeometry | None,
    ) -> shapely.geometry.base.BaseGeometry | None:
        # A numerically degenerate sliver makes the covers-based growth check report
        # growth whose constructed difference collapses to nothing.
        if previous is not None and previous.equals(square(1.0)):
            return None
        return real_difference(current, previous)

    monkeypatch.setattr(
        peri_scribe.fires.differential,
        "geometry_difference",
        collapsing_difference,
    )
    output = peri_scribe.fires.differential.differential_perimeter_dataframe(frame)
    # The second growth step collapses, so it contributes no ring and the area of its
    # empty difference is never measured.
    assert len(output) == 1
    assert output.geometry.iloc[0].equals(square(1.0))


def test_write_history_of_differential_geography_writes_two_layers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    full_path = pathlib.Path("data/2026/derived/history_of_full_geography.gpkg")
    monkeypatch.setattr(
        peri_scribe.fires.files,
        "write_history_of_full_geography",
        lambda _directory: full_path,
    )
    perimeters = full_perimeter_frame([], [])
    points = geopandas.GeoDataFrame(
        {"fire_name": ["Bug"]},
        geometry=[shapely.geometry.Point(0, 0)],
        crs="EPSG:4326",
    )
    monkeypatch.setattr(
        peri_scribe.geo.reading,
        "read_layer",
        lambda _path, layer_name: (
            perimeters if layer_name == "perimeter_history" else points
        ),
    )
    monkeypatch.setattr(
        pathlib.Path,
        "mkdir",
        lambda *_arguments, **_keywords: None,
    )
    written: list[tuple[pathlib.Path, list[peri_scribe.models.LayerData]]] = []
    monkeypatch.setattr(
        peri_scribe.output,
        "write_geopackage",
        lambda path, layers: written.append((path, layers)),
    )
    result = peri_scribe.fires.differential.write_history_of_differential_geography(
        pathlib.Path("data/2026"),
    )
    assert result == pathlib.Path(
        "data/2026/derived/history_of_differential_geography.gpkg",
    )
    assert len(written) == 1
    _path, layers = written[0]
    assert [layer.name for layer in layers] == [
        peri_scribe.fires.files.PERIMETER_LAYER_NAME,
        peri_scribe.fires.files.POINT_LAYER_NAME,
    ]
    assert layers[1].dataframe is points
