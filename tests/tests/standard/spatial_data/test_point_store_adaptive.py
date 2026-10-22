import pathlib
import unittest.mock

import numpy as np
import pytest
import shapely

import spatial_data.point_index
import spatial_data.point_store
import tests.helpers.factories.spatial_data.point_store


@pytest.mark.parametrize("repetitions", [1, 8])
def test_point_counts_within_preserves_query_order_multiplicity_and_strict_containment(
    tmp_path: pathlib.Path,
    repetitions: int,
) -> None:
    path = tmp_path / "points.sqlite"
    tests.helpers.factories.spatial_data.point_store.write_database(
        np.array([
            [0.1, 0.1],
            [0.1, 0.1],
            [0.15, 0.15],
            [0.2, 0.1],
            [0.49, 0.1],
            [0.5, 0.1],
            [0.51, 0.1],
            [-0.01, 0.1],
            [0.1, 0.25],
        ]),
        path,
    )
    queries = [
        shapely.box(0.05, 0.05, 0.2, 0.2),
        None,
        shapely.box(0.3, 0.0, 0.6, 0.2),
        shapely.Polygon(),
        shapely.box(-0.5, 0.0, 0.0, 0.2),
        shapely.Polygon(
            shapely.box(0.0, 0.0, 0.4, 0.4).exterior,
            [shapely.box(0.05, 0.05, 0.12, 0.12).exterior],
        ),
    ]
    assert spatial_data.point_store.point_counts_within(
        queries * repetitions,
        path,
    ) == ([3, 0, 3, 0, 1, 3] * repetitions)


def test_point_counts_within_keeps_source_database_byte_identical(
    tmp_path: pathlib.Path,
) -> None:
    path = tmp_path / "points.sqlite"
    tests.helpers.factories.spatial_data.point_store.write_database(
        np.array([[0.2, 0.2], [0.3, 0.3]]),
        path,
    )
    original = path.read_bytes()
    queries = [shapely.box(0.1, 0.1, 0.4, 0.4)] * 12
    spatial_data.point_store.point_counts_within(queries, path)
    assert path.read_bytes() == original


def test_point_counts_within_releases_preparation_after_indexed_containment_failure(
    tmp_path: pathlib.Path,
) -> None:
    path = tmp_path / "points.sqlite"
    tests.helpers.factories.spatial_data.point_store.write_database(
        np.array([[0.2, 0.2]]),
        path,
    )
    geometry = shapely.box(0.1, 0.1, 0.4, 0.4)
    shapely.prepare(geometry)
    with (
        unittest.mock.patch.object(
            shapely,
            "contains_xy",
            side_effect=ValueError("test"),
        ),
        pytest.raises(ValueError, match="test"),
    ):
        spatial_data.point_store.point_counts_within([geometry] * 12, path)
    assert not shapely.is_prepared(geometry)


def test_point_counts_within_builds_one_index_per_busy_tile(
    tmp_path: pathlib.Path,
) -> None:
    path = tmp_path / "points.sqlite"
    tests.helpers.factories.spatial_data.point_store.write_database(
        np.array([[0.2, 0.2], [0.6, 0.2]]),
        path,
    )
    with unittest.mock.patch.object(
        spatial_data.point_index.LongitudeIndex,
        "build",
        wraps=spatial_data.point_index.LongitudeIndex.build,
    ) as build:
        spatial_data.point_store.point_counts_within(
            [shapely.box(0.1, 0.1, 0.3, 0.3)] * 12
            + [shapely.box(0.55, 0.1, 0.65, 0.3)],
            path,
        )
    assert build.call_count == 1
