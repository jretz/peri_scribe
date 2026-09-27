import pathlib

import numpy as np
import shapely

import spatial_data.point_store
import tests.formal.helpers.oracle
import tests.formal.helpers.spatial_index


def test_tile_id_and_tile_ids_match_lean_every_grid_axis_boundary() -> None:
    cases = tests.formal.helpers.spatial_index.coordinate_boundaries()
    expected = tests.formal.helpers.oracle.evaluate(
        [f"tile {tests.formal.helpers.spatial_index.offset(point)}" for point in cases],
        executable="oracleDomain",
    )
    vectorized = spatial_data.point_store.tile_ids(np.array(cases, dtype="<i4"))
    for point, batch, result in zip(cases, vectorized, expected, strict=True):
        assert spatial_data.point_store.tile_id(*point) == batch == result[0], point


def test_tile_ids_for_box_matches_proved_complete_enumeration() -> None:
    _points, cases = tests.formal.helpers.spatial_index.query_cases()
    expected = tests.formal.helpers.oracle.evaluate(
        [
            f"tiles {tests.formal.helpers.spatial_index.offset((box[0], box[1]))} "
            f"{tests.formal.helpers.spatial_index.offset((box[2], box[3]))}"
            for box in cases
        ],
        executable="oracleDomain",
    )
    for box, result in zip(cases, expected, strict=True):
        assert spatial_data.point_store.tile_ids_for_box(
            tests.formal.helpers.spatial_index.degrees(box),
        ) == list(result), box
        assert len(result) == len(set(result)), box


def test_point_counts_within_matches_lean_tile_bag_counts(
    tmp_path: pathlib.Path,
) -> None:
    points, boxes = tests.formal.helpers.spatial_index.query_cases()
    vectors = " ".join(
        tests.formal.helpers.spatial_index.offset(point) for point in points
    )
    expected = tests.formal.helpers.oracle.evaluate(
        [
            f"count {tests.formal.helpers.spatial_index.offset((box[0], box[1]))} "
            f"{tests.formal.helpers.spatial_index.offset((box[2], box[3]))} {vectors}"
            for box in boxes
        ],
        executable="oracleDomain",
    )
    path = tmp_path / "points.sqlite"
    tests.formal.helpers.spatial_index.database(path, points)
    geometries = [
        shapely.box(*tests.formal.helpers.spatial_index.degrees(box)) for box in boxes
    ]
    assert spatial_data.point_store.point_counts_within(geometries, path) == [
        result[0] for result in expected
    ]
